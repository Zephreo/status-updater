import requests
from dto.player_summary import PlayerSummary
import os
import logging
import asyncio
from discord.ext import commands

class SteamPlayerSummaries:
	poll_ids: dict[int, list[str]] # channel id to list non-duplicate steam id
	cache: dict[str, PlayerSummary] # list of player summaries
	log: logging.Logger
	_bot: commands.Bot

	def __init__(self, logger: logging.Logger, bot: commands.Bot):
		self.poll_ids = {}
		self.cache = {}
		self.log = logger
		self._bot = bot

	async def background_task(self):
		await self._bot.wait_until_ready()
		while not self._bot.is_closed():
			self.poll()
			await asyncio.sleep(40)

	# poll steam api for player summaries
	# https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/
	def poll(self):
		# skip if empty
		if all(not ids for ids in self.poll_ids.values()):
			return
		steam_ids = ",".join(self.poll_ids.values())
		self.log.debug("Polling Steam API for player summaries: %s", steam_ids) # TEMP
		url = f"https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/?key={os.getenv('STEAM_KEY')}&steamids={steam_ids}"
		response = requests.get(url)
		data = response.json()
		players = data["response"]["players"]
		cache = {}
		for player in players:
			cache[player["steamid"]] = PlayerSummary(player)

	def get_player_summary(self, steam_id: str | None) -> PlayerSummary | None:
		if steam_id is None:
			return None
		# get player summary from cache
		return self.cache.get(steam_id, None)

	def set_poll(self, channel_id: int, steam_ids: list[str]):
		self.poll_ids[channel_id] = steam_ids
