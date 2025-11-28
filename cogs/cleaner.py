import discord
from discord.ext import commands
import asyncio
import settings
from utils.embed_utils import embed_empty_notice


class VCCleaner(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.tasks = {}  # vc_id → asyncio.Task

    async def schedule_delete(self, vc: discord.VoiceChannel):
        try:
            await asyncio.sleep(settings.FIRST_EMPTY_NOTICE_SEC)

            if len(vc.members) == 0:
                try:
                    await vc.send(embed=embed_empty_notice())
                except:
                    pass

            await asyncio.sleep(settings.FINAL_DELETE_SEC)

            if len(vc.members) == 0:
                try:
                    await vc.delete(reason="無人削除")
                except:
                    pass

        except asyncio.CancelledError:
            return
        finally:
            self.tasks.pop(vc.id, None)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):

        # 入室 → 削除キャンセル
        if after.channel and after.channel.id != settings.BASE_VC_ID:
            if after.channel.category and after.channel.category.id == settings.VC_CATEGORY_ID:
                t = self.tasks.get(after.channel.id)
                if t and not t.done():
                    t.cancel()

        # 退室 → 無人なら削除へ
        if before.channel and before.channel.category and before.channel.category.id == settings.VC_CATEGORY_ID:
            vc = before.channel
            if len(vc.members) == 0:
                if vc.id not in self.tasks:
                    self.tasks[vc.id] = asyncio.create_task(self.schedule_delete(vc))


async def setup(bot):
    await bot.add_cog(VCCleaner(bot))
