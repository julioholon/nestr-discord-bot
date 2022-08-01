"""
This module loads the token, cogs, and runs the bot app
"""

import logging.config
import os
from os import listdir
from os.path import isfile, join, dirname
import traceback
import discord
from discord.ext import commands
from discord_slash import SlashCommand
from dotenv import load_dotenv, find_dotenv

# Load Discord secret token from .env file
load_dotenv(find_dotenv())
TOKEN = os.getenv('DISCORD_TOKEN')

# Set up logging for application to write to
logging.config.fileConfig("logs.ini", disable_existing_loggers=False)
logger = logging.getLogger(__name__)

# Cog directory. 'meme.py' in cogs directory is be cogs.meme
cogs_dir = "cogs"

bot = commands.Bot(command_prefix="!", description='The Nestr bot using slash commands', self_bot=True,
                   intents=discord.Intents.default(), allowed_mentions=discord.AllowedMentions.all())
slash = SlashCommand(bot, sync_commands=True)

# Load the extensions(cogs) that are located in the cogs directory. Any file in here attempts to load.
if __name__ == '__main__':
    for extension in [f.replace('.py', '') for f in listdir(cogs_dir) if isfile(join(cogs_dir, f))]:
        try:
            bot.load_extension(cogs_dir + "." + extension)
            print(f'Loaded {extension} successfully')
            logger.info('Loaded %s successfully', extension)
        except (discord.ClientException, ModuleNotFoundError):
            print(f'Failed to load extension: {extension}')
            print(discord.ClientException)
            print(ModuleNotFoundError)
            logger.error('Failed to load extension: %s', extension)
            traceback.print_exc()


@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="/help"))
    print('-' * 15)
    print('Successfully logged in and booted...!')
    print(f'Logged in as: {bot.user.name} - {bot.user.id}\nVersion: {discord.__version__}')
    print('-' * 15)
    logger.info('Successfully logged in and booted...!')
    logger.info('Logged in as: %s - %s\nVersion: %s', bot.user.name, bot.user.id, discord.__version__)

bot.run(TOKEN, bot=True, reconnect=True)