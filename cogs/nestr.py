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
from urllib.parse import quote 

nestr_url = "https://staging.nestr.io/api"

class NestrCog(commands.Cog, name='Nestr functions'):
    """Nestr functions"""

    def __init__(self, bot):
        self.logger = logging.getLogger(__name__)
        self.bot = bot
        self.db = TinyDB('/app/db.json')

    # webhook listener
    @commands.Cog.listener()
    async def on_message(self, message):
        # messages like: !webhook-login|123123123123|Chn6AGBTysKCnXESc|Chn6AGBTysKCnXEScChn6AGBTysKCnXESc
        if message.content.startswith("!webhook-login"):
            parts = message.content.split("|")
            if len(parts) == 4:
                discord_uid = parts[1]
                userid = parts[2]
                token = parts[3]
                
                # store or update userid and token
                User = Query()
                user = self.db.search(User.id == discord_uid)
                if len(user) == 0:
                    self.db.insert({'id': discord_uid, 'userid': userid, 'token': token})
                else:
                    self.db.upsert({'id': discord_uid, 'userid': userid, 'token': token}, User.id == discord_uid)

                # delete the received message
                hooks = await message.guild.webhooks()
                hook = next((x for x in hooks if x.name == "Nestr"), None)
                if hook:
                    webhook = Webhook.from_url(hooks[0].url, adapter=RequestsWebhookAdapter())
                    webhook.delete_message(message.id)

        # messages like: !webhook-notification|123123123123123|Title|Content
        if message.content.startswith("!webhook-notification"):
            parts = message.content.split("|")
            if len(parts) == 4:
                discord_uid = int(parts[1])
                title = parts[2]
                content = parts[3]
                
                # send pm to user
                user = await message.channel.guild.fetch_member(discord_uid)
                if user:
                    embed = discord.Embed(
                        title="Nestr Notification",
                        description=title,
                        color=0x4A44EE,
                    )
                    embed.add_field(name="Contents", value=content)
                    await user.send(embed=embed)

                # delete the received message
                hooks = await message.guild.webhooks()
                hook = next((x for x in hooks if x.name == "Nestr"), None)
                if hook:
                    webhook = Webhook.from_url(hooks[0].url, adapter=RequestsWebhookAdapter())
                    webhook.delete_message(message.id)


    @cog_ext.cog_slash(name="inbox",
                       description="Adds a new inbox todo",
                       options = [
                          create_option(
                              name="text",
                              description="Inbox text",
                              option_type=SlashCommandOptionType.STRING,
                              required=True),
                       ])
    async def inbox(self, ctx: SlashContext, text: str):
        """Nestr inbox"""

        nest_data = {
            "parentId": "inbox",
            "title": text,
        }
        ts = dt.datetime.now().strftime('%d-%b-%y %H:%M:%S')
        
        # check if user logged in
        User = Query()
        res = self.db.search(User.id == ctx.author)
        if len(res) == 0:
            await ctx.send("Please /login to Nestr first.", hidden=True)
            return
        user = res[0]
        
        url = nestr_url + "/n/inbox"
        # call Nestr API to create inbox
        resp = requests.post(url, headers={'X-Auth-Token': user['token'], 'X-User-Id': user['userid']}, verify=True, data=nest_data)
        if (resp.ok):
            self.logger.info(f"{ts}: posted {resp}\n")
            #print (resp.json())
        elif (resp.status_code == 401):
            await ctx.send("Invalid login data, please `/login` to Nestr first.", hidden=True)
            return
        
        self.logger.info(f"{ts}: {ctx.author} executed '/inbox'\n")
        await ctx.send("Added to inbox!", hidden=True)

    @cog_ext.cog_slash(name="login",
                       description="Logs you into nestr",
                       )
    async def login(self, ctx: SlashContext):
        """Nestr login"""
        print(f"Login: User {ctx.author.id}: {ctx.author.name}")
        hooks = await ctx.guild.webhooks()
        if len(hooks) > 0:
            url = nestr_url + "/authenticate?bot_callback="+hooks[0].url+"&discord_id=" + str(ctx.author.id)
            await ctx.send("Please login clicking on [this link]("+url+").", hidden=True)
        else:
            await ctx.send("[ERROR] Webhook not configured!", hidden=True)

def setup(bot):
    bot.add_cog(NestrCog(bot))