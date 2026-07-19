from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import discord
from fastapi import WebSocket

from vc_control.embeds import BRAND_BLUE, COLOR_ERROR, COLOR_NOTIFY, COLOR_SUCCESS, COLOR_WARNING, build_embed
from vc_control.i18n import t
from vc_control.models import DEFAULT_TEAM_NAMES, CompletedMember, CompletedSession, GuildConfig, ScheduledVC, SessionSnapshot, SnapshotMember
from vc_control.repositories import ConfigRepository, StatsRepository
from vc_control.utils import format_duration, make_session_key, normalize_ids, utcnow


TIMELINE_EVENT_LABEL_KEYS = {
    "vc_started": "timeline.vc_started",
    "vc_ended": "timeline.vc_ended",
    "member_joined": "timeline.member_joined",
    "member_left": "timeline.member_left",
    "member_moved": "timeline.member_moved",
    "member_mute_changed": "timeline.member_mute_changed",
    "teams_split": "timeline.teams_split",
    "teams_assembled": "timeline.teams_assembled",
    "member_recalled": "timeline.member_recalled",
    "voice_settings_changed": "timeline.voice_settings_changed",
    "team_changed": "timeline.team_changed",
    "bot_restart_restored": "timeline.bot_restart_restored",
    "scheduled_vc_created": "timeline.scheduled_vc_created",
    "web_vc_created": "timeline.web_vc_created",
    "access_changed": "timeline.access_changed",
}

ACCESS_MODE_LABEL_KEYS = {
    "public": "access.mode.public",
    "invite": "access.mode.invite",
    "role": "access.mode.role",
}

LOCAL_TZ = ZoneInfo("Asia/Tokyo")
RANKING_TARGET_LABEL_KEYS = {
    "top_talkers": "ranking.target.top_talkers",
    "top_hosts": "ranking.target.top_hosts",
    "team_splits": "ranking.target.team_splits",
    "night_owls": "ranking.target.night_owls",
}


def _timeline_label(event_type: str, locale: str | None) -> str:
    key = TIMELINE_EVENT_LABEL_KEYS.get(event_type)
    return t(key, locale) if key else event_type


def _access_mode_label(mode: str, locale: str | None) -> str:
    key = ACCESS_MODE_LABEL_KEYS.get(mode)
    return t(key, locale) if key else mode


@dataclass(slots=True)
class LiveParticipant:
    user_id: int
    user_name: str
    joined_at: datetime
    last_transition_at: datetime
    current_channel_id: int | None
    talk_seconds: int = 0
    afk_seconds: int = 0
    afk_channel_seconds: int = 0
    self_mute_seconds: int = 0
    self_deafen_seconds: int = 0
    self_muted: bool = False
    self_deafened: bool = False
    in_afk_channel: bool = False
    current_team: str | None = None
    panel_creator: bool = False

    def accrue(self, now: datetime) -> None:
        elapsed = max(0, int((now - self.last_transition_at).total_seconds()))
        if elapsed <= 0:
            self.last_transition_at = now
            return None
        if self.current_channel_id is not None:
            self.talk_seconds += elapsed
        if self.self_muted or self.self_deafened or self.in_afk_channel:
            self.afk_seconds += elapsed
        if self.self_muted:
            self.self_mute_seconds += elapsed
        if self.self_deafened:
            self.self_deafen_seconds += elapsed
        if self.in_afk_channel:
            self.afk_channel_seconds += elapsed
        self.last_transition_at = now

    def apply_voice_state(self, state: discord.VoiceState | None) -> None:
        self.self_muted = bool(state and state.self_mute)
        self.self_deafened = bool(state and state.self_deaf)
        self.in_afk_channel = bool(state and state.channel and state.channel.guild.afk_channel and state.channel.guild.afk_channel.id == state.channel.id)

    def to_snapshot_member(self) -> SnapshotMember:
        return SnapshotMember(
            user_id=self.user_id,
            user_name=self.user_name,
            joined_at=self.joined_at,
            last_transition_at=self.last_transition_at,
            current_channel_id=self.current_channel_id,
            talk_seconds=self.talk_seconds,
            afk_seconds=self.afk_seconds,
            afk_channel_seconds=self.afk_channel_seconds,
            self_mute_seconds=self.self_mute_seconds,
            self_deafen_seconds=self.self_deafen_seconds,
            self_muted=self.self_muted,
            self_deafened=self.self_deafened,
            in_afk_channel=self.in_afk_channel,
            current_team=self.current_team,
            panel_creator=self.panel_creator,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "user_id": str(self.user_id),
            "user_name": self.user_name,
            "joined_at": self.joined_at.isoformat(),
            "current_channel_id": str(self.current_channel_id) if self.current_channel_id is not None else None,
            "talk_seconds": self.talk_seconds,
            "afk_seconds": self.afk_seconds,
            "current_team": self.current_team,
            "panel_creator": self.panel_creator,
            "self_muted": self.self_muted,
            "self_deafened": self.self_deafened,
            "in_afk_channel": self.in_afk_channel,
        }


@dataclass(slots=True)
class LiveSession:
    session_id: str
    guild_id: int
    guild_name: str
    root_channel_id: int
    root_channel_name: str
    starter_user_id: int
    starter_user_name: str
    owner_user_id: int
    owner_user_name: str
    started_at: datetime
    team_names: list[str]
    team_mode: str
    panel_creator_id: int | None = None
    panel_creator_name: str | None = None
    team_assignments: dict[int, str] = field(default_factory=dict)
    team_channels: dict[str, int] = field(default_factory=dict)
    access_mode: str = "public"
    invited_user_ids: set[str] = field(default_factory=set)
    access_role_ids: set[str] = field(default_factory=set)
    notice_channel_id: int | None = None
    notice_message_id: int | None = None
    member_order: list[int] = field(default_factory=list)
    participants: dict[int, LiveParticipant] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    def active_participants(self) -> list[LiveParticipant]:
        return [participant for participant in self.participants.values() if participant.current_channel_id is not None]

    @property
    def session_key(self) -> tuple[int, int]:
        return (int(self.guild_id), int(self.root_channel_id))

    def to_snapshot(self) -> SessionSnapshot:
        return SessionSnapshot(
            session_id=self.session_id,
            guild_id=self.guild_id,
            root_channel_id=self.root_channel_id,
            root_channel_name=self.root_channel_name,
            starter_user_id=self.starter_user_id,
            starter_user_name=self.starter_user_name,
            owner_user_id=self.owner_user_id,
            owner_user_name=self.owner_user_name,
            started_at=self.started_at,
            panel_creator_id=self.panel_creator_id,
            panel_creator_name=self.panel_creator_name,
            team_names=self.team_names.copy(),
            team_mode=self.team_mode,
            team_assignments={str(key): value for key, value in self.team_assignments.items()},
            team_channels=self.team_channels.copy(),
            access_mode=self.access_mode,
            invited_user_ids=sorted(self.invited_user_ids),
            access_role_ids=sorted(self.access_role_ids),
            notice_channel_id=self.notice_channel_id,
            notice_message_id=self.notice_message_id,
            member_order=self.member_order.copy(),
            members=[participant.to_snapshot_member() for participant in self.participants.values()],
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "guild_id": str(self.guild_id),
            "guild_name": self.guild_name,
            "root_channel_id": str(self.root_channel_id),
            "root_channel_name": self.root_channel_name,
            "starter_user_id": str(self.starter_user_id),
            "starter_user_name": self.starter_user_name,
            "owner_user_id": str(self.owner_user_id),
            "owner_user_name": self.owner_user_name,
            "started_at": self.started_at.isoformat(),
            "panel_creator_id": str(self.panel_creator_id) if self.panel_creator_id is not None else None,
            "panel_creator_name": self.panel_creator_name,
            "team_names": self.team_names,
            "team_mode": self.team_mode,
            "team_assignments": {str(key): value for key, value in self.team_assignments.items()},
            "team_channels": {team_name: str(channel_id) for team_name, channel_id in self.team_channels.items()},
            "access_mode": self.access_mode,
            "invited_user_ids": sorted(self.invited_user_ids),
            "access_role_ids": sorted(self.access_role_ids),
            "session_key": {"guild_id": str(self.guild_id), "vc_id": str(self.root_channel_id)},
            "notice_channel_id": str(self.notice_channel_id) if self.notice_channel_id is not None else None,
            "notice_message_id": str(self.notice_message_id) if self.notice_message_id is not None else None,
            "active_participant_count": len(self.active_participants()),
            "elapsed_seconds": max(0, int((utcnow() - self.started_at).total_seconds())),
            "participants": [participant.to_payload() for participant in self.participants.values()],
        }


@dataclass(slots=True)
class DeletionHandle:
    task: asyncio.Task[None]
    notice_sent: bool = False


@dataclass(slots=True)
class SoloCleanupHandle:
    task: asyncio.Task[None]
    notice_sent: bool = False
    warning_sent: bool = False


@dataclass(slots=True)
class SystemMoveMarker:
    user_id: int
    source_channel_id: int | None
    target_channel_id: int | None
    reason: str
    created_at: datetime


class RealtimeEventBroker:
    def __init__(self) -> None:
        self.connections: dict[str, set[WebSocket]] = {}
        self.lock = asyncio.Lock()

    async def connect(self, websocket: WebSocket, scopes: list[str]) -> None:
        await websocket.accept()
        async with self.lock:
            for scope in scopes:
                self.connections.setdefault(scope, set()).add(websocket)

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self.lock:
            empty_scopes: list[str] = []
            for scope, members in self.connections.items():
                members.discard(websocket)
                if not members:
                    empty_scopes.append(scope)
            for scope in empty_scopes:
                self.connections.pop(scope, None)

    async def broadcast(self, scope: str, event: str, payload: dict[str, Any]) -> None:
        async with self.lock:
            targets = list(self.connections.get(scope, set()))
        stale: list[WebSocket] = []
        for websocket in targets:
            try:
                await websocket.send_json({"event": event, "payload": payload})
            except Exception:
                stale.append(websocket)
        for websocket in stale:
            await self.disconnect(websocket)


WebSocketHub = RealtimeEventBroker


class SessionManager:
    def __init__(
        self,
        config_repo: ConfigRepository,
        stats_repo: StatsRepository,
        websocket_hub: WebSocketHub,
        logger: logging.Logger,
    ) -> None:
        self.config_repo = config_repo
        self.stats_repo = stats_repo
        self.websocket_hub = websocket_hub
        self.logger = logger
        self.bot: discord.Client | None = None
        self.guild_configs: dict[int, GuildConfig] = {}
        self.sessions: dict[int, LiveSession] = {}
        self.sessions_by_key: dict[tuple[int, int], LiveSession] = {}
        self.channel_to_root: dict[int, int] = {}
        self.deletion_tasks: dict[int, DeletionHandle] = {}
        self.solo_cleanup_tasks: dict[int, SoloCleanupHandle] = {}
        self.auto_personal_root_channels: set[int] = set()
        self.scheduled_vc_task: asyncio.Task[None] | None = None
        self.system_move_markers: list[SystemMoveMarker] = []

    def bind_bot(self, bot: discord.Client) -> None:
        self.bot = bot

    async def refresh_guild_configs(self) -> None:
        configs = await self.config_repo.list_guild_configs()
        self.guild_configs = {config.guild_id: config for config in configs}
        for session in list(self.sessions.values()):
            self._cancel_solo_cleanup_by_channel_id(session.root_channel_id)
            await self._refresh_solo_cleanup_for_session(session)

    async def sync_guild_catalog(self) -> None:
        if self.bot is None:
            return
        guilds = [(guild.id, guild.name) for guild in self.bot.guilds]
        await self.config_repo.sync_guild_catalog(guilds)
        await self.refresh_guild_configs()

    def start_scheduled_vc_worker(self) -> None:
        if self.scheduled_vc_task is not None and not self.scheduled_vc_task.done():
            return
        self.scheduled_vc_task = asyncio.create_task(self._scheduled_vc_worker())

    async def _scheduled_vc_worker(self) -> None:
        while True:
            try:
                await self._process_scheduled_vcs()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger.exception("scheduled VC worker failed")
            await asyncio.sleep(30)

    async def _process_scheduled_vcs(self) -> None:
        if self.bot is None or not self.guild_configs:
            return
        now = utcnow()
        for scheduled in await self.config_repo.list_due_scheduled_vc_starts(now):
            await self._start_scheduled_vc(scheduled)
        for scheduled in await self.config_repo.list_active_scheduled_vcs():
            await self._process_active_scheduled_vc(scheduled, now)
        await self._process_ranking_posts(now)

    def _ranking_frequency_key(self, frequency: str, now: datetime) -> str:
        local_now = now.astimezone(LOCAL_TZ)
        if frequency == "weekly":
            year, week, _ = local_now.isocalendar()
            return f"weekly:{year}-W{week:02d}"
        if frequency == "monthly":
            return f"monthly:{local_now.year}-{local_now.month:02d}"
        return f"daily:{local_now.date().isoformat()}"

    def _ranking_period_for_frequency(self, frequency: str) -> str:
        if frequency == "weekly":
            return "week"
        if frequency == "monthly":
            return "month"
        return "day"

    def _ranking_post_time_due(self, config: GuildConfig, now: datetime) -> bool:
        try:
            hour_text, minute_text = (config.ranking_post_time or "21:00").split(":", 1)
            hour = max(0, min(23, int(hour_text)))
            minute = max(0, min(59, int(minute_text)))
        except ValueError:
            hour, minute = 21, 0
        local_now = now.astimezone(LOCAL_TZ)
        return (local_now.hour, local_now.minute) >= (hour, minute)

    async def _process_ranking_posts(self, now: datetime) -> None:
        for config in list(self.guild_configs.values()):
            if not config.ranking_post_enabled or not config.ranking_post_channel_id:
                continue
            if not self._ranking_post_time_due(config, now):
                continue
            frequencies = [item for item in config.ranking_post_frequencies if item in {"daily", "weekly", "monthly"}]
            for frequency in frequencies:
                post_key = self._ranking_frequency_key(frequency, now)
                if config.ranking_post_last_keys.get(frequency) == post_key:
                    continue
                sent = await self.post_activity_rankings(config.guild_id, frequency=frequency)
                if sent:
                    config.ranking_post_last_keys[frequency] = post_key
                    await self.config_repo.update_ranking_post_last_keys(config.guild_id, config.ranking_post_last_keys)

    async def post_activity_rankings(self, guild_id: int, *, frequency: str = "manual") -> bool:
        config = self.guild_configs.get(guild_id) or await self.get_guild_config(guild_id)
        if config is None or config.ranking_post_channel_id is None:
            return False
        channel = await self._resolve_notice_channel(guild_id, config.ranking_post_channel_id)
        if channel is None:
            return False
        period = self._ranking_period_for_frequency(frequency)
        targets = [target for target in config.ranking_post_targets if target in RANKING_TARGET_LABEL_KEYS]
        if not targets:
            targets = list(RANKING_TARGET_LABEL_KEYS)
        bundle = await self.stats_repo.get_activity_ranking_bundle(guild_id, period=period, limit=5)
        embed = self._build_activity_ranking_embed(config, bundle, targets, frequency)
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            self.logger.exception("activity ranking post permission denied: guild_id=%s", guild_id)
            return False
        except discord.HTTPException:
            self.logger.exception("activity ranking post failed: guild_id=%s", guild_id)
            return False
        return True

    def _build_activity_ranking_embed(
        self,
        config: GuildConfig,
        bundle: dict[str, list[dict[str, Any]]],
        targets: list[str],
        frequency: str,
    ) -> discord.Embed:
        locale = config.guild_language
        title_suffix = t(f"ranking.freq.{frequency}", locale) if frequency in {"manual", "daily", "weekly", "monthly"} else frequency
        embed = build_embed(
            locale,
            "embed.ranking.title",
            "embed.ranking.description",
            color=BRAND_BLUE,
            title_fmt={"suffix": title_suffix},
            description_fmt={"guild": config.guild_name},
        )
        embed.timestamp = utcnow()
        for target in targets:
            rows = bundle.get(target, [])
            lines: list[str] = []
            for row in rows[:5]:
                rank = int(row.get("rank") or len(lines) + 1)
                user = row.get("user_name") or row.get("user_id") or t("common.unknown", locale)
                if target == "top_hosts":
                    value = t(
                        "ranking.hostValue",
                        locale,
                        gathered=int(row.get("gathered_count") or 0),
                        sessions=int(row.get("session_count") or 0),
                    )
                elif target == "team_splits":
                    value = t("ranking.splitValue", locale, count=int(row.get("split_count") or 0))
                else:
                    value = format_duration(int(row.get("talk_seconds") or 0))
                lines.append(f"{rank}. {user} - {value}")
            embed.add_field(
                name=t(RANKING_TARGET_LABEL_KEYS[target], locale),
                value="\n".join(lines) if lines else t("common.noData", locale),
                inline=False,
            )
        embed.set_footer(text=t("ranking.footer", locale))
        return embed

    async def restore_sessions(self) -> None:
        if self.bot is None:
            return
        await self.refresh_guild_configs()
        snapshots = {snapshot.root_channel_id: snapshot for snapshot in await self.config_repo.list_session_snapshots()}
        for root_channel_id, snapshot in snapshots.items():
            guild = self.bot.get_guild(snapshot.guild_id)
            if guild is None:
                continue
            root_channel = guild.get_channel(root_channel_id)
            if not isinstance(root_channel, discord.VoiceChannel):
                await self.config_repo.delete_session_snapshot(snapshot.session_id)
                continue
            session = LiveSession(
                session_id=snapshot.session_id,
                guild_id=snapshot.guild_id,
                guild_name=guild.name,
                root_channel_id=root_channel.id,
                root_channel_name=root_channel.name,
                starter_user_id=snapshot.starter_user_id,
                starter_user_name=snapshot.starter_user_name,
                owner_user_id=snapshot.owner_user_id,
                owner_user_name=snapshot.owner_user_name,
                started_at=snapshot.started_at,
                team_names=snapshot.team_names,
                team_mode=snapshot.team_mode,
                panel_creator_id=snapshot.panel_creator_id,
                panel_creator_name=snapshot.panel_creator_name,
                team_assignments={int(key): value for key, value in snapshot.team_assignments.items()},
                team_channels=snapshot.team_channels.copy(),
                access_mode=snapshot.access_mode,
                invited_user_ids=set(snapshot.invited_user_ids),
                access_role_ids=set(snapshot.access_role_ids),
                notice_channel_id=snapshot.notice_channel_id,
                notice_message_id=snapshot.notice_message_id,
                member_order=snapshot.member_order.copy(),
            )
            for member_snapshot in snapshot.members:
                participant = LiveParticipant(
                    user_id=member_snapshot.user_id,
                    user_name=member_snapshot.user_name,
                    joined_at=member_snapshot.joined_at,
                    last_transition_at=utcnow(),
                    current_channel_id=member_snapshot.current_channel_id,
                    talk_seconds=member_snapshot.talk_seconds,
                    afk_seconds=member_snapshot.afk_seconds,
                    afk_channel_seconds=member_snapshot.afk_channel_seconds,
                    self_mute_seconds=member_snapshot.self_mute_seconds,
                    self_deafen_seconds=member_snapshot.self_deafen_seconds,
                    self_muted=member_snapshot.self_muted,
                    self_deafened=member_snapshot.self_deafened,
                    in_afk_channel=member_snapshot.in_afk_channel,
                    current_team=member_snapshot.current_team,
                    panel_creator=member_snapshot.panel_creator,
                )
                member = guild.get_member(member_snapshot.user_id)
                if member and member.voice and member.voice.channel:
                    participant.current_channel_id = member.voice.channel.id
                    participant.apply_voice_state(member.voice)
                    participant.user_name = member.display_name
                else:
                    participant.current_channel_id = None
                session.participants[participant.user_id] = participant
            self._hydrate_session_live_members(session, guild, root_channel)
            self._register_session(session)
            self.auto_personal_root_channels.add(session.root_channel_id)
            await self._apply_access_overwrites(session)
            management_url = await self.build_management_url(session.guild_id, session.root_channel_id)
            await self._send_restart_restored_management_panel(session, management_url)
            await self._persist_and_broadcast(session)
            restore_locale = self.guild_configs.get(session.guild_id).guild_language if self.guild_configs.get(session.guild_id) else None
            await self._record_timeline_event(
                session,
                "bot_restart_restored",
                t("event.restoredAfterRestart", restore_locale, channel=session.root_channel_name),
            )
            await self._publish_important_event(
                "bot_restart_restored",
                t("event.title.restored", restore_locale),
                t("event.restoredAfterRestart", restore_locale, channel=session.root_channel_name),
                session,
            )
            self.logger.info("セッションを復元しました: session_key=%s session_id=%s", session.session_key, session.session_id)

        for guild in self.bot.guilds:
            config = self.guild_configs.get(guild.id)
            if not config or not config.enabled or config.managed_category_id is None:
                continue
            category = guild.get_channel(config.managed_category_id)
            if not isinstance(category, discord.CategoryChannel):
                continue
            for channel in category.voice_channels:
                if config.base_voice_channel_id and channel.id == config.base_voice_channel_id:
                    continue
                if channel.id in self.channel_to_root:
                    continue
                members = self.get_non_bot_members_for_channel(guild, channel)
                if not members:
                    continue
                await self.restore_or_create_session_from_channel(guild, channel, members)
        await self.update_presence()

    def _hydrate_session_live_members(
        self,
        session: LiveSession,
        guild: discord.Guild,
        root_channel: discord.VoiceChannel,
    ) -> None:
        live_members: dict[int, discord.Member] = {}
        for member in self.get_non_bot_members_for_channel(guild, root_channel):
            live_members[int(member.id)] = member
        for channel_id in session.team_channels.values():
            team_channel = self._resolve_voice_channel(int(channel_id))
            if team_channel is None:
                continue
            for member in self.get_non_bot_members_for_channel(guild, team_channel):
                live_members[int(member.id)] = member

        now = utcnow()
        for participant in session.participants.values():
            participant.current_channel_id = None

        for member_id, member in live_members.items():
            voice_channel_id = int(member.voice.channel.id) if member.voice and member.voice.channel else int(root_channel.id)
            participant = session.participants.get(member_id)
            if participant is None:
                participant = LiveParticipant(
                    user_id=member_id,
                    user_name=member.display_name,
                    joined_at=session.started_at,
                    last_transition_at=now,
                    current_channel_id=voice_channel_id,
                    current_team=session.team_assignments.get(member_id),
                )
                session.participants[member_id] = participant
                if member_id not in session.member_order:
                    session.member_order.append(member_id)
            else:
                participant.user_name = member.display_name
                participant.current_channel_id = voice_channel_id
                participant.last_transition_at = now
                participant.current_team = participant.current_team or session.team_assignments.get(member_id)
            if member.voice is not None:
                participant.apply_voice_state(member.voice)

    async def _send_restart_restored_management_panel(
        self,
        session: LiveSession,
        management_url: str | None,
    ) -> None:
        root_channel = self._resolve_voice_channel(session.root_channel_id)
        if root_channel is None:
            return
        from vc_control.team_ui import TeamPanelView

        config = await self.get_guild_config(session.guild_id)
        locale = config.guild_language if config else None
        embed = self._build_management_panel_embed(session, management_url, locale)
        embed.title = t("embed.management_panel_restored.title", locale)
        embed.description = t("embed.management_panel_restored.description", locale)
        await self._send_embed(
            root_channel,
            embed,
            view=TeamPanelView(self, session.root_channel_id, management_url=management_url),
        )

    async def get_guild_config(self, guild_id: int) -> GuildConfig | None:
        if not self.guild_configs:
            await self.refresh_guild_configs()
        return self.guild_configs.get(guild_id)

    def build_session_key(self, guild_id: int, vc_id: int) -> tuple[int, int]:
        return make_session_key(guild_id, vc_id)

    def get_session(self, guild_id: int, vc_id: int) -> LiveSession | None:
        normalized_guild_id, normalized_vc_id = normalize_ids(guild_id, vc_id)
        session = self.sessions_by_key.get((normalized_guild_id, normalized_vc_id))
        if session is not None:
            return session
        legacy = self.sessions.get(normalized_vc_id)
        if legacy is not None and legacy.guild_id == normalized_guild_id:
            self.sessions_by_key[(normalized_guild_id, normalized_vc_id)] = legacy
            return legacy
        return None

    def get_active_session_keys(self) -> list[tuple[int, int]]:
        if self.sessions_by_key:
            return list(self.sessions_by_key.keys())
        return [(int(session.guild_id), int(root_channel_id)) for root_channel_id, session in self.sessions.items()]

    async def build_management_url(self, guild_id: int, vc_id: int) -> str | None:
        settings = await self.config_repo.get_runtime_settings()
        base_url = (
            (settings.get("base_url") or "").strip()
            or (os.getenv("DASHBOARD_BASE_URL") or "").strip()
        ).rstrip("/")
        if not base_url:
            return None
        session_key = self.build_session_key(guild_id, vc_id)
        return f"{base_url}/dashboard/voice/{session_key[0]}/{session_key[1]}"

    async def resolve_voice_channel_for_guild(self, guild_id: int, vc_id: int) -> discord.VoiceChannel | None:
        normalized_guild_id, normalized_vc_id = normalize_ids(guild_id, vc_id)
        guild = self._resolve_guild(normalized_guild_id)
        if guild is None or self.bot is None:
            return None
        channel = guild.get_channel(normalized_vc_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(normalized_vc_id)
            except Exception:
                self.logger.exception("VCチャンネルの取得に失敗しました: guild_id=%s vc_id=%s", normalized_guild_id, normalized_vc_id)
                return None
        if not isinstance(channel, discord.VoiceChannel):
            return None
        return channel

    def get_non_bot_members_for_channel(
        self,
        guild: discord.Guild,
        channel: discord.VoiceChannel,
    ) -> list[discord.Member]:
        members: dict[int, discord.Member] = {}

        for member in channel.members:
            if not member.bot:
                members[int(member.id)] = member

        for member in guild.members:
            if member.bot:
                continue
            voice_state = member.voice
            if voice_state is None or voice_state.channel is None:
                continue
            if int(voice_state.channel.id) == int(channel.id):
                members[int(member.id)] = member

        return sorted(members.values(), key=lambda item: item.display_name.lower())

    async def create_session_from_current_channel_state(
        self,
        guild: discord.Guild,
        channel: discord.VoiceChannel,
        members: list[discord.Member],
    ) -> LiveSession:
        config = await self.get_guild_config(guild.id)
        started_at = utcnow()
        starter = members[0]
        team_names = config.team_names.copy() if config and config.team_names else DEFAULT_TEAM_NAMES.copy()
        team_mode = config.team_mode if config else "custom"

        session = LiveSession(
            session_id=str(uuid.uuid4()),
            guild_id=int(guild.id),
            guild_name=guild.name,
            root_channel_id=int(channel.id),
            root_channel_name=channel.name,
            starter_user_id=int(starter.id),
            starter_user_name=starter.display_name,
            owner_user_id=int(starter.id),
            owner_user_name=starter.display_name,
            started_at=started_at,
            team_names=team_names,
            team_mode=team_mode,
            notice_channel_id=config.notification_channel_id if config else None,
            notice_message_id=None,
        )
        for member in members:
            current_channel_id = int(member.voice.channel.id) if member.voice and member.voice.channel else int(channel.id)
            participant = LiveParticipant(
                user_id=int(member.id),
                user_name=member.display_name,
                joined_at=started_at,
                last_transition_at=started_at,
                current_channel_id=current_channel_id,
                current_team=None,
            )
            if member.voice is not None:
                participant.apply_voice_state(member.voice)
            session.participants[participant.user_id] = participant
            session.member_order.append(participant.user_id)
        return session

    async def restore_or_create_session_from_channel(
        self,
        guild: discord.Guild,
        channel: discord.VoiceChannel,
        non_bot_members: list[discord.Member],
    ) -> LiveSession | None:
        session = self.get_session(guild.id, channel.id)
        if session is not None:
            return session
        if not non_bot_members:
            return None

        session = await self.create_session_from_current_channel_state(guild, channel, non_bot_members)

        self._register_session(session)
        if self._channel_name_matches_personal_session(session, channel):
            self.auto_personal_root_channels.add(session.root_channel_id)
        management_url = await self.build_management_url(session.guild_id, session.root_channel_id)
        await self._send_restart_restored_management_panel(session, management_url)
        await self._persist_and_broadcast(session)
        restore_locale = self.guild_configs.get(session.guild_id).guild_language if self.guild_configs.get(session.guild_id) else None
        await self._record_timeline_event(
            session,
            "bot_restart_restored",
            t("event.restoredFromDiscordState", restore_locale, channel=session.root_channel_name),
        )
        await self._publish_important_event(
            "bot_restart_restored",
            t("event.title.restored", restore_locale),
            t("event.restoredFromDiscordState", restore_locale, channel=session.root_channel_name),
            session,
        )
        self.logger.info("Discord状態からセッションを復元しました: session_key=%s members=%s", session.session_key, len(non_bot_members))
        return session

    async def get_or_create_active_session_for_channel(self, guild_id: int, vc_id: int) -> LiveSession | None:
        normalized_guild_id, normalized_vc_id = normalize_ids(guild_id, vc_id)
        session_key = self.build_session_key(normalized_guild_id, normalized_vc_id)
        session = self.get_session(*session_key)
        if session is not None:
            return session

        guild = self._resolve_guild(normalized_guild_id)
        if guild is None:
            return None
        channel = await self.resolve_voice_channel_for_guild(normalized_guild_id, normalized_vc_id)
        if channel is None:
            return None
        non_bot_members = self.get_non_bot_members_for_channel(guild, channel)
        if not non_bot_members:
            return None
        return await self.restore_or_create_session_from_channel(guild, channel, non_bot_members)

    async def get_or_restore_session(self, guild_id: int, vc_id: int) -> LiveSession | None:
        return await self.get_or_create_active_session_for_channel(guild_id, vc_id)

    async def ensure_personal_channel(self, member: discord.Member, config: GuildConfig) -> discord.VoiceChannel | None:
        guild = member.guild
        if config.managed_category_id is None:
            return None
        category = guild.get_channel(config.managed_category_id)
        if not isinstance(category, discord.CategoryChannel):
            return None
        target_name = f"{member.display_name}のVC"
        for channel in category.voice_channels:
            if config.base_voice_channel_id and channel.id == config.base_voice_channel_id:
                continue
            if channel.name == target_name:
                self.auto_personal_root_channels.add(channel.id)
                return channel
        try:
            created = await guild.create_voice_channel(
                target_name,
                category=category,
                reason="個人VCの自動作成",
            )
            self.logger.info("個人VCを作成しました: guild=%s channel=%s", guild.name, created.name)
            self.auto_personal_root_channels.add(created.id)
            return created
        except discord.Forbidden:
            self.logger.exception("個人VCの作成権限がありません")
            return None
        except discord.HTTPException:
            self.logger.exception("個人VCの作成に失敗しました")
            return None

    async def handle_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot:
            return
        config = await self.get_guild_config(member.guild.id)
        if not config or not config.enabled:
            return

        before_channel = before.channel if isinstance(before.channel, discord.VoiceChannel) else None
        after_channel = after.channel if isinstance(after.channel, discord.VoiceChannel) else None

        if (before_channel and after_channel and before_channel.id != after_channel.id) or (before_channel is None) != (after_channel is None):
            self.logger.info(
                "VC入退室: guild=%s member=%s before=%s after=%s",
                member.guild.id,
                member.id,
                before_channel.id if before_channel else None,
                after_channel.id if after_channel else None,
            )

        if before_channel and after_channel and before_channel.id == after_channel.id:
            await self._handle_state_only_change(member, after_channel, after)
            await self.update_presence()
            return

        if after_channel and config.base_voice_channel_id and after_channel.id == config.base_voice_channel_id:
            target_channel = await self.ensure_personal_channel(member, config)
            if target_channel is not None:
                try:
                    await member.move_to(target_channel, reason="基点VCから個人VCへ自動移動")
                except discord.Forbidden:
                    self.logger.exception("自動移動の権限がありません")
                except discord.HTTPException:
                    self.logger.exception("自動移動に失敗しました")
            await self.update_presence()
            return

        before_root = before_channel and self.channel_to_root.get(before_channel.id)
        after_root = after_channel and self.channel_to_root.get(after_channel.id)

        if before_channel and after_channel and before_root and before_root == after_root:
            suppressed = self._consume_system_move(member.id, before_channel.id, after_channel.id)
            await self._move_within_session(member, before_channel, after_channel, before, after, suppressed=suppressed)
            await self.update_presence()
            return

        if before_channel and before_root:
            suppressed = self._consume_system_move(member.id, before_channel.id, after_channel.id if after_channel else None)
            await self._leave_session_channel(member, before_channel, before, suppressed=suppressed)

        if after_channel and after_root:
            suppressed = self._consume_system_move(member.id, before_channel.id if before_channel else None, after_channel.id)
            await self._join_existing_session(member, after_channel, after, suppressed=suppressed)
        elif after_channel and self._is_managed_voice_channel(after_channel, include_base=False):
            suppressed = self._consume_system_move(member.id, before_channel.id if before_channel else None, after_channel.id)
            await self._join_or_start_session(member, after_channel, after, suppressed=suppressed)

        if before_channel and self._is_managed_voice_channel(before_channel, include_base=False) and not before_channel.members:
            await self._schedule_empty_cleanup(before_channel)
        if after_channel and self._is_managed_voice_channel(after_channel, include_base=False):
            await self._cancel_empty_cleanup(after_channel)

        await self.update_presence()

    async def _handle_state_only_change(
        self,
        member: discord.Member,
        channel: discord.VoiceChannel,
        state: discord.VoiceState,
    ) -> None:
        root_id = self.channel_to_root.get(channel.id)
        if root_id is None:
            return
        session = self.sessions.get(root_id)
        if session is None:
            return
        participant = session.participants.get(member.id)
        if participant is None:
            return
        now = utcnow()
        participant.accrue(now)
        participant.user_name = member.display_name
        participant.apply_voice_state(state)
        await self._persist_and_broadcast(session)
        await self._record_timeline_event(
            session,
            "member_mute_changed",
            f"{member.display_name} voice state changed.",
            user_id=member.id,
            user_name=member.display_name,
            payload={
                "self_muted": participant.self_muted,
                "self_deafened": participant.self_deafened,
                "in_afk_channel": participant.in_afk_channel,
            },
        )
        await self._publish_session_event(
            session,
            "member_mute_changed",
            {
                "user_id": str(member.id),
                "self_muted": participant.self_muted,
                "self_deafened": participant.self_deafened,
                "in_afk_channel": participant.in_afk_channel,
            },
        )

    async def _join_or_start_session(
        self,
        member: discord.Member,
        channel: discord.VoiceChannel,
        state: discord.VoiceState,
        suppressed: bool,
    ) -> None:
        existing_root = self.channel_to_root.get(channel.id)
        if existing_root:
            await self._join_existing_session(member, channel, state, suppressed=suppressed)
            return
        await self._start_session(
            channel,
            member,
            self.get_non_bot_members_for_channel(member.guild, channel),
            suppressed=suppressed,
        )

    def _build_management_link_view(self, management_url: str | None) -> discord.ui.View | None:
        if not management_url:
            return None
        view = discord.ui.View(timeout=None)
        view.add_item(discord.ui.Button(label="VCを管理", style=discord.ButtonStyle.link, url=management_url))
        return view

    def _format_discord_timestamp(self, value: datetime, style: str = "F") -> str:
        return discord.utils.format_dt(value, style=style)

    def _build_start_embed(
        self,
        session: LiveSession,
        starter: discord.Member,
        management_url: str | None,
        locale: str | None = None,
    ) -> discord.Embed:
        embed = build_embed(
            locale,
            "embed.vc_started.title",
            "embed.vc_started.description",
            color=COLOR_SUCCESS,
            description_fmt={"channel": session.root_channel_name},
        )
        embed.add_field(name=t("field.vcName", locale), value=session.root_channel_name, inline=False)
        embed.add_field(name=t("field.startedAt", locale), value=self._format_discord_timestamp(session.started_at), inline=True)
        embed.add_field(name=t("field.participant", locale), value=starter.mention, inline=True)
        embed.add_field(name=t("field.management", locale), value=management_url or t("common.notSet", locale), inline=False)
        return embed

    def _build_management_panel_embed(self, session: LiveSession, management_url: str | None, locale: str | None = None) -> discord.Embed:
        embed = build_embed(
            locale,
            "embed.management_panel.title",
            "embed.management_panel.description",
            color=BRAND_BLUE,
        )
        embed.add_field(name=t("field.vcName", locale), value=session.root_channel_name, inline=False)
        embed.add_field(name=t("field.currentOwner", locale), value=f"<@{session.owner_user_id}>", inline=True)
        embed.add_field(name=t("field.teams", locale), value=", ".join(session.team_names), inline=True)
        embed.add_field(name=t("field.management", locale), value=management_url or t("common.notSet", locale), inline=False)
        return embed

    def _build_end_embed(self, session: LiveSession, completed: CompletedSession, locale: str | None = None) -> discord.Embed:
        session_seconds = max(0, int((completed.ended_at - completed.started_at).total_seconds()))
        member_lines = [
            f"- {member.user_name}: {format_duration(member.talk_seconds)}"
            for member in sorted(completed.members, key=lambda item: item.talk_seconds, reverse=True)
        ]
        embed = build_embed(
            locale,
            "embed.vc_ended.title",
            "embed.vc_ended.description",
            color=BRAND_BLUE,
            description_fmt={"channel": session.root_channel_name},
        )
        embed.add_field(name=t("field.vc", locale), value=session.root_channel_name, inline=False)
        embed.add_field(name=t("field.startedShort", locale), value=self._format_discord_timestamp(completed.started_at), inline=True)
        embed.add_field(name=t("field.endedShort", locale), value=self._format_discord_timestamp(completed.ended_at), inline=True)
        embed.add_field(name=t("field.duration", locale), value=format_duration(session_seconds), inline=True)
        embed.add_field(
            name=t("field.participantList", locale),
            value="\n".join(member_lines) if member_lines else t("common.noParticipants", locale),
            inline=False,
        )
        embed.add_field(name=t("field.totalTalkTime", locale), value=format_duration(completed.total_talk_seconds), inline=False)
        return embed

    async def _resolve_notice_channel(
        self,
        guild_id: int,
        preferred_channel_id: int | None = None,
    ) -> discord.abc.Messageable | None:
        guild = self._resolve_guild(int(guild_id))
        if guild is None or self.bot is None:
            return None

        channel_id = int(preferred_channel_id or 0)
        if channel_id <= 0:
            config = self.guild_configs.get(int(guild_id))
            if config is None or config.notification_channel_id is None:
                return None
            channel_id = int(config.notification_channel_id)

        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except Exception as exc:
                print(f"[NOTICE ERROR] {exc}")
                self.logger.exception("通知チャンネルの取得に失敗しました: guild_id=%s channel_id=%s", guild_id, channel_id)
                return None

        if not hasattr(channel, "send"):
            self.logger.warning("通知チャンネルが送信可能ではありません: guild_id=%s channel_id=%s", guild_id, channel_id)
            return None
        return channel

    async def _send_notification_message(
        self,
        session: LiveSession,
        embed: discord.Embed,
        view: discord.ui.View | None = None,
    ) -> discord.Message | None:
        channel = await self._resolve_notice_channel(session.guild_id, session.notice_channel_id)
        if channel is None:
            return None
        channel_id = int(getattr(channel, "id", 0) or 0)
        print(f"[NOTICE] send to {channel_id} / {channel}")
        self.logger.info("通知送信: session_key=%s channel_id=%s", session.session_key, channel_id)
        try:
            message = await channel.send(embed=embed, view=view)
        except Exception as exc:
            print(f"[NOTICE ERROR] {exc}")
            self.logger.exception("通知送信に失敗しました: session_key=%s channel_id=%s", session.session_key, channel_id)
            return None
        session.notice_channel_id = channel_id
        session.notice_message_id = message.id
        return message

    async def _delete_notification_message(self, session: LiveSession) -> None:
        if session.notice_channel_id is None or session.notice_message_id is None:
            return
        channel = await self._resolve_notice_channel(session.guild_id, session.notice_channel_id)
        if channel is None:
            return None
        try:
            partial_message = channel.get_partial_message(session.notice_message_id)  # type: ignore[attr-defined]
            await partial_message.delete()
            self.logger.info(
                "開始通知を削除しました: session_key=%s channel_id=%s message_id=%s",
                session.session_key,
                session.notice_channel_id,
                session.notice_message_id,
            )
        except Exception as exc:
            print(f"[NOTICE ERROR] {exc}")
            self.logger.exception(
                "開始通知の削除に失敗しました: session_key=%s channel_id=%s message_id=%s",
                session.session_key,
                session.notice_channel_id,
                session.notice_message_id,
            )

    def _scheduled_mention_text(self, scheduled: ScheduledVC) -> str:
        if scheduled.mention_type == "everyone":
            return "@everyone"
        if scheduled.mention_type == "here":
            return "@here"
        if scheduled.mention_type == "role":
            return " ".join(f"<@&{target}>" for target in scheduled.mention_targets)
        if scheduled.mention_type == "user":
            return " ".join(f"<@{target}>" for target in scheduled.mention_targets)
        return ""

    async def _publish_scheduled_vc_notification(
        self,
        event_type: str,
        title: str,
        message: str,
        scheduled: ScheduledVC,
        *,
        channel_id: int | None = None,
    ) -> None:
        payload = {
            "scheduled_vc_id": str(scheduled.id),
            "guild_id": str(scheduled.guild_id),
            "root_channel_id": str(channel_id) if channel_id is not None else None,
            "vc_name": scheduled.vc_name,
        }
        try:
            notification = await self.config_repo.create_notification(
                event_type=event_type,
                title=title,
                message=message,
                guild_id=scheduled.guild_id,
                root_channel_id=channel_id,
                recipient_user_id=None,
                payload=payload,
            )
        except Exception:
            self.logger.exception("scheduled VC notification save failed: scheduled_id=%s", scheduled.id)
            notification = {
                "id": None,
                "created_at": utcnow().isoformat(),
                "event_type": event_type,
                "title": title,
                "message": message,
                "guild_id": str(scheduled.guild_id),
                "root_channel_id": str(channel_id) if channel_id is not None else None,
                "recipient_user_id": None,
                "payload": payload,
                "read_at": None,
            }
        await self.websocket_hub.broadcast(
            f"guild:{scheduled.guild_id}",
            "important_notification",
            {"type": event_type, "notification": notification, "payload": payload},
        )
        await self.websocket_hub.broadcast(
            "global",
            "important_notification",
            {"type": event_type, "notification": notification, "payload": payload},
        )

    async def _send_scheduled_vc_dms(self, scheduled: ScheduledVC, embed: discord.Embed) -> None:
        if self.bot is None:
            return
        guild = self._resolve_guild(scheduled.guild_id)
        target_ids: set[int] = {scheduled.creator_user_id}
        if guild is not None:
            if scheduled.mention_type == "user":
                target_ids.update(int(target) for target in scheduled.mention_targets if str(target).isdigit())
            elif scheduled.mention_type == "role":
                role_ids = {int(target) for target in scheduled.mention_targets if str(target).isdigit()}
                for member in guild.members:
                    if member.bot:
                        continue
                    if any(role.id in role_ids for role in member.roles):
                        target_ids.add(member.id)
            elif scheduled.mention_type in {"everyone", "here"}:
                target_ids.update(member.id for member in guild.members if not member.bot)
        for user_id in target_ids:
            user: discord.User | discord.Member | None = self.bot.get_user(user_id)
            if user is None and guild is not None:
                user = guild.get_member(user_id)
            if user is None:
                try:
                    user = await self.bot.fetch_user(user_id)
                except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                    continue
            try:
                await user.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException):
                self.logger.info("scheduled VC DM failed: scheduled_id=%s user=%s", scheduled.id, user_id)

    async def _send_scheduled_vc_message(
        self,
        channel: discord.abc.Messageable | None,
        scheduled: ScheduledVC,
        embed: discord.Embed,
    ) -> None:
        if channel is None:
            return
        mention_text = self._scheduled_mention_text(scheduled)
        try:
            await channel.send(
                content=mention_text or None,
                embed=embed,
                allowed_mentions=discord.AllowedMentions(everyone=True, users=True, roles=True),
            )
        except discord.Forbidden:
            self.logger.exception("scheduled VC notification permission denied: scheduled_id=%s", scheduled.id)
        except discord.HTTPException:
            self.logger.exception("scheduled VC notification send failed: scheduled_id=%s", scheduled.id)

    async def _record_scheduled_vc_timeline(self, scheduled: ScheduledVC, channel: discord.VoiceChannel, event_type: str, message: str) -> None:
        config = self.guild_configs.get(scheduled.guild_id)
        locale = config.guild_language if config else None
        try:
            event = await self.stats_repo.record_timeline_event(
                session_id=f"scheduled:{scheduled.id}",
                guild_id=str(scheduled.guild_id),
                guild_name=scheduled.guild_name,
                root_channel_id=str(channel.id),
                root_channel_name=channel.name,
                event_type=event_type,
                event_label=_timeline_label(event_type, locale),
                user_id=str(scheduled.creator_user_id),
                user_name=scheduled.creator_user_name,
                message=message,
                payload={"scheduled_vc_id": str(scheduled.id)},
                retention_days=await self._timeline_retention_days(),
            )
            await self.websocket_hub.broadcast(f"guild:{scheduled.guild_id}", "timeline_event", event)
        except Exception:
            self.logger.exception("scheduled VC timeline save failed: scheduled_id=%s", scheduled.id)

    async def _record_web_vc_creation(
        self,
        *,
        guild: discord.Guild,
        channel: discord.VoiceChannel,
        actor_id: int,
        actor_name: str,
        vc_type: str,
    ) -> None:
        config = self.guild_configs.get(guild.id)
        locale = config.guild_language if config else None
        try:
            event = await self.stats_repo.record_timeline_event(
                session_id=f"web:{channel.id}",
                guild_id=str(guild.id),
                guild_name=guild.name,
                root_channel_id=str(channel.id),
                root_channel_name=channel.name,
                event_type="web_vc_created",
                event_label=_timeline_label("web_vc_created", locale),
                user_id=str(actor_id),
                user_name=actor_name,
                message=t("embed.web_vc_created.description", locale, channel=channel.name),
                payload={"vc_type": vc_type},
                retention_days=await self._timeline_retention_days(),
            )
            await self.websocket_hub.broadcast(f"guild:{guild.id}", "timeline_event", event)
        except Exception:
            self.logger.exception("web VC creation timeline save failed: guild_id=%s channel_id=%s", guild.id, channel.id)

    async def _publish_web_vc_creation_notification(
        self,
        *,
        guild: discord.Guild,
        channel: discord.VoiceChannel,
        actor_id: int,
        actor_name: str,
        vc_type: str,
    ) -> None:
        config = self.guild_configs.get(guild.id)
        locale = config.guild_language if config else None
        payload = {
            "guild_id": str(guild.id),
            "root_channel_id": str(channel.id),
            "vc_name": channel.name,
            "vc_type": vc_type,
            "actor_user_id": str(actor_id),
        }
        try:
            notification = await self.config_repo.create_notification(
                event_type="web_vc_created",
                title=t("embed.web_vc_created.title", locale),
                message=t("event.webVcCreatedByActor", locale, channel=channel.name, actor=actor_name),
                guild_id=guild.id,
                root_channel_id=channel.id,
                recipient_user_id=None,
                payload=payload,
            )
        except Exception:
            self.logger.exception("web VC creation notification save failed: guild_id=%s channel_id=%s", guild.id, channel.id)
            notification = {
                "id": None,
                "created_at": utcnow().isoformat(),
                "event_type": "web_vc_created",
                "title": t("embed.web_vc_created.title", locale),
                "message": t("event.webVcCreatedByActor", locale, channel=channel.name, actor=actor_name),
                "guild_id": str(guild.id),
                "root_channel_id": str(channel.id),
                "recipient_user_id": None,
                "payload": payload,
                "read_at": None,
            }
        envelope = {"type": "web_vc_created", "notification": notification, "payload": payload}
        for scope in {f"guild:{guild.id}", f"session:{channel.id}", "global"}:
            await self.websocket_hub.broadcast(scope, "important_notification", envelope)

    async def create_web_voice_channel(
        self,
        *,
        guild_id: int,
        actor_id: int,
        actor_name: str,
        vc_type: str,
        owner_user_id: int | None = None,
        vc_name: str | None = None,
        user_limit: int = 0,
        bitrate: int | None = None,
        end_at: datetime | None = None,
        description: str = "",
    ) -> discord.VoiceChannel:
        if not await self.is_guild_admin(guild_id, actor_id):
            raise PermissionError("サーバー管理者権限が必要です。")
        guild = self._resolve_guild(guild_id)
        config = await self.get_guild_config(guild_id)
        if guild is None or config is None or not config.enabled or config.managed_category_id is None:
            raise ValueError("管理対象カテゴリが設定されていません。")
        category = guild.get_channel(config.managed_category_id)
        if not isinstance(category, discord.CategoryChannel):
            raise ValueError("管理対象カテゴリが利用できません。")
        normalized_type = "event" if vc_type == "event" else "personal"
        owner_name = ""
        if normalized_type == "personal":
            if owner_user_id is None:
                raise ValueError("所有者ユーザーの指定が必要です。")
            owner = guild.get_member(owner_user_id)
            if owner is None and self.bot is not None:
                try:
                    owner = await guild.fetch_member(owner_user_id)
                except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                    owner = None
            owner_name = owner.display_name if owner is not None else str(owner_user_id)
            target_name = (vc_name or "").strip() or t("msg.personalVcName", config.guild_language, name=owner_name)
        else:
            if end_at is None:
                raise ValueError("一時イベントVCには終了時刻の指定が必要です。")
            target_name = (vc_name or "").strip() or t("msg.eventVcDefaultName", config.guild_language)
        create_kwargs: dict[str, Any] = {
            "category": category,
            "user_limit": max(0, min(99, int(user_limit))),
            "reason": f"Webダッシュボードからの{normalized_type}VC作成",
        }
        if bitrate is not None:
            create_kwargs["bitrate"] = int(bitrate)
        try:
            channel = await guild.create_voice_channel(target_name, **create_kwargs)
        except discord.Forbidden as exc:
            raise PermissionError("Botにボイスチャンネルを作成する権限がありません。") from exc
        except discord.HTTPException as exc:
            raise RuntimeError("ボイスチャンネルの作成に失敗しました。") from exc

        if normalized_type == "personal":
            self.auto_personal_root_channels.add(channel.id)
        else:
            scheduled = await self.config_repo.create_scheduled_vc(
                ScheduledVC(
                    id=None,
                    guild_id=guild.id,
                    guild_name=guild.name,
                    creator_user_id=actor_id,
                    creator_user_name=actor_name,
                    vc_name=channel.name,
                    category_id=category.id,
                    user_limit=max(0, min(99, int(user_limit))),
                    bitrate=bitrate,
                    mention_type="none",
                    mention_targets=[],
                    description=description.strip(),
                    start_at=utcnow(),
                    end_at=end_at,
                    repeat_mode="none",
                    status="active",
                    created_channel_id=channel.id,
                )
            )
            if scheduled.id is not None:
                await self.config_repo.update_scheduled_vc_start_result(scheduled.id, channel_id=channel.id, status="active")

        embed = build_embed(
            config.guild_language,
            "embed.web_vc_created.title",
            "embed.web_vc_created.description",
            color=COLOR_SUCCESS,
            description_fmt={"channel": channel.name},
        )
        if normalized_type == "personal":
            embed.add_field(name=t("field.owner", config.guild_language), value=f"<@{owner_user_id}>", inline=True)
        if end_at is not None:
            embed.add_field(name=t("field.scheduledEnd", config.guild_language), value=discord.utils.format_dt(end_at, style="F"), inline=True)
        if description.strip():
            embed.add_field(name=t("field.description", config.guild_language), value=description.strip()[:1024], inline=False)
        await self._send_embed(channel, embed)
        notice_channel = await self._resolve_notice_channel(guild.id)
        if notice_channel is not None:
            await self._send_embed(notice_channel, embed)
        await self._record_web_vc_creation(
            guild=guild,
            channel=channel,
            actor_id=actor_id,
            actor_name=actor_name,
            vc_type=normalized_type,
        )
        await self._publish_web_vc_creation_notification(
            guild=guild,
            channel=channel,
            actor_id=actor_id,
            actor_name=actor_name,
            vc_type=normalized_type,
        )
        await self._broadcast_global_state()
        return channel

    def _next_scheduled_occurrence(self, scheduled: ScheduledVC) -> tuple[datetime, datetime | None] | None:
        if scheduled.start_at is None or scheduled.repeat_mode == "none":
            return None
        duration = (scheduled.end_at - scheduled.start_at) if scheduled.end_at is not None else None
        cursor = scheduled.start_at
        if scheduled.repeat_mode == "daily":
            next_start = cursor + timedelta(days=1)
        elif scheduled.repeat_mode == "weekly":
            next_start = cursor + timedelta(days=7)
        elif scheduled.repeat_mode == "monthly":
            month = cursor.month + 1
            year = cursor.year + (1 if month > 12 else 0)
            month = 1 if month > 12 else month
            day = min(cursor.day, 28)
            next_start = cursor.replace(year=year, month=month, day=day)
        elif scheduled.repeat_mode == "weekdays":
            weekdays = sorted({int(day) for day in scheduled.repeat_weekdays if 0 <= int(day) <= 6})
            if not weekdays:
                return None
            next_start = cursor + timedelta(days=1)
            for _ in range(14):
                if next_start.weekday() in weekdays:
                    break
                next_start += timedelta(days=1)
        else:
            return None
        return next_start, (next_start + duration) if duration is not None else None

    async def _create_next_scheduled_occurrence(self, scheduled: ScheduledVC) -> None:
        next_range = self._next_scheduled_occurrence(scheduled)
        if next_range is None:
            return
        next_start, next_end = next_range
        await self.config_repo.create_scheduled_vc(
            ScheduledVC(
                id=None,
                guild_id=scheduled.guild_id,
                guild_name=scheduled.guild_name,
                creator_user_id=scheduled.creator_user_id,
                creator_user_name=scheduled.creator_user_name,
                vc_name=scheduled.vc_name,
                category_id=scheduled.category_id,
                user_limit=scheduled.user_limit,
                bitrate=scheduled.bitrate,
                mention_type=scheduled.mention_type,
                mention_targets=scheduled.mention_targets.copy(),
                description=scheduled.description,
                start_at=next_start,
                end_at=next_end,
                repeat_mode=scheduled.repeat_mode,
                repeat_weekdays=scheduled.repeat_weekdays.copy(),
            )
        )

    async def _start_scheduled_vc(self, scheduled: ScheduledVC) -> None:
        if scheduled.id is None:
            return
        config = self.guild_configs.get(scheduled.guild_id)
        locale = config.guild_language if config else None
        guild = self._resolve_guild(scheduled.guild_id)
        if guild is None:
            await self.config_repo.update_scheduled_vc_status(scheduled.id, "failed")
            await self._publish_scheduled_vc_notification(
                "error", t("scheduled.error.createTitle", locale), t("scheduled.error.guildNotFound", locale), scheduled
            )
            return
        category = guild.get_channel(scheduled.category_id) if scheduled.category_id is not None else None
        if scheduled.category_id is not None and not isinstance(category, discord.CategoryChannel):
            await self.config_repo.update_scheduled_vc_status(scheduled.id, "failed")
            await self._publish_scheduled_vc_notification(
                "error", t("scheduled.error.createTitle", locale), t("scheduled.error.categoryUnavailable", locale), scheduled
            )
            return
        try:
            create_kwargs: dict[str, Any] = {
                "category": category if isinstance(category, discord.CategoryChannel) else None,
                "user_limit": max(0, min(99, scheduled.user_limit)),
                "reason": "scheduled VC start",
            }
            if scheduled.bitrate is not None:
                create_kwargs["bitrate"] = scheduled.bitrate
            channel = await guild.create_voice_channel(scheduled.vc_name, **create_kwargs)
        except discord.Forbidden:
            await self.config_repo.update_scheduled_vc_status(scheduled.id, "failed")
            await self._publish_scheduled_vc_notification(
                "permission_denied", t("scheduled.error.permissionTitle", locale), t("scheduled.error.createPermission", locale), scheduled
            )
            return
        except discord.HTTPException:
            self.logger.exception("scheduled VC create failed: scheduled_id=%s", scheduled.id)
            await self.config_repo.update_scheduled_vc_status(scheduled.id, "failed")
            await self._publish_scheduled_vc_notification(
                "error", t("scheduled.error.createTitle", locale), t("scheduled.error.createFailed", locale), scheduled
            )
            return

        self.auto_personal_root_channels.discard(channel.id)
        status = "active" if scheduled.end_at is not None else "completed"
        await self.config_repo.update_scheduled_vc_start_result(scheduled.id, channel_id=channel.id, status=status)
        if scheduled.repeat_mode != "none":
            await self._create_next_scheduled_occurrence(scheduled)

        description = scheduled.description.strip() or t("scheduled.defaultDescription", locale)
        if scheduled.end_at is not None:
            description += t("scheduled.endAtSuffix", locale, time=discord.utils.format_dt(scheduled.end_at, style="F"))
        embed = build_embed(
            locale,
            "embed.scheduled_vc_started.title",
            color=COLOR_SUCCESS,
            title_fmt={"name": scheduled.vc_name},
        )
        embed.description = description
        await self._send_scheduled_vc_message(channel, scheduled, embed)
        notice_channel = await self._resolve_notice_channel(scheduled.guild_id)
        if notice_channel is not None:
            await self._send_scheduled_vc_message(notice_channel, scheduled, embed)
        await self._send_scheduled_vc_dms(scheduled, embed)
        await self._record_scheduled_vc_timeline(
            scheduled, channel, "scheduled_vc_created", t("scheduled.notif.startedDesc", locale, name=scheduled.vc_name)
        )
        await self._publish_scheduled_vc_notification(
            "scheduled_vc_started",
            t("scheduled.notif.startedTitle", locale),
            t("scheduled.notif.startedDesc", locale, name=scheduled.vc_name),
            scheduled,
            channel_id=channel.id,
        )

    async def _process_active_scheduled_vc(self, scheduled: ScheduledVC, now: datetime) -> None:
        if scheduled.id is None or scheduled.end_at is None or scheduled.created_channel_id is None:
            return
        config = self.guild_configs.get(scheduled.guild_id)
        locale = config.guild_language if config else None
        channel = self._resolve_voice_channel(scheduled.created_channel_id)
        if channel is None:
            await self.config_repo.update_scheduled_vc_status(scheduled.id, "completed")
            return
        remaining = int((scheduled.end_at - now).total_seconds())
        for minutes, already_sent in ((15, scheduled.pre_notice_15_sent), (5, scheduled.pre_notice_5_sent), (3, scheduled.pre_notice_3_sent)):
            if not already_sent and 0 < remaining <= minutes * 60:
                embed = build_embed(
                    locale,
                    "embed.scheduled_vc_ending.title",
                    "embed.scheduled_vc_ending.description",
                    color=COLOR_WARNING,
                    title_fmt={"minutes": minutes},
                    description_fmt={"name": scheduled.vc_name},
                )
                await self._send_embed(channel, embed)
                await self.config_repo.mark_scheduled_vc_pre_notice(scheduled.id, minutes)
        if remaining > 0:
            return
        session = self.sessions.get(channel.id)
        if session is not None:
            await self._end_session(session)
        try:
            await channel.delete(reason="予約VCの終了時刻に到達")
        except discord.Forbidden:
            await self._publish_scheduled_vc_notification(
                "permission_denied", t("scheduled.error.permissionTitle", locale), t("scheduled.error.deletePermission", locale), scheduled, channel_id=channel.id
            )
            return
        except discord.HTTPException:
            self.logger.exception("scheduled VC delete failed: scheduled_id=%s", scheduled.id)
            await self._publish_scheduled_vc_notification(
                "error", t("scheduled.error.deleteTitle", locale), t("scheduled.error.deleteFailed", locale), scheduled, channel_id=channel.id
            )
            return
        await self.config_repo.update_scheduled_vc_status(scheduled.id, "completed")
        await self._publish_scheduled_vc_notification(
            "scheduled_vc_ended",
            t("scheduled.notif.endedTitle", locale),
            t("scheduled.notif.endedDesc", locale, name=scheduled.vc_name),
            scheduled,
            channel_id=channel.id,
        )

    async def cancel_scheduled_vc(self, scheduled: ScheduledVC) -> None:
        if scheduled.id is None:
            return
        if scheduled.created_channel_id is not None:
            config = self.guild_configs.get(scheduled.guild_id)
            locale = config.guild_language if config else None
            channel = self._resolve_voice_channel(scheduled.created_channel_id)
            if channel is not None:
                session = self.sessions.get(channel.id)
                if session is not None:
                    await self._end_session(session)
                try:
                    await channel.delete(reason="予約VCの削除によるキャンセル")
                except discord.Forbidden:
                    await self._publish_scheduled_vc_notification(
                        "permission_denied",
                        t("scheduled.error.deletePermissionTitle", locale),
                        t("scheduled.error.deletePermission", locale),
                        scheduled,
                        channel_id=channel.id,
                    )
                except discord.HTTPException:
                    self.logger.exception("予約VCキャンセル時のチャンネル削除に失敗: scheduled_id=%s", scheduled.id)
        await self.config_repo.delete_scheduled_vc(scheduled.id)

    async def _start_session(
        self,
        channel: discord.VoiceChannel,
        starter: discord.Member,
        current_members: list[discord.Member],
        suppressed: bool = False,
    ) -> None:
        config = await self.get_guild_config(channel.guild.id)
        if config is None:
            return
        session = LiveSession(
            session_id=str(uuid.uuid4()),
            guild_id=channel.guild.id,
            guild_name=channel.guild.name,
            root_channel_id=channel.id,
            root_channel_name=channel.name,
            starter_user_id=starter.id,
            starter_user_name=starter.display_name,
            owner_user_id=starter.id,
            owner_user_name=starter.display_name,
            started_at=utcnow(),
            team_names=config.team_names.copy(),
            team_mode=config.team_mode,
        )
        management_url = await self.build_management_url(session.guild_id, session.root_channel_id)
        self.logger.info(
            "セッション作成: session_key=%s session_id=%s starter=%s",
            session.session_key,
            session.session_id,
            starter.id,
        )
        self._register_session(session)
        for member in current_members:
            voice_state = member.voice
            participant = LiveParticipant(
                user_id=member.id,
                user_name=member.display_name,
                joined_at=utcnow(),
                last_transition_at=utcnow(),
                current_channel_id=channel.id,
                current_team=session.team_assignments.get(member.id),
            )
            participant.apply_voice_state(voice_state)
            session.participants[member.id] = participant
            session.member_order.append(member.id)
        locale = config.guild_language
        start_embed = self._build_start_embed(session, starter, management_url, locale)
        start_view = self._build_management_link_view(management_url)
        await self._send_embed(channel, start_embed, view=start_view)
        from vc_control.team_ui import TeamPanelView

        await self._send_embed(
            channel,
            self._build_management_panel_embed(session, management_url, locale),
            view=TeamPanelView(self, session.root_channel_id, management_url=management_url),
        )
        await self._send_notification_message(session, start_embed, view=start_view)
        if not suppressed:
            await self._send_embed(
                channel,
                build_embed(
                    locale,
                    "embed.member_joined.title",
                    "embed.member_joined.description",
                    color=COLOR_SUCCESS,
                    description_fmt={"mention": starter.mention},
                ),
            )
        await self._persist_and_broadcast(session)
        await self._record_timeline_event(
            session,
            "vc_started",
            f"{session.root_channel_name} started.",
            user_id=starter.id,
            user_name=starter.display_name,
        )
        for member in current_members:
            if member.bot:
                continue
            await self._record_timeline_event(
                session,
                "member_joined",
                f"{member.display_name} joined.",
                user_id=member.id,
                user_name=member.display_name,
            )
        await self._publish_important_event(
            "vc_started",
            t("event.title.vcStarted", locale),
            t("event.vcStartedDesc", locale, channel=session.root_channel_name),
            session,
        )

    async def _join_existing_session(
        self,
        member: discord.Member,
        channel: discord.VoiceChannel,
        state: discord.VoiceState,
        suppressed: bool,
    ) -> None:
        root_id = self.channel_to_root.get(channel.id)
        if root_id is None:
            return
        session = self.sessions.get(root_id)
        if session is None:
            return
        now = utcnow()
        participant = session.participants.get(member.id)
        if participant is None:
            participant = LiveParticipant(
                user_id=member.id,
                user_name=member.display_name,
                joined_at=now,
                last_transition_at=now,
                current_channel_id=channel.id,
                current_team=session.team_assignments.get(member.id),
            )
            session.participants[member.id] = participant
            session.member_order.append(member.id)
        else:
            participant.accrue(now)
            participant.user_name = member.display_name
            participant.current_channel_id = channel.id
            participant.last_transition_at = now
        participant.apply_voice_state(state)
        await self._cancel_empty_cleanup(channel)
        if not suppressed:
            config = self.guild_configs.get(session.guild_id)
            await self._send_embed(
                channel,
                build_embed(
                    config.guild_language if config else None,
                    "embed.member_joined.title",
                    "embed.member_joined.description",
                    color=COLOR_SUCCESS,
                    description_fmt={"mention": member.mention},
                ),
            )
        await self._persist_and_broadcast(session)
        await self._record_timeline_event(
            session,
            "member_joined",
            f"{member.display_name} joined.",
            user_id=member.id,
            user_name=member.display_name,
        )
        await self._publish_session_event(session, "member_joined", {"user_id": str(member.id)})

    async def _leave_session_channel(
        self,
        member: discord.Member,
        channel: discord.VoiceChannel,
        state: discord.VoiceState,
        suppressed: bool,
    ) -> None:
        root_id = self.channel_to_root.get(channel.id)
        if root_id is None:
            return
        session = self.sessions.get(root_id)
        if session is None:
            return
        participant = session.participants.get(member.id)
        if participant is None:
            return
        now = utcnow()
        participant.accrue(now)
        participant.current_channel_id = None
        participant.user_name = member.display_name
        participant.apply_voice_state(None)

        config = self.guild_configs.get(session.guild_id)
        locale = config.guild_language if config else None
        if not suppressed:
            await self._send_embed(
                channel,
                build_embed(
                    locale,
                    "embed.member_left.title",
                    "embed.member_left.description",
                    color=COLOR_ERROR,
                    description_fmt={"mention": member.mention},
                ),
            )

        active_users = session.active_participants()
        if session.owner_user_id == member.id and active_users:
            next_owner = active_users[0]
            session.owner_user_id = next_owner.user_id
            session.owner_user_name = next_owner.user_name
            await self._send_embed(
                self._resolve_voice_channel(session.root_channel_id),
                build_embed(
                    locale,
                    "embed.owner_changed.title",
                    "embed.owner_changed.description",
                    color=COLOR_WARNING,
                    description_fmt={"mention": f"<@{next_owner.user_id}>"},
                ),
            )

        if not session.active_participants():
            await self._record_timeline_event(
                session,
                "member_left",
                f"{member.display_name} left.",
                user_id=member.id,
                user_name=member.display_name,
            )
            await self._end_session(session)
            return

        await self._persist_and_broadcast(session)
        await self._record_timeline_event(
            session,
            "member_left",
            f"{member.display_name} left.",
            user_id=member.id,
            user_name=member.display_name,
        )
        await self._publish_session_event(session, "member_left", {"user_id": str(member.id)})

    async def _move_within_session(
        self,
        member: discord.Member,
        before_channel: discord.VoiceChannel,
        after_channel: discord.VoiceChannel,
        before_state: discord.VoiceState,
        after_state: discord.VoiceState,
        suppressed: bool,
    ) -> None:
        root_id = self.channel_to_root.get(before_channel.id)
        if root_id is None:
            return
        session = self.sessions.get(root_id)
        if session is None:
            return
        participant = session.participants.get(member.id)
        if participant is None:
            return
        now = utcnow()
        participant.accrue(now)
        participant.current_channel_id = after_channel.id
        participant.user_name = member.display_name
        participant.apply_voice_state(after_state)
        await self._cancel_empty_cleanup(after_channel)
        if not before_channel.members:
            await self._schedule_empty_cleanup(before_channel)
        if not suppressed:
            config = self.guild_configs.get(session.guild_id)
            locale = config.guild_language if config else None
            leave_embed = build_embed(
                locale,
                "embed.member_moved_leave.title",
                "embed.member_moved_leave.description",
                color=COLOR_ERROR,
                description_fmt={"mention": member.mention, "channel": before_channel.name},
            )
            join_embed = build_embed(
                locale,
                "embed.member_moved_join.title",
                "embed.member_moved_join.description",
                color=COLOR_SUCCESS,
                description_fmt={"mention": member.mention, "channel": after_channel.name},
            )
            await self._send_embed(before_channel, leave_embed)
            await self._send_embed(after_channel, join_embed)
        await self._persist_and_broadcast(session)
        await self._record_timeline_event(
            session,
            "member_moved",
            f"{member.display_name} moved from {before_channel.name} to {after_channel.name}.",
            user_id=member.id,
            user_name=member.display_name,
            payload={"before_channel_id": str(before_channel.id), "after_channel_id": str(after_channel.id)},
        )
        await self._publish_session_event(
            session,
            "member_moved",
            {
                "user_id": str(member.id),
                "before_channel_id": str(before_channel.id),
                "after_channel_id": str(after_channel.id),
            },
        )

    async def _end_session(self, session: LiveSession) -> None:
        self._cancel_solo_cleanup_by_channel_id(session.root_channel_id)
        now = utcnow()
        members: list[CompletedMember] = []
        total_talk = 0
        total_afk = 0
        for participant in session.participants.values():
            participant.accrue(now)
            member = CompletedMember(
                user_id=participant.user_id,
                user_name=participant.user_name,
                joined_at=participant.joined_at,
                left_at=now,
                talk_seconds=participant.talk_seconds,
                afk_seconds=participant.afk_seconds,
                afk_channel_seconds=participant.afk_channel_seconds,
                self_mute_seconds=participant.self_mute_seconds,
                self_deafen_seconds=participant.self_deafen_seconds,
                is_owner=participant.user_id == session.owner_user_id,
            )
            members.append(member)
            total_talk += participant.talk_seconds
            total_afk += participant.afk_seconds
        completed = CompletedSession(
            session_id=session.session_id,
            guild_id=session.guild_id,
            guild_name=session.guild_name,
            root_channel_id=session.root_channel_id,
            root_channel_name=session.root_channel_name,
            started_by=session.starter_user_id,
            started_by_name=session.starter_user_name,
            started_at=session.started_at,
            ended_at=now,
            total_talk_seconds=total_talk,
            total_afk_seconds=total_afk,
            members=members,
            payload=session.to_payload(),
        )
        try:
            await self.stats_repo.record_completed_session(completed)
        except Exception:
            self.logger.exception("統計保存に失敗しました: session_key=%s", session.session_key)
        try:
            await self.config_repo.delete_session_snapshot(session.session_id)
        except Exception:
            self.logger.exception("セッションスナップショット削除に失敗しました: session_key=%s", session.session_key)
        await self._delete_notification_message(session)
        session.notice_message_id = None
        config = self.guild_configs.get(session.guild_id)
        locale = config.guild_language if config else None
        end_embed = self._build_end_embed(session, completed, locale)
        await self._send_notification_message(session, end_embed)
        await self._record_timeline_event(
            session,
            "vc_ended",
            f"{session.root_channel_name} ended.",
            payload={"total_talk_seconds": total_talk, "total_afk_seconds": total_afk},
        )
        await self._publish_important_event(
            "vc_ended",
            t("event.title.vcEnded", locale),
            t("event.vcEndedDesc", locale, channel=session.root_channel_name),
            session,
            extra_payload={"total_talk_seconds": total_talk, "total_afk_seconds": total_afk},
        )
        await self._send_embed(self._resolve_voice_channel(session.root_channel_id), end_embed)
        self._unregister_session(session)
        await self._broadcast_global_state()

    async def handle_channel_delete(self, channel: discord.abc.GuildChannel) -> None:
        if not isinstance(channel, discord.VoiceChannel):
            return
        root_id = self.channel_to_root.get(channel.id)
        if root_id is None:
            return
        session = self.sessions.get(root_id)
        if session is None:
            return
        if channel.id == session.root_channel_id:
            self._cancel_solo_cleanup_by_channel_id(channel.id)
            self._unregister_session(session)
            await self.config_repo.delete_session_snapshot(session.session_id)
        else:
            for team_name, team_channel_id in list(session.team_channels.items()):
                if team_channel_id == channel.id:
                    session.team_channels.pop(team_name, None)
                    self.channel_to_root.pop(channel.id, None)
                    await self._persist_and_broadcast(session)
                    break

    async def handle_message(self, message: discord.Message) -> None:
        if message.author.bot or not isinstance(message.channel, discord.VoiceChannel):
            return
        if not self._is_managed_voice_channel(message.channel, include_base=False):
            return
        root_id = self.channel_to_root.get(message.channel.id)
        if root_id is None:
            return
        config = self.guild_configs.get(message.channel.guild.id)
        locale = config.guild_language if config else None
        if message.mention_everyone:
            await self._send_embed(
                message.channel,
                build_embed(
                    locale,
                    "embed.everyone_mention_warning.title",
                    "embed.everyone_mention_warning.description",
                    color=COLOR_ERROR,
                ),
            )
            return
        for user in message.mentions:
            if user.bot:
                continue
            try:
                await user.send(
                    embed=build_embed(
                        locale,
                        "embed.vc_mention.title",
                        "embed.vc_mention.description",
                        color=BRAND_BLUE,
                        description_fmt={
                            "author": message.author.mention,
                            "channel": message.channel.mention,
                            "content": message.content,
                        },
                    )
                )
            except discord.Forbidden:
                self.logger.info("DM送信をスキップしました: user=%s", user.id)
            except discord.HTTPException:
                self.logger.exception("DM転送に失敗しました")

    async def set_panel_creator(self, root_channel_id: int, user: discord.Member) -> None:
        session = self.sessions.get(int(root_channel_id))
        if session is None:
            return
        session.panel_creator_id = user.id
        session.panel_creator_name = user.display_name
        for participant in session.participants.values():
            participant.panel_creator = False
        participant = session.participants.get(user.id)
        if participant:
            participant.panel_creator = True
        await self._persist_and_broadcast(session)

    def get_session_by_root(self, root_channel_id: int) -> LiveSession | None:
        normalized_root_channel_id = int(root_channel_id)
        session = self.sessions.get(normalized_root_channel_id)
        if session is not None:
            return session
        for _, active_session in self.sessions_by_key.items():
            if int(active_session.root_channel_id) != normalized_root_channel_id:
                continue
            self.sessions[normalized_root_channel_id] = active_session
            return active_session
        return None

    def get_session_by_channel(self, channel_id: int) -> LiveSession | None:
        root_id = self.channel_to_root.get(int(channel_id))
        if root_id is None:
            return None
        return self.get_session_by_root(root_id)

    async def is_guild_admin(self, guild_id: int, user_id: int) -> bool:
        if self.bot is None:
            return False
        guild = self.bot.get_guild(guild_id)
        if guild is None:
            return False
        member = guild.get_member(user_id)
        if member is None:
            return False
        return member.guild_permissions.manage_guild or member.guild_permissions.administrator

    async def can_view_session(self, session: LiveSession, user_id: int) -> bool:
        if await self.is_guild_admin(session.guild_id, user_id):
            return True
        if session.starter_user_id == user_id:
            return True
        if session.access_mode == "invite" and str(user_id) in session.invited_user_ids:
            return True
        if session.access_mode == "role":
            guild = self._resolve_guild(session.guild_id)
            member = guild.get_member(user_id) if guild is not None else None
            if member is not None and any(str(role.id) in session.access_role_ids for role in member.roles):
                return True
        if session.panel_creator_id == user_id:
            return True
        if session.access_mode in {"invite", "role"}:
            return False
        participant = session.participants.get(user_id)
        return participant is not None and participant.current_channel_id is not None

    async def can_edit_session(self, session: LiveSession, user_id: int) -> bool:
        if session.starter_user_id == user_id:
            return True
        return await self.is_guild_admin(session.guild_id, user_id)

    async def _apply_access_overwrites(self, session: LiveSession) -> None:
        guild = self._resolve_guild(session.guild_id)
        if guild is None:
            return
        channel_ids = [session.root_channel_id, *session.team_channels.values()]
        default_role = guild.default_role
        bot_member = guild.me
        for channel_id in channel_ids:
            channel = self._resolve_voice_channel(channel_id)
            if channel is None:
                continue
            try:
                if session.access_mode == "public":
                    await channel.set_permissions(default_role, overwrite=None, reason="VCアクセスを公開に設定")
                    for user_id in session.invited_user_ids:
                        member = guild.get_member(int(user_id)) if str(user_id).isdigit() else None
                        if member is not None:
                            await channel.set_permissions(member, overwrite=None, reason="VCアクセスを公開に設定")
                    for role_id in session.access_role_ids:
                        role = guild.get_role(int(role_id)) if str(role_id).isdigit() else None
                        if role is not None:
                            await channel.set_permissions(role, overwrite=None, reason="VCアクセスを公開に設定")
                    continue

                await channel.set_permissions(
                    default_role,
                    overwrite=discord.PermissionOverwrite(view_channel=False, connect=False),
                    reason="VCアクセスを制限",
                )
                if bot_member is not None:
                    await channel.set_permissions(
                        bot_member,
                        overwrite=discord.PermissionOverwrite(view_channel=True, connect=True, manage_channels=True, send_messages=True),
                        reason="VCアクセスを制限",
                    )
                starter = guild.get_member(session.starter_user_id)
                if starter is not None:
                    await channel.set_permissions(
                        starter,
                        overwrite=discord.PermissionOverwrite(view_channel=True, connect=True),
                        reason="VCアクセスを制限",
                    )
                if session.access_mode == "invite":
                    for user_id in session.invited_user_ids:
                        member = guild.get_member(int(user_id)) if str(user_id).isdigit() else None
                        if member is not None:
                            await channel.set_permissions(
                                member,
                                overwrite=discord.PermissionOverwrite(view_channel=True, connect=True),
                                reason="VC招待アクセスを更新",
                            )
                    for role_id in session.access_role_ids:
                        role = guild.get_role(int(role_id)) if str(role_id).isdigit() else None
                        if role is not None:
                            await channel.set_permissions(role, overwrite=None, reason="VC招待アクセスを更新")
                if session.access_mode == "role":
                    for role_id in session.access_role_ids:
                        role = guild.get_role(int(role_id)) if str(role_id).isdigit() else None
                        if role is not None:
                            await channel.set_permissions(
                                role,
                                overwrite=discord.PermissionOverwrite(view_channel=True, connect=True),
                                reason="VCロールアクセスを更新",
                            )
                    for user_id in session.invited_user_ids:
                        member = guild.get_member(int(user_id)) if str(user_id).isdigit() else None
                        if member is not None and member.id != session.starter_user_id:
                            await channel.set_permissions(member, overwrite=None, reason="VCロールアクセスを更新")
            except discord.Forbidden:
                self.logger.exception("VC access permission update denied: session_key=%s channel_id=%s", session.session_key, channel_id)
                raise PermissionError("Botにチャンネル権限を更新する権限がありません。")
            except discord.HTTPException as exc:
                self.logger.exception("VC access permission update failed: session_key=%s channel_id=%s", session.session_key, channel_id)
                raise RuntimeError("チャンネル権限の更新に失敗しました。") from exc

    async def update_access_control(
        self,
        root_channel_id: int,
        actor_id: int,
        *,
        access_mode: str,
        invited_user_ids: list[str] | None = None,
        access_role_ids: list[str] | None = None,
    ) -> str:
        session = self.sessions.get(root_channel_id)
        if session is None:
            raise ValueError(t("msg.sessionNotFound", None))
        config = self.guild_configs.get(session.guild_id)
        locale = config.guild_language if config else None
        if not await self.can_edit_session(session, actor_id):
            raise PermissionError(t("msg.noPermissionAccessControl", locale))
        mode = access_mode if access_mode in {"public", "invite", "role"} else "public"
        old_invited = set(session.invited_user_ids)
        old_roles = set(session.access_role_ids)
        final_invited = {str(item).strip() for item in (invited_user_ids or sorted(session.invited_user_ids)) if str(item).strip().isdigit()}
        final_roles = {str(item).strip() for item in (access_role_ids or sorted(session.access_role_ids)) if str(item).strip().isdigit()}
        session.access_mode = mode
        session.invited_user_ids = final_invited | old_invited
        session.access_role_ids = final_roles | old_roles
        await self._apply_access_overwrites(session)
        session.invited_user_ids = final_invited if mode == "invite" else set()
        session.access_role_ids = final_roles if mode == "role" else set()
        await self._persist_and_broadcast(session)
        mode_label = _access_mode_label(mode, locale)
        await self._record_timeline_event(
            session,
            "access_changed",
            f"アクセスモードを{mode_label}に変更しました。",
            user_id=actor_id,
            user_name=str(actor_id),
            payload={
                "access_mode": mode,
                "invited_user_ids": sorted(session.invited_user_ids),
                "access_role_ids": sorted(session.access_role_ids),
            },
        )
        await self._publish_important_event(
            "access_changed",
            t("event.title.accessChanged", locale),
            t("event.accessChangedDesc", locale, channel=session.root_channel_name, mode=mode_label),
            session,
            extra_payload={"access_mode": mode},
        )
        return t("msg.accessModeUpdated", locale, mode=mode_label)

    async def add_invited_users(self, root_channel_id: int, actor_id: int, user_ids: list[str]) -> str:
        session = self.sessions.get(root_channel_id)
        if session is None:
            raise ValueError(t("msg.sessionNotFound", None))
        merged = sorted(session.invited_user_ids | {str(item).strip() for item in user_ids if str(item).strip().isdigit()})
        return await self.update_access_control(root_channel_id, actor_id, access_mode="invite", invited_user_ids=merged)

    async def can_assign_others(self, session: LiveSession, user_id: int) -> bool:
        if session.starter_user_id == user_id:
            return True
        if session.panel_creator_id == user_id:
            return True
        return await self.is_guild_admin(session.guild_id, user_id)

    async def can_execute_team_actions(self, session: LiveSession, user_id: int) -> bool:
        if session.starter_user_id == user_id:
            return True
        if session.panel_creator_id == user_id:
            return True
        return await self.is_guild_admin(session.guild_id, user_id)

    async def assign_team(
        self,
        root_channel_id: int,
        actor_id: int,
        target_user_id: int,
        team_name: str | None,
    ) -> str:
        session = self.sessions.get(root_channel_id)
        if session is None:
            raise ValueError(t("msg.sessionNotFound", None))
        config = self.guild_configs.get(session.guild_id)
        locale = config.guild_language if config else None
        participant = session.participants.get(target_user_id)
        if participant is None:
            raise ValueError(t("msg.targetUserNotFound", locale))
        if target_user_id != actor_id and not await self.can_assign_others(session, actor_id):
            raise PermissionError(t("msg.noPermissionAssignOthers", locale))
        if team_name and team_name not in session.team_names:
            raise ValueError(t("msg.teamNotExist", locale))
        participant.current_team = team_name
        if team_name is None:
            session.team_assignments.pop(target_user_id, None)
        else:
            session.team_assignments[target_user_id] = team_name
        await self._persist_and_broadcast(session)
        await self._record_timeline_event(
            session,
            "team_changed",
            f"{participant.user_name} team changed to {team_name or 'unassigned'}.",
            user_id=target_user_id,
            user_name=participant.user_name,
            payload={"team_name": team_name},
        )
        await self._publish_session_event(
            session,
            "team_changed",
            {"user_id": str(target_user_id), "team_name": team_name},
        )
        return t("msg.teamAssignedTo", locale, userId=target_user_id, team=team_name or t("common.unassigned", locale))

    async def update_team_settings(
        self,
        root_channel_id: int,
        actor_id: int,
        team_names: list[str],
        team_mode: str,
    ) -> None:
        session = self.sessions.get(root_channel_id)
        if session is None:
            raise ValueError(t("msg.sessionNotFound", None))
        if not await self.can_assign_others(session, actor_id):
            config = self.guild_configs.get(session.guild_id)
            raise PermissionError(t("msg.noPermissionTeamSettings", config.guild_language if config else None))
        normalized = [name.strip() for name in team_names if name.strip()]
        if not normalized:
            config = self.guild_configs.get(session.guild_id)
            raise ValueError(t("msg.teamNamesRequired", config.guild_language if config else None))
        session.team_names = normalized
        session.team_mode = team_mode
        for user_id, current_team in list(session.team_assignments.items()):
            if current_team not in normalized:
                session.team_assignments.pop(user_id, None)
                participant = session.participants.get(user_id)
                if participant:
                    participant.current_team = None
        await self._persist_and_broadcast(session)
        await self._publish_session_event(session, "team_settings_changed", {"team_names": session.team_names})

    async def split_teams(self, root_channel_id: int, actor_id: int) -> list[str]:
        session = self.sessions.get(root_channel_id)
        if session is None:
            raise ValueError(t("msg.sessionNotFound", None))
        config = self.guild_configs.get(session.guild_id)
        locale = config.guild_language if config else None
        if not await self.can_execute_team_actions(session, actor_id):
            raise PermissionError(t("msg.noPermissionSplit", locale))
        guild = self._resolve_guild(session.guild_id)
        root_channel = self._resolve_voice_channel(session.root_channel_id)
        if guild is None or root_channel is None:
            raise ValueError(t("msg.channelUnresolvable", locale))
        moved_messages: list[str] = []
        async with session.lock:
            for team_name in session.team_names:
                team_members = [
                    participant
                    for participant in session.active_participants()
                    if session.team_assignments.get(participant.user_id) == team_name
                ]
                if not team_members:
                    continue
                team_channel = await self._ensure_team_channel(root_channel, session, team_name)
                if team_channel is None:
                    continue
                await self._cancel_empty_cleanup(team_channel)
                for participant in team_members:
                    member = guild.get_member(participant.user_id)
                    if member is None or member.voice is None or member.voice.channel is None:
                        continue
                    if member.voice.channel.id == team_channel.id:
                        continue
                    self._mark_system_move(participant.user_id, member.voice.channel.id, team_channel.id, "team_split")
                    try:
                        await member.move_to(team_channel, reason="チーム分割")
                    except discord.Forbidden:
                        self.logger.exception("チームVCへの移動権限がありません")
                    except discord.HTTPException:
                        self.logger.exception("チームVCへの移動に失敗しました")
                names = ", ".join(f"<@{participant.user_id}>" for participant in team_members)
                moved_messages.append(f"{team_name}: {names}")
                await self._send_embed(
                    team_channel,
                    build_embed(
                        locale,
                        "embed.team_moved.title",
                        "embed.team_moved.description",
                        color=BRAND_BLUE,
                        description_fmt={"names": names, "team": team_name},
                    ),
                )
            if moved_messages:
                await self._send_embed(
                    root_channel,
                    discord.Embed(
                        title=t("embed.teams_split.title", locale),
                        description="\n".join(moved_messages),
                        color=BRAND_BLUE,
                    ),
                )
            await self._persist_and_broadcast(session)
            actor = guild.get_member(actor_id)
            await self._record_timeline_event(
                session,
                "teams_split",
                "チームを分割しました。",
                user_id=actor_id,
                user_name=actor.display_name if actor is not None else str(actor_id),
                payload={"messages": moved_messages},
            )
            await self._publish_session_event(session, "teams_split", {"messages": moved_messages})
        return moved_messages

    async def assemble_teams(self, root_channel_id: int, actor_id: int) -> list[str]:
        session = self.sessions.get(root_channel_id)
        if session is None:
            raise ValueError(t("msg.sessionNotFound", None))
        config = self.guild_configs.get(session.guild_id)
        locale = config.guild_language if config else None
        if not await self.can_execute_team_actions(session, actor_id):
            raise PermissionError(t("msg.noPermissionAssemble", locale))
        guild = self._resolve_guild(session.guild_id)
        root_channel = self._resolve_voice_channel(session.root_channel_id)
        if guild is None or root_channel is None:
            raise ValueError(t("msg.channelUnresolvable", locale))
        moved_users: list[str] = []
        async with session.lock:
            for participant in session.active_participants():
                if participant.current_channel_id == root_channel.id:
                    continue
                member = guild.get_member(participant.user_id)
                if member is None or member.voice is None or member.voice.channel is None:
                    continue
                self._mark_system_move(participant.user_id, member.voice.channel.id, root_channel.id, "team_collect")
                try:
                    await member.move_to(root_channel, reason="チーム集合")
                    moved_users.append(f"<@{participant.user_id}>")
                except discord.Forbidden:
                    self.logger.exception("集合時の移動権限がありません")
                except discord.HTTPException:
                    self.logger.exception("集合時の移動に失敗しました")
            if moved_users:
                await self._send_embed(
                    root_channel,
                    build_embed(
                        locale,
                        "embed.teams_assembled.title",
                        "embed.teams_assembled.description",
                        color=COLOR_NOTIFY,
                        description_fmt={"names": ", ".join(moved_users)},
                    ),
                )
            await self._persist_and_broadcast(session)
            await self._record_timeline_event(
                session,
                "teams_assembled",
                "チームが集合しました。",
                payload={"users": moved_users},
            )
            await self._publish_session_event(session, "teams_assembled", {"users": moved_users})
        return moved_users

    async def recall_member(self, root_channel_id: int, actor_id: int, target_user_id: int) -> str:
        session = self.sessions.get(root_channel_id)
        if session is None:
            raise ValueError(t("msg.sessionNotFound", None))
        config = self.guild_configs.get(session.guild_id)
        locale = config.guild_language if config else None
        if not await self.can_execute_team_actions(session, actor_id):
            raise PermissionError(t("msg.noPermissionRecall", locale))
        guild = self._resolve_guild(session.guild_id)
        root_channel = self._resolve_voice_channel(session.root_channel_id)
        if guild is None or root_channel is None:
            raise ValueError(t("msg.channelUnresolvable", locale))
        participant = session.participants.get(target_user_id)
        member = guild.get_member(target_user_id) if guild else None
        if participant is None or member is None or member.voice is None or member.voice.channel is None:
            raise ValueError(t("msg.targetNotInVoice", locale))
        self._mark_system_move(participant.user_id, member.voice.channel.id, root_channel.id, "team_recall")
        try:
            await member.move_to(root_channel, reason="個別呼び戻し")
        except discord.Forbidden as exc:
            raise PermissionError(t("msg.noPermissionRecall", locale)) from exc
        except discord.HTTPException as exc:
            raise ValueError(t("msg.recallFailed", locale)) from exc
        message = t("msg.recalledTo", locale, userId=target_user_id)
        await self._send_embed(
            root_channel,
            discord.Embed(title=t("embed.member_recalled.title", locale), description=message, color=COLOR_NOTIFY),
        )
        await self._persist_and_broadcast(session)
        await self._record_timeline_event(
            session,
            "member_recalled",
            f"{participant.user_name} was recalled.",
            user_id=target_user_id,
            user_name=participant.user_name,
        )
        await self._publish_session_event(session, "member_recalled", {"user_id": str(target_user_id)})
        return message

    async def update_voice_settings(
        self,
        root_channel_id: int,
        name: str | None = None,
        user_limit: int | None = None,
        bitrate: int | None = None,
    ) -> None:
        channel = self._resolve_voice_channel(root_channel_id)
        session = self.sessions.get(root_channel_id)
        if channel is None or session is None:
            raise ValueError("チャンネルが見つかりません。")
        await channel.edit(
            name=name or channel.name,
            user_limit=user_limit if user_limit is not None else channel.user_limit,
            bitrate=bitrate if bitrate is not None else channel.bitrate,
            reason="Web管理画面からのVC設定変更",
        )
        session.root_channel_name = name or channel.name
        await self._persist_and_broadcast(session)
        await self._record_timeline_event(
            session,
            "voice_settings_changed",
            f"VC settings changed: {session.root_channel_name}.",
            payload={
                "name": session.root_channel_name,
                "user_limit": channel.user_limit,
                "bitrate": channel.bitrate,
            },
        )
        await self._publish_session_event(
            session,
            "voice_settings_changed",
            {
                "name": session.root_channel_name,
                "user_limit": channel.user_limit,
                "bitrate": channel.bitrate,
            },
        )

    async def set_member_server_state(
        self,
        root_channel_id: int,
        target_user_id: int,
        mute: bool | None = None,
        deafen: bool | None = None,
    ) -> None:
        session = self.sessions.get(root_channel_id)
        if session is None:
            raise ValueError("セッションが見つかりません。")
        guild = self._resolve_guild(session.guild_id)
        if guild is None:
            raise ValueError("ギルドが見つかりません。")
        member = guild.get_member(target_user_id)
        if member is None:
            raise ValueError("対象ユーザーが見つかりません。")
        if mute is not None:
            await member.edit(mute=mute, reason="Web管理画面からのサーバーミュート変更")
        if deafen is not None:
            await member.edit(deafen=deafen, reason="Web管理画面からのサーバーデフェン変更")
        await self._persist_and_broadcast(session)
        await self._record_timeline_event(
            session,
            "member_mute_changed",
            f"{member.display_name} server voice state changed.",
            user_id=target_user_id,
            user_name=member.display_name,
            payload={"mute": mute, "deafen": deafen},
        )
        await self._publish_session_event(
            session,
            "member_mute_changed",
            {"user_id": str(target_user_id), "mute": mute, "deafen": deafen},
        )

    def list_sessions(self) -> list[LiveSession]:
        return list(self.sessions.values())

    async def list_accessible_sessions(self, user_id: int, admin_only: bool = False) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for session in self.sessions.values():
            is_admin = await self.is_guild_admin(session.guild_id, user_id)
            if admin_only and not is_admin:
                continue
            if admin_only or await self.can_view_session(session, user_id):
                payload = session.to_payload()
                payload["can_edit"] = await self.can_edit_session(session, user_id)
                result.append(payload)
        result.sort(key=lambda item: item["started_at"], reverse=True)
        return result

    async def update_presence(self) -> None:
        if self.bot is None or self.bot.user is None:
            return
        count = sum(1 for session in self.sessions.values() for participant in session.active_participants())
        name = "通話はされていません。" if count == 0 else f"{count}人が通話中"
        try:
            await self.bot.change_presence(activity=discord.CustomActivity(name=name))
        except discord.HTTPException:
            self.logger.exception("プレゼンス更新に失敗しました")

    async def _ensure_team_channel(
        self,
        root_channel: discord.VoiceChannel,
        session: LiveSession,
        team_name: str,
    ) -> discord.VoiceChannel | None:
        existing_id = session.team_channels.get(team_name)
        if existing_id:
            existing = self._resolve_voice_channel(existing_id)
            if existing is not None:
                await self._apply_access_overwrites(session)
                return existing
        target_name = f"{root_channel.name}-{team_name}"
        for channel in root_channel.category.voice_channels if root_channel.category else []:
            if channel.name == target_name:
                session.team_channels[team_name] = channel.id
                self.channel_to_root[channel.id] = session.root_channel_id
                await self._apply_access_overwrites(session)
                return channel
        try:
            created = await root_channel.guild.create_voice_channel(
                target_name,
                category=root_channel.category,
                reason="チームVCの自動作成",
            )
        except discord.Forbidden:
            self.logger.exception("チームVCの作成権限がありません")
            return None
        except discord.HTTPException:
            self.logger.exception("チームVCの作成に失敗しました")
            return None
        session.team_channels[team_name] = created.id
        self.channel_to_root[created.id] = session.root_channel_id
        await self._apply_access_overwrites(session)
        return created

    def _solo_cleanup_mode(self, config: GuildConfig) -> str:
        if config.solo_cleanup_mode in {"disabled", "notify_only", "delete_warning", "repeat_notice"}:
            return config.solo_cleanup_mode
        return "notify_only"

    def _channel_name_matches_personal_session(self, session: LiveSession, channel: discord.VoiceChannel) -> bool:
        return channel.name == f"{session.starter_user_name}のVC" or channel.name == f"{session.owner_user_name}のVC"

    def _get_solo_cleanup_member(self, session: LiveSession) -> discord.Member | None:
        root_channel = self._resolve_voice_channel(session.root_channel_id)
        if root_channel is None or not self._is_managed_voice_channel(root_channel, include_base=False):
            return None
        if (
            root_channel.id not in self.auto_personal_root_channels
            and not self._channel_name_matches_personal_session(session, root_channel)
        ):
            return None
        all_members: list[discord.Member] = [member for member in root_channel.members if not member.bot]
        for channel_id in session.team_channels.values():
            team_channel = self._resolve_voice_channel(channel_id)
            if team_channel is not None:
                all_members.extend(member for member in team_channel.members if not member.bot)
        if len(all_members) != 1:
            return None
        member = all_members[0]
        if member.voice is None or member.voice.channel is None or member.voice.channel.id != root_channel.id:
            return None
        return member

    async def _refresh_solo_cleanup_for_session(self, session: LiveSession) -> None:
        config = self.guild_configs.get(session.guild_id)
        if config is None:
            config = await self.get_guild_config(session.guild_id)
        if config is None or self._solo_cleanup_mode(config) == "disabled":
            self._cancel_solo_cleanup_by_channel_id(session.root_channel_id)
            return
        member = self._get_solo_cleanup_member(session)
        if member is None:
            self._cancel_solo_cleanup_by_channel_id(session.root_channel_id)
            return
        if session.root_channel_id in self.solo_cleanup_tasks:
            return
        self._schedule_solo_cleanup(session, config)

    def _schedule_solo_cleanup(self, session: LiveSession, config: GuildConfig) -> None:
        root_channel_id = session.root_channel_id
        mode = self._solo_cleanup_mode(config)
        notice_after = max(60, int(config.solo_notice_after_sec))
        warning_after = max(60, int(config.solo_delete_warning_after_sec))
        repeat_after = max(300, int(config.solo_repeat_notice_sec))
        session_key = session.session_key

        async def runner() -> None:
            handle = self.solo_cleanup_tasks[root_channel_id]
            try:
                await asyncio.sleep(notice_after)
                current = self.sessions_by_key.get(session_key)
                if current is None:
                    return
                member = self._get_solo_cleanup_member(current)
                if member is None:
                    return
                handle.notice_sent = True
                await self._send_solo_cleanup_notice(current, member, warning=False)
                if mode == "delete_warning":
                    await asyncio.sleep(warning_after)
                    current = self.sessions_by_key.get(session_key)
                    if current is None:
                        return
                    member = self._get_solo_cleanup_member(current)
                    if member is None:
                        return
                    handle.warning_sent = True
                    await self._send_solo_cleanup_notice(current, member, warning=True)
                    await asyncio.sleep(warning_after)
                    current = self.sessions_by_key.get(session_key)
                    if current is None:
                        return
                    member = self._get_solo_cleanup_member(current)
                    if member is None:
                        return
                    channel = self._resolve_voice_channel(current.root_channel_id)
                    if channel is None:
                        return
                    await self._end_session(current)
                    try:
                        await channel.delete(reason="ソロVCの自動削除")
                    except discord.Forbidden:
                        self.logger.info("ソロVC自動削除: 権限不足のためスキップ: channel=%s", channel.id)
                    except discord.HTTPException:
                        self.logger.exception("ソロVC自動削除に失敗しました: channel=%s", channel.id)
                    return
                if mode == "repeat_notice":
                    while True:
                        await asyncio.sleep(repeat_after)
                        current = self.sessions_by_key.get(session_key)
                        if current is None:
                            return
                        member = self._get_solo_cleanup_member(current)
                        if member is None:
                            return
                        await self._send_solo_cleanup_notice(current, member, warning=False)
            except asyncio.CancelledError:
                raise
            except Exception:
                self.logger.exception("solo VC cleanup task failed: session_key=%s", session_key)
            finally:
                self.solo_cleanup_tasks.pop(root_channel_id, None)

        self.solo_cleanup_tasks[root_channel_id] = SoloCleanupHandle(task=asyncio.create_task(runner()))

    async def _send_solo_cleanup_notice(
        self,
        session: LiveSession,
        member: discord.Member,
        *,
        warning: bool,
    ) -> None:
        channel = self._resolve_voice_channel(session.root_channel_id)
        if channel is None:
            return
        config = self.guild_configs.get(session.guild_id)
        locale = config.guild_language if config else None
        title_key = "embed.solo_warning.title" if warning else "embed.solo_notice.title"
        description = t("embed.solo_notice.description", locale, mention=member.mention, channel=channel.name)
        if warning:
            description += t("embed.solo_warning.suffix", locale)
        embed = discord.Embed(title=t(title_key, locale), description=description, color=COLOR_ERROR if warning else COLOR_WARNING)
        await self._send_embed(channel, embed)
        await self._send_solo_cleanup_dm(session, embed)

    async def _send_solo_cleanup_dm(self, session: LiveSession, embed: discord.Embed) -> None:
        if self.bot is None:
            return
        user: discord.User | discord.Member | None = self.bot.get_user(session.starter_user_id)
        if user is None:
            guild = self._resolve_guild(session.guild_id)
            user = guild.get_member(session.starter_user_id) if guild is not None else None
        if user is None:
            try:
                user = await self.bot.fetch_user(session.starter_user_id)
            except (discord.Forbidden, discord.HTTPException, discord.NotFound):
                return
        try:
            await user.send(embed=embed)
        except (discord.Forbidden, discord.HTTPException):
            self.logger.info("solo VC cleanup DM failed: guild=%s user=%s", session.guild_id, session.starter_user_id)

    def _cancel_solo_cleanup_by_channel_id(self, channel_id: int) -> None:
        handle = self.solo_cleanup_tasks.pop(channel_id, None)
        if handle is not None:
            handle.task.cancel()

    async def _is_active_temporary_event_channel(self, channel_id: int) -> bool:
        try:
            active_items = await self.config_repo.list_active_scheduled_vcs()
        except Exception:
            self.logger.exception("active scheduled VC lookup failed: channel_id=%s", channel_id)
            return False
        return any(item.created_channel_id == channel_id for item in active_items)

    async def _schedule_empty_cleanup(self, channel: discord.VoiceChannel) -> None:
        if channel.id in self.deletion_tasks:
            return
        if not self._is_managed_voice_channel(channel, include_base=False):
            return
        if await self._is_active_temporary_event_channel(channel.id):
            return
        config = await self.get_guild_config(channel.guild.id)
        if config is None:
            return

        async def runner() -> None:
            handle = self.deletion_tasks[channel.id]
            try:
                await asyncio.sleep(config.first_empty_notice_sec)
                refreshed = self._resolve_voice_channel(channel.id)
                if refreshed is None or refreshed.members:
                    return
                handle.notice_sent = True
                await self._send_embed(
                    refreshed,
                    build_embed(
                        config.guild_language,
                        "embed.delete_notice.title",
                        "embed.delete_notice.description",
                        color=COLOR_WARNING,
                        description_fmt={"seconds": config.final_delete_sec},
                    ),
                )
                await asyncio.sleep(max(0, config.final_delete_sec - config.first_empty_notice_sec))
                refreshed = self._resolve_voice_channel(channel.id)
                if refreshed is None or refreshed.members:
                    return
                root_id = self.channel_to_root.get(channel.id)
                if root_id and root_id in self.sessions and channel.id != root_id:
                    session = self.sessions[root_id]
                    for team_name, team_channel_id in list(session.team_channels.items()):
                        if team_channel_id == channel.id:
                            session.team_channels.pop(team_name, None)
                            break
                    self.channel_to_root.pop(channel.id, None)
                    await self._persist_and_broadcast(session)
                await refreshed.delete(reason="空室VCの自動削除")
            except asyncio.CancelledError:
                raise
            except discord.Forbidden:
                self.logger.exception("VC削除権限がありません")
            except discord.HTTPException:
                self.logger.exception("VC削除に失敗しました")
            finally:
                self.deletion_tasks.pop(channel.id, None)

        self.deletion_tasks[channel.id] = DeletionHandle(task=asyncio.create_task(runner()))

    async def _cancel_empty_cleanup(self, channel: discord.VoiceChannel) -> None:
        handle = self.deletion_tasks.pop(channel.id, None)
        if handle is None:
            return
        handle.task.cancel()
        if handle.notice_sent:
            config = self.guild_configs.get(channel.guild.id)
            await self._send_embed(
                channel,
                build_embed(
                    config.guild_language if config else None,
                    "embed.delete_cancelled.title",
                    "embed.delete_cancelled.description",
                    color=COLOR_SUCCESS,
                ),
            )

    def _mark_system_move(
        self,
        user_id: int,
        source_channel_id: int | None,
        target_channel_id: int | None,
        reason: str,
    ) -> None:
        self.system_move_markers.append(
            SystemMoveMarker(
                user_id=user_id,
                source_channel_id=source_channel_id,
                target_channel_id=target_channel_id,
                reason=reason,
                created_at=utcnow(),
            )
        )

    def _consume_system_move(
        self,
        user_id: int,
        source_channel_id: int | None,
        target_channel_id: int | None,
    ) -> bool:
        threshold = utcnow() - timedelta(seconds=15)
        remaining: list[SystemMoveMarker] = []
        matched = False
        for marker in self.system_move_markers:
            if marker.created_at < threshold:
                continue
            if (
                marker.user_id == user_id
                and marker.source_channel_id == source_channel_id
                and marker.target_channel_id == target_channel_id
            ):
                matched = True
                continue
            remaining.append(marker)
        self.system_move_markers = remaining
        return matched

    async def _persist_and_broadcast(self, session: LiveSession) -> None:
        try:
            await self.config_repo.save_session_snapshot(session.to_snapshot())
        except Exception:
            self.logger.exception("セッションスナップショット保存に失敗しました: session_key=%s", session.session_key)
        payload = session.to_payload()
        await self.websocket_hub.broadcast(f"session:{session.root_channel_id}", "session_update", payload)
        await self.websocket_hub.broadcast(f"guild:{session.guild_id}", "session_update", payload)
        await self.websocket_hub.broadcast(f"user:{session.owner_user_id}", "session_update", payload)
        for participant in session.participants.values():
            await self.websocket_hub.broadcast(f"user:{participant.user_id}", "session_update", payload)
        await self._broadcast_global_state()
        await self._refresh_solo_cleanup_for_session(session)

    async def _broadcast_global_state(self) -> None:
        payload = {"active_sessions": [session.to_payload() for session in self.sessions.values()]}
        await self.websocket_hub.broadcast("global", "global_state", payload)

    async def _timeline_retention_days(self) -> int:
        raw = await self.config_repo.get_app_setting("timeline_retention_days", "90")
        try:
            return max(1, int(raw or "90"))
        except ValueError:
            return 90

    async def _record_timeline_event(
        self,
        session: LiveSession,
        event_type: str,
        message: str,
        *,
        user_id: int | None = None,
        user_name: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        locale = self.guild_configs.get(session.guild_id).guild_language if self.guild_configs.get(session.guild_id) else None
        try:
            event = await self.stats_repo.record_timeline_event(
                session_id=session.session_id,
                guild_id=str(session.guild_id),
                guild_name=session.guild_name,
                root_channel_id=str(session.root_channel_id),
                root_channel_name=session.root_channel_name,
                event_type=event_type,
                event_label=_timeline_label(event_type, locale),
                user_id=str(user_id) if user_id is not None else None,
                user_name=user_name,
                message=message,
                payload=payload or {},
                retention_days=await self._timeline_retention_days(),
            )
        except Exception:
            self.logger.exception("タイムライン保存に失敗しました: session_key=%s event_type=%s", session.session_key, event_type)
            return

        envelope = {
            "type": event_type,
            "guild_id": str(session.guild_id),
            "root_channel_id": str(session.root_channel_id),
            "event": event,
        }
        for scope in {f"session:{session.root_channel_id}", f"guild:{session.guild_id}", "global"}:
            await self.websocket_hub.broadcast(scope, "timeline_event", envelope)

    async def _publish_session_event(
        self,
        session: LiveSession,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        envelope = {
            "type": event_type,
            "guild_id": str(session.guild_id),
            "root_channel_id": str(session.root_channel_id),
            "session": session.to_payload(),
            "payload": payload or {},
        }
        scopes = {f"session:{session.root_channel_id}", f"guild:{session.guild_id}", "global"}
        scopes.add(f"user:{session.owner_user_id}")
        for participant in session.participants.values():
            scopes.add(f"user:{participant.user_id}")
        for scope in scopes:
            await self.websocket_hub.broadcast(scope, "session_event", envelope)

    async def _publish_important_event(
        self,
        event_type: str,
        title: str,
        message: str,
        session: LiveSession,
        *,
        extra_payload: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "session": session.to_payload(),
            **(extra_payload or {}),
        }
        try:
            notification = await self.config_repo.create_notification(
                event_type=event_type,
                title=title,
                message=message,
                guild_id=session.guild_id,
                root_channel_id=session.root_channel_id,
                payload=payload,
            )
        except Exception:
            self.logger.exception("通知センター保存に失敗しました: session_key=%s event_type=%s", session.session_key, event_type)
            notification = {
                "id": "",
                "created_at": utcnow().isoformat(),
                "event_type": event_type,
                "title": title,
                "message": message,
                "guild_id": str(session.guild_id),
                "root_channel_id": str(session.root_channel_id),
                "recipient_user_id": None,
                "payload": payload,
                "read_at": None,
            }
        envelope = {"type": event_type, "notification": notification, "payload": payload}
        for scope in {f"session:{session.root_channel_id}", f"guild:{session.guild_id}", "global"}:
            await self.websocket_hub.broadcast(scope, "important_notification", envelope)

    def _register_session(self, session: LiveSession) -> None:
        self.sessions[session.root_channel_id] = session
        self.sessions_by_key[session.session_key] = session
        self.channel_to_root[session.root_channel_id] = session.root_channel_id
        for channel_id in session.team_channels.values():
            self.channel_to_root[channel_id] = session.root_channel_id

    def _unregister_session(self, session: LiveSession) -> None:
        self._cancel_solo_cleanup_by_channel_id(session.root_channel_id)
        self.auto_personal_root_channels.discard(session.root_channel_id)
        self.sessions.pop(session.root_channel_id, None)
        self.sessions_by_key.pop(session.session_key, None)
        self.channel_to_root.pop(session.root_channel_id, None)
        for channel_id in session.team_channels.values():
            self.channel_to_root.pop(channel_id, None)

    def _is_managed_voice_channel(self, channel: discord.VoiceChannel, include_base: bool) -> bool:
        config = self.guild_configs.get(channel.guild.id)
        if config is None or not config.enabled or config.managed_category_id is None:
            return False
        if channel.category_id != config.managed_category_id:
            return False
        if not include_base and config.base_voice_channel_id and channel.id == config.base_voice_channel_id:
            return False
        return True

    async def _send_embed(
        self,
        channel: discord.abc.Messageable | None,
        embed: discord.Embed,
        view: discord.ui.View | None = None,
    ) -> discord.Message | None:
        if channel is None:
            return None
        try:
            return await channel.send(embed=embed, view=view)
        except discord.Forbidden:
            self.logger.exception("通知送信権限がありません")
            await self._send_fallback_notification(channel, embed, view=view)
        except discord.HTTPException:
            self.logger.exception("通知送信に失敗しました")
            await self._send_fallback_notification(channel, embed, view=view)
        return None

    async def _send_fallback_notification(
        self,
        channel: discord.abc.Messageable,
        embed: discord.Embed,
        view: discord.ui.View | None = None,
    ) -> None:
        guild = getattr(channel, "guild", None)
        if guild is None:
            return
        config = self.guild_configs.get(guild.id)
        if config is None or config.notification_channel_id is None:
            return
        fallback = await self._resolve_notice_channel(guild.id, config.notification_channel_id)
        if fallback is None:
            return
        channel_id = int(getattr(fallback, "id", 0) or 0)
        print(f"[NOTICE] send to {channel_id} / {fallback}")
        try:
            await fallback.send(embed=embed, view=view)
        except Exception as exc:
            print(f"[NOTICE ERROR] {exc}")
            self.logger.exception("フォールバック通知にも失敗しました")

    def _resolve_voice_channel(self, channel_id: int) -> discord.VoiceChannel | None:
        if self.bot is None:
            return None
        channel = self.bot.get_channel(channel_id)
        if isinstance(channel, discord.VoiceChannel):
            return channel
        return None

    def resolve_voice_channel(self, channel_id: int) -> discord.VoiceChannel | None:
        return self._resolve_voice_channel(channel_id)

    def _resolve_guild(self, guild_id: int) -> discord.Guild | None:
        if self.bot is None:
            return None
        return self.bot.get_guild(guild_id)
