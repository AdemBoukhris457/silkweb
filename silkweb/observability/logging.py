from __future__ import annotations

import logging
import sys
from typing import Any, Literal

import structlog

from ..config import SilkwebConfig, get_config

LogFormat = Literal["json", "text"]

_CONFIGURED = False


def configure_logging(cfg: SilkwebConfig | None = None) -> None:
    """
    Configure structlog according to SilkwebConfig.
    Idempotent and safe to call multiple times.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    cfg = cfg or get_config()
    level = getattr(logging, str(cfg.log_level or "WARNING").upper(), logging.WARNING)
    logging.basicConfig(level=level, stream=sys.stderr, format="%(message)s")

    pre_chain = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    fmt: LogFormat = "json" if str(cfg.log_format).lower() == "json" else "text"
    if fmt == "json":
        renderer: Any = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *pre_chain,
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            renderer,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )
    _CONFIGURED = True


def log_event(event: str, **fields: Any) -> None:
    """
    Emit a normalized event. Missing recommended fields are included as None.
    """
    configure_logging()
    base = {
        "url": fields.pop("url", None),
        "tier": fields.pop("tier", None),
        "duration_ms": fields.pop("duration_ms", None),
        "model": fields.pop("model", None),
        "cache_hit": fields.pop("cache_hit", None),
        "error": fields.pop("error", None),
    }
    structlog.get_logger("silkweb").info(event, **base, **fields)
