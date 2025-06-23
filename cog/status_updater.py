import asyncio
import json
import subprocess
import time
from discord import VoiceChannel
from discord import app_commands
import discord
from discord.ext import commands
from cog.steam_status import SteamPlayerSummaries
import util
import logging
from typing_extensions import NotRequired
from typing import TypedDict, Dict, Literal, Callable, Awaitable
import os
import sys
import re
from datetime import datetime

from cog.get_icon import IconList

CONFIG_FILE = "config.json"
UPDATE_INTERVAL = 10
SLEEP_THRESHOLD = 15
DEFAULT_EMOJI_CREATE_LIMIT = 10

class ChannelData(TypedDict):
	active: bool
	name: str | None
	current_message: str | None

class GameData(TypedDict):
	emoji: NotRequired[str]
	display_name: NotRequired[str]
	ignore: NotRequired[bool]

class EmojiData(TypedDict):
	id: int # snowflake
	name: str
	emoji: str # The emoji string, e.g. "<:emoji_name:123456789012345678>"
	created_at: str # ISO 8601 format
	times_used: int # How many times the emoji has been used
	last_used: NotRequired[str] # ISO 8601 format, when the emoji was last used

class MemberData(TypedDict):
	steam_id: NotRequired[str]

class GuildData(TypedDict):
	channels: Dict[str, ChannelData]
	games: Dict[str, GameData]
	members: Dict[str, MemberData]
	emojis: Dict[str, EmojiData]
	emoji_create_limit: int # Limit for how many emojis can be created by the bot in this guild

class ConfigFile(TypedDict):
	guilds: Dict[str, GuildData]

class GameInfo:
	emoji: str | None
	count: int
	name: str
	activity: discord.Activity | discord.Game | str

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
		except (FileNotFoundError):
			self._data = ConfigFile(guilds={})
			self.save()

	def save(self):
		"""Saves the config to disk."""
		with open(CONFIG_FILE, "w") as f:
			json.dump(self._data, f, indent=2)

	def get_guild(self, guild: int) -> GuildData:
		"""Gets a config value."""
		if str(guild) not in self._data["guilds"]:
			self._data["guilds"][str(guild)] = GuildData(channels={}, games={}, members={}, emojis={}, emoji_create_limit=DEFAULT_EMOJI_CREATE_LIMIT)
		return self._data["guilds"][str(guild)]

	def get_channel(self, guild: int, channel: int) -> ChannelData:
		"""Gets a config value."""
		guild_data = self.get_guild(guild)
		if str(channel) not in guild_data["channels"]:
			guild_data["channels"][str(channel)] = ChannelData(active=True, current_message="", name=None)
		return guild_data["channels"][str(channel)]

	def get_member(self, guild: int, member: int) -> MemberData:
		"""Gets a config value."""
		guild_data = self.get_guild(guild)
		if str(member) not in guild_data["members"]:
			guild_data["members"][str(member)] = MemberData()
		return guild_data["members"][str(member)]

	def set_emoji(self, guild_data: GuildData, emoji: discord.Emoji) -> EmojiData:
		"""Gets a config value for an emoji."""
		if emoji.name not in guild_data["emojis"]:
			guild_data["emojis"][emoji.name] = EmojiData(id=emoji.id, name=emoji.name, emoji=str(emoji), created_at=datetime.now().isoformat(), times_used=0)
		return guild_data["emojis"][emoji.name]

	def prune(self, guild: int, voice_channels: list[VoiceChannel]):
		"""Removes any unused config entries."""
		guild_data = self.get_guild(guild)
		voice_channel_ids = set(str(vc.id) for vc in voice_channels)
		keys_to_remove = [key for key in guild_data["channels"].keys() if key not in voice_channel_ids]
		for key in keys_to_remove:
			self.log.info("Removing config for voice channel that no longer exists")
			guild_data["channels"].pop(key)
		# prune members with no data (all fields None or empty)
		keys_to_remove = [key for key, data in guild_data["members"].items() if all(not value for value in data.values())]
		for key in keys_to_remove:
			self.log.info(f"Removing member with no data: {guild_data['members'][key]}")
			guild_data["members"].pop(key)
		# prune emojis with no data (all fields None or empty)
		keys_to_remove = [key for key, data in guild_data["emojis"].items() if all(not value for value in data.values())]
		for key in keys_to_remove:
			self.log.info(f"Removing emoji with no data: {guild_data['emojis'][key]}")
			guild_data["emojis"].pop(key)
		return bool(keys_to_remove)

def find_alias(emojis: dict[str, GameInfo], emoji: str):
	for game, data in emojis.items():
		if emoji == data.emoji:
			return game, data

class StatusUpdater(commands.Cog):

	def __init__(self, bot: commands.Bot) -> None:
		self._bot = bot
		self.log = util.setup_logging()
		self.config = Config(self.log)
		self.steam_status = SteamPlayerSummaries(self.log, bot)
		self._bot.loop.create_task(self.background_task())
		self._bot.loop.create_task(self.steam_status.background_task())
		self.icon_list = None  # Will be initialized in setup

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
		activities = [(member.name, activity if isinstance(activity, str) else str(activity.name)) for member in members for activity in self.get_tracked_games(member, guild_config)]
		games_count = self.calculate_game_info(members, guild_config)
		tracked = [(info.name, info.count) for info in games_count]
		message = f"All activities: {activities}\nTracked games: {tracked}\nConfig: {config}"
		self.log.info(message)
		await interaction.response.send_message(message, ephemeral=True)

	@app_commands.command(name='emoji', description="Edit config for the game, usually to add an emoji")
	@app_commands.describe(
        action="Whether to add or remove an emoji",
        emoji="The emoji to add (ignored if removing)",
        display_name="Override the game name with a custom display name",
        target_user="@Mention the user whose game you want to target (defaults to you if omitted)"
    )
	async def emoji(
		self,
		interaction: discord.Interaction,
		action: Literal["add", "remove", "ignore"],
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
		tracked_games = self.get_tracked_games(member, config)
		if not tracked_games or len(tracked_games) < 1 or tracked_games[0] is None:
			await interaction.response.send_message("You are not playing any games.", ephemeral=True)
			return
		game = tracked_games[0]
		if len(tracked_games) > 1:
			await interaction.response.send_message("You are playing multiple games. Aborting..", ephemeral=True)
			return
		game_name = game if isinstance(game, str) else str(game.name)
		game_config: GameData | None = config["games"].get(game_name, None)
		if action == "remove":
			if game_config is None or "emoji" not in game_config:
				await interaction.response.send_message(f"You have not added an emoji for this game. {game_name}", ephemeral=True)
				return
			emoji = game_config.pop("emoji", None)
			await interaction.response.send_message(f"Removed emoji {emoji} for game {game_name}")
			self.log.info(f"Removed emoji {emoji} for game {game_name}")
		elif action == "add":
			emoji = emoji.strip() if emoji is not None and emoji.strip() != "" and " " not in emoji else None
			maybe_defer, send_message = self.make_defer_callback(interaction)
			if emoji is None and display_name is None:
				emoji = await self.upload_emoji(guild, game, maybe_defer)
				if emoji is None:
					await send_message(f"Invalid input ({emoji}, {display_name})", ephemeral=True)
					return
			if game_config is None:
				game_config = GameData()
				config["games"][game_name] = game_config
			if emoji is not None:
				game_config["emoji"] = emoji
			if game_config.get("emoji") is not None:
				config["emojis"].pop(game_name, None)  # Remove emoji from auto emoji list
			if display_name is not None:
				game_config['display_name'] = display_name
			await send_message(f"Added emoji {emoji} for game {game_name}", ephemeral=True)
			self.log.info(f"Added emoji {emoji} for game {game_name}")
		elif action == "ignore":
			if game_config is None:
				game_config = GameData()
				config["games"][game_name] = game_config
			config["games"][game_name]["ignore"] = not config["games"][game_name].get("ignore", False)
			await interaction.response.send_message(f"{'Ignored' if config['games'][game_name]['ignore'] else 'Unignored'} game {game_name}", ephemeral=True)
			self.log.info(f"{'Ignored' if config['games'][game_name]['ignore'] else 'Unignored'} game {game_name}")
		self.config.save()

	@app_commands.command(name='config', description="Edit config for this guild")
	@app_commands.describe(
		key="The key to edit",
		value="The value to set the key to",
		target_user="@Mention the user who you want to target (defaults to you if omitted)"
	)
	async def edit_config(
		self,
		interaction: discord.Interaction,
		key: Literal["steam_id"],
		value: str | None,
		target_user: discord.User | None
	) -> None:
		"""Adds or removes config values for a user."""
		self.log.info(f"User '{interaction.user.name}' ran /config command for channel '{getattr(interaction.channel, 'name', None)}'")
		guild = interaction.guild
		# Check if this is a voice channel
		if guild is None:
			await interaction.response.send_message("Must be run in the server where the config is to be added", ephemeral=True)
			return
		member = interaction.user
		if target_user is not None:
			member = target_user
		if member is None:
			await interaction.response.send_message("Failed to get user data", ephemeral=True)
			return
		if key == "steam_id":
			member_config = self.config.get_member(guild.id, member.id)
			if value is None:
				member_config.pop("steam_id", None)
			else:
				member_config["steam_id"] = value
			await interaction.response.send_message(f"Set steam_id to {value} for {member.name}", ephemeral=True)
		self.config.prune(guild.id, guild.voice_channels)
		self.config.save()

	@app_commands.command(name='get_icon', description="Get the link to your current game's icon if it exists")
	@app_commands.describe(
        target_user="@Mention the user whose game you want to target (defaults to you if omitted)",
		source="The service to pick the icon from (defaults to first available if omitted)"
    )
	async def get_icon(self, interaction: discord.Interaction, target_user: discord.User | None, source: Literal["discord", "steam"] | None) -> None:
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
		tracked_games = self.get_game_info(member, self.config.get_guild(guild.id))
		if not tracked_games or len(tracked_games) < 1 or tracked_games[0] is None:
			await interaction.response.send_message("User is not playing any games.", ephemeral=True)
			return
		game = tracked_games[0]
		if self.icon_list is None:
			await interaction.response.send_message("Icon list not initialized yet. Please try again in a moment.", ephemeral=True)
			return
		maybe_defer, send_message = self.make_defer_callback(interaction)
		icon_url = await self.icon_list.get_game_image(game, source, maybe_defer)
		if icon_url is None:
			await send_message("Unable to get game url for this game.", ephemeral=True)
			return
		await send_message(icon_url, ephemeral=True)

	@staticmethod
	def make_defer_callback(interaction: discord.Interaction) -> tuple[Callable[[], Awaitable[None]], Callable[..., Awaitable[None]]]:
		"""
		Returns:
		- `maybe_defer`: an async function to defer the interaction only once
		- `send`: the correct send function (response.send_message or followup.send) based on defer status
		"""
		deferred = False

		async def maybe_defer():
			nonlocal deferred
			if not deferred:
				await interaction.response.defer(thinking=True, ephemeral=True)
				deferred = True

		async def send(*args, **kwargs):
			if deferred:
				return await interaction.followup.send(*args, **kwargs)
			else:
				return await interaction.response.send_message(*args, **kwargs)

		return maybe_defer, send

	@app_commands.command(name='reload', description="Restart the bot cause it broke")
	async def reload(self, interaction: discord.Interaction) -> None:
		self.log.warning(f"User '{interaction.user.name}' ran /reload command for channel '{getattr(interaction.channel, 'name', None)}'")
		await interaction.response.send_message("Reloading...", ephemeral=True)
		os.execv(sys.executable, ['python'] + sys.argv)

	async def upload_emoji(
		self,
		guild: discord.Guild,
		activity: discord.Activity | discord.Game | str,
		on_slow_callback: Callable[[], Awaitable[None]] | None = None
	) -> str | None:
		"""Uploads an emoji for the given activity and returns the emoji name."""
		if self.icon_list is None:
			self.log.warning("Icon list not initialized yet. Unable to upload emoji.")
			return None
		guild_config = self.config.get_guild(guild.id)
		activity_name = activity if isinstance(activity, str) else str(activity.name)
		game_config = guild_config["games"].get(activity_name, None)
		emoji_name = re.sub(r'[^a-zA-Z0-9]', '', activity_name.lower()) # Remove non-alphanumeric characters

		if game_config is not None:
			self.log.warning(f"Game config for {activity_name} already exists")
			return game_config.get("emoji", None)
		if emoji_name in guild_config["emojis"]:
			self.log.warning(f"Emoji {emoji_name} already exists in guild config for {activity_name}")
			return guild_config["emojis"][emoji_name]["emoji"]

		image_data = await self.icon_list.fetch_game_image(activity, None, on_slow_callback)
		if image_data is None:
			self.log.warning(f"Failed to fetch image for activity {activity_name}. Cannot upload emoji.")
			return None

		# check if server has reached emoji create limit
		if len(guild_config["emojis"]) >= guild_config["emoji_create_limit"]:
			# LRU remove the least recently used emoji
			emoji_to_remove = min(guild_config["emojis"].values(), key=lambda e: datetime.fromisoformat(e.get("last_used", e["created_at"])))
			self.log.info(f"Guild {guild.name} has reached emoji create limit of {guild_config['emoji_create_limit']}. Removing least recently used emoji <{emoji_to_remove.name}:{emoji_to_remove}> to make space.")
			await guild.delete_emoji(discord.Emoji(id=emoji_to_remove["id"], name=emoji_to_remove["name"], guild=guild), 
				f"Removing bot managed emoji to make space for {activity_name}, last used at {emoji_to_remove.get('last_used', None)}, created at {emoji_to_remove['created_at']}, times used {emoji_to_remove['times_used']}")
			guild_config["emojis"].pop(emoji_to_remove["name"], None)
			# Remove all the games that contain this emoji from the game config
			for game_name, game_config in guild_config["games"].items():
				if game_config.get("emoji") == emoji_to_remove["emoji"]:
					self.log.info(f"Removing game {game_name} from config because it used the removed emoji {emoji_to_remove['emoji']}, config: {game_config}")
					guild_config["games"].pop(game_name, None)

		emoji_obj = await guild.create_custom_emoji(name=emoji_name, image=image_data)
		self.log.info(f"Uploaded emoji {str(emoji_obj)} for game {activity_name}")

		self.config.set_emoji(guild_config, emoji_obj) # Ensure the emoji is in the config
		# add emoji to game config
		game_config = GameData()
		game_config["emoji"] = str(emoji_obj)
		guild_config["games"][activity_name] = game_config

		self.config.save()
		return str(emoji_obj)

	def get_game_info(self, member: discord.Member, config: GuildData) -> list[discord.Activity | discord.Game]:
		games: list[discord.Activity | discord.Game] = []
		for activity in member.activities:
			if isinstance(activity, (discord.Activity, discord.Game)):
				games.append(activity)
		if games:
			return games
		member_config = config["members"].get(str(member.id), {})
		steam_id = member_config.get("steam_id", None)
		steam_profile = self.steam_status.get_player_summary(steam_id)
		return [discord.Game(steam_profile.game_name)] if steam_profile is not None and steam_profile.game_name is not None else []

	def get_tracked_games(self, member: discord.Member, config: GuildData) -> list[discord.Activity | discord.Game | str]:
		discord_games: list[discord.Activity | discord.Game | str] = [activity for activity in member.activities if isinstance(activity, discord.Activity | discord.Game) and activity.name]
		if discord_games:
			return discord_games
		member_config = config["members"].get(str(member.id), {})
		steam_id = member_config.get("steam_id", None)
		steam_profile = self.steam_status.get_player_summary(steam_id)
		steam_games: list[discord.Activity | discord.Game | str] = [steam_profile.game_name] if steam_profile is not None and steam_profile.game_name is not None else []
		return steam_games

	def all_tracked_games(self, members: list[discord.Member], config: GuildData) -> list[discord.Activity | discord.Game | str]:
		return [game for member in members for game in self.get_tracked_games(member, config)]

	def calculate_game_info(self, members: list[discord.Member], config: GuildData) -> list[GameInfo]:
		games = self.all_tracked_games(members, config)
		if not games:
			return []
		game_info: dict[str, GameInfo] = {}
		for game in games:
			game_name = game if isinstance(game, str) else str(game.name)
			if game_name in game_info:
				info = game_info[game_name]
				info.count += 1
				continue
			info = GameInfo()
			info.name = game_name
			info.count = 1
			info.emoji = None
			info.activity = game
			game_config = None
			if game_name in config["games"]:
				game_config = config["games"][game_name]
			if game_config is not None:
				if "ignore" in game_config and game_config["ignore"]:
					continue
				if "display_name" in game_config and game_config["display_name"] is not None:
					info.name = game_config["display_name"]
				info.emoji = game_config["emoji"]
				temp = find_alias(game_info, game_config["emoji"])
				if temp is not None:
					game_name, alias = temp
					if "display_name" in game_config and game_config["display_name"] is not None:
						alias.name = game_config["display_name"]
					info = alias
					info.count += 1
					if isinstance(info.activity, str):
						info.activity = game
			game_info[game_name] = info
		games_count = list(game_info.values())
		games_count.sort(key=lambda x: x.count, reverse=True)
		return games_count

	def get_steam_ids(self, members: list[discord.Member], guild_config: GuildData) -> list[str]:
		"""Extracts steam IDs from the guild configuration for the given members."""
		# member could not exist
		steam_ids = [guild_config["members"].get(str(member.id), {}).get("steam_id", None) for member in members]
		return [steam_id for steam_id in steam_ids if steam_id is not None]

	async def background_task(self):
		await self._bot.wait_until_ready()
		last_timestamp = time.time()
		while not self._bot.is_closed():
			for guild in self._bot.guilds:
				await self.update_vc_status(guild)
			await asyncio.sleep(UPDATE_INTERVAL)

			current_timestamp = time.time()
			if (current_timestamp - last_timestamp) > UPDATE_INTERVAL + SLEEP_THRESHOLD:
				self.log.warning("System likely went to sleep and then resumed!, Reloading...")
				subprocess.Popen([sys.executable] + sys.argv)
				os._exit(0)
			last_timestamp = current_timestamp

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

		needed_emojis: dict[str, discord.Activity | discord.Game | str] = {}
		for voice_channel in voice_channels:
			# get config for this voice channel
			guild_config = self.config.get_guild(guild.id)
			channel_config = self.config.get_channel(guild.id, voice_channel.id)
			channel_config["name"] = voice_channel.name

			if not channel_config["active"] and not force:
				continue

			skip_api = False

			# get all members in the voice channel
			members = voice_channel.members
			if not members:
				skip_api = True

			# add any members to be tracked by steam filter None values
			steam_ids = self.get_steam_ids(members, guild_config)
			self.steam_status.set_poll(voice_channel.id, steam_ids)

			games_count = self.calculate_game_info(members, guild_config)

			message = ""
			if games_count:
				emoji_games = [info for info in games_count if info.emoji]

				# Check emoji config exists and update the emoji usage count
				for info in games_count:
					emoji_name = re.sub(r'[^a-zA-Z0-9]', '', info.name.lower())
					if info.emoji:
						emoji_data = guild_config["emojis"].get(emoji_name, None)
						if emoji_data is not None:
							emoji_data["times_used"] += info.count
							emoji_data["last_used"] = datetime.now().isoformat()
					else:
						needed_emojis[emoji_name] = info.activity

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
					self.log.error(f"Failed to update voice channel status for '{voice_channel.name}' with status code '{response.status}'\n {response}")
			else:
				self.log.info(f"Setting cached status of '{voice_channel.name}' to '{message}'")

		if needed_emojis:
			self.log.info(f"Adding emojis for games: {', '.join(needed_emojis.keys())}")
			for activity in needed_emojis.values():
				await self.upload_emoji(guild, activity)

		if config_changed:
			self.config.prune(guild.id, guild.voice_channels)
			self.config.save()

	async def setup(self):
		"""Async setup method to initialize async components."""
		self.icon_list = await IconList.create(self.log)

# https://discord.com/oauth2/authorize?client_id=1151102788420501507&permissions=281477124194320&scope=bot

async def setup(bot: commands.Bot) -> None:
    """A hook for the bot to register the Status Updater cog.

    Args:
        bot: The bot to add this cog to.
    """
    cog = StatusUpdater(bot)
    await cog.setup()  # Initialize async components
    await bot.add_cog(cog)

