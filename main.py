"""The entry point of the program which configures and runs the bot."""

import os
import asyncio
from dotenv import load_dotenv
import util
import discord
from discord.ext import commands


# Configure gateway intents.
intents = discord.Intents.default()
intents.presences = True
# intents.members = True
# intents.messages = True
# intents.message_content = True
# intents.reactions = True

# Load variables from '.env' file into the environment.
load_dotenv()

# Get the Discord token from the environment.
discord_token = os.getenv('DISCORD_TOKEN')

asyncio.run(util.wait_for_connection())

# Configure the bot. The 'command_prefix' parameter is required
# but it's not being used so we set it to something random.
bot = commands.Bot(command_prefix='(╯°□°)╯', intents=intents)

# Load the first cog located at 'cog/bot.py'.
asyncio.run(bot.load_extension('cog.bot'))

if discord_token is None:
	raise ValueError("DISCORD_TOKEN environment variable is not set. Please set it in the .env file as per the README.")

# Run the bot.
bot.run(discord_token)
