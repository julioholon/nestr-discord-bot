"""
A cog extension for the nestr info functions of the bot app
"""

import os
import re
import logging
import logging.config
import discord
import requests
import datetime as dt
from discord.utils import get
from discord import Webhook, RequestsWebhookAdapter
from requests.auth import HTTPDigestAuth
from discord.ext import commands
from discord_slash.utils.manage_commands import create_option, create_choice, SlashCommandOptionType
from discord_slash.utils.manage_components import wait_for_component, create_button, create_actionrow
from discord_slash.model import ButtonStyle
from discord_slash import cog_ext, SlashContext
from tinydb import TinyDB, Query, operations
from tinydb.storages import JSONStorage
from tinydb.middlewares import CachingMiddleware
from urllib.parse import quote, quote_plus, unquote
from bs4 import BeautifulSoup as bs

nestr_base_url = "https://app.nestr.io"
nestr_url = nestr_base_url+"/api"

class NestrCog(commands.Cog, name='Nestr functions'):
    """Nestr functions"""

    def __init__(self, bot):
        self.logger = logging.getLogger(__name__)
        self.bot = bot
        self.db = TinyDB('/app/db.json', storage=CachingMiddleware(JSONStorage))

    def get_loggedin_user(self, discord_id):
        discord_id = str(discord_id)
        User = Query()
        res = self.db.search(User.discord_id == discord_id)
        if len(res) == 1:
            return res[0]
        if len(res) > 1:
            raise RuntimeError("More than one user found on the database!")
        return None

    async def delete_webhook_message(self, message):
        hooks = await message.guild.webhooks()
        hook = next((x for x in hooks if x.name == "Nestr"), None)
        if hook:
            webhook = Webhook.from_url(hooks[0].url, adapter=RequestsWebhookAdapter())
            webhook.delete_message(message.id)
    
    async def get_search_results(self, user, text, limit=100, skip=0, context_id=None):
        url = f"{nestr_url}/search/{text}?limit={limit}&skip={skip}"
        if context_id != None:
            url += "&contextId="+context_id
        resp = requests.get(url, headers={'X-Auth-Token': user['token'], 'X-User-Id': user['nestr_id']}, verify=True)
        if (resp.ok):
            return resp.json().get('data')

        elif (resp.status_code == 401):
            raise RuntimeError("Invalid login data, please `/login` to Nestr first.")
    
    async def add_sync_workspace(self, user, guild, workspace_id):
        hooks = await guild.webhooks()
        hook = next((x for x in hooks if x.name == "Nestr"), None)
        if not hook:
            raise RuntimeError("Webhook not configured on Discord server")
        webhook_url = hooks[0].url
        url = f"{nestr_url}/discordsync/{workspace_id}?webhookUrl={webhook_url}"
        resp = requests.get(url, headers={'X-Auth-Token': user['token'], 'X-User-Id': user['nestr_id']}, verify=True)
        if (resp.ok):
            return True
        elif (resp.status_code != 200):
            raise RuntimeError("Unable to sync workspace.")

      
        
    #### webhook listeners ####
    @commands.Cog.listener()
    async def on_message(self, message):
        # messages like: !webhook-login|123123123123|Chn6AGBTysKCnXESc|Chn6AGBTysKCnXEScChn6AGBTysKCnXESc
        if message.content.startswith("!webhook-login"):
            parts = message.content.split("|")
            if len(parts) == 4:
                discord_id = parts[1]
                nestr_id = parts[2]
                token = parts[3]
                
                # store or update userid and token
                User = Query()
                res = self.db.search(User.discord_id == discord_id)
                if len(res) > 0:
                    self.db.update({'discord_id': discord_id, 'nestr_id': nestr_id, 'token': token}, User.discord_id == discord_id)
                else:
                    self.db.insert({'discord_id': discord_id, 'nestr_id': nestr_id, 'token': token})
                self.db.storage.flush()
                
                # delete the received message
                await self.delete_webhook_message(message)

        # messages like: !webhook-notification|123123123123123|Title|Content
        if message.content.startswith("!webhook-notification"):
            parts = message.content.split("|")
            print (parts)  
            if len(parts) >= 4:
                discord_id = int(parts[1])
                title = parts[2]
                content = parts[3] or "No extra details"
                url = ""
                if len(parts) == 5:
                    url = parts[4] 
                
                # send pm to user
                user = await message.channel.guild.fetch_member(discord_id)
                if user:
                    embed = discord.Embed(
                        title="Nestr Notification",
                        description=title,
                        color=0x4A44EE,
                        url=url, 
                    )
                    embed.add_field(name="Contents", value=content)
                    await user.send(embed=embed)

                # delete the received message
                await self.delete_webhook_message(message)

    ##### /search command ####
    @cog_ext.cog_slash(name="search",
                       description="Searches on nestr",
                       options = [
                          create_option(
                              name="text",
                              description="Search text",
                              option_type=SlashCommandOptionType.STRING,
                              required=True),
                       ])
    async def search(self, ctx: SlashContext, text: str):
        """Search nestr"""

        ts = dt.datetime.now().strftime('%d-%b-%y %H:%M:%S')
        
        # check if user logged in
        user = self.get_loggedin_user(ctx.author.id)
        if user == None:
            await ctx.send("Please /login to Nestr first.", hidden=True)
            return
        try:
            res = await self.get_search_results(user, text, 25)
            count = len(res)
            results = await ctx.send(f"Found {count} search results for '{text}'.")

            for nest in res:
                title = bs(nest.get('title', "No title")[:100], "html.parser").text
                description = bs(nest.get('description', "No description.")[:4090], "html.parser").text
                link = nestr_base_url+"/n/"+nest.get('_id')
                embed = discord.Embed(
                    title=title,
                    description=description,
                    color=0x4A44EE,
                    url=link
                )
                await results.reply(embed=embed)
        except Exception as err:
            await ctx.send("{0}".format(err), hidden=True)

        self.logger.info(f"{ts}: {ctx.author} executed '/search'\n")

    ##### /sync command ####
    @cog_ext.cog_slash(name="sync",
                       description="Sync workspaces",
                      options=[])
    async def sync(self, ctx: SlashContext):
        """Syncs Nestr workspaces to Discord"""

        ts = dt.datetime.now().strftime('%d-%b-%y %H:%M:%S')
        
        # check if user logged in
        user = self.get_loggedin_user(ctx.author.id)
        if user == None:
            await ctx.send("Please /login to Nestr first.", hidden=True)
            return
        try:
            workspaces = await self.get_search_results(user, "label:circleplus-anchor-circle", limit=5)
            action_rows = []
            added = {}
            while (len(workspaces)): 
                buttons = []
                for ws in workspaces:
                    b = create_button(
                        style=ButtonStyle.blue,
                        label=ws.get("title", "No title"),
                        custom_id=ws.get("_id"),
                        disabled = False
                    )
                    buttons.append(b)
                    added[ws.get("_id")] = ws.get("title", "No title")
                action_rows.append(create_actionrow(*buttons))
                workspaces = await self.get_search_results(user, "label:circleplus-anchor-circle", limit=5, skip=len(added))
            await ctx.send("Choose workspace to sync to Discord", components=action_rows, hidden=True)
            button_ctx = await wait_for_component(self.bot, components=action_rows)
            selected_id = button_ctx.component_id
            selected_name = added[button_ctx.component_id]
            category_name = f"{selected_name} circles"

            # add one channel per circle + one for anchor
            circles = await self.get_search_results(user, "label:circleplus-circle", context_id=selected_id)
            category = get(ctx.guild.categories, name=category_name)
            if not category:
                category = await ctx.guild.create_category(category_name, overwrites=None, reason=None)
            
            if not get(category.channels, name="anchor-circle"):
                await ctx.guild.create_text_channel("anchor-circle", category=category)

            anchor_roles = await self.get_search_results(user, "label:circleplus-role depth:2", context_id=selected_id)
            for role in anchor_roles:
                role_name = bs(role.get('title', "No title")[:100], "html.parser").text 
                print(role_name)
                
            for circle in circles:
                circle_name = bs(circle.get('title', "No title")[:100], "html.parser").text.lower()+"-circle"
                circle_name = re.sub('\.', '', circle_name)
                circle_name = re.sub('\s', '-', circle_name)
                if not get(category.channels, name=circle_name):
                  # TODO: Set channel topic as circle purpose!
                  await ctx.guild.create_text_channel(name=circle_name, category=category)

            # TODO: map people already bound to Discord to their roles??
            await self.add_sync_workspace(user, ctx.guild, selected_id)
            await button_ctx.edit_origin(content=f"Worspace `{selected_name}` enabled!")
            return
        except Exception as err:
            await ctx.send("{0}".format(err), hidden=True)
            raise

    ##### /inbox command ####
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
        user = self.get_loggedin_user(ctx.author.id)
        if user == None:
            await ctx.send("Please /login to Nestr first.", hidden=True)
            return
        
        url = nestr_url + "/n/inbox"
        # call Nestr API to create inbox
        resp = requests.post(url, headers={'X-Auth-Token': user['token'], 'X-User-Id': user['nestr_id']}, verify=True, data=nest_data)
        if (resp.ok):
            self.logger.info(f"{ts}: posted {resp}\n")
            #rint (resp.json())
        elif (resp.status_code == 401):
            await ctx.send("Invalid login data, please `/login` to Nestr first.", hidden=True)
            return
        
        self.logger.info(f"{ts}: {ctx.author} executed '/inbox'\n")
        await ctx.send("Added to inbox!", hidden=True)

        
    ##### /login command ####
    @cog_ext.cog_slash(name="login",
                       description="Logs you into nestr",
                       )
    async def login(self, ctx: SlashContext):
        """Nestr login"""
        #print(f"Login: User {ctx.author.id}: {ctx.author.name}")
        
        if not ctx.guild:
            await ctx.send("You must login from an existing guild that has the bot configured.", hidden=True)
            return
        hooks = await ctx.guild.webhooks()
        if len(hooks) > 0:
            url = nestr_url + "/authenticate?bot_callback="+hooks[0].url+"&discord_id=" + str(ctx.author.id)
            await ctx.send("Please login clicking on [this link]("+url+").", hidden=True)
        else:
            await ctx.send("[ERROR] Webhook not configured!", hidden=True)

def setup(bot):
    bot.add_cog(NestrCog(bot))