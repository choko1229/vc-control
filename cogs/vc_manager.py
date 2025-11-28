import discord
from discord.ext import commands
import asyncio
import settings
from utils.embed_utils import embed_join, embed_leave


class VCManager(commands.Cog):
    """
    - BASE_VC 入室 → 個人VC作成＆移動
    - VC入退室時に VC テキスト（VoiceChannel）へ Join/Leave Embed を送信
    - 参加者の joined_at / total_sec 記録は vc_notice が担当するので、
      ここでは "VCテキスト通知" と "個人VC生成" のみを担当
    """

    def __init__(self, bot):
        self.bot = bot

    async def create_personal_vc(self, member: discord.Member) -> discord.VoiceChannel:
        """
        個人VCを自動生成する。
        既に存在する場合はそれを返す。
        """
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
            reason="個人VCの自動作成"
        )
        return new_vc

    async def send_vc_embed(self, vc: discord.VoiceChannel, embed: discord.Embed):
        """VCのテキストメッセージ欄にEmbedを送信（Pycordの拡張機能前提）"""
        try:
            await vc.send(embed=embed)
        except Exception as e:
            print(f"[VCテキスト送信失敗] {e}")

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return

        # ===== BASE VC に入った時：個人VCへ誘導 =====
        if after.channel and after.channel.id == settings.BASE_VC_ID:
            try:
                personal_vc = await self.create_personal_vc(member)

                if member.voice and member.voice.channel.id != personal_vc.id:
                    await member.move_to(personal_vc, reason="個人VCへ移動")

            except Exception as e:
                print(f"[個人VC作成失敗] {e}")

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

        # ===== 退室側処理 =====
        if (
            before.channel
            and before.channel.category
            and before.channel.category.id == settings.VC_CATEGORY_ID
            and before.channel.id != settings.BASE_VC_ID
        ):
            vc_before = before.channel
            await self.send_vc_embed(vc_before, embed_leave(member))


async def setup(bot):
    await bot.add_cog(VCManager(bot))
