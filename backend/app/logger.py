# ============================================================
# Yuno Agent Platform — Structured Logging Configuration
# Uses structlog for machine-readable JSON logs in production,
# human-readable console output in development.
# ============================================================
from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import EventDict, Processor


def add_app_context(logger: Any, method: str, event_dict: EventDict) -> EventDict:
    """Inject application-level context into every log entry."""
    event_dict["service"] = "yuno-backend"
    return event_dict


def setup_logging(log_level: str = "INFO", json_logs: bool = False) -> None:
    """
    Configure structlog + stdlib logging.

    In development: pretty colored console output.
    In production: JSON lines for log aggregation (DataDog, CloudWatch, etc).

    Design decision: structlog over plain logging because:
    - Structured key=value context (execution_id, agent_id, etc)
    - Easy to add context with bind_contextvars()
    - Machine-parseable in production
    """
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        add_app_context,
    ]

    if json_logs:
        # Production: JSON for log aggregation
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    else:
        # Development: Pretty console output
        processors = shared_processors + [
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(log_level.upper())
        ),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Also configure stdlib logging for third-party libraries
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=logging.getLevelName(log_level.upper()),
    )

    # Silence noisy loggers
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.BoundLogger:
    """Get a named logger with application context pre-bound."""
    return structlog.get_logger(name)
