from contextlib import AbstractAsyncContextManager, AbstractContextManager
from typing import Any, Protocol

from .records import EventData, NativeEvent

SAFE_EVENT_DATA_KEYS = {
    "attempt",
    "branch",
    "checkpoint_id",
    "decision",
    "eligible",
    "failure_code",
    "latency_ms",
    "model",
    "refund_id",
    "retry_in_ms",
    "route",
    "tool",
    "tool_call_id",
    "usage",
    "verified_count",
}


def safe_event_data(data: dict[str, Any] | None) -> dict[str, Any]:
    if not data:
        return {}
    return EventData.model_validate(data).model_dump(exclude_unset=True)


class ApprovalCommandConflictError(ValueError):
    pass


class RefundIdempotencyConflictError(ValueError):
    pass


class CommandInProgressError(ValueError):
    pass


class AuditRepository(Protocol):
    def command_lock(self, case_id: str) -> AbstractAsyncContextManager[None]: ...

    async def ping(self) -> bool: ...

    async def create_run(self, record: dict[str, Any]) -> None: ...

    async def update_run(self, run_id: str, updates: dict[str, Any]) -> None: ...

    async def get_run_by_case(self, case_id: str) -> dict[str, Any] | None: ...

    async def append_event(
        self,
        *,
        case_id: str,
        run_id: str,
        event_type: str,
        summary: str,
        node: str | None = None,
        status: str | None = None,
        data: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
    ) -> NativeEvent: ...

    async def list_events(self, run_id: str, after: int = 0) -> list[NativeEvent]: ...

    async def save_approval(self, run_id: str, approval: dict[str, Any]) -> None: ...

    async def get_approval(self, run_id: str) -> dict[str, Any] | None: ...

    async def get_pending_approval(self, run_id: str) -> dict[str, Any] | None: ...

    async def consume_approval(self, run_id: str) -> None: ...

    async def get_refund(self, idempotency_key: str) -> dict[str, Any] | None: ...

    async def record_refund(self, refund: dict[str, Any]) -> dict[str, Any]: ...

    async def upsert_memory(
        self, customer_id: str, case_id: str, facts: dict[str, Any]
    ) -> None: ...

    async def get_memory(self, customer_id: str, case_id: str) -> dict[str, Any]: ...


class WorkflowRunner(Protocol):
    def trace_run(self, run_id: str, *, case_id: str, command: str) -> AbstractContextManager: ...

    async def start(self, state: dict[str, Any]) -> dict[str, Any]: ...
    async def resume(self, run_id: str, decision: dict[str, Any]) -> dict[str, Any]: ...
    async def continue_run(self, run_id: str) -> dict[str, Any]: ...
    async def snapshot(self, run_id: str) -> dict[str, Any] | None: ...


def _approval_identity(approval: dict[str, Any]) -> tuple[Any, ...]:
    return (
        approval.get("checkpoint_id"),
        approval.get("decision"),
        approval.get("reviewer_id"),
        approval.get("reason"),
    )
