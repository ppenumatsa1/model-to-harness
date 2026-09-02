from model_to_harness_shared.domain import (
    ApprovalDecision,
    DuplicateDecision,
    FailureCode,
    NotificationStatus,
    PolicyDecision,
    RefundStatus,
    TerminalStatus,
    WorkflowOutcome,
)
from model_to_harness_shared.fixtures import EVALUATION_CASES, SCENARIO_FIXTURES


def test_required_scenario_fixtures_exist() -> None:
    assert set(SCENARIO_FIXTURES) == {
        "duplicate-confirmed",
        "no-duplicate",
        "approval-denied",
        "transient-failure",
        "retry-safe-refund",
        "resumed-approval",
        "verification-mismatch",
    }
    assert {case.fixture_id for case in EVALUATION_CASES} == set(SCENARIO_FIXTURES)


def test_expected_outcome_compares_only_normalized_business_fields() -> None:
    expected = SCENARIO_FIXTURES["duplicate-confirmed"].expected
    outcome = WorkflowOutcome(
        case_id="framework-case-id",
        run_id="framework-run-id",
        duplicate_decision=DuplicateDecision.CONFIRMED,
        policy_decision=PolicyDecision.ELIGIBLE,
        approval_decision=ApprovalDecision.APPROVED,
        refund_status=RefundStatus.VERIFIED,
        refund_id="refund-123",
        notification_status=NotificationStatus.SENT,
        terminal_status=TerminalStatus.COMPLETED_REFUNDED,
        failure_code=FailureCode.NONE,
    )

    assert expected.compare(outcome) == {}
