from typing import Literal, Callable, Awaitable
import util
import discord
import aiohttp
import logging
import os
import subprocess
import re
import shutil
import json

CLIENT_ICON_REGEX = re.compile(r'^\s*"clienticon"\s+"([^"]+)"\s*$', re.MULTILINE)

STEAM_APP_LIST_URL = "https://api.steampowered.com/IStoreService/GetAppList/v1/"
STEAM_APP_LIST_CACHE = "cache/steam_app_list.json"
STEAM_APP_LIST_PAGE_SIZE = 50000

class IconList:
	log: logging.Logger
	app_list: list
	steam_app_list: list

	async def get_game_image(
		self,
		activity: discord.Activity | discord.Game | str,
		source: Literal["discord", "steam"] | None,
		on_slow_callback: Callable[[], Awaitable[None]] | None = None
	) -> str | None:
		if self.is_discord_source(source) and hasattr(activity, 'large_image_url') and activity.large_image_url is not None:
			return activity.large_image_url
		if self.is_discord_source(source) and hasattr(activity, 'small_image_url') and activity.small_image_url is not None:
			return activity.small_image_url
		if self.is_discord_source(source) and hasattr(activity, 'application_id'):
			app_id = str(activity.application_id)
			discord_app = list(filter(lambda app: app['id'] == app_id, self.app_list))
			if discord_app:
				rpc = await self.fetch_rpc(app_id)
				self.log.info("FOUND discord app by application_id = %s, rpc = %s", discord_app, rpc)
				if 'icon' in rpc and rpc['icon']:
					return f"https://cdn.discordapp.com/app-icons/{app_id}/{rpc['icon']}.png"
		activity_name = activity if isinstance(activity, str) else str(activity.name)
		# A demo falls back to the main game's icon so both share one emoji
		for name in dict.fromkeys([activity_name, util.base_game_name(activity_name)]):
			discord_app_by_name = self.find_discord_app_by_name(name)
			if self.is_discord_source(source) and discord_app_by_name:
				app_id = discord_app_by_name['id']
				rpc = await self.fetch_rpc(app_id)
				self.log.info("FOUND discord app by name = %s, rpc = %s", discord_app_by_name, rpc)
				if 'icon' in rpc and rpc['icon']:
					return f"https://cdn.discordapp.com/app-icons/{app_id}/{rpc['icon']}.png"
			if self.is_steam_source(source):
				image_url = await self.get_steam_icon(name, on_slow_callback)
				if image_url:
					return image_url
		return None

	async def get_steam_icon(
		self,
		activity_name: str,
		on_slow_callback: Callable[[], Awaitable[None]] | None = None
	) -> str | None:
		steam_app_by_name = list(filter(lambda steam_app: steam_app['name'] == activity_name, self.steam_app_list))
		if steam_app_by_name:
			steam_app_id = str(steam_app_by_name[0]["appid"])
			self.log.info("FOUND Steam app by name = %s", steam_app_by_name[0])
			steamcmd_path = shutil.which("steamcmd")
			if steamcmd_path:
				if on_slow_callback:
					await on_slow_callback()
				self.log.info(f"Fetching Steam icon for app_id = {steam_app_id} via steamcmd, this may take a few seconds...")
				cmd = [
        			'steamcmd',
        			'+login', 'anonymous',
        			'+app_info_print', steam_app_id,
        			'+quit'
    			]
				process = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
				output = process.stdout.decode('utf-8', errors='replace')
				match = CLIENT_ICON_REGEX.search(output)
				if match:
					icon_hash = match.group(1)
					return f"https://cdn.cloudflare.steamstatic.com/steamcommunity/public/images/apps/{steam_app_id}/{icon_hash}.ico"
			else:
				game_image_logo = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{steam_app_id}/logo.png"
				if await util.check_resource_exists(game_image_logo):
					return game_image_logo
				game_image_logo = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{steam_app_id}/logo.jpg"
				if await util.check_resource_exists(game_image_logo):
					return game_image_logo
		return None

	async def fetch_game_image(
		self,
		activity: discord.Activity | discord.Game | str,
		source: Literal["discord", "steam"] | None,
		on_slow_callback: Callable[[], Awaitable[None]] | None = None
	) -> bytes | None:
		"""Fetch the game image for a given activity as a file, checking Discord and Steam sources."""
		url = await self.get_game_image(activity, source, on_slow_callback)
		if not url:
			return None
		async with aiohttp.ClientSession() as session:
			async with session.get(url) as response:
				if response.status != 200:
					raise ValueError("Failed to fetch image: ", url, response)
				image_data = await response.read()

		# Auto-convert ICO files to PNG
		if util.get_img_type(image_data) == "ico":
			self.log.info("Converting ICO image to PNG")
			image_data = util.convert_ico_to_png(image_data)

		return image_data

	def find_discord_app_by_name(self, target_name: str) -> dict | None:
		"""Return the first Discord app from app_list that matches target_name using discord_name_matcher."""
		for app in self.app_list:
			if self.discord_name_matcher(app, target_name):
				return app
		return None

	@staticmethod
	def discord_name_matcher(app, target_name: str) -> bool:
		if app['name'] == target_name:
			return True
		if 'aliases' in app and isinstance(app['aliases'], list):
			return any(alias == target_name for alias in app['aliases'])
		return False

	@staticmethod
	def is_discord_source(source: Literal["discord", "steam"] | None):
		return source is None or source == "discord"

	@staticmethod
	def is_steam_source(source: Literal["discord", "steam"] | None):
		return source is None or source == "steam"

	def __init__(self, logger: logging.Logger):
		self.log = logger
		self.app_list = []
		self.steam_app_list = []

	@classmethod
	async def create(cls, logger: logging.Logger) -> 'IconList':
		"""Async factory method to create and initialize an IconList instance."""
		self = cls(logger)
		await self.load_discord_application_list()
		await self.load_steam_application_list()
		return self

	async def load_discord_application_list(self):
		async with aiohttp.ClientSession() as session:
			self.log.info("Loading Discord detectable applications")
			async with session.get("https://discord.com/api/v10/applications/detectable") as response:
				self.app_list = await response.json()
			self.log.info("Loading Discord detectable applications finished")

	async def load_steam_application_list(self):
		self.log.info("Loading Steam detectable applications")
		try:
			self.steam_app_list = await self.fetch_steam_application_list()
			# save to file /cache/steam_app_list.json
			with open(STEAM_APP_LIST_CACHE, "w", encoding="utf-8") as f:
				json.dump(self.steam_app_list, f)
		except Exception as e:
			self.log.error("Failed to load Steam app list: %s", e)
			# try to load from file /cache/steam_app_list.json
			try:
				with open(STEAM_APP_LIST_CACHE, "r", encoding="utf-8") as f:
					self.steam_app_list = json.load(f)
			except Exception as cache_error:
				self.log.error("Failed to load cached Steam app list: %s", cache_error)
				self.steam_app_list = []
		self.log.info("Loading Steam detectable applications finished, %s apps", len(self.steam_app_list))

	async def fetch_steam_application_list(self) -> list:
		"""Fetch the full Steam app list, paging through IStoreService until it reports no more results."""
		apps = []
		last_appid = 0
		async with aiohttp.ClientSession() as session:
			while True:
				params = {
					"key": os.getenv("STEAM_KEY", ""),
					"include_games": "true",
					"max_results": str(STEAM_APP_LIST_PAGE_SIZE),
				}
				if last_appid:
					params["last_appid"] = str(last_appid)
				async with session.get(STEAM_APP_LIST_URL, params=params) as response:
					if response.status != 200:
						raise ValueError(f"Steam app list request failed, status code: {response.status}")
					page = (await response.json()).get('response', {})
				apps.extend(page.get('apps', []))
				if not page.get('have_more_results'):
					return apps
				next_appid = page.get('last_appid')
				if not next_appid or next_appid == last_appid:
					self.log.warning("Steam app list pagination stalled after appid %s", last_appid)
					return apps
				last_appid = next_appid

	@staticmethod
	async def fetch_rpc(id: str) -> dict:
		async with aiohttp.ClientSession() as session:
			async with session.get(f"https://discord.com/api/v10/applications/{id}/rpc") as response:
				return await response.json()