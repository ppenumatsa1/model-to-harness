from concurrent.futures import ThreadPoolExecutor

from model_to_harness_shared.fixtures import get_fixture
from model_to_harness_shared.simulators import (
    BillingReadError,
    BillingSimulator,
    IdempotencyConflictError,
    UncertainRefundResponseError,
)


def test_duplicate_detection_and_validation_are_deterministic() -> None:
    fixture = get_fixture("duplicate-confirmed")
    simulator = BillingSimulator(fixture.charges)

    first = simulator.detect_duplicate(fixture.scenario_input.account_id)
    second = simulator.detect_duplicate(fixture.scenario_input.account_id)

    assert first == second
    assert first.matching_charge_ids == ("charge-100-a", "charge-100-b")
    assert simulator.validate_duplicate(first).valid is True


def test_no_duplicate_is_not_a_read_failure() -> None:
    fixture = get_fixture("no-duplicate")
    evidence = BillingSimulator(fixture.charges).detect_duplicate(
        fixture.scenario_input.account_id
    )

    assert evidence.decision.value == "not_found"
    assert evidence.matching_charge_ids == ()


def test_transient_reads_fail_the_configured_number_of_times() -> None:
    fixture = get_fixture("transient-failure")
    simulator = BillingSimulator(
        fixture.charges,
        transient_read_failures=fixture.billing_behavior.transient_read_failures,
    )

    for _ in range(fixture.maximum_read_attempts):
        try:
            simulator.detect_duplicate(fixture.scenario_input.account_id)
        except BillingReadError:
            pass
        else:
            raise AssertionError("configured transient read should fail")

    assert simulator.detect_duplicate(
        fixture.scenario_input.account_id
    ).decision.value == "confirmed"


def test_refund_submission_is_idempotent_by_key() -> None:
    fixture = get_fixture("duplicate-confirmed")
    simulator = BillingSimulator(fixture.charges)

    first = simulator.submit_refund(
        account_id="account-100",
        charge_id="charge-100-b",
        idempotency_key="stable-key",
    )
    second = simulator.submit_refund(
        account_id="account-100",
        charge_id="charge-100-b",
        idempotency_key="stable-key",
    )

    assert first == second
    assert len(simulator.refunds) == 1
    assert simulator.verify_refund("stable-key").verified is True


def test_refund_identity_is_deterministic_across_simulator_instances() -> None:
    fixture = get_fixture("duplicate-confirmed")
    refunds = [
        BillingSimulator(fixture.charges).submit_refund(
            account_id="account-100",
            charge_id="charge-100-b",
            idempotency_key="deterministic-key",
        )
        for _ in range(2)
    ]

    assert refunds[0] == refunds[1]


def test_concurrent_retries_create_one_refund() -> None:
    fixture = get_fixture("duplicate-confirmed")
    simulator = BillingSimulator(fixture.charges)

    def submit():
        return simulator.submit_refund(
            account_id="account-100",
            charge_id="charge-100-b",
            idempotency_key="concurrent-key",
        )

    with ThreadPoolExecutor(max_workers=8) as executor:
        refunds = list(executor.map(lambda _: submit(), range(20)))

    assert len({refund.refund_id for refund in refunds}) == 1
    assert len(simulator.refunds) == 1


def test_uncertain_response_retry_returns_the_stored_refund() -> None:
    fixture = get_fixture("retry-safe-refund")
    simulator = BillingSimulator(
        fixture.charges,
        uncertain_refund_response_once=True,
    )

    try:
        simulator.submit_refund(
            account_id="account-100",
            charge_id="charge-100-b",
            idempotency_key="retry-key",
        )
    except UncertainRefundResponseError:
        pass
    else:
        raise AssertionError("first submission should simulate an uncertain response")

    refund = simulator.submit_refund(
        account_id="account-100",
        charge_id="charge-100-b",
        idempotency_key="retry-key",
    )

    assert refund.refund_id.startswith("refund-")
    assert len(simulator.refunds) == 1


def test_idempotency_key_cannot_be_rebound() -> None:
    fixture = get_fixture("duplicate-confirmed")
    simulator = BillingSimulator(fixture.charges)
    simulator.submit_refund(
        account_id="account-100",
        charge_id="charge-100-a",
        idempotency_key="bound-key",
    )

    try:
        simulator.submit_refund(
            account_id="account-100",
            charge_id="charge-100-b",
            idempotency_key="bound-key",
        )
    except IdempotencyConflictError:
        pass
    else:
        raise AssertionError("reusing a key for another charge must fail")


def test_verification_mismatch_does_not_claim_success() -> None:
    fixture = get_fixture("verification-mismatch")
    simulator = BillingSimulator(
        fixture.charges,
        verification_count_override=(
            fixture.billing_behavior.verification_count_override
        ),
    )
    key = fixture.scenario_input.idempotency_key
    assert key is not None
    simulator.submit_refund(
        account_id="account-100",
        charge_id="charge-100-b",
        idempotency_key=key,
    )

    verification = simulator.verify_refund(key)

    assert verification.matching_refund_count == 2
    assert verification.verified is False
    assert verification.refund_id is None
