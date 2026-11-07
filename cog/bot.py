"""The entry point for the bot's logic.

Mainly just loads all other cogs and syncs the
command tree when the bot is ready.
"""

import logging
import pkgutil
import time
from pathlib import Path
import discord
from discord import app_commands
from discord.ext import commands
import util


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
        self._default_on_error = bot.tree.on_error
        bot.tree.error(self._on_app_command_error)
        bot.tree.interaction_check = self._received

    async def _received(self, interaction: discord.Interaction) -> bool:
        """Runs before every slash command, ahead of its checks: notes when it arrived, so its log line can
        say how long it took (see util.command_summary)."""
        interaction.extras['received'] = time.perf_counter()
        return True

    async def _on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        """Logs a command that didn't finish, and tells the user when a check stopped them running it
        (e.g. util.admins_only). Other errors are logged as usual too."""
        log = logging.getLogger('voice-channel-status')
        if not isinstance(error, app_commands.CheckFailure):
            log.error(f"{util.command_summary(interaction)}, but it failed")
            await self._default_on_error(interaction, error)
            return
        log.warning(f"{util.command_summary(interaction)}, but was refused: {error}")
        send = interaction.followup.send if interaction.response.is_done() else interaction.response.send_message
        await send(str(error), ephemeral=util.ephemeral(interaction))

    @commands.Cog.listener()
    async def on_app_command_completion(self, interaction: discord.Interaction, command: app_commands.Command) -> None:
        """Logs every slash command that finishes, the core cogs' and extensions' alike, with how long it took."""
        logging.getLogger('voice-channel-status').info(util.command_summary(interaction))

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
