"""The entry point for the bot's logic.

Mainly just loads all other cogs and syncs the
command tree when the bot is ready.
"""

import logging
import pkgutil
from pathlib import Path
from discord.ext import commands


# The list of cogs to load.
_COGS = ('status_updater',)

# Extensions live in their own gitignored repos under 'extensions/'.
# Every package in there is loaded as 'extensions.<name>' and must
# expose an async 'setup(bot)' hook, the same as a cog in 'cog/'.
_EXTENSIONS_DIR = Path(__file__).resolve().parent.parent / 'extensions'


class Bot(commands.Cog):
    """A class to handle general bot things.

    Attributes:
        bot: The bot to add this cog to.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self._bot = bot

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Sets up the bot when it is ready to do so."""

        # Load all other cogs after the bot is ready.
        for cog in _COGS:
            await self._bot.load_extension(f'cog.{cog}')

        # Load extensions after the core cogs. A broken extension is
        # logged and skipped so it can't take the status updater down.
        for ext in pkgutil.iter_modules([str(_EXTENSIONS_DIR)]):
            try:
                await self._bot.load_extension(f'extensions.{ext.name}')
            except commands.ExtensionError:
                logging.getLogger('voice-channel-status').exception(
                    f"Failed to load extension '{ext.name}'")

        # Sync the command tree to all guilds.
        await self._bot.tree.sync()

        # Log that the bot is ready.
        ready_msg = f'{self._bot.user} is ready!'
        print(ready_msg)
        print('-' * len(ready_msg))


async def setup(bot: commands.Bot) -> None:
    """A hook for the bot to register the Bot cog.

    Args:
        bot: The bot to add this cog to.
    """

    await bot.add_cog(Bot(bot))
