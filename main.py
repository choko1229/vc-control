from __future__ import annotations

import asyncio
import os
from pathlib import Path

import uvicorn

from vc_control.bootstrap import AppContainer
from vc_control.bot import build_bot
from vc_control.logging_utils import DatabaseLogHandler, configure_logging
from vc_control.repositories import ConfigRepository, StatsRepository
from vc_control.runtime import SessionManager, WebSocketHub
from vc_control.security import SecretBox
from vc_control.web import create_app


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

    host = settings.get("dashboard_host") or "127.0.0.1"
    port = int(settings.get("dashboard_port") or 8000)
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

    if await config_repo.is_setup_complete() and settings.get("bot_token"):
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
