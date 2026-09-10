from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from model_to_harness_shared import WorkflowOutcome
from pydantic import BaseModel, ConfigDict, Field


def utc_now() -> datetime:
    return datetime.now(UTC)


class RunStatus(StrEnum):
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    MANUAL_REVIEW = "manual_review"


class NodeStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    SKIPPED = "skipped"


class ApprovalDecision(StrEnum):
    APPROVE = "approve"
    DENY = "deny"


class StartResult(BaseModel):
    case_id: str
    run_id: str
    status: RunStatus
    current_step: str
    approval_required: bool
    checkpoint_id: str | None = None


class ApprovalResponse(BaseModel):
    decision: ApprovalDecision
    reviewer_id: str
    reason: str | None = None
    decided_at: datetime = Field(default_factory=utc_now)

    def same_intent(self, other: ApprovalResponse) -> bool:
        return (
            self.decision == other.decision
            and self.reviewer_id == other.reviewer_id
            and self.reason == other.reason
        )


class BranchResult(BaseModel):
    branch: Literal["billing_validation", "policy_validation"]
    ok: bool
    summary: str
    failure_code: str | None = None
    attempts: int = 1
    evidence: dict[str, Any] = Field(default_factory=dict)


class WorkflowState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    run_id: str
    complaint: str
    customer_id: str
    scenario_id: str
    idempotency_key: str
    status: RunStatus = RunStatus.RUNNING
    current_step: str = "normalize_complaint"
    normalized_complaint: str | None = None
    account_summary: dict[str, Any] = Field(default_factory=dict)
    duplicate_found: bool | None = None
    duplicate_summary: str | None = None
    duplicate_evidence: dict[str, Any] = Field(default_factory=dict)
    billing_validation: BranchResult | None = None
    policy_validation: BranchResult | None = None
    approval_required: bool = False
    approval_decision: ApprovalDecision | None = None
    checkpoint_id: str | None = None
    refund_status: str = "not_requested"
    refund_id: str | None = None
    notification_status: str = "not_sent"
    notification_summary: str | None = None
    terminal_status: str | None = None
    failure_code: str | None = None
    updated_at: datetime = Field(default_factory=utc_now)

    def advance(self, step: str, **updates: Any) -> WorkflowState:
        return self.model_copy(update={"current_step": step, "updated_at": utc_now(), **updates})


class DurableEvent(BaseModel):
    sequence: int = 0
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    case_id: str
    run_id: str
    event_type: str
    node: str | None = None
    transition: str | None = None
    checkpoint_id: str | None = None
    retry_attempt: int | None = None
    idempotency_key: str | None = None
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class RefundLedgerEntry(BaseModel):
    idempotency_key: str
    request_fingerprint: str
    account_id: str
    charge_id: str
    amount: Decimal
    currency: str
    refund_id: str
    refund: dict[str, Any]
    created_by_run_id: str
    created_at: datetime = Field(default_factory=utc_now)


class CaseRecord(BaseModel):
    state: WorkflowState
    memory: dict[str, Any] = Field(default_factory=dict)
    outcome: WorkflowOutcome | None = None
