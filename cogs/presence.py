# cogs/presence.py

import discord
from discord.ext import commands
import settings


class Presence(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def update_vc_status(self, guild: discord.Guild):
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
        # Bot 起動時に一度ステータス更新＋ダッシュボード更新
        for g in self.bot.guilds:
            await self.update_vc_status(g)
        if hasattr(self.bot, "dashboard"):
            try:
                await self.bot.dashboard.broadcast_vc_update(self.bot)
            except Exception as e:
                print(f"[Dashboard broadcast error on_ready] {e}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState):
        if not member.guild:
            return

        # ステータス更新
        await self.update_vc_status(member.guild)

        # ダッシュボード更新
        if hasattr(self.bot, "dashboard"):
            try:
                await self.bot.dashboard.broadcast_vc_update(self.bot)
            except Exception as e:
                print(f"[Dashboard broadcast error] {e}")


def setup(bot):
    bot.add_cog(Presence(bot))
