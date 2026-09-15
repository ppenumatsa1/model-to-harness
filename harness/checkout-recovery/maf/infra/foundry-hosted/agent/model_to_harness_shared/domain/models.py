from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .enums import (
    ApprovalDecision,
    ChargeStatus,
    DuplicateDecision,
    FailureCode,
    NotificationStatus,
    PolicyDecision,
    RefundStatus,
    TerminalStatus,
)


class DomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ScenarioInput(DomainModel):
    complaint_text: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    fixture_id: str = Field(min_length=1)
    existing_case_id: str | None = Field(default=None, min_length=1)
    idempotency_key: str | None = Field(default=None, min_length=1)


class CaseStartResult(DomainModel):
    case_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    status: TerminalStatus
    current_step: str = Field(min_length=1)
    approval_required: bool


class ChargeRecord(DomainModel):
    charge_id: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    purchase_reference: str = Field(min_length=1)
    amount: Decimal = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    charged_at: datetime
    status: ChargeStatus = ChargeStatus.CAPTURED

    @model_validator(mode="after")
    def validate_timestamp(self) -> "ChargeRecord":
        if self.charged_at.utcoffset() is None:
            raise ValueError("charged_at must be timezone-aware")
        return self


class DuplicateEvidence(DomainModel):
    decision: DuplicateDecision
    matching_charge_ids: tuple[str, ...] = ()
    purchase_reference: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_confirmed_evidence(self) -> "DuplicateEvidence":
        if self.decision == DuplicateDecision.CONFIRMED:
            if (
                len(self.matching_charge_ids) != 2
                or self.purchase_reference is None
                or self.amount is None
                or self.currency is None
            ):
                raise ValueError("confirmed duplicate evidence requires one complete charge pair")
        elif self.matching_charge_ids:
            raise ValueError("non-confirmed evidence cannot contain matching charge IDs")
        return self


class BillingValidation(DomainModel):
    valid: bool
    checked_charge_ids: tuple[str, ...]
    reason: str = Field(min_length=1)


class PolicyAssessment(DomainModel):
    decision: PolicyDecision
    policy_code: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class ApprovalCommand(DomainModel):
    checkpoint_id: str = Field(min_length=1)
    decision: ApprovalDecision
    reviewer_id: str = Field(min_length=1)
    reason: str | None = None

    @model_validator(mode="after")
    def validate_terminal_decision(self) -> "ApprovalCommand":
        if self.decision not in {ApprovalDecision.APPROVED, ApprovalDecision.DENIED}:
            raise ValueError("approval command decision must be approved or denied")
        return self


class ApprovalRecord(DomainModel):
    approval_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    checkpoint_id: str = Field(min_length=1)
    decision: ApprovalDecision
    amount: Decimal = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    reviewer_id: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def validate_reviewer(self) -> "ApprovalRecord":
        is_resolved = self.decision in {
            ApprovalDecision.APPROVED,
            ApprovalDecision.DENIED,
        }
        if is_resolved != (self.reviewer_id is not None):
            raise ValueError("resolved approvals require a reviewer")
        return self


class RefundRecord(DomainModel):
    refund_id: str = Field(min_length=1)
    idempotency_key: str = Field(min_length=1)
    account_id: str = Field(min_length=1)
    original_charge_id: str = Field(min_length=1)
    amount: Decimal = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    submitted_at: datetime

    @model_validator(mode="after")
    def validate_timestamp(self) -> "RefundRecord":
        if self.submitted_at.utcoffset() is None:
            raise ValueError("submitted_at must be timezone-aware")
        return self


class RefundVerification(DomainModel):
    idempotency_key: str = Field(min_length=1)
    matching_refund_count: int = Field(ge=0)
    verified: bool
    refund_id: str | None = None
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def validate_verification(self) -> "RefundVerification":
        if self.verified != (self.matching_refund_count == 1):
            raise ValueError("verified must mean exactly one matching refund")
        if self.verified and self.refund_id is None:
            raise ValueError("verified refund requires refund_id")
        return self


class ExecutionEventSummary(DomainModel):
    sequence: int = Field(ge=1)
    event_type: str = Field(min_length=1)
    step: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    retry_attempt: int = Field(default=0, ge=0)


class WorkflowOutcome(DomainModel):
    case_id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    duplicate_decision: DuplicateDecision
    policy_decision: PolicyDecision
    approval_decision: ApprovalDecision
    refund_status: RefundStatus
    refund_id: str | None = None
    notification_status: NotificationStatus
    terminal_status: TerminalStatus
    failure_code: FailureCode = FailureCode.NONE
    events: tuple[ExecutionEventSummary, ...] = ()

    @model_validator(mode="after")
    def validate_outcome_consistency(self) -> "WorkflowOutcome":
        if self.refund_status == RefundStatus.VERIFIED and self.refund_id is None:
            raise ValueError("verified outcome requires refund_id")
        if (
            self.terminal_status == TerminalStatus.COMPLETED_REFUNDED
            and self.refund_status != RefundStatus.VERIFIED
        ):
            raise ValueError("completed_refunded requires a verified refund")
        if self.notification_status == NotificationStatus.SENT and (
            self.refund_status != RefundStatus.VERIFIED
        ):
            raise ValueError("notification can be sent only after refund verification")
        sequences = [event.sequence for event in self.events]
        if sequences != sorted(sequences) or len(sequences) != len(set(sequences)):
            raise ValueError("event sequences must be ordered and unique")
        return self
