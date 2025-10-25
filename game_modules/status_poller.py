from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Awaitable, Callable, Dict, Iterable, List, Optional

from discord.ext import commands
import aiohttp

# fetch_func must accept a list[str] and return Dict[str, List[str]]
FetchFunc = Callable[[logging.Logger, List[str]], Awaitable[Dict[str, List[str]]]]

class RateLimitError(Exception):
    """Optional: a fetcher can raise this to signal backoff without leaking HTTP deps."""
    def __init__(self, retry_after_seconds: Optional[float] = None, message: str = "Rate limited"):
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class GenericPlayerPoller:
    """
    Generic API polling system.
    - cache: Dict[str, List[str]]
    - poll_ids: Dict[channel_id, List[str]]
    - Handles 429 rate limits in the poller (custom RateLimitError or aiohttp 429).
    """

    poll_ids: Dict[int, List[str]]
    cache: Dict[str, List[str]]
    last_update_time: datetime

    def __init__(
        self,
        logger: logging.Logger,
        bot: commands.Bot,
        fetch_func: FetchFunc,
        *,
        poll_interval_seconds: float = 60.0,
        stale_timeout: timedelta = timedelta(minutes=15),
        batch_size: int = 100,
        max_retries: int = 3,
        base_retry_backoff_seconds: float = 2.0,
    ):
        self._log = logger
        self._bot = bot
        self._fetch = fetch_func

        self.poll_ids = {}
        self.cache = {}
        self.last_update_time = datetime.min

        self._poll_interval = poll_interval_seconds
        self._stale_timeout = stale_timeout
        self._batch_size = max(1, batch_size)
        self._max_retries = max(0, max_retries)
        self._base_backoff = max(0.1, base_retry_backoff_seconds)

        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()

    # ---------------- Public API ----------------

    def set_poll(self, channel_id: int, external_ids: Iterable[str]) -> None:
        """Replace the list of ids to poll for a channel."""
        self.poll_ids[channel_id] = list(external_ids)

    def add_to_poll(self, channel_id: int, external_ids: Iterable[str]) -> None:
        """Append ids to a channel's poll list."""
        cur = self.poll_ids.get(channel_id, [])
        cur.extend(list(external_ids))
        self.poll_ids[channel_id] = cur

    def remove_channel(self, channel_id: int) -> None:
        self.poll_ids.pop(channel_id, None)

    def clear_cache(self) -> None:
        self.cache.clear()
        self.last_update_time = datetime.min

    def get_player_values(self, external_id: Optional[str]) -> Optional[List[str]]:
        if external_id is None:
            return None
        return self.cache.get(external_id)

    # ---------------- Background lifecycle ----------------

    async def start_background_task(self) -> None:
        await self._bot.wait_until_ready()
        if self._task is None or self._task.done():
            self._stop_event.clear()
            self._task = asyncio.create_task(self._run_loop(), name="GenericPlayerPollerLoop")

    async def stop_background_task(self) -> None:
        self._stop_event.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=self._poll_interval + 5)
            except asyncio.TimeoutError:
                self._log.warning("GenericPlayerPoller loop did not stop in time; cancelling.")
                self._task.cancel()
            finally:
                self._task = None

    # ---------------- Core loop & polling ----------------

    async def _run_loop(self) -> None:
        self._log.debug("GenericPlayerPoller background task started")
        try:
            while not self._stop_event.is_set() and not self._bot.is_closed():
                await self._poll_once_with_backoff()
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self._poll_interval)
                except asyncio.TimeoutError:
                    pass
        finally:
            self._log.warning("GenericPlayerPoller background task stopped")

    async def _poll_once_with_backoff(self) -> None:
        retries = 0
        while True:
            try:
                await self.poll()
                return

            except RateLimitError as rl:
                # Custom error path: respect retry-after if provided
                now = datetime.now()
                since = now - self.last_update_time
                if since > self._stale_timeout:
                    self._log.warning("Rate limit + stale cache (%s). Clearing cache.", since)
                    self.clear_cache()

                delay = rl.retry_after_seconds if rl.retry_after_seconds is not None else (self._base_backoff * (2 ** retries))
                delay = min(delay, 60.0)
                self._log.debug("Rate limited (custom); retrying in %.2fs (attempt %d/%d).", delay, retries + 1, self._max_retries)
                await asyncio.sleep(delay)

            except aiohttp.ClientResponseError as cre:
                # Generic HTTP path: handle direct 429 from fetcher without custom exception
                if cre.status == 429:
                    now = datetime.now()
                    since = now - self.last_update_time
                    if since > self._stale_timeout:
                        self._log.warning("429 + stale cache (%s). Clearing cache.", since)
                        self.clear_cache()

                    # Try to parse Retry-After header if the fetcher surfaced it
                    retry_after = None
                    try:
                        if hasattr(cre, "headers") and cre.headers is not None:
                            ra = cre.headers.get("Retry-After")
                            retry_after = float(ra) if ra is not None else None
                    except Exception:
                        retry_after = None

                    delay = retry_after if retry_after is not None else (self._base_backoff * (2 ** retries))
                    delay = min(delay, 60.0)
                    self._log.debug("429 received; retrying in %.2fs (attempt %d/%d).", delay, retries + 1, self._max_retries)
                    await asyncio.sleep(delay)
                else:
                    # Non-429 HTTP error: retry a few times then bail
                    if retries >= self._max_retries:
                        self._log.error("Poll failed after retries (HTTP %s).", cre.status, exc_info=cre)
                        return
                    delay = min(self._base_backoff * (2 ** retries), 30.0)
                    self._log.warning("HTTP %s error. Retrying in %.2fs (attempt %d/%d).", cre.status, delay, retries + 1, self._max_retries)
                    await asyncio.sleep(delay)

            except asyncio.CancelledError:
                raise

            except Exception as e:
                if retries >= self._max_retries:
                    self._log.error("Poll failed after retries; keeping old cache.", exc_info=e)
                    return
                delay = min(self._base_backoff * (2 ** retries), 30.0)
                self._log.warning("Poll error (%s). Retrying in %.2fs (attempt %d/%d).", type(e).__name__, delay, retries + 1, self._max_retries)
                await asyncio.sleep(delay)

            retries += 1
            if retries > self._max_retries:
                return

    async def poll(self) -> None:
        """
        One poll cycle:
        - If no ids, clear cache and return.
        - Otherwise batch over the exact list and replace cache on success.
        """
        # Flatten lists exactly as provided (duplicates allowed)
        all_ids: List[str] = []
        for ids in self.poll_ids.values():
            all_ids.extend(ids)

        if not all_ids:
            if self.cache:
                self._log.debug("No ids to poll; clearing cache")
            self.clear_cache()
            return

        new_cache: Dict[str, List[str]] = {}
        # Batch on raw list (duplicates stay; your fetcher should handle them or the API will ignore them)
        batches = [all_ids[i:i + self._batch_size] for i in range(0, len(all_ids), self._batch_size)]

        for batch in batches:
            batch_map = await self._fetch(self._log, batch)  # may raise RateLimitError or aiohttp.ClientResponseError(429)
            for k, v in batch_map.items():
                if v is None:
                    continue
                new_cache[k] = list(v)

        # Commit snapshot on success
        self.cache = new_cache
        self.last_update_time = datetime.now()
        self._log.debug("Poll successful; cache size=%d; polled_ids=%d", len(self.cache), len(all_ids))
