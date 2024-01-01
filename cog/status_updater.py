import asyncio
import pickle
from discord import VoiceChannel
from discord import app_commands
import discord
from discord.ext import commands
import util
import logging

# map of games to emojis, not finalised names
GAME_EMOJIS = {
	"Overwatch 2": "<:overwatch:853544867116744734>",
	"Baldur's Gate 3": "<:bg3:1151420728957227038>",
	"BattleBit Remastered": "<:battlebitremastered:966875064437981224>",
	"Yu-Gi-Oh!  Master Duel": "<:ygomasterduel:1188332980867977269>",
	"THE FINALS": "<:thefinals:1169070694131306599>",
	"Arma III": "<:arma3:853543185091788800>",
	"Apex Legends": "<:apexlegends:853543185178820608>",
	"Destiny 2": "<:destiny2:853543185074094121>",
	"Valorant": "<:valorant:853542233000640542>",
	"Rainbow Six Siege": "<:rainbow6:853541705223766027>",
	"Stellaris": "<:stellaris:1170568267614670930>",
	"Warframe": "<:warframe:1188300388470902845>",
	"Factorio": "<:factorio:1188365073790554132>",
	"Minecraft": "<:minecraft:853544867132211230>",
	"RimWorld": "<:rimworld:1189051920845897798>",
	"Kerbal Space Program 2": "<:ksp2:1189052270747324477>",
	"Genshin Impact": "<:genshin:1191258304836554894>",
}

CONFIG_FILE = "config.pkl"

class Data():
	def __init__(self):
		self.active = True
		self.current_message = ""

class Config():
	"""Allows configuration of the bot via commands. Stored to disk."""

	def __init__(self, logger: logging.Logger):
		self.log = logger
		self._load()

	def _load(self):
		"""Loads the config pickle from disk."""
		try:
			with open(CONFIG_FILE, "rb") as f:
				self._data = pickle.load(f)
		except FileNotFoundError:
			self._data = {}

	def save(self):
		"""Saves the config to disk."""
		with open(CONFIG_FILE, "wb") as f:
			pickle.dump(self._data, f)

	def get(self, key) -> Data:
		"""Gets a config value."""
		if key not in self._data:
			self._data[key] = Data()
		return self._data.get(key)

	def prune(self, voice_channels: list[VoiceChannel]):
		"""Removes any config entries for voice channels that no longer exist."""
		voice_channel_ids = set(vc.id for vc in voice_channels)
		keys_to_remove = [key for key in self._data if key not in voice_channel_ids]
		for key in keys_to_remove:
			self.log.info("Removing config for voice channel that no longer exists")
			self._data.pop(key)
		return bool(keys_to_remove)

class StatusUpdater(commands.Cog):

	def __init__(self, bot: commands.Bot) -> None:
		self._bot = bot
		self._guild = bot.guilds[0]
		self.log = util.setup_logging()
		self.config = Config(self.log)
		self._bot.loop.create_task(self.background_task())

	@app_commands.command(name='toggle', description="Toggle Voice Status updates for this channel")
	async def toggle(
        self,
        interaction: discord.Interaction
    ) -> None:
		self.log.info(f"User '{interaction.user.name}' ran /toggle command for channel '{getattr(interaction.channel, 'name', None)}'")
		# Check if this is a voice channel
		if interaction.channel_id not in [vc.id for vc in self._guild.voice_channels]:
			await interaction.response.send_message("This is not a voice channel", ephemeral=True)
			return
		config = self.config.get(interaction.channel_id)
		config.active = not config.active
		if config.active:
			message = "Enabled Voice Status updates for this channel"
		else:
			message = "Disabled Voice Status updates for this channel"
			config.current_message = None
		self.config.save()
		await interaction.response.send_message(message, ephemeral=True)
		self.log.info(f"{message} '{interaction.channel.name}'")

	@app_commands.command(name='update', description="Force an update of the Voice Status")
	async def update(self, interaction: discord.Interaction) -> None:
		self.log.info(f"User '{interaction.user.name}' ran /update command for channel '{getattr(interaction.channel, 'name', None)}'")
		# Check if this is a voice channel
		if interaction.channel_id not in [vc.id for vc in self._guild.voice_channels]:
			await interaction.response.send_message("This is not a voice channel", ephemeral=True)
			return
		# force a cache update for each member in the channel
		for member in interaction.channel.members:
			await self._guild.fetch_member(member.id)
		self.config.get(interaction.channel_id).current_message = None
		await self.update_vc_status(interaction.channel_id, True)
		await interaction.response.send_message("Updated Voice Status", ephemeral=True)

	@app_commands.command(name='debug', description="Debug the current voice channel status")
	async def debug(self, interaction: discord.Interaction) -> None:
		self.log.info(f"User '{interaction.user.name}' ran /debug command for channel '{getattr(interaction.channel, 'name', None)}'")
		# Check if this is a voice channel
		if interaction.channel_id not in [vc.id for vc in self._guild.voice_channels]:
			await interaction.response.send_message("This is not a voice channel", ephemeral=True)
			return
		channel = self._guild.get_channel(interaction.channel_id)
		config = self.config.get(interaction.channel_id)
		members = channel.members
		activities = [(member.name, activity) for member in members for activity in member.activities]
		games = [activity.name for member in members for activity in member.activities if activity.type == discord.ActivityType.playing or activity.type == discord.ActivityType.streaming]
		games_count = [(game, games.count(game)) for game in set(games)]
		games_count.sort(key=lambda x: x[1], reverse=True)
		message = f"All activities: {activities}\nTracked games: {games_count}\nConfig: {config.__dict__}"
		await interaction.response.send_message(message, ephemeral=True)

	async def background_task(self):
		await self._bot.wait_until_ready()
		while not self._bot.is_closed():
			await self.update_vc_status()
			await asyncio.sleep(5)

	async def update_vc_status(self, id=None, force=False):
		"""Updates the voice chat status based on the game members are playing."""
		config_changed = False

		if id is not None:
			voice_channels = [self._guild.get_channel(id)]
		else:
			voice_channels = self._guild.voice_channels

		for voice_channel in voice_channels:
			# get config for this voice channel
			config = self.config.get(voice_channel.id)

			if not config.active and not force:
				continue

			skip_api = False

			# get all members in the voice channel
			members = voice_channel.members
			if not members:
				skip_api = True

			# add all games a user is playing to the list (not sure if a user can have more than one)
			games = [activity.name for member in members for activity in member.activities if activity.type == discord.ActivityType.playing or activity.type == discord.ActivityType.streaming]

			message = ""
			games_count = []
			if games:
				games_count = [(game, games.count(game)) for game in set(games)]
				games_count.sort(key=lambda x: x[1], reverse=True)

				emoji_games = [game for game, count in games_count if game in GAME_EMOJIS]

				if games_count:
					if len(games_count) == 1:
						game = games_count[0][0]
						count = games_count[0][1]
						if game in GAME_EMOJIS:
							message = f"{GAME_EMOJIS[game]} "
						message = f"{message}{game}"
					else:
						# If there is more games only show the emojis
						message = " ".join([f"{GAME_EMOJIS[game]}" for game, count in games_count if game in GAME_EMOJIS])
						# if one emoji, include the game name
						if len(emoji_games) == 1:
							message = message + f" {emoji_games[0]}"
						# if no emojis, show a default message
						if not message:
							message = f"Playing {len(games_count)} games"

			# Check cache for changes
			if config.current_message == message:
				continue
			config.current_message = message
			config_changed = True

			self.log.info(games_count)

			if not skip_api:
				self.log.info(f"Setting status of '{voice_channel.name}' to '{message}'")
				success, response = await util.set_status(voice_channel, message)
				if not success:
					self.log.error(f"Failed to update voice channel status for '{voice_channel.name}' with status code '{response.status_code}'\n {response}")
			else:
				self.log.info(f"Setting cached status of '{voice_channel.name}' to '{message}'")

		if config_changed:
			self.config.prune(voice_channels)
			self.config.save()

# https://discord.com/oauth2/authorize?client_id=1151102788420501507&permissions=281477124194320&scope=bot

async def setup(bot: commands.Bot) -> None:
    """A hook for the bot to register the Status Updater cog.

    Args:
        bot: The bot to add this cog to.
    """

    await bot.add_cog(StatusUpdater(bot))

