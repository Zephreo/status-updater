# https://developer.valvesoftware.com/wiki/Steam_Web_API#GetPlayerSummaries_.28v0001.29
class PlayerSummary:
	steam_id: str
	community_visibility_level: int
	profile_state: int
	username: str
	steam_profile_url: str
	avatar: str
	avatar_medium: str
	avatar_full: str
	avatar_hash: str
	last_log_off_timestamp: int
	online_status: int
	primary_clan_id: str | None
	user_created_at: int | None
	player_status_flags: int | None
	game_name: str | None
	game_id: str | None
	location_country_code: str | None

	def __init__(self, data: dict):
		self.steam_id = data["steamid"]
		self.community_visibility_level = data["communityvisibilitystate"]
		self.profile_state = data["profilestate"]
		self.username = data["personaname"]
		self.steam_profile_url = data["profileurl"]
		self.avatar = data["avatar"]
		self.avatar_medium = data["avatarmedium"]
		self.avatar_full = data["avatarfull"]
		self.avatar_hash = data["avatarhash"]
		self.last_log_off_timestamp = data["lastlogoff"]
		self.online_status = data["personastate"]
		self.primary_clan_id = data.get("primaryclanid")
		self.user_created_at = data.get("timecreated")
		self.player_status_flags = data.get("personastateflags")
		self.game_name = data.get("gameextrainfo")
		self.game_id = data.get("gameid")
		self.location_country_code = data.get("loccountrycode")

	def __str__(self):
		return f"{self.username} ({self.steam_id}) - {self.game_name}"