"""
A cog extension for the nestr info functions of the bot app
"""

import os
import logging
import logging.config
import discord
import requests
import datetime as dt
from discord import Webhook, RequestsWebhookAdapter
from requests.auth import HTTPDigestAuth
from discord.ext import commands
from discord_slash.utils.manage_commands import create_option, create_choice, SlashCommandOptionType
from discord_slash import cog_ext, SlashContext
from tinydb import TinyDB, Query, operations

nestr_url = "https://staging.nestr.io/api"
NESTR_TOKEN = os.getenv('NESTR_TOKEN')
NESTR_USERID = os.getenv('NESTR_USERID')

class NestrCog(commands.Cog, name='Nestr functions'):
    """Nestr functions"""

    def __init__(self, bot):
        self.logger = logging.getLogger(__name__)
        self.bot = bot
        self.db = TinyDB('/app/db.json')

    # webhook listener
    @commands.Cog.listener()
    async def on_message(self, message):
        if message.content.startswith("!webhook-login"):
            parts = message.content.split(" ")
            if len(parts) == 4:
                uid = parts[1]
                userid = parts[2]
                token = parts[3]
                
                # store or update userid and token
                User = Query()
                user = self.db.search(User.id == uid)
                if len(user) == 0:
                    self.db.insert({'id': uid, 'userid': userid, 'token': token})
                else:
                    self.db.upsert({'id': uid, 'userid': userid, 'token': token}, User.id == uid)

            hooks = await message.guild.webhooks()
            if len(hooks) > 0:
                webhook = Webhook.from_url(hooks[0].url, adapter=RequestsWebhookAdapter())
                webhook.send(f'{message.author}: Login message processed.')
                await webhook.delete_message(message.id)


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
        
        # check if user logged in
        User = Query()
        res = self.db.search(User.id == ctx.author.id)
        if len(res) == 0:
            await ctx.send("Please /login to Nestr first.", hidden=True)
            return
        user = res[0]
        
        url = nestr_url + "/n/inbox"
        # call Nestr API to create inbox
        resp = requests.post(url, headers={'X-Auth-Token': user['token'], 'X-User-Id': user['userid']}, verify=True, data=nest_data)
        if(resp.ok):
            self.logger.info(f"{ts}: posted {resp}\n")
            #print (resp.json())
        else:
            resp.raise_for_status()
        
        self.logger.info(f"{ts}: {ctx.author} executed '/inbox'\n")
        await ctx.send("Inbox created!", hidden=True)

    @cog_ext.cog_slash(name="login",
                       description="Logs you into nestr",
                       options = [
                          create_option(
                              name="userid",
                              description="UserID",
                              option_type=SlashCommandOptionType.STRING,
                              required=False),
                          create_option(
                              name="token",
                              description="Auth token",
                              option_type=SlashCommandOptionType.STRING,
                              required=False),
                       ])
    async def login(self, ctx: SlashContext, userid: str = "", token: str = ""):
        """Nestr login"""

        if userid == "" or token == "":
            url = nestr_url + "/authenticate"
            await ctx.send("Please login on the following page: "+url, hidden=True)
        else:
            # store or update userid and token
            User = Query()
            user = self.db.search(User.id == ctx.author.id)
            if len(user) == 0:
                self.db.insert({'id': ctx.author.id, 'userid': userid, 'token': token})
            else:
                self.db.upsert({'id': ctx.author.id, 'userid': userid, 'token': token}, User.id == ctx.author.id)
            await ctx.send("Logged into Nestr!", hidden=True)

def setup(bot):
    bot.add_cog(NestrCog(bot))