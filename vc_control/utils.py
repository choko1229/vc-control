from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import TypeVar


def utcnow() -> datetime:
    return datetime.now(tz=UTC)


def to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(UTC).isoformat()


def from_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value).astimezone(UTC)


def format_duration(seconds: float | int) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}時間{minutes}分{secs}秒"
    if minutes:
        return f"{minutes}分{secs}秒"
    return f"{secs}秒"


def json_dumps(value: object) -> str:
    import json

    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def json_loads(value: str | None, default: object) -> object:
    import json

    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def period_cutoff(period: str) -> date | None:
    today = utcnow().date()
    if period == "day":
        return today
    if period == "week":
        return today - timedelta(days=6)
    if period == "month":
        return today - timedelta(days=29)
    if period == "year":
        return today - timedelta(days=364)
    return None


def clamp(value: int, minimum: int, maximum: int) -> int:
    return max(minimum, min(value, maximum))


def safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


T = TypeVar("T")


def chunked(items: Iterable[T], size: int) -> list[list[T]]:
    bucket: list[T] = []
    result: list[list[T]] = []
    for item in items:
        bucket.append(item)
        if len(bucket) == size:
            result.append(bucket)
            bucket = []
    if bucket:
        result.append(bucket)
    return result
