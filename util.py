"""Contains functions that are useful throughout the program."""

import os
import discord
import requests

async def get_nth_msg(
    channel: discord.TextChannel | discord.Thread,
    n: int
) -> None:
    """Get the nth message in a text channel or thread.

    Args:
        channel: The text channel or thread.
        n: The nth message to get.
    """

    return [
        msg async for msg in channel.history(
            limit=n,
            oldest_first=True
        )
    ][n - 1]

VOICE_STATUS_URL = "https://discord.com/api/v10/channels/:channelId/voice-status"
async def set_status(channel: discord.VoiceChannel, message: str) -> None:
    """Sets the status of a voice channel.

    Args:
        channel: The voice channel to set the status of.
        message: The message to set the status to.
    """

    url = VOICE_STATUS_URL.replace(":channelId", str(channel.id))

    headers = {
        'Content-Type': 'application/json',
        "Authorization": f"Bot {os.getenv('DISCORD_TOKEN')}",
        "x-super-properties": os.getenv('X_SUPER_PROPERTIES')
    }

    data = {
        "status": message
    }

    response = requests.put(url, headers=headers, json=data)

    return response.status_code == 204
