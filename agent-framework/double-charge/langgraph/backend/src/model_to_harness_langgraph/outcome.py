from typing import Any

from model_to_harness_shared import (
    ApprovalDecision,
    DuplicateDecision,
    ExecutionEventSummary,
    FailureCode,
    NotificationStatus,
    PolicyDecision,
    RefundStatus,
    TerminalStatus,
    WorkflowOutcome,
)

from .contracts import NativeEvent


def map_framework_outcome(
    state: dict[str, Any], events: list[NativeEvent]
) -> WorkflowOutcome:
    duplicate = _duplicate(state.get("duplicate_decision"))
    policy = _policy(state)
    approval = _approval(state.get("approval_decision"))
    refund = _refund(state)
    notification = _notification(state.get("notification_status"))
    terminal = _terminal(state, duplicate, approval, refund)
    failure = _failure(state.get("failure_code"))
    return WorkflowOutcome(
        case_id=state["case_id"],
        run_id=state["run_id"],
        duplicate_decision=duplicate,
        policy_decision=policy,
        approval_decision=approval,
        refund_status=refund,
        refund_id=state.get("refund_id") if refund == RefundStatus.VERIFIED else None,
        notification_status=notification,
        terminal_status=terminal,
        failure_code=failure,
        events=tuple(
            ExecutionEventSummary(
                sequence=event.sequence,
                event_type=event.event_type,
                step=event.node or "workflow",
                summary=event.summary,
                retry_attempt=int(event.data.get("attempt") or 0),
            )
            for event in events
        ),
    )


def _duplicate(value: Any) -> DuplicateDecision:
    if str(value) in {"duplicate", "confirmed", "yes"}:
        return DuplicateDecision.CONFIRMED
    if str(value) in {"no_duplicate", "not_duplicate", "not_found", "no"}:
        return DuplicateDecision.NOT_FOUND
    return DuplicateDecision.INDETERMINATE


def _policy(state: dict[str, Any]) -> PolicyDecision:
    result = state.get("validation_results", {}).get("policy")
    if not result:
        return PolicyDecision.NOT_EVALUATED
    return PolicyDecision.ELIGIBLE if result.get("ok") else PolicyDecision.INELIGIBLE


def _approval(value: Any) -> ApprovalDecision:
    if str(value) in {"approve", "approved"}:
        return ApprovalDecision.APPROVED
    if str(value) in {"deny", "denied"}:
        return ApprovalDecision.DENIED
    return ApprovalDecision.NOT_REQUIRED


def _refund(state: dict[str, Any]) -> RefundStatus:
    value = str(state.get("refund_status", "not_requested"))
    if value == "verified":
        return RefundStatus.VERIFIED
    if value == "mismatch" or state.get("terminal_status") == "manual_review":
        return RefundStatus.MANUAL_REVIEW
    if value == "failed":
        return RefundStatus.FAILED
    if value == "submitted":
        return RefundStatus.SUBMITTED
    return RefundStatus.NOT_REQUESTED


def _notification(value: Any) -> NotificationStatus:
    if str(value) == "sent":
        return NotificationStatus.SENT
    if str(value) == "failed":
        return NotificationStatus.FAILED
    return NotificationStatus.NOT_SENT


def _terminal(
    state: dict[str, Any],
    duplicate: DuplicateDecision,
    approval: ApprovalDecision,
    refund: RefundStatus,
) -> TerminalStatus:
    if state.get("terminal_status") == "manual_review":
        return TerminalStatus.MANUAL_REVIEW
    if state.get("terminal_status") == "failed":
        return TerminalStatus.FAILED
    if refund == RefundStatus.VERIFIED:
        return TerminalStatus.COMPLETED_REFUNDED
    if approval == ApprovalDecision.DENIED:
        return TerminalStatus.CLOSED_DENIED
    if duplicate == DuplicateDecision.NOT_FOUND:
        return TerminalStatus.COMPLETED_NO_REFUND
    return TerminalStatus.FAILED


def _failure(value: Any) -> FailureCode:
    mapping = {
        None: FailureCode.NONE,
        "TRANSIENT_BILLING_READ": FailureCode.TRANSIENT_BILLING_READ,
        "BILLING_VALIDATION_FAILED": FailureCode.BILLING_VALIDATION_FAILED,
        "POLICY_INELIGIBLE": FailureCode.POLICY_INELIGIBLE,
        "REFUND_IDEMPOTENCY_CONFLICT": FailureCode.REFUND_IDEMPOTENCY_CONFLICT,
        "REFUND_SUBMISSION_FAILED": FailureCode.REFUND_SUBMISSION_FAILED,
        "VERIFY_MISMATCH": FailureCode.REFUND_VERIFICATION_MISMATCH,
    }
    return mapping.get(value, FailureCode.REFUND_SUBMISSION_FAILED)

