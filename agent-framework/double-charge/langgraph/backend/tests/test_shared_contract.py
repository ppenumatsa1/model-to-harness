import pytest
from fakes import FakeModel
from langgraph.checkpoint.memory import InMemorySaver
from model_to_harness_langgraph.audit import InMemoryAuditRepository
from model_to_harness_langgraph.contracts import ApprovalRequest, StartCaseRequest
from model_to_harness_langgraph.domain_gateway import SharedDomainGateway
from model_to_harness_langgraph.service import WorkflowService
from model_to_harness_langgraph.workflow import DoubleChargeWorkflow
from model_to_harness_shared import EVALUATION_CASES, get_fixture


@pytest.mark.parametrize("evaluation_case", EVALUATION_CASES, ids=lambda case: case.fixture_id)
async def test_shared_fixture_matches_framework_neutral_outcome(evaluation_case):
    fixture = get_fixture(evaluation_case.fixture_id)
    audit = InMemoryAuditRepository()
    workflow = DoubleChargeWorkflow(
        audit=audit,
        gateway=SharedDomainGateway(),
        model=FakeModel(),
        checkpointer=InMemorySaver(),
    )
    service = WorkflowService(workflow, audit)
    scenario = fixture.scenario_input
    started = await service.start(
        StartCaseRequest(
            complaint=scenario.complaint_text,
            customer_id=scenario.customer_id,
            scenario_id=fixture.fixture_id,
            idempotency_key=scenario.idempotency_key,
        )
    )
    if started.status == "paused":
        await service.submit_approval(
            started.case_id,
            ApprovalRequest(
                checkpoint_id=started.checkpoint_id or "",
                decision="deny"
                if str(fixture.approval_decision) == "denied"
                else "approve",
                reviewer_id="shared-contract-test",
            ),
        )
        await service.resume(started.case_id)

    outcome = (await service.get_case(started.case_id)).outcome
    assert outcome is not None
    expected = evaluation_case.expected.model_dump(mode="json")
    actual = outcome.model_dump(mode="json")
    for field in expected:
        assert actual[field] == expected[field]


async def test_shared_simulator_state_is_isolated_per_run():
    fixture = get_fixture("retry-safe-refund")
    audit = InMemoryAuditRepository()
    workflow = DoubleChargeWorkflow(
        audit=audit,
        gateway=SharedDomainGateway(),
        model=FakeModel(),
        checkpointer=InMemorySaver(),
    )
    service = WorkflowService(workflow, audit)

    for suffix in ("one", "two"):
        started = await service.start(
            StartCaseRequest(
                complaint=fixture.scenario_input.complaint_text,
                customer_id=fixture.scenario_input.customer_id,
                scenario_id=fixture.fixture_id,
                idempotency_key=f"refund-{suffix}",
            )
        )
        await service.submit_approval(
            started.case_id,
            ApprovalRequest(
                checkpoint_id=started.checkpoint_id or "",
                decision="approve",
                reviewer_id="isolation-test",
            ),
        )
        await service.resume(started.case_id)
        events = await service.list_events(started.case_id)
        assert any(event.event_type == "tool_call_retried" for event in events)
