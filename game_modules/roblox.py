import aiohttp
import logging
from typing import Dict, List
from datetime import timedelta
from game_modules.status_poller import GenericPlayerPoller

async def fetch_roblox_status(log: logging.Logger, ids: List[str]) -> Dict[str, List[str]]:
    """
    Fetch Roblox presence for a list of user IDs.
    Returns {user_id: ["Roblox"]} if they are in-game (userPresenceType == 2),
    otherwise {user_id: []}.
    """
    if not ids:
        return {}

    url = "https://presence.roblox.com/v1/presence/users"
    payload = {"userIds": [int(i) for i in ids]}

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload) as resp:
            # raise_for_status() lets GenericPlayerPoller handle 429 & retries
            resp.raise_for_status()
            data = await resp.json()

    result: Dict[str, List[str]] = {}

    for user in data.get("userPresences", []):
        user_id = str(user.get("userId"))
        presence_type = user.get("userPresenceType", 0)
        result[user_id] = ["Roblox"] if presence_type == 2 else []

    return result


def create_roblox_poller(bot, log: logging.Logger) -> GenericPlayerPoller:
    """
    Create and configure a Roblox player poller using the generic player poller system.
    """
    poller = GenericPlayerPoller(
        logger=log,
        bot=bot,
        fetch_func=fetch_roblox_status,
        poll_interval_seconds=60,      # poll every minute
        stale_timeout=timedelta(minutes=15),
        batch_size=100,
        max_retries=3,
        base_retry_backoff_seconds=2.0,
    )

    log.info("RobloxPlayerPoller initialized and ready.")
    return poller
