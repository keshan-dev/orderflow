"""Structured JSON logs.

Every line is 1 JSON object with the service name plus any context fields set with
`log_context` (for example order_id and event_id), so logs can be searched by order.
"""

import contextlib
import contextvars
import json
import logging
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

_context: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("log_context", default={})  # noqa: B039

_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        line: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "service": self._service,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        line.update(_context.get())
        # Fields passed with logger.info("...", extra={...}) are added as top-level keys.
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                line[key] = value
        if record.exc_info:
            line["error"] = self.formatException(record.exc_info)
        return json.dumps(line, default=str)


def configure_logging(service: str, level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


@contextlib.contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    """Add fields to every log line written inside this block (and its threads' copies)."""
    token = _context.set({**_context.get(), **fields})
    try:
        yield
    finally:
        _context.reset(token)
