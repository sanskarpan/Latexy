"""
Logging configuration.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict

from .config import settings
from .observability import get_log_context
from .tracing import current_trace_context

_REDACT_KEYS = {
    "authorization",
    "cookie",
    "password",
    "token",
    "secret",
    "api_key",
    "access_token",
    "refresh_token",
}


def _sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: ("[redacted]" if key.lower() in _REDACT_KEYS else _sanitize(item))
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(item) for item in value]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class ContextFilter(logging.Filter):
    """Inject request/task correlation context into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in get_log_context().items():
            setattr(record, key, value)
        for key, value in current_trace_context().items():
            setattr(record, key, value)
        return True


class JsonFormatter(logging.Formatter):
    """Emit structured JSON logs suitable for ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        payload: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "module": record.module,
        }
        for key in ("request_id", "route", "task_id", "task_name", "job_id", "queue", "trace_id", "span_id"):
            value = getattr(record, key, None)
            if value:
                payload[key] = value
        for key in ("method", "status_code", "latency_seconds", "user_id", "resume_id", "event_name", "metric_name", "route_name", "otel_mode", "otel_endpoint", "component"):
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(_sanitize(payload), ensure_ascii=True)


def setup_logging() -> None:
    """Configure application logging."""
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ContextFilter())
    root_logger.addHandler(handler)

    loggers_config: Dict[str, Dict[str, Any]] = {
        "uvicorn": {"level": "INFO"},
        "uvicorn.error": {"level": "INFO"},
        "uvicorn.access": {"level": "WARNING"},
        "fastapi": {"level": "INFO"},
    }

    for logger_name, config in loggers_config.items():
        logger = logging.getLogger(logger_name)
        logger.setLevel(getattr(logging, config["level"]))
        logger.handlers.clear()
        logger.propagate = True


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance."""
    return logging.getLogger(name)
