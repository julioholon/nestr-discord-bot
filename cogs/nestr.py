"""
A cog extension for the nestr info functions of the bot app
"""

import os
import re
import json
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
from itertools import groupby

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
    
    def get_synced_roles(self, ctx):
        Role = Query()
        return self.db.search((Role.guild_id == ctx.guild.id) & Role.role_id.exists())

    def get_synced_circles(self, ctx):
        Circle = Query()
        circles = self.db.search((Circle.guild_id == ctx.guild.id) & Circle.circle_id.exists())
        return circles

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
    
    async def sync_workspace(self, ctx, user, category, prefix, workspace_id, workspace_name):
        # Recursively sync circles and subcircles
        await self._sync_circle(ctx, user, category, prefix, workspace_id)
        self.db.storage.flush()

        hooks = await ctx.guild.webhooks()
        hook = next((x for x in hooks if x.name == "Nestr"), None)
        if not hook:
            raise RuntimeError("Webhook not configured on Discord server")
        webhook_url = quote_plus(hooks[0].url)
        url = f"{nestr_url}/discordsync/{workspace_id}?webhookUrl={webhook_url}"
        resp = requests.post(url, headers={'X-Auth-Token': user['token'], 'X-User-Id': user['nestr_id']},  verify=True)
        if (resp.ok):
            # store synced workspace for this guild
            Workspace = Query()
            res = self.db.search((Workspace.workspace_id == workspace_id) & (Workspace.guild_id == ctx.guild.id))
            if len(res) == 0:
                self.db.insert({'workspace_id': workspace_id,
                                'workspace_name': workspace_name,
                                'prefix': prefix,
                                'circle_id': workspace_id,
                                'circle_name': workspace_name,
                                'discord_name': workspace_name,
                                'parent_circle': "",
                                'sync_at': dt.datetime.now().isoformat(),
                                'guild_id': ctx.guild.id})
            else:
                self.db.update({'prefix': prefix,
                                'workspace_name': workspace_name,
                                'sync_at': dt.datetime.now().isoformat()},
                                (Workspace.workspace_id == workspace_id) & (Workspace.guild_id == ctx.guild.id))
            self.db.storage.flush()
            return True
        elif (resp.status_code != 200):
            print(resp.json())
            raise RuntimeError("Unable to sync workspace.")

    async def _sync_circle(self, ctx, user, category, prefix, circle_id, depth=2):
        roles = await self.get_search_results(user, f"label:circleplus-role depth:{depth}", context_id=circle_id)
        for role in roles:
            role_name = bs(role.get('title', "No title"), "html.parser").text
            role_id = role.get('_id') 
            if prefix:
                role_name = f"{prefix}/{role_name}"
            if not get(ctx.guild.roles, name=role_name):
                await ctx.guild.create_role(name=role_name, mentionable=True)
                Role = Query()
                res = self.db.search((Role.role_id == role_id) & (Role.guild_id == ctx.guild.id))
                if len(res) == 0:
                    self.db.insert({'role_id': role_id,
                                    'role_name': bs(role.get('title', "No title"), "html.parser").text,
                                    'discord_name': role_name,
                                    'parent_circle': circle_id,
                                    'sync_at': dt.datetime.now().isoformat(),
                                    'guild_id': ctx.guild.id})
                else:
                    self.db.update({'role_name': bs(role.get('title', "No title"), "html.parser").text,
                                    'discord_name': role_name,
                                    'sync_at': dt.datetime.now().isoformat()},
                                    (Role.role_id == role_id) & (Role.guild_id == ctx.guild.id))
                self.db.storage.flush()
            
        circles = await self.get_search_results(user, f"label:circleplus-circle depth:{depth}", context_id=circle_id)
        for subcircle in circles:
            subcircle_id = subcircle.get('_id')
            if subcircle_id == circle_id:
                continue
            subcircle_name = bs(subcircle.get('title', "No title"), "html.parser").text.lower()
            subcircle_name = re.sub('\.', '', subcircle_name)
            subcircle_name = re.sub('\s', '-', subcircle_name)
            if prefix:
                subcircle_name = f"{prefix}-{subcircle_name}"

            if not get(category.channels, name=subcircle_name+"-circle"):
                purpose = bs(subcircle.get('purpose', ""), "html.parser").text
                await ctx.guild.create_text_channel(name=subcircle_name+"-circle", category=category, topic=purpose)
                # create circle in database
                Circle = Query()
                res = self.db.search((Circle.circle_id == subcircle_id) & (Circle.guild_id == ctx.guild.id))
                if len(res) == 0:
                    self.db.insert({'circle_id': subcircle_id,
                                    'circle_name': bs(subcircle.get('title', "No title"), "html.parser").text,
                                    'discord_name': subcircle_name,
                                    'parent_circle': circle_id,
                                    'updated_at': dt.datetime.now().isoformat(),
                                    'guild_id': ctx.guild.id})
                else:
                    self.db.update({'circle_name': bs(subcircle.get('title', "No title"), "html.parser").text,
                                    'discord_name': subcircle_name,
                                    'parent_circle': circle_id,
                                    'updated_at': dt.datetime.now().isoformat()},
                                    (Circle.circle_id == subcircle_id) & (Circle.guild_id == ctx.guild.id))
                self.db.storage.flush()
            
            # TODO: remove deleted circles and roles???

            # Recursively sync subcircles
            await self._sync_circle(ctx, user, category, subcircle_name, subcircle_id, depth+1)
    
    async def unsync_workspace(self, ctx, user, workspace_id):
        Workspace = Query()
        ws = self.db.search((Workspace.workspace_id == workspace_id) & (Workspace.guild_id == ctx.guild.id))
        if len(ws) > 0:
            await self._unsync_circles(ctx, user, workspace_id)
            self.db.remove((Workspace.workspace_id == workspace_id) & (Workspace.guild_id == ctx.guild.id))
            self.db.storage.flush()

            # TODO: tell Nestr to unsync this workspace
            # url = f"{nestr_url}/discordunsync/{workspace_id}"
            # resp = requests.post(url, headers={'X-Auth-Token': user['token'], 'X-User-Id': user['nestr_id']}, verify=True)
            # if (resp.ok):
            #     return True
            # elif (resp.status_code != 200):
            #     print (resp.status_code)
            #     print(resp.json())
            #     raise RuntimeError("Unable to unsync workspace.")
            return True
        else:
            raise RuntimeError("Workspace not found.")

    # Recursive remove circles
    # NOTE: remember to self.db.storage.flush() later
    async def _unsync_circles(self, ctx, user, circle_id):
        Role = Query()
        roles = self.db.search((Role.parent_circle == circle_id) & (Role.guild_id == ctx.guild.id))
        if len(roles) > 0:
            for role in roles:
                role_name = role.get('discord_name',"")
                if get(ctx.guild.roles, name=role_name):
                    await get(ctx.guild.roles, name=role_name).delete()
                    self.db.remove((Role.role_id == role.get('role_id')) & (Role.guild_id == ctx.guild.id))

        Circle = Query()
        circles = self.db.search((Circle.parent_circle == circle_id) & (Circle.guild_id == ctx.guild.id))
        if len(circles) > 0:
            for circle in circles:
                circle_name = circle.get('discord_name',"")
                if get(ctx.guild.channels, name=circle_name+"-circle"):
                    await get(ctx.guild.channels, name=circle_name+"-circle").delete()
                    self.db.remove((Circle.circle_id == circle.get('circle_id')) & (Circle.guild_id == ctx.guild.id))

                # Recursively unsync subcircles
                await self._unsync_circles(ctx, user, circle.get('circle_id'))

      
        
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

    ##### /sync command ####
    @cog_ext.cog_slash(name="sync",
                       description="Sync workspaces",
                      options=[
                          create_option(
                              name="prefix",
                              description="Workspace prefix",
                              option_type=SlashCommandOptionType.STRING,
                              required=False),
                      ])
    @commands.has_any_role("admin")
    async def sync(self, ctx: SlashContext, prefix: str=None):
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
                        label=bs(ws.get('title', "No title"), "html.parser").text,
                        custom_id=ws.get("_id"),
                        disabled = False
                    )
                    buttons.append(b)
                    added[ws.get("_id")] = ws.get("title", "No title")
                action_rows.append(create_actionrow(*buttons))
                workspaces = await self.get_search_results(user, "label:circleplus-anchor-circle", limit=5, skip=len(added))
            await ctx.send("Choose workspace to sync to Discord", components=action_rows, hidden=True)
            button_ctx = await wait_for_component(self.bot, components=action_rows, timeout=120)
            selected_id = button_ctx.component_id
            selected_name = added[button_ctx.component_id]
            category_name = f"{selected_name} circles"

            # add one channel per circle + one for anchor
            category = get(ctx.guild.categories, name=category_name)
            if not category:
                category = await ctx.guild.create_category(category_name, overwrites=None, reason=None)
            
            if not get(category.channels, name="anchor-circle"):
                await ctx.guild.create_text_channel("anchor-circle", category=category)
            
            # TODO: map people already bound to Discord to their roles??
            await self.sync_workspace(ctx, user, category, prefix, workspace_id=selected_id, workspace_name=selected_name)
            
            await button_ctx.edit_origin(content=f"Worspace `{selected_name}` enabled!")
            return
        except Exception as err:
            await ctx.send("{0}".format(err), hidden=True)
            raise

    ##### /unsync command ####
    @cog_ext.cog_slash(name="unsync",
                       description="Disable sync of Nestr workspaces",)
    @commands.has_any_role("admin")
    async def unsync(self, ctx: SlashContext):
        """Disables Sync of Nestr workspaces on Discord"""

        ts = dt.datetime.now().strftime('%d-%b-%y %H:%M:%S')
        
        # check if user logged in
        user = self.get_loggedin_user(ctx.author.id)
        if user == None:
            await ctx.send("Please /login to Nestr first.", hidden=True)
            return
        try:
            Workspace = Query()
            workspaces = self.db.search((Workspace.guild_id == ctx.guild.id) & Workspace.workspace_name.exists())
            if len(workspaces) == 0:
                await ctx.send("No workspaces enabled.", hidden=True)
                return
            action_rows = []
            added = {}
            while (len(workspaces)): 
                buttons = []
                for ws in workspaces:
                    b = create_button(
                        style=ButtonStyle.blue,
                        label=ws.get('workspace_name'),
                        custom_id=ws.get("workspace_id"),
                        disabled = False
                    )
                    buttons.append(b)
                    added[ws.get("workspace_id")] = ws.get("workspace_name")
                action_rows.append(create_actionrow(*buttons))
                workspaces = [] # TODO: handle more than 5 workspaces
            await ctx.send("Choose workspace to disable", components=action_rows, hidden=True)
            button_ctx = await wait_for_component(self.bot, components=action_rows, timeout=120)
            selected_id = button_ctx.component_id
            selected_name = added[button_ctx.component_id]
            category_name = f"{selected_name} circles"

            await self.unsync_workspace(ctx, user, workspace_id=selected_id)

            category = get(ctx.guild.categories, name=category_name)
            if category:
                await category.delete()

            anchor_circle = get(ctx.guild.channels, name="anchor-circle")
            if anchor_circle:
                await anchor_circle.delete()

            
            await button_ctx.edit_origin(content=f"Worspace `{selected_name}` disabled!")
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

            
    ##### /accountable command ####
    @cog_ext.cog_slash(name="accountable",
                       description="Who is accountable for this",
                       options = [
                          create_option(
                              name="search",
                              description="Search accountability text",
                              option_type=SlashCommandOptionType.STRING,
                              required=True),
                        ])
    async def accountable(self, ctx: SlashContext, search: str):
        """Search roles accountable"""

        ts = dt.datetime.now().strftime('%d-%b-%y %H:%M:%S')
        
        # check if user logged in
        user = self.get_loggedin_user(ctx.author.id)
        if user == None:
            await ctx.send("Please /login to Nestr first.", hidden=True)
            return
        try:
            valid_roles = self.get_synced_roles(ctx)
            synced_circles = {circle.get("circle_id"): circle for circle in self.get_synced_circles(ctx)}
            text = search
            search_text = "label:circleplus-accountability "+search
            accs = await self.get_search_results(user, search_text, 100)
            accs_sorted = sorted(accs, key=lambda acc: acc.get("parentId"))
            keys = [key for key,group in groupby(accs_sorted, key=lambda acc: acc.get("parentId"))]
            res = [role for role in valid_roles if role.get("role_id") in keys]
            res_sorted = sorted(res, key=lambda res: res.get("parent_circle"))
            grouped_roles = {}
            for k,g in groupby(res_sorted, key=lambda res: res.get("parent_circle")):
                grouped_roles[k] = list(g)

            embed = discord.Embed(
                title="Accountable roles",
                color=0x4A44EE,
                description=f"Roles accountable for `{search}` (top 25 items)",
                url=nestr_base_url+quote("/search/"+search_text),
            )
            for circle_id in grouped_roles.keys():
                if circle_id not in synced_circles.keys():
                    continue
                circle = synced_circles[circle_id]
                circle_title = circle.get("circle_name")
                circle_link = nestr_base_url+"/n/"+circle_id
                embed.add_field(name=f"🔵 Circle", value=f"[{circle_title}]({circle_link})", inline=False)
                for role in grouped_roles[circle_id]:
                    title = role.get('role_name')[:100]
                    link = nestr_base_url+"/n/"+role.get('role_id')
                    role_text = ""
                    for acc in accs:
                        if acc.get("parentId") == role.get("role_id"):
                            acc_title = bs(acc.get('title'), "html.parser").text
                            role_text += f"> - {acc_title}\n"
                    embed.add_field(name=f"> 🎭 {title} - {link}", value=f"{role_text}", inline=False)
            if len(grouped_roles) == 0:
                    embed.add_field(name=f"No results found", value="...", inline=False)
            
            await ctx.send(embed=embed)
        except Exception as err:
            await ctx.send("{0}".format(err), hidden=True)
            raise


    ##### /roles command ####
    @cog_ext.cog_slash(name="roles",
                       description="Roles a user fills",
                       options = [
                          create_option(
                              name="who",
                              description="Roles of someone",
                              option_type=SlashCommandOptionType.USER,
                              required=False),
                       ])
    async def roles(self, ctx: SlashContext, who: discord.User=None):
        """Search nestr for Roles"""

        ts = dt.datetime.now().strftime('%d-%b-%y %H:%M:%S')
        
        # check if user logged in
        user = self.get_loggedin_user(ctx.author.id)
        if user == None:
            await ctx.send("Please /login to Nestr first.", hidden=True)
            return
        try:
            valid_roles = [role.get("role_id") for role in self.get_synced_roles(ctx)]
            synced_circles = {circle.get("circle_id"): circle for circle in self.get_synced_circles(ctx)}
            res = []
            mention = ""
            if who:
                db_user = self.get_loggedin_user(who.id)
                if not db_user:
                    await ctx.send("That user never logged in to Nestr.", hidden=True)
                    return
                text = who.name
                mention = f"{who.mention}"
                search_text = "label:circleplus-role assignee:"+db_user['nestr_id']
                res = await self.get_search_results(user, search_text, 100)
                res = [role for role in res if role.get("_id") in valid_roles]

            else:
                text = "me"
                mention = f"{ctx.author.mention}"
                search_text = "label:circleplus-role assignee:me"
                res = await self.get_search_results(user, search_text, 100)
                res = [role for role in res if role.get("_id") in valid_roles]
            count = len(res)

            res_sorted = sorted(res, key=lambda res: res.get("parentId"))
            grouped_roles = {}
            for k,g in groupby(res_sorted, key=lambda res: res.get("parentId")):
                grouped_roles[k] = list(g)

            embed = discord.Embed(
                title="Roles",
                color=0x4A44EE,
                description=f"Roles for {mention} (showing top 25)",
                url=nestr_base_url+quote("/search/"+search_text),
            )
            for circle_id in grouped_roles.keys():
                if circle_id not in synced_circles.keys():
                    continue
                circle = synced_circles[circle_id]
                circle_title = circle.get("circle_name")
                circle_link = nestr_base_url+"/n/"+circle_id
                embed.add_field(name=f"🔵 Circle", value=f"[{circle_title}]({circle_link})", inline=False)
                for role in grouped_roles[circle_id]:
                    title = bs(role.get('title', "No title")[:100], "html.parser").text
                    purpose = bs(role.get('purpose', "No title")[:200], "html.parser").text
                    link = nestr_base_url+"/n/"+role.get('_id')
                    embed.add_field(name=f"> 🎭 {title} - {link}", value=f"> {purpose}", inline=False)
                    # \n> >[link]({link})
                if len(grouped_roles) == 0:
                    embed.add_field(name=f"No roles found", value="...", inline=False)

            await ctx.send(embed=embed)
        except Exception as err:
            await ctx.send("{0}".format(err), hidden=True)
            raise
        self.logger.info(f"{ts}: {ctx.author} executed '/roles'\n")

    ##### /todos command ####
    @cog_ext.cog_slash(name="todos",
                       description="Todos for a user or role",
                       options = [
                          create_option(
                              name="who",
                              description="Todos for someone",
                              option_type=SlashCommandOptionType.USER,
                              required=False),
                          create_option(
                              name="role",
                              description="Todos for some role",
                              option_type=SlashCommandOptionType.ROLE,
                              required=False),
                       ])
    async def todos(self, ctx: SlashContext, who: discord.User=None, role: discord.Role=None):
        """Search nestr for Todos"""

        ts = dt.datetime.now().strftime('%d-%b-%y %H:%M:%S')
        
        # check if user logged in
        user = self.get_loggedin_user(ctx.author.id)
        if user == None:
            await ctx.send("Please /login to Nestr first.", hidden=True)
            return
        try:
            valid_role_ids = [role.get("role_id") for role in self.get_synced_roles(ctx)]
            valid_circle_ids = [circle.get("circle_id") for circle in self.get_synced_circles(ctx)]
            res = []
            mention = ""
            if role:
                mention = f"{role.mention}"
                search_text = "label:!project has:completable"
                clean_role_name = bs(role.name, "html.parser").text
                db_roles = [r for r in self.get_synced_roles(ctx) if r.get("discord_name") == clean_role_name]
                if len(db_roles) == 0:
                    await ctx.send(f"Role {role.name} not present on Nestr.", hidden=True)
                    return
                db_role = db_roles[0]
                res = await self.get_search_results(user, search_text, 100, context_id=db_role.get("role_id"))
            elif who:
                db_user = self.get_loggedin_user(who.id)
                if not db_user:
                    await ctx.send("That user never logged in to Nestr.", hidden=True)
                    return
                mention = f"{who.mention}"
                search_text = "label:!project has:completable parent-labels:circleplus-role,circleplus-circle,circleplus-anchor-circle assignee:"+db_user['nestr_id']
                res = await self.get_search_results(user, search_text, 200)

            else:
                mention = f"{ctx.author.mention}"
                search_text = "label:!project has:completable parent-labels:circleplus-role,circleplus-circle,circleplus-anchor-circle assignee:"+user['nestr_id']
                res = await self.get_search_results(user, search_text, 200)
                

            res = [todo for todo in res if todo.get("parentId") in valid_role_ids or todo.get("parentId") in valid_circle_ids]
            res_sorted = sorted(res, key=lambda res: res.get("parentId"))
            grouped_todos = {}
            for k,g in groupby(res_sorted, key=lambda res: res.get("parentId")):
                grouped_todos[k] = list(g)

            embed = discord.Embed(
                title="Todos",
                color=0x4A44EE,
                description=f"Todos for {mention} (page 1)",
                url=nestr_base_url+quote("/search/"+search_text),
            )
            synced_roles = {role.get("role_id"):role for role in self.get_synced_roles(ctx)}
            synced_circles = {circle.get("circle_id"):circle for circle in self.get_synced_circles(ctx)}
            item_count=0
            page=1
            for parent_id in grouped_todos.keys():
                if parent_id in valid_circle_ids:
                    circle = synced_circles[parent_id]
                    circle_title = circle.get("circle_name")
                    circle_link = nestr_base_url+"/n/"+parent_id
                    embed.add_field(name=f"🔵 Circle", value=f"[{circle_title}]({circle_link})", inline=False)
                    for todo in grouped_todos[parent_id]:
                        title = bs(todo.get('title', "No title")[:200], "html.parser").text
                        link = nestr_base_url+"/n/"+todo.get('_id')
                        embed.add_field(name=f"> 📃 {title}", value=f"> 🔗 [link]({link})", inline=False)
                        item_count+=1
                elif parent_id in valid_role_ids:
                    role = synced_roles[parent_id]
                    role_id = role.get("role_id")
                    role_title = role.get("role_name")
                    role_link = nestr_base_url+"/n/"+parent_id
                    embed.add_field(name=f"  🎭Role", value=f"[{role_title}]({role_link})", inline=False)
                    for todo in grouped_todos[role_id]:
                        title = bs(todo.get('title', "No title")[:200], "html.parser").text
                        link = nestr_base_url+"/n/"+todo.get('_id')
                        embed.add_field(name=f"> 📃 {title}", value=f"> 🔗 [link]({link})", inline=False)
                        item_count+=1
                    
                if item_count > 20:
                    await ctx.send(embed=embed)
                    page+=1
                    item_count=0
                    embed = discord.Embed(
                        title="Todos",
                        color=0x4A44EE,
                        description=f"Todos for {mention} (page {page})",
                        url=nestr_base_url+quote("/search/"+search_text),
                    )

                    
                if len(grouped_todos) == 0:
                    embed.add_field(name=f"No todos found", value="...", inline=False)

            await ctx.send(embed=embed)
        except Exception as err:
            await ctx.send("{0}".format(err), hidden=True)
            raise
        self.logger.info(f"{ts}: {ctx.author} executed '/todos'\n")


def setup(bot):
    bot.add_cog(NestrCog(bot))