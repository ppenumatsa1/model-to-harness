import logging
import sys

from pythonjsonlogger.json import JsonFormatter

SAFE_LOG_FIELDS = (
    "levelname",
    "name",
    "message",
    "case_id_hash",
    "run_id_hash",
    "node",
    "retry_count",
    "idempotency_key_hash",
    "error_type",
)


class SafeLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        safe_message = getattr(record, "safe_event", record.msg)
        allowed = {
            "runtime_log",
            "audit_readiness_failed",
            "storage_readiness_failed",
            "node_started",
            "model_call_started",
            "model_call_completed",
            "tool_call_started",
            "tool_call_succeeded",
            "tool_call_failed",
            "tool_call_retried",
            "decision_summary",
            "parallel_branch_started",
            "parallel_branch_completed",
            "parallel_branch_joined",
            "checkpoint_created",
            "human_approval_requested",
            "human_approval_resolved",
            "refund_idempotency_lookup",
            "refund_verification",
            "run_completed",
            "run_failed",
        }
        record.msg = (
            safe_message
            if isinstance(safe_message, str) and safe_message in allowed
            else "runtime_log"
        )
        record.message = record.msg
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        standard = logging.makeLogRecord({}).__dict__
        for key in tuple(record.__dict__):
            if key not in standard and key not in SAFE_LOG_FIELDS:
                del record.__dict__[key]
        return True


def configure_logging(level: str = "INFO", *, hosted: bool = False) -> None:
    root = logging.getLogger()
    if not hosted and not any(getattr(h, "_langgraph_owned", False) for h in root.handlers):
        handler = logging.StreamHandler(sys.stdout)
        handler._langgraph_owned = True
        handler.setFormatter(JsonFormatter(" ".join(f"%({field})s" for field in SAFE_LOG_FIELDS)))
        root.addHandler(handler)
    loggers = [root]
    while loggers:
        logger = loggers.pop()
        loggers.extend(logger.getChildren())
        for handler in logger.handlers:
            if not any(isinstance(f, SafeLogFilter) for f in handler.filters):
                handler.addFilter(SafeLogFilter())
    root.setLevel(level.upper())
