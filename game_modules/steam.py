import os
import aiohttp
from typing import Dict, List
from dto.player_summary import PlayerSummary
from game_modules.status_poller import GenericPlayerPoller
from datetime import timedelta
import logging

def create_steam_poller(bot, log: logging.Logger) -> GenericPlayerPoller:
    """
    Create and configure a Steam player poller using the generic player poller system.
    """

    poller = GenericPlayerPoller(
        logger=log,
        bot=bot,
        fetch_func=fetch_steam_summaries,
        poll_interval_seconds=60,      # how often to poll Steam
        stale_timeout=timedelta(minutes=15),
        batch_size=100,
        max_retries=3,
        base_retry_backoff_seconds=2.0,
    )

    log.info("SteamPlayerPoller initialized and ready.")
    return poller

async def fetch_steam_summaries(log: logging.Logger, ids: List[str]) -> Dict[str, List[str]]:
    """
    Fetch player summaries using the official Steam Web API and convert each
    response entry into a PlayerSummary object, then back into a generic
    list[str] for the poller's cache.
    """
    if not ids:
        return {}

    url = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
    params = {
        "key": os.getenv("STEAM_KEY", ""),
        "steamids": ",".join(ids),
    }

    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            # 429 and other HTTP error codes — handled by poller.
            resp.raise_for_status()
            data = await resp.json()

    players = data.get("response", {}).get("players", [])
    result: Dict[str, List[str]] = {}

    for player_data in players:
        try:
            summary = PlayerSummary(player_data)
        except KeyError as e:
            continue

        result[summary.steam_id] = [summary.game_name] if summary.game_name else []

    return result
