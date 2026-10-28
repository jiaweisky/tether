"""Configuration helpers for JSON or human-readable structured logging."""

from __future__ import annotations

import logging
from typing import Any

import structlog

_configured = False


def configure_logging(level: str = "INFO", json: bool = True) -> None:
    """Configure structlog once; safe to call repeatedly."""
    global _configured
    if _configured:
        return
    numeric_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(level=numeric_level, format="%(message)s")
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if json:
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
    _configured = True


def get_logger(name: str = "tether"):
    """Return a structlog logger; call ``configure_logging`` before first use."""
    return structlog.get_logger(name)
