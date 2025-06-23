"""Contains functions that are useful throughout the program."""

import os
import discord
import aiohttp
import logging
import asyncio
from PIL import Image, ImageSequence
from io import BytesIO

async def wait_for_connection(url: str = "https://www.google.com", max_retries: int = 15, retry_delay: float = 3.0) -> bool:
    """Wait for a connection to be available.

    Args:
        url: The URL to check for connection
        max_retries: Maximum number of retries before giving up
        retry_delay: Delay between retries in seconds

    Returns:
        bool: True if connection is successful, False otherwise
    """
    for attempt in range(max_retries):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as response:
                    if response.status == 200:
                        return True
        except Exception as e:
            if attempt < max_retries - 1:
                logging.debug(f"Connection attempt {attempt + 1} failed: {e}")
                await asyncio.sleep(retry_delay)
            else:
                logging.error(f"Failed to connect after {max_retries} attempts: {e}")
                return False
    return False

async def get_nth_msg(
    channel: discord.TextChannel | discord.Thread,
    n: int
) -> discord.Message:
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
async def set_status(channel: discord.VoiceChannel, message: str) -> tuple[bool, aiohttp.ClientResponse]:
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

    async with aiohttp.ClientSession() as session:
        async with session.put(url, headers=headers, json=data) as response:
            return response.status == 204, response

async def check_resource_exists(url: str | None) -> bool:
    if not url:
        return False
    async with aiohttp.ClientSession() as session:
        async with session.head(url) as response:
            return response.status == 200

def setup_logging() -> logging.Logger:
    level = logging.INFO
    if os.getenv('DEBUG') == '1':
        level = logging.DEBUG

    terminal = logging.StreamHandler()
    log_file = logging.FileHandler('output.log', encoding='utf-8')

    setup_handler(terminal)
    setup_handler(log_file)

    logger = logging.getLogger('voice-channel-status')

    # Remove all old handlers
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
        handler.close()

    logger.setLevel(level)
    logger.addHandler(terminal)
    logger.addHandler(log_file)

    return logger

def setup_handler(handler):
    if isinstance(handler, logging.StreamHandler) and discord.utils.stream_supports_colour(handler.stream):
        formatter = discord.utils._ColourFormatter()
    else:
        dt_fmt = '%Y-%m-%d %H:%M:%S'
        formatter = logging.Formatter('[{asctime}] [{levelname:<8}] {name}: {message}', dt_fmt, style='{')

    handler.setFormatter(formatter)

def convert_ico_to_png(ico_bytes: bytes) -> bytes:
    with Image.open(BytesIO(ico_bytes)) as img:
        img = img.convert("RGBA")
        largest_frame = max(
            (frame.copy() for frame in ImageSequence.Iterator(img)),
            key=lambda f: f.size[0] * f.size[1],
            default=img
        )
        buf = BytesIO()
        largest_frame.save(buf, format="PNG")
        return buf.getvalue()

def get_img_type(image_data: bytes) -> str | None:
    try:
        with Image.open(BytesIO(image_data)) as img:
            return img.format.lower()
    except Exception:
        return None