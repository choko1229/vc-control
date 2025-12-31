import discord
from discord.ext import commands

from utils.embed_utils import embed_team_overview
import settings

TEAM_EMOJIS = {
    "A": "🇦",
    "B": "🇧",
    "C": "🇨",
    "D": "🇩",
}

SPLIT_EMOJI = "🔀"
GATHER_EMOJI = "🏠"


class VCTeam(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.team_messages: dict[int, dict] = {}

    def _notice(self):
        return self.bot.get_cog("VCNotice")

    def _can_manage(self, member: discord.Member | None, starter_id: int | None):
        if member is None:
            return False
        if member.guild_permissions.administrator:
            return True
        return starter_id is not None and member.id == starter_id

    def _get_session(self, vc: discord.VoiceChannel, starter=None):
        notice = self._notice()
        if not notice:
            return None
        return notice.ensure_session_by_voice(vc, discord.utils.utcnow(), starter=starter)

    def _assign_team(self, vc: discord.VoiceChannel, member: discord.Member, team: str):
        session = self._get_session(vc, starter=member)
        if not session:
            return None
        participants = session.setdefault("participants", {})
        info = participants.get(member.id)
        if info is None:
            info = {
                "name": member.display_name,
                "total_sec": 0,
                "joined_at": discord.utils.utcnow(),
                "team": None,
            }
            participants[member.id] = info
        info["team"] = team
        info["name"] = member.display_name
        return session

    def _collect_assignments(self, session: dict, vc: discord.VoiceChannel):
        assignments = {"A": [], "B": [], "C": [], "D": []}
        participants = session.get("participants", {}) if session else {}
        members = list(vc.members)
        for ch_id in session.get("team_channels", {}).values() if session else []:
            ch = vc.guild.get_channel(ch_id)
            if isinstance(ch, discord.VoiceChannel):
                members.extend(ch.members)

        for m in members:
            pdata = participants.get(m.id)
            team = pdata.get("team") if pdata else None
            if team in assignments:
                assignments[team].append(m.display_name)
        return assignments

    async def _ensure_team_channel(self, vc: discord.VoiceChannel, team: str, session: dict):
        team_channels = session.setdefault("team_channels", {})
        guild = vc.guild
        if team in team_channels:
            existing = guild.get_channel(team_channels[team])
            if isinstance(existing, discord.VoiceChannel):
                return existing

        name = f"{vc.name}-{team}"
        new_ch = await guild.create_voice_channel(
            name=name,
            category=vc.category,
            bitrate=min(vc.bitrate, guild.bitrate_limit),
            user_limit=vc.user_limit,
            reason="チームVC自動生成",
        )
        team_channels[team] = new_ch.id
        return new_ch

    async def split_teams(self, vc: discord.VoiceChannel, starter_id: int | None):
        session = self._get_session(vc)
        if not session:
            return "セッション情報がありません"

        participants = session.get("participants", {})
        for member in list(vc.members):
            if member.bot:
                continue
            pdata = participants.get(member.id) or {}
            team = pdata.get("team")
            if not team or team not in TEAM_EMOJIS:
                continue
            if starter_id and member.id == starter_id:
                continue
            dest = await self._ensure_team_channel(vc, team, session)
            try:
                await member.move_to(dest, reason="チームVCへ移動")
            except Exception:
                continue
        return None

    async def gather_teams(self, vc: discord.VoiceChannel):
        session = self._get_session(vc)
        if not session:
            return "セッション情報がありません"

        team_channels = session.get("team_channels", {})
        guild = vc.guild
        for ch_id in list(team_channels.values()):
            ch = guild.get_channel(ch_id)
            if not isinstance(ch, discord.VoiceChannel):
                continue
            for member in list(ch.members):
                try:
                    await member.move_to(vc, reason="チーム集合")
                except Exception:
                    continue
            try:
                await ch.delete(reason="チーム集合後のクリーンアップ")
            except Exception:
                pass
        session["team_channels"] = {}
        return None

    def _build_team_embed(self, vc: discord.VoiceChannel, starter_id: int | None):
        session = self._get_session(vc)
        starter_name = None
        if session:
            participants = session.get("participants", {})
            if starter_id and starter_id in participants:
                starter_name = participants[starter_id].get("name")
        assignments = self._collect_assignments(session or {}, vc)
        return embed_team_overview(vc.name, assignments, starter_name=starter_name)

    @commands.command(name="team")
    async def team_panel(self, ctx: commands.Context):
        if not ctx.author.voice or not ctx.author.voice.channel:
            await ctx.reply("ボイスチャンネルに参加してから実行してください。")
            return

        vc = ctx.author.voice.channel
        if vc.category and vc.category.id != settings.VC_CATEGORY_ID:
            await ctx.reply("管理対象のVCでのみ利用できます。")
            return

        session = self._get_session(vc, starter=ctx.author)
        if not session:
            await ctx.reply("セッション情報を準備できませんでした。")
            return

        starter_id = session.get("starter_id")
        embed = self._build_team_embed(vc, starter_id)
        msg = await ctx.send(embed=embed)
        self.team_messages[msg.id] = {
            "vc_id": vc.id,
            "guild_id": ctx.guild.id,
            "starter_id": starter_id,
        }

        for emoji in TEAM_EMOJIS.values():
            await msg.add_reaction(emoji)
        await msg.add_reaction(SPLIT_EMOJI)
        await msg.add_reaction(GATHER_EMOJI)

    async def _handle_team_reaction(self, payload: discord.RawReactionActionEvent):
        if payload.message_id not in self.team_messages:
            return
        if payload.user_id == self.bot.user.id:
            return

        data = self.team_messages[payload.message_id]
        guild = self.bot.get_guild(data["guild_id"])
        if not guild:
            return
        member = guild.get_member(payload.user_id)
        if not member:
            return
        vc = guild.get_channel(data["vc_id"])
        if not isinstance(vc, discord.VoiceChannel):
            return

        session = self._get_session(vc)
        starter_id = session.get("starter_id") if session else None
        emoji = str(payload.emoji)

        allowed_channels = {vc.id}
        if session:
            allowed_channels.update(session.get("team_channels", {}).values())
        if not member.voice or not member.voice.channel or member.voice.channel.id not in allowed_channels:
            return

        if emoji in TEAM_EMOJIS.values():
            team = next((k for k, v in TEAM_EMOJIS.items() if v == emoji), None)
            if not team:
                return
            self._assign_team(vc, member, team)
        elif emoji == SPLIT_EMOJI:
            if not self._can_manage(member, starter_id):
                return
            err = await self.split_teams(vc, starter_id)
            if err:
                try:
                    await member.send(err)
                except Exception:
                    pass
        elif emoji == GATHER_EMOJI:
            if not self._can_manage(member, starter_id):
                return
            await self.gather_teams(vc)

        try:
            channel = guild.get_channel(payload.channel_id)
            if isinstance(channel, discord.TextChannel):
                msg = await channel.fetch_message(payload.message_id)
                embed = self._build_team_embed(vc, starter_id)
                await msg.edit(embed=embed)
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        await self._handle_team_reaction(payload)


def setup(bot: commands.Bot):
    bot.add_cog(VCTeam(bot))
