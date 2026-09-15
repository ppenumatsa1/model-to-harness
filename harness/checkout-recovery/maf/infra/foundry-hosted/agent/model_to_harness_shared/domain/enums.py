from enum import StrEnum


class ChargeStatus(StrEnum):
    CAPTURED = "captured"
    PENDING = "pending"
    REVERSED = "reversed"


class DuplicateDecision(StrEnum):
    CONFIRMED = "confirmed"
    NOT_FOUND = "not_found"
    INDETERMINATE = "indeterminate"


class PolicyDecision(StrEnum):
    NOT_EVALUATED = "not_evaluated"
    ELIGIBLE = "eligible"
    INELIGIBLE = "ineligible"
    MANUAL_REVIEW = "manual_review"


class ApprovalDecision(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"


class RefundStatus(StrEnum):
    NOT_REQUESTED = "not_requested"
    SUBMITTED = "submitted"
    VERIFIED = "verified"
    MANUAL_REVIEW = "manual_review"
    FAILED = "failed"


class NotificationStatus(StrEnum):
    NOT_SENT = "not_sent"
    DRAFTED = "drafted"
    SENT = "sent"
    FAILED = "failed"


class TerminalStatus(StrEnum):
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED_NO_REFUND = "completed_no_refund"
    COMPLETED_REFUNDED = "completed_refunded"
    CLOSED_DENIED = "closed_denied"
    MANUAL_REVIEW = "manual_review"
    FAILED = "failed"


class FailureCode(StrEnum):
    NONE = "none"
    TRANSIENT_BILLING_READ = "transient_billing_read"
    BILLING_VALIDATION_FAILED = "billing_validation_failed"
    POLICY_INELIGIBLE = "policy_ineligible"
    APPROVAL_CONFLICT = "approval_conflict"
    REFUND_IDEMPOTENCY_CONFLICT = "refund_idempotency_conflict"
    REFUND_SUBMISSION_FAILED = "refund_submission_failed"
    REFUND_VERIFICATION_MISMATCH = "refund_verification_mismatch"
