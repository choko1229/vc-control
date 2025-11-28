# cogs/presence.py

import discord
from discord.ext import commands
import settings


class PresenceCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def update_presence(self):
        # VCカテゴリ内の合計人数をカウント
        total_members = 0
        for g in self.bot.guilds:
            for ch in g.voice_channels:
                if ch.category and ch.category.id == settings.VC_CATEGORY_ID:
                    total_members += len(ch.members)

        if total_members == 0:
            activity = discord.Game("通話はされていません。")
        else:
            activity = discord.Game(f"{total_members}人が通話中！")

        await self.bot.change_presence(activity=activity)

        # ダッシュボードへVC状況をブロードキャスト
        if hasattr(self.bot, "dashboard"):
            try:
                await self.bot.dashboard.broadcast_vc_update()
            except Exception as e:
                print(f"[Dashboard broadcast error on_ready] {e}")

    @commands.Cog.listener()
    async def on_ready(self):
        await self.update_presence()

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return
        # ミュート切り替えなどは無視したければ同様に条件追加
        if before.channel == after.channel:
            return

        await self.update_presence()


def setup(bot):
    bot.add_cog(PresenceCog(bot))
