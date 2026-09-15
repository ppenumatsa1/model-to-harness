from collections.abc import Iterator
from contextlib import contextmanager
from copy import deepcopy
from threading import RLock
from typing import Any

from model_to_harness_shared import CheckoutApprovalDecision, CheckoutSimulator

from checkout_recovery_maf.application.models import AuditEvent, CaseRecord, RemediationIntent


class InMemoryCaseRepository:
    """Test/local repository with the same authority boundaries as the PostgreSQL adapter."""

    def __init__(self) -> None:
        self._cases: dict[str, CaseRecord] = {}
        self._events: dict[str, list[AuditEvent]] = {}
        self._intents: dict[str, RemediationIntent] = {}
        self._approvals: dict[str, tuple[CheckoutApprovalDecision, str]] = {}
        self._framework: dict[str, dict[str, Any]] = {}
        self._lock = RLock()

    @contextmanager
    def transaction(self, case_id: str) -> Iterator[None]:
        with self._lock:
            snapshot = deepcopy(
                (self._cases, self._events, self._intents, self._approvals, self._framework)
            )
            try:
                yield
            except BaseException:
                (self._cases, self._events, self._intents, self._approvals, self._framework) = (
                    snapshot
                )
                raise

    def ready(self) -> bool:
        return True

    def save_framework_state(self, case_id: str, state: dict[str, Any]) -> None:
        self._framework[case_id] = deepcopy(state)

    def create(self, case: CaseRecord, simulator: CheckoutSimulator) -> None:
        if case.case_id in self._cases:
            raise ValueError("case already exists")
        self._cases[case.case_id] = case.model_copy(deep=True)
        self._events[case.case_id] = []

    def get(self, case_id: str) -> CaseRecord | None:
        case = self._cases.get(case_id)
        return case.model_copy(deep=True) if case else None

    def save(self, case: CaseRecord) -> None:
        if case.case_id not in self._cases:
            raise KeyError("cannot save an unknown case")
        self._cases[case.case_id] = case.model_copy(deep=True)

    def save_approval(
        self, case_id: str, decision: CheckoutApprovalDecision, reviewer_id: str
    ) -> None:
        if case_id not in self._cases:
            raise KeyError("cannot approve an unknown case")
        existing = self._approvals.get(case_id)
        value = (decision, reviewer_id)
        if existing is not None and existing != value:
            raise ValueError("case approval is immutable")
        self._approvals[case_id] = value

    def simulator_for(self, case: CaseRecord) -> CheckoutSimulator:
        if case.case_id not in self._cases:
            raise KeyError("case has no checkout simulator")
        return CheckoutSimulator.from_snapshot(case.simulator_snapshot)

    def append_event(self, case_id: str, event: AuditEvent) -> None:
        self._events[case_id].append(event)

    def events_for(self, case_id: str) -> tuple[AuditEvent, ...]:
        return tuple(self._events[case_id])

    def remediation_intent_for(self, case_id: str) -> RemediationIntent | None:
        return self._intents.get(case_id)

    def save_remediation_intent(self, case_id: str, intent: RemediationIntent) -> None:
        existing = self._intents.get(case_id)
        if existing is not None and existing != intent:
            raise ValueError("case remediation intent is immutable")
        self._intents[case_id] = intent
