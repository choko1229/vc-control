from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

from vc_control.models import CompletedMember, CompletedSession, GuildConfig, ScheduledVC, SessionSnapshot, SetupPayload
from vc_control.security import SecretBox
from vc_control.utils import from_iso, json_dumps, json_loads, period_cutoff, to_iso, utcnow


SQLITE_BUSY_TIMEOUT_MS = 5000
SQLITE_RETRY_DELAYS = (0.0, 0.2, 0.5, 1.0)


def _row_to_dict(row: aiosqlite.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def _is_database_locked_error(exc: Exception) -> bool:
    return "database is locked" in str(exc).lower()


async def _apply_sqlite_pragmas(db: aiosqlite.Connection) -> None:
    await db.execute("PRAGMA journal_mode=WAL;")
    await db.execute(f"PRAGMA busy_timeout={SQLITE_BUSY_TIMEOUT_MS};")
    await db.execute("PRAGMA synchronous=NORMAL;")
    await db.execute("PRAGMA foreign_keys=ON;")


@asynccontextmanager
async def _open_sqlite_connection(
    db_path: Path,
    *,
    row_factory: type[aiosqlite.Row] | None = None,
) -> Any:
    async with aiosqlite.connect(db_path, timeout=SQLITE_BUSY_TIMEOUT_MS / 1000) as db:
        if row_factory is not None:
            db.row_factory = row_factory
        await _apply_sqlite_pragmas(db)
        yield db


def _split_by_day(started_at: datetime, ended_at: datetime) -> list[tuple[date, int]]:
    result: list[tuple[date, int]] = []
    cursor = started_at
    while cursor < ended_at:
        next_day = datetime.combine(cursor.date() + timedelta(days=1), time.min, tzinfo=UTC)
        boundary = min(next_day, ended_at)
        seconds = int((boundary - cursor).total_seconds())
        result.append((cursor.date(), seconds))
        cursor = boundary
    return result


def _split_by_hour(started_at: datetime, ended_at: datetime) -> list[tuple[date, int, int]]:
    result: list[tuple[date, int, int]] = []
    cursor = started_at
    while cursor < ended_at:
        next_hour = (cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)).astimezone(UTC)
        boundary = min(next_hour, ended_at)
        seconds = int((boundary - cursor).total_seconds())
        result.append((cursor.date(), cursor.hour, seconds))
        cursor = boundary
    return result


class ConfigRepository:
    def __init__(self, db_path: Path, secret_box: SecretBox) -> None:
        self.db_path = db_path
        self.secret_box = secret_box
        self._write_lock = asyncio.Lock()

    async def _run_write(self, operation: Any) -> Any:
        async with self._write_lock:
            last_error: Exception | None = None
            for delay in SQLITE_RETRY_DELAYS:
                if delay:
                    await asyncio.sleep(delay)
                try:
                    async with _open_sqlite_connection(self.db_path) as db:
                        result = await operation(db)
                        await db.commit()
                        return result
                except Exception as exc:
                    if not _is_database_locked_error(exc):
                        raise
                    last_error = exc
            if last_error is not None:
                raise last_error
        return None

    async def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with _open_sqlite_connection(self.db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS app_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS secure_settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS guild_settings (
                    guild_id INTEGER PRIMARY KEY,
                    guild_name TEXT NOT NULL,
                    managed_category_id INTEGER,
                    base_voice_channel_id INTEGER,
                    notification_channel_id INTEGER,
                    first_empty_notice_sec INTEGER NOT NULL DEFAULT 30,
                    final_delete_sec INTEGER NOT NULL DEFAULT 90,
                    solo_cleanup_mode TEXT NOT NULL DEFAULT 'notify_only',
                    solo_notice_after_sec INTEGER NOT NULL DEFAULT 3600,
                    solo_delete_warning_after_sec INTEGER NOT NULL DEFAULT 1800,
                    solo_repeat_notice_sec INTEGER NOT NULL DEFAULT 3600,
                    ranking_post_enabled INTEGER NOT NULL DEFAULT 0,
                    ranking_post_channel_id INTEGER,
                    ranking_post_frequencies_json TEXT NOT NULL DEFAULT '[]',
                    ranking_post_time TEXT NOT NULL DEFAULT '21:00',
                    ranking_post_targets_json TEXT NOT NULL DEFAULT '["top_talkers", "top_hosts", "team_splits", "night_owls"]',
                    ranking_post_last_keys_json TEXT NOT NULL DEFAULT '{}',
                    team_mode TEXT NOT NULL DEFAULT 'custom',
                    team_names_json TEXT NOT NULL DEFAULT '["A", "B", "C", "D"]',
                    enabled INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS session_snapshots (
                    session_key TEXT PRIMARY KEY,
                    guild_id INTEGER NOT NULL,
                    root_channel_id INTEGER NOT NULL,
                    payload_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS error_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    level TEXT NOT NULL,
                    source TEXT NOT NULL,
                    message TEXT NOT NULL,
                    detail TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    message TEXT NOT NULL,
                    guild_id INTEGER,
                    root_channel_id INTEGER,
                    recipient_user_id INTEGER,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    read_at TEXT
                );
                CREATE TABLE IF NOT EXISTS notification_user_states (
                    notification_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    read_at TEXT,
                    deleted_at TEXT,
                    PRIMARY KEY(notification_id, user_id),
                    FOREIGN KEY(notification_id) REFERENCES notifications(id) ON DELETE CASCADE
                );
                CREATE TABLE IF NOT EXISTS scheduled_vcs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    guild_id INTEGER NOT NULL,
                    guild_name TEXT NOT NULL,
                    creator_user_id INTEGER NOT NULL,
                    creator_user_name TEXT NOT NULL,
                    vc_name TEXT NOT NULL,
                    category_id INTEGER,
                    user_limit INTEGER NOT NULL DEFAULT 0,
                    bitrate INTEGER,
                    mention_type TEXT NOT NULL DEFAULT 'none',
                    mention_targets_json TEXT NOT NULL DEFAULT '[]',
                    description TEXT NOT NULL DEFAULT '',
                    start_at TEXT NOT NULL,
                    end_at TEXT,
                    repeat_mode TEXT NOT NULL DEFAULT 'none',
                    repeat_weekdays_json TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_channel_id INTEGER,
                    pre_notice_15_sent INTEGER NOT NULL DEFAULT 0,
                    pre_notice_5_sent INTEGER NOT NULL DEFAULT 0,
                    pre_notice_3_sent INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_error_logs_created_at ON error_logs(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_guild_settings_enabled ON guild_settings(enabled);
                CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON notifications(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_notifications_recipient ON notifications(recipient_user_id, read_at);
                CREATE INDEX IF NOT EXISTS idx_notification_user_states_user ON notification_user_states(user_id, read_at, deleted_at);
                CREATE INDEX IF NOT EXISTS idx_scheduled_vcs_status_start ON scheduled_vcs(status, start_at);
                CREATE INDEX IF NOT EXISTS idx_scheduled_vcs_guild ON scheduled_vcs(guild_id, start_at);
                """
            )
            await self._ensure_guild_settings_columns(db)
            await db.commit()
        await self.purge_old_notifications(days=45)

    async def _ensure_guild_settings_columns(self, db: aiosqlite.Connection) -> None:
        cursor = await db.execute("PRAGMA table_info(guild_settings)")
        rows = await cursor.fetchall()
        existing = {str(row[1]) for row in rows}
        additions = {
            "solo_cleanup_mode": "TEXT NOT NULL DEFAULT 'notify_only'",
            "solo_notice_after_sec": "INTEGER NOT NULL DEFAULT 3600",
            "solo_delete_warning_after_sec": "INTEGER NOT NULL DEFAULT 1800",
            "solo_repeat_notice_sec": "INTEGER NOT NULL DEFAULT 3600",
            "ranking_post_enabled": "INTEGER NOT NULL DEFAULT 0",
            "ranking_post_channel_id": "INTEGER",
            "ranking_post_frequencies_json": "TEXT NOT NULL DEFAULT '[]'",
            "ranking_post_time": "TEXT NOT NULL DEFAULT '21:00'",
            "ranking_post_targets_json": "TEXT NOT NULL DEFAULT '[\"top_talkers\", \"top_hosts\", \"team_splits\", \"night_owls\"]'",
            "ranking_post_last_keys_json": "TEXT NOT NULL DEFAULT '{}'",
        }
        for column, definition in additions.items():
            if column not in existing:
                await db.execute(f"ALTER TABLE guild_settings ADD COLUMN {column} {definition}")

    async def _set_app_setting(self, key: str, value: str) -> None:
        now = to_iso(utcnow()) or ""
        async def operation(db: aiosqlite.Connection) -> None:
            await db.execute(
                """
                INSERT INTO app_settings(key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, now),
            )
        await self._run_write(operation)

    async def _set_secure_setting(self, key: str, value: str) -> None:
        now = to_iso(utcnow()) or ""
        encrypted = self.secret_box.encrypt(value)
        async def operation(db: aiosqlite.Connection) -> None:
            await db.execute(
                """
                INSERT INTO secure_settings(key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, encrypted, now),
            )
        await self._run_write(operation)

    async def save_initial_setup(self, payload: SetupPayload, session_secret: str) -> None:
        await self._set_secure_setting("bot_token", payload.bot_token)
        await self._set_secure_setting("client_secret", payload.client_secret)
        await self._set_secure_setting("session_secret", session_secret)

        plain_values = {
            "client_id": payload.client_id,
            "redirect_uri": payload.redirect_uri,
            "base_url": payload.base_url.rstrip("/"),
            "owner_user_id": str(payload.owner_user_id),
            "dashboard_host": payload.dashboard_host,
            "dashboard_port": str(payload.dashboard_port),
            "setup_completed": "1",
        }
        for key, value in plain_values.items():
            await self._set_app_setting(key, value)

    async def update_runtime_settings(
        self,
        plain_values: dict[str, str],
        secure_values: dict[str, str] | None = None,
    ) -> None:
        for key, value in plain_values.items():
            await self._set_app_setting(key, value)
        for key, value in (secure_values or {}).items():
            if value:
                await self._set_secure_setting(key, value)

    async def get_app_setting(self, key: str, default: str | None = None) -> str | None:
        async with _open_sqlite_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
            row = await cursor.fetchone()
        if row is None:
            return default
        return str(row["value"])

    async def get_secure_setting(self, key: str) -> str | None:
        async with _open_sqlite_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT value FROM secure_settings WHERE key = ?", (key,))
            row = await cursor.fetchone()
        if row is None:
            return None
        return self.secret_box.decrypt(str(row["value"]))

    async def is_setup_complete(self) -> bool:
        return (await self.get_app_setting("setup_completed", "0")) == "1"

    async def get_runtime_settings(self) -> dict[str, str]:
        keys = [
            "client_id",
            "redirect_uri",
            "base_url",
            "owner_user_id",
            "dashboard_host",
            "dashboard_port",
            "timeline_retention_days",
        ]
        secure_keys = ["bot_token", "client_secret", "session_secret"]
        values: dict[str, str] = {}
        for key in keys:
            values[key] = await self.get_app_setting(key, "") or ""
        for key in secure_keys:
            values[key] = await self.get_secure_setting(key) or ""
        return values

    async def sync_guild_catalog(self, guilds: list[tuple[int, str]]) -> None:
        now = to_iso(utcnow()) or ""
        async def operation(db: aiosqlite.Connection) -> None:
            for guild_id, guild_name in guilds:
                await db.execute(
                    """
                    INSERT INTO guild_settings(guild_id, guild_name, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(guild_id) DO UPDATE SET guild_name = excluded.guild_name
                    """,
                    (guild_id, guild_name, now),
                )
        await self._run_write(operation)

    async def list_guild_configs(self) -> list[GuildConfig]:
        async with _open_sqlite_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM guild_settings ORDER BY guild_name COLLATE NOCASE")
            rows = await cursor.fetchall()
        return [GuildConfig.from_record(_row_to_dict(row) or {}) for row in rows]

    async def get_guild_config(self, guild_id: int) -> GuildConfig | None:
        async with _open_sqlite_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))
            row = await cursor.fetchone()
        if row is None:
            return None
        return GuildConfig.from_record(_row_to_dict(row) or {})

    async def upsert_guild_config(self, config: GuildConfig) -> None:
        record = config.to_record()
        now = to_iso(utcnow()) or ""
        async def operation(db: aiosqlite.Connection) -> None:
            await db.execute(
                """
                INSERT INTO guild_settings(
                    guild_id, guild_name, managed_category_id, base_voice_channel_id,
                    notification_channel_id, first_empty_notice_sec, final_delete_sec,
                    solo_cleanup_mode, solo_notice_after_sec, solo_delete_warning_after_sec,
                    solo_repeat_notice_sec, ranking_post_enabled, ranking_post_channel_id,
                    ranking_post_frequencies_json, ranking_post_time, ranking_post_targets_json,
                    ranking_post_last_keys_json, team_mode, team_names_json, enabled, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    guild_name = excluded.guild_name,
                    managed_category_id = excluded.managed_category_id,
                    base_voice_channel_id = excluded.base_voice_channel_id,
                    notification_channel_id = excluded.notification_channel_id,
                    first_empty_notice_sec = excluded.first_empty_notice_sec,
                    final_delete_sec = excluded.final_delete_sec,
                    solo_cleanup_mode = excluded.solo_cleanup_mode,
                    solo_notice_after_sec = excluded.solo_notice_after_sec,
                    solo_delete_warning_after_sec = excluded.solo_delete_warning_after_sec,
                    solo_repeat_notice_sec = excluded.solo_repeat_notice_sec,
                    ranking_post_enabled = excluded.ranking_post_enabled,
                    ranking_post_channel_id = excluded.ranking_post_channel_id,
                    ranking_post_frequencies_json = excluded.ranking_post_frequencies_json,
                    ranking_post_time = excluded.ranking_post_time,
                    ranking_post_targets_json = excluded.ranking_post_targets_json,
                    ranking_post_last_keys_json = excluded.ranking_post_last_keys_json,
                    team_mode = excluded.team_mode,
                    team_names_json = excluded.team_names_json,
                    enabled = excluded.enabled,
                    updated_at = excluded.updated_at
                """,
                (
                    record["guild_id"],
                    record["guild_name"],
                    record["managed_category_id"],
                    record["base_voice_channel_id"],
                    record["notification_channel_id"],
                    record["first_empty_notice_sec"],
                    record["final_delete_sec"],
                    record["solo_cleanup_mode"],
                    record["solo_notice_after_sec"],
                    record["solo_delete_warning_after_sec"],
                    record["solo_repeat_notice_sec"],
                    record["ranking_post_enabled"],
                    record["ranking_post_channel_id"],
                    json_dumps(record["ranking_post_frequencies_json"]),
                    record["ranking_post_time"],
                    json_dumps(record["ranking_post_targets_json"]),
                    json_dumps(record["ranking_post_last_keys_json"]),
                    record["team_mode"],
                    json_dumps(record["team_names_json"]),
                    record["enabled"],
                    now,
                ),
            )
        await self._run_write(operation)

    async def update_ranking_post_last_keys(self, guild_id: int, last_keys: dict[str, str]) -> None:
        now = to_iso(utcnow()) or ""

        async def operation(db: aiosqlite.Connection) -> None:
            await db.execute(
                """
                UPDATE guild_settings
                SET ranking_post_last_keys_json = ?, updated_at = ?
                WHERE guild_id = ?
                """,
                (json_dumps(last_keys), now, guild_id),
            )

        await self._run_write(operation)

    async def save_session_snapshot(self, snapshot: SessionSnapshot) -> None:
        now = to_iso(utcnow()) or ""
        async def operation(db: aiosqlite.Connection) -> None:
            await db.execute(
                """
                INSERT INTO session_snapshots(session_key, guild_id, root_channel_id, payload_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_key) DO UPDATE SET
                    guild_id = excluded.guild_id,
                    root_channel_id = excluded.root_channel_id,
                    payload_json = excluded.payload_json,
                    updated_at = excluded.updated_at
                """,
                (
                    snapshot.session_id,
                    snapshot.guild_id,
                    snapshot.root_channel_id,
                    json_dumps(snapshot.to_dict()),
                    now,
                ),
            )
        await self._run_write(operation)

    async def list_session_snapshots(self) -> list[SessionSnapshot]:
        async with _open_sqlite_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT payload_json FROM session_snapshots")
            rows = await cursor.fetchall()
        snapshots: list[SessionSnapshot] = []
        for row in rows:
            payload = json_loads(row["payload_json"], {})
            if isinstance(payload, dict):
                snapshots.append(SessionSnapshot.from_dict(payload))
        return snapshots

    async def delete_session_snapshot(self, session_id: str) -> None:
        async def operation(db: aiosqlite.Connection) -> None:
            await db.execute("DELETE FROM session_snapshots WHERE session_key = ?", (session_id,))
        await self._run_write(operation)

    async def log_error(self, level: str, source: str, message: str, detail: str) -> None:
        created_at = to_iso(utcnow()) or ""
        async def operation(db: aiosqlite.Connection) -> None:
            await db.execute(
                """
                INSERT INTO error_logs(created_at, level, source, message, detail)
                VALUES (?, ?, ?, ?, ?)
                """,
                (created_at, level, source, message, detail),
            )
        await self._run_write(operation)

    async def get_error_logs(self, page: int = 1, per_page: int = 30) -> tuple[list[dict[str, Any]], int]:
        offset = max(0, (page - 1) * per_page)
        async with _open_sqlite_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            count_cursor = await db.execute("SELECT COUNT(*) AS total FROM error_logs")
            total_row = await count_cursor.fetchone()
            cursor = await db.execute(
                """
                SELECT * FROM error_logs
                ORDER BY id DESC
                LIMIT ? OFFSET ?
                """,
                (per_page, offset),
            )
            rows = await cursor.fetchall()
        total = int(total_row["total"]) if total_row else 0
        return ([_row_to_dict(row) or {} for row in rows], total)

    async def create_notification(
        self,
        *,
        event_type: str,
        title: str,
        message: str,
        guild_id: int | None = None,
        root_channel_id: int | None = None,
        recipient_user_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        created_at = to_iso(utcnow()) or ""

        async def operation(db: aiosqlite.Connection) -> int:
            cursor = await db.execute(
                """
                INSERT INTO notifications(
                    created_at, event_type, title, message, guild_id, root_channel_id,
                    recipient_user_id, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    event_type,
                    title,
                    message,
                    guild_id,
                    root_channel_id,
                    recipient_user_id,
                    json_dumps(payload or {}),
                ),
            )
            return int(cursor.lastrowid)

        notification_id = await self._run_write(operation)
        return {
            "id": str(notification_id),
            "created_at": created_at,
            "event_type": event_type,
            "title": title,
            "message": message,
            "guild_id": str(guild_id) if guild_id is not None else None,
            "root_channel_id": str(root_channel_id) if root_channel_id is not None else None,
            "recipient_user_id": str(recipient_user_id) if recipient_user_id is not None else None,
            "payload": payload or {},
            "read_at": None,
        }

    async def list_notifications(self, user_id: int, limit: int = 30) -> list[dict[str, Any]]:
        async with _open_sqlite_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT
                    n.*,
                    COALESCE(s.read_at, n.read_at) AS user_read_at,
                    s.deleted_at AS user_deleted_at
                FROM notifications n
                LEFT JOIN notification_user_states s
                    ON s.notification_id = n.id AND s.user_id = ?
                WHERE (n.recipient_user_id IS NULL OR n.recipient_user_id = ?)
                    AND s.deleted_at IS NULL
                ORDER BY n.id DESC
                LIMIT ?
                """,
                (user_id, user_id, limit),
            )
            rows = await cursor.fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = _row_to_dict(row) or {}
            item["id"] = str(item["id"])
            item["guild_id"] = str(item["guild_id"]) if item.get("guild_id") is not None else None
            item["root_channel_id"] = str(item["root_channel_id"]) if item.get("root_channel_id") is not None else None
            item["recipient_user_id"] = str(item["recipient_user_id"]) if item.get("recipient_user_id") is not None else None
            item["payload"] = json_loads(item.pop("payload_json", "{}"), {})
            item["read_at"] = item.pop("user_read_at", None)
            item.pop("user_deleted_at", None)
            result.append(item)
        return result

    async def count_unread_notifications(self, user_id: int) -> int:
        async with _open_sqlite_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT COUNT(*) AS total
                FROM notifications n
                LEFT JOIN notification_user_states s
                    ON s.notification_id = n.id AND s.user_id = ?
                WHERE COALESCE(s.read_at, n.read_at) IS NULL
                    AND s.deleted_at IS NULL
                    AND (n.recipient_user_id IS NULL OR n.recipient_user_id = ?)
                """,
                (user_id, user_id),
            )
            row = await cursor.fetchone()
        return int(row["total"]) if row else 0

    async def mark_notification_read(self, user_id: int, notification_id: int) -> bool:
        now = to_iso(utcnow()) or ""

        async def operation(db: aiosqlite.Connection) -> bool:
            cursor = await db.execute(
                """
                SELECT id
                FROM notifications
                WHERE id = ? AND (recipient_user_id IS NULL OR recipient_user_id = ?)
                """,
                (notification_id, user_id),
            )
            if await cursor.fetchone() is None:
                return False
            await db.execute(
                """
                INSERT INTO notification_user_states(notification_id, user_id, read_at)
                VALUES (?, ?, ?)
                ON CONFLICT(notification_id, user_id) DO UPDATE SET
                    read_at = excluded.read_at
                """,
                (notification_id, user_id, now),
            )
            return True

        return bool(await self._run_write(operation))

    async def mark_all_notifications_read(self, user_id: int) -> int:
        now = to_iso(utcnow()) or ""

        async def operation(db: aiosqlite.Connection) -> int:
            cursor = await db.execute(
                """
                SELECT n.id
                FROM notifications n
                LEFT JOIN notification_user_states s
                    ON s.notification_id = n.id AND s.user_id = ?
                WHERE (n.recipient_user_id IS NULL OR n.recipient_user_id = ?)
                    AND s.deleted_at IS NULL
                    AND COALESCE(s.read_at, n.read_at) IS NULL
                """,
                (user_id, user_id),
            )
            rows = await cursor.fetchall()
            notification_ids = [int(row[0]) for row in rows]
            for item_id in notification_ids:
                await db.execute(
                    """
                    INSERT INTO notification_user_states(notification_id, user_id, read_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(notification_id, user_id) DO UPDATE SET
                        read_at = excluded.read_at
                    """,
                    (item_id, user_id, now),
                )
            return len(notification_ids)

        return int(await self._run_write(operation) or 0)

    async def delete_notification_for_user(self, user_id: int, notification_id: int) -> bool:
        now = to_iso(utcnow()) or ""

        async def operation(db: aiosqlite.Connection) -> bool:
            cursor = await db.execute(
                """
                SELECT id
                FROM notifications
                WHERE id = ? AND (recipient_user_id IS NULL OR recipient_user_id = ?)
                """,
                (notification_id, user_id),
            )
            if await cursor.fetchone() is None:
                return False
            await db.execute(
                """
                INSERT INTO notification_user_states(notification_id, user_id, deleted_at)
                VALUES (?, ?, ?)
                ON CONFLICT(notification_id, user_id) DO UPDATE SET
                    deleted_at = excluded.deleted_at
                """,
                (notification_id, user_id, now),
            )
            return True

        return bool(await self._run_write(operation))

    async def delete_all_notifications(self) -> int:
        async def operation(db: aiosqlite.Connection) -> int:
            cursor = await db.execute("SELECT COUNT(*) AS total FROM notifications")
            row = await cursor.fetchone()
            total = int(row[0]) if row else 0
            await db.execute("DELETE FROM notification_user_states")
            await db.execute("DELETE FROM notifications")
            return total

        return int(await self._run_write(operation) or 0)

    async def purge_old_notifications(self, days: int = 45) -> int:
        cutoff = to_iso(utcnow() - timedelta(days=max(1, days))) or ""

        async def operation(db: aiosqlite.Connection) -> int:
            cursor = await db.execute("SELECT COUNT(*) AS total FROM notifications WHERE created_at < ?", (cutoff,))
            row = await cursor.fetchone()
            total = int(row[0]) if row else 0
            await db.execute("DELETE FROM notifications WHERE created_at < ?", (cutoff,))
            return total

        return int(await self._run_write(operation) or 0)

    async def create_scheduled_vc(self, scheduled: ScheduledVC) -> ScheduledVC:
        record = scheduled.to_record()
        now = to_iso(utcnow()) or ""

        async def operation(db: aiosqlite.Connection) -> int:
            cursor = await db.execute(
                """
                INSERT INTO scheduled_vcs(
                    created_at, updated_at, guild_id, guild_name, creator_user_id,
                    creator_user_name, vc_name, category_id, user_limit, bitrate,
                    mention_type, mention_targets_json, description, start_at, end_at,
                    repeat_mode, repeat_weekdays_json, status, created_channel_id,
                    pre_notice_15_sent, pre_notice_5_sent, pre_notice_3_sent
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    now,
                    now,
                    record["guild_id"],
                    record["guild_name"],
                    record["creator_user_id"],
                    record["creator_user_name"],
                    record["vc_name"],
                    record["category_id"],
                    record["user_limit"],
                    record["bitrate"],
                    record["mention_type"],
                    json_dumps(record["mention_targets_json"]),
                    record["description"],
                    record["start_at"],
                    record["end_at"],
                    record["repeat_mode"],
                    json_dumps(record["repeat_weekdays_json"]),
                    record["status"],
                    record["created_channel_id"],
                    record["pre_notice_15_sent"],
                    record["pre_notice_5_sent"],
                    record["pre_notice_3_sent"],
                ),
            )
            return int(cursor.lastrowid)

        scheduled.id = await self._run_write(operation)
        scheduled.created_at = from_iso(now)
        scheduled.updated_at = from_iso(now)
        return scheduled

    async def list_scheduled_vcs(self, guild_id: int | None = None, limit: int = 100) -> list[ScheduledVC]:
        clauses: list[str] = []
        params: list[Any] = []
        if guild_id is not None:
            clauses.append("guild_id = ?")
            params.append(guild_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        async with _open_sqlite_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                f"""
                SELECT *
                FROM scheduled_vcs
                {where}
                ORDER BY start_at ASC, id ASC
                LIMIT ?
                """,
                params,
            )
            rows = await cursor.fetchall()
        return [ScheduledVC.from_record(_row_to_dict(row) or {}) for row in rows]

    async def list_due_scheduled_vc_starts(self, now: datetime, limit: int = 20) -> list[ScheduledVC]:
        async with _open_sqlite_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT *
                FROM scheduled_vcs
                WHERE status = 'pending' AND start_at <= ?
                ORDER BY start_at ASC, id ASC
                LIMIT ?
                """,
                (to_iso(now), limit),
            )
            rows = await cursor.fetchall()
        return [ScheduledVC.from_record(_row_to_dict(row) or {}) for row in rows]

    async def list_active_scheduled_vcs(self) -> list[ScheduledVC]:
        async with _open_sqlite_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM scheduled_vcs WHERE status = 'active' ORDER BY end_at ASC, id ASC")
            rows = await cursor.fetchall()
        return [ScheduledVC.from_record(_row_to_dict(row) or {}) for row in rows]

    async def update_scheduled_vc_start_result(self, scheduled_id: int, *, channel_id: int, status: str) -> None:
        now = to_iso(utcnow()) or ""

        async def operation(db: aiosqlite.Connection) -> None:
            await db.execute(
                """
                UPDATE scheduled_vcs
                SET status = ?, created_channel_id = ?, updated_at = ?,
                    pre_notice_15_sent = 0, pre_notice_5_sent = 0, pre_notice_3_sent = 0
                WHERE id = ?
                """,
                (status, channel_id, now, scheduled_id),
            )

        await self._run_write(operation)

    async def update_scheduled_vc_status(self, scheduled_id: int, status: str) -> None:
        now = to_iso(utcnow()) or ""

        async def operation(db: aiosqlite.Connection) -> None:
            await db.execute("UPDATE scheduled_vcs SET status = ?, updated_at = ? WHERE id = ?", (status, now, scheduled_id))

        await self._run_write(operation)

    async def mark_scheduled_vc_pre_notice(self, scheduled_id: int, minutes: int) -> None:
        column = {15: "pre_notice_15_sent", 5: "pre_notice_5_sent", 3: "pre_notice_3_sent"}.get(minutes)
        if column is None:
            return
        now = to_iso(utcnow()) or ""

        async def operation(db: aiosqlite.Connection) -> None:
            await db.execute(f"UPDATE scheduled_vcs SET {column} = 1, updated_at = ? WHERE id = ?", (now, scheduled_id))

        await self._run_write(operation)

    async def delete_scheduled_vc(self, scheduled_id: int) -> None:
        async def operation(db: aiosqlite.Connection) -> None:
            await db.execute("DELETE FROM scheduled_vcs WHERE id = ?", (scheduled_id,))

        await self._run_write(operation)


class StatsRepository:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._write_lock = asyncio.Lock()

    async def _run_write(self, operation: Any) -> Any:
        async with self._write_lock:
            last_error: Exception | None = None
            for delay in SQLITE_RETRY_DELAYS:
                if delay:
                    await asyncio.sleep(delay)
                try:
                    async with _open_sqlite_connection(self.db_path) as db:
                        result = await operation(db)
                        await db.commit()
                        return result
                except Exception as exc:
                    if not _is_database_locked_error(exc):
                        raise
                    last_error = exc
            if last_error is not None:
                raise last_error
        return None

    async def initialize(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        async with _open_sqlite_connection(self.db_path) as db:
            await db.executescript(
                """
                CREATE TABLE IF NOT EXISTS vc_sessions (
                    session_id TEXT PRIMARY KEY,
                    guild_id INTEGER NOT NULL,
                    guild_name TEXT NOT NULL,
                    root_channel_id INTEGER NOT NULL,
                    root_channel_name TEXT NOT NULL,
                    started_by INTEGER NOT NULL,
                    started_by_name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    ended_at TEXT NOT NULL,
                    total_talk_seconds INTEGER NOT NULL,
                    total_afk_seconds INTEGER NOT NULL,
                    payload_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS session_members (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    guild_id INTEGER NOT NULL,
                    guild_name TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    user_name TEXT NOT NULL,
                    joined_at TEXT NOT NULL,
                    left_at TEXT NOT NULL,
                    talk_seconds INTEGER NOT NULL,
                    afk_seconds INTEGER NOT NULL,
                    afk_channel_seconds INTEGER NOT NULL,
                    self_mute_seconds INTEGER NOT NULL,
                    self_deafen_seconds INTEGER NOT NULL,
                    is_owner INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS user_totals (
                    guild_id INTEGER NOT NULL,
                    guild_name TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    user_name TEXT NOT NULL,
                    talk_seconds INTEGER NOT NULL,
                    afk_seconds INTEGER NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(guild_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS daily_user_stats (
                    date TEXT NOT NULL,
                    guild_id INTEGER NOT NULL,
                    guild_name TEXT NOT NULL,
                    user_id INTEGER NOT NULL,
                    user_name TEXT NOT NULL,
                    talk_seconds INTEGER NOT NULL,
                    afk_seconds INTEGER NOT NULL,
                    PRIMARY KEY(date, guild_id, user_id)
                );
                CREATE TABLE IF NOT EXISTS hourly_user_stats (
                    date TEXT NOT NULL,
                    guild_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    hour INTEGER NOT NULL,
                    talk_seconds INTEGER NOT NULL,
                    afk_seconds INTEGER NOT NULL,
                    PRIMARY KEY(date, guild_id, user_id, hour)
                );
                CREATE TABLE IF NOT EXISTS timeline_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    guild_id TEXT NOT NULL,
                    guild_name TEXT NOT NULL,
                    root_channel_id TEXT NOT NULL,
                    root_channel_name TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_label TEXT NOT NULL,
                    user_id TEXT,
                    user_name TEXT,
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_daily_user_stats_user ON daily_user_stats(user_id, date);
                CREATE INDEX IF NOT EXISTS idx_hourly_user_stats_user ON hourly_user_stats(user_id, date, hour);
                CREATE INDEX IF NOT EXISTS idx_session_members_user ON session_members(user_id, guild_id);
                CREATE INDEX IF NOT EXISTS idx_timeline_events_session ON timeline_events(session_id, created_at, id);
                CREATE INDEX IF NOT EXISTS idx_timeline_events_voice ON timeline_events(guild_id, root_channel_id, created_at);
                CREATE INDEX IF NOT EXISTS idx_timeline_events_type ON timeline_events(event_type, created_at);
                """
            )
            await db.commit()

    async def record_completed_session(self, session: CompletedSession) -> None:
        async def operation(db: aiosqlite.Connection) -> None:
            await db.execute(
                """
                INSERT OR REPLACE INTO vc_sessions(
                    session_id, guild_id, guild_name, root_channel_id, root_channel_name,
                    started_by, started_by_name, started_at, ended_at,
                    total_talk_seconds, total_afk_seconds, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session.session_id,
                    session.guild_id,
                    session.guild_name,
                    session.root_channel_id,
                    session.root_channel_name,
                    session.started_by,
                    session.started_by_name,
                    to_iso(session.started_at),
                    to_iso(session.ended_at),
                    session.total_talk_seconds,
                    session.total_afk_seconds,
                    json_dumps(session.payload),
                ),
            )

            for member in session.members:
                await db.execute(
                    """
                    INSERT INTO session_members(
                        session_id, guild_id, guild_name, user_id, user_name,
                        joined_at, left_at, talk_seconds, afk_seconds, afk_channel_seconds,
                        self_mute_seconds, self_deafen_seconds, is_owner
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        session.session_id,
                        session.guild_id,
                        session.guild_name,
                        member.user_id,
                        member.user_name,
                        to_iso(member.joined_at),
                        to_iso(member.left_at),
                        member.talk_seconds,
                        member.afk_seconds,
                        member.afk_channel_seconds,
                        member.self_mute_seconds,
                        member.self_deafen_seconds,
                        int(member.is_owner),
                    ),
                )

                await db.execute(
                    """
                    INSERT INTO user_totals(guild_id, guild_name, user_id, user_name, talk_seconds, afk_seconds, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(guild_id, user_id) DO UPDATE SET
                        guild_name = excluded.guild_name,
                        user_name = excluded.user_name,
                        talk_seconds = user_totals.talk_seconds + excluded.talk_seconds,
                        afk_seconds = user_totals.afk_seconds + excluded.afk_seconds,
                        updated_at = excluded.updated_at
                    """,
                    (
                        session.guild_id,
                        session.guild_name,
                        member.user_id,
                        member.user_name,
                        member.talk_seconds,
                        member.afk_seconds,
                        to_iso(utcnow()),
                    ),
                )

                await self._upsert_rollups(db, session.guild_id, session.guild_name, member)
        await self._run_write(operation)

    async def _upsert_rollups(
        self,
        db: aiosqlite.Connection,
        guild_id: int,
        guild_name: str,
        member: CompletedMember,
    ) -> None:
        total_seconds = max(1, int((member.left_at - member.joined_at).total_seconds()))
        talk_ratio = member.talk_seconds / total_seconds
        afk_ratio = member.afk_seconds / total_seconds

        for target_date, seconds in _split_by_day(member.joined_at, member.left_at):
            talk_seconds = int(seconds * talk_ratio)
            afk_seconds = int(seconds * afk_ratio)
            await db.execute(
                """
                INSERT INTO daily_user_stats(date, guild_id, guild_name, user_id, user_name, talk_seconds, afk_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date, guild_id, user_id) DO UPDATE SET
                    guild_name = excluded.guild_name,
                    user_name = excluded.user_name,
                    talk_seconds = daily_user_stats.talk_seconds + excluded.talk_seconds,
                    afk_seconds = daily_user_stats.afk_seconds + excluded.afk_seconds
                """,
                (
                    target_date.isoformat(),
                    guild_id,
                    guild_name,
                    member.user_id,
                    member.user_name,
                    talk_seconds,
                    afk_seconds,
                ),
            )

        for target_date, hour, seconds in _split_by_hour(member.joined_at, member.left_at):
            talk_seconds = int(seconds * talk_ratio)
            afk_seconds = int(seconds * afk_ratio)
            await db.execute(
                """
                INSERT INTO hourly_user_stats(date, guild_id, user_id, hour, talk_seconds, afk_seconds)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(date, guild_id, user_id, hour) DO UPDATE SET
                    talk_seconds = hourly_user_stats.talk_seconds + excluded.talk_seconds,
                    afk_seconds = hourly_user_stats.afk_seconds + excluded.afk_seconds
                """,
                (target_date.isoformat(), guild_id, member.user_id, hour, talk_seconds, afk_seconds),
            )

    async def get_recent_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        async with _open_sqlite_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT * FROM vc_sessions
                ORDER BY ended_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = await cursor.fetchall()
        return [_row_to_dict(row) or {} for row in rows]

    async def get_completed_session(self, session_id: str) -> dict[str, Any] | None:
        async with _open_sqlite_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute("SELECT * FROM vc_sessions WHERE session_id = ?", (session_id,))
            row = await cursor.fetchone()
        return _row_to_dict(row)

    async def record_timeline_event(
        self,
        *,
        session_id: str,
        guild_id: str,
        guild_name: str,
        root_channel_id: str,
        root_channel_name: str,
        event_type: str,
        event_label: str,
        message: str,
        user_id: str | None = None,
        user_name: str | None = None,
        payload: dict[str, Any] | None = None,
        retention_days: int | None = None,
    ) -> dict[str, Any]:
        created_at = to_iso(utcnow()) or ""

        async def operation(db: aiosqlite.Connection) -> int:
            cursor = await db.execute(
                """
                INSERT INTO timeline_events(
                    created_at, session_id, guild_id, guild_name, root_channel_id,
                    root_channel_name, event_type, event_label, user_id, user_name,
                    message, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    session_id,
                    guild_id,
                    guild_name,
                    root_channel_id,
                    root_channel_name,
                    event_type,
                    event_label,
                    user_id,
                    user_name,
                    message,
                    json_dumps(payload or {}),
                ),
            )
            if retention_days and retention_days > 0:
                cutoff = to_iso(utcnow() - timedelta(days=retention_days))
                await db.execute("DELETE FROM timeline_events WHERE created_at < ?", (cutoff,))
            return int(cursor.lastrowid)

        event_id = await self._run_write(operation)
        return {
            "id": str(event_id),
            "created_at": created_at,
            "session_id": session_id,
            "guild_id": guild_id,
            "guild_name": guild_name,
            "root_channel_id": root_channel_id,
            "root_channel_name": root_channel_name,
            "event_type": event_type,
            "event_label": event_label,
            "user_id": user_id,
            "user_name": user_name,
            "message": message,
            "payload": payload or {},
        }

    async def list_timeline_events(
        self,
        *,
        session_id: str | None = None,
        guild_id: str | None = None,
        root_channel_id: str | None = None,
        user_id: str | None = None,
        event_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if guild_id:
            clauses.append("guild_id = ?")
            params.append(guild_id)
        if root_channel_id:
            clauses.append("root_channel_id = ?")
            params.append(root_channel_id)
        if user_id:
            clauses.append("user_id = ?")
            params.append(user_id)
        if event_type:
            clauses.append("event_type = ?")
            params.append(event_type)
        if date_from:
            clauses.append("created_at >= ?")
            params.append(date_from)
        if date_to:
            clauses.append("created_at <= ?")
            params.append(date_to)
        query = "SELECT * FROM timeline_events"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY created_at ASC, id ASC LIMIT ?"
        params.append(max(1, min(500, int(limit))))
        async with _open_sqlite_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, tuple(params))
            rows = await cursor.fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = _row_to_dict(row) or {}
            item["id"] = str(item["id"])
            item["guild_id"] = str(item["guild_id"])
            item["root_channel_id"] = str(item["root_channel_id"])
            item["user_id"] = str(item["user_id"]) if item.get("user_id") is not None else None
            item["payload"] = json_loads(item.pop("payload_json", "{}"), {})
            result.append(item)
        return result

    async def get_rankings(
        self,
        period: str = "all",
        guild_id: int | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        cutoff = period_cutoff(period)
        async with _open_sqlite_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if cutoff is None:
                params: list[Any] = []
                query = """
                    SELECT guild_id, guild_name, user_id, user_name,
                           SUM(talk_seconds) AS talk_seconds,
                           SUM(afk_seconds) AS afk_seconds
                    FROM user_totals
                """
                if guild_id is not None:
                    query += " WHERE guild_id = ?"
                    params.append(guild_id)
                query += """
                    GROUP BY guild_id, guild_name, user_id, user_name
                    ORDER BY talk_seconds DESC, afk_seconds ASC
                    LIMIT ?
                """
                params.append(limit)
                cursor = await db.execute(query, tuple(params))
            else:
                params = [cutoff.isoformat()]
                query = """
                    SELECT guild_id, guild_name, user_id, user_name,
                           SUM(talk_seconds) AS talk_seconds,
                           SUM(afk_seconds) AS afk_seconds
                    FROM daily_user_stats
                    WHERE date >= ?
                """
                if guild_id is not None:
                    query += " AND guild_id = ?"
                    params.append(guild_id)
                query += """
                    GROUP BY guild_id, guild_name, user_id, user_name
                    ORDER BY talk_seconds DESC, afk_seconds ASC
                    LIMIT ?
                """
                params.append(limit)
                cursor = await db.execute(query, tuple(params))
            rows = await cursor.fetchall()
        result: list[dict[str, Any]] = []
        for index, row in enumerate(rows, start=1):
            item = _row_to_dict(row) or {}
            item["rank"] = index
            item["effective_seconds"] = max(0, int(item["talk_seconds"]) - int(item["afk_seconds"]))
            result.append(item)
        return result

    async def get_activity_ranking_bundle(self, guild_id: int, period: str = "day", limit: int = 5) -> dict[str, list[dict[str, Any]]]:
        today = utcnow().date().isoformat()
        cutoff = period_cutoff(period) or utcnow().date()
        cutoff_text = cutoff.isoformat()
        async with _open_sqlite_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            top_talkers_cursor = await db.execute(
                """
                SELECT guild_id, guild_name, user_id, user_name,
                       SUM(talk_seconds) AS talk_seconds,
                       SUM(afk_seconds) AS afk_seconds
                FROM daily_user_stats
                WHERE guild_id = ? AND date = ?
                GROUP BY guild_id, guild_name, user_id, user_name
                ORDER BY talk_seconds DESC, afk_seconds ASC
                LIMIT ?
                """,
                (guild_id, today, limit),
            )
            top_hosts_cursor = await db.execute(
                """
                SELECT started_by AS user_id, started_by_name AS user_name,
                       COUNT(*) AS session_count,
                       MAX(guild_name) AS guild_name,
                       MAX(guild_id) AS guild_id,
                       SUM(member_count) AS gathered_count
                FROM (
                    SELECT s.session_id, s.guild_id, s.guild_name, s.started_by, s.started_by_name,
                           COUNT(DISTINCT m.user_id) AS member_count
                    FROM vc_sessions s
                    LEFT JOIN session_members m ON m.session_id = s.session_id
                    WHERE s.guild_id = ? AND date(s.started_at) >= ?
                    GROUP BY s.session_id, s.guild_id, s.guild_name, s.started_by, s.started_by_name
                )
                GROUP BY user_id, user_name
                ORDER BY gathered_count DESC, session_count DESC
                LIMIT ?
                """,
                (guild_id, cutoff_text, limit),
            )
            team_splits_cursor = await db.execute(
                """
                SELECT user_id, user_name, guild_id, guild_name, COUNT(*) AS split_count
                FROM timeline_events
                WHERE guild_id = ? AND event_type = 'teams_split' AND date(created_at) >= ?
                GROUP BY user_id, user_name, guild_id, guild_name
                ORDER BY split_count DESC
                LIMIT ?
                """,
                (str(guild_id), cutoff_text, limit),
            )
            night_owls_cursor = await db.execute(
                """
                SELECT h.guild_id, d.guild_name, h.user_id, d.user_name,
                       SUM(h.talk_seconds) AS talk_seconds,
                       SUM(h.afk_seconds) AS afk_seconds
                FROM hourly_user_stats h
                LEFT JOIN daily_user_stats d ON d.guild_id = h.guild_id AND d.user_id = h.user_id AND d.date = h.date
                WHERE h.guild_id = ? AND h.date >= ? AND h.hour BETWEEN 0 AND 4
                GROUP BY h.guild_id, h.user_id
                ORDER BY talk_seconds DESC, afk_seconds ASC
                LIMIT ?
                """,
                (guild_id, cutoff_text, limit),
            )
            top_talkers = await top_talkers_cursor.fetchall()
            top_hosts = await top_hosts_cursor.fetchall()
            team_splits = await team_splits_cursor.fetchall()
            night_owls = await night_owls_cursor.fetchall()

        def decorate(rows: list[aiosqlite.Row]) -> list[dict[str, Any]]:
            result: list[dict[str, Any]] = []
            for index, row in enumerate(rows, start=1):
                item = _row_to_dict(row) or {}
                item["rank"] = index
                result.append(item)
            return result

        return {
            "top_talkers": decorate(top_talkers),
            "top_hosts": decorate(top_hosts),
            "team_splits": decorate(team_splits),
            "night_owls": decorate(night_owls),
        }

    async def get_user_period_summary(self, user_id: int, period: str = "all") -> dict[str, Any]:
        cutoff = period_cutoff(period)
        async with _open_sqlite_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if cutoff is None:
                cursor = await db.execute(
                    """
                    SELECT
                        COALESCE(SUM(talk_seconds), 0) AS talk_seconds,
                        COALESCE(SUM(afk_seconds), 0) AS afk_seconds
                    FROM user_totals
                    WHERE user_id = ?
                    """,
                    (user_id,),
                )
            else:
                cursor = await db.execute(
                    """
                    SELECT
                        COALESCE(SUM(talk_seconds), 0) AS talk_seconds,
                        COALESCE(SUM(afk_seconds), 0) AS afk_seconds
                    FROM daily_user_stats
                    WHERE user_id = ? AND date >= ?
                    """,
                    (user_id, cutoff.isoformat()),
                )
            row = await cursor.fetchone()
        payload = _row_to_dict(row) or {"talk_seconds": 0, "afk_seconds": 0}
        payload["effective_seconds"] = max(0, int(payload["talk_seconds"]) - int(payload["afk_seconds"]))
        return payload

    async def get_user_guild_breakdown(self, user_id: int, period: str = "all") -> list[dict[str, Any]]:
        cutoff = period_cutoff(period)
        async with _open_sqlite_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            if cutoff is None:
                cursor = await db.execute(
                    """
                    SELECT guild_id, guild_name,
                           SUM(talk_seconds) AS talk_seconds,
                           SUM(afk_seconds) AS afk_seconds
                    FROM user_totals
                    WHERE user_id = ?
                    GROUP BY guild_id, guild_name
                    ORDER BY talk_seconds DESC
                    """,
                    (user_id,),
                )
            else:
                cursor = await db.execute(
                    """
                    SELECT guild_id, guild_name,
                           SUM(talk_seconds) AS talk_seconds,
                           SUM(afk_seconds) AS afk_seconds
                    FROM daily_user_stats
                    WHERE user_id = ? AND date >= ?
                    GROUP BY guild_id, guild_name
                    ORDER BY talk_seconds DESC
                    """,
                    (user_id, cutoff.isoformat()),
                )
            rows = await cursor.fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            item = _row_to_dict(row) or {}
            item["effective_seconds"] = max(0, int(item["talk_seconds"]) - int(item["afk_seconds"]))
            result.append(item)
        return result

    async def get_user_daily_chart(self, user_id: int, guild_id: int | None = None, days: int = 30) -> list[dict[str, Any]]:
        cutoff = (utcnow().date() - timedelta(days=days - 1)).isoformat()
        params: list[Any] = [user_id, cutoff]
        query = """
            SELECT date, SUM(talk_seconds) AS talk_seconds, SUM(afk_seconds) AS afk_seconds
            FROM daily_user_stats
            WHERE user_id = ? AND date >= ?
        """
        if guild_id is not None:
            query += " AND guild_id = ?"
            params.append(guild_id)
        query += " GROUP BY date ORDER BY date ASC"
        async with _open_sqlite_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, tuple(params))
            rows = await cursor.fetchall()
        return [_row_to_dict(row) or {} for row in rows]

    async def get_user_hourly_heatmap(self, user_id: int, guild_id: int | None = None, days: int = 60) -> list[dict[str, Any]]:
        cutoff = (utcnow().date() - timedelta(days=days - 1)).isoformat()
        params: list[Any] = [user_id, cutoff]
        query = """
            SELECT hour, SUM(talk_seconds) AS talk_seconds, SUM(afk_seconds) AS afk_seconds
            FROM hourly_user_stats
            WHERE user_id = ? AND date >= ?
        """
        if guild_id is not None:
            query += " AND guild_id = ?"
            params.append(guild_id)
        query += " GROUP BY hour ORDER BY hour ASC"
        async with _open_sqlite_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(query, tuple(params))
            rows = await cursor.fetchall()
        return [_row_to_dict(row) or {} for row in rows]

    async def get_known_guilds_for_user(self, user_id: int) -> list[dict[str, Any]]:
        async with _open_sqlite_connection(self.db_path) as db:
            db.row_factory = aiosqlite.Row
            cursor = await db.execute(
                """
                SELECT guild_id, guild_name,
                       SUM(talk_seconds) AS talk_seconds,
                       SUM(afk_seconds) AS afk_seconds
                FROM user_totals
                WHERE user_id = ?
                GROUP BY guild_id, guild_name
                ORDER BY guild_name COLLATE NOCASE
                """,
                (user_id,),
            )
            rows = await cursor.fetchall()
        return [_row_to_dict(row) or {} for row in rows]
