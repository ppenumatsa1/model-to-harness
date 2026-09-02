from __future__ import annotations

from maf_double_charge.agui import project_events
from maf_double_charge.models import DurableEvent, WorkflowState


def state() -> WorkflowState:
    return WorkflowState(
        case_id="case-1",
        run_id="run-1",
        complaint="private complaint",
        customer_id="customer-1",
        scenario_id="duplicate-confirmed",
        idempotency_key="secret-ish-key",
    )


def test_projection_orders_events_and_redacts_sensitive_state() -> None:
    current = state()
    events = [
        DurableEvent(
            sequence=1,
            case_id=current.case_id,
            run_id=current.run_id,
            event_type="node.started",
            node="billing_validation",
            summary="Billing validation started.",
        ),
        DurableEvent(
            sequence=2,
            case_id=current.case_id,
            run_id=current.run_id,
            event_type="decision.summary",
            node="detect_duplicate",
            summary="Two captured charges match.",
            payload={"decision": "confirmed"},
        ),
        DurableEvent(
            sequence=3,
            case_id=current.case_id,
            run_id=current.run_id,
            event_type="approval.requested",
            node="approval_checkpoint",
            summary="Approval required.",
            payload={"amount": "42.50", "currency": "USD"},
        ),
    ]
    projected = project_events(events, current)
    sequences = [
        item["metadata"]["sequence"]
        for item in projected
        if item.get("metadata", {}).get("sequence")
    ]
    assert sequences == sorted(sequences)
    serialized = str(projected)
    assert "private complaint" not in serialized
    assert "secret-ish-key" not in serialized
    assert "raw prompt" not in serialized.lower()
    assert any(item.get("name") == "approval_requested" for item in projected)


def test_tool_completion_closes_before_emitting_result() -> None:
    current = state()
    completed = DurableEvent(
        sequence=1,
        case_id=current.case_id,
        run_id=current.run_id,
        event_type="tool.call.succeeded",
        node="load_account",
        retry_attempt=2,
        summary="Account loaded.",
        payload={"tool": "shared.billing.load_charges"},
    )

    projected = project_events([completed], current)

    assert [item["type"] for item in projected[:2]] == [
        "TOOL_CALL_END",
        "TOOL_CALL_RESULT",
    ]
    assert projected[0]["toolCallId"] == projected[1]["toolCallId"]
    assert projected[0]["toolCallId"].endswith(":2")
