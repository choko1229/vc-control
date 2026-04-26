from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from vc_control.bot import VoiceControlBot
from vc_control.repositories import ConfigRepository, StatsRepository
from vc_control.runtime import SessionManager, WebSocketHub


@dataclass(slots=True)
class AppContainer:
    root_dir: Path
    data_dir: Path
    config_repo: ConfigRepository
    stats_repo: StatsRepository
    websocket_hub: WebSocketHub
    session_manager: SessionManager
    logger: object
    bot: VoiceControlBot | None = None
