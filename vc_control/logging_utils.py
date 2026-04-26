from __future__ import annotations

import asyncio
import logging
from pathlib import Path


def configure_logging(log_path: Path) -> logging.Logger:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(log_path, encoding="utf-8"),
        ],
    )
    logger = logging.getLogger("vc_control")
    logger.setLevel(logging.INFO)
    return logger


class DatabaseLogHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)
        self.writer: object | None = None

    def bind(self, writer: object) -> None:
        self.writer = writer

    def emit(self, record: logging.LogRecord) -> None:
        if self.writer is None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        source = record.name
        message = record.getMessage()
        detail = logging.Formatter().formatException(record.exc_info) if record.exc_info else ""
        loop.create_task(self._write(source, message, detail))

    async def _write(self, source: str, message: str, detail: str) -> None:
        writer = self.writer
        if writer is None:
            return
        log_error = getattr(writer, "log_error", None)
        if log_error is None:
            return
        await log_error("ERROR", source, message, detail)
