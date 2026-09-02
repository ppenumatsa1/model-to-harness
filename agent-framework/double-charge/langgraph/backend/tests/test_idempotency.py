import pytest
from fakes import FakeDomainGateway, FakeModel
from langgraph.checkpoint.memory import InMemorySaver
from model_to_harness_langgraph.audit import (
    ApprovalCommandConflictError,
    InMemoryAuditRepository,
    RefundIdempotencyConflictError,
)
from model_to_harness_langgraph.contracts import ApprovalRequest, StartCaseRequest
from model_to_harness_langgraph.domain_gateway import SharedDomainGateway
from model_to_harness_langgraph.service import InvalidCommandError, WorkflowService
from model_to_harness_langgraph.workflow import DoubleChargeWorkflow

APPROVAL = {
    "checkpoint_id": "checkpoint-1",
    "decision": "approve",
    "reviewer_id": "reviewer-1",
    "reason": "Evidence confirmed",
}


async def test_in_memory_approval_is_insert_once_and_consumption_is_not_reset():
    repository = InMemoryAuditRepository()

    await repository.save_approval("run-1", APPROVAL)
    await repository.save_approval("run-1", APPROVAL)
    await repository.consume_approval("run-1")
    await repository.save_approval("run-1", APPROVAL)

    assert await repository.get_pending_approval("run-1") is None
    for field, changed in (
        ("checkpoint_id", "checkpoint-2"),
        ("decision", "deny"),
        ("reviewer_id", "reviewer-2"),
        ("reason", "Different reason"),
    ):
        conflicting = {**APPROVAL, field: changed}
        with pytest.raises(ApprovalCommandConflictError):
            await repository.save_approval("run-1", conflicting)
    assert repository.approvals["run-1"]["decision"] == "approve"
    assert repository.approvals["run-1"]["consumed"] is True


async def test_service_accepts_identical_approval_retry_and_rejects_mutation():
    audit = InMemoryAuditRepository()
    workflow = DoubleChargeWorkflow(
        audit=audit,
        gateway=FakeDomainGateway(),
        model=FakeModel(),
        checkpointer=InMemorySaver(),
    )
    service = WorkflowService(workflow, audit)
    started = await service.start(
        StartCaseRequest(
            complaint="I was charged twice for the same purchase.",
            customer_id="customer-1",
        )
    )
    command = ApprovalRequest(
        checkpoint_id=started.checkpoint_id or "",
        decision="approve",
        reviewer_id="reviewer-1",
        reason="Evidence confirmed",
    )

    await service.submit_approval(started.case_id, command)
    await service.submit_approval(started.case_id, command)
    with pytest.raises(InvalidCommandError, match="different approval command"):
        await service.submit_approval(
            started.case_id,
            command.model_copy(update={"decision": "deny"}),
        )
    resumed = await service.resume(started.case_id)
    await service.submit_approval(started.case_id, command)
    with pytest.raises(InvalidCommandError, match="different approval command"):
        await service.submit_approval(
            started.case_id,
            command.model_copy(update={"reason": "Changed after resume"}),
        )

    assert resumed.status == "completed"
    outcome = (await service.get_case(started.case_id)).outcome
    assert outcome and outcome.approval_decision == "approved"
    events = await service.list_events(started.case_id)
    assert sum(event.event_type == "approval_command_recorded" for event in events) == 1


async def test_in_memory_refund_is_insert_once_with_fingerprint_conflict():
    repository = InMemoryAuditRepository()
    refund = {
        "idempotency_key": "refund-key",
        "request_fingerprint": "fingerprint-a",
        "refund_id": "refund-1",
        "case_id": "case-1",
        "run_id": "run-1",
        "customer_id": "customer-1",
    }

    assert await repository.record_refund(refund) == refund
    assert await repository.record_refund(refund) == refund
    with pytest.raises(RefundIdempotencyConflictError):
        await repository.record_refund(
            {**refund, "request_fingerprint": "fingerprint-b"}
        )
    with pytest.raises(RefundIdempotencyConflictError):
        await repository.record_refund(
            {**refund, "idempotency_key": "other-key"}
        )
    assert len(repository.refunds) == 1


async def test_uncertain_refund_survives_gateway_and_workflow_reconstruction():
    audit = InMemoryAuditRepository()
    checkpointer = InMemorySaver()
    workflow1 = DoubleChargeWorkflow(
        audit=audit,
        gateway=SharedDomainGateway(),
        model=FakeModel(),
        checkpointer=checkpointer,
    )
    service1 = WorkflowService(workflow1, audit)
    started = await service1.start(
        StartCaseRequest(
            complaint="I was charged twice for the same purchase.",
            customer_id="customer-1",
            scenario_id="retry-safe-refund",
            idempotency_key="durable-reconstruction-key",
        )
    )

    workflow2 = DoubleChargeWorkflow(
        audit=audit,
        gateway=SharedDomainGateway(),
        model=FakeModel(),
        checkpointer=checkpointer,
        interrupt_after=["submit_refund"],
    )
    service2 = WorkflowService(workflow2, audit)
    await service2.submit_approval(
        started.case_id,
        ApprovalRequest(
            checkpoint_id=started.checkpoint_id or "",
            decision="approve",
            reviewer_id="reviewer-1",
        ),
    )
    interrupted = await service2.resume(started.case_id)
    assert interrupted.status == "running"
    assert len(audit.refunds) == 1

    workflow3 = DoubleChargeWorkflow(
        audit=audit,
        gateway=SharedDomainGateway(),
        model=FakeModel(),
        checkpointer=checkpointer,
    )
    service3 = WorkflowService(workflow3, audit)
    completed = await service3.continue_run(started.case_id)

    assert completed.status == "completed"
    assert len(audit.refunds) == 1
    outcome = (await service3.get_case(started.case_id)).outcome
    assert outcome and outcome.refund_status == "verified"
