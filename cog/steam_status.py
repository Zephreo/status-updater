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
		self.log.warning("SteamPlayerSummaries background task stopped")

	# poll steam api for player summaries
	# https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/
	def poll(self):
		# skip if empty
		if all(not ids for ids in self.poll_ids.values()):
			self.cache.clear()
			return
		steam_ids = ",".join([steam_id for ids in self.poll_ids.values() for steam_id in ids])
		# self.log.debug("Polling Steam API for player summaries: %s", steam_ids) # TEMP
		url = f"https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/?key={os.getenv('STEAM_KEY')}&steamids={steam_ids}"
		response = requests.get(url)
		try:
			data = response.json()
		except ValueError as e:
			self.log.error("Failed to decode player summaries from Steam API, response: %s", response.text, exc_info=e)
			return
		players = data["response"]["players"]
		self.cache.clear()
		for player in players:
			self.cache[player["steamid"]] = PlayerSummary(player)

	def get_player_summary(self, steam_id: str | None) -> PlayerSummary | None:
		if steam_id is None:
			return None
		# get player summary from cache
		return self.cache.get(steam_id, None)

	def set_poll(self, channel_id: int, steam_ids: list[str]):
		self.poll_ids[channel_id] = steam_ids

