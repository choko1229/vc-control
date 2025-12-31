import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
import json

# Always place the DB next to this module so it is found regardless of CWD.
DB_PATH = Path(__file__).with_name("vc_sessions.db")
# Older builds stored the DB at the repository root; keep a reference so we can
# migrate existing data if present.
LEGACY_DB_PATH = Path("vc_sessions.db")


def _get_conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    """テーブルがなければ作成"""
    if LEGACY_DB_PATH.exists() and not DB_PATH.exists():
        try:
            DB_PATH.write_bytes(LEGACY_DB_PATH.read_bytes())
        except Exception:
            pass

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS vc_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            guild_id INTEGER NOT NULL,
            vc_id INTEGER NOT NULL,
            vc_name TEXT NOT NULL,
            started_at TEXT NOT NULL,  -- ISO形式
            ended_at TEXT NOT NULL,
            duration_sec INTEGER NOT NULL,
            participants_json TEXT NOT NULL  -- {user_id: {name, total_sec}} のJSON
        )
        """
    )
    conn.commit()
    conn.close()


def insert_session(
    guild_id: int,
    vc_id: int,
    vc_name: str,
    started_at: datetime,
    ended_at: datetime,
    participants: dict,
):
    """VCセッション1件を保存"""
    duration_sec = int((ended_at - started_at).total_seconds())

    # joined_at は履歴には不要なので total_sec だけにしておく
    clean_participants = {}
    for uid, p in participants.items():
        clean_participants[str(uid)] = {
            "name": p.get("name", f"UID:{uid}"),
            "total_sec": int(p.get("total_sec", 0)),
        }

    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO vc_sessions
            (guild_id, vc_id, vc_name, started_at, ended_at, duration_sec, participants_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            int(guild_id),
            int(vc_id),
            vc_name,
            started_at.isoformat(),
            ended_at.isoformat(),
            duration_sec,
            json.dumps(clean_participants, ensure_ascii=False),
        ),
    )
    conn.commit()
    conn.close()


def get_sessions_by_guild(guild_id: int, limit: int = 50):
    """ギルドごとのセッション履歴を新しい順に取得"""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, vc_id, vc_name, started_at, ended_at, duration_sec, participants_json
        FROM vc_sessions
        WHERE guild_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (int(guild_id), int(limit)),
    )
    rows = cur.fetchall()
    conn.close()

    sessions = []
    for row in rows:
        sid, vc_id, vc_name, started_at, ended_at, duration_sec, participants_json = row
        try:
            participants = json.loads(participants_json)
        except Exception:
            participants = {}
        sessions.append(
            {
                "id": sid,
                "vc_id": vc_id,
                "vc_name": vc_name,
                "started_at": started_at,
                "ended_at": ended_at,
                "duration_sec": duration_sec,
                "participants": participants,
            }
        )
    return sessions


def get_usage_for_user(user_id: int, days: int = 7):
    """参加者として記録されたセッションから利用傾向を集計"""
    conn = _get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT vc_name, started_at, ended_at, participants_json
        FROM vc_sessions
        ORDER BY id DESC
        """
    )
    rows = cur.fetchall()
    conn.close()

    total_seconds = 0
    daily = {}
    hourly = [0 for _ in range(24)]

    cutoff = datetime.utcnow() - timedelta(days=days - 1)

    for row in rows:
        vc_name, started_at, ended_at, participants_json = row
        try:
            participants = json.loads(participants_json)
        except Exception:
            continue

        pdata = participants.get(str(user_id))
        if not pdata:
            continue

        try:
            started_dt = datetime.fromisoformat(started_at)
            ended_dt = datetime.fromisoformat(ended_at)
        except Exception:
            continue

        duration = int(pdata.get("total_sec", 0))
        total_seconds += duration

        if started_dt >= cutoff:
            day_key = started_dt.date()
            daily.setdefault(day_key, 0)
            daily[day_key] += duration

        try:
            hour = int(started_dt.hour)
            hourly[hour] += duration
        except Exception:
            pass

    # 整形して返却（欠損日は0で埋める）
    daily_points = []
    for i in range(days):
        day = (datetime.utcnow() - timedelta(days=days - 1 - i)).date()
        val = daily.get(day, 0)
        daily_points.append({"label": f"{day.month}/{day.day}", "seconds": val})

    return {
        "total_seconds": total_seconds,
        "daily": daily_points,
        "hourly": hourly,
    }


# モジュール import 時にテーブルを準備
init_db()
