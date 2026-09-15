import importlib.util
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
from checkout_recovery_maf.application import CheckoutRecoveryService, InvalidCaseCommandError
from checkout_recovery_maf.infrastructure import InMemoryCaseRepository, PostgresCaseRepository
from model_to_harness_shared import CheckoutApprovalDecision


@pytest.fixture(params=["memory", "postgres"])
def repository(request):
    if request.param == "memory":
        yield InMemoryCaseRepository()
        return
    url = os.getenv("CHECKOUT_TEST_DATABASE_URL")
    if not url:
        pytest.skip("dedicated CHECKOUT_TEST_DATABASE_URL not supplied")
    path = Path(__file__).resolve().parents[2] / "scripts/migrate.py"
    spec = importlib.util.spec_from_file_location("checkout_migrate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.migrate(url, apply=True)
    repo = PostgresCaseRepository(url)
    repo.open()
    try:
        yield repo
    finally:
        repo.close()


def test_repeat_fixture_and_start_retry_are_separate_contracts(repository):
    service = CheckoutRecoveryService(repository)
    request_id = str(uuid4())
    first = service.start_case("recoverable-inventory-reservation", request_id)
    retry = service.start_case("recoverable-inventory-reservation", request_id)
    second = service.start_case("recoverable-inventory-reservation")
    assert first.case_id == retry.case_id
    assert first.order_id != second.order_id
    assert first.verification_result and second.verification_result
    with pytest.raises(InvalidCaseCommandError):
        service.start_case("denied-approval", request_id)


def test_approval_retry_after_closure_and_concurrent_resume(repository):
    service = CheckoutRecoveryService(repository)
    case = service.start_case("captured-payment-approved-remediation")
    command = dict(
        decision=CheckoutApprovalDecision.APPROVED,
        reviewer_id="reviewer",
        approval_request_id=case.approval_request_id,
        reason="Reviewed",
    )
    with pytest.raises(InvalidCaseCommandError):
        service.record_approval(case.case_id, **{**command, "approval_request_id": str(uuid4())})
    service.record_approval(case.case_id, **command)
    with ThreadPoolExecutor(max_workers=4) as pool:
        outcomes = list(pool.map(service.resume_case, [case.case_id] * 4))
    assert all(case.verification_result for case in outcomes)
    final = service.record_approval(case.case_id, **command)
    assert len(final.simulator_snapshot.remediation_results) == 1
    assert final.verification.verified
    assert [event.code.value for event in service.events(case.case_id)].count(
        "remediation_completed"
    ) == 1


def test_transaction_failure_rolls_back_all_case_writes(repository, monkeypatch):
    service = CheckoutRecoveryService(repository)
    case = service.start_case("captured-payment-approved-remediation")

    def fail(*args, **kwargs):
        raise RuntimeError("injected repository failure")

    monkeypatch.setattr(repository, "save", fail)
    with pytest.raises(RuntimeError, match="injected"):
        service.record_approval(
            case.case_id,
            decision=CheckoutApprovalDecision.APPROVED,
            reviewer_id="reviewer",
            reason="Reviewed",
            approval_request_id=case.approval_request_id,
        )
    assert service.get_case(case.case_id).approval_decision == CheckoutApprovalDecision.PENDING
    assert "approval_recorded" not in [e.code.value for e in service.events(case.case_id)]
