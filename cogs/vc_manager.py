import discord
from discord.ext import commands
import settings
from utils.embed_utils import embed_join, embed_leave


class VCManager(commands.Cog):
    """
    - BASE_VC 入室 → 個人VC作成＆移動
    - VC入退室時に VCテキストへ Join/Leave Embed を送信（BASE VC は除外）
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def create_personal_vc(self, member: discord.Member) -> discord.VoiceChannel:
        """個人VCを自動生成。既にあればそれを返す。"""
        guild = member.guild
        category = guild.get_channel(settings.VC_CATEGORY_ID)

        if not isinstance(category, discord.CategoryChannel):
            raise RuntimeError("VC_CATEGORY_ID が CategoryChannel ではありません。")

        vc_name = f"{member.display_name}のVC"

        for ch in category.voice_channels:
            if ch.name == vc_name:
                return ch

        new_vc = await guild.create_voice_channel(
            name=vc_name,
            category=category,
            reason="個人VCの自動作成",
        )
        return new_vc

    async def send_vc_embed(self, vc: discord.VoiceChannel, embed: discord.Embed):
        """VCのテキスト欄にEmbedを送信"""
        try:
            await vc.send(embed=embed)
        except Exception as e:
            print(f"[VCテキスト送信失敗] {e}")

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        if member.bot:
            return

        # ===== BASE VC 入室 → 個人VC作成＆移動 =====
        if after.channel and after.channel.id == settings.BASE_VC_ID:
            try:
                personal_vc = await self.create_personal_vc(member)
                if member.voice and member.voice.channel.id != personal_vc.id:
                    await member.move_to(personal_vc, reason="個人VCへ移動")
            except Exception as e:
                print(f"[個人VC作成/移動失敗] {e}")
            return  # BASE VC ではここで処理終了

        # ===== 入室側処理（BASE VC は除外） =====
        if (
            after.channel
            and after.channel.id != settings.BASE_VC_ID
            and after.channel.category
            and after.channel.category.id == settings.VC_CATEGORY_ID
        ):
            vc_after: discord.VoiceChannel = after.channel
            await self.send_vc_embed(vc_after, embed_join(member))

        # ===== 退室側処理（BASE VC は除外） =====
        if (
            before.channel
            and before.channel.id != settings.BASE_VC_ID
            and before.channel.category
            and before.channel.category.id == settings.VC_CATEGORY_ID
        ):
            vc_before: discord.VoiceChannel = before.channel
            await self.send_vc_embed(vc_before, embed_leave(member))


def setup(bot: commands.Bot):
    bot.add_cog(VCManager(bot))
