import asyncio
from collections import defaultdict
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ..application.ports import (
    ApprovalCommandConflictError,
    CommandInProgressError,
    RefundIdempotencyConflictError,
    _approval_identity,
    safe_event_data,
)
from ..application.records import NativeEvent


class InMemoryAuditRepository:
    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self.case_to_run: dict[str, str] = {}
        self.events: dict[str, list[NativeEvent]] = defaultdict(list)
        self.approvals: dict[str, dict[str, Any]] = {}
        self.refunds: dict[str, dict[str, Any]] = {}
        self.memories: dict[tuple[str, str], dict[str, Any]] = {}
        self._dedupe: dict[tuple[str, str], NativeEvent] = {}
        self._lock = asyncio.Lock()
        self._commands: set[str] = set()

    @asynccontextmanager
    async def command_lock(self, case_id: str):
        if case_id in self._commands:
            raise CommandInProgressError("Another command is executing for this case")
        self._commands.add(case_id)
        try:
            yield
        finally:
            self._commands.remove(case_id)

    async def setup(self) -> None:
        return None

    async def ping(self) -> bool:
        return True

    async def create_run(self, record: dict[str, Any]) -> None:
        async with self._lock:
            self.runs[record["run_id"]] = deepcopy(record)
            self.case_to_run[record["case_id"]] = record["run_id"]

    async def update_run(self, run_id: str, updates: dict[str, Any]) -> None:
        async with self._lock:
            self.runs[run_id].update(deepcopy(updates))

    async def get_run_by_case(self, case_id: str) -> dict[str, Any] | None:
        run_id = self.case_to_run.get(case_id)
        return deepcopy(self.runs.get(run_id)) if run_id else None

    async def append_event(self, **kwargs: Any) -> NativeEvent:
        dedupe_key = kwargs.pop("dedupe_key", None)
        run_id = kwargs["run_id"]
        async with self._lock:
            if dedupe_key and (run_id, dedupe_key) in self._dedupe:
                return self._dedupe[(run_id, dedupe_key)]
            event = NativeEvent(
                sequence=len(self.events[run_id]) + 1,
                event_id=str(uuid4()),
                timestamp=datetime.now(UTC),
                data=safe_event_data(kwargs.pop("data", None)),
                **kwargs,
            )
            self.events[run_id].append(event)
            if dedupe_key:
                self._dedupe[(run_id, dedupe_key)] = event
            return event

    async def list_events(self, run_id: str, after: int = 0) -> list[NativeEvent]:
        return [deepcopy(event) for event in self.events[run_id] if event.sequence > after]

    async def save_approval(self, run_id: str, approval: dict[str, Any]) -> None:
        candidate = {**deepcopy(approval), "consumed": False}
        async with self._lock:
            existing = self.approvals.get(run_id)
            if existing is None:
                self.approvals[run_id] = candidate
                return
            if _approval_identity(existing) != _approval_identity(candidate):
                raise ApprovalCommandConflictError(
                    "A different approval command is already recorded for this run"
                )

    async def get_pending_approval(self, run_id: str) -> dict[str, Any] | None:
        approval = self.approvals.get(run_id)
        if not approval or approval["consumed"]:
            return None
        return deepcopy(approval)

    async def get_approval(self, run_id: str) -> dict[str, Any] | None:
        return deepcopy(self.approvals.get(run_id))

    async def consume_approval(self, run_id: str) -> None:
        async with self._lock:
            self.approvals[run_id]["consumed"] = True

    async def get_refund(self, idempotency_key: str) -> dict[str, Any] | None:
        return deepcopy(self.refunds.get(idempotency_key))

    async def record_refund(self, refund: dict[str, Any]) -> dict[str, Any]:
        candidate = deepcopy(refund)
        key = candidate["idempotency_key"]
        async with self._lock:
            existing = self.refunds.get(key)
            if existing is None:
                if any(
                    record["refund_id"] == candidate["refund_id"]
                    for record in self.refunds.values()
                ):
                    raise RefundIdempotencyConflictError(
                        "Refund ID is already bound to another idempotency key"
                    )
                self.refunds[key] = candidate
                return deepcopy(candidate)
            if (
                existing["request_fingerprint"] != candidate["request_fingerprint"]
                or existing["refund_id"] != candidate["refund_id"]
            ):
                raise RefundIdempotencyConflictError(
                    "Idempotency key is already bound to a different refund request"
                )
            return deepcopy(existing)

    async def upsert_memory(self, customer_id: str, case_id: str, facts: dict[str, Any]) -> None:
        self.memories[(customer_id, case_id)] = deepcopy(facts)

    async def get_memory(self, customer_id: str, case_id: str) -> dict[str, Any]:
        return deepcopy(self.memories.get((customer_id, case_id), {}))
