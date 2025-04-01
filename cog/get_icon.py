from typing import Literal
import util
import discord
import aiohttp
import logging

class IconList:
	log: logging.Logger
	app_list: list
	steam_app_list: list

	async def get_game_image(self, activity: discord.Activity | discord.Game, source: Literal["discord", "steam"] | None) -> str | None:
		if self.is_discord_source(source) and hasattr(activity, 'large_image_url') and activity.large_image_url is not None:
			return activity.large_image_url
		if self.is_discord_source(source) and hasattr(activity, 'small_image_url') and activity.small_image_url is not None:
			return activity.small_image_url
		if self.is_discord_source(source) and hasattr(activity, 'application_id'):
			app_id = str(activity.application_id)
			discord_app = list(filter(lambda app: app['id'] == app_id, self.app_list))
			if discord_app:
				rpc = await self.fetch_rpc(app_id)
				self.log.debug("FOUND discord app by application_id = %s, rpc = %s", discord_app, rpc)
				return f"https://cdn.discordapp.com/app-icons/{app_id}/{rpc['icon']}.png"
		activity_name = str(activity.name)
		discord_app_by_name = self.find_discord_app_by_name(activity_name)
		if self.is_discord_source(source) and discord_app_by_name:
			app_id = discord_app_by_name['id']
			rpc = await self.fetch_rpc(app_id)
			self.log.debug("FOUND discord app by name = %s, rpc = %s", discord_app_by_name, rpc)
			return f"https://cdn.discordapp.com/app-icons/{app_id}/{rpc['icon']}.png"
		steam_app_by_name = list(filter(lambda steam_app: steam_app['name'] == activity_name, self.steam_app_list))
		if self.is_steam_source(source) and steam_app_by_name:
			steam_app_id = steam_app_by_name[0]["appid"]
			self.log.debug("FOUND Steam app by name = %s", steam_app_by_name[0])
			game_image_logo = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{steam_app_id}/logo.png"
			if await util.check_resource_exists(game_image_logo):
				return game_image_logo
			game_image_logo = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{steam_app_id}/logo.jpg"
			if await util.check_resource_exists(game_image_logo):
				return game_image_logo
		return None

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
			self.log.debug("Loading Discord detectable applications")
			async with session.get("https://discord.com/api/v10/applications/detectable") as response:
				self.app_list = await response.json()
			self.log.debug("Loading Discord detectable applications finished")

	async def load_steam_application_list(self):
		async with aiohttp.ClientSession() as session:
			self.log.debug("Loading Steam detectable applications")
			async with session.get("https://api.steampowered.com/ISteamApps/GetAppList/v2/") as response:
				steam_app_list_response = dict(await response.json())
				self.steam_app_list = steam_app_list_response['applist']['apps']
				self.log.debug("Loading Steam detectable applications finished")

	@staticmethod
	async def fetch_rpc(id: str) -> dict:
		async with aiohttp.ClientSession() as session:
			async with session.get(f"https://discord.com/api/v10/applications/{id}/rpc") as response:
				return await response.json()