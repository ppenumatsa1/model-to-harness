import logging
import sys

from pythonjsonlogger.json import JsonFormatter

SAFE_LOG_FIELDS = (
    "asctime",
    "levelname",
    "name",
    "message",
    "case_id",
    "run_id",
    "node",
    "transition",
    "checkpoint_id",
    "retry_count",
    "idempotency_key_hash",
)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(" ".join(f"%({field})s" for field in SAFE_LOG_FIELDS)))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
