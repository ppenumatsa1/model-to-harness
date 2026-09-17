from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from model_to_harness_shared import (
    CheckoutApproval,
    CheckoutApprovalDecision,
    CheckoutApprovalRequiredError,
    CheckoutDiagnosticReadError,
    CheckoutFailureCode,
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

from checkout_recovery_maf.infrastructure.telemetry import operation

from .models import (
    AuditCode,
    AuditEvent,
    CasePhase,
    CaseRecord,
    RemediationIntent,
    WorkspaceArtifact,
)
from .ports import CaseRepository, InvestigationIncompleteError, Investigator

if TYPE_CHECKING:
    from checkout_recovery_maf.projections import (
        SafeAuditEventResponse,
        SafeCaseResponse,
        SafeWorkspaceArtifactResponse,
    )


class CaseNotFoundError(LookupError):
    pass


class InvalidCaseCommandError(ValueError):
    pass


class CheckoutRecoveryService:
    """Application-owned recovery state machine; MAF state is deliberately not read."""

    def __init__(
        self,
        repository: CaseRepository,
        *,
        max_auto_inventory_quantity: int = 1,
        investigator: Investigator | None = None,
    ) -> None:
        if max_auto_inventory_quantity < 1:
            raise ValueError("max_auto_inventory_quantity must be at least one")
        self._repository = repository
        self._max_auto_inventory_quantity = max_auto_inventory_quantity
        if investigator is None:
            from checkout_recovery_maf.maf.investigation import ScriptedInvestigator

            investigator = ScriptedInvestigator()
        self._investigator = investigator

    def ready(self) -> bool:
        return self._repository.ready()

    def start_case(self, fixture_id: str, request_id: str | None = None) -> CaseRecord:
        case_id = str(UUID(request_id)) if request_id else str(uuid4())
        with operation("start", case_id), self._repository.transaction(case_id):
            existing = self._repository.get(case_id)
            if existing is not None:
                if existing.fixture_id != fixture_id:
                    raise InvalidCaseCommandError("start request is bound to another fixture")
                return existing
            return self._start_case(fixture_id, case_id)

    def _start_case(self, fixture_id: str, case_id: str) -> CaseRecord:
        fixture = get_checkout_fixture(fixture_id)
        now = self._now()
        order_id = f"order-8472-{case_id}"
        simulator = CheckoutSimulator(
            order=fixture.order.model_copy(update={"order_id": order_id}),
            payment_attempt=fixture.payment_attempt.model_copy(
                update={"order_id": order_id, "payment_attempt_id": f"payment-{case_id}"}
            ),
            reservation=fixture.reservation.model_copy(
                update={"order_id": order_id, "reservation_id": f"reservation-{case_id}"}
            ),
            diagnostic_read_failures=fixture.behavior.diagnostic_read_failures,
            uncertain_remediation_response_once=fixture.behavior.uncertain_remediation_response_once,
            resulting_reservation_status=fixture.behavior.resulting_reservation_status,
        )
        case = CaseRecord(
            case_id=case_id,
            run_id=str(uuid4()),
            fixture_id=fixture.fixture_id,
            order_id=order_id,
            simulator_snapshot=simulator.snapshot(),
            phase=CasePhase.OPEN,
            artifact=WorkspaceArtifact(
                artifact_id=str(uuid4()),
                kind="checkout_recovery_plan_evidence_summary",
                revision=1,
                updated_at=now,
            ),
            created_at=now,
            updated_at=now,
        )
        self._repository.create(case, simulator)
        self._event(case, AuditCode.CASE_STARTED, "Checkout recovery case started.")
        try:
            investigation = self._investigator.investigate(simulator)
            case.diagnostic_tools = investigation.selected_tools
            case.harness_mode = investigation.mode
            self._repository.save_framework_state(case_id, investigation.framework_state)
            self._event(case, AuditCode.HARNESS_COMPLETED, "Bounded diagnosis completed.")
            diagnostic = simulator.read_diagnostic()
        except CheckoutDiagnosticReadError:
            case.diagnostic_disposition = DiagnosticDisposition.NO_ACTION
            self._event(case, AuditCode.CASE_CLOSED, "Diagnostic data could not be read.")
            return self._close(
                case, CheckoutTerminalStatus.FAILED, CheckoutFailureCode.DIAGNOSTIC_READ_FAILED
            )
        except InvestigationIncompleteError:
            self._event(
                case, AuditCode.CASE_CLOSED, "Harness investigation failed; no action taken."
            )
            return self._close(
                case, CheckoutTerminalStatus.FAILED, CheckoutFailureCode.HARNESS_FAILED
            )

        case.diagnostic_disposition = diagnostic.disposition
        case.simulator_snapshot = simulator.snapshot()
        self._event(
            case, AuditCode.DIAGNOSTIC_COMPLETED, "Read-only checkout diagnostic completed."
        )
        if diagnostic.disposition == DiagnosticDisposition.MANUAL_REVIEW:
            self._event(case, AuditCode.CASE_CLOSED, "Case routed to manual review.")
            return self._close(case, CheckoutTerminalStatus.MANUAL_REVIEW)
        if diagnostic.disposition == DiagnosticDisposition.NO_ACTION:
            self._event(case, AuditCode.CASE_CLOSED, "No checkout remediation was required.")
            return self._close(case, CheckoutTerminalStatus.MANUAL_REVIEW)
        if diagnostic.disposition == DiagnosticDisposition.REFUND_CAPTURED_PAYMENT:
            case.phase = CasePhase.WAITING_APPROVAL
            case.approval_decision = CheckoutApprovalDecision.PENDING
            case.approval_request_id = str(uuid4())
            case.approval_evidence_hash = self._evidence_hash(case)
            self._ensure_intent(case, simulator, RemediationAction.REFUND_CAPTURED_PAYMENT)
            self._touch(case)
            self._repository.save(case)
            return case
        return self._remediate_and_verify(case)

    def record_approval(
        self,
        case_id: str,
        *,
        decision: CheckoutApprovalDecision,
        reviewer_id: str,
        approval_request_id: str,
        reason: str,
    ) -> CaseRecord:
        with operation("approval", case_id), self._repository.transaction(case_id):
            return self._record_approval(
                case_id,
                decision=decision,
                reviewer_id=reviewer_id,
                approval_request_id=approval_request_id,
                reason=reason,
            )

    def _record_approval(
        self,
        case_id: str,
        *,
        decision: CheckoutApprovalDecision,
        reviewer_id: str,
        approval_request_id: str,
        reason: str,
    ) -> CaseRecord:
        case = self._case(case_id)
        if not reviewer_id.strip() or not reason.strip():
            raise InvalidCaseCommandError("reviewer and reason are required")
        if not case.approval_request_id or case.approval_request_id != approval_request_id:
            raise InvalidCaseCommandError("approval request does not match this case")
        if decision not in {CheckoutApprovalDecision.APPROVED, CheckoutApprovalDecision.DENIED}:
            raise InvalidCaseCommandError("approval command must approve or deny")
        if case.approval_decision != CheckoutApprovalDecision.PENDING:
            if (
                case.approval_decision == decision
                and case.approval_reviewer_id == reviewer_id
                and case.approval_reason == reason
            ):
                return case
            raise InvalidCaseCommandError("approval decision is already recorded")
        if case.phase != CasePhase.WAITING_APPROVAL:
            raise InvalidCaseCommandError("case is not awaiting approval")
        if case.approval_evidence_hash != self._evidence_hash(case):
            raise InvalidCaseCommandError("approval evidence is stale")
        case.approval_decision = decision
        case.approval_reviewer_id = reviewer_id
        case.approval_reason = reason
        self._event(case, AuditCode.APPROVAL_RECORDED, "Reviewer approval command recorded.")
        self._touch(case)
        self._repository.save_approval(case_id, decision, reviewer_id)
        self._repository.save(case)
        return case

    def resume_case(self, case_id: str) -> CaseRecord:
        with operation("resume", case_id), self._repository.transaction(case_id):
            return self._resume_case(case_id)

    def _resume_case(self, case_id: str) -> CaseRecord:
        case = self._case(case_id)
        if case.phase == CasePhase.CLOSED:
            return case
        if case.phase == CasePhase.WAITING_APPROVAL:
            if case.approval_decision == CheckoutApprovalDecision.PENDING:
                return case
            if case.approval_decision == CheckoutApprovalDecision.DENIED:
                self._event(case, AuditCode.CASE_CLOSED, "Approved remediation was denied.")
                return self._close(case, CheckoutTerminalStatus.CLOSED_DENIED)
            if case.approval_evidence_hash != self._evidence_hash(case):
                raise InvalidCaseCommandError("approval evidence is stale")
        return self._remediate_and_verify(case)

    def get_case(self, case_id: str) -> CaseRecord:
        return self._case(case_id)

    def events(self, case_id: str) -> tuple[AuditEvent, ...]:
        self._case(case_id)
        return self._repository.events_for(case_id)

    def get_case_response(self, case_id: str) -> SafeCaseResponse:
        from checkout_recovery_maf.projections import project_case

        return project_case(self.get_case(case_id))

    def list_event_responses(self, case_id: str) -> list[SafeAuditEventResponse]:
        from checkout_recovery_maf.projections import project_event

        return [project_event(event) for event in self.events(case_id)]

    def get_workspace_artifact_response(self, case_id: str) -> SafeWorkspaceArtifactResponse:
        from checkout_recovery_maf.projections import project_artifact

        return project_artifact(self.get_case(case_id).artifact)

    def _remediate_and_verify(self, case: CaseRecord) -> CaseRecord:
        simulator = self._repository.simulator_for(case)
        action = self._action_for(case)
        if (
            action == RemediationAction.RECREATE_INVENTORY_RESERVATION
            and simulator.reservation.quantity > self._max_auto_inventory_quantity
        ):
            self._event(
                case,
                AuditCode.CASE_CLOSED,
                "Inventory recovery exceeded the configured automatic recovery bound.",
            )
            return self._close(case, CheckoutTerminalStatus.MANUAL_REVIEW)
        intent = self._ensure_intent(case, simulator, action)
        if intent.action != action:
            raise InvalidCaseCommandError("remediation intent changed")
        request = RemediationRequest(
            operation_id=intent.operation_id,
            request_fingerprint=intent.request_fingerprint,
            order_id=case.order_id,
            action=action,
            payment_attempt_id=(
                simulator.payment_attempt.payment_attempt_id
                if action == RemediationAction.REFUND_CAPTURED_PAYMENT
                else None
            ),
            reservation_id=(
                simulator.reservation.reservation_id
                if action == RemediationAction.RECREATE_INVENTORY_RESERVATION
                else None
            ),
        )
        approval = self._approval(case)
        with operation("remediation", case.case_id):
            try:
                result = simulator.submit_remediation(request, approval=approval)
            except UncertainCheckoutRemediationResponseError:
                case.simulator_snapshot = simulator.snapshot()
                self._repository.save(case)
                self._event(
                    case,
                    AuditCode.REMEDIATION_RESPONSE_UNCERTAIN,
                    "Remediation response was uncertain.",
                )
                simulator = self._repository.simulator_for(self._case(case.case_id))
                result = simulator.submit_remediation(request, approval=approval)
            except CheckoutApprovalRequiredError as error:
                raise InvalidCaseCommandError("durable approval is required") from error
            except CheckoutRemediationPreconditionError:
                self._event(
                    case, AuditCode.CASE_CLOSED, "Remediation preconditions require review."
                )
                return self._close(case, CheckoutTerminalStatus.MANUAL_REVIEW)

        case.remediation_action = action
        case.remediation_status = result.status
        case.simulator_snapshot = simulator.snapshot()
        self._repository.save(case)
        self._event(case, AuditCode.REMEDIATION_COMPLETED, "Remediation recorded.")
        simulator = self._repository.simulator_for(self._case(case.case_id))
        expected = self._expected_states(action)
        with operation("verification", case.case_id):
            verification = simulator.verify(
                operation_id=intent.operation_id,
                expected_order_status=expected[0],
                expected_payment_status=expected[1],
                expected_reservation_status=expected[2],
                expected_remediation_status=RemediationStatus.APPLIED,
            )
        case.verification = verification
        case.verification_result = verification.verified
        self._event(
            case,
            AuditCode.VERIFICATION_COMPLETED,
            "Authoritative remediation verification completed.",
        )
        if verification.verified:
            self._event(case, AuditCode.CASE_CLOSED, "Recovery completed after verification.")
            return self._close(case, CheckoutTerminalStatus.RECOVERED)
        self._event(case, AuditCode.CASE_CLOSED, "Verification mismatch routed to manual review.")
        return self._close(
            case, CheckoutTerminalStatus.MANUAL_REVIEW, CheckoutFailureCode.VERIFICATION_MISMATCH
        )

    def _ensure_intent(
        self,
        case: CaseRecord,
        simulator: CheckoutSimulator,
        action: RemediationAction,
    ) -> RemediationIntent:
        intent = self._repository.remediation_intent_for(case.case_id)
        if intent is None:
            operation_id = str(uuid4())
            request_fingerprint = checkout_remediation_fingerprint(
                order_id=case.order_id,
                action=action,
                payment_attempt_id=(
                    simulator.payment_attempt.payment_attempt_id
                    if action == RemediationAction.REFUND_CAPTURED_PAYMENT
                    else None
                ),
                reservation_id=(
                    simulator.reservation.reservation_id
                    if action == RemediationAction.RECREATE_INVENTORY_RESERVATION
                    else None
                ),
            )
            intent = RemediationIntent(
                operation_id=operation_id, request_fingerprint=request_fingerprint, action=action
            )
            self._repository.save_remediation_intent(case.case_id, intent)
            self._event(
                case, AuditCode.REMEDIATION_INTENT_RECORDED, "Remediation intent persisted."
            )
        return intent

    @staticmethod
    def _evidence_hash(case: CaseRecord) -> str:
        return sha256(
            (case.run_id + case.simulator_snapshot.model_dump_json()).encode()
        ).hexdigest()

    def _approval(self, case: CaseRecord) -> CheckoutApproval | None:
        if case.approval_decision == CheckoutApprovalDecision.NOT_REQUIRED:
            return None
        if case.approval_reviewer_id is None:
            return None
        return CheckoutApproval(
            approval_id=f"approval-{case.case_id}",
            order_id=case.order_id,
            decision=case.approval_decision,
            reviewer_id=case.approval_reviewer_id,
            reason=case.approval_reason,
        )

    @staticmethod
    def _action_for(case: CaseRecord) -> RemediationAction:
        if case.diagnostic_disposition == DiagnosticDisposition.RECOVER_INVENTORY:
            return RemediationAction.RECREATE_INVENTORY_RESERVATION
        if case.diagnostic_disposition == DiagnosticDisposition.REFUND_CAPTURED_PAYMENT:
            return RemediationAction.REFUND_CAPTURED_PAYMENT
        raise InvalidCaseCommandError("case has no remediable diagnostic")

    @staticmethod
    def _expected_states(action: RemediationAction) -> tuple:
        from model_to_harness_shared import CheckoutOrderStatus, CheckoutPaymentStatus

        if action == RemediationAction.RECREATE_INVENTORY_RESERVATION:
            return (
                CheckoutOrderStatus.CONFIRMED,
                CheckoutPaymentStatus.AUTHORIZED,
                InventoryReservationStatus.RESERVED,
            )
        return (
            CheckoutOrderStatus.CANCELLED,
            CheckoutPaymentStatus.REFUNDED,
            InventoryReservationStatus.RELEASED,
        )

    def _close(
        self,
        case: CaseRecord,
        terminal_status: CheckoutTerminalStatus,
        failure_code: CheckoutFailureCode = CheckoutFailureCode.NONE,
    ) -> CaseRecord:
        case.phase = CasePhase.CLOSED
        case.terminal_status = terminal_status
        case.failure_code = failure_code
        case.outcome = CheckoutRecoveryOutcome(
            order_id=case.order_id,
            diagnostic_disposition=case.diagnostic_disposition or DiagnosticDisposition.NO_ACTION,
            approval_decision=case.approval_decision,
            remediation_status=case.remediation_status,
            verification_result=case.verification_result,
            terminal_status=terminal_status,
            failure_code=failure_code,
        )
        self._touch(case)
        self._repository.save(case)
        return case

    def _event(self, case: CaseRecord, code: AuditCode, summary: str) -> None:
        self._repository.append_event(
            case.case_id, AuditEvent(code=code, occurred_at=self._now(), summary=summary)
        )

    def _touch(self, case: CaseRecord) -> None:
        now = self._now()
        case.updated_at = now
        case.artifact = case.artifact.model_copy(
            update={"revision": case.artifact.revision + 1, "updated_at": now}
        )

    def _case(self, case_id: str) -> CaseRecord:
        try:
            UUID(case_id)
        except ValueError as error:
            raise CaseNotFoundError("case identifier is invalid") from error
        case = self._repository.get(case_id)
        if case is None:
            raise CaseNotFoundError(f"checkout recovery case {case_id} does not exist")
        return case

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)
