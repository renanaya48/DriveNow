"""Central logging configuration: console + rotating file.

Configured once at startup. Every module then uses ``logging.getLogger(__name__)``.
Step 7 extends this (structured fields, per-action helpers); the transport setup
below is the stable base.
"""

from __future__ import annotations

import logging
from logging.config import dictConfig
from pathlib import Path

from app.core.config import Settings

_configured = False


def configure_logging(settings: Settings) -> None:
    """Install console + rotating-file handlers on the root logger.

    Idempotent: safe to call from both the app lifespan and the MQ consumer.
    """
    global _configured
    if _configured:
        return

    log_path = Path(settings.log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "standard": {
                    "format": "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
                    "datefmt": "%Y-%m-%dT%H:%M:%S%z",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "standard",
                    "level": settings.log_level,
                },
                "file": {
                    "class": "logging.handlers.RotatingFileHandler",
                    "formatter": "standard",
                    "level": settings.log_level,
                    "filename": str(log_path),
                    "maxBytes": 5 * 1024 * 1024,
                    "backupCount": 3,
                    "encoding": "utf-8",
                },
            },
            "root": {
                "level": settings.log_level,
                "handlers": ["console", "file"],
            },
        }
    )

    _configured = True
    logging.getLogger(__name__).info(
        "Logging configured (level=%s, file=%s)", settings.log_level, log_path
    )
