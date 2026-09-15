from pydantic import BaseModel, ConfigDict, Field

from model_to_harness_shared.domain.checkout import (
    CheckoutApproval,
    CheckoutApprovalDecision,
    CheckoutFailureCode,
    CheckoutOrderStatus,
    CheckoutPaymentStatus,
    CheckoutTerminalStatus,
    DiagnosticDisposition,
    InventoryReservationRecord,
    InventoryReservationStatus,
    OrderRecord,
    PaymentAttemptRecord,
    RemediationStatus,
)
from model_to_harness_shared.evaluation_contracts.checkout import (
    CheckoutEvaluationCase,
    ExpectedCheckoutOutcome,
)


class CheckoutFixtureModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CheckoutSimulatorBehavior(CheckoutFixtureModel):
    diagnostic_read_failures: int = Field(default=0, ge=0)
    uncertain_remediation_response_once: bool = False
    resulting_reservation_status: InventoryReservationStatus | None = None


class CheckoutScenarioFixture(CheckoutFixtureModel):
    fixture_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    order: OrderRecord
    payment_attempt: PaymentAttemptRecord
    reservation: InventoryReservationRecord
    approval: CheckoutApproval
    behavior: CheckoutSimulatorBehavior = CheckoutSimulatorBehavior()
    expected: ExpectedCheckoutOutcome
    tags: frozenset[str] = frozenset()


def _records(
    fixture_id: str,
    *,
    payment_status: CheckoutPaymentStatus,
    reservation_status: InventoryReservationStatus,
) -> tuple[OrderRecord, PaymentAttemptRecord, InventoryReservationRecord]:
    order_id = f"order-{fixture_id}"
    return (
        OrderRecord(
            order_id=order_id,
            customer_id="customer-100",
            status=CheckoutOrderStatus.CHECKOUT_FAILED,
        ),
        PaymentAttemptRecord(
            payment_attempt_id=f"payment-{fixture_id}",
            order_id=order_id,
            status=payment_status,
            amount_minor=4250,
            currency="USD",
        ),
        InventoryReservationRecord(
            reservation_id=f"reservation-{fixture_id}",
            order_id=order_id,
            sku="sku-100",
            quantity=1,
            status=reservation_status,
        ),
    )


def _approval(
    fixture_id: str, decision: CheckoutApprovalDecision
) -> CheckoutApproval:
    return CheckoutApproval(
        approval_id=f"approval-{fixture_id}",
        order_id=f"order-{fixture_id}",
        decision=decision,
        reviewer_id=(
            "reviewer-100"
            if decision
            in {CheckoutApprovalDecision.APPROVED, CheckoutApprovalDecision.DENIED}
            else None
        ),
        reason="Fixture decision" if decision != CheckoutApprovalDecision.NOT_REQUIRED else None,
    )


def _fixture(
    fixture_id: str,
    description: str,
    *,
    payment_status: CheckoutPaymentStatus,
    reservation_status: InventoryReservationStatus,
    approval_decision: CheckoutApprovalDecision,
    expected: ExpectedCheckoutOutcome,
    behavior: CheckoutSimulatorBehavior | None = None,
    tags: frozenset[str] = frozenset(),
) -> CheckoutScenarioFixture:
    order, payment_attempt, reservation = _records(
        fixture_id,
        payment_status=payment_status,
        reservation_status=reservation_status,
    )
    return CheckoutScenarioFixture(
        fixture_id=fixture_id,
        description=description,
        order=order,
        payment_attempt=payment_attempt,
        reservation=reservation,
        approval=_approval(fixture_id, approval_decision),
        behavior=behavior or CheckoutSimulatorBehavior(),
        expected=expected,
        tags=tags,
    )


CHECKOUT_SCENARIO_FIXTURES: dict[str, CheckoutScenarioFixture] = {
    "recoverable-inventory-reservation": _fixture(
        "recoverable-inventory-reservation",
        "An expired inventory reservation is safely recreated.",
        payment_status=CheckoutPaymentStatus.AUTHORIZED,
        reservation_status=InventoryReservationStatus.EXPIRED,
        approval_decision=CheckoutApprovalDecision.NOT_REQUIRED,
        expected=ExpectedCheckoutOutcome(
            diagnostic_disposition=DiagnosticDisposition.RECOVER_INVENTORY,
            approval_decision=CheckoutApprovalDecision.NOT_REQUIRED,
            remediation_status=RemediationStatus.APPLIED,
            verification_result=True,
            terminal_status=CheckoutTerminalStatus.RECOVERED,
        ),
        tags=frozenset({"inventory", "recovery"}),
    ),
    "captured-payment-approved-remediation": _fixture(
        "captured-payment-approved-remediation",
        "A captured payment is refunded only after customer-impacting approval.",
        payment_status=CheckoutPaymentStatus.CAPTURED,
        reservation_status=InventoryReservationStatus.EXPIRED,
        approval_decision=CheckoutApprovalDecision.APPROVED,
        expected=ExpectedCheckoutOutcome(
            diagnostic_disposition=DiagnosticDisposition.REFUND_CAPTURED_PAYMENT,
            approval_decision=CheckoutApprovalDecision.APPROVED,
            remediation_status=RemediationStatus.APPLIED,
            verification_result=True,
            terminal_status=CheckoutTerminalStatus.RECOVERED,
        ),
        tags=frozenset({"payment", "approval"}),
    ),
    "payment-pending-manual-review": _fixture(
        "payment-pending-manual-review",
        "A pending payment is routed to manual review without remediation.",
        payment_status=CheckoutPaymentStatus.PENDING,
        reservation_status=InventoryReservationStatus.EXPIRED,
        approval_decision=CheckoutApprovalDecision.NOT_REQUIRED,
        expected=ExpectedCheckoutOutcome(
            diagnostic_disposition=DiagnosticDisposition.MANUAL_REVIEW,
            approval_decision=CheckoutApprovalDecision.NOT_REQUIRED,
            terminal_status=CheckoutTerminalStatus.MANUAL_REVIEW,
        ),
        tags=frozenset({"payment", "manual-review"}),
    ),
    "diagnostic-read-failure": _fixture(
        "diagnostic-read-failure",
        "A deterministic diagnostic read failure is terminally reported.",
        payment_status=CheckoutPaymentStatus.AUTHORIZED,
        reservation_status=InventoryReservationStatus.EXPIRED,
        approval_decision=CheckoutApprovalDecision.NOT_REQUIRED,
        behavior=CheckoutSimulatorBehavior(diagnostic_read_failures=1),
        expected=ExpectedCheckoutOutcome(
            diagnostic_disposition=DiagnosticDisposition.NO_ACTION,
            approval_decision=CheckoutApprovalDecision.NOT_REQUIRED,
            terminal_status=CheckoutTerminalStatus.FAILED,
            failure_code=CheckoutFailureCode.DIAGNOSTIC_READ_FAILED,
        ),
        tags=frozenset({"diagnostic", "failure"}),
    ),
    "denied-approval": _fixture(
        "denied-approval",
        "A captured-payment remediation remains unapplied when approval is denied.",
        payment_status=CheckoutPaymentStatus.CAPTURED,
        reservation_status=InventoryReservationStatus.EXPIRED,
        approval_decision=CheckoutApprovalDecision.DENIED,
        expected=ExpectedCheckoutOutcome(
            diagnostic_disposition=DiagnosticDisposition.REFUND_CAPTURED_PAYMENT,
            approval_decision=CheckoutApprovalDecision.DENIED,
            terminal_status=CheckoutTerminalStatus.CLOSED_DENIED,
        ),
        tags=frozenset({"approval", "denial"}),
    ),
    "uncertain-remediation-recovery": _fixture(
        "uncertain-remediation-recovery",
        "The first remediation response is uncertain but the same operation is recoverable.",
        payment_status=CheckoutPaymentStatus.AUTHORIZED,
        reservation_status=InventoryReservationStatus.EXPIRED,
        approval_decision=CheckoutApprovalDecision.NOT_REQUIRED,
        behavior=CheckoutSimulatorBehavior(uncertain_remediation_response_once=True),
        expected=ExpectedCheckoutOutcome(
            diagnostic_disposition=DiagnosticDisposition.RECOVER_INVENTORY,
            approval_decision=CheckoutApprovalDecision.NOT_REQUIRED,
            remediation_status=RemediationStatus.APPLIED,
            verification_result=True,
            terminal_status=CheckoutTerminalStatus.RECOVERED,
        ),
        tags=frozenset({"idempotency", "recovery"}),
    ),
    "verification-mismatch": _fixture(
        "verification-mismatch",
        "A remediation response cannot override mismatching authoritative inventory.",
        payment_status=CheckoutPaymentStatus.AUTHORIZED,
        reservation_status=InventoryReservationStatus.EXPIRED,
        approval_decision=CheckoutApprovalDecision.NOT_REQUIRED,
        behavior=CheckoutSimulatorBehavior(
            resulting_reservation_status=InventoryReservationStatus.RELEASED
        ),
        expected=ExpectedCheckoutOutcome(
            diagnostic_disposition=DiagnosticDisposition.RECOVER_INVENTORY,
            approval_decision=CheckoutApprovalDecision.NOT_REQUIRED,
            remediation_status=RemediationStatus.APPLIED,
            verification_result=False,
            terminal_status=CheckoutTerminalStatus.MANUAL_REVIEW,
            failure_code=CheckoutFailureCode.VERIFICATION_MISMATCH,
        ),
        tags=frozenset({"verification", "manual-review"}),
    ),
}


CHECKOUT_EVALUATION_CASES: tuple[CheckoutEvaluationCase, ...] = tuple(
    CheckoutEvaluationCase(
        case_id=f"checkout-eval-{fixture.fixture_id}",
        fixture_id=fixture.fixture_id,
        description=fixture.description,
        expected=fixture.expected,
        tags=fixture.tags,
    )
    for fixture in CHECKOUT_SCENARIO_FIXTURES.values()
)


def get_checkout_fixture(fixture_id: str) -> CheckoutScenarioFixture:
    try:
        return CHECKOUT_SCENARIO_FIXTURES[fixture_id]
    except KeyError as error:
        raise KeyError(f"unknown checkout scenario fixture: {fixture_id}") from error
