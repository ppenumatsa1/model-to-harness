from decimal import Decimal

from model_to_harness_shared.domain import ApprovalCommand, ApprovalDecision
from model_to_harness_shared.fixtures import get_fixture
from model_to_harness_shared.simulators import (
    ApprovalConflictError,
    ApprovalSimulator,
    BillingSimulator,
    RefundPolicySimulator,
)


def test_policy_approves_current_confirmed_duplicate() -> None:
    fixture = get_fixture("duplicate-confirmed")
    evidence = BillingSimulator(fixture.charges).detect_duplicate("account-100")

    assessment = RefundPolicySimulator().assess(evidence, fixture.charges)

    assert assessment.decision.value == "eligible"


def test_approval_request_and_resolution_are_repeatable() -> None:
    simulator = ApprovalSimulator()
    pending = simulator.request(
        case_id="case-100",
        amount=Decimal("42.50"),
        currency="USD",
    )
    assert simulator.request(
        case_id="case-100",
        amount=Decimal("42.50"),
        currency="USD",
    ) == pending

    command = ApprovalCommand(
        checkpoint_id=pending.checkpoint_id,
        decision=ApprovalDecision.APPROVED,
        reviewer_id="reviewer-1",
        reason="Evidence confirmed",
    )
    approved = simulator.resolve(command)

    assert approved.decision == ApprovalDecision.APPROVED
    assert simulator.resolve(command) == approved


def test_conflicting_approval_resolution_is_rejected() -> None:
    simulator = ApprovalSimulator()
    pending = simulator.request(
        case_id="case-conflict",
        amount=Decimal("42.50"),
        currency="USD",
    )
    simulator.resolve(
        ApprovalCommand(
            checkpoint_id=pending.checkpoint_id,
            decision=ApprovalDecision.APPROVED,
            reviewer_id="reviewer-1",
        )
    )

    try:
        simulator.resolve(
            ApprovalCommand(
                checkpoint_id=pending.checkpoint_id,
                decision=ApprovalDecision.DENIED,
                reviewer_id="reviewer-2",
            )
        )
    except ApprovalConflictError:
        pass
    else:
        raise AssertionError("conflicting approval resolution must fail")
