from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class CheckoutOrderStatus(StrEnum):
    CHECKOUT_FAILED = "checkout_failed"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    MANUAL_REVIEW = "manual_review"


class CheckoutPaymentStatus(StrEnum):
    AUTHORIZED = "authorized"
    CAPTURED = "captured"
    PENDING = "pending"
    REFUNDED = "refunded"
    DECLINED = "declined"


class InventoryReservationStatus(StrEnum):
    RESERVED = "reserved"
    EXPIRED = "expired"
    RELEASED = "released"


class DiagnosticDisposition(StrEnum):
    RECOVER_INVENTORY = "recover_inventory"
    REFUND_CAPTURED_PAYMENT = "refund_captured_payment"
    MANUAL_REVIEW = "manual_review"
    NO_ACTION = "no_action"


class RemediationAction(StrEnum):
    RECREATE_INVENTORY_RESERVATION = "recreate_inventory_reservation"
    REFUND_CAPTURED_PAYMENT = "refund_captured_payment"


class RemediationStatus(StrEnum):
    APPLIED = "applied"
    REJECTED = "rejected"


class CheckoutApprovalDecision(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class CheckoutTerminalStatus(StrEnum):
    RECOVERED = "recovered"
    WAITING_APPROVAL = "waiting_approval"
    MANUAL_REVIEW = "manual_review"
    CLOSED_DENIED = "closed_denied"
    FAILED = "failed"


class CheckoutFailureCode(StrEnum):
    NONE = "none"
    DIAGNOSTIC_READ_FAILED = "diagnostic_read_failed"
    REMEDIATION_IDEMPOTENCY_CONFLICT = "remediation_idempotency_conflict"
    VERIFICATION_MISMATCH = "verification_mismatch"
    HARNESS_FAILED = "harness_failed"


class CheckoutDomainModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class OrderRecord(CheckoutDomainModel):
    order_id: str = Field(min_length=1)
    customer_id: str = Field(min_length=1)
    status: CheckoutOrderStatus


class PaymentAttemptRecord(CheckoutDomainModel):
    payment_attempt_id: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    status: CheckoutPaymentStatus
    amount_minor: int = Field(gt=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")


class InventoryReservationRecord(CheckoutDomainModel):
    reservation_id: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    sku: str = Field(min_length=1)
    quantity: int = Field(gt=0)
    status: InventoryReservationStatus


class CheckoutDiagnosticRecord(CheckoutDomainModel):
    diagnostic_id: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    disposition: DiagnosticDisposition
    reason: str = Field(min_length=1)
    recommended_action: RemediationAction | None = None

    @model_validator(mode="after")
    def validate_recommendation(self) -> "CheckoutDiagnosticRecord":
        needs_action = self.disposition in {
            DiagnosticDisposition.RECOVER_INVENTORY,
            DiagnosticDisposition.REFUND_CAPTURED_PAYMENT,
        }
        if needs_action != (self.recommended_action is not None):
            raise ValueError("recovery diagnostics must have one recommended action")
        return self


class RemediationRequest(CheckoutDomainModel):
    operation_id: str = Field(min_length=1)
    request_fingerprint: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    action: RemediationAction
    payment_attempt_id: str | None = None
    reservation_id: str | None = None

    @model_validator(mode="after")
    def validate_target(self) -> "RemediationRequest":
        if self.action == RemediationAction.RECREATE_INVENTORY_RESERVATION:
            if self.reservation_id is None or self.payment_attempt_id is not None:
                raise ValueError("inventory recovery requires only a reservation target")
        elif self.payment_attempt_id is None or self.reservation_id is not None:
            raise ValueError("captured-payment refund requires only a payment target")
        return self


class RemediationResult(CheckoutDomainModel):
    remediation_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    request_fingerprint: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    action: RemediationAction
    status: RemediationStatus
    applied_at: datetime

    @model_validator(mode="after")
    def validate_applied_at(self) -> "RemediationResult":
        if self.applied_at.utcoffset() is None:
            raise ValueError("applied_at must be timezone-aware")
        return self


class CheckoutApproval(CheckoutDomainModel):
    approval_id: str = Field(min_length=1)
    order_id: str = Field(min_length=1)
    decision: CheckoutApprovalDecision
    reviewer_id: str | None = None
    reason: str | None = None

    @model_validator(mode="after")
    def validate_resolution(self) -> "CheckoutApproval":
        resolved = self.decision in {
            CheckoutApprovalDecision.APPROVED,
            CheckoutApprovalDecision.DENIED,
        }
        if resolved != (self.reviewer_id is not None):
            raise ValueError("resolved approval requires a reviewer")
        return self


class VerificationEvidence(CheckoutDomainModel):
    order_id: str = Field(min_length=1)
    operation_id: str = Field(min_length=1)
    expected_order_status: CheckoutOrderStatus
    actual_order_status: CheckoutOrderStatus
    expected_payment_status: CheckoutPaymentStatus
    actual_payment_status: CheckoutPaymentStatus
    expected_reservation_status: InventoryReservationStatus
    actual_reservation_status: InventoryReservationStatus
    expected_remediation_status: RemediationStatus
    actual_remediation_status: RemediationStatus | None = None


class VerificationResult(CheckoutDomainModel):
    verified: bool
    evidence: VerificationEvidence
    reason: str = Field(min_length=1)


class CheckoutRecoveryOutcome(CheckoutDomainModel):
    order_id: str = Field(min_length=1)
    diagnostic_disposition: DiagnosticDisposition
    approval_decision: CheckoutApprovalDecision
    remediation_status: RemediationStatus | None = None
    verification_result: bool | None = None
    terminal_status: CheckoutTerminalStatus
    failure_code: CheckoutFailureCode = CheckoutFailureCode.NONE

    @model_validator(mode="after")
    def validate_terminal_state(self) -> "CheckoutRecoveryOutcome":
        if self.terminal_status == CheckoutTerminalStatus.RECOVERED and (
            self.remediation_status != RemediationStatus.APPLIED
            or self.verification_result is not True
        ):
            raise ValueError("recovered outcome requires applied, verified remediation")
        if self.terminal_status == CheckoutTerminalStatus.MANUAL_REVIEW and (
            self.verification_result is True
        ):
            raise ValueError("manual review cannot claim successful verification")
        return self
