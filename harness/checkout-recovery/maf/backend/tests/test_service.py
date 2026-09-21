import pytest
from checkout_recovery_maf.application import (
    CaseNotFoundError,
    CheckoutRecoveryService,
    InvalidCaseCommandError,
)
from checkout_recovery_maf.infrastructure import InMemoryCaseRepository
from checkout_recovery_maf.projections import project_artifact, project_case, project_event
from model_to_harness_shared import (
    CheckoutApprovalDecision,
    CheckoutFailureCode,
    CheckoutTerminalStatus,
    InventoryReservationStatus,
    get_checkout_fixture,
)


def make_service() -> CheckoutRecoveryService:
    return CheckoutRecoveryService(InMemoryCaseRepository())


def test_safe_queries_project_without_mutating_domain_or_audit():
    repository = InMemoryCaseRepository()
    service = CheckoutRecoveryService(repository)
    case = service.start_case("captured-payment-approved-remediation")
    repository.save_framework_state(
        case.case_id, {"workspace": {"plan.md": "PRIVATE-WORKSPACE-CANARY"}}
    )
    before_case = case.model_dump_json()
    before_events = service.events(case.case_id)
    assert service.get_case_response(case.case_id) == project_case(case)
    assert service.list_event_responses(case.case_id) == [
        project_event(event) for event in before_events
    ]
    assert service.get_workspace_artifact_response(case.case_id) == project_artifact(case.artifact)
    assert service.get_case(case.case_id).model_dump_json() == before_case
    assert service.events(case.case_id) == before_events
    safe_json = service.get_case_response(case.case_id).model_dump_json()
    assert "PRIVATE-WORKSPACE-CANARY" not in safe_json
    assert service.get_case(case.case_id).order_id
    assert "order_id" not in service.get_case_response(case.case_id).model_dump()


@pytest.mark.parametrize(
    "query", ["get_case_response", "list_event_responses", "get_workspace_artifact_response"]
)
def test_safe_queries_preserve_missing_case_errors(query):
    with pytest.raises(CaseNotFoundError):
        getattr(make_service(), query)("missing")


def test_recovers_inventory_and_verifies_authoritative_records() -> None:
    case = make_service().start_case("recoverable-inventory-reservation")

    assert case.terminal_status == CheckoutTerminalStatus.RECOVERED
    assert case.verification_result is True


def test_approval_must_be_persisted_then_resumed() -> None:
    service = make_service()
    case = service.start_case("captured-payment-approved-remediation")

    assert case.terminal_status is None
    assert case.approval_decision == CheckoutApprovalDecision.PENDING
    approved = service.record_approval(
        case.case_id,
        decision=CheckoutApprovalDecision.APPROVED,
        reviewer_id="reviewer-1",
        approval_request_id=case.approval_request_id,
        reason="Reviewed",
    )
    assert approved.terminal_status is None

    outcome = service.resume_case(case.case_id)

    assert outcome.terminal_status == CheckoutTerminalStatus.RECOVERED
    assert outcome.verification_result is True


def test_matching_approval_retry_is_idempotent() -> None:
    service = make_service()
    case = service.start_case("captured-payment-approved-remediation")

    approved = service.record_approval(
        case.case_id,
        decision=CheckoutApprovalDecision.APPROVED,
        reviewer_id="reviewer-1",
        approval_request_id=case.approval_request_id,
        reason="Reviewed",
    )
    retried = service.record_approval(
        case.case_id,
        decision=CheckoutApprovalDecision.APPROVED,
        reviewer_id="reviewer-1",
        approval_request_id=case.approval_request_id,
        reason="Reviewed",
    )

    assert retried == approved


def test_conflicting_approval_retry_is_rejected() -> None:
    service = make_service()
    case = service.start_case("captured-payment-approved-remediation")
    service.record_approval(
        case.case_id,
        decision=CheckoutApprovalDecision.APPROVED,
        reviewer_id="reviewer-1",
        approval_request_id=case.approval_request_id,
        reason="Reviewed",
    )

    with pytest.raises(InvalidCaseCommandError):
        service.record_approval(
            case.case_id,
            decision=CheckoutApprovalDecision.DENIED,
            reviewer_id="reviewer-1",
            approval_request_id=case.approval_request_id,
            reason="Reviewed",
        )


def test_inventory_recovery_above_safe_bound_routes_to_manual_review(monkeypatch) -> None:
    fixture = get_checkout_fixture("recoverable-inventory-reservation").model_copy(
        update={
            "reservation": get_checkout_fixture(
                "recoverable-inventory-reservation"
            ).reservation.model_copy(
                update={"quantity": 2, "status": InventoryReservationStatus.EXPIRED}
            )
        }
    )
    monkeypatch.setattr(
        "checkout_recovery_maf.application.service.get_checkout_fixture",
        lambda fixture_id: fixture,
    )

    case = make_service().start_case("inventory-over-safe-bound")

    assert case.terminal_status == CheckoutTerminalStatus.MANUAL_REVIEW
    assert case.remediation_status is None


def test_denied_approval_closes_without_remediation() -> None:
    service = make_service()
    case = service.start_case("denied-approval")
    service.record_approval(
        case.case_id,
        decision=CheckoutApprovalDecision.DENIED,
        reviewer_id="reviewer-1",
        approval_request_id=case.approval_request_id,
        reason="Reviewed",
    )

    outcome = service.resume_case(case.case_id)

    assert outcome.terminal_status == CheckoutTerminalStatus.CLOSED_DENIED
    assert outcome.remediation_status is None


def test_uncertain_remediation_is_recovered_with_same_persisted_intent() -> None:
    service = make_service()
    case = service.start_case("uncertain-remediation-recovery")
    events = service.events(case.case_id)

    assert case.terminal_status == CheckoutTerminalStatus.RECOVERED
    assert [event.code.value for event in events].count("remediation_response_uncertain") == 1


def test_verification_mismatch_routes_to_manual_review() -> None:
    case = make_service().start_case("verification-mismatch")

    assert case.terminal_status == CheckoutTerminalStatus.MANUAL_REVIEW
    assert case.failure_code == CheckoutFailureCode.VERIFICATION_MISMATCH
    assert case.verification_result is False


def test_cannot_approve_case_that_is_not_waiting() -> None:
    service = make_service()
    case = service.start_case("recoverable-inventory-reservation")

    with pytest.raises(InvalidCaseCommandError):
        service.record_approval(
            case.case_id,
            decision=CheckoutApprovalDecision.APPROVED,
            reviewer_id="reviewer-1",
            approval_request_id="invalid",
            reason="Reviewed",
        )
