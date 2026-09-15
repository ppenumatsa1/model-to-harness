from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from model_to_harness_shared.domain import (
    ApprovalDecision,
    ChargeRecord,
    DuplicateDecision,
    FailureCode,
    NotificationStatus,
    PolicyDecision,
    RefundStatus,
    ScenarioInput,
    TerminalStatus,
)
from model_to_harness_shared.evaluation_contracts import (
    EvaluationCase,
    ExpectedOutcome,
)


class FixtureModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BillingBehavior(FixtureModel):
    transient_read_failures: int = Field(default=0, ge=0)
    uncertain_refund_response_once: bool = False
    verification_count_override: int | None = Field(default=None, ge=0)


class ScenarioFixture(FixtureModel):
    fixture_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    scenario_input: ScenarioInput
    charges: tuple[ChargeRecord, ...]
    approval_decision: ApprovalDecision
    initially_paused: bool = False
    maximum_read_attempts: int = Field(default=2, ge=1)
    billing_behavior: BillingBehavior = BillingBehavior()
    expected: ExpectedOutcome
    tags: frozenset[str] = frozenset()


def _charge(
    charge_id: str,
    purchase_reference: str,
    *,
    amount: str = "42.50",
    day: int,
) -> ChargeRecord:
    return ChargeRecord(
        charge_id=charge_id,
        account_id="account-100",
        purchase_reference=purchase_reference,
        amount=Decimal(amount),
        currency="USD",
        charged_at=datetime(2026, 1, day, 12, tzinfo=timezone.utc),
    )


def _input(fixture_id: str, *, idempotency_key: str | None = None) -> ScenarioInput:
    return ScenarioInput(
        complaint_text="I was charged twice for the same purchase.",
        customer_id="customer-100",
        account_id="account-100",
        fixture_id=fixture_id,
        idempotency_key=idempotency_key,
    )


_DUPLICATE_CHARGES = (
    _charge("charge-100-a", "purchase-100", day=10),
    _charge("charge-100-b", "purchase-100", day=10),
)


SCENARIO_FIXTURES: dict[str, ScenarioFixture] = {
    "duplicate-confirmed": ScenarioFixture(
        fixture_id="duplicate-confirmed",
        description="Confirmed duplicate proceeds through approval to a verified refund.",
        scenario_input=_input("duplicate-confirmed", idempotency_key="refund-case-100"),
        charges=_DUPLICATE_CHARGES,
        approval_decision=ApprovalDecision.APPROVED,
        expected=ExpectedOutcome(
            duplicate_decision=DuplicateDecision.CONFIRMED,
            policy_decision=PolicyDecision.ELIGIBLE,
            approval_decision=ApprovalDecision.APPROVED,
            refund_status=RefundStatus.VERIFIED,
            notification_status=NotificationStatus.SENT,
            terminal_status=TerminalStatus.COMPLETED_REFUNDED,
        ),
        tags=frozenset({"happy-path", "approval", "refund"}),
    ),
    "no-duplicate": ScenarioFixture(
        fixture_id="no-duplicate",
        description="Distinct purchases close without a refund.",
        scenario_input=_input("no-duplicate"),
        charges=(
            _charge("charge-200-a", "purchase-200-a", day=10),
            _charge("charge-200-b", "purchase-200-b", day=11),
        ),
        approval_decision=ApprovalDecision.NOT_REQUIRED,
        expected=ExpectedOutcome(
            duplicate_decision=DuplicateDecision.NOT_FOUND,
            policy_decision=PolicyDecision.NOT_EVALUATED,
            approval_decision=ApprovalDecision.NOT_REQUIRED,
            refund_status=RefundStatus.NOT_REQUESTED,
            notification_status=NotificationStatus.NOT_SENT,
            terminal_status=TerminalStatus.COMPLETED_NO_REFUND,
        ),
        tags=frozenset({"no-duplicate"}),
    ),
    "approval-denied": ScenarioFixture(
        fixture_id="approval-denied",
        description="Eligible evidence is denied and closes without a refund.",
        scenario_input=_input("approval-denied", idempotency_key="refund-case-denied"),
        charges=_DUPLICATE_CHARGES,
        approval_decision=ApprovalDecision.DENIED,
        expected=ExpectedOutcome(
            duplicate_decision=DuplicateDecision.CONFIRMED,
            policy_decision=PolicyDecision.ELIGIBLE,
            approval_decision=ApprovalDecision.DENIED,
            refund_status=RefundStatus.NOT_REQUESTED,
            notification_status=NotificationStatus.NOT_SENT,
            terminal_status=TerminalStatus.CLOSED_DENIED,
        ),
        tags=frozenset({"approval", "denial"}),
    ),
    "transient-failure": ScenarioFixture(
        fixture_id="transient-failure",
        description="Billing reads exhaust the bounded retry and fail explicitly.",
        scenario_input=_input("transient-failure"),
        charges=_DUPLICATE_CHARGES,
        approval_decision=ApprovalDecision.NOT_REQUIRED,
        maximum_read_attempts=2,
        billing_behavior=BillingBehavior(transient_read_failures=2),
        expected=ExpectedOutcome(
            duplicate_decision=DuplicateDecision.INDETERMINATE,
            policy_decision=PolicyDecision.NOT_EVALUATED,
            approval_decision=ApprovalDecision.NOT_REQUIRED,
            refund_status=RefundStatus.NOT_REQUESTED,
            notification_status=NotificationStatus.NOT_SENT,
            terminal_status=TerminalStatus.FAILED,
            failure_code=FailureCode.TRANSIENT_BILLING_READ,
        ),
        tags=frozenset({"retry", "failure"}),
    ),
    "retry-safe-refund": ScenarioFixture(
        fixture_id="retry-safe-refund",
        description="An uncertain first response is retried with the same refund key.",
        scenario_input=_input("retry-safe-refund", idempotency_key="refund-retry-safe"),
        charges=_DUPLICATE_CHARGES,
        approval_decision=ApprovalDecision.APPROVED,
        billing_behavior=BillingBehavior(uncertain_refund_response_once=True),
        expected=ExpectedOutcome(
            duplicate_decision=DuplicateDecision.CONFIRMED,
            policy_decision=PolicyDecision.ELIGIBLE,
            approval_decision=ApprovalDecision.APPROVED,
            refund_status=RefundStatus.VERIFIED,
            notification_status=NotificationStatus.SENT,
            terminal_status=TerminalStatus.COMPLETED_REFUNDED,
        ),
        tags=frozenset({"retry", "idempotency"}),
    ),
    "resumed-approval": ScenarioFixture(
        fixture_id="resumed-approval",
        description="Approval arrives after a persisted pause and resumes the case.",
        scenario_input=_input("resumed-approval", idempotency_key="refund-resumed"),
        charges=_DUPLICATE_CHARGES,
        approval_decision=ApprovalDecision.APPROVED,
        initially_paused=True,
        expected=ExpectedOutcome(
            duplicate_decision=DuplicateDecision.CONFIRMED,
            policy_decision=PolicyDecision.ELIGIBLE,
            approval_decision=ApprovalDecision.APPROVED,
            refund_status=RefundStatus.VERIFIED,
            notification_status=NotificationStatus.SENT,
            terminal_status=TerminalStatus.COMPLETED_REFUNDED,
        ),
        tags=frozenset({"approval", "pause-resume"}),
    ),
    "verification-mismatch": ScenarioFixture(
        fixture_id="verification-mismatch",
        description="Refund verification mismatch routes to manual review.",
        scenario_input=_input(
            "verification-mismatch", idempotency_key="refund-verification-mismatch"
        ),
        charges=_DUPLICATE_CHARGES,
        approval_decision=ApprovalDecision.APPROVED,
        billing_behavior=BillingBehavior(verification_count_override=2),
        expected=ExpectedOutcome(
            duplicate_decision=DuplicateDecision.CONFIRMED,
            policy_decision=PolicyDecision.ELIGIBLE,
            approval_decision=ApprovalDecision.APPROVED,
            refund_status=RefundStatus.MANUAL_REVIEW,
            notification_status=NotificationStatus.NOT_SENT,
            terminal_status=TerminalStatus.MANUAL_REVIEW,
            failure_code=FailureCode.REFUND_VERIFICATION_MISMATCH,
        ),
        tags=frozenset({"verification", "manual-review"}),
    ),
}


EVALUATION_CASES: tuple[EvaluationCase, ...] = tuple(
    EvaluationCase(
        case_id=f"eval-{fixture.fixture_id}",
        fixture_id=fixture.fixture_id,
        description=fixture.description,
        expected=fixture.expected,
        tags=fixture.tags,
    )
    for fixture in SCENARIO_FIXTURES.values()
)


def get_fixture(fixture_id: str) -> ScenarioFixture:
    try:
        return SCENARIO_FIXTURES[fixture_id]
    except KeyError as error:
        raise KeyError(f"unknown scenario fixture: {fixture_id}") from error
