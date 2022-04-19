import logging.config
import discord
from discord.ext import commands
from discord_slash import cog_ext, SlashContext


class Admin(commands.Cog, name='Admin'):
    """Admin-only commands that make the bot dynamic."""

    def __init__(self, bot):
        self.logger = logging.getLogger(__name__)
        self.bot = bot
        self.dir = "cogs"

    @cog_ext.cog_slash(name="load", description="Load module/cog")
    @commands.has_any_role("admin")
    async def load(self, ctx: SlashContext, module: str):
        """
        Loads a module.
        """
        try:
            self.bot.load_extension(self.dir + "." + module)
        except Exception as e:
            await ctx.send('\N{PISTOL}')
            await ctx.send('{}: {}'.format(type(e).__name__, e))
        else:
            self.logger.info(f'{module} loaded')
            await ctx.send('\N{OK HAND SIGN}')

    @load.error
    async def load_error(self, ctx: SlashContext, error):
        """
        Error catcher for load command
        :param ctx:
        :param error:
        """
        msg = f'load module error: {error}'
        await ctx.send(msg, hidden=True)

    @cog_ext.cog_slash(name="unload", description="Unload module/cog")
    @commands.has_any_role("admin")
    async def unload(self, ctx: SlashContext, module: str):
        """
        Unloads a module.
        """
        try:
            self.bot.unload_extension(self.dir + "." + module)
        except Exception as e:
            await ctx.send('\N{PISTOL}')
            await ctx.send('{}: {}'.format(type(e).__name__, e))
        else:
            self.logger.info(f'{module} unloaded')
            await ctx.send('\N{OK HAND SIGN}')

    @unload.error
    async def unload_error(self, ctx: SlashContext, error):
        """
        Error catcher for unload command
        :param ctx:
        :param error:
        """
        msg = f'unload module error: {error}'
        await ctx.send(msg, hidden=True)

    @cog_ext.cog_slash(name="reload", description="Reload module/cog")
    @commands.has_any_role("admin")
    async def _reload(self, ctx: SlashContext, module: str):
        """
        Reloads a module.
        """
        try:
            self.bot.unload_extension(self.dir + "." + module)
            self.bot.load_extension(self.dir + "." + module)
        except Exception as e:
            await ctx.send('\N{PISTOL}')
            await ctx.send('{}: {}'.format(type(e).__name__, e))
        else:
            self.logger.info(f'{module} reloaded')
            await ctx.send('\N{OK HAND SIGN}')

    @_reload.error
    async def _reload_error(self, ctx: SlashContext, error):
        """
        Error catcher for _reload command
        :param ctx:
        :param error:
        """
        msg = f'reload module error: {error}'
        await ctx.send(msg, hidden=True)

    @cog_ext.cog_slash(name="help", description="Nestr Bot Help")
    async def help(self, ctx: SlashContext):
        """
        /help - Help file
        """
        embed = discord.Embed(
            title="⚠️ Nestr Bot Commands:",
            description="All Nestr Bot commands",
            color=0xED4245,
        )
        embed.add_field(name="/inbox", value="   - Adds a new todo to your inbox")
        embed.set_footer(text="Made with Python | https://github.com/juliomonteiro/",
                         icon_url="https://i.imgur.com/5BFecvA.png")
        return await ctx.send(embed=embed)

def setup(bot):
    bot.add_cog(Admin(bot))