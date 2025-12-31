"""
settings.json を読み込んで Bot やダッシュボード用の設定を提供するモジュール。
README の設定手順に沿って settings-template.json を複製して使用してください。
"""

import json
from pathlib import Path
from urllib.parse import urlparse

CONFIG_PATH = Path(__file__).with_name("settings.json")


def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(
            "settings.json が見つかりません。settings-template.json をコピーして値を設定してください。"
        )

    try:
        with CONFIG_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise ValueError(f"settings.json の読み込みに失敗しました: {e}") from e


def _require(config: dict, key: str):
    if key not in config:
        raise KeyError(f"settings.json に {key} が設定されていません。")
    value = config[key]
    if value in (None, ""):
        raise ValueError(f"settings.json の {key} が空です。")
    return value


def _require_int(config: dict, key: str) -> int:
    value = _require(config, key)
    try:
        return int(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"settings.json の {key} は数値で指定してください。") from e


def _require_str(config: dict, key: str) -> str:
    value = _require(config, key)
    return str(value)


def _optional_str(config: dict, key: str, default: str | None = None) -> str:
    value = config.get(key, default)
    if value is None:
        return ""
    return str(value)


def _derive_base_url_from_redirect(redirect_uri: str) -> str:
    parsed = urlparse(redirect_uri)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme}://{parsed.netloc}"
    return ""


_config = _load_config()

# Discord Bot Token / VC 基本設定
TOKEN = _require_str(_config, "TOKEN")
BASE_VC_ID = _require_int(_config, "BASE_VC_ID")
VC_CATEGORY_ID = _require_int(_config, "VC_CATEGORY_ID")
NOTICE_CHANNEL_ID = _require_int(_config, "NOTICE_CHANNEL_ID")

# 無人VC → 通知 → 削除
FIRST_EMPTY_NOTICE_SEC = _require_int(_config, "FIRST_EMPTY_NOTICE_SEC")
FINAL_DELETE_SEC = _require_int(_config, "FINAL_DELETE_SEC")

# ダッシュボード / OAuth2 設定
DISCORD_CLIENT_ID = _require_str(_config, "DISCORD_CLIENT_ID")
DISCORD_CLIENT_SECRET = _require_str(_config, "DISCORD_CLIENT_SECRET")
DISCORD_REDIRECT_URI = _require_str(_config, "DISCORD_REDIRECT_URI")
DASHBOARD_SESSION_SECRET = _require_str(_config, "DASHBOARD_SESSION_SECRET")
DASHBOARD_BASE_URL = _optional_str(
    _config, "DASHBOARD_BASE_URL", _derive_base_url_from_redirect(DISCORD_REDIRECT_URI)
).rstrip("/") or _derive_base_url_from_redirect(DISCORD_REDIRECT_URI)
