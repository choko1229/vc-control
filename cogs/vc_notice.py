import discord
from discord.ext import commands
import settings
from utils.embed_utils import embed_notice_start, embed_notice_end


class VCNotice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.sessions = {}  # vc_id → session情報

    def ensure_session(self, vc, member, now):
        if vc.id not in self.sessions:
            self.sessions[vc.id] = {
                "start": now,
                "starter_id": member.id,
                "notice_msg_id": None,
                "participants": {}
            }
        return self.sessions[vc.id]

    def leave_session(self, vc_id, member, now):
        sess = self.sessions.get(vc_id)
        if not sess:
            return
        parts = sess["participants"].get(member.id)
        if parts and parts["joined_at"]:
            sec = int((now - parts["joined_at"]).total_seconds())
            parts["total_sec"] += sec
            parts["joined_at"] = None

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return

        now = discord.utils.utcnow()

        # 入室
        if after.channel and after.channel.category and after.channel.category.id == settings.VC_CATEGORY_ID:
            vc = after.channel

            # セッション開始
            if len(vc.members) == 1:
                sess = self.ensure_session(vc, member, now)
                # 開始通知
                notice_ch = member.guild.get_channel(settings.NOTICE_CHANNEL_ID)
                if notice_ch:
                    msg = await notice_ch.send(embed=embed_notice_start(member, now))
                    sess["notice_msg_id"] = msg.id
                sess["participants"][member.id] = {
                    "name": member.display_name,
                    "total_sec": 0,
                    "joined_at": now
                }
            else:
                # 参加者追加
                sess = self.sessions.get(vc.id)
                if sess:
                    sess["participants"][member.id] = {
                        "name": member.display_name,
                        "total_sec": 0,
                        "joined_at": now
                    }

        # 退室
        if before.channel and before.channel.category and before.channel.category.id == settings.VC_CATEGORY_ID:
            vc = before.channel
            if vc.id not in self.sessions:
                return

            # 退室処理
            sess = self.sessions[vc.id]
            parts = sess["participants"].get(member.id)
            if parts and parts["joined_at"]:
                sec = int((now - parts["joined_at"]).total_seconds())
                parts["total_sec"] += sec
                parts["joined_at"] = None

            # 無人 → セッション終了
            if len(vc.members) == 0:
                started = sess["start"]
                notice_ch = member.guild.get_channel(settings.NOTICE_CHANNEL_ID)

                # 開始Embed削除
                if notice_ch and sess["notice_msg_id"]:
                    try:
                        msg = await notice_ch.fetch_message(sess["notice_msg_id"])
                        await msg.delete()
                    except:
                        pass

                # 終了通知
                if notice_ch:
                    await notice_ch.send(
                        embed=embed_notice_end(vc.name, started, now, sess["participants"])
                    )

                self.sessions.pop(vc.id, None)


async def setup(bot):
    await bot.add_cog(VCNotice(bot))
