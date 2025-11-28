import discord
from discord.ext import commands
import settings


class Presence(commands.Cog):
    """VC人数に応じてBOTステータスを更新"""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def update_status(self, guild: discord.Guild):
        count = 0
        for ch in guild.voice_channels:
            if ch.category and ch.category.id == settings.VC_CATEGORY_ID:
                count += len(ch.members)

        if count == 0:
            activity = discord.Game(name="通話はされていません。")
        else:
            activity = discord.Game(name=f"{count}人が通話中！")

        await self.bot.change_presence(status=discord.Status.online, activity=activity)

    @commands.Cog.listener()
    async def on_ready(self):
        for g in self.bot.guilds:
            await self.update_status(g)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before, after):
        if not member.guild:
            return
        await self.update_status(member.guild)


def setup(bot: commands.Bot):
    bot.add_cog(Presence(bot))
