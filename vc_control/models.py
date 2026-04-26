from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from vc_control.utils import from_iso, json_loads, to_iso


DEFAULT_TEAM_NAMES = ["A", "B", "C", "D"]


@dataclass(slots=True)
class SetupPayload:
    setup_password: str
    bot_token: str
    client_id: str
    client_secret: str
    redirect_uri: str
    base_url: str
    owner_user_id: int
    dashboard_host: str
    dashboard_port: int


@dataclass(slots=True)
class GuildConfig:
    guild_id: int
    guild_name: str
    managed_category_id: int | None = None
    base_voice_channel_id: int | None = None
    notification_channel_id: int | None = None
    first_empty_notice_sec: int = 30
    final_delete_sec: int = 90
    team_mode: str = "custom"
    team_names: list[str] = field(default_factory=lambda: DEFAULT_TEAM_NAMES.copy())
    enabled: bool = False
    updated_at: datetime | None = None

    def to_record(self) -> dict[str, Any]:
        return {
            "guild_id": self.guild_id,
            "guild_name": self.guild_name,
            "managed_category_id": self.managed_category_id,
            "base_voice_channel_id": self.base_voice_channel_id,
            "notification_channel_id": self.notification_channel_id,
            "first_empty_notice_sec": self.first_empty_notice_sec,
            "final_delete_sec": self.final_delete_sec,
            "team_mode": self.team_mode,
            "team_names_json": self.team_names,
            "enabled": int(self.enabled),
            "updated_at": to_iso(self.updated_at),
        }

    @classmethod
    def from_record(cls, row: dict[str, Any]) -> "GuildConfig":
        return cls(
            guild_id=int(row["guild_id"]),
            guild_name=str(row["guild_name"]),
            managed_category_id=row["managed_category_id"],
            base_voice_channel_id=row["base_voice_channel_id"],
            notification_channel_id=row["notification_channel_id"],
            first_empty_notice_sec=int(row["first_empty_notice_sec"]),
            final_delete_sec=int(row["final_delete_sec"]),
            team_mode=str(row["team_mode"]),
            team_names=list(json_loads(row["team_names_json"], DEFAULT_TEAM_NAMES)),
            enabled=bool(row["enabled"]),
            updated_at=from_iso(row["updated_at"]),
        )


@dataclass(slots=True)
class OAuthProfile:
    user_id: int
    username: str
    global_name: str | None
    avatar_url: str | None
    guilds: list[dict[str, Any]] = field(default_factory=list)

    @property
    def display_name(self) -> str:
        return self.global_name or self.username

    def to_session(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_session(cls, data: dict[str, Any]) -> "OAuthProfile":
        return cls(
            user_id=int(data["user_id"]),
            username=str(data["username"]),
            global_name=data.get("global_name"),
            avatar_url=data.get("avatar_url"),
            guilds=list(data.get("guilds", [])),
        )


@dataclass(slots=True)
class CompletedMember:
    user_id: int
    user_name: str
    joined_at: datetime
    left_at: datetime
    talk_seconds: int
    afk_seconds: int
    afk_channel_seconds: int
    self_mute_seconds: int
    self_deafen_seconds: int
    is_owner: bool

    def to_record(self, session_id: str, guild_id: int, guild_name: str) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "guild_id": guild_id,
            "guild_name": guild_name,
            "user_id": self.user_id,
            "user_name": self.user_name,
            "joined_at": to_iso(self.joined_at),
            "left_at": to_iso(self.left_at),
            "talk_seconds": self.talk_seconds,
            "afk_seconds": self.afk_seconds,
            "afk_channel_seconds": self.afk_channel_seconds,
            "self_mute_seconds": self.self_mute_seconds,
            "self_deafen_seconds": self.self_deafen_seconds,
            "is_owner": int(self.is_owner),
        }


@dataclass(slots=True)
class CompletedSession:
    session_id: str
    guild_id: int
    guild_name: str
    root_channel_id: int
    root_channel_name: str
    started_by: int
    started_by_name: str
    started_at: datetime
    ended_at: datetime
    total_talk_seconds: int
    total_afk_seconds: int
    members: list[CompletedMember]
    payload: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "guild_id": self.guild_id,
            "guild_name": self.guild_name,
            "root_channel_id": self.root_channel_id,
            "root_channel_name": self.root_channel_name,
            "started_by": self.started_by,
            "started_by_name": self.started_by_name,
            "started_at": to_iso(self.started_at),
            "ended_at": to_iso(self.ended_at),
            "total_talk_seconds": self.total_talk_seconds,
            "total_afk_seconds": self.total_afk_seconds,
            "payload_json": self.payload,
        }


@dataclass(slots=True)
class SnapshotMember:
    user_id: int
    user_name: str
    joined_at: datetime
    last_transition_at: datetime
    current_channel_id: int | None
    talk_seconds: int
    afk_seconds: int
    afk_channel_seconds: int
    self_mute_seconds: int
    self_deafen_seconds: int
    self_muted: bool
    self_deafened: bool
    in_afk_channel: bool
    current_team: str | None
    panel_creator: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["joined_at"] = to_iso(self.joined_at)
        payload["last_transition_at"] = to_iso(self.last_transition_at)
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SnapshotMember":
        return cls(
            user_id=int(payload["user_id"]),
            user_name=str(payload["user_name"]),
            joined_at=from_iso(payload["joined_at"]) or datetime(1970, 1, 1, tzinfo=UTC),
            last_transition_at=from_iso(payload["last_transition_at"]) or datetime(1970, 1, 1, tzinfo=UTC),
            current_channel_id=payload.get("current_channel_id"),
            talk_seconds=int(payload.get("talk_seconds", 0)),
            afk_seconds=int(payload.get("afk_seconds", 0)),
            afk_channel_seconds=int(payload.get("afk_channel_seconds", 0)),
            self_mute_seconds=int(payload.get("self_mute_seconds", 0)),
            self_deafen_seconds=int(payload.get("self_deafen_seconds", 0)),
            self_muted=bool(payload.get("self_muted", False)),
            self_deafened=bool(payload.get("self_deafened", False)),
            in_afk_channel=bool(payload.get("in_afk_channel", False)),
            current_team=payload.get("current_team"),
            panel_creator=bool(payload.get("panel_creator", False)),
        )


@dataclass(slots=True)
class SessionSnapshot:
    session_id: str
    guild_id: int
    root_channel_id: int
    root_channel_name: str
    starter_user_id: int
    starter_user_name: str
    owner_user_id: int
    owner_user_name: str
    started_at: datetime
    panel_creator_id: int | None
    panel_creator_name: str | None
    team_names: list[str]
    team_mode: str
    team_assignments: dict[str, str]
    team_channels: dict[str, int]
    notice_channel_id: int | None
    notice_message_id: int | None
    member_order: list[int]
    members: list[SnapshotMember]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "guild_id": self.guild_id,
            "root_channel_id": self.root_channel_id,
            "root_channel_name": self.root_channel_name,
            "starter_user_id": self.starter_user_id,
            "starter_user_name": self.starter_user_name,
            "owner_user_id": self.owner_user_id,
            "owner_user_name": self.owner_user_name,
            "started_at": to_iso(self.started_at),
            "panel_creator_id": self.panel_creator_id,
            "panel_creator_name": self.panel_creator_name,
            "team_names": self.team_names,
            "team_mode": self.team_mode,
            "team_assignments": self.team_assignments,
            "team_channels": self.team_channels,
            "notice_channel_id": self.notice_channel_id,
            "notice_message_id": self.notice_message_id,
            "member_order": self.member_order,
            "members": [member.to_dict() for member in self.members],
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "SessionSnapshot":
        return cls(
            session_id=str(payload["session_id"]),
            guild_id=int(payload["guild_id"]),
            root_channel_id=int(payload["root_channel_id"]),
            root_channel_name=str(payload["root_channel_name"]),
            starter_user_id=int(payload.get("starter_user_id", payload["owner_user_id"])),
            starter_user_name=str(payload.get("starter_user_name", payload["owner_user_name"])),
            owner_user_id=int(payload["owner_user_id"]),
            owner_user_name=str(payload["owner_user_name"]),
            started_at=from_iso(payload["started_at"]) or datetime(1970, 1, 1, tzinfo=UTC),
            panel_creator_id=payload.get("panel_creator_id"),
            panel_creator_name=payload.get("panel_creator_name"),
            team_names=list(payload.get("team_names", DEFAULT_TEAM_NAMES)),
            team_mode=str(payload.get("team_mode", "custom")),
            team_assignments=dict(payload.get("team_assignments", {})),
            team_channels={str(key): int(value) for key, value in dict(payload.get("team_channels", {})).items()},
            notice_channel_id=int(payload["notice_channel_id"]) if payload.get("notice_channel_id") is not None else None,
            notice_message_id=int(payload["notice_message_id"]) if payload.get("notice_message_id") is not None else None,
            member_order=[int(item) for item in payload.get("member_order", [])],
            members=[SnapshotMember.from_dict(item) for item in payload.get("members", [])],
        )
