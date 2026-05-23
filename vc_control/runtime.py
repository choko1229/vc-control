from __future__ import annotations

import asyncio
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import discord
from fastapi import WebSocket

from vc_control.models import DEFAULT_TEAM_NAMES, CompletedMember, CompletedSession, GuildConfig, SessionSnapshot, SnapshotMember
from vc_control.repositories import ConfigRepository, StatsRepository
from vc_control.utils import format_duration, make_session_key, normalize_ids, utcnow


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
        self.system_move_markers: list[SystemMoveMarker] = []

    def bind_bot(self, bot: discord.Client) -> None:
        self.bot = bot

    async def refresh_guild_configs(self) -> None:
        configs = await self.config_repo.list_guild_configs()
        self.guild_configs = {config.guild_id: config for config in configs}

    async def sync_guild_catalog(self) -> None:
        if self.bot is None:
            return
        guilds = [(guild.id, guild.name) for guild in self.bot.guilds]
        await self.config_repo.sync_guild_catalog(guilds)
        await self.refresh_guild_configs()

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
            self._register_session(session)
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
                await self._start_session(channel, members[0], members)
        await self.update_presence()

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
        await self._persist_and_broadcast(session)
        await self._publish_important_event(
            "vc_started",
            "VC開始",
            f"{session.root_channel_name} が開始されました。",
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
                return channel
        try:
            created = await guild.create_voice_channel(
                target_name,
                category=category,
                reason="個人VCの自動作成",
            )
            self.logger.info("個人VCを作成しました: guild=%s channel=%s", guild.name, created.name)
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
    ) -> discord.Embed:
        embed = discord.Embed(
            title="VC開始",
            description=f"**{session.root_channel_name}** のセッションを開始しました。",
            color=discord.Color.green(),
        )
        embed.add_field(name="VC名", value=session.root_channel_name, inline=False)
        embed.add_field(name="開始時刻", value=self._format_discord_timestamp(session.started_at), inline=True)
        embed.add_field(name="参加者", value=starter.mention, inline=True)
        embed.add_field(name="VC管理", value=management_url or "未設定", inline=False)
        return embed

    def _build_management_panel_embed(self, session: LiveSession, management_url: str | None) -> discord.Embed:
        embed = discord.Embed(
            title="VC管理パネル",
            description="チーム操作はこのメッセージか `/team` から実行できます。",
            color=discord.Color.blue(),
        )
        embed.add_field(name="VC名", value=session.root_channel_name, inline=False)
        embed.add_field(name="現在の管理者", value=f"<@{session.owner_user_id}>", inline=True)
        embed.add_field(name="チーム", value=", ".join(session.team_names), inline=True)
        embed.add_field(name="VC管理", value=management_url or "未設定", inline=False)
        return embed

    def _build_end_embed(self, session: LiveSession, completed: CompletedSession) -> discord.Embed:
        session_seconds = max(0, int((completed.ended_at - completed.started_at).total_seconds()))
        member_lines = [
            f"- {member.user_name}: {format_duration(member.talk_seconds)}"
            for member in sorted(completed.members, key=lambda item: item.talk_seconds, reverse=True)
        ]
        embed = discord.Embed(
            title="VC終了",
            description=f"**{session.root_channel_name}** のセッションを終了しました。",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="VC", value=session.root_channel_name, inline=False)
        embed.add_field(name="開始", value=self._format_discord_timestamp(completed.started_at), inline=True)
        embed.add_field(name="終了", value=self._format_discord_timestamp(completed.ended_at), inline=True)
        embed.add_field(name="時間", value=format_duration(session_seconds), inline=True)
        embed.add_field(name="参加ユーザー一覧", value="\n".join(member_lines) if member_lines else "参加者なし", inline=False)
        embed.add_field(name="VC全体の利用時間", value=format_duration(completed.total_talk_seconds), inline=False)
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
        start_embed = self._build_start_embed(session, starter, management_url)
        start_view = self._build_management_link_view(management_url)
        await self._send_embed(channel, start_embed, view=start_view)
        from vc_control.team_ui import TeamPanelView

        await self._send_embed(
            channel,
            self._build_management_panel_embed(session, management_url),
            view=TeamPanelView(self, session.root_channel_id, management_url=management_url),
        )
        await self._send_notification_message(session, start_embed, view=start_view)
        if not suppressed:
            await self._send_embed(
                channel,
                discord.Embed(
                    title="入室通知",
                    description=f"{starter.mention} が通話に参加しました。",
                    color=discord.Color.green(),
                ),
            )
        await self._persist_and_broadcast(session)
        await self._publish_important_event(
            "vc_started",
            "VC開始",
            f"{session.root_channel_name} が開始されました。",
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
            await self._send_embed(
                channel,
                discord.Embed(
                    title="入室通知",
                    description=f"{member.mention} が通話に参加しました。",
                    color=discord.Color.green(),
                ),
            )
        await self._persist_and_broadcast(session)
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

        if not suppressed:
            await self._send_embed(
                channel,
                discord.Embed(
                    title="退出通知",
                    description=f"{member.mention} が通話から退出しました。",
                    color=discord.Color.red(),
                ),
            )

        active_users = session.active_participants()
        if session.owner_user_id == member.id and active_users:
            next_owner = active_users[0]
            session.owner_user_id = next_owner.user_id
            session.owner_user_name = next_owner.user_name
            await self._send_embed(
                self._resolve_voice_channel(session.root_channel_id),
                discord.Embed(
                    title="セッション管理者変更",
                    description=f"現在の管理者が退出したため、管理者を <@{next_owner.user_id}> に移譲しました。",
                    color=discord.Color.orange(),
                ),
            )

        if not session.active_participants():
            await self._end_session(session)
            return

        await self._persist_and_broadcast(session)
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
            leave_embed = discord.Embed(
                title="移動通知",
                description=f"{member.mention} が **{before_channel.name}** から移動しました。",
                color=discord.Color.red(),
            )
            join_embed = discord.Embed(
                title="移動通知",
                description=f"{member.mention} が **{after_channel.name}** に参加しました。",
                color=discord.Color.green(),
            )
            await self._send_embed(before_channel, leave_embed)
            await self._send_embed(after_channel, join_embed)
        await self._persist_and_broadcast(session)
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
        end_embed = self._build_end_embed(session, completed)
        await self._send_notification_message(session, end_embed)
        await self._publish_important_event(
            "vc_ended",
            "VC終了",
            f"{session.root_channel_name} が終了しました。",
            session,
            extra_payload={"total_talk_seconds": total_talk, "total_afk_seconds": total_afk},
        )
        summary_lines = [
            f"開始者: <@{session.starter_user_id}>",
            f"参加者数: {len(session.participants)}人",
            f"累計通話時間: {format_duration(total_talk)}",
            f"累計AFK時間: {format_duration(total_afk)}",
        ]
        await self._send_embed(
            self._resolve_voice_channel(session.root_channel_id),
            discord.Embed(
                title="VCセッション終了",
                description="\n".join(summary_lines),
                color=discord.Color.blurple(),
            ),
        )
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
        if message.mention_everyone:
            await self._send_embed(
                message.channel,
                discord.Embed(
                    title="警告",
                    description="@everyone / @here のDM転送は行いません。",
                    color=discord.Color.red(),
                ),
            )
            return
        for user in message.mentions:
            if user.bot:
                continue
            try:
                await user.send(
                    embed=discord.Embed(
                        title="VCメンション通知",
                        description=f"{message.author.mention} さんから {message.channel.mention} でメンションされました。\n\n{message.content}",
                        color=discord.Color.blue(),
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
        if session.panel_creator_id == user_id:
            return True
        participant = session.participants.get(user_id)
        return participant is not None and participant.current_channel_id is not None

    async def can_edit_session(self, session: LiveSession, user_id: int) -> bool:
        if session.starter_user_id == user_id:
            return True
        return await self.is_guild_admin(session.guild_id, user_id)

    async def can_assign_others(self, session: LiveSession, user_id: int) -> bool:
        if session.starter_user_id == user_id:
            return True
        if session.panel_creator_id == user_id:
            return True
        return await self.is_guild_admin(session.guild_id, user_id)

    async def can_execute_team_actions(self, session: LiveSession, user_id: int) -> bool:
        if session.starter_user_id == user_id:
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
            raise ValueError("セッションが見つかりません。")
        participant = session.participants.get(target_user_id)
        if participant is None:
            raise ValueError("対象ユーザーが見つかりません。")
        if target_user_id != actor_id and not await self.can_assign_others(session, actor_id):
            raise PermissionError("他ユーザーのチーム変更権限がありません。")
        if team_name and team_name not in session.team_names:
            raise ValueError("存在しないチームです。")
        participant.current_team = team_name
        if team_name is None:
            session.team_assignments.pop(target_user_id, None)
        else:
            session.team_assignments[target_user_id] = team_name
        await self._persist_and_broadcast(session)
        await self._publish_session_event(
            session,
            "team_changed",
            {"user_id": str(target_user_id), "team_name": team_name},
        )
        return f"<@{target_user_id}> を {team_name or '未所属'} に設定しました。"

    async def update_team_settings(
        self,
        root_channel_id: int,
        actor_id: int,
        team_names: list[str],
        team_mode: str,
    ) -> None:
        session = self.sessions.get(root_channel_id)
        if session is None:
            raise ValueError("セッションが見つかりません。")
        if not await self.can_assign_others(session, actor_id):
            raise PermissionError("チーム設定の変更権限がありません。")
        normalized = [name.strip() for name in team_names if name.strip()]
        if not normalized:
            raise ValueError("少なくとも1つのチーム名が必要です。")
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
            raise ValueError("セッションが見つかりません。")
        if not await self.can_execute_team_actions(session, actor_id):
            raise PermissionError("分割権限がありません。")
        guild = self._resolve_guild(session.guild_id)
        root_channel = self._resolve_voice_channel(session.root_channel_id)
        if guild is None or root_channel is None:
            raise ValueError("Discord上のチャンネルを解決できません。")
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
                    discord.Embed(
                        title="チーム移動",
                        description=f"{names} を **{team_name}** へ移動しました。",
                        color=discord.Color.blue(),
                    ),
                )
            if moved_messages:
                await self._send_embed(
                    root_channel,
                    discord.Embed(
                        title="チーム分割完了",
                        description="\n".join(moved_messages),
                        color=discord.Color.blue(),
                    ),
                )
            await self._persist_and_broadcast(session)
            await self._publish_session_event(session, "teams_split", {"messages": moved_messages})
        return moved_messages

    async def assemble_teams(self, root_channel_id: int, actor_id: int) -> list[str]:
        session = self.sessions.get(root_channel_id)
        if session is None:
            raise ValueError("セッションが見つかりません。")
        if not await self.can_execute_team_actions(session, actor_id):
            raise PermissionError("集合権限がありません。")
        guild = self._resolve_guild(session.guild_id)
        root_channel = self._resolve_voice_channel(session.root_channel_id)
        if guild is None or root_channel is None:
            raise ValueError("Discord上のチャンネルを解決できません。")
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
                    discord.Embed(
                        title="集合完了",
                        description=f"{', '.join(moved_users)} をメインVCへ戻しました。",
                        color=discord.Color.gold(),
                    ),
                )
            await self._persist_and_broadcast(session)
            await self._publish_session_event(session, "teams_assembled", {"users": moved_users})
        return moved_users

    async def recall_member(self, root_channel_id: int, actor_id: int, target_user_id: int) -> str:
        session = self.sessions.get(root_channel_id)
        if session is None:
            raise ValueError("セッションが見つかりません。")
        if not await self.can_execute_team_actions(session, actor_id):
            raise PermissionError("呼び戻し権限がありません。")
        guild = self._resolve_guild(session.guild_id)
        root_channel = self._resolve_voice_channel(session.root_channel_id)
        if guild is None or root_channel is None:
            raise ValueError("Discord上のチャンネルを解決できません。")
        participant = session.participants.get(target_user_id)
        member = guild.get_member(target_user_id) if guild else None
        if participant is None or member is None or member.voice is None or member.voice.channel is None:
            raise ValueError("対象ユーザーが現在通話にいません。")
        self._mark_system_move(participant.user_id, member.voice.channel.id, root_channel.id, "team_recall")
        try:
            await member.move_to(root_channel, reason="個別呼び戻し")
        except discord.Forbidden as exc:
            raise PermissionError("呼び戻し権限がありません。") from exc
        except discord.HTTPException as exc:
            raise ValueError("呼び戻しに失敗しました。") from exc
        message = f"<@{target_user_id}> をメインVCへ呼び戻しました。"
        await self._send_embed(
            root_channel,
            discord.Embed(title="呼び戻し", description=message, color=discord.Color.gold()),
        )
        await self._persist_and_broadcast(session)
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
            await member.edit(deafen=deafen, reason="Web管理画面からのサーバーデafen変更")
        await self._persist_and_broadcast(session)
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
                return existing
        target_name = f"{root_channel.name}-{team_name}"
        for channel in root_channel.category.voice_channels if root_channel.category else []:
            if channel.name == target_name:
                session.team_channels[team_name] = channel.id
                self.channel_to_root[channel.id] = session.root_channel_id
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
        return created

    async def _schedule_empty_cleanup(self, channel: discord.VoiceChannel) -> None:
        if channel.id in self.deletion_tasks:
            return
        if not self._is_managed_voice_channel(channel, include_base=False):
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
                    discord.Embed(
                        title="削除予告",
                        description=f"{config.final_delete_sec}秒後まで空室ならVCを削除します。",
                        color=discord.Color.orange(),
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
            await self._send_embed(
                channel,
                discord.Embed(
                    title="削除キャンセル",
                    description="再入室を検知したため、自動削除をキャンセルしました。",
                    color=discord.Color.green(),
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

    async def _broadcast_global_state(self) -> None:
        payload = {"active_sessions": [session.to_payload() for session in self.sessions.values()]}
        await self.websocket_hub.broadcast("global", "global_state", payload)

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
