from __future__ import annotations

import logging
from contextvars import ContextVar
from typing import Any

from pythonjsonlogger.json import JsonFormatter

_context: ContextVar[dict[str, Any] | None] = ContextVar("log_context", default=None)


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in (_context.get() or {}).items():
            setattr(record, key, value)
        return True


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s "
            "%(case_id)s %(run_id)s %(node)s %(transition)s %(checkpoint_id)s "
            "%(retry_attempt)s %(idempotency_key)s",
            defaults={
                "case_id": None,
                "run_id": None,
                "node": None,
                "transition": None,
                "checkpoint_id": None,
                "retry_attempt": None,
                "idempotency_key": None,
            },
        )
    )
    handler.addFilter(ContextFilter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())


def bind_log_context(**values: Any) -> None:
    _context.set({**(_context.get() or {}), **values})


def clear_log_context() -> None:
    _context.set(None)
