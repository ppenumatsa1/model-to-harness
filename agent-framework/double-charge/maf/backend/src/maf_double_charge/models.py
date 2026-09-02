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


class ScenarioInput(BaseModel):
    complaint: str = Field(min_length=3, max_length=4000)
    customer_id: str = Field(min_length=1, max_length=128)
    account_id: str | None = Field(default=None, max_length=128)
    scenario_id: str = Field(default="duplicate-confirmed", max_length=128)
    existing_case_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=256)


class StartResponse(BaseModel):
    case_id: str
    run_id: str
    status: RunStatus
    current_step: str
    approval_required: bool
    checkpoint_id: str | None = None


class ApprovalCommand(BaseModel):
    checkpoint_id: str
    decision: ApprovalDecision
    reviewer_id: str = Field(min_length=1, max_length=128)
    reason: str | None = Field(default=None, max_length=1000)


class ResumeCommand(BaseModel):
    checkpoint_id: str


class ApprovalRequest(BaseModel):
    case_id: str
    run_id: str
    evidence_summary: str
    amount: str | None = None
    currency: str | None = None


class ApprovalResponse(BaseModel):
    decision: ApprovalDecision
    reviewer_id: str
    reason: str | None = None
    decided_at: datetime = Field(default_factory=utc_now)


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


class CaseView(BaseModel):
    state: WorkflowState
    memory: dict[str, Any] = Field(default_factory=dict)
    outcome: WorkflowOutcome | None = None
    node_statuses: dict[str, NodeStatus] = Field(default_factory=dict)


WORKFLOW_GRAPH: dict[str, Any] = {
    "nodes": [
        "normalize_complaint",
        "load_account",
        "detect_duplicate",
        "prepare_validation",
        "billing_validation",
        "policy_validation",
        "join_validations",
        "approval_checkpoint",
        "submit_refund",
        "verify_refund",
        "notify_customer",
        "close_case",
        "close_no_duplicate",
        "close_denied",
        "route_failure",
        "manual_review",
    ],
    "edges": [
        ["normalize_complaint", "load_account"],
        ["load_account", "detect_duplicate", "loaded"],
        ["load_account", "route_failure", "read_failed"],
        ["detect_duplicate", "prepare_validation", "duplicate"],
        ["detect_duplicate", "close_no_duplicate", "no_duplicate"],
        ["prepare_validation", "billing_validation"],
        ["prepare_validation", "policy_validation"],
        ["billing_validation", "join_validations"],
        ["policy_validation", "join_validations"],
        ["join_validations", "approval_checkpoint", "valid"],
        ["join_validations", "route_failure", "invalid"],
        ["approval_checkpoint", "submit_refund", "approved"],
        ["approval_checkpoint", "close_denied", "denied"],
        ["submit_refund", "verify_refund"],
        ["verify_refund", "notify_customer", "exactly_one"],
        ["verify_refund", "manual_review", "mismatch"],
        ["notify_customer", "close_case"],
    ],
    "parallel_groups": [["billing_validation", "policy_validation"]],
}
