from __future__ import annotations

import asyncio
from collections import defaultdict
from copy import deepcopy
from typing import TYPE_CHECKING

from maf_double_charge.application.errors import RefundIdempotencyConflictError
from maf_double_charge.application.models import (
    ApprovalResponse,
    DurableEvent,
    RefundLedgerEntry,
    WorkflowState,
)
from model_to_harness_shared import WorkflowOutcome

if TYPE_CHECKING:
    from agent_framework import WorkflowCheckpoint


class InMemoryRepository:
    def __init__(self) -> None:
        self.states: dict[str, WorkflowState] = {}
        self.case_runs: dict[str, str] = {}
        self.events: dict[str, list[DurableEvent]] = defaultdict(list)
        self.approvals: dict[str, tuple[str, ApprovalResponse]] = {}
        self.outcomes: dict[str, WorkflowOutcome] = {}
        self.memory: dict[str, dict[str, object]] = {}
        self.refunds: dict[str, RefundLedgerEntry] = {}
        self.run_checkpoints: dict[str, dict[str, WorkflowCheckpoint]] = {}
        self._lock = asyncio.Lock()
        self._sequence = 0

    async def initialize(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def check_ready(self) -> None:
        return None

    async def create_run(self, state: WorkflowState) -> None:
        async with self._lock:
            if state.run_id in self.states or state.case_id in self.case_runs:
                raise ValueError("run or case already exists")
            self.states[state.run_id] = deepcopy(state)
            self.case_runs[state.case_id] = state.run_id

    async def save_state(self, state: WorkflowState) -> None:
        async with self._lock:
            self.states[state.run_id] = deepcopy(state)

    async def get_state(self, run_id: str) -> WorkflowState | None:
        state = self.states.get(run_id)
        return deepcopy(state) if state else None

    async def get_state_by_case(self, case_id: str) -> WorkflowState | None:
        run_id = self.case_runs.get(case_id)
        return await self.get_state(run_id) if run_id else None

    async def save_memory(self, case_id: str, memory: dict[str, object]) -> None:
        self.memory[case_id] = deepcopy(memory)

    async def get_memory(self, case_id: str) -> dict[str, object]:
        return deepcopy(self.memory.get(case_id, {}))

    async def append_event(self, event: DurableEvent) -> DurableEvent:
        async with self._lock:
            self._sequence += 1
            saved = event.model_copy(update={"sequence": self._sequence}, deep=True)
            self.events[event.run_id].append(saved)
            return deepcopy(saved)

    async def list_events(self, run_id: str, after: int = 0) -> list[DurableEvent]:
        return [deepcopy(event) for event in self.events[run_id] if event.sequence > after]

    async def save_approval(
        self, run_id: str, checkpoint_id: str, response: ApprovalResponse
    ) -> None:
        async with self._lock:
            existing = self.approvals.get(run_id)
            if existing:
                if existing[0] != checkpoint_id or not existing[1].same_intent(response):
                    raise ValueError("approval already resolved with another decision")
                return
            self.approvals[run_id] = (checkpoint_id, deepcopy(response))

    async def get_approval(self, run_id: str) -> ApprovalResponse | None:
        record = self.approvals.get(run_id)
        return deepcopy(record[1]) if record else None

    async def save_outcome(self, outcome: WorkflowOutcome) -> None:
        self.outcomes[outcome.run_id] = deepcopy(outcome)

    async def get_outcome(self, run_id: str) -> WorkflowOutcome | None:
        outcome = self.outcomes.get(run_id)
        return deepcopy(outcome) if outcome else None

    async def set_checkpoint(self, run_id: str, checkpoint_id: str) -> None:
        async with self._lock:
            state = self.states.get(run_id)
            if state:
                self.states[run_id] = state.model_copy(update={"checkpoint_id": checkpoint_id})

    async def get_refund(self, idempotency_key: str) -> RefundLedgerEntry | None:
        async with self._lock:
            entry = self.refunds.get(idempotency_key)
            return deepcopy(entry) if entry else None

    async def store_refund(self, entry: RefundLedgerEntry) -> tuple[RefundLedgerEntry, bool]:
        async with self._lock:
            existing = self.refunds.get(entry.idempotency_key)
            if existing is not None:
                if existing.request_fingerprint != entry.request_fingerprint:
                    raise RefundIdempotencyConflictError(
                        "idempotency key is already bound to a different refund request"
                    )
                return deepcopy(existing), False
            self.refunds[entry.idempotency_key] = deepcopy(entry)
            return deepcopy(entry), True

    async def count_refunds(self, idempotency_key: str) -> int:
        async with self._lock:
            return int(idempotency_key in self.refunds)
