# cogs/vc_manager.py

import discord
from discord.ext import commands
import settings
from utils.voice_utils import is_channel_transition
from utils.embed_utils import embed_join, embed_leave


class VCManager(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def create_personal_vc(self, member: discord.Member) -> discord.VoiceChannel:
        guild = member.guild
        category = guild.get_channel(settings.VC_CATEGORY_ID)

        if not isinstance(category, discord.CategoryChannel):
            raise RuntimeError("VC_CATEGORY_ID が CategoryChannel ではありません。")

        vc_name = f"{member.display_name}のVC"

        # 既存VCチェック
        for ch in category.voice_channels:
            if ch.name == vc_name:
                return ch

        # 新規作成
        new_vc = await guild.create_voice_channel(
            name=vc_name,
            category=category,
            reason="個人VCの自動作成",
        )
        return new_vc

    async def send_vc_embed(self, vc: discord.VoiceChannel, embed: discord.Embed):
        try:
            await vc.send(embed=embed)
        except Exception as e:
            print(f"[VCテキスト送信失敗] {e}")

    async def broadcast_dashboard(self):
        if hasattr(self.bot, "dashboard"):
            try:
                await self.bot.dashboard.broadcast_vc_update()
            except Exception as e:
                print(f"[Dashboard broadcast error] {e}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return

        # ミュート切り替えや画面共有など、同一VC内の状態変化は無視
        if not is_channel_transition(before, after):
            return

        # BASE VC → 個人VC への誘導
        if after.channel and after.channel.id == settings.BASE_VC_ID:
            try:
                personal_vc = await self.create_personal_vc(member)
                if member.voice and member.voice.channel.id != personal_vc.id:
                    await member.move_to(personal_vc, reason="個人VCへ移動")
            except Exception as e:
                print(f"[個人VC作成/移動失敗] {e}")
            # ダッシュボードに反映
            await self.broadcast_dashboard()
            return

        # ===== 入室側処理 =====
        if (
            after.channel
            and after.channel.category
            and after.channel.category.id == settings.VC_CATEGORY_ID
            and after.channel.id != settings.BASE_VC_ID
        ):
            vc_after = after.channel
            await self.send_vc_embed(vc_after, embed_join(member))
            await self.broadcast_dashboard()

        # ===== 退室側処理 =====
        if (
            before.channel
            and before.channel.category
            and before.channel.category.id == settings.VC_CATEGORY_ID
            and before.channel.id != settings.BASE_VC_ID
        ):
            vc_before = before.channel
            await self.send_vc_embed(vc_before, embed_leave(member))
            await self.broadcast_dashboard()


def setup(bot):
    bot.add_cog(VCManager(bot))
