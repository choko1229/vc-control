import discord
from discord.ext import commands
import settings
from utils.embed_utils import embed_notice_start, embed_notice_end, embed_manage_panel
from utils import db_utils
from utils.voice_utils import is_channel_transition


class VCNotice(commands.Cog):
    """
    VC開始/終了のサマリ通知＋履歴保存（BASE VC は対象外）
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # vc_id → セッション情報
        self.sessions = {}

    def ensure_session(self, vc: discord.VoiceChannel, member: discord.Member, now):
        if vc.id not in self.sessions:
            self.sessions[vc.id] = {
                "start": now,
                "starter_id": member.id,
                "notice_msg_id": None,
                "manage_msg_id": None,
                "participants": {},
                "team_channels": {},
            }
        return self.sessions[vc.id]

    def ensure_session_by_voice(self, vc: discord.VoiceChannel, now, starter=None):
        """Create or return a session for the given VC.

        If ``starter`` is omitted, the first non-bot member in the channel is
        used as the starter id. This is used by dashboard/team APIs that may be
        called after the initial join hook.
        """

        starter_member = starter or next((m for m in vc.members if not m.bot), None)
        if not starter_member:
            return None
        return self.ensure_session(vc, starter_member, now)

    def base_session_for_channel(self, channel: discord.VoiceChannel | None):
        if not channel:
            return None
        for base_id, sess in self.sessions.items():
            if base_id == channel.id:
                return base_id
            if channel.id in sess.get("team_channels", {}).values():
                return base_id
        return None

    def build_manage_url(self, guild_id: int, vc_id: int) -> str:
        base = settings.DASHBOARD_BASE_URL.rstrip("/") if settings.DASHBOARD_BASE_URL else ""
        if base:
            return f"{base}/guild/{guild_id}/vc/{vc_id}"
        return f"/guild/{guild_id}/vc/{vc_id}"

    def member_join(self, vc_id: int, member: discord.Member, now):
        sess = self.sessions.get(vc_id)
        if not sess:
            return

        parts = sess["participants"].get(member.id)
        if parts is None:
            parts = {
                "name": member.display_name,
                "total_sec": 0,
                "joined_at": now,
                "team": None,
            }
            sess["participants"][member.id] = parts
        else:
            parts["name"] = member.display_name
            if parts.get("joined_at") is None:
                parts["joined_at"] = now
            parts.setdefault("team", None)

    def member_leave(self, vc_id: int, member: discord.Member, now):
        sess = self.sessions.get(vc_id)
        if not sess:
            return

        parts = sess["participants"].get(member.id)
        if not parts:
            return

        joined_at = parts.get("joined_at")
        if joined_at:
            sec = int((now - joined_at).total_seconds())
            parts["total_sec"] = int(parts.get("total_sec", 0)) + sec
            parts["joined_at"] = None
        parts["name"] = member.display_name

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ):
        if member.bot:
            return

        # ミュートや画面共有などの状態変更は無視し、入退室のみを対象とする
        if not is_channel_transition(before, after):
            return

        now = discord.utils.utcnow()

        before_base = self.base_session_for_channel(before.channel)
        after_base = self.base_session_for_channel(after.channel)

        # チームVC間の移動は同じセッションとして扱い、参加時間を途切れさせない
        if before_base and after_base and before_base == after_base and after.channel:
            return

        # ===== 入室 side（BASE VC 除外） =====
        if (
            after.channel
            and after.channel.id != settings.BASE_VC_ID
            and after.channel.category
            and after.channel.category.id == settings.VC_CATEGORY_ID
        ):
            vc = after.channel

            # チームVCの場合はセッションを開始済みの親VCに紐づけるだけ
            parent_id = self.base_session_for_channel(vc)
            if parent_id and parent_id in self.sessions:
                self.member_join(parent_id, member, now)
                return

            if len(vc.members) == 1:
                # セッション開始
                sess = self.ensure_session(vc, member, now)
                self.member_join(vc.id, member, now)

                notice_ch = member.guild.get_channel(settings.NOTICE_CHANNEL_ID)
                if notice_ch:
                    msg = await notice_ch.send(embed=embed_notice_start(member, now))
                    sess["notice_msg_id"] = msg.id

                manage_url = self.build_manage_url(member.guild.id, vc.id)
                try:
                    msg = await vc.send(
                        embed=embed_manage_panel(
                            vc.name, manage_url, starter_name=member.display_name
                        )
                    )
                    sess["manage_msg_id"] = msg.id
                except Exception as e:
                    print(f"[VC管理リンク送信失敗] {e}")
                    if notice_ch:
                        try:
                            await notice_ch.send(
                                embed=embed_manage_panel(
                                    vc.name, manage_url, starter_name=member.display_name
                                )
                            )
                        except Exception:
                            pass
            else:
                if vc.id in self.sessions:
                    self.member_join(vc.id, member, now)

        # ===== 退室 side（BASE VC 除外） =====
        if (
            before.channel
            and before.channel.id != settings.BASE_VC_ID
            and before.channel.category
            and before.channel.category.id == settings.VC_CATEGORY_ID
        ):
            vc = before.channel

            parent_id = self.base_session_for_channel(vc)
            if parent_id and parent_id in self.sessions and parent_id != vc.id:
                self.member_leave(parent_id, member, now)
                return

            if vc.id in self.sessions:
                self.member_leave(vc.id, member, now)

            # 無人になったらセッション終了
            if len(vc.members) == 0 and vc.id in self.sessions:
                sess = self.sessions.pop(vc.id)
                started_at = sess["start"]
                ended_at = now
                participants = sess["participants"]

                notice_ch = member.guild.get_channel(settings.NOTICE_CHANNEL_ID)

                # 開始Embed削除
                if notice_ch and sess.get("notice_msg_id"):
                    try:
                        msg = await notice_ch.fetch_message(sess["notice_msg_id"])
                        await msg.delete()
                    except Exception:
                        pass

                # 管理パネルEmbed削除（VC内で送れていれば）
                if sess.get("manage_msg_id"):
                    try:
                        msg = await vc.fetch_message(sess["manage_msg_id"])
                        await msg.delete()
                    except Exception:
                        pass

                # 終了Embed送信
                if notice_ch:
                    try:
                        await notice_ch.send(
                            embed=embed_notice_end(
                                vc.name,
                                started_at,
                                ended_at,
                                participants,
                            )
                        )
                    except Exception as e:
                        print(f"[終了通知送信失敗] {e}")

                # 履歴をDBに保存
                try:
                    db_utils.insert_session(
                        guild_id=member.guild.id,
                        vc_id=vc.id,
                        vc_name=vc.name,
                        started_at=started_at,
                        ended_at=ended_at,
                        participants=participants,
                    )
                except Exception as e:
                    print(f"[DB保存失敗] {e}")


def setup(bot: commands.Bot):
    bot.add_cog(VCNotice(bot))
