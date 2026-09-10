from __future__ import annotations

import json

import pytest
from maf_double_charge.application.models import DurableEvent, WorkflowState
from maf_double_charge.projections.agui import project_events
from maf_double_charge.projections.selected_run import (
    SAFE_EVENT_TYPES,
    selected_run_facts,
    selected_run_view,
)


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


@pytest.mark.parametrize(
    ("event_type", "safe_payload"),
    [
        ("parallel.started", {"branches": ["billing_validation", "policy_validation"]}),
        ("parallel.branch.completed", {"branch": "billing_validation", "ok": True}),
        ("parallel.joined", {"billing_ok": True, "policy_ok": True}),
        (
            "decision.summary",
            {
                "decision": "confirmed",
                "matching_charge_count": 2,
                "amount": "42.50",
                "currency": "USD",
            },
        ),
        ("checkpoint.created", {"workflow_name": "double-charge-run-1"}),
        (
            "approval.requested",
            {"amount": "42.50", "currency": "USD", "evidence_summary": "Duplicate confirmed."},
        ),
        ("approval.recorded", {"decision": "approve", "reviewer_id": "reviewer"}),
        ("approval.resolved", {"decision": "approve", "reviewer_id": "reviewer"}),
        ("refund.idempotency.lookup", {"tool": "shared.billing.submit_refund"}),
        ("refund.verification", {"matching_refund_count": 1, "verified": True}),
        ("notification.sent", {}),
        ("workflow.resumed", {}),
    ],
)
def test_custom_event_details_are_explicitly_allowlisted(
    event_type: str, safe_payload: dict[str, object]
) -> None:
    current = state()
    event = DurableEvent(
        case_id=current.case_id,
        run_id=current.run_id,
        event_type=event_type,
        summary="Safe durable summary.",
        payload={
            **safe_payload,
            "prompt": "private-prompt",
            "credential": "private-credential",
            "checkpoint": {"raw": "private-checkpoint"},
            "arguments": {"raw": "private-arguments"},
            "result": {"raw": "private-result"},
            "reasoning": "private-reasoning",
        },
    )
    projected = project_events([event])
    assert projected[0]["value"]["details"] == safe_payload
    assert "private-" not in json.dumps(projected)


def test_projection_rejects_nested_payloads_even_for_allowlisted_keys() -> None:
    current = state()
    events = [
        DurableEvent(
            case_id=current.case_id,
            run_id=current.run_id,
            event_type="approval.requested",
            summary="Approval required.",
            payload={"amount": {"prompt": "private-prompt"}},
        ),
        DurableEvent(
            case_id=current.case_id,
            run_id=current.run_id,
            event_type="model.call.completed",
            summary="Model call completed.",
            payload={
                "model": "fake-model",
                "latency_ms": 1,
                "prompt": "private-prompt",
                "reasoning": "private-reasoning",
                "summary": "private-summary-override",
                "node": "private-node-override",
            },
        ),
        DurableEvent(
            case_id=current.case_id,
            run_id=current.run_id,
            event_type="tool.call.started",
            node="load_account",
            summary="Billing read started.",
            payload={"tool": {"prompt": "private-prompt"}, "arguments": "private-arguments"},
        ),
        DurableEvent(
            case_id=current.case_id,
            run_id=current.run_id,
            event_type="maf.native.output",
            summary="MAF emitted output.",
            payload={"state": {"complaint": "private-complaint"}, "result": "private-result"},
        ),
    ]
    projected = project_events(events)
    assert projected[0]["value"]["details"] == {}
    assert projected[1]["value"] == {
        "node": None,
        "summary": "Model call completed.",
        "model": "fake-model",
        "latency_ms": 1,
    }
    assert projected[2]["toolCallName"] == "load_account"
    assert projected[3]["value"] == {"kind": "output", "node": None}
    assert "private-" not in json.dumps(projected)


def test_selected_run_facts_keep_existing_allowlist_and_latest_eight_summaries() -> None:
    current = state()
    assert SAFE_EVENT_TYPES == {
        "decision.summary",
        "parallel.joined",
        "approval.requested",
        "approval.recorded",
        "approval.resolved",
        "refund.verification",
        "run.completed",
        "run.failed",
    }
    events = [
        DurableEvent(
            sequence=sequence,
            case_id=current.case_id,
            run_id=current.run_id,
            event_type="decision.summary",
            summary=f"Safe fact {sequence}.",
            payload={"secret": "private-payload"},
        )
        for sequence in range(1, 11)
    ]
    events.append(
        DurableEvent(
            sequence=11,
            case_id=current.case_id,
            run_id=current.run_id,
            event_type="tool.call.succeeded",
            summary="private-unallowlisted-summary",
            payload={"result": "private-result"},
        )
    )
    allowlisted, facts = selected_run_facts(current, events)
    assert allowlisted == events[:10]
    assert set(facts) == {
        "status",
        "current_step",
        "terminal_status",
        "refund_status",
        "latest_summary",
        "event_summaries",
    }
    assert facts["latest_summary"] == "Safe fact 10."
    assert facts["event_summaries"] == [f"Safe fact {sequence}." for sequence in range(3, 11)]
    view = selected_run_view(current, events)
    assert len(view["events"]) == 10
    assert all(set(event) == {"sequence", "event_type", "summary"} for event in view["events"])
    assert "private" not in json.dumps(view)
    assert current.idempotency_key not in json.dumps(view)
    assert selected_run_facts(current, [])[1]["latest_summary"] == "No decision yet."


@pytest.mark.parametrize(
    ("event_type", "protocol_types", "custom_name"),
    [
        ("run.started", ["RUN_STARTED"], None),
        ("run.completed", ["RUN_FINISHED"], None),
        ("run.failed", ["RUN_ERROR"], None),
        ("node.started", ["STEP_STARTED"], None),
        ("node.completed", ["STEP_FINISHED"], None),
        ("tool.call.started", ["TOOL_CALL_START"], None),
        ("tool.call.succeeded", ["TOOL_CALL_END", "TOOL_CALL_RESULT"], None),
        ("tool.call.failed", ["TOOL_CALL_END", "TOOL_CALL_RESULT"], None),
        ("tool.call.retried", ["CUSTOM"], "tool_retry"),
        ("edge.selected", ["CUSTOM"], "edge_selected"),
        ("model.call.started", ["CUSTOM"], "model_call_started"),
        ("model.call.completed", ["CUSTOM"], "model_call_completed"),
        ("maf.native.status", ["CUSTOM"], "maf_native_event"),
        ("unprojected.event", [], None),
    ],
)
def test_durable_event_protocol_vocabulary(
    event_type: str, protocol_types: list[str], custom_name: str | None
) -> None:
    current = state().model_copy(update={"failure_code": "workflow_failed"})
    event = DurableEvent(
        sequence=7,
        case_id=current.case_id,
        run_id=current.run_id,
        event_type=event_type,
        node="load_account",
        transition="load_account->detect_duplicate",
        retry_attempt=2,
        idempotency_key=current.idempotency_key,
        summary="Safe durable summary.",
        payload={"tool": "shared.billing.load_charges", "result": "private-result"},
    )
    projected = project_events([event], current)
    assert [item["type"] for item in projected] == [*protocol_types, "STATE_SNAPSHOT"]
    for item in projected[:-1]:
        assert item["metadata"] == {"sequence": 7, "source": "maf_durable_audit"}
    if custom_name:
        assert projected[0]["name"] == custom_name
    assert projected[-1]["snapshot"] == {
        "case_id": "case-1",
        "run_id": "run-1",
        "status": "running",
        "current_step": "normalize_complaint",
        "approval_required": False,
        "checkpoint_id": None,
        "refund_status": "not_requested",
        "terminal_status": None,
    }
    assert "private-result" not in json.dumps(projected)
    assert current.complaint not in json.dumps(projected)
    assert current.idempotency_key not in json.dumps(projected)
