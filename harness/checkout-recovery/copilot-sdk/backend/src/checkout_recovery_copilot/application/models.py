from datetime import datetime
from enum import StrEnum
from typing import Any

from model_to_harness_shared import (
    CheckoutApprovalDecision,
    CheckoutFailureCode,
    CheckoutRecoveryOutcome,
    CheckoutSimulatorSnapshot,
    CheckoutTerminalStatus,
    DiagnosticDisposition,
    RemediationAction,
    RemediationStatus,
    VerificationResult,
)
from pydantic import BaseModel, ConfigDict, Field


class CasePhase(StrEnum):
    OPEN = "open"
    WAITING_APPROVAL = "waiting_approval"
    CLOSED = "closed"


class AuditCode(StrEnum):
    CASE_STARTED = "case_started"
    HARNESS_COMPLETED = "harness_completed"
    DIAGNOSTIC_COMPLETED = "diagnostic_completed"
    APPROVAL_RECORDED = "approval_recorded"
    REMEDIATION_INTENT_RECORDED = "remediation_intent_recorded"
    REMEDIATION_RESPONSE_UNCERTAIN = "remediation_response_uncertain"
    REMEDIATION_COMPLETED = "remediation_completed"
    VERIFICATION_COMPLETED = "verification_completed"
    CASE_CLOSED = "case_closed"


class WorkspaceArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: str
    kind: str = "checkout_recovery_summary"
    revision: int = Field(ge=1)
    updated_at: datetime


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: AuditCode
    occurred_at: datetime
    summary: str


class CaseRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    run_id: str
    fixture_id: str
    order_id: str
    simulator_snapshot: CheckoutSimulatorSnapshot
    phase: CasePhase
    diagnostic_disposition: DiagnosticDisposition | None = None
    approval_decision: CheckoutApprovalDecision = CheckoutApprovalDecision.NOT_REQUIRED
    approval_reviewer_id: str | None = None
    approval_request_id: str | None = None
    approval_reason: str | None = None
    approval_evidence_hash: str | None = None
    remediation_action: RemediationAction | None = None
    remediation_status: RemediationStatus | None = None
    verification_result: bool | None = None
    verification: VerificationResult | None = None
    diagnostic_tools: tuple[str, ...] = ()
    harness_mode: str = "scripted"
    terminal_status: CheckoutTerminalStatus | None = None
    failure_code: CheckoutFailureCode = CheckoutFailureCode.NONE
    outcome: CheckoutRecoveryOutcome | None = None
    artifact: WorkspaceArtifact
    created_at: datetime
    updated_at: datetime


class RemediationIntent(BaseModel):
    """Private operational ledger record; it is never included in a projection."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str
    request_fingerprint: str
    action: RemediationAction


class InvestigationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    selected_tools: tuple[str, ...]
    mode: str
    framework_state: dict[str, Any] = Field(default_factory=dict)
