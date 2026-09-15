import pytest
from model_to_harness_shared import (
    CHECKOUT_EVALUATION_CASES,
    CHECKOUT_SCENARIO_FIXTURES,
    CheckoutApprovalDecision,
    CheckoutApprovalRequiredError,
    CheckoutFailureCode,
    CheckoutOrderStatus,
    CheckoutPaymentStatus,
    CheckoutRecoveryOutcome,
    CheckoutRemediationPreconditionError,
    CheckoutSimulator,
    CheckoutTerminalStatus,
    DiagnosticDisposition,
    InventoryReservationStatus,
    RemediationAction,
    RemediationRequest,
    RemediationStatus,
    UncertainCheckoutRemediationResponseError,
    checkout_remediation_fingerprint,
    get_checkout_fixture,
)
from model_to_harness_shared.simulators import CheckoutRemediationConflictError


def _simulator(fixture_id: str) -> CheckoutSimulator:
    fixture = get_checkout_fixture(fixture_id)
    return CheckoutSimulator(
        order=fixture.order,
        payment_attempt=fixture.payment_attempt,
        reservation=fixture.reservation,
        diagnostic_read_failures=fixture.behavior.diagnostic_read_failures,
        uncertain_remediation_response_once=(fixture.behavior.uncertain_remediation_response_once),
        resulting_reservation_status=fixture.behavior.resulting_reservation_status,
    )


def _inventory_request(fixture_id: str, operation_id: str) -> RemediationRequest:
    fixture = get_checkout_fixture(fixture_id)
    return RemediationRequest(
        operation_id=operation_id,
        request_fingerprint=checkout_remediation_fingerprint(
            order_id=fixture.order.order_id,
            action=RemediationAction.RECREATE_INVENTORY_RESERVATION,
            reservation_id=fixture.reservation.reservation_id,
        ),
        order_id=fixture.order.order_id,
        action=RemediationAction.RECREATE_INVENTORY_RESERVATION,
        reservation_id=fixture.reservation.reservation_id,
    )


def test_checkout_fixtures_cover_the_recovery_contract() -> None:
    assert set(CHECKOUT_SCENARIO_FIXTURES) == {
        "recoverable-inventory-reservation",
        "captured-payment-approved-remediation",
        "payment-pending-manual-review",
        "diagnostic-read-failure",
        "denied-approval",
        "uncertain-remediation-recovery",
        "verification-mismatch",
    }
    assert {case.fixture_id for case in CHECKOUT_EVALUATION_CASES} == set(
        CHECKOUT_SCENARIO_FIXTURES
    )
    assert (
        get_checkout_fixture("captured-payment-approved-remediation").approval.decision
        == CheckoutApprovalDecision.APPROVED
    )
    assert (
        get_checkout_fixture("denied-approval").approval.decision == CheckoutApprovalDecision.DENIED
    )


def test_remediation_is_idempotent_and_rejects_conflicting_fingerprints() -> None:
    simulator = _simulator("recoverable-inventory-reservation")
    request = _inventory_request("recoverable-inventory-reservation", "operation-100")

    first = simulator.submit_remediation(request)
    assert simulator.submit_remediation(request) == first
    assert len(simulator.remediation_results) == 1

    fixture = get_checkout_fixture("recoverable-inventory-reservation")
    conflicting_request = RemediationRequest(
        operation_id=request.operation_id,
        request_fingerprint=checkout_remediation_fingerprint(
            order_id=fixture.order.order_id,
            action=RemediationAction.REFUND_CAPTURED_PAYMENT,
            payment_attempt_id=fixture.payment_attempt.payment_attempt_id,
        ),
        order_id=fixture.order.order_id,
        action=RemediationAction.REFUND_CAPTURED_PAYMENT,
        payment_attempt_id=fixture.payment_attempt.payment_attempt_id,
    )
    with pytest.raises(CheckoutRemediationConflictError, match="operation ID"):
        simulator.submit_remediation(conflicting_request)


def test_uncertain_response_is_recovered_with_the_same_operation_and_fingerprint() -> None:
    simulator = _simulator("uncertain-remediation-recovery")
    request = _inventory_request("uncertain-remediation-recovery", "operation-uncertain")

    with pytest.raises(UncertainCheckoutRemediationResponseError):
        simulator.submit_remediation(request)

    recovered = simulator.submit_remediation(request)
    verification = simulator.verify(
        operation_id=request.operation_id,
        expected_order_status=CheckoutOrderStatus.CONFIRMED,
        expected_payment_status=CheckoutPaymentStatus.AUTHORIZED,
        expected_reservation_status=InventoryReservationStatus.RESERVED,
        expected_remediation_status=RemediationStatus.APPLIED,
    )

    assert recovered.operation_id == request.operation_id
    assert recovered.request_fingerprint == request.request_fingerprint
    assert len(simulator.remediation_results) == 1
    assert verification.verified is True


def test_snapshot_rehydrates_applied_remediation_without_reissuing_it() -> None:
    simulator = _simulator("recoverable-inventory-reservation")
    request = _inventory_request("recoverable-inventory-reservation", "operation-rehydrated")
    first = simulator.submit_remediation(request)

    rehydrated = CheckoutSimulator.from_snapshot(simulator.snapshot())

    assert rehydrated.submit_remediation(request) == first
    assert len(rehydrated.remediation_results) == 1
    assert rehydrated.verify(
        operation_id=request.operation_id,
        expected_order_status=CheckoutOrderStatus.CONFIRMED,
        expected_payment_status=CheckoutPaymentStatus.AUTHORIZED,
        expected_reservation_status=InventoryReservationStatus.RESERVED,
        expected_remediation_status=RemediationStatus.APPLIED,
    ).verified


def test_captured_payment_remediation_requires_and_uses_approved_decision() -> None:
    fixture = get_checkout_fixture("captured-payment-approved-remediation")
    simulator = _simulator("captured-payment-approved-remediation")
    request = RemediationRequest(
        operation_id="operation-captured-payment",
        request_fingerprint=checkout_remediation_fingerprint(
            order_id=fixture.order.order_id,
            action=RemediationAction.REFUND_CAPTURED_PAYMENT,
            payment_attempt_id=fixture.payment_attempt.payment_attempt_id,
        ),
        order_id=fixture.order.order_id,
        action=RemediationAction.REFUND_CAPTURED_PAYMENT,
        payment_attempt_id=fixture.payment_attempt.payment_attempt_id,
    )

    with pytest.raises(CheckoutApprovalRequiredError):
        simulator.submit_remediation(request)

    simulator.submit_remediation(request, approval=fixture.approval)
    verification = simulator.verify(
        operation_id=request.operation_id,
        expected_order_status=CheckoutOrderStatus.CANCELLED,
        expected_payment_status=CheckoutPaymentStatus.REFUNDED,
        expected_reservation_status=InventoryReservationStatus.RELEASED,
        expected_remediation_status=RemediationStatus.APPLIED,
    )

    assert verification.verified is True


def test_successful_verification_reads_authoritative_final_records() -> None:
    simulator = _simulator("recoverable-inventory-reservation")
    request = _inventory_request("recoverable-inventory-reservation", "operation-verified")
    simulator.submit_remediation(request)

    verification = simulator.verify(
        operation_id=request.operation_id,
        expected_order_status=CheckoutOrderStatus.CONFIRMED,
        expected_payment_status=CheckoutPaymentStatus.AUTHORIZED,
        expected_reservation_status=InventoryReservationStatus.RESERVED,
        expected_remediation_status=RemediationStatus.APPLIED,
    )

    assert verification.verified is True
    assert verification.evidence.actual_order_status == CheckoutOrderStatus.CONFIRMED
    assert verification.evidence.actual_reservation_status == (InventoryReservationStatus.RESERVED)


def test_pending_payment_routes_to_manual_review_without_remediation() -> None:
    fixture = get_checkout_fixture("payment-pending-manual-review")
    diagnostic = _simulator("payment-pending-manual-review").read_diagnostic()
    outcome = CheckoutRecoveryOutcome(
        order_id=fixture.order.order_id,
        diagnostic_disposition=diagnostic.disposition,
        approval_decision=fixture.approval.decision,
        terminal_status=CheckoutTerminalStatus.MANUAL_REVIEW,
    )

    assert diagnostic.disposition == DiagnosticDisposition.MANUAL_REVIEW
    assert fixture.expected.compare(outcome) == {}


def test_verification_mismatch_does_not_claim_recovery() -> None:
    fixture = get_checkout_fixture("verification-mismatch")
    simulator = _simulator("verification-mismatch")
    request = _inventory_request("verification-mismatch", "operation-mismatch")
    result = simulator.submit_remediation(request)
    verification = simulator.verify(
        operation_id=request.operation_id,
        expected_order_status=CheckoutOrderStatus.CONFIRMED,
        expected_payment_status=CheckoutPaymentStatus.AUTHORIZED,
        expected_reservation_status=InventoryReservationStatus.RESERVED,
        expected_remediation_status=RemediationStatus.APPLIED,
    )
    outcome = CheckoutRecoveryOutcome(
        order_id=fixture.order.order_id,
        diagnostic_disposition=DiagnosticDisposition.RECOVER_INVENTORY,
        approval_decision=fixture.approval.decision,
        remediation_status=result.status,
        verification_result=verification.verified,
        terminal_status=CheckoutTerminalStatus.MANUAL_REVIEW,
        failure_code=CheckoutFailureCode.VERIFICATION_MISMATCH,
    )

    assert result.status == RemediationStatus.APPLIED
    assert verification.verified is False
    assert verification.evidence.actual_reservation_status == (InventoryReservationStatus.RELEASED)
    assert fixture.expected.compare(outcome) == {}


def test_diagnostic_read_failure_is_deterministic() -> None:
    from model_to_harness_shared.simulators import CheckoutDiagnosticReadError

    with pytest.raises(CheckoutDiagnosticReadError):
        _simulator("diagnostic-read-failure").read_diagnostic()


@pytest.mark.parametrize(
    ("order_status", "payment_status", "reservation_status"),
    [
        (
            CheckoutOrderStatus.CANCELLED,
            CheckoutPaymentStatus.AUTHORIZED,
            InventoryReservationStatus.EXPIRED,
        ),
        (
            CheckoutOrderStatus.CONFIRMED,
            CheckoutPaymentStatus.AUTHORIZED,
            InventoryReservationStatus.EXPIRED,
        ),
        (
            CheckoutOrderStatus.CHECKOUT_FAILED,
            CheckoutPaymentStatus.DECLINED,
            InventoryReservationStatus.EXPIRED,
        ),
        (
            CheckoutOrderStatus.CHECKOUT_FAILED,
            CheckoutPaymentStatus.AUTHORIZED,
            InventoryReservationStatus.RELEASED,
        ),
    ],
)
def test_inventory_preconditions_prevent_unauthorized_business_transition(
    order_status, payment_status, reservation_status
) -> None:
    fixture = get_checkout_fixture("recoverable-inventory-reservation")
    simulator = CheckoutSimulator(
        order=fixture.order.model_copy(update={"status": order_status}),
        payment_attempt=fixture.payment_attempt.model_copy(update={"status": payment_status}),
        reservation=fixture.reservation.model_copy(update={"status": reservation_status}),
    )
    before = simulator.snapshot()
    assert simulator.read_diagnostic().disposition != DiagnosticDisposition.RECOVER_INVENTORY
    with pytest.raises(CheckoutRemediationPreconditionError):
        simulator.submit_remediation(_inventory_request(fixture.fixture_id, "invalid-transition"))
    assert simulator.snapshot() == before
