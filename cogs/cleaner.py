import discord
from discord.ext import commands
import asyncio
import settings
from utils.embed_utils import embed_empty_notice


class VCCleaner(commands.Cog):
    """
    無人VCの自動削除（BASE VC は対象外）
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.tasks: dict[int, asyncio.Task] = {}

    async def schedule_delete(self, vc: discord.VoiceChannel):
        """無人VCを一定時間後に削除（BASE VC は呼ばれない想定だが念のためガード）"""
        if vc.id == settings.BASE_VC_ID:
            return

        try:
            await asyncio.sleep(settings.FIRST_EMPTY_NOTICE_SEC)

            if len(vc.members) == 0 and vc.id != settings.BASE_VC_ID:
                try:
                    await vc.send(embed=embed_empty_notice())
                except Exception:
                    pass

            await asyncio.sleep(settings.FINAL_DELETE_SEC)

            if len(vc.members) == 0 and vc.id != settings.BASE_VC_ID:
                try:
                    await vc.delete(reason="無人削除")
                except Exception:
                    pass

        except asyncio.CancelledError:
            return
        finally:
            self.tasks.pop(vc.id, None)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        # ===== 入室 → 削除スケジュールのキャンセル（BASE VC 除外） =====
        if (
            after.channel
            and after.channel.id != settings.BASE_VC_ID
            and after.channel.category
            and after.channel.category.id == settings.VC_CATEGORY_ID
        ):
            t = self.tasks.get(after.channel.id)
            if t and not t.done():
                t.cancel()

        # ===== 退室 → 無人なら削除スケジュール開始（BASE VC 除外） =====
        if (
            before.channel
            and before.channel.id != settings.BASE_VC_ID
            and before.channel.category
            and before.channel.category.id == settings.VC_CATEGORY_ID
        ):
            vc = before.channel
            if len(vc.members) == 0 and vc.id not in self.tasks:
                self.tasks[vc.id] = asyncio.create_task(self.schedule_delete(vc))


def setup(bot: commands.Bot):
    bot.add_cog(VCCleaner(bot))
