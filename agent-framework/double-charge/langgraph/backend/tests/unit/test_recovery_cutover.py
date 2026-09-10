import asyncio

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from model_to_harness_langgraph.application.records import ApprovalRequest, StartCaseRequest
from model_to_harness_langgraph.application.service import InvalidCommandError, WorkflowService
from model_to_harness_langgraph.graph.runner import DoubleChargeWorkflow
from model_to_harness_langgraph.infrastructure.domain_gateway import ToolResult
from model_to_harness_langgraph.testing.audit import InMemoryAuditRepository
from model_to_harness_langgraph.testing.fakes import FakeDomainGateway, FakeModel


def service(audit, saver, gateway=None):
    return WorkflowService(
        DoubleChargeWorkflow(
            audit=audit,
            checkpointer=saver,
            gateway=gateway or FakeDomainGateway(),
            model=FakeModel(),
        ),
        audit,
    )


def request():
    return StartCaseRequest(
        complaint="I was charged twice.",
        customer_id="customer",
        existing_case_id="crash-case",
    )


async def approve(runtime, started):
    await runtime.submit_approval(
        started.case_id,
        ApprovalRequest(
            checkpoint_id=started.checkpoint_id,
            decision="approve",
            reviewer_id="reviewer",
        ),
    )


async def test_interrupt_checkpoint_reconciles_after_audit_update_crash(monkeypatch):
    audit, saver = InMemoryAuditRepository(), InMemorySaver()
    first = service(audit, saver)
    update = audit.update_run

    async def fail(*args):
        raise RuntimeError("worker lost after native checkpoint")

    monkeypatch.setattr(audit, "update_run", fail)
    with pytest.raises(RuntimeError, match="worker lost"):
        await first.start(request())
    monkeypatch.setattr(audit, "update_run", update)
    restarted = service(audit, saver)
    interrupted = await restarted.continue_run("crash-case")
    assert interrupted.status == "paused" and interrupted.checkpoint_id
    await approve(restarted, interrupted)
    result = await restarted.resume("crash-case")
    assert result.status == "completed"
    events = await restarted.list_events("crash-case")
    assert sum(e.event_type == "human_approval_requested" for e in events) == 1
    assert sum(e.event_type == "human_approval_resolved" for e in events) == 1


async def test_completed_checkpoint_reconciles_without_repeating_verified_effect(monkeypatch):
    audit, saver, gateway = InMemoryAuditRepository(), InMemorySaver(), FakeDomainGateway()
    first = service(audit, saver, gateway)
    started = await first.start(request())
    await approve(first, started)
    persist = first.results.persist

    async def fail_terminal(result):
        if result.get("terminal_status"):
            raise RuntimeError("worker lost before application result")
        return await persist(result)

    monkeypatch.setattr(first.results, "persist", fail_terminal)
    with pytest.raises(RuntimeError, match="worker lost"):
        await first.resume(started.case_id)
    assert await audit.get_pending_approval(started.run_id)
    before = sum(gateway.refund_calls.values())
    resumed = await service(audit, saver, gateway).resume(started.case_id)
    assert resumed.status == "completed"
    assert sum(gateway.refund_calls.values()) == before == 1
    assert await audit.get_pending_approval(started.run_id) is None
    assert len(audit.refunds) == 1


async def test_audit_completion_before_approval_consumption_crash_is_recoverable(monkeypatch):
    audit, saver = InMemoryAuditRepository(), InMemorySaver()
    first = service(audit, saver)
    started = await first.start(request())
    await approve(first, started)
    consume = audit.consume_approval

    async def fail(*args):
        raise RuntimeError("approval consumption interrupted")

    monkeypatch.setattr(audit, "consume_approval", fail)
    with pytest.raises(RuntimeError, match="interrupted"):
        await first.resume(started.case_id)
    assert (await audit.get_run_by_case(started.case_id))["status"] == "completed"
    monkeypatch.setattr(audit, "consume_approval", consume)
    assert (await service(audit, saver).resume(started.case_id)).status == "completed"
    assert await audit.get_pending_approval(started.run_id) is None


async def test_concurrent_resume_rejected_and_lock_released():
    audit, saver = InMemoryAuditRepository(), InMemorySaver()
    entered, release = asyncio.Event(), asyncio.Event()

    class Gateway(FakeDomainGateway):
        async def submit_refund(self, *args):
            entered.set()
            await release.wait()
            return await super().submit_refund(*args)

    gateway = Gateway()
    first, second = service(audit, saver, gateway), service(audit, saver, gateway)
    started = await first.start(request())
    await approve(first, started)
    task = asyncio.create_task(first.resume(started.case_id))
    await asyncio.wait_for(entered.wait(), 2)
    try:
        with pytest.raises(InvalidCommandError, match="Another command"):
            await second.resume(started.case_id)
    finally:
        release.set()
        await task
    assert sum(gateway.refund_calls.values()) == 1
    async with audit.command_lock(started.case_id):
        pass


async def test_verification_must_match_the_durable_refund_id():
    class Gateway(FakeDomainGateway):
        async def verify_refund(self, *args):
            return ToolResult(ok=True, value={"matching_refunds": 1, "refund_id": "other-refund"})

    runtime = service(InMemoryAuditRepository(), InMemorySaver(), Gateway())
    started = await runtime.start(request())
    await approve(runtime, started)
    result = await runtime.resume(started.case_id)
    assert result.status == "manual_review"
    case = await runtime.get_case(started.case_id)
    assert case.workflow_state["failure_code"] == "VERIFY_MISMATCH"
    assert case.outcome.failure_code == "refund_verification_mismatch"


async def test_notification_receipt_prevents_replay_after_checkpoint_loss():
    audit, saver = InMemoryAuditRepository(), InMemorySaver()

    class Gateway(FakeDomainGateway):
        calls = 0

        async def send_notification(self, *args):
            self.calls += 1
            return await super().send_notification(*args)

    gateway = Gateway()
    runtime = service(audit, saver, gateway)
    started = await runtime.start(request())
    await approve(runtime, started)
    await runtime.resume(started.case_id)
    state = await runtime.workflow.snapshot(started.run_id)
    replay = await runtime.workflow.notify_customer(state)
    assert replay["notification_status"] == "sent"
    assert gateway.calls == 1


async def test_raw_native_resume_cannot_bypass_the_durable_approval_command():
    from langgraph.types import Command
    from model_to_harness_langgraph.application.ports import ApprovalCommandConflictError

    audit, saver = InMemoryAuditRepository(), InMemorySaver()
    runtime = service(audit, saver)
    started = await runtime.start(request())
    with pytest.raises(ApprovalCommandConflictError, match="recorded approval"):
        await runtime.workflow.graph.ainvoke(
            Command(resume={"decision": "approve", "reviewer_id": "unrecorded"}),
            config=runtime.workflow.config(started.run_id),
        )
    assert not audit.refunds


@pytest.mark.parametrize("durable_receipt_written", [False, True])
async def test_refund_effect_and_receipt_crash_windows_reconcile(
    monkeypatch, durable_receipt_written
):
    audit, saver, gateway = InMemoryAuditRepository(), InMemorySaver(), FakeDomainGateway()
    runtime = service(audit, saver, gateway)
    started = await runtime.start(request())
    await approve(runtime, started)
    record = audit.record_refund

    async def crash(refund):
        if durable_receipt_written:
            await record(refund)
        raise RuntimeError("worker lost after external acceptance")

    monkeypatch.setattr(audit, "record_refund", crash)
    with pytest.raises(RuntimeError, match="external acceptance"):
        await runtime.resume(started.case_id)
    assert len(gateway.refunds) == 1
    monkeypatch.setattr(audit, "record_refund", record)
    restarted_gateway = FakeDomainGateway() if durable_receipt_written else gateway
    reconstructed = service(audit, saver, restarted_gateway)
    assert (await reconstructed.resume(started.case_id)).status == "completed"
    assert len(audit.refunds) == 1
    assert (await reconstructed.get_case(started.case_id)).outcome.refund_status == "verified"
    if durable_receipt_written:
        assert not restarted_gateway.refund_calls
    else:
        assert sum(gateway.refund_calls.values()) == 2
        assert len(gateway.refunds) == 1
