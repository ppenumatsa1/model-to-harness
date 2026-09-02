from __future__ import annotations

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

from .models import DurableEvent, WorkflowState


def map_outcome(state: WorkflowState, events: list[DurableEvent]) -> WorkflowOutcome:
    if state.duplicate_found is True:
        duplicate = DuplicateDecision.CONFIRMED
    elif state.duplicate_found is False:
        duplicate = DuplicateDecision.NOT_FOUND
    else:
        duplicate = DuplicateDecision.INDETERMINATE

    if state.policy_validation is None:
        policy = PolicyDecision.NOT_EVALUATED
    elif state.policy_validation.ok:
        policy = PolicyDecision.ELIGIBLE
    elif state.policy_validation.failure_code == "policy_ineligible":
        policy = PolicyDecision.INELIGIBLE
    else:
        policy = PolicyDecision.MANUAL_REVIEW

    if state.approval_decision is None:
        approval = (
            ApprovalDecision.PENDING
            if state.approval_required
            else ApprovalDecision.NOT_REQUIRED
        )
    elif state.approval_decision.value == "approve":
        approval = ApprovalDecision.APPROVED
    else:
        approval = ApprovalDecision.DENIED

    terminal = TerminalStatus(state.terminal_status or state.status.value)
    failure = FailureCode(state.failure_code or FailureCode.NONE.value)
    return WorkflowOutcome(
        case_id=state.case_id,
        run_id=state.run_id,
        duplicate_decision=duplicate,
        policy_decision=policy,
        approval_decision=approval,
        refund_status=RefundStatus(state.refund_status),
        refund_id=state.refund_id,
        notification_status=NotificationStatus(state.notification_status),
        terminal_status=terminal,
        failure_code=failure,
        events=tuple(
            ExecutionEventSummary(
                sequence=event.sequence,
                event_type=event.event_type,
                step=event.node or event.transition or "workflow",
                summary=event.summary,
                retry_attempt=event.retry_attempt or 0,
            )
            for event in events
        ),
    )

