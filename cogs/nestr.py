"""
A cog extension for the nestr info functions of the bot app
"""

import os
import logging
import logging.config
import discord
import requests
import datetime as dt
from requests.auth import HTTPDigestAuth
from discord.ext import commands
from discord_slash.utils.manage_commands import create_option, create_choice, SlashCommandOptionType
from discord_slash import cog_ext, SlashContext

nestr_url = "https://staging.nestr.io/api"
NESTR_TOKEN = os.getenv('NESTR_TOKEN')
NESTR_USERID = os.getenv('NESTR_USERID')

class NestrCog(commands.Cog, name='Nestr functions'):
    """Nestr functions"""

    def __init__(self, bot):
        self.logger = logging.getLogger(__name__)
        self.bot = bot

    @cog_ext.cog_slash(name="inbox",
                       description="Adds a new inbox todo",
                       options = [
                          create_option(
                              name="title",
                              description="Nest title",
                              option_type=SlashCommandOptionType.STRING,
                              required=True),
                          create_option(
                              name="description",
                              description="Nest description",
                              option_type=SlashCommandOptionType.STRING,
                              required=False),
                       ])
    async def inbox(self, ctx: SlashContext, title: str, description: str = ""):
        """Nestr inbox"""

        nest_data = {
            "parentId": "inbox",
            "title": title,
            "description": description,
        }
        ts = dt.datetime.now().strftime('%d-%b-%y %H:%M:%S')
        
        url = nestr_url + "/n/inbox"
        
        # call Nestr API to create inbox
        resp = requests.post(url, headers={'X-Auth-Token': NESTR_TOKEN, 'X-User-Id': NESTR_USERID}, verify=True, data=nest_data)
        if(resp.ok):
            self.logger.info(f"{ts}: posted {resp}\n")
            #print (resp.json())
        else:
            resp.raise_for_status()
        
        self.logger.info(f"{ts}: {ctx.author} executed '/inbox'\n")
        await ctx.send("Inbox created!", hidden=True)

    @inbox.error
    async def inbox_error(self, ctx: SlashContext, error):
        """
        Error catcher for inbox command
        :param ctx:
        :param error:
        """
        msg = f'inbox error: {error}'
        await ctx.send(msg, hidden=True)


def setup(bot):
    bot.add_cog(NestrCog(bot))