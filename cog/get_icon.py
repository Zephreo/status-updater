import calendar
import util
import time
import discord
import requests
import logging

class IconList:
	log: logging.Logger
	app_list: list
	steam_app_list: list

	async def get_game_image(self, activity: discord.Activity | discord.Game) -> str | None:
		if hasattr(activity, 'large_image_url'):
			return activity.large_image_url
		if hasattr(activity, 'application_id'):
			app_id = activity.application_id
			discord_app = list(filter(lambda app: app['id'] == str(app_id), self.app_list))
			if discord_app:
				self.log.debug("FOUND discord app by application_id = %s", discord_app)
				return f"https://cdn.discordapp.com/app-icons/{discord_app[0]['id']}/{discord_app[0]['icon']}.png"
		discord_app_by_name = list(filter(lambda app: app['name'] == str(activity.name), self.app_list))
		if discord_app_by_name:
			self.log.debug("FOUND discord app by name = %s", discord_app_by_name)
			return f"https://cdn.discordapp.com/app-icons/{discord_app_by_name[0]['id']}/{discord_app_by_name[0]['icon']}.png"
		steam_app_by_name = list(filter(lambda steam_app: steam_app['name'] == str(activity.name), self.steam_app_list))
		if steam_app_by_name:
			steam_app_id = steam_app_by_name[0]["appid"]
			self.log.debug("FOUND Steam app by name = %s", steam_app_by_name[0])
			timestamp = calendar.timegm(time.gmtime())
			game_image_logo = f"https://cdn.cloudflare.steamstatic.com/steam/apps/{steam_app_id}/logo.jpg?t={timestamp}"
			if util.check_resource_exists(game_image_logo):
				return game_image_logo
		return None

	def __init__(self, logger: logging.Logger):
		self.log = logger
		self.load_discord_application_list()
		self.load_steam_application_list()

	def load_discord_application_list(self):
		with requests.Session() as session:
			self.log.debug("Loading Discord detectable applications")
			with session.get("https://discord.com/api/v10/applications/detectable") as response:
				self.app_list = response.json()
			self.log.debug("Loading Discord detectable applications finished")

	def load_steam_application_list(self):
		with requests.Session() as steam_session:
			self.log.debug("Loading Steam detectable applications")
			with steam_session.get("https://api.steampowered.com/ISteamApps/GetAppList/v2/") as steam_response:
				steam_app_list_response = dict(steam_response.json())
				self.steam_app_list = steam_app_list_response['applist']['apps']
				self.log.debug("Loading Steam detectable applications finished")