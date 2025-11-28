import sqlite3
from pathlib import Path
from datetime import datetime
import json

DB_PATH = Path("vc_sessions.db")


def _get_conn():
    return sqlite3.connect(DB_PATH)


def init_db():
    """テーブルがなければ作成"""
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


# モジュール import 時にテーブルを準備
init_db()
