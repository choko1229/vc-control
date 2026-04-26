from __future__ import annotations

import asyncio
import os
import secrets
from logging import Logger
from pathlib import Path

import uvicorn

from vc_control.bootstrap import AppContainer
from vc_control.bot import build_bot
from vc_control.logging_utils import DatabaseLogHandler, configure_logging
from vc_control.repositories import ConfigRepository, StatsRepository
from vc_control.runtime import SessionManager, WebSocketHub
from vc_control.security import SecretBox
from vc_control.web import create_app


def _read_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _resolve_bind_host(settings: dict[str, str]) -> tuple[str, str]:
    env_host = _read_env("DASHBOARD_HOST")
    if env_host:
        return env_host, "env:DASHBOARD_HOST"

    configured_host = (settings.get("dashboard_host") or "").strip()
    if configured_host and configured_host not in {"127.0.0.1", "localhost"}:
        return configured_host, "config.db:dashboard_host"

    return "0.0.0.0", "default"


def _resolve_bind_port(settings: dict[str, str]) -> tuple[int, str]:
    for env_name in ("SERVER_PORT", "PORT", "DASHBOARD_PORT"):
        env_value = _read_env(env_name)
        if env_value is None:
            continue
        try:
            return int(env_value), f"env:{env_name}"
        except ValueError:
            continue

    configured_port = (settings.get("dashboard_port") or "").strip()
    if configured_port:
        try:
            return int(configured_port), "config.db:dashboard_port"
        except ValueError:
            pass

    return 49162, "default"


def _ensure_setup_password(setup_complete: bool, logger: Logger) -> None:
    if setup_complete:
        return

    existing_password = _read_env("SETUP_PASSWORD")
    if existing_password:
        return

    generated_password = secrets.token_urlsafe(24)
    os.environ["SETUP_PASSWORD"] = generated_password

    banner = "\n".join(
        [
            "============================================================",
            "初回セットアップ用パスワード",
            f"SETUP_PASSWORD: {generated_password}",
            "このパスワードは初回セットアップ完了まで有効です。",
            "============================================================",
        ]
    )
    print(banner, flush=True)
    logger.info("初回セットアップ未完了のため SETUP_PASSWORD を自動生成しました。Pterodactyl コンソールの表示を確認してください。")


async def async_main() -> None:
    root_dir = Path(__file__).resolve().parent
    data_dir = root_dir / "data"
    logger = configure_logging(data_dir / "app.log")

    secret_box = SecretBox(data_dir / "secret.key")
    config_repo = ConfigRepository(data_dir / "config.db", secret_box)
    stats_repo = StatsRepository(data_dir / "stats.db")
    websocket_hub = WebSocketHub()
    session_manager = SessionManager(config_repo=config_repo, stats_repo=stats_repo, websocket_hub=websocket_hub, logger=logger)
    container = AppContainer(
        root_dir=root_dir,
        data_dir=data_dir,
        config_repo=config_repo,
        stats_repo=stats_repo,
        websocket_hub=websocket_hub,
        session_manager=session_manager,
        logger=logger,
    )

    await config_repo.initialize()
    await stats_repo.initialize()

    db_handler = DatabaseLogHandler()
    db_handler.bind(config_repo)
    logger.addHandler(db_handler)

    settings = await config_repo.get_runtime_settings()
    if settings.get("session_secret"):
        os.environ["SESSION_SECRET_FALLBACK"] = settings["session_secret"]

    setup_complete = await config_repo.is_setup_complete()
    _ensure_setup_password(setup_complete, logger)

    host, host_source = _resolve_bind_host(settings)
    port, port_source = _resolve_bind_port(settings)
    app = create_app(container)

    server = uvicorn.Server(
        uvicorn.Config(
            app=app,
            host=host,
            port=port,
            log_config=None,
            access_log=False,
            loop="asyncio",
        )
    )

    tasks: list[asyncio.Task[None]] = [asyncio.create_task(server.serve())]
    logger.info("Webサーバーのbind先: %s:%s (host=%s, port=%s)", host, port, host_source, port_source)

    if setup_complete and settings.get("bot_token"):
        bot = build_bot(session_manager, logger)
        container.bot = bot
        tasks.append(asyncio.create_task(bot.start(settings["bot_token"])))
        logger.info("WebサーバーとDiscord Botを起動します: %s:%s", host, port)
    else:
        logger.info("初回セットアップモードでWebサーバーのみ起動します: %s:%s", host, port)

    try:
        await asyncio.gather(*tasks)
    finally:
        if container.bot is not None and not container.bot.is_closed():
            await container.bot.close()


if __name__ == "__main__":
    asyncio.run(async_main())
