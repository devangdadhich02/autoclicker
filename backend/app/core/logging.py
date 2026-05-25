from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path
from typing import Any

import structlog
from structlog.types import EventDict, WrappedLogger

from app.core.config import settings


def _add_app_context(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    event_dict["app"] = settings.APP_NAME
    event_dict["env"] = settings.APP_ENV
    return event_dict


def _drop_color_message_key(
    logger: WrappedLogger, method_name: str, event_dict: EventDict
) -> EventDict:
    event_dict.pop("color_message", None)
    return event_dict


def configure_logging() -> None:
    log_dir: Path = settings.LOG_DIR
    log_dir.mkdir(parents=True, exist_ok=True)

    log_level = getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        _add_app_context,
        _drop_color_message_key,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    json_formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.processors.JSONRenderer(),
        foreign_pre_chain=shared_processors,
    )

    console_formatter = structlog.stdlib.ProcessorFormatter(
        processor=structlog.dev.ConsoleRenderer(colors=True),
        foreign_pre_chain=shared_processors,
    )

    # Rotating JSON file handler
    file_handler = logging.handlers.RotatingFileHandler(
        filename=log_dir / "app.log",
        maxBytes=settings.LOG_MAX_BYTES,
        backupCount=settings.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(json_formatter)

    # Error-only rotating file handler
    error_handler = logging.handlers.RotatingFileHandler(
        filename=log_dir / "error.log",
        maxBytes=settings.LOG_MAX_BYTES,
        backupCount=settings.LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(json_formatter)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(
        console_formatter if settings.is_development else json_formatter
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)
    root_logger.handlers.clear()
    root_logger.addHandler(file_handler)
    root_logger.addHandler(error_handler)
    root_logger.addHandler(console_handler)

    # Silence noisy libraries
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
