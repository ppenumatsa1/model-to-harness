import asyncio
import json
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from model_to_harness_langgraph.api.app import create_app
from model_to_harness_langgraph.api.streams import audit_stream
from model_to_harness_langgraph.application.records import (
    ApprovalRequest,
    NativeEvent,
    ResumeRequest,
    StartCaseRequest,
)
from model_to_harness_langgraph.application.service import WorkflowService
from model_to_harness_langgraph.config import Settings
from model_to_harness_langgraph.graph.runner import DoubleChargeWorkflow
from model_to_harness_langgraph.infrastructure.domain_gateway import ToolResult
from model_to_harness_langgraph.testing.audit import InMemoryAuditRepository
from model_to_harness_langgraph.testing.fakes import FakeDomainGateway, FakeModel
from pydantic import ValidationError

START = {
    "complaint": "Original complaint: I was charged twice.",
    "customer_id": "customer-1",
    "operator_id": " operator-start ",
}
APPROVAL = {
    "decision": "approve", "reviewer_id": " reviewer-1 ", "reason": " Evidence reviewed ",
}


def runtime(*, model=None, gateway=None):
    audit = InMemoryAuditRepository()
    workflow = DoubleChargeWorkflow(
        audit=audit, model=model or FakeModel(), gateway=gateway or FakeDomainGateway(),
        checkpointer=InMemorySaver(),
    )
    return WorkflowService(workflow, audit)


@pytest.fixture
def client():
    app = create_app(
        settings=Settings(_env_file=None, telemetry_enabled=False),
        audit=InMemoryAuditRepository(), model=FakeModel(), gateway=FakeDomainGateway(),
        checkpointer=InMemorySaver(),
    )
    with TestClient(app) as test_client:
        yield test_client


@pytest.mark.parametrize("field,value", [
    ("operator_id", None), ("operator_id", ""), ("operator_id", " \n "),
    ("operator_id", "x" * 129), ("complaint", "    "), ("complaint", "x" * 4001),
])
def test_start_rejects_missing_blank_and_unbounded_operator_fields(client, field, value):
    body = {**START, field: value}
    if value is None:
        del body[field]
    assert client.post("/api/cases", json=body).status_code == 422
    assert client.get("/api/cases").json()["items"] == []


@pytest.mark.parametrize("field,value", [
    ("reviewer_id", None), ("reviewer_id", " "), ("reviewer_id", "x" * 129),
    ("reason", None), ("reason", ""), ("reason", "\n"), ("reason", "x" * 1001),
    ("checkpoint_id", " "), ("checkpoint_id", "x" * 257),
])
def test_approval_request_requires_bounded_trimmed_evidence(field, value):
    body = {"checkpoint_id": "checkpoint", **APPROVAL, field: value}
    if value is None:
        del body[field]
    with pytest.raises(ValidationError):
        ApprovalRequest.model_validate(body)


@pytest.mark.parametrize("field,value", [
    ("operator_id", None), ("operator_id", " "), ("operator_id", "x" * 129),
    ("checkpoint_id", None), ("checkpoint_id", ""), ("checkpoint_id", "x" * 257),
])
def test_resume_requires_explicit_operator_and_checkpoint(field, value):
    body = {"checkpoint_id": "checkpoint", "operator_id": "operator", field: value}
    if value is None:
        del body[field]
    with pytest.raises(ValidationError):
        ResumeRequest.model_validate(body)


def test_workspace_command_contract_preserves_flat_case_and_six_picker(client):
    started = client.post("/api/cases", json=START).json()
    case_id = started["case_id"]
    workspace = client.get(f"/api/cases/{case_id}/workspace").json()
    assert workspace["state"]["complaint"] == START["complaint"]
    assert workspace["state"]["customer_id"] == START["customer_id"]
    assert workspace["state"]["updated_at"]
    assert workspace["approval"] is None
    assert workspace["can_record_approval"] and not workspace["can_resume"]
    assert workspace["memory"] == {}
    flat = client.get(f"/api/cases/{case_id}").json()
    assert {"workflow_state", "selected_memory"} <= flat.keys()
    assert len(client.get("/api/scenarios").json()) == 6
    assert "verification-mismatch" not in str(client.get("/api/scenarios").json())
    assert all(set(node) == {"id", "label"} for node in workspace["graph"]["nodes"])
    assert workspace["graph"]["parallel_groups"] == [["billing_validation", "policy_validation"]]
    assert workspace["node_statuses"]["request_approval"] == "paused"
    assert workspace["node_statuses"]["normalize_complaint"] == "completed"
    approved = client.post(
        f"/api/cases/{case_id}/approval",
        json={"checkpoint_id": started["checkpoint_id"], **APPROVAL},
    )
    assert approved.status_code == 202
    workspace = client.get(f"/api/cases/{case_id}/workspace").json()
    assert workspace["state"]["status"] == "paused"
    assert workspace["approval"]["reviewer_id"] == "reviewer-1"
    assert workspace["approval"]["reason"] == "Evidence reviewed"
    assert workspace["approval"]["decided_at"]
    assert workspace["can_resume"] and not workspace["can_record_approval"]
    assert client.post(f"/api/cases/{case_id}/resume").status_code == 422
    assert client.post(
        f"/api/cases/{case_id}/resume",
        json={"checkpoint_id": "stale", "operator_id": "operator-resume"},
    ).status_code == 409
    assert client.post(
        f"/api/cases/{case_id}/resume",
        json={"checkpoint_id": started["checkpoint_id"], "operator_id": "operator-resume"},
    ).status_code == 200
    workspace = client.get(f"/api/cases/{case_id}/workspace").json()
    assert not workspace["can_resume"] and not workspace["can_record_approval"]
    assert workspace["approval"]["consumed"]
    assert workspace["outcome"]["terminal_status"] == "completed_refunded"
    assert workspace["memory"]["refund_status"] == "verified"


async def approved(service, *, decision="approve"):
    started = await service.start(StartCaseRequest(**START))
    await service.submit_approval(
        started.case_id,
        ApprovalRequest(checkpoint_id=started.checkpoint_id, **{**APPROVAL, "decision": decision}),
    )
    return started


async def test_audit_actors_intent_actual_execution_and_privacy():
    captured = []

    class Model(FakeModel):
        async def draft_notification(self, facts):
            captured.append(facts)
            return await super().draft_notification(facts)

    service = runtime(model=Model())
    started = await approved(service)
    before = await service.list_events(started.case_id)
    assert not any(event.event_type == "run_resumed" for event in before)
    await service.resume(
        started.case_id,
        ResumeRequest(checkpoint_id=started.checkpoint_id, operator_id="operator-resume"),
    )
    events = await service.list_events(started.case_id)
    by_type = {event.event_type: event for event in events}
    for name, identity in (
        ("run_started", "operator-start"), ("approval_command_recorded", "reviewer-1"),
        ("resume_command_recorded", "operator-resume"),
    ):
        assert by_type[name].data["actor_type"] == "human"
        assert by_type[name].data["actor_id"] == identity
        assert by_type[name].data["actor_source"] == "operator_supplied"
    for name in ("human_approval_resolved", "run_resumed", "run_completed"):
        assert by_type[name].data["actor_type"] == "system"
        assert by_type[name].data["actor_id"] == "langgraph-workflow"
        assert by_type[name].data["actor_source"] == "system"
    assert by_type["human_approval_resolved"].data["reviewer_id"] == "reviewer-1"
    assert by_type["resume_command_recorded"].sequence < by_type["run_resumed"].sequence
    assert by_type["run_resumed"].sequence < next(
        event.sequence for event in events
        if event.node == "submit_refund" and event.event_type == "tool_call_started"
    )
    assert all(event.data["audit_version"] == 2 for event in events)
    answer, _ = await service.explain(started.case_id, "state")
    for marker in ("operator-start", "operator-resume", "reviewer-1", "Evidence reviewed",
                   START["complaint"]):
        assert marker not in json.dumps(captured)
        assert marker not in answer
    terminal = by_type["run_completed"].model_dump()
    state = await service.workflow.snapshot(started.run_id)
    await service.workflow.close_success({**state, "refund_id": "changed-later"})
    terminal_again = next(
        event for event in await service.list_events(started.case_id)
        if event.event_type == "run_completed"
    )
    assert terminal_again.model_dump() == terminal
    assert terminal["data"]["refund_status"] == "verified"
    assert terminal["data"]["notification_status"] == "sent"


async def test_resume_request_is_not_proof_when_native_invocation_fails(monkeypatch):
    service = runtime()
    started = await approved(service)

    async def fail(*args):
        raise RuntimeError("worker interrupted before native invocation")

    monkeypatch.setattr(service.workflow, "resume", fail)
    with pytest.raises(RuntimeError):
        await service.resume(
            started.case_id,
            ResumeRequest(checkpoint_id=started.checkpoint_id, operator_id="operator"),
        )
    events = await service.list_events(started.case_id)
    assert any(event.event_type == "resume_command_recorded" for event in events)
    assert not any(event.event_type == "run_resumed" for event in events)
    assert not service.audit.refunds


@pytest.mark.parametrize("field,value", [
    ("decision", "deny"), ("reviewer_id", "different-reviewer"), ("reason", "Different evidence"),
])
async def test_approval_intent_conflicts_include_reviewer_and_reason(field, value):
    from model_to_harness_langgraph.application.service import InvalidCommandError

    service = runtime()
    started = await approved(service)
    original = ApprovalRequest(checkpoint_id=started.checkpoint_id, **APPROVAL)
    await service.submit_approval(started.case_id, original)
    with pytest.raises(InvalidCommandError):
        await service.submit_approval(started.case_id, original.model_copy(update={field: value}))
    events = await service.list_events(started.case_id)
    assert sum(event.event_type == "approval_command_recorded" for event in events) == 1
    assert not service.audit.refunds


async def test_resume_retries_preserve_distinct_operator_intents_without_fake_continuation(
    monkeypatch,
):
    service = runtime()
    started = await approved(service)
    resume = service.workflow.resume

    async def fail(*args):
        raise RuntimeError("before native execution")

    monkeypatch.setattr(service.workflow, "resume", fail)
    for operator in ("first-operator", "first-operator", "second-operator"):
        with pytest.raises(RuntimeError):
            await service.resume(
                started.case_id,
                ResumeRequest(checkpoint_id=started.checkpoint_id, operator_id=operator),
            )
    requests = [
        event for event in await service.list_events(started.case_id)
        if event.event_type == "resume_command_recorded"
    ]
    assert [event.data["actor_id"] for event in requests] == ["first-operator", "second-operator"]
    monkeypatch.setattr(service.workflow, "resume", resume)
    await service.resume(
        started.case_id,
        ResumeRequest(checkpoint_id=started.checkpoint_id, operator_id="second-operator"),
    )
    events = await service.list_events(started.case_id)
    assert sum(event.event_type == "run_resumed" for event in events) == 1


async def test_audit_fields_are_bounded_allowlisted_and_new_actor_cannot_be_spoofed():
    from model_to_harness_langgraph.application.records import EventData

    service = runtime()
    started = await service.start(StartCaseRequest(**START))
    event = await service.audit.append_event(
        case_id=started.case_id, run_id=started.run_id, event_type="safe",
        summary="Safe evidence",
        data={
            "raw_prompt": "SECRET", "arguments": {"password": "SECRET"},
            "actor_type": "human", "actor_id": "spoofed", "actor_source": "operator_supplied",
            "tool": "billing.load_account", "ok": True,
        },
    )
    assert "SECRET" not in event.model_dump_json()
    assert event.data["actor_type"] == "system"
    assert event.data["actor_id"] == "langgraph-workflow"
    for data in (
        {"actor_id": "x" * 129}, {"reason": "x" * 1001}, {"refund_id": "x" * 257},
        {"verified": "true"}, {"verified_count": -1}, {"matching_charge_ids": ["x"] * 101},
        {"matching_charge_ids": [{"secret": "SECRET"}]},
    ):
        with pytest.raises(ValidationError):
            EventData.model_validate(data)


async def test_verification_count_one_with_wrong_id_is_explicitly_not_verified():
    class Gateway(FakeDomainGateway):
        async def verify_refund(self, *args):
            return ToolResult(ok=True, value={"matching_refunds": 1, "refund_id": "wrong"})

    service = runtime(gateway=Gateway())
    started = await approved(service)
    await service.resume(
        started.case_id, ResumeRequest(checkpoint_id=started.checkpoint_id, operator_id="operator"),
    )
    event = next(
        event for event in await service.list_events(started.case_id)
        if event.event_type == "refund_verification"
    )
    assert event.data["verified_count"] == 1
    assert event.data["verified"] is False
    assert event.data["failure_code"] == "VERIFY_MISMATCH"


async def test_workspace_legacy_nulls_and_nested_projection_privacy():
    service = runtime()
    started = await service.start(StartCaseRequest(**START))
    run = service.audit.runs[started.run_id]
    run["state"] = {
        "normalized_complaint": "Normalized only", "raw_prompt": "secret",
        "validation_results": {"billing": {"ok": True, "arguments": "secret"}},
    }
    service.audit.approvals[started.run_id] = {
        "checkpoint_id": started.checkpoint_id, "decision": "approve",
        "reviewer_id": "legacy-reviewer", "reason": None, "consumed": False,
    }
    service.audit.memories[(run["customer_id"], started.case_id)] = {
        "case_id": started.case_id, "credential": "secret",
    }
    legacy = NativeEvent(
        sequence=999, event_id="legacy", case_id=started.case_id, run_id=started.run_id,
        timestamp=datetime.now(UTC), event_type="run_resumed", summary="Legacy dispatch",
        data={"raw_checkpoint": "secret"},
    )
    service.audit.events[started.run_id].append(legacy)
    before = deepcopy(run)
    workspace = await service.workspace(started.case_id)
    assert workspace.state.complaint is None
    assert workspace.state.scenario_id is None
    assert workspace.approval.reason is None and workspace.approval.decided_at is None
    assert workspace.can_resume
    assert "secret" not in workspace.model_dump_json()
    assert "actor_id" not in legacy.data and "audit_version" not in legacy.data
    assert run == before
    service.audit.approvals[started.run_id]["checkpoint_id"] = "stale"
    assert not (await service.workspace(started.case_id)).can_resume


async def test_history_complete_keyset_ties_and_concurrent_new_case():
    service = runtime()
    timestamp = datetime.now(UTC)
    for index in range(23):
        await service.audit.create_run({
            "case_id": f"case-{index:02}", "run_id": f"run-{index:02}",
            "customer_id": "customer", "status": "completed", "current_step": "completed",
            "checkpoint_id": None, "approval_required": False, "state": {},
            "outcome": None, "created_at": timestamp,
        })
    page = await service.list_cases()
    assert len(page.items) == 10 and page.has_more
    assert page.items[0].run_id == "run-22"
    assert page.items[0].scenario_id is None
    await service.audit.create_run({
        "case_id": "new", "run_id": "new", "customer_id": "customer",
        "status": "running", "current_step": "start", "state": {}, "outcome": None,
    })
    second = await service.list_cases(cursor=page.next_cursor)
    third = await service.list_cases(cursor=second.next_cursor)
    ids = [item.run_id for item in page.items + second.items + third.items]
    assert len(ids) == len(set(ids)) == 23
    assert len(third.items) == 3 and not third.has_more and third.next_cursor is None
    assert (await service.list_cases()).items[0].run_id == "new"


@pytest.mark.parametrize("query", ["cursor=garbage", "cursor=", "limit=0", "limit=101"])
def test_invalid_history_queries_return_422(client, query):
    assert client.get(f"/api/cases?{query}").status_code == 422


def test_native_sse_replay_and_snapshot_cursor_contract(client):
    started = client.post("/api/cases", json=START).json()
    path = f"/api/cases/{started['case_id']}"
    events = client.get(f"{path}/events").json()
    cursor = events[-3]["sequence"]
    response = client.get(
        f"{path}/events/stream?after=1&follow=false", headers={"Last-Event-ID": str(cursor)},
    )
    assert response.status_code == 200
    assert response.headers["x-accel-buffering"] == "no"
    frames = response.text.strip().split("\n\n")
    audit = [frame for frame in frames if frame.startswith("event: audit")]
    assert len(audit) == 2
    assert all(int(frame.split("\n")[1][4:]) > cursor for frame in audit)
    snapshots = [frame for frame in frames if frame.startswith("event: snapshot")]
    assert len(snapshots) == 1 and "\nid:" not in snapshots[0]
    assert json.loads(snapshots[0].split("\ndata: ")[1]) == client.get(f"{path}/workspace").json()
    for header in ("-1", "abc", "1\n2", str(2**63), "9" * 100):
        assert client.get(
            f"{path}/events/stream?follow=false", headers={"Last-Event-ID": header},
        ).status_code == 422
    assert client.get("/api/cases/missing/events/stream?follow=false").status_code == 404


class StreamRequest:
    headers = {}
    disconnected = False

    async def is_disconnected(self):
        return self.disconnected


async def test_early_observation_while_start_pending_and_late_terminal_snapshots(monkeypatch):
    import model_to_harness_langgraph.api.streams as streams

    monkeypatch.setattr(streams, "POLL_SECONDS", 0)
    entered, release = asyncio.Event(), asyncio.Event()

    class Model(FakeModel):
        async def normalize(self, complaint):
            entered.set()
            await release.wait()
            return await super().normalize(complaint)

    service = runtime(model=Model())
    start = asyncio.create_task(
        service.start(StartCaseRequest(**START, existing_case_id="early-case"))
    )
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert not start.done()
        workspace = await service.workspace("early-case")
        assert workspace.state.complaint == START["complaint"]
        assert workspace.state.status == "running"
        request = StreamRequest()
        response = await audit_stream(request, service, "early-case", 0, True)
        first = await anext(response.body_iterator)
        assert "event: audit" in first and "run_started" in first
        request.disconnected = True
        await response.body_iterator.aclose()
    finally:
        release.set()
        started = await start
    await service.submit_approval(
        started.case_id, ApprovalRequest(checkpoint_id=started.checkpoint_id, **APPROVAL),
    )
    await service.resume(
        started.case_id, ResumeRequest(checkpoint_id=started.checkpoint_id, operator_id="operator"),
    )
    last = (await service.list_events(started.case_id))[-1].sequence
    response = await audit_stream(StreamRequest(), service, started.case_id, last, True)
    first = await anext(response.body_iterator)
    assert "event: snapshot" in first
    await service.audit.upsert_memory(
        START["customer_id"], started.case_id, {"refund_status": "late"}
    )
    second = await asyncio.wait_for(anext(response.body_iterator), 2)
    assert "event: snapshot" in second and '"refund_status":"late"' in second
    await response.body_iterator.aclose()


async def test_heartbeat_and_safe_stream_error(monkeypatch):
    import model_to_harness_langgraph.api.streams as streams

    service = runtime()
    started = await service.start(StartCaseRequest(**START))
    cursor = (await service.list_events(started.case_id))[-1].sequence
    monkeypatch.setattr(streams, "POLL_SECONDS", 0)
    monkeypatch.setattr(streams, "HEARTBEAT_SECONDS", 0)
    response = await audit_stream(StreamRequest(), service, started.case_id, cursor, True)
    assert (await anext(response.body_iterator)).startswith("event: snapshot")
    assert (await anext(response.body_iterator)).startswith(": keepalive")

    async def fail(*args):
        raise RuntimeError("SECRET database exception")

    monkeypatch.setattr(service, "list_events", fail)
    error = await anext(response.body_iterator)
    assert error.startswith("event: error") and "SECRET" not in error
    await response.body_iterator.aclose()
