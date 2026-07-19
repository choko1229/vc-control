from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

import discord
import httpx
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.templating import Jinja2Templates

from vc_control.bootstrap import AppContainer
from vc_control.models import GuildConfig, OAuthProfile, ScheduledVC, SetupPayload
from vc_control.utils import format_duration, from_iso, make_session_key, normalize_ids, safe_int, utcnow


LOCAL_TZ = ZoneInfo("Asia/Tokyo")


def _default_dashboard_host() -> str:
    return os.getenv("DASHBOARD_HOST", "0.0.0.0").strip() or "0.0.0.0"


def _default_dashboard_port() -> int:
    for env_name in ("SERVER_PORT", "PORT", "DASHBOARD_PORT"):
        value = os.getenv(env_name)
        if not value:
            continue
        try:
            return int(value)
        except ValueError:
            continue
    return 49162


def _validate_templates(template_dir: Path) -> None:
    forbidden_patterns = ("namespace(", "Namespace")
    violations: list[str] = []
    for template_path in sorted(template_dir.glob("*.html")):
        for lineno, line in enumerate(template_path.read_text(encoding="utf-8").splitlines(), start=1):
            for pattern in forbidden_patterns:
                if pattern in line:
                    relative_path = template_path.relative_to(template_dir.parent.parent)
                    violations.append(f"{relative_path}:{lineno}: {pattern}")
    if violations:
        details = "\n".join(violations)
        raise RuntimeError(
            "Jinja2テンプレートに禁止された namespace 利用が残っています。\n"
            "表示ロジックは Python 側で計算し、テンプレートは表示専用にしてください。\n"
            f"{details}"
        )


def _sign_ws_token(secret: str, user_id: int) -> str:
    nonce = secrets.token_hex(8)
    payload = f"{user_id}:{nonce}"
    signature = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return base64.urlsafe_b64encode(f"{payload}:{signature}".encode("utf-8")).decode("utf-8")


def _verify_ws_token(secret: str, token: str) -> int | None:
    try:
        decoded = base64.urlsafe_b64decode(token.encode("utf-8")).decode("utf-8")
        user_id_text, nonce, signature = decoded.split(":")
    except Exception:
        return None
    payload = f"{user_id_text}:{nonce}"
    expected = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        return None
    return safe_int(user_id_text)


def _build_avatar_url(user: dict[str, Any]) -> str | None:
    avatar = user.get("avatar")
    if not avatar:
        return None
    return f"https://cdn.discordapp.com/avatars/{user['id']}/{avatar}.png?size=128"


def _current_profile(request: Request) -> OAuthProfile | None:
    raw = request.session.get("oauth_profile")
    if not isinstance(raw, dict):
        return None
    return OAuthProfile.from_session(raw)


async def _require_profile(request: Request) -> OAuthProfile:
    profile = _current_profile(request)
    if profile is None:
        raise HTTPException(status_code=401, detail="ログインが必要です。")
    return profile


async def _require_admin(request: Request, container: AppContainer) -> OAuthProfile:
    profile = await _require_profile(request)
    settings = await container.config_repo.get_runtime_settings()
    if _owner_user_id(settings) != profile.user_id:
        raise HTTPException(status_code=403, detail="Bot Ownerのみ利用できます。")
    return profile


def _guild_sort_key(item: dict[str, Any]) -> str:
    return str(item.get("name") or item.get("guild_name") or "").lower()


def _asset_url(asset: discord.Asset | None) -> str | None:
    return str(asset.url) if asset is not None else None


def _build_initials(name: str | None) -> str:
    text = (name or "?").strip()
    if not text:
        return "?"
    parts = [part for part in text.replace("_", " ").split() if part]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return text[:2].upper()


def _build_user_badge(display_name: str, avatar_url: str | None = None) -> dict[str, str | None]:
    return {
        "display_name": display_name,
        "avatar_url": avatar_url,
        "initials": _build_initials(display_name),
    }


def _serialize_guild_identity(guild: discord.Guild | None, guild_id: int, guild_name: str) -> dict[str, Any]:
    display_name = guild.name if guild is not None else guild_name
    return {
        "id": str(guild_id),
        "name": display_name,
        "icon_url": _asset_url(guild.icon) if guild is not None else None,
        "initials": _build_initials(display_name),
    }


def _resolve_guild(container: AppContainer, guild_id: int) -> discord.Guild | None:
    if container.bot is None:
        return None
    return container.bot.get_guild(guild_id)


def _resolve_member(container: AppContainer, guild_id: int, user_id: int) -> discord.Member | None:
    guild = _resolve_guild(container, guild_id)
    if guild is None:
        return None
    return guild.get_member(user_id)


def _serialize_user_identity(
    container: AppContainer,
    guild_id: int,
    user_id: int,
    fallback_name: str,
) -> dict[str, Any]:
    member = _resolve_member(container, guild_id, user_id)
    display_name = member.display_name if member is not None else fallback_name
    avatar_url = _asset_url(member.display_avatar) if member is not None else None
    return {
        "id": str(user_id),
        "display_name": display_name,
        "avatar_url": avatar_url,
        "initials": _build_initials(display_name),
        "sub_label": f"ID: {user_id}",
    }


def _serialize_channel_entry(channel: discord.abc.GuildChannel, kind: str, icon: str) -> dict[str, Any]:
    return {
        "id": str(channel.id),
        "name": channel.name,
        "kind": kind,
        "icon": icon,
        "sub_label": f"ID: {channel.id}",
    }


def _serialize_guild_channels(container: AppContainer, guild_id: int) -> dict[str, list[dict[str, Any]]]:
    if container.bot is None:
        return {"categories": [], "voice_channels": [], "text_channels": []}
    guild = container.bot.get_guild(guild_id)
    if guild is None:
        return {"categories": [], "voice_channels": [], "text_channels": []}
    return {
        "categories": [
            _serialize_channel_entry(channel, "カテゴリ", "🗂")
            for channel in sorted(guild.categories, key=lambda item: item.position)
        ],
        "voice_channels": [
            _serialize_channel_entry(channel, "ボイス", "🔊")
            for channel in sorted(guild.voice_channels, key=lambda item: item.position)
        ],
        "text_channels": [
            _serialize_channel_entry(channel, "テキスト", "#")
            for channel in sorted(guild.text_channels, key=lambda item: item.position)
        ],
    }


def _serialize_guild_members(container: AppContainer, guild_id: int) -> list[dict[str, str]]:
    if container.bot is None:
        return []
    guild = container.bot.get_guild(guild_id)
    if guild is None:
        return []
    members = [
        {
            "id": str(member.id),
            "name": member.display_name,
            "username": str(member),
        }
        for member in guild.members
        if not member.bot
    ]
    members.sort(key=lambda item: item["name"].lower())
    return members


def _serialize_guild_roles(container: AppContainer, guild_id: int) -> list[dict[str, str]]:
    if container.bot is None:
        return []
    guild = container.bot.get_guild(guild_id)
    if guild is None:
        return []
    roles = [
        {"id": str(role.id), "name": role.name}
        for role in guild.roles
        if not role.is_default()
    ]
    roles.sort(key=lambda item: item["name"].lower())
    return roles


def _decorate_guild_rows(rows: list[dict[str, Any]], container: AppContainer) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        guild_id = safe_int(row.get("guild_id") or row.get("id"))
        guild_name = str(row.get("guild_name") or row.get("name") or guild_id)
        guild = _resolve_guild(container, guild_id)
        merged = dict(row)
        merged.update(_serialize_guild_identity(guild, guild_id, guild_name))
        result.append(merged)
    return result


def _decorate_bot_guilds(container: AppContainer) -> list[dict[str, Any]]:
    if container.bot is None:
        return []
    rows = [
        {
            "id": guild.id,
            "name": guild.name,
            "icon_url": _asset_url(guild.icon),
            "initials": _build_initials(guild.name),
            "member_count": guild.member_count or 0,
        }
        for guild in container.bot.guilds
    ]
    rows.sort(key=_guild_sort_key)
    return rows


def _build_guild_config_defaults(guild_id: int, guild_name: str, current: GuildConfig | None) -> GuildConfig:
    if current is not None:
        return current
    return GuildConfig(guild_id=guild_id, guild_name=guild_name)


def _normalize_solo_cleanup_mode(value: Any, default: str = "notify_only") -> str:
    mode = str(value or default).strip()
    if mode not in {"disabled", "notify_only", "delete_warning", "repeat_notice"}:
        return default
    return mode


def _normalize_ranking_frequencies(values: list[Any]) -> list[str]:
    allowed = {"daily", "weekly", "monthly", "manual"}
    result = [str(value).strip() for value in values if str(value).strip() in allowed]
    return result


def _list_payload(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None:
        return []
    return [value]


def _normalize_ranking_targets(values: list[Any]) -> list[str]:
    allowed = {"top_talkers", "top_hosts", "team_splits", "night_owls"}
    result = [str(value).strip() for value in values if str(value).strip() in allowed]
    return result or ["top_talkers", "top_hosts", "team_splits", "night_owls"]


def _normalize_hhmm(value: Any, default: str = "21:00") -> str:
    text = str(value or default).strip()
    try:
        hour_text, minute_text = text.split(":", 1)
        hour = max(0, min(23, int(hour_text)))
        minute = max(0, min(59, int(minute_text)))
    except ValueError:
        return default
    return f"{hour:02d}:{minute:02d}"


def _normalize_repeat_mode(value: Any) -> str:
    mode = str(value or "none").strip()
    if mode not in {"none", "daily", "weekly", "monthly", "weekdays"}:
        return "none"
    return mode


def _parse_datetime_local(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=LOCAL_TZ).astimezone(UTC)
    return parsed.astimezone(UTC)


def _format_datetime_input(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(LOCAL_TZ).strftime("%Y-%m-%dT%H:%M")


async def _admin_guilds_for_profile(container: AppContainer, profile: OAuthProfile) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for guild in _decorate_bot_guilds(container):
        guild_id = safe_int(guild.get("id"))
        if await container.session_manager.is_guild_admin(guild_id, profile.user_id):
            rows.append(guild)
    return rows


def _build_guild_diagnostics(container: AppContainer, guild_id: int, config: GuildConfig | None) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []
    guild = _resolve_guild(container, guild_id)
    if config is None:
        diagnostics.append({"level": "warning", "title": "設定未作成", "message": "このサーバーの設定はまだ保存されていません。"})
        return diagnostics
    if config.base_voice_channel_id is None:
        diagnostics.append({"level": "warning", "title": "基点VC未選択", "message": "基点VCが未選択です。個人VCの自動作成は動作しません。"})
    if config.managed_category_id is None:
        diagnostics.append({"level": "warning", "title": "管理カテゴリ未選択", "message": "管理対象カテゴリが未選択です。作成先カテゴリを設定してください。"})
    if config.notification_channel_id is None:
        diagnostics.append({"level": "warning", "title": "通知チャンネル未選択", "message": "通知チャンネルが未選択です。フォールバック通知や管理通知に影響します。"})
    if guild is None or container.bot is None or container.bot.user is None:
        diagnostics.append({"level": "warning", "title": "Bot未接続", "message": "Bot が未接続のため、権限チェックは一部確認できません。"})
        return diagnostics

    bot_member = guild.get_member(container.bot.user.id)
    if bot_member is None:
        diagnostics.append({"level": "danger", "title": "Botメンバー不在", "message": "このサーバー内で Bot メンバーを解決できません。"})
        return diagnostics

    if config.managed_category_id is not None:
        category = guild.get_channel(config.managed_category_id)
        if isinstance(category, discord.CategoryChannel):
            perms = category.permissions_for(bot_member)
            if not perms.manage_channels:
                diagnostics.append({"level": "danger", "title": "VC作成権限不足", "message": "管理カテゴリで `Manage Channels` 権限がありません。"})
        else:
            diagnostics.append({"level": "warning", "title": "管理カテゴリ不明", "message": "選択中の管理カテゴリが存在しません。"})

    if config.notification_channel_id is not None:
        notification_channel = guild.get_channel(config.notification_channel_id)
        if isinstance(notification_channel, discord.TextChannel):
            perms = notification_channel.permissions_for(bot_member)
            if not perms.send_messages:
                diagnostics.append({"level": "danger", "title": "送信権限不足", "message": "通知チャンネルでメッセージ送信権限がありません。"})
            if not perms.embed_links:
                diagnostics.append({"level": "warning", "title": "Embed権限不足", "message": "通知チャンネルで Embed Links 権限がありません。"})
        else:
            diagnostics.append({"level": "warning", "title": "通知チャンネル不明", "message": "選択中の通知チャンネルが存在しません。"})

    move_check_channel = None
    if config.base_voice_channel_id is not None:
        channel = guild.get_channel(config.base_voice_channel_id)
        if isinstance(channel, discord.VoiceChannel):
            move_check_channel = channel
        else:
            diagnostics.append({"level": "warning", "title": "基点VC不明", "message": "選択中の基点VCが存在しません。"})
    if move_check_channel is not None:
        perms = move_check_channel.permissions_for(bot_member)
        if not perms.move_members:
            diagnostics.append({"level": "danger", "title": "メンバー移動権限不足", "message": "基点VCで Move Members 権限がありません。"})

    if not diagnostics:
        diagnostics.append({"level": "success", "title": "設定チェックOK", "message": "主要な選択項目と権限は確認できています。"})
    return diagnostics


def _build_daily_chart_rows(daily_chart: list[dict[str, Any]]) -> list[dict[str, Any]]:
    max_talk = max((safe_int(row.get("talk_seconds")) for row in daily_chart), default=0)
    scale = max(max_talk, 1)
    rows: list[dict[str, Any]] = []
    for row in daily_chart:
        talk_seconds = safe_int(row.get("talk_seconds"))
        afk_seconds = safe_int(row.get("afk_seconds"))
        rows.append(
            {
                "date": row.get("date", ""),
                "talk_seconds": talk_seconds,
                "afk_seconds": afk_seconds,
                "effective_seconds": max(0, talk_seconds - afk_seconds),
                "width_percent": round((talk_seconds / scale) * 100, 2) if talk_seconds else 0.0,
            }
        )
    return rows


def _build_talk_ratio(summary: dict[str, Any]) -> dict[str, float]:
    talk_seconds = safe_int(summary.get("talk_seconds"))
    afk_seconds = safe_int(summary.get("afk_seconds"))
    effective_seconds = safe_int(summary.get("effective_seconds"))
    total = max(talk_seconds, 1)
    return {
        "effective_percent": round((effective_seconds / total) * 100, 2) if talk_seconds else 0.0,
        "afk_percent": round((afk_seconds / total) * 100, 2) if talk_seconds else 0.0,
    }


def _build_hourly_heatmap_slots(hourly_heatmap: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_hour: dict[int, dict[str, int]] = {}
    for row in hourly_heatmap:
        hour = safe_int(row.get("hour"))
        if hour < 0 or hour > 23:
            continue
        by_hour[hour] = {
            "talk_seconds": safe_int(row.get("talk_seconds")),
            "afk_seconds": safe_int(row.get("afk_seconds")),
        }
    max_value = max((item["talk_seconds"] for item in by_hour.values()), default=0)
    scale = max(max_value, 1)
    slots: list[dict[str, Any]] = []
    for hour in range(24):
        item = by_hour.get(hour, {"talk_seconds": 0, "afk_seconds": 0})
        talk_seconds = item["talk_seconds"]
        slots.append(
            {
                "hour": hour,
                "label": f"{hour:02d}:00",
                "talk_seconds": talk_seconds,
                "afk_seconds": item["afk_seconds"],
                "alpha": round(0.08 + ((talk_seconds / scale) * 0.48), 4) if max_value else 0.08,
            }
        )
    return slots


def _build_timeline_query_params(
    *,
    user_id: str | None = None,
    event_type: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, str | None]:
    return {
        "user_id": str(user_id).strip() if user_id else None,
        "event_type": str(event_type).strip() if event_type else None,
        "date_from": str(date_from).strip() if date_from else None,
        "date_to": str(date_to).strip() if date_to else None,
    }


def _decorate_timeline_events(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["id"] = str(item.get("id") or "")
        item["guild_id"] = str(item.get("guild_id") or "")
        item["root_channel_id"] = str(item.get("root_channel_id") or "")
        item["user_id"] = str(item.get("user_id")) if item.get("user_id") is not None else None
        item["user_name"] = str(item.get("user_name") or "")
        item["display_actor"] = item["user_name"] or "System"
        result.append(item)
    return result


def _build_session_card(container: AppContainer, session_payload: dict[str, Any]) -> dict[str, Any]:
    guild_id = safe_int(session_payload.get("guild_id"))
    guild_name = str(session_payload.get("guild_name") or guild_id)
    guild = _resolve_guild(container, guild_id)
    started_at = from_iso(str(session_payload.get("started_at") or "")) or utcnow()
    active_count = safe_int(session_payload.get("active_participant_count"))
    owner = _serialize_user_identity(
        container,
        guild_id,
        safe_int(session_payload.get("owner_user_id")),
        str(session_payload.get("owner_user_name") or "Unknown"),
    )
    return {
        **session_payload,
        "guild": _serialize_guild_identity(guild, guild_id, guild_name),
        "owner": owner,
        "participant_count": active_count,
        "elapsed_label": format_duration(max(0, int((utcnow() - started_at).total_seconds()))),
        "status_label": "進行中" if active_count else "待機中",
        "status_tone": "success" if active_count else "muted",
    }


def _build_session_ui_payload(container: AppContainer, session: dict[str, Any] | Any) -> dict[str, Any]:
    payload = session if isinstance(session, dict) else session.to_payload()
    guild_id = safe_int(payload.get("guild_id"))
    guild_name = str(payload.get("guild_name") or guild_id)
    guild = _resolve_guild(container, guild_id)
    root_channel_id = safe_int(payload.get("root_channel_id"))
    root_channel_name = str(payload.get("root_channel_name") or "VC")
    root_channel = container.session_manager.resolve_voice_channel(root_channel_id)
    team_channels = {str(key): safe_int(value) for key, value in dict(payload.get("team_channels", {})).items()}
    team_assignments = {str(key): str(value) for key, value in dict(payload.get("team_assignments", {})).items()}

    live_members: dict[int, discord.Member] = {}
    if root_channel is not None and guild is not None:
        for member in container.session_manager.get_non_bot_members_for_channel(guild, root_channel):
            live_members[int(member.id)] = member
    for channel_id in team_channels.values():
        team_channel = container.session_manager.resolve_voice_channel(channel_id)
        if team_channel is None or guild is None:
            continue
        for member in container.session_manager.get_non_bot_members_for_channel(guild, team_channel):
            live_members[int(member.id)] = member

    participant_map: dict[int, dict[str, Any]] = {}
    for raw in list(payload.get("participants", [])):
        user_id = safe_int(raw.get("user_id"))
        participant_map[user_id] = dict(raw)

    if live_members:
        for user_id, raw in list(participant_map.items()):
            if user_id in live_members:
                continue
            raw["current_channel_id"] = None
            participant_map[user_id] = raw

    for user_id, member in live_members.items():
        raw = participant_map.get(user_id, {})
        current_channel_id = int(member.voice.channel.id) if member.voice and member.voice.channel else root_channel_id
        participant_map[user_id] = {
            **raw,
            "user_id": user_id,
            "user_name": member.display_name,
            "current_channel_id": current_channel_id,
            "talk_seconds": safe_int(raw.get("talk_seconds")),
            "afk_seconds": safe_int(raw.get("afk_seconds")),
            "current_team": raw.get("current_team") or team_assignments.get(str(user_id)),
            "panel_creator": bool(raw.get("panel_creator", False)),
            "self_muted": bool(member.voice and member.voice.self_mute),
            "server_muted": bool(member.voice and member.voice.mute),
            "self_deafened": bool(member.voice and member.voice.self_deaf),
            "server_deafened": bool(member.voice and member.voice.deaf),
            "in_afk_channel": bool(
                member.voice
                and member.voice.channel
                and member.guild.afk_channel
                and member.guild.afk_channel.id == member.voice.channel.id
            ),
        }

    participants: list[dict[str, Any]] = []
    for raw in participant_map.values():
        user_id = safe_int(raw.get("user_id"))
        user = _serialize_user_identity(container, guild_id, user_id, str(raw.get("user_name") or user_id))
        current_channel_id = safe_int(raw.get("current_channel_id")) if raw.get("current_channel_id") is not None else None
        location_label = "離席"
        location_kind = "away"
        if current_channel_id == root_channel_id:
            location_label = "メインVC"
            location_kind = "root"
        elif current_channel_id is not None:
            matched_team = next((team_name for team_name, channel_id in team_channels.items() if channel_id == current_channel_id), None)
            location_label = matched_team or "チームVC"
            location_kind = "team"
        participants.append(
            {
                **raw,
                "user_id": str(user_id),
                "current_channel_id": str(current_channel_id) if current_channel_id is not None else None,
                "user": user,
                "location_label": location_label,
                "location_kind": location_kind,
                "status_flags": [
                    item
                    for item in (
                        {"icon": "🎙", "label": "自己ミュート"} if raw.get("self_muted") else None,
                        {"icon": "🔇", "label": "自己デafen"} if raw.get("self_deafened") else None,
                        {"icon": "💤", "label": "AFK"} if raw.get("in_afk_channel") else None,
                    )
                    if item is not None
                ],
            }
        )
    participants.sort(key=lambda item: (item.get("location_kind") == "away", item["user"]["display_name"].lower()))

    teams: list[dict[str, Any]] = []
    team_names = list(payload.get("team_names", []))
    for team_name in team_names:
        members = [participant for participant in participants if participant.get("current_team") == team_name]
        teams.append(
            {
                "name": team_name,
                "channel_id": str(team_channels.get(team_name)) if team_channels.get(team_name) is not None else None,
                "member_count": len(members),
                "members": members,
            }
        )
    unassigned_members = [participant for participant in participants if not participant.get("current_team")]
    participant_count = len([participant for participant in participants if participant.get("current_channel_id") is not None])

    return {
        **payload,
        "guild_id": str(guild_id),
        "root_channel_id": str(root_channel_id),
        "starter_user_id": str(safe_int(payload.get("starter_user_id"))),
        "owner_user_id": str(safe_int(payload.get("owner_user_id"))),
        "panel_creator_id": str(safe_int(payload.get("panel_creator_id"))) if payload.get("panel_creator_id") is not None else None,
        "notice_channel_id": str(safe_int(payload.get("notice_channel_id"))) if payload.get("notice_channel_id") is not None else None,
        "notice_message_id": str(safe_int(payload.get("notice_message_id"))) if payload.get("notice_message_id") is not None else None,
        "team_assignments": team_assignments,
        "access_mode": str(payload.get("access_mode") or "public"),
        "invited_user_ids": [str(item) for item in payload.get("invited_user_ids", [])],
        "access_role_ids": [str(item) for item in payload.get("access_role_ids", [])],
        "guild": _serialize_guild_identity(guild, guild_id, guild_name),
        "root_channel": {
            "id": str(root_channel_id),
            "name": root_channel_name,
            "icon": "🔊",
            "user_limit": root_channel.user_limit if root_channel is not None else 0,
            "bitrate": root_channel.bitrate if root_channel is not None else 64000,
        },
        "owner": _serialize_user_identity(
            container,
            guild_id,
            safe_int(payload.get("owner_user_id")),
            str(payload.get("owner_user_name") or "Unknown"),
        ),
        "starter": _serialize_user_identity(
            container,
            guild_id,
            safe_int(payload.get("starter_user_id")),
            str(payload.get("starter_user_name") or "Unknown"),
        ),
        "participant_count": participant_count,
        "active_participant_count": participant_count,
        "elapsed_seconds": safe_int(payload.get("elapsed_seconds")),
        "elapsed_label": format_duration(safe_int(payload.get("elapsed_seconds"))),
        "participants": participants,
        "teams": teams,
        "unassigned_members": unassigned_members,
        "team_channels": {team_name: str(channel_id) for team_name, channel_id in team_channels.items()},
        "has_pending_team_channels": any(team_channels.values()),
    }


async def _resolve_voice_dashboard_state(container: AppContainer, guild_id: int, root_channel_id: int) -> dict[str, Any]:
    guild_id, root_channel_id = normalize_ids(guild_id, root_channel_id)
    key = make_session_key(guild_id, root_channel_id)
    guild = _resolve_guild(container, guild_id)
    existing_session = container.session_manager.get_session(guild_id, root_channel_id)
    channel = await container.session_manager.resolve_voice_channel_for_guild(guild_id, root_channel_id)
    non_bot_members = (
        container.session_manager.get_non_bot_members_for_channel(guild, channel)
        if guild is not None and channel is not None
        else []
    )
    session = await container.session_manager.get_or_create_active_session_for_channel(guild_id, root_channel_id)
    restored = existing_session is None and session is not None
    active_keys = container.session_manager.get_active_session_keys()

    container.logger.info(
        "VC管理ページ: guild_id=%s vc_id=%s key=%s active_keys=%s channel=%s members=%s session_found=%s",
        guild_id,
        root_channel_id,
        key,
        active_keys,
        channel.name if channel else None,
        len(non_bot_members) if channel else 0,
        bool(session),
    )
    container.logger.info(
        "[VC管理] guild_id=%s vc_id=%s active_keys=%s channel=%s non_bot_members=%s session_found=%s restored=%s",
        guild_id,
        root_channel_id,
        active_keys,
        channel.name if channel else None,
        len(non_bot_members),
        bool(session),
        restored,
    )

    if session is not None:
        session_view = _build_session_ui_payload(container, session)
    else:
        guild = _resolve_guild(container, guild_id)
        config = await container.session_manager.get_guild_config(guild_id)
        session_view = _build_session_ui_payload(
            container,
            {
                "session_id": f"fallback:{guild_id}:{root_channel_id}",
                "guild_id": guild_id,
                "guild_name": guild.name if guild else str(guild_id),
                "root_channel_id": root_channel_id,
                "root_channel_name": channel.name if channel else str(root_channel_id),
                "starter_user_id": non_bot_members[0].id if non_bot_members else 0,
                "starter_user_name": non_bot_members[0].display_name if non_bot_members else "Unknown",
                "owner_user_id": non_bot_members[0].id if non_bot_members else 0,
                "owner_user_name": non_bot_members[0].display_name if non_bot_members else "Unknown",
                "started_at": utcnow().isoformat(),
                "panel_creator_id": None,
                "panel_creator_name": None,
                "team_names": config.team_names.copy() if config else ["A", "B", "C", "D"],
                "team_mode": config.team_mode if config else "custom",
                "team_assignments": {},
                "team_channels": {},
                "participants": [],
                "active_participant_count": len(non_bot_members),
                "elapsed_seconds": 0,
            },
        )

    management_url = await container.session_manager.build_management_url(guild_id, root_channel_id)
    return {
        "key": key,
        "session": session,
        "session_view": session_view,
        "guild": _resolve_guild(container, guild_id),
        "channel": channel,
        "participants": session_view["participants"],
        "teams": session_view["teams"],
        "unassigned_members": session_view["unassigned_members"],
        "non_bot_members": non_bot_members,
        "management_url": management_url,
        "restored": restored,
    }


def _build_rankings_view(rankings: list[dict[str, Any]], container: AppContainer) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    bot_user_id = container.bot.user.id if container.bot and container.bot.user else None
    rows: list[dict[str, Any]] = []
    for row in rankings:
        user_id = safe_int(row.get("user_id"))
        if bot_user_id is not None and user_id == bot_user_id:
            continue
        guild_id = safe_int(row.get("guild_id"))
        guild_name = str(row.get("guild_name") or guild_id)
        guild = _resolve_guild(container, guild_id)
        decorated = dict(row)
        decorated["guild"] = _serialize_guild_identity(guild, guild_id, guild_name)
        decorated["user"] = _serialize_user_identity(container, guild_id, user_id, str(row.get("user_name") or user_id))
        decorated["rank_label"] = f"{safe_int(row.get('rank'))}位"
        rows.append(decorated)
    return rows[:3], rows[3:]


async def _fetch_runtime_settings(container: AppContainer) -> dict[str, str]:
    return await container.config_repo.get_runtime_settings()


def _owner_user_id(settings: dict[str, str]) -> int:
    return safe_int(settings.get("owner_user_id"))


def _oauth_config_error(settings: dict[str, str]) -> str | None:
    if not settings.get("client_id"):
        return "Discord Client ID が未設定です。"
    if not settings.get("client_secret"):
        return "Discord Client Secret が未設定です。"
    if not settings.get("redirect_uri"):
        return "Discord Redirect URI が未設定です。"
    return None


def _recommended_callback_uri(settings: dict[str, str]) -> str | None:
    base_url = (settings.get("base_url") or "").rstrip("/")
    if not base_url:
        return None
    return f"{base_url}/callback"


def _filter_shared_guilds(profile: OAuthProfile, container: AppContainer) -> list[dict[str, Any]]:
    if container.bot is None:
        return list(profile.guilds)
    bot_guild_ids = {guild.id for guild in container.bot.guilds}
    return [guild for guild in profile.guilds if safe_int(guild.get("id")) in bot_guild_ids]


def _build_auth_url(settings: dict[str, str], state: str) -> str:
    params = {
        "client_id": settings.get("client_id", ""),
        "redirect_uri": settings.get("redirect_uri", ""),
        "response_type": "code",
        "scope": "identify guilds",
        "state": state,
        "prompt": "consent",
    }
    return f"https://discord.com/api/oauth2/authorize?{urlencode(params)}"


async def _exchange_code(settings: dict[str, str], code: str) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(
            "https://discord.com/api/oauth2/token",
            data={
                "client_id": settings.get("client_id", ""),
                "client_secret": settings.get("client_secret", ""),
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": settings.get("redirect_uri", ""),
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        response.raise_for_status()
        return response.json()


async def _fetch_discord_profile(access_token: str) -> OAuthProfile:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=20) as client:
        user_response = await client.get("https://discord.com/api/users/@me", headers=headers)
        guilds_response = await client.get("https://discord.com/api/users/@me/guilds", headers=headers)
        user_response.raise_for_status()
        guilds_response.raise_for_status()
        user_payload = user_response.json()
        guilds_payload = guilds_response.json()
    return OAuthProfile(
        user_id=int(user_payload["id"]),
        username=str(user_payload["username"]),
        global_name=user_payload.get("global_name"),
        avatar_url=_build_avatar_url(user_payload),
        guilds=guilds_payload,
    )


def create_app(container: AppContainer) -> FastAPI:
    template_dir = container.root_dir / "vc_control" / "templates"
    _validate_templates(template_dir)
    templates = Jinja2Templates(directory=str(template_dir))
    app = FastAPI(title="VC Control Dashboard")
    session_secret = os.environ.get("SESSION_SECRET_FALLBACK", secrets.token_urlsafe(32))
    app.add_middleware(SessionMiddleware, secret_key=session_secret, same_site="lax")
    app.mount("/static", StaticFiles(directory=str(container.root_dir / "vc_control" / "static")), name="static")
    spa_dir = container.root_dir / "vc_control" / "static" / "app"
    spa_assets_dir = spa_dir / "assets"
    if spa_assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(spa_assets_dir)), name="spa-assets")
    app.state.container = container
    app.state.templates = templates
    app.state.ws_secret = session_secret

    def render(
        request: Request,
        template_name: str,
        context: dict[str, Any] | None = None,
        status_code: int = 200,
    ) -> HTMLResponse:
        profile = _current_profile(request)
        current_user_view = None
        if profile is not None:
            current_user_view = {
                **_build_user_badge(profile.display_name, profile.avatar_url),
                "id": str(profile.user_id),
            }
        base_context = {
            "request": request,
            "current_user": profile,
            "current_user_view": current_user_view,
            "is_owner": bool(request.session.get("is_owner")),
            "app_version": "1.0.0",
        }
        if context:
            base_context.update(context)
        base_context["is_owner"] = bool(base_context.get("is_owner"))
        return templates.TemplateResponse(
            request=request,
            name=template_name,
            context=base_context,
            status_code=status_code,
        )

    def render_error(
        request: Request,
        title: str,
        message: str,
        *,
        status_code: int,
        next_url: str = "/login",
        next_label: str = "ログイン画面へ戻る",
        details: list[str] | None = None,
    ) -> HTMLResponse:
        return render(
            request,
            "error.html",
            {
                "title": title,
                "error_message": message,
                "error_details": details or [],
                "next_url": next_url,
                "next_label": next_label,
            },
            status_code=status_code,
        )

    def serve_spa() -> Response:
        return FileResponse(str(spa_dir / "index.html"))

    @app.get("/", response_class=HTMLResponse, response_model=None)
    async def index(request: Request) -> Response:
        if not await container.config_repo.is_setup_complete():
            return RedirectResponse("/setup", status_code=302)
        profile = _current_profile(request)
        if profile is None:
            return RedirectResponse("/login", status_code=302)
        settings = await _fetch_runtime_settings(container)
        destination = "/admin" if _owner_user_id(settings) == profile.user_id else "/dashboard/me"
        return RedirectResponse(destination, status_code=302)

    @app.get("/setup", response_model=None)
    async def setup_page(request: Request) -> Response:
        if await container.config_repo.is_setup_complete():
            raise HTTPException(status_code=404, detail="初回セットアップは無効です。")
        return serve_spa()

    @app.post("/setup", response_model=None)
    async def submit_setup(request: Request) -> Response:
        if await container.config_repo.is_setup_complete():
            raise HTTPException(status_code=404, detail="初回セットアップは無効です。")
        form = await request.form()
        expected_password = os.environ.get("SETUP_PASSWORD", "")
        payload = SetupPayload(
            setup_password=str(form.get("setup_password", "")),
            bot_token=str(form.get("bot_token", "")).strip(),
            client_id=str(form.get("client_id", "")).strip(),
            client_secret=str(form.get("client_secret", "")).strip(),
            redirect_uri=str(form.get("redirect_uri", "")).strip(),
            base_url=str(form.get("base_url", "")).strip(),
            owner_user_id=safe_int(form.get("owner_user_id")),
            dashboard_host=str(form.get("dashboard_host", _default_dashboard_host())).strip(),
            dashboard_port=safe_int(form.get("dashboard_port"), _default_dashboard_port()),
        )
        if not expected_password or not hmac.compare_digest(payload.setup_password, expected_password):
            raise HTTPException(status_code=403, detail="セットアップパスワードが正しくありません。")
        await container.config_repo.save_initial_setup(payload, secrets.token_urlsafe(32))
        return RedirectResponse("/login?setup=1", status_code=302)

    @app.get("/login", response_model=None)
    async def login_page(request: Request) -> Response:
        if not await container.config_repo.is_setup_complete():
            return RedirectResponse("/setup", status_code=302)
        settings = await _fetch_runtime_settings(container)
        profile = _current_profile(request)
        if profile is not None:
            destination = "/admin" if _owner_user_id(settings) == profile.user_id else "/dashboard/me"
            return RedirectResponse(destination, status_code=302)
        return serve_spa()

    @app.get("/auth/login", response_model=None)
    async def login(request: Request) -> Response:
        if not await container.config_repo.is_setup_complete():
            return RedirectResponse("/setup", status_code=302)
        settings = await _fetch_runtime_settings(container)
        if _oauth_config_error(settings):
            return RedirectResponse("/login?oauth_error=1", status_code=302)
        state = secrets.token_urlsafe(24)
        request.session["oauth_state"] = state
        return RedirectResponse(_build_auth_url(settings, state), status_code=302)

    async def _handle_oauth_callback(request: Request, code: str | None, state: str | None) -> Response:
        if not await container.config_repo.is_setup_complete():
            return RedirectResponse("/setup", status_code=302)
        expected_state = request.session.pop("oauth_state", None)
        if not code:
            return render_error(
                request,
                "Discord OAuth ログインに失敗しました",
                "認可コードが受け取れませんでした。もう一度ログインをやり直してください。",
                status_code=400,
            )
        if not state or not expected_state or expected_state != state:
            return render_error(
                request,
                "Discord OAuth ログインに失敗しました",
                "state の検証に失敗しました。セッションが切れているか、Redirect URI の設定が一致していない可能性があります。",
                status_code=400,
                details=["Discord Developer Portal とアプリ設定の Redirect URI を完全一致させてください。"],
            )
        settings = await _fetch_runtime_settings(container)
        config_error = _oauth_config_error(settings)
        if config_error:
            return render_error(
                request,
                "OAuth設定エラー",
                config_error,
                status_code=500,
                next_url="/login",
                next_label="ログイン画面へ戻る",
            )
        try:
            token_payload = await _exchange_code(settings, code)
            profile = await _fetch_discord_profile(token_payload["access_token"])
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            container.logger.exception("OAuth認証に失敗しました")
            configured_redirect_uri = settings.get("redirect_uri", "")
            recommended_redirect_uri = _recommended_callback_uri(settings)
            details = [
                "Discord Developer Portal の Redirect URI とアプリの Redirect URI を完全一致させてください。",
                f"現在のアプリ設定: {configured_redirect_uri or '未設定'}",
            ]
            if recommended_redirect_uri:
                details.append(f"推奨値: {recommended_redirect_uri}")
            details.append("HTTP と HTTPS が混在していないか確認してください。")
            return render_error(
                request,
                "Discord OAuth ログインに失敗しました",
                "アクセストークンの取得に失敗しました。Redirect URI、Client ID、Client Secret の設定を確認してください。",
                status_code=502,
                details=details,
            )
        is_admin = _owner_user_id(settings) == profile.user_id
        shared_guilds = _filter_shared_guilds(profile, container)
        if not is_admin and container.bot is not None and not shared_guilds:
            request.session.pop("oauth_profile", None)
            return render_error(
                request,
                "ログインできません",
                "Bot が参加している Discord サーバーに所属していないため、このダッシュボードは利用できません。",
                status_code=403,
                details=["Bot が参加しているサーバーへ参加しているアカウントでログインしてください。"],
            )
        if container.bot is not None:
            profile.guilds = shared_guilds
        request.session["oauth_profile"] = profile.to_session()
        request.session["shared_guild_ids"] = [safe_int(guild.get("id")) for guild in shared_guilds]
        request.session["is_owner"] = is_admin
        return RedirectResponse("/admin" if is_admin else "/dashboard/me", status_code=302)

    @app.get("/callback", response_class=HTMLResponse, response_model=None)
    @app.get("/auth/callback", response_class=HTMLResponse, response_model=None)
    async def auth_callback(request: Request, code: str | None = None, state: str | None = None) -> Response:
        return await _handle_oauth_callback(request, code, state)

    @app.get("/logout", response_model=None)
    @app.get("/auth/logout", response_model=None)
    async def logout(request: Request) -> Response:
        request.session.clear()
        return RedirectResponse("/login", status_code=302)

    @app.get("/dashboard/me", response_class=HTMLResponse, response_model=None)
    async def dashboard_me(request: Request) -> Response:
        profile = await _require_profile(request)
        settings = await _fetch_runtime_settings(container)
        is_admin = _owner_user_id(settings) == profile.user_id
        sessions = await container.session_manager.list_accessible_sessions(profile.user_id)
        session_cards = [_build_session_card(container, session) for session in sessions]
        summary = await container.stats_repo.get_user_period_summary(profile.user_id, "all")
        guild_breakdown = _decorate_guild_rows(await container.stats_repo.get_user_guild_breakdown(profile.user_id, "all"), container)
        return render(
            request,
            "dashboard.html",
            {
                "title": "マイダッシュボード",
                "sessions": session_cards,
                "summary": summary,
                "guild_breakdown": guild_breakdown,
                "is_admin": is_admin,
                "format_duration": format_duration,
            },
        )

    @app.get("/dashboard/settings", response_class=HTMLResponse, response_model=None)
    async def user_settings(request: Request) -> Response:
        await _require_profile(request)
        return render(
            request,
            "user_settings.html",
            {
                "title": "ユーザー設定",
            },
        )

    @app.get("/dashboard/reservations", response_class=HTMLResponse, response_model=None)
    async def reservations_page(request: Request, guild_id: int | None = None) -> Response:
        profile = await _require_profile(request)
        guilds = await _admin_guilds_for_profile(container, profile)
        selected_guild_id = guild_id or (safe_int(guilds[0]["id"]) if guilds else 0)
        if selected_guild_id and not await container.session_manager.is_guild_admin(selected_guild_id, profile.user_id):
            raise HTTPException(status_code=403, detail="Server administrator permission is required.")
        selected_guild = _resolve_guild(container, selected_guild_id) if selected_guild_id else None
        channel_catalog = _serialize_guild_channels(container, selected_guild_id) if selected_guild_id else {"categories": [], "voice_channels": [], "text_channels": []}
        selected_config = await container.config_repo.get_guild_config(selected_guild_id) if selected_guild_id else None
        member_catalog = _serialize_guild_members(container, selected_guild_id) if selected_guild_id else []
        schedules = await container.config_repo.list_scheduled_vcs(selected_guild_id or None)
        return render(
            request,
            "reservations.html",
            {
                "title": "VC予約",
                "page_name": "reservations",
                "guild_id": str(selected_guild_id) if selected_guild_id else "",
                "guilds": guilds,
                "selected_guild_id": selected_guild_id,
                "selected_guild": selected_guild,
                "selected_config": selected_config,
                "channel_catalog": channel_catalog,
                "member_catalog": member_catalog,
                "schedules": schedules,
                "format_datetime_input": _format_datetime_input,
            },
        )

    @app.post("/dashboard/voice/create", response_model=None)
    async def create_web_voice_channel(request: Request) -> Response:
        profile = await _require_profile(request)
        form = await request.form()
        guild_id = safe_int(form.get("guild_id"))
        if not await container.session_manager.is_guild_admin(guild_id, profile.user_id):
            raise HTTPException(status_code=403, detail="Server administrator permission is required.")
        vc_type = str(form.get("vc_type", "personal")).strip()
        end_at = _parse_datetime_local(form.get("end_at"))
        if vc_type == "event" and end_at is None:
            raise HTTPException(status_code=400, detail="Temporary event VC requires end time.")
        try:
            channel = await container.session_manager.create_web_voice_channel(
                guild_id=guild_id,
                actor_id=profile.user_id,
                actor_name=profile.display_name,
                vc_type=vc_type,
                owner_user_id=safe_int(form.get("owner_user_id")) or None,
                vc_name=str(form.get("vc_name", "")).strip() or None,
                user_limit=safe_int(form.get("user_limit"), 0),
                bitrate=safe_int(form.get("bitrate")) or None,
                end_at=end_at,
                description=str(form.get("description", "")).strip(),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return RedirectResponse(f"/dashboard/voice/{guild_id}/{channel.id}", status_code=302)

    @app.post("/dashboard/reservations", response_model=None)
    async def create_reservation(request: Request) -> Response:
        profile = await _require_profile(request)
        form = await request.form()
        guild_id = safe_int(form.get("guild_id"))
        if not await container.session_manager.is_guild_admin(guild_id, profile.user_id):
            raise HTTPException(status_code=403, detail="Server administrator permission is required.")
        guild = _resolve_guild(container, guild_id)
        if guild is None:
            raise HTTPException(status_code=404, detail="Guild is not available.")
        start_at = _parse_datetime_local(form.get("start_at"))
        if start_at is None:
            raise HTTPException(status_code=400, detail="Start time is required.")
        end_at = _parse_datetime_local(form.get("end_at"))
        if end_at is not None and end_at <= start_at:
            raise HTTPException(status_code=400, detail="End time must be later than start time.")
        repeat_weekdays = [safe_int(item, -1) for item in form.getlist("repeat_weekdays")]
        repeat_weekdays = [item for item in repeat_weekdays if 0 <= item <= 6]
        mention_targets = [
            chunk.strip()
            for chunk in str(form.get("mention_targets", "")).replace("\n", ",").split(",")
            if chunk.strip()
        ]
        mention_type = str(form.get("mention_type", "none")).strip()
        if mention_type not in {"none", "user", "role", "everyone", "here"}:
            mention_type = "none"
        scheduled = ScheduledVC(
            id=None,
            guild_id=guild.id,
            guild_name=guild.name,
            creator_user_id=profile.user_id,
            creator_user_name=profile.display_name,
            vc_name=str(form.get("vc_name", "")).strip() or "Scheduled VC",
            category_id=safe_int(form.get("category_id")) or None,
            user_limit=max(0, min(99, safe_int(form.get("user_limit"), 0))),
            bitrate=safe_int(form.get("bitrate")) or None,
            mention_type=mention_type,
            mention_targets=mention_targets,
            description=str(form.get("description", "")).strip(),
            start_at=start_at,
            end_at=end_at,
            repeat_mode=_normalize_repeat_mode(form.get("repeat_mode")),
            repeat_weekdays=repeat_weekdays,
        )
        await container.config_repo.create_scheduled_vc(scheduled)
        return RedirectResponse(f"/dashboard/reservations?guild_id={guild.id}&saved=1", status_code=302)

    @app.post("/dashboard/reservations/{scheduled_id}/delete", response_model=None)
    async def delete_reservation(request: Request, scheduled_id: int) -> Response:
        profile = await _require_profile(request)
        schedules = await container.config_repo.list_scheduled_vcs(limit=1000)
        scheduled = next((item for item in schedules if item.id == scheduled_id), None)
        if scheduled is None:
            raise HTTPException(status_code=404, detail="Reservation not found.")
        if not await container.session_manager.is_guild_admin(scheduled.guild_id, profile.user_id):
            raise HTTPException(status_code=403, detail="Server administrator permission is required.")
        await container.session_manager.cancel_scheduled_vc(scheduled)
        return RedirectResponse(f"/dashboard/reservations?guild_id={scheduled.guild_id}&deleted=1", status_code=302)

    @app.get("/dashboard/voice/{guild_id}/{root_channel_id}", response_class=HTMLResponse, response_model=None)
    async def voice_dashboard(request: Request, guild_id: int, root_channel_id: int) -> Response:
        profile = await _require_profile(request)
        state = await _resolve_voice_dashboard_state(container, guild_id, root_channel_id)
        session = state["session"]
        container.logger.info(
            "[VC管理ページ] guild_id=%s vc_id=%s active_keys=%s channel=%s non_bot_members=%s session_found=%s restored=%s",
            safe_int(guild_id),
            safe_int(root_channel_id),
            container.session_manager.get_active_session_keys(),
            state["channel"].name if state["channel"] else None,
            len(state["non_bot_members"]),
            bool(session),
            bool(state.get("restored")),
        )
        channel = state["channel"]
        non_bot_members = state["non_bot_members"]

        if session is None and not non_bot_members:
            raise HTTPException(status_code=404, detail="このVCには現在アクティブなセッションがありません。")

        if session is not None:
            if not await container.session_manager.can_view_session(session, profile.user_id):
                raise HTTPException(status_code=403, detail="閲覧権限がありません。")
            can_edit = await container.session_manager.can_edit_session(session, profile.user_id)
            can_assign_others = await container.session_manager.can_assign_others(session, profile.user_id)
        else:
            member_ids = {member.id for member in non_bot_members}
            if profile.user_id not in member_ids and not await container.session_manager.is_guild_admin(guild_id, profile.user_id):
                raise HTTPException(status_code=403, detail="閲覧権限がありません。")
            can_edit = await container.session_manager.is_guild_admin(guild_id, profile.user_id)
            can_assign_others = False

        session_view = state["session_view"]
        session_view["can_edit"] = can_edit
        session_view["can_assign_others"] = can_assign_others
        return render(
            request,
            "voice.html",
            {
                "title": "VC管理",
                "page_name": "voice",
                "guild_id": guild_id,
                "root_channel_id": root_channel_id,
                "session": session_view,
                "guild": state["guild"],
                "channel": channel,
                "participants": state["participants"],
                "teams": state["teams"],
                "unassigned_members": state["unassigned_members"],
                "member_catalog": _serialize_guild_members(container, guild_id),
                "role_catalog": _serialize_guild_roles(container, guild_id),
                "can_edit": can_edit,
                "can_assign_others": can_assign_others,
                "can_manage": can_edit,
                "management_url": state["management_url"],
                "format_duration": format_duration,
            },
        )

    @app.get("/dashboard/stats/me", response_class=HTMLResponse, response_model=None)
    async def my_stats(request: Request, period: str = "all", guild_id: int | None = None) -> Response:
        profile = await _require_profile(request)
        summary = await container.stats_repo.get_user_period_summary(profile.user_id, period)
        breakdown = _decorate_guild_rows(await container.stats_repo.get_user_guild_breakdown(profile.user_id, period), container)
        known_guilds = _decorate_guild_rows(await container.stats_repo.get_known_guilds_for_user(profile.user_id), container)
        daily_chart = await container.stats_repo.get_user_daily_chart(profile.user_id, guild_id)
        hourly_heatmap = await container.stats_repo.get_user_hourly_heatmap(profile.user_id, guild_id)
        daily_chart_rows = _build_daily_chart_rows(daily_chart)
        talk_ratio = _build_talk_ratio(summary)
        hourly_heatmap_slots = _build_hourly_heatmap_slots(hourly_heatmap)
        return render(
            request,
            "stats_me.html",
            {
                "title": "自分の通話時間",
                "period": period,
                "selected_guild_id": guild_id,
                "summary": summary,
                "breakdown": breakdown,
                "known_guilds": known_guilds,
                "daily_chart_rows": daily_chart_rows,
                "talk_ratio": talk_ratio,
                "hourly_heatmap_slots": hourly_heatmap_slots,
                "format_duration": format_duration,
            },
        )

    @app.get("/dashboard/rankings", response_class=HTMLResponse, response_model=None)
    async def rankings(request: Request, period: str = "all", guild_id: int | None = None) -> Response:
        profile = await _require_profile(request)
        rankings_data = await container.stats_repo.get_rankings(period=period, guild_id=guild_id, limit=100)
        known_guilds = _decorate_guild_rows(await container.stats_repo.get_known_guilds_for_user(profile.user_id), container)
        top_rankings, other_rankings = _build_rankings_view(rankings_data, container)
        return render(
            request,
            "rankings.html",
            {
                "title": "ランキング",
                "period": period,
                "selected_guild_id": guild_id,
                "top_rankings": top_rankings,
                "other_rankings": other_rankings,
                "known_guilds": known_guilds,
                "format_duration": format_duration,
            },
        )

    @app.get("/dashboard/sessions/{session_id}", response_class=HTMLResponse, response_model=None)
    async def session_detail(request: Request, session_id: str, user_id: str | None = None, event_type: str | None = None, date_from: str | None = None, date_to: str | None = None) -> Response:
        profile = await _require_profile(request)
        completed = await container.stats_repo.get_completed_session(session_id)
        if completed is None:
            raise HTTPException(status_code=404, detail="セッションが見つかりません。")
        guild_id = safe_int(completed.get("guild_id"))
        is_admin = await container.session_manager.is_guild_admin(guild_id, profile.user_id)
        member_ids = {safe_int(item.get("user_id")) for item in await container.stats_repo.list_timeline_events(session_id=session_id)}
        if not is_admin and profile.user_id not in member_ids and profile.user_id != safe_int(completed.get("started_by")):
            raise HTTPException(status_code=403, detail="閲覧権限がありません。")
        filters = _build_timeline_query_params(user_id=user_id, event_type=event_type, date_from=date_from, date_to=date_to)
        timeline = await container.stats_repo.list_timeline_events(
            session_id=session_id,
            user_id=filters["user_id"],
            event_type=filters["event_type"],
            date_from=filters["date_from"],
            date_to=filters["date_to"],
        )
        return render(
            request,
            "session_detail.html",
            {
                "title": "Session Detail",
                "session": completed,
                "timeline_events": _decorate_timeline_events(timeline),
                "filters": filters,
                "format_duration": format_duration,
            },
        )

    @app.get("/admin", response_class=HTMLResponse, response_model=None)
    async def admin_page(request: Request, guild_id: int | None = None, page: int = 1) -> Response:
        profile = await _require_admin(request, container)
        settings = await _fetch_runtime_settings(container)
        guild_configs = await container.config_repo.list_guild_configs()
        bot_guilds = _decorate_bot_guilds(container)
        selected_guild_id = guild_id or (bot_guilds[0]["id"] if bot_guilds else None)
        selected_config = next((config for config in guild_configs if config.guild_id == selected_guild_id), None)
        selected_config_saved = selected_config is not None
        channel_catalog = _serialize_guild_channels(container, selected_guild_id) if selected_guild_id else {"categories": [], "voice_channels": [], "text_channels": []}
        selected_guild = next((guild for guild in bot_guilds if guild["id"] == selected_guild_id), None)
        if selected_guild_id is not None:
            guild_name = selected_guild["name"] if selected_guild else str(selected_guild_id)
            selected_config = _build_guild_config_defaults(selected_guild_id, guild_name, selected_config)
        diagnostics = _build_guild_diagnostics(container, selected_guild_id, selected_config) if selected_guild_id and selected_config else []
        error_logs, total_logs = await container.config_repo.get_error_logs(page=page, per_page=25)
        recent_sessions = _decorate_guild_rows(await container.stats_repo.get_recent_sessions(limit=20), container)
        return render(
            request,
            "admin.html",
            {
                "title": "アドミン管理",
                "profile": profile,
                "settings": settings,
                "bot_guilds": bot_guilds,
                "selected_guild": selected_guild,
                "selected_guild_id": selected_guild_id,
                "selected_config": selected_config,
                "selected_config_saved": selected_config_saved,
                "channel_catalog": channel_catalog,
                "diagnostics": diagnostics,
                "recent_sessions": recent_sessions,
                "error_logs": error_logs,
                "page": page,
                "total_logs": total_logs,
                "format_duration": format_duration,
                "recommended_redirect_uri": _recommended_callback_uri(settings),
            },
        )

    @app.post("/admin/settings", response_model=None)
    async def update_admin_settings(request: Request) -> Response:
        await _require_admin(request, container)
        form = await request.form()
        plain_values = {
            "client_id": str(form.get("client_id", "")).strip(),
            "redirect_uri": str(form.get("redirect_uri", "")).strip(),
            "base_url": str(form.get("base_url", "")).strip(),
            "owner_user_id": str(safe_int(form.get("owner_user_id"))),
            "dashboard_host": str(form.get("dashboard_host", _default_dashboard_host())).strip(),
            "dashboard_port": str(safe_int(form.get("dashboard_port"), _default_dashboard_port())),
            "timeline_retention_days": str(max(1, safe_int(form.get("timeline_retention_days"), 90))),
        }
        secure_values = {
            "bot_token": str(form.get("bot_token", "")).strip(),
            "client_secret": str(form.get("client_secret", "")).strip(),
        }
        await container.config_repo.update_runtime_settings(plain_values, secure_values)
        return RedirectResponse("/admin?saved=1", status_code=302)

    @app.post("/admin/guilds/{guild_id}", response_model=None)
    async def update_guild_config(request: Request, guild_id: int) -> Response:
        await _require_admin(request, container)
        form = await request.form()
        current = await container.config_repo.get_guild_config(guild_id)
        guild = container.bot.get_guild(guild_id) if container.bot else None
        guild_name = current.guild_name if current else (guild.name if guild else str(guild_id))
        config = GuildConfig(
            guild_id=guild_id,
            guild_name=guild_name,
            managed_category_id=safe_int(form.get("managed_category_id")) or None,
            base_voice_channel_id=safe_int(form.get("base_voice_channel_id")) or None,
            notification_channel_id=safe_int(form.get("notification_channel_id")) or None,
            first_empty_notice_sec=safe_int(form.get("first_empty_notice_sec"), 30),
            final_delete_sec=safe_int(form.get("final_delete_sec"), 90),
            solo_cleanup_mode=_normalize_solo_cleanup_mode(form.get("solo_cleanup_mode")),
            solo_notice_after_sec=max(60, safe_int(form.get("solo_notice_after_sec"), 3600)),
            solo_delete_warning_after_sec=max(60, safe_int(form.get("solo_delete_warning_after_sec"), 1800)),
            solo_repeat_notice_sec=max(300, safe_int(form.get("solo_repeat_notice_sec"), 3600)),
            ranking_post_enabled=str(form.get("ranking_post_enabled", "")) == "on",
            ranking_post_channel_id=safe_int(form.get("ranking_post_channel_id")) or None,
            ranking_post_frequencies=_normalize_ranking_frequencies(form.getlist("ranking_post_frequencies")),
            ranking_post_time=_normalize_hhmm(form.get("ranking_post_time")),
            ranking_post_targets=_normalize_ranking_targets(form.getlist("ranking_post_targets")),
            ranking_post_last_keys=current.ranking_post_last_keys.copy() if current else {},
            team_mode=str(form.get("team_mode", "custom")).strip(),
            team_names=[name.strip() for name in str(form.get("team_names", "A,B,C,D")).split(",") if name.strip()],
            enabled=str(form.get("enabled", "")) == "on",
        )
        await container.config_repo.upsert_guild_config(config)
        await container.session_manager.refresh_guild_configs()
        return RedirectResponse(f"/admin?guild_id={guild_id}&saved=1", status_code=302)

    @app.post("/admin/guilds/{guild_id}/rankings/post", response_model=None)
    async def post_guild_rankings(request: Request, guild_id: int) -> Response:
        await _require_admin(request, container)
        await container.session_manager.post_activity_rankings(guild_id, frequency="manual")
        return RedirectResponse(f"/admin?guild_id={guild_id}&rankings_posted=1", status_code=302)

    @app.post("/api/admin/settings")
    async def api_update_admin_settings(request: Request) -> JSONResponse:
        await _require_admin(request, container)
        payload = await request.json()
        current = await _fetch_runtime_settings(container)
        plain_values = {
            "client_id": str(payload.get("client_id", current.get("client_id", ""))).strip(),
            "redirect_uri": str(payload.get("redirect_uri", current.get("redirect_uri", ""))).strip(),
            "base_url": str(payload.get("base_url", current.get("base_url", ""))).strip(),
            "owner_user_id": str(safe_int(payload.get("owner_user_id", current.get("owner_user_id", "0")))),
            "dashboard_host": str(payload.get("dashboard_host", current.get("dashboard_host", _default_dashboard_host()))).strip(),
            "dashboard_port": str(safe_int(payload.get("dashboard_port", current.get("dashboard_port", _default_dashboard_port())))),
            "timeline_retention_days": str(max(1, safe_int(payload.get("timeline_retention_days", current.get("timeline_retention_days", "90")), 90))),
        }
        secure_values = {
            "bot_token": str(payload.get("bot_token", "")).strip(),
            "client_secret": str(payload.get("client_secret", "")).strip(),
        }
        await container.config_repo.update_runtime_settings(plain_values, secure_values)
        updated = await _fetch_runtime_settings(container)
        warnings: list[dict[str, str]] = []
        config_error = _oauth_config_error(updated)
        if config_error:
            warnings.append({"level": "warning", "title": "OAuth設定", "message": config_error})
        recommended_redirect_uri = _recommended_callback_uri(updated)
        if updated.get("redirect_uri") and recommended_redirect_uri and updated["redirect_uri"] != recommended_redirect_uri:
            warnings.append(
                {
                    "level": "warning",
                    "title": "Redirect URI不一致",
                    "message": f"推奨値は {recommended_redirect_uri} です。Discord Developer Portal 側も完全一致させてください。",
                }
            )
        return JSONResponse(
            {
                "ok": True,
                "message": "基本設定を保存しました。",
                "warnings": warnings,
                "settings": updated,
                "recommended_redirect_uri": recommended_redirect_uri,
            }
        )

    @app.post("/api/admin/guilds/{guild_id}/settings")
    async def api_update_admin_guild_settings(request: Request, guild_id: int) -> JSONResponse:
        await _require_admin(request, container)
        payload = await request.json()
        current = await container.config_repo.get_guild_config(guild_id)
        guild = container.bot.get_guild(guild_id) if container.bot else None
        guild_name = current.guild_name if current else (guild.name if guild else str(guild_id))
        base_config = _build_guild_config_defaults(guild_id, guild_name, current)
        config = GuildConfig(
            guild_id=guild_id,
            guild_name=guild_name,
            managed_category_id=safe_int(payload["managed_category_id"]) or None if "managed_category_id" in payload else base_config.managed_category_id,
            base_voice_channel_id=safe_int(payload["base_voice_channel_id"]) or None if "base_voice_channel_id" in payload else base_config.base_voice_channel_id,
            notification_channel_id=safe_int(payload["notification_channel_id"]) or None if "notification_channel_id" in payload else base_config.notification_channel_id,
            first_empty_notice_sec=safe_int(payload.get("first_empty_notice_sec", base_config.first_empty_notice_sec), base_config.first_empty_notice_sec),
            final_delete_sec=safe_int(payload.get("final_delete_sec", base_config.final_delete_sec), base_config.final_delete_sec),
            solo_cleanup_mode=_normalize_solo_cleanup_mode(payload.get("solo_cleanup_mode", base_config.solo_cleanup_mode), base_config.solo_cleanup_mode),
            solo_notice_after_sec=max(60, safe_int(payload.get("solo_notice_after_sec", base_config.solo_notice_after_sec), base_config.solo_notice_after_sec)),
            solo_delete_warning_after_sec=max(60, safe_int(payload.get("solo_delete_warning_after_sec", base_config.solo_delete_warning_after_sec), base_config.solo_delete_warning_after_sec)),
            solo_repeat_notice_sec=max(300, safe_int(payload.get("solo_repeat_notice_sec", base_config.solo_repeat_notice_sec), base_config.solo_repeat_notice_sec)),
            ranking_post_enabled=bool(payload.get("ranking_post_enabled", base_config.ranking_post_enabled)),
            ranking_post_channel_id=safe_int(payload.get("ranking_post_channel_id", base_config.ranking_post_channel_id)) or None,
            ranking_post_frequencies=_normalize_ranking_frequencies(_list_payload(payload.get("ranking_post_frequencies", base_config.ranking_post_frequencies))),
            ranking_post_time=_normalize_hhmm(payload.get("ranking_post_time", base_config.ranking_post_time), base_config.ranking_post_time),
            ranking_post_targets=_normalize_ranking_targets(_list_payload(payload.get("ranking_post_targets", base_config.ranking_post_targets))),
            ranking_post_last_keys=base_config.ranking_post_last_keys.copy(),
            team_mode=str(payload.get("team_mode", base_config.team_mode)).strip() or base_config.team_mode,
            team_names=[name.strip() for name in str(payload.get("team_names", ",".join(base_config.team_names))).split(",") if name.strip()],
            enabled=bool(payload.get("enabled", base_config.enabled)),
        )
        await container.config_repo.upsert_guild_config(config)
        await container.session_manager.refresh_guild_configs()
        return JSONResponse(
            {
                "ok": True,
                "message": "サーバー設定を保存しました。",
                "diagnostics": _build_guild_diagnostics(container, guild_id, config),
                "config": {
                    "managed_category_id": config.managed_category_id,
                    "base_voice_channel_id": config.base_voice_channel_id,
                    "notification_channel_id": config.notification_channel_id,
                    "first_empty_notice_sec": config.first_empty_notice_sec,
                    "final_delete_sec": config.final_delete_sec,
                    "solo_cleanup_mode": config.solo_cleanup_mode,
                    "solo_notice_after_sec": config.solo_notice_after_sec,
                    "solo_delete_warning_after_sec": config.solo_delete_warning_after_sec,
                    "solo_repeat_notice_sec": config.solo_repeat_notice_sec,
                    "ranking_post_enabled": config.ranking_post_enabled,
                    "ranking_post_channel_id": config.ranking_post_channel_id,
                    "ranking_post_frequencies": config.ranking_post_frequencies,
                    "ranking_post_time": config.ranking_post_time,
                    "ranking_post_targets": config.ranking_post_targets,
                    "team_mode": config.team_mode,
                    "team_names": config.team_names,
                    "enabled": config.enabled,
                },
            }
        )

    @app.post("/api/admin/guilds/{guild_id}/rankings/post")
    async def api_post_admin_guild_rankings(request: Request, guild_id: int) -> JSONResponse:
        await _require_admin(request, container)
        sent = await container.session_manager.post_activity_rankings(guild_id, frequency="manual")
        if not sent:
            raise HTTPException(status_code=400, detail="Ranking post failed. Check ranking channel settings and bot permissions.")
        return JSONResponse({"ok": True, "message": "ランキングを手動投稿しました。"})

    @app.get("/api/me")
    async def api_me(request: Request) -> JSONResponse:
        profile = await _require_profile(request)
        return JSONResponse(
            {
                "user": {
                    "id": str(profile.user_id),
                    "username": profile.username,
                    "displayName": profile.display_name,
                    "avatarUrl": profile.avatar_url,
                },
                "isOwner": bool(request.session.get("is_owner")),
                "sharedGuildIds": [str(guild_id) for guild_id in request.session.get("shared_guild_ids", [])],
            }
        )

    @app.get("/api/ws-token")
    async def ws_token(request: Request) -> JSONResponse:
        profile = await _require_profile(request)
        return JSONResponse({"token": _sign_ws_token(app.state.ws_secret, profile.user_id)})

    @app.get("/api/notifications")
    async def api_notifications(request: Request, limit: int = 30) -> JSONResponse:
        profile = await _require_profile(request)
        safe_limit = max(1, min(100, safe_int(limit, 30)))
        notifications = await container.config_repo.list_notifications(profile.user_id, limit=safe_limit)
        unread_count = await container.config_repo.count_unread_notifications(profile.user_id)
        return JSONResponse({"notifications": notifications, "unread_count": unread_count})

    @app.post("/api/notifications/read-all")
    async def api_notifications_read_all(request: Request) -> JSONResponse:
        profile = await _require_profile(request)
        updated = await container.config_repo.mark_all_notifications_read(profile.user_id)
        unread_count = await container.config_repo.count_unread_notifications(profile.user_id)
        return JSONResponse({"ok": True, "updated": updated, "unread_count": unread_count})

    @app.post("/api/notifications/{notification_id}/read")
    async def api_notification_read(request: Request, notification_id: int) -> JSONResponse:
        profile = await _require_profile(request)
        updated = await container.config_repo.mark_notification_read(profile.user_id, notification_id)
        if not updated:
            raise HTTPException(status_code=404, detail="通知が見つかりません。")
        unread_count = await container.config_repo.count_unread_notifications(profile.user_id)
        return JSONResponse({"ok": True, "unread_count": unread_count})

    @app.delete("/api/notifications/{notification_id}")
    async def api_notification_delete(request: Request, notification_id: int) -> JSONResponse:
        profile = await _require_profile(request)
        deleted = await container.config_repo.delete_notification_for_user(profile.user_id, notification_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="通知が見つかりません。")
        unread_count = await container.config_repo.count_unread_notifications(profile.user_id)
        return JSONResponse({"ok": True, "unread_count": unread_count})

    @app.delete("/api/notifications")
    async def api_notifications_delete_all(request: Request) -> JSONResponse:
        await _require_admin(request, container)
        deleted = await container.config_repo.delete_all_notifications()
        return JSONResponse({"ok": True, "deleted": deleted, "unread_count": 0})

    async def _voice_state_payload(request: Request, guild_id: int, root_channel_id: int) -> JSONResponse:
        profile = await _require_profile(request)
        state = await _resolve_voice_dashboard_state(container, guild_id, root_channel_id)
        session = state["session"]
        container.logger.info(
            "[VC API] guild_id=%s vc_id=%s active_keys=%s channel=%s non_bot_members=%s session_found=%s restored=%s",
            safe_int(guild_id),
            safe_int(root_channel_id),
            container.session_manager.get_active_session_keys(),
            state["channel"].name if state["channel"] else None,
            len(state["non_bot_members"]),
            bool(session),
            bool(state.get("restored")),
        )
        if session is None and not state["non_bot_members"]:
            raise HTTPException(status_code=404, detail="このVCには現在アクティブなセッションがありません。")
        if session is None:
            member_ids = {member.id for member in state["non_bot_members"]}
            if profile.user_id not in member_ids and not await container.session_manager.is_guild_admin(guild_id, profile.user_id):
                raise HTTPException(status_code=403, detail="閲覧権限がありません。")
            payload = state["session_view"]
            payload["can_edit"] = await container.session_manager.is_guild_admin(guild_id, profile.user_id)
            payload["can_assign_others"] = False
            payload["management_url"] = state["management_url"]
            return JSONResponse(payload)
        if not await container.session_manager.can_view_session(session, profile.user_id):
            raise HTTPException(status_code=403, detail="閲覧権限がありません。")
        payload = state["session_view"]
        payload["can_edit"] = await container.session_manager.can_edit_session(session, profile.user_id)
        payload["can_assign_others"] = await container.session_manager.can_assign_others(session, profile.user_id)
        payload["management_url"] = state["management_url"]
        return JSONResponse(payload)

    @app.get("/api/voice/{guild_id}/{root_channel_id}")
    async def session_payload(request: Request, guild_id: int, root_channel_id: int) -> JSONResponse:
        return await _voice_state_payload(request, guild_id, root_channel_id)

    @app.get("/api/voice/{guild_id}/{root_channel_id}/state")
    async def session_state_payload(request: Request, guild_id: int, root_channel_id: int) -> JSONResponse:
        return await _voice_state_payload(request, guild_id, root_channel_id)

    @app.get("/api/voice/{guild_id}/{root_channel_id}/timeline")
    async def api_voice_timeline(
        request: Request,
        guild_id: int,
        root_channel_id: int,
        user_id: str | None = None,
        event_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> JSONResponse:
        profile = await _require_profile(request)
        guild_id, root_channel_id = normalize_ids(guild_id, root_channel_id)
        session = await container.session_manager.get_or_restore_session(guild_id, root_channel_id)
        if session is not None and not await container.session_manager.can_view_session(session, profile.user_id):
            raise HTTPException(status_code=403, detail="閲覧権限がありません。")
        filters = _build_timeline_query_params(user_id=user_id, event_type=event_type, date_from=date_from, date_to=date_to)
        rows = await container.stats_repo.list_timeline_events(
            session_id=session.session_id if session else None,
            guild_id=str(guild_id),
            root_channel_id=str(root_channel_id),
            user_id=filters["user_id"],
            event_type=filters["event_type"],
            date_from=filters["date_from"],
            date_to=filters["date_to"],
        )
        return JSONResponse({"events": _decorate_timeline_events(rows)})

    @app.post("/api/voice/{guild_id}/{root_channel_id}/settings")
    async def api_update_voice_settings(request: Request, guild_id: int, root_channel_id: int) -> JSONResponse:
        profile = await _require_profile(request)
        guild_id, root_channel_id = normalize_ids(guild_id, root_channel_id)
        session = await container.session_manager.get_or_restore_session(guild_id, root_channel_id)
        if session is None:
            raise HTTPException(status_code=404, detail="セッションが見つかりません。")
        if not await container.session_manager.can_edit_session(session, profile.user_id):
            raise HTTPException(status_code=403, detail="変更権限がありません。")
        payload = await request.json()
        await container.session_manager.update_voice_settings(
            root_channel_id=root_channel_id,
            name=str(payload.get("name")).strip() if payload.get("name") else None,
            user_limit=safe_int(payload.get("user_limit")) if payload.get("user_limit") is not None else None,
            bitrate=safe_int(payload.get("bitrate")) if payload.get("bitrate") is not None else None,
        )
        return JSONResponse({"ok": True})

    @app.post("/api/voice/{guild_id}/{root_channel_id}/access")
    async def api_update_voice_access(request: Request, guild_id: int, root_channel_id: int) -> JSONResponse:
        profile = await _require_profile(request)
        guild_id, root_channel_id = normalize_ids(guild_id, root_channel_id)
        session = await container.session_manager.get_or_restore_session(guild_id, root_channel_id)
        if session is None:
            raise HTTPException(status_code=404, detail="Session not found.")
        if not await container.session_manager.can_edit_session(session, profile.user_id):
            raise HTTPException(status_code=403, detail="Access control permission denied.")
        payload = await request.json()
        try:
            message = await container.session_manager.update_access_control(
                root_channel_id,
                profile.user_id,
                access_mode=str(payload.get("access_mode", "public")),
                invited_user_ids=[str(item).strip() for item in _list_payload(payload.get("invited_user_ids")) if str(item).strip()],
                access_role_ids=[str(item).strip() for item in _list_payload(payload.get("access_role_ids")) if str(item).strip()],
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "message": message})

    @app.post("/api/voice/{guild_id}/{root_channel_id}/member-state")
    async def api_member_state(request: Request, guild_id: int, root_channel_id: int) -> JSONResponse:
        profile = await _require_profile(request)
        guild_id, root_channel_id = normalize_ids(guild_id, root_channel_id)
        session = await container.session_manager.get_or_restore_session(guild_id, root_channel_id)
        if session is None:
            raise HTTPException(status_code=404, detail="セッションが見つかりません。")
        if not await container.session_manager.can_edit_session(session, profile.user_id):
            raise HTTPException(status_code=403, detail="変更権限がありません。")
        payload = await request.json()
        await container.session_manager.set_member_server_state(
            root_channel_id=root_channel_id,
            target_user_id=safe_int(payload.get("user_id")),
            mute=payload.get("mute"),
            deafen=payload.get("deafen"),
        )
        return JSONResponse({"ok": True})

    @app.post("/api/voice/{guild_id}/{root_channel_id}/team/assign")
    async def api_team_assign(request: Request, guild_id: int, root_channel_id: int) -> JSONResponse:
        profile = await _require_profile(request)
        guild_id, root_channel_id = normalize_ids(guild_id, root_channel_id)
        session = await container.session_manager.get_or_restore_session(guild_id, root_channel_id)
        if session is None:
            raise HTTPException(status_code=404, detail="セッションが見つかりません。")
        payload = await request.json()
        try:
            message = await container.session_manager.assign_team(
                root_channel_id,
                profile.user_id,
                safe_int(payload.get("user_id")),
                payload.get("team_name"),
            )
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "message": message})

    @app.post("/api/voice/{guild_id}/{root_channel_id}/team/split")
    async def api_team_split(request: Request, guild_id: int, root_channel_id: int) -> JSONResponse:
        profile = await _require_profile(request)
        guild_id, root_channel_id = normalize_ids(guild_id, root_channel_id)
        session = await container.session_manager.get_or_restore_session(guild_id, root_channel_id)
        if session is None:
            raise HTTPException(status_code=404, detail="セッションが見つかりません。")
        try:
            result = await container.session_manager.split_teams(root_channel_id, profile.user_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "result": result})

    @app.post("/api/voice/{guild_id}/{root_channel_id}/team/assemble")
    async def api_team_assemble(request: Request, guild_id: int, root_channel_id: int) -> JSONResponse:
        profile = await _require_profile(request)
        guild_id, root_channel_id = normalize_ids(guild_id, root_channel_id)
        session = await container.session_manager.get_or_restore_session(guild_id, root_channel_id)
        if session is None:
            raise HTTPException(status_code=404, detail="セッションが見つかりません。")
        try:
            result = await container.session_manager.assemble_teams(root_channel_id, profile.user_id)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "result": result})

    @app.post("/api/voice/{guild_id}/{root_channel_id}/team/recall")
    async def api_team_recall(request: Request, guild_id: int, root_channel_id: int) -> JSONResponse:
        profile = await _require_profile(request)
        guild_id, root_channel_id = normalize_ids(guild_id, root_channel_id)
        session = await container.session_manager.get_or_restore_session(guild_id, root_channel_id)
        if session is None:
            raise HTTPException(status_code=404, detail="セッションが見つかりません。")
        payload = await request.json()
        try:
            result = await container.session_manager.recall_member(root_channel_id, profile.user_id, safe_int(payload.get("user_id")))
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse({"ok": True, "result": result})

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket, token: str, scopes: str = "global") -> None:
        user_id = _verify_ws_token(app.state.ws_secret, token)
        if user_id is None:
            await websocket.close(code=4001)
            return
        requested_scopes = [item.strip() for item in scopes.split(",") if item.strip()]
        allowed_scopes: list[str] = []
        for scope in requested_scopes:
            if scope == "global":
                allowed_scopes.append(scope)
                continue
            if scope == f"user:{user_id}":
                allowed_scopes.append(scope)
                continue
            if scope.startswith("session:"):
                root_id = safe_int(scope.split(":", 1)[1])
                session = container.session_manager.get_session_by_root(root_id)
                if session and await container.session_manager.can_view_session(session, user_id):
                    allowed_scopes.append(scope)
                continue
            if scope.startswith("guild:"):
                guild_id = safe_int(scope.split(":", 1)[1])
                if await container.session_manager.is_guild_admin(guild_id, user_id):
                    allowed_scopes.append(scope)
                    continue
                for session in container.session_manager.list_sessions():
                    if session.guild_id == guild_id and await container.session_manager.can_view_session(session, user_id):
                        allowed_scopes.append(scope)
                        break
        if not allowed_scopes:
            await websocket.close(code=4003)
            return
        await container.websocket_hub.connect(websocket, allowed_scopes)
        try:
            while True:
                message = await websocket.receive_text()
                if message == "ping":
                    await websocket.send_text("pong")
        except WebSocketDisconnect:
            await container.websocket_hub.disconnect(websocket)
        except Exception:
            await container.websocket_hub.disconnect(websocket)

    @app.get("/{full_path:path}", response_model=None)
    async def spa_fallback(full_path: str) -> Response:
        if full_path.startswith(("api/", "static/", "assets/", "ws")):
            raise HTTPException(status_code=404)
        if not (spa_dir / "index.html").is_file():
            raise HTTPException(status_code=404)
        return serve_spa()

    return app
