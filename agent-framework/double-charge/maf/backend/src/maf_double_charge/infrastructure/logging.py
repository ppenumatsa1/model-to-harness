from __future__ import annotations

import hashlib
import logging
import re
import sys
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from opentelemetry import trace
from pythonjsonlogger.json import JsonFormatter

_context: ContextVar[dict[str, Any] | None] = ContextVar("maf_log_context", default=None)
_CORRELATION_KEYS = frozenset({"case_id", "run_id", "conversation_id", "response_id"})
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_TOKEN = re.compile(r"[A-Za-z0-9_.-]{1,120}\Z")
_HTTP_METHODS = frozenset(
    {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "CONNECT", "TRACE"}
)
_EVENTS = frozenset(
    {
        "run.started",
        "run.completed",
        "run.failed",
        "node.started",
        "node.completed",
        "edge.selected",
        "tool.call.started",
        "tool.call.succeeded",
        "tool.call.failed",
        "tool.call.retried",
        "checkpoint.created",
        "approval.requested",
        "approval.recorded",
        "approval.resolved",
        "refund.idempotency.lookup",
        "refund.verification",
        "workflow.resumed",
        "telemetry.configured",
        "telemetry.flush_failed",
        "telemetry.shutdown_failed",
        "http.request.completed",
    }
)
_STANDARD_FIELDS = frozenset(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}
_HANDLER_MARKER = "_maf_safe_console"


def correlation_id(value: str) -> str:
    """Produce a stable, non-raw join key; this is pseudonymization, not anonymization."""
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def safe_log_attributes(values: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in _CORRELATION_KEYS:
        value = values.get(key)
        if isinstance(value, str) and value:
            result[key] = value if _DIGEST.fullmatch(value) else correlation_id(value)
    for key in ("node", "error.type"):
        value = values.get(key)
        if isinstance(value, str) and _TOKEN.fullmatch(value):
            result[key] = value
    transition = values.get("transition")
    if isinstance(transition, str) and re.fullmatch(r"[a-z_]{1,60}->[a-z_]{1,60}", transition):
        result["transition"] = transition
    attempt = values.get("retry_attempt")
    if type(attempt) is int and 0 <= attempt <= 100:
        result["retry_attempt"] = attempt
    event = values.get("event_type")
    if isinstance(event, str) and event in _EVENTS:
        result["event_type"] = event
    method = values.get("http.request.method")
    if isinstance(method, str):
        result["http.request.method"] = method if method in _HTTP_METHODS else "_OTHER"
    status = values.get("http.response.status_code")
    if type(status) is int and 100 <= status <= 599:
        result["http.response.status_code"] = status
    for key, size in (("trace_id", 32), ("span_id", 16)):
        value = values.get(key)
        if isinstance(value, str) and re.fullmatch(rf"[0-9a-f]{{{size}}}", value):
            result[key] = value
    return result


def current_log_context() -> dict[str, Any]:
    return dict(_context.get() or {})


class ContextFilter(logging.Filter):
    """Allowlist the complete record, including messages, extras and exception bodies."""

    def filter(self, record: logging.LogRecord) -> bool:
        values = {**record.__dict__, **current_log_context()}
        if record.name == "uvicorn.access":
            values["event_type"] = "http.request.completed"
            if isinstance(record.args, tuple) and len(record.args) == 5:
                values["http.request.method"] = record.args[1]
                values["http.response.status_code"] = record.args[4]
        safe = safe_log_attributes(values)
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            safe["trace_id"] = f"{span_context.trace_id:032x}"
            safe["span_id"] = f"{span_context.span_id:016x}"
        if record.exc_info and record.exc_info[0]:
            safe["error.type"] = record.exc_info[0].__name__
        for key in list(record.__dict__):
            if key not in _STANDARD_FIELDS:
                del record.__dict__[key]
        record.__dict__.update(safe)
        record.msg = safe.get("event_type", "Operational event (details suppressed)")
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        record.__dict__.pop("message", None)
        return True


def protect_log_handlers() -> None:
    """Protect existing platform/export handlers without replacing or closing them."""
    access_formatter = getattr(sys.modules.get("uvicorn.logging"), "AccessFormatter", None)
    loggers = [logging.getLogger()]
    loggers.extend(
        value
        for value in logging.Logger.manager.loggerDict.values()
        if isinstance(value, logging.Logger)
    )
    for logger in loggers:
        for handler in logger.handlers:
            if isinstance(access_formatter, type) and isinstance(
                handler.formatter, access_formatter
            ):
                # AccessFormatter unpacks raw request arguments; redaction removes them.
                handler.setFormatter(
                    JsonFormatter(
                        "%(asctime)s %(levelname)s %(name)s %(message)s "
                        "%(http.request.method)s %(http.response.status_code)s"
                    )
                )
            if not any(isinstance(value, ContextFilter) for value in handler.filters):
                handler.addFilter(ContextFilter())


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if not any(getattr(handler, _HANDLER_MARKER, False) for handler in root.handlers):
        handler = logging.StreamHandler()
        setattr(handler, _HANDLER_MARKER, True)
        handler.setFormatter(
            JsonFormatter(
                "%(asctime)s %(levelname)s %(name)s %(message)s "
                "%(case_id)s %(run_id)s %(conversation_id)s %(response_id)s "
                "%(node)s %(transition)s %(retry_attempt)s %(trace_id)s %(span_id)s",
            )
        )
        root.addHandler(handler)
    protect_log_handlers()
    root.setLevel(level.upper())


def bind_log_context(**values: Any) -> None:
    _context.set({**current_log_context(), **safe_log_attributes(values)})


def clear_log_context() -> None:
    _context.set(None)


@contextmanager
def log_context(**values: Any):
    token = _context.set({**current_log_context(), **safe_log_attributes(values)})
    try:
        yield
    finally:
        _context.reset(token)
