import asyncio
import json
from discord import VoiceChannel
from discord import app_commands
import discord
from discord.ext import commands
import util
import logging
from typing_extensions import NotRequired
from typing import TypedDict, Dict, Literal
import os
import sys

from cog.get_icon import IconList

CONFIG_FILE = "config.json"

class ChannelData(TypedDict):
	active: bool
	current_message: str | None

class EmojiData(TypedDict):
	emoji: str
	display_name: NotRequired[str]

class GuildData(TypedDict):
	channels: Dict[str, ChannelData]
	emojis: Dict[str, EmojiData]

class ConfigFile(TypedDict):
	guilds: Dict[str, GuildData]

class GameInfo:
	emoji: str | None
	count: int
	name: str

class Config():
	"""Allows configuration of the bot via commands. Stored to disk."""
	_data: ConfigFile

	def __init__(self, logger: logging.Logger):
		self.log = logger
		self._load()

	def _load(self):
		"""Loads the config json from disk."""
		try:
			with open(CONFIG_FILE, "r") as f:
				self._data = json.load(f)
		except (json.decoder.JSONDecodeError, FileNotFoundError):
			self._data = ConfigFile(guilds={})
			self.save()

	def save(self):
		"""Saves the config to disk."""
		with open(CONFIG_FILE, "w") as f:
			json.dump(self._data, f, indent=2)

	def get_guild(self, guild: int) -> GuildData:
		"""Gets a config value."""
		if str(guild) not in self._data["guilds"]:
			self._data["guilds"][str(guild)] = GuildData(channels={}, emojis={})
		return self._data["guilds"][str(guild)]

	def get_channel(self, guild: int, channel: int) -> ChannelData:
		"""Gets a config value."""
		guild_data = self.get_guild(guild)
		if str(channel) not in guild_data["channels"]:
			guild_data["channels"][str(channel)] = ChannelData(active=True, current_message="")
		return guild_data["channels"][str(channel)]

	def prune(self, guild: int, voice_channels: list[VoiceChannel]):
		"""Removes any config entries for voice channels that no longer exist."""
		guild_data = self.get_guild(guild)
		voice_channel_ids = set(str(vc.id) for vc in voice_channels)
		keys_to_remove = [key for key in guild_data["channels"].keys() if key not in voice_channel_ids]
		for key in keys_to_remove:
			self.log.info("Removing config for voice channel that no longer exists")
			guild_data["channels"].pop(key)
		return bool(keys_to_remove)

def find_alias(emojis: dict[str, GameInfo], emoji: str):
	for game, data in emojis.items():
		if emoji == data.emoji:
			return game, data

def calculate_game_info(members: list[discord.Member], emojis: dict[str, EmojiData]) -> list[GameInfo]:
	games = [activity.name for member in members for activity in member.activities if (activity.type == discord.ActivityType.playing or activity.type == discord.ActivityType.streaming) and activity.name]
	if not games:
		return []
	game_info: dict[str, GameInfo] = {}
	for game in set(games):
		info = GameInfo()
		info.name = game
		info.count = 1
		info.emoji = None
		if game in game_info:
			info = game_info[game]
			info.count += 1
		config = None
		if game in emojis:
			config = emojis[game]
		if config is not None:
			if "display_name" in config and config["display_name"] is not None:
				info.name = config["display_name"]
			info.emoji = config["emoji"]
			temp = find_alias(game_info, config["emoji"])
			if temp is not None:
				game, alias = temp
				if "display_name" in config and config["display_name"] is not None:
					alias.name = config["display_name"]
				info = alias
				info.count += 1
		game_info[game] = info
	games_count = [info for game, info in game_info.items()]
	games_count.sort(key=lambda x: x.count, reverse=True)
	return games_count

class StatusUpdater(commands.Cog):

	def __init__(self, bot: commands.Bot) -> None:
		self._bot = bot
		self.log = util.setup_logging()
		self.config = Config(self.log)
		self._bot.loop.create_task(self.background_task())
		self.icon_list = IconList(self.log) # load last

	@app_commands.command(name='toggle', description="Toggle Voice Status updates for this channel")
	async def toggle(
        self,
        interaction: discord.Interaction
    ) -> None:
		self.log.info(f"User '{interaction.user.name}' ran /toggle command for channel '{getattr(interaction.channel, 'name', None)}'")
		guild = interaction.guild
		channel = interaction.channel
		# Check if this is a voice channel
		if guild is None or channel is None or not isinstance(channel, VoiceChannel) or interaction.channel_id not in [vc.id for vc in guild.voice_channels]:
			await interaction.response.send_message("This is not a voice channel", ephemeral=True)
			return
		config = self.config.get_channel(guild.id, interaction.channel_id)
		config["active"] = not config["active"]
		if config["active"]:
			message = "Enabled Voice Status updates for this channel"
		else:
			message = "Disabled Voice Status updates for this channel"
			config["current_message"] = None
		self.config.save()
		await interaction.response.send_message(message, ephemeral=True)
		self.log.info(f"{message} '{channel.name}'")

	@app_commands.command(name='update', description="Force an update of the Voice Status")
	async def update(self, interaction: discord.Interaction) -> None:
		self.log.info(f"User '{interaction.user.name}' ran /update command for channel '{getattr(interaction.channel, 'name', None)}'")
		guild = interaction.guild
		channel = interaction.channel
		# Check if this is a voice channel
		if guild is None or channel is None or not isinstance(channel, VoiceChannel) or interaction.channel_id not in [vc.id for vc in guild.voice_channels]:
			await interaction.response.send_message("This is not a voice channel", ephemeral=True)
			return
		self.config.get_channel(guild.id, interaction.channel_id)["current_message"] = None
		await self.update_vc_status(guild, interaction.channel_id, True)
		await interaction.response.send_message("Updated Voice Status", ephemeral=True)

	@app_commands.command(name='debug', description="Debug the current voice channel status")
	async def debug(self, interaction: discord.Interaction) -> None:
		self.log.info(f"User '{interaction.user.name}' ran /debug command for channel '{getattr(interaction.channel, 'name', None)}'")
		guild = interaction.guild
		if guild is None or interaction.channel_id is None:
			await interaction.response.send_message("This is not a guild", ephemeral=True)
			return
		channel = guild.get_channel(interaction.channel_id)
		if channel is None or not isinstance(channel, VoiceChannel) or interaction.channel_id not in [vc.id for vc in guild.voice_channels]:
			await interaction.response.send_message("This is not a voice channel", ephemeral=True)
			return
		guild_config = self.config.get_guild(guild.id)
		config = self.config.get_channel(guild.id, interaction.channel_id)
		members = channel.members
		activities = [(member.name, activity.name) for member in members for activity in member.activities]
		games_count = calculate_game_info(members, guild_config["emojis"])
		tracked = [(info.name, info.count) for info in games_count]
		message = f"All activities: {activities}\nTracked games: {tracked}\nConfig: {config}"
		self.log.info(message)
		await interaction.response.send_message(message, ephemeral=True)

	@app_commands.command(name='emoji', description="Add or Remove an emoji to your current game")
	@app_commands.describe(
        action="Whether to add or remove an emoji",
        emoji="The emoji to add (ignored if removing)",
        display_name="Override the game name with a custom display name",
        target_user="The user whose game you want to target (defaults to you if omitted)"
    )
	async def emoji(
		self,
		interaction: discord.Interaction,
		action: Literal["add", "remove"],
		emoji: str | None,
		display_name: str | None,
		target_user: discord.User | None
	) -> None:
		"""Adds or removes an emoji for a user's currently active game."""
		self.log.info(f"User '{interaction.user.name}' ran /emoji command for channel '{getattr(interaction.channel, 'name', None)}'")
		guild = interaction.guild
		# Check if this is a voice channel
		if guild is None:
			await interaction.response.send_message("Must be run in the server where the emoji is to be added", ephemeral=True)
			return
		if target_user is None:
			member = guild.get_member(interaction.user.id)
		else:
			member = guild.get_member(target_user.id)
		if member is None:
			await interaction.response.send_message("Failed to get user data", ephemeral=True)
			return
		config = self.config.get_guild(guild.id)
		tracked_games = [activity.name for activity in member.activities if activity.type == discord.ActivityType.playing or activity.type == discord.ActivityType.streaming]
		if not tracked_games or len(tracked_games) < 1 or tracked_games[0] is None:
			await interaction.response.send_message("You are not playing any games.", ephemeral=True)
			return
		game = tracked_games[0]
		if len(tracked_games) > 1:
			await interaction.response.send_message("You are playing multiple games. Aborting..", ephemeral=True)
			return
		if action == "remove":
			if game not in config["emojis"]:
				await interaction.response.send_message(f"You have not added an emoji for this game. {game}", ephemeral=True)
				return
			emoji = config["emojis"].pop(game)["emoji"]
			await interaction.response.send_message(f"Removed emoji {emoji} for game {game}")
			self.log.info(f"Removed emoji {emoji} for game {game}")
		elif action == "add":
			if emoji is None or emoji.strip() == "" or " " in emoji:
				await interaction.response.send_message("Invalid emoji", ephemeral=True)
				return
			emoji_obj: EmojiData = { 'emoji': emoji }
			if display_name is not None:
				emoji_obj['display_name'] = display_name
			config["emojis"][game] = emoji_obj
			await interaction.response.send_message(f"Added emoji {emoji} for game {game}")
			self.log.info(f"Added emoji {emoji} for game {game}")
		self.config.save()

	@app_commands.command(name='get_icon', description="Get the link to your current game's icon if it exists")
	@app_commands.describe(
        target_user="The user whose game you want to target (defaults to you if omitted)"
    )
	async def get_icon(self, interaction: discord.Interaction, target_user: discord.User | None) -> None:
		self.log.info(f"User '{interaction.user.name}' ran /get_icon command for channel '{getattr(interaction.channel, 'name', None)}'")
		guild = interaction.guild
		if guild is None:
			await interaction.response.send_message("Must be run in a server to fetch activity data from user", ephemeral=True)
			return
		if target_user is None:
			member = guild.get_member(interaction.user.id)
		else:
			member = guild.get_member(target_user.id)
		if member is None:
			await interaction.response.send_message("Failed to get user data", ephemeral=True)
			return
		tracked_games = [activity for activity in member.activities if activity.type == discord.ActivityType.playing]
		if not tracked_games or len(tracked_games) < 1 or tracked_games[0] is None:
			await interaction.response.send_message("User is not playing any games.", ephemeral=True)
			return
		game = tracked_games[0]
		if not isinstance(game, (discord.Activity, discord.Game)):
			await interaction.response.send_message("Unable to get game url for this user.", ephemeral=True)
			return
		icon_url = self.icon_list.get_game_image(game)
		if icon_url is None:
			await interaction.response.send_message("Unable to get game url for this game.", ephemeral=True)
			return
		await interaction.response.send_message(icon_url, ephemeral=True)

	@app_commands.command(name='reload', description="Restart the bot cause it broke")
	async def reload(self, interaction: discord.Interaction) -> None:
		self.log.warning(f"User '{interaction.user.name}' ran /reload command for channel '{getattr(interaction.channel, 'name', None)}'")
		await interaction.response.send_message("Reloading...")
		os.execv(sys.executable, ['python'] + sys.argv)

	async def background_task(self):
		await self._bot.wait_until_ready()
		while not self._bot.is_closed():
			for guild in self._bot.guilds:
				await self.update_vc_status(guild)
			await asyncio.sleep(10)

	async def update_vc_status(self, guild: discord.Guild, id: int | None = None, force = False):
		"""Updates the voice chat status based on the game members are playing."""
		config_changed = False

		if id is not None:
			channel = guild.get_channel(id)
			if channel is None or not isinstance(channel, VoiceChannel):
				return
			voice_channels = [channel]
		else:
			voice_channels = guild.voice_channels

		for voice_channel in voice_channels:
			# get config for this voice channel
			guild_config = self.config.get_guild(guild.id)
			emojis = guild_config["emojis"]
			channel_config = self.config.get_channel(guild.id, voice_channel.id)

			if not channel_config["active"] and not force:
				continue

			skip_api = False

			# get all members in the voice channel
			members = voice_channel.members
			if not members:
				skip_api = True

			games_count = calculate_game_info(members, emojis)

			message = ""
			if games_count:
				emoji_games = [info for info in games_count if info.emoji]

				if len(games_count) == 1:
					info = games_count[0]
					if info.emoji is not None:
						message = f"{info.emoji} "
					message = f"{message}{info.name}"
				else:
					# If there is more games only show the emojis
					message = " ".join([f"{info.emoji}" for info in games_count if info.emoji is not None])
					# if one emoji, include the game name
					if len(emoji_games) == 1:
						message = message + f" {emoji_games[0].name}"
					# if no emojis, show a default message
					if not message:
						message = f"Playing {len(games_count)} games"

			# Check cache for changes
			if channel_config["current_message"] == message:
				continue
			channel_config["current_message"] = message
			config_changed = True

			if games_count:
				self.log.info([(info.name, info.count) for info in games_count])

			if not skip_api:
				self.log.info(f"Setting status of '{voice_channel.name}' to '{message}'")
				success, response = await util.set_status(voice_channel, message)
				if not success:
					self.log.error(f"Failed to update voice channel status for '{voice_channel.name}' with status code '{response.status_code}'\n {response}")
			else:
				self.log.info(f"Setting cached status of '{voice_channel.name}' to '{message}'")

		if config_changed:
			self.config.prune(guild.id, voice_channels)
			self.config.save()

# https://discord.com/oauth2/authorize?client_id=1151102788420501507&permissions=281477124194320&scope=bot

async def setup(bot: commands.Bot) -> None:
    """A hook for the bot to register the Status Updater cog.

    Args:
        bot: The bot to add this cog to.
    """

    await bot.add_cog(StatusUpdater(bot))

