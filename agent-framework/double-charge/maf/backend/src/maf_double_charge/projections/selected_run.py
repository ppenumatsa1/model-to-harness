from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ..application.models import DurableEvent, WorkflowState

SAFE_EVENT_TYPES = frozenset(
    {
        "decision.summary",
        "parallel.joined",
        "approval.requested",
        "approval.recorded",
        "approval.resolved",
        "refund.verification",
        "run.completed",
        "run.failed",
    }
)


def selected_run_facts(
    state: WorkflowState, events: Iterable[DurableEvent]
) -> tuple[list[DurableEvent], dict[str, Any]]:
    allowlisted = [event for event in events if event.event_type in SAFE_EVENT_TYPES]
    facts = {
        "status": state.status,
        "current_step": state.current_step,
        "terminal_status": state.terminal_status,
        "refund_status": state.refund_status,
        "latest_summary": allowlisted[-1].summary if allowlisted else "No decision yet.",
        "event_summaries": [event.summary for event in allowlisted[-8:]],
    }
    return allowlisted, facts


def selected_run_view(state: WorkflowState, events: Iterable[DurableEvent]) -> dict[str, Any]:
    allowlisted, _ = selected_run_facts(state, events)
    return {
        "read_only": True,
        "run": {
            "run_id": state.run_id,
            "case_id": state.case_id,
            "status": state.status,
            "current_step": state.current_step,
            "approval_required": state.approval_required,
            "terminal_status": state.terminal_status,
            "refund_status": state.refund_status,
        },
        "events": [
            {
                "sequence": event.sequence,
                "event_type": event.event_type,
                "summary": event.summary,
            }
            for event in allowlisted
        ],
        "safety": (
            "No complaint text, prompts, secrets, checkpoint bodies, "
            "idempotency keys, or unrestricted tool payloads."
        ),
    }
