# cogs/vc_manager.py

import discord
from discord.ext import commands
import settings
from utils.embed_utils import embed_join, embed_leave


class VCManager(commands.Cog):
    """
    - BASE_VC への入室 → 個人VC作成 + 移動
    - VC入退室時 → VCテキストへ Join/Leave Embed 送信
    - WebDashboard へ VC状態更新通知 (broadcast_vc_update)
    """

    def __init__(self, bot):
        self.bot = bot

    # ----------------------------------------------------
    # 個人VCの自動作成
    # ----------------------------------------------------
    async def create_personal_vc(self, member: discord.Member) -> discord.VoiceChannel:
        guild = member.guild
        category = guild.get_channel(settings.VC_CATEGORY_ID)

        if not isinstance(category, discord.CategoryChannel):
            raise RuntimeError("VC_CATEGORY_ID が有効なカテゴリではありません。")

        vc_name = f"{member.display_name}のVC"

        # すでに同名VCがあればそれを使用
        for ch in category.voice_channels:
            if ch.name == vc_name:
                return ch

        # 新規VC作成
        new_vc = await guild.create_voice_channel(
            name=vc_name,
            category=category,
            reason="個人VCの自動作成"
        )
        return new_vc

    # ----------------------------------------------------
    # VCへのEmbed送信
    # ----------------------------------------------------
    async def send_vc_embed(self, vc: discord.VoiceChannel, embed: discord.Embed):
        try:
            await vc.send(embed=embed)
        except Exception as e:
            print(f"[VCテキスト送信失敗] {e}")

    # ----------------------------------------------------
    # VC入退室イベント
    # ----------------------------------------------------
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):

        if member.bot:
            return

        # ─────────────────────────────────────
        # BASE VC に入ったとき：個人VCの作成＆移動
        # ─────────────────────────────────────
        if after.channel and after.channel.id == settings.BASE_VC_ID:
            try:
                personal_vc = await self.create_personal_vc(member)

                if member.voice and member.voice.channel.id != personal_vc.id:
                    await member.move_to(personal_vc, reason="個人VCへ移動")
            except Exception as e:
                print(f"[個人VC作成失敗] {e}")

            # 🔥 ダッシュボード更新を送信
            if hasattr(self.bot, "dashboard"):
                await self.bot.dashboard.broadcast_vc_update()

            return

        # ─────────────────────────────────────
        # 入室処理（VC_CATEGORY 内）
        # ─────────────────────────────────────
        if (
            after.channel
            and after.channel.category
            and after.channel.category.id == settings.VC_CATEGORY_ID
            and after.channel.id != settings.BASE_VC_ID
        ):
            vc_after = after.channel
            # 入室Embed
            await self.send_vc_embed(vc_after, embed_join(member))

            # 🔥 ダッシュボード更新
            if hasattr(self.bot, "dashboard"):
                await self.bot.dashboard.broadcast_vc_update()

        # ─────────────────────────────────────
        # 退室処理（VC_CATEGORY 内）
        # ─────────────────────────────────────
        if (
            before.channel
            and before.channel.category
            and before.channel.category.id == settings.VC_CATEGORY_ID
            and before.channel.id != settings.BASE_VC_ID
        ):
            vc_before = before.channel
            # 退室Embed
            await self.send_vc_embed(vc_before, embed_leave(member))

            # 🔥 ダッシュボード更新
            if hasattr(self.bot, "dashboard"):
                await self.bot.dashboard.broadcast_vc_update()


def setup(bot):
    bot.add_cog(VCManager(bot))
