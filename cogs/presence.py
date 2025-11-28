import discord
from discord.ext import commands
import settings


class Presence(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def update_status(self, guild: discord.Guild):
        count = 0
        for ch in guild.voice_channels:
            if ch.category and ch.category.id == settings.VC_CATEGORY_ID:
                count += len(ch.members)

        name = (
            "通話はされていません。" if count == 0
            else f"{count}人が通話中！"
        )

        await self.bot.change_presence(activity=discord.Game(name=name))

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if not member.guild:
            return
        await self.update_status(member.guild)

    @commands.Cog.listener()
    async def on_ready(self):
        for g in self.bot.guilds:
            await self.update_status(g)


async def setup(bot):
    await bot.add_cog(Presence(bot))
