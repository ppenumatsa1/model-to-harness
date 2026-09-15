from datetime import UTC, datetime
from hashlib import sha256
from threading import Lock

from pydantic import BaseModel, ConfigDict, Field, model_validator

from model_to_harness_shared.domain.checkout import (
    CheckoutApproval,
    CheckoutApprovalDecision,
    CheckoutDiagnosticRecord,
    CheckoutOrderStatus,
    CheckoutPaymentStatus,
    DiagnosticDisposition,
    InventoryReservationRecord,
    InventoryReservationStatus,
    OrderRecord,
    PaymentAttemptRecord,
    RemediationAction,
    RemediationRequest,
    RemediationResult,
    RemediationStatus,
    VerificationEvidence,
    VerificationResult,
)


class CheckoutDiagnosticReadError(RuntimeError):
    """A deterministic failure while reading checkout diagnostic records."""


class CheckoutRemediationConflictError(ValueError):
    """An operation ID or fingerprint was reused for a different request."""


class CheckoutApprovalRequiredError(PermissionError):
    """A captured-payment refund was attempted without durable approval."""


class CheckoutRemediationPreconditionError(ValueError):
    """Business records no longer permit the proposed remediation."""


class UncertainCheckoutRemediationResponseError(RuntimeError):
    """The remediation was stored, but the caller did not receive its result."""


class CheckoutSimulatorSnapshot(BaseModel):
    """Serializable checkout state used to rehydrate deterministic adapters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    order: OrderRecord
    payment_attempt: PaymentAttemptRecord
    reservation: InventoryReservationRecord
    remaining_diagnostic_read_failures: int = Field(ge=0)
    uncertain_remediation_response_once: bool
    uncertain_response_emitted: bool
    resulting_reservation_status: InventoryReservationStatus | None = None
    applied_at: datetime
    remediation_results: tuple[RemediationResult, ...] = ()

    @model_validator(mode="after")
    def validate_remediation_results(self) -> "CheckoutSimulatorSnapshot":
        operation_ids = {result.operation_id for result in self.remediation_results}
        fingerprints = {result.request_fingerprint for result in self.remediation_results}
        if len(operation_ids) != len(self.remediation_results):
            raise ValueError("remediation results must use unique operation IDs")
        if len(fingerprints) != len(self.remediation_results):
            raise ValueError("remediation results must use unique request fingerprints")
        return self


def checkout_remediation_fingerprint(
    *,
    order_id: str,
    action: RemediationAction,
    payment_attempt_id: str | None = None,
    reservation_id: str | None = None,
) -> str:
    payload = "|".join(
        (
            order_id,
            action.value,
            payment_attempt_id or "",
            reservation_id or "",
        )
    )
    return sha256(payload.encode("utf-8")).hexdigest()


class CheckoutSimulator:
    """In-memory deterministic checkout records and recovery side effects."""

    def __init__(
        self,
        *,
        order: OrderRecord,
        payment_attempt: PaymentAttemptRecord,
        reservation: InventoryReservationRecord,
        diagnostic_read_failures: int = 0,
        uncertain_remediation_response_once: bool = False,
        resulting_reservation_status: InventoryReservationStatus | None = None,
        applied_at: datetime | None = None,
        remaining_diagnostic_read_failures: int | None = None,
        uncertain_response_emitted: bool = False,
        remediation_results: tuple[RemediationResult, ...] = (),
    ) -> None:
        if diagnostic_read_failures < 0:
            raise ValueError("diagnostic_read_failures cannot be negative")
        if (
            remaining_diagnostic_read_failures is not None
            and remaining_diagnostic_read_failures < 0
        ):
            raise ValueError("remaining_diagnostic_read_failures cannot be negative")
        if order.order_id != payment_attempt.order_id or order.order_id != reservation.order_id:
            raise ValueError("order, payment attempt, and reservation must have one order ID")
        self._order = order
        self._payment_attempt = payment_attempt
        self._reservation = reservation
        self._remaining_diagnostic_read_failures = (
            diagnostic_read_failures
            if remaining_diagnostic_read_failures is None
            else remaining_diagnostic_read_failures
        )
        self._uncertain_remediation_response_once = uncertain_remediation_response_once
        self._uncertain_response_emitted = uncertain_response_emitted
        self._resulting_reservation_status = resulting_reservation_status
        self._applied_at = applied_at or datetime(2026, 1, 15, tzinfo=UTC)
        self._results_by_operation = {result.operation_id: result for result in remediation_results}
        self._operation_by_fingerprint = {
            result.request_fingerprint: result.operation_id for result in remediation_results
        }
        if len(self._results_by_operation) != len(remediation_results):
            raise ValueError("remediation results must use unique operation IDs")
        if len(self._operation_by_fingerprint) != len(remediation_results):
            raise ValueError("remediation results must use unique request fingerprints")
        self._remediation_lock = Lock()

    @property
    def order(self) -> OrderRecord:
        return self._order

    @property
    def payment_attempt(self) -> PaymentAttemptRecord:
        return self._payment_attempt

    @property
    def reservation(self) -> InventoryReservationRecord:
        return self._reservation

    @property
    def remediation_results(self) -> tuple[RemediationResult, ...]:
        return tuple(
            self._results_by_operation[operation_id]
            for operation_id in sorted(self._results_by_operation)
        )

    def snapshot(self) -> CheckoutSimulatorSnapshot:
        return CheckoutSimulatorSnapshot(
            order=self._order,
            payment_attempt=self._payment_attempt,
            reservation=self._reservation,
            remaining_diagnostic_read_failures=self._remaining_diagnostic_read_failures,
            uncertain_remediation_response_once=self._uncertain_remediation_response_once,
            uncertain_response_emitted=self._uncertain_response_emitted,
            resulting_reservation_status=self._resulting_reservation_status,
            applied_at=self._applied_at,
            remediation_results=self.remediation_results,
        )

    @classmethod
    def from_snapshot(cls, snapshot: CheckoutSimulatorSnapshot) -> "CheckoutSimulator":
        return cls(
            order=snapshot.order,
            payment_attempt=snapshot.payment_attempt,
            reservation=snapshot.reservation,
            uncertain_remediation_response_once=snapshot.uncertain_remediation_response_once,
            resulting_reservation_status=snapshot.resulting_reservation_status,
            applied_at=snapshot.applied_at,
            remaining_diagnostic_read_failures=snapshot.remaining_diagnostic_read_failures,
            uncertain_response_emitted=snapshot.uncertain_response_emitted,
            remediation_results=snapshot.remediation_results,
        )

    def read_diagnostic(self) -> CheckoutDiagnosticRecord:
        if self._remaining_diagnostic_read_failures:
            self._remaining_diagnostic_read_failures -= 1
            raise CheckoutDiagnosticReadError("simulated checkout diagnostic read failure")
        if self._payment_attempt.status == CheckoutPaymentStatus.PENDING:
            return CheckoutDiagnosticRecord(
                diagnostic_id=f"diagnostic-{self._order.order_id}",
                order_id=self._order.order_id,
                disposition=DiagnosticDisposition.MANUAL_REVIEW,
                reason="Payment attempt remains pending and requires manual review.",
            )
        if self._payment_attempt.status == CheckoutPaymentStatus.CAPTURED:
            return CheckoutDiagnosticRecord(
                diagnostic_id=f"diagnostic-{self._order.order_id}",
                order_id=self._order.order_id,
                disposition=DiagnosticDisposition.REFUND_CAPTURED_PAYMENT,
                reason="Captured payment requires customer-impacting remediation.",
                recommended_action=RemediationAction.REFUND_CAPTURED_PAYMENT,
            )
        if self._reservation.status == InventoryReservationStatus.EXPIRED:
            if not self._inventory_recovery_allowed():
                return CheckoutDiagnosticRecord(
                    diagnostic_id=f"diagnostic-{self._order.order_id}",
                    order_id=self._order.order_id,
                    disposition=DiagnosticDisposition.MANUAL_REVIEW,
                    reason="Order or payment state does not permit automatic inventory recovery.",
                )
            return CheckoutDiagnosticRecord(
                diagnostic_id=f"diagnostic-{self._order.order_id}",
                order_id=self._order.order_id,
                disposition=DiagnosticDisposition.RECOVER_INVENTORY,
                reason="Inventory reservation expired before checkout could complete.",
                recommended_action=RemediationAction.RECREATE_INVENTORY_RESERVATION,
            )
        return CheckoutDiagnosticRecord(
            diagnostic_id=f"diagnostic-{self._order.order_id}",
            order_id=self._order.order_id,
            disposition=DiagnosticDisposition.NO_ACTION,
            reason="No deterministic checkout remediation applies.",
        )

    def submit_remediation(
        self,
        request: RemediationRequest,
        *,
        approval: CheckoutApproval | None = None,
    ) -> RemediationResult:
        self._validate_request_fingerprint(request)
        with self._remediation_lock:
            existing = self._results_by_operation.get(request.operation_id)
            if existing is not None:
                if not self._same_request(existing, request):
                    raise CheckoutRemediationConflictError(
                        "operation ID is already bound to a different remediation request"
                    )
                return existing
            bound_operation = self._operation_by_fingerprint.get(request.request_fingerprint)
            if bound_operation is not None:
                raise CheckoutRemediationConflictError(
                    "request fingerprint is already bound to another operation ID"
                )
            self._validate_approval(request, approval)
            result = self._apply_remediation(request)
            self._results_by_operation[request.operation_id] = result
            self._operation_by_fingerprint[request.request_fingerprint] = request.operation_id
            if self._uncertain_remediation_response_once and not self._uncertain_response_emitted:
                self._uncertain_response_emitted = True
                raise UncertainCheckoutRemediationResponseError(
                    "remediation was stored but response outcome is uncertain"
                )
            return result

    def verify(
        self,
        *,
        operation_id: str,
        expected_order_status: CheckoutOrderStatus,
        expected_payment_status: CheckoutPaymentStatus,
        expected_reservation_status: InventoryReservationStatus,
        expected_remediation_status: RemediationStatus,
    ) -> VerificationResult:
        remediation = self._results_by_operation.get(operation_id)
        evidence = VerificationEvidence(
            order_id=self._order.order_id,
            operation_id=operation_id,
            expected_order_status=expected_order_status,
            actual_order_status=self._order.status,
            expected_payment_status=expected_payment_status,
            actual_payment_status=self._payment_attempt.status,
            expected_reservation_status=expected_reservation_status,
            actual_reservation_status=self._reservation.status,
            expected_remediation_status=expected_remediation_status,
            actual_remediation_status=remediation.status if remediation else None,
        )
        verified = (
            evidence.expected_order_status == evidence.actual_order_status
            and evidence.expected_payment_status == evidence.actual_payment_status
            and evidence.expected_reservation_status == evidence.actual_reservation_status
            and evidence.expected_remediation_status == evidence.actual_remediation_status
        )
        return VerificationResult(
            verified=verified,
            evidence=evidence,
            reason=(
                "Authoritative order, payment, inventory, and remediation records match."
                if verified
                else "Authoritative records do not match the expected final states."
            ),
        )

    def _validate_request_fingerprint(self, request: RemediationRequest) -> None:
        expected = checkout_remediation_fingerprint(
            order_id=request.order_id,
            action=request.action,
            payment_attempt_id=request.payment_attempt_id,
            reservation_id=request.reservation_id,
        )
        if request.request_fingerprint != expected:
            raise CheckoutRemediationConflictError(
                "request fingerprint does not match remediation request content"
            )
        if request.order_id != self._order.order_id:
            raise ValueError("remediation request belongs to a different order")

    @staticmethod
    def _validate_approval(request: RemediationRequest, approval: CheckoutApproval | None) -> None:
        if request.action != RemediationAction.REFUND_CAPTURED_PAYMENT:
            return
        if (
            approval is None
            or approval.order_id != request.order_id
            or approval.decision != CheckoutApprovalDecision.APPROVED
        ):
            raise CheckoutApprovalRequiredError(
                "captured-payment remediation requires approved durable approval"
            )

    @staticmethod
    def _same_request(result: RemediationResult, request: RemediationRequest) -> bool:
        return (
            result.request_fingerprint == request.request_fingerprint
            and result.order_id == request.order_id
            and result.action == request.action
        )

    def _inventory_recovery_allowed(self) -> bool:
        return (
            self._order.status == CheckoutOrderStatus.CHECKOUT_FAILED
            and self._payment_attempt.status == CheckoutPaymentStatus.AUTHORIZED
            and self._reservation.status == InventoryReservationStatus.EXPIRED
        )

    def _apply_remediation(self, request: RemediationRequest) -> RemediationResult:
        if request.action == RemediationAction.RECREATE_INVENTORY_RESERVATION:
            if not self._inventory_recovery_allowed():
                raise CheckoutRemediationPreconditionError(
                    "inventory recovery requires failed checkout, authorized payment, and expired reservation"
                )
            if request.reservation_id != self._reservation.reservation_id:
                raise ValueError("inventory recovery must target the order reservation")
            self._reservation = self._reservation.model_copy(
                update={
                    "status": (
                        self._resulting_reservation_status or InventoryReservationStatus.RESERVED
                    )
                }
            )
            self._order = self._order.model_copy(update={"status": CheckoutOrderStatus.CONFIRMED})
        elif request.payment_attempt_id != self._payment_attempt.payment_attempt_id:
            raise ValueError("payment remediation must target the order payment attempt")
        else:
            self._payment_attempt = self._payment_attempt.model_copy(
                update={"status": CheckoutPaymentStatus.REFUNDED}
            )
            self._reservation = self._reservation.model_copy(
                update={"status": InventoryReservationStatus.RELEASED}
            )
            self._order = self._order.model_copy(update={"status": CheckoutOrderStatus.CANCELLED})
        digest = sha256(request.operation_id.encode("utf-8")).hexdigest()[:16]
        return RemediationResult(
            remediation_id=f"remediation-{digest}",
            operation_id=request.operation_id,
            request_fingerprint=request.request_fingerprint,
            order_id=request.order_id,
            action=request.action,
            status=RemediationStatus.APPLIED,
            applied_at=self._applied_at,
        )
