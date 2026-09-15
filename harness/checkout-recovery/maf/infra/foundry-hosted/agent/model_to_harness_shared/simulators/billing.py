from collections.abc import Iterable
from datetime import datetime, timezone
from hashlib import sha256
from itertools import combinations
from threading import Lock

from model_to_harness_shared.domain import (
    BillingValidation,
    ChargeRecord,
    ChargeStatus,
    DuplicateDecision,
    DuplicateEvidence,
    RefundRecord,
    RefundVerification,
)


class BillingReadError(RuntimeError):
    pass


class UncertainRefundResponseError(RuntimeError):
    pass


class IdempotencyConflictError(ValueError):
    pass


class BillingSimulator:
    def __init__(
        self,
        charges: Iterable[ChargeRecord],
        *,
        transient_read_failures: int = 0,
        uncertain_refund_response_once: bool = False,
        verification_count_override: int | None = None,
        submitted_at: datetime | None = None,
    ) -> None:
        if transient_read_failures < 0:
            raise ValueError("transient_read_failures cannot be negative")
        if verification_count_override is not None and verification_count_override < 0:
            raise ValueError("verification_count_override cannot be negative")
        self._charges = tuple(
            sorted(charges, key=lambda charge: (charge.charged_at, charge.charge_id))
        )
        self._charges_by_id = {charge.charge_id: charge for charge in self._charges}
        if len(self._charges_by_id) != len(self._charges):
            raise ValueError("charge IDs must be unique")
        self._remaining_read_failures = transient_read_failures
        self._uncertain_refund_response_once = uncertain_refund_response_once
        self._uncertain_response_emitted = False
        self._verification_count_override = verification_count_override
        self._submitted_at = submitted_at or datetime(2026, 1, 15, tzinfo=timezone.utc)
        self._refunds_by_key: dict[str, RefundRecord] = {}
        self._refund_lock = Lock()

    def load_charges(self, account_id: str) -> tuple[ChargeRecord, ...]:
        if self._remaining_read_failures:
            self._remaining_read_failures -= 1
            raise BillingReadError("simulated transient billing read failure")
        return tuple(charge for charge in self._charges if charge.account_id == account_id)

    def detect_duplicate(self, account_id: str) -> DuplicateEvidence:
        captured = [
            charge
            for charge in self.load_charges(account_id)
            if charge.status == ChargeStatus.CAPTURED
        ]
        for first, second in combinations(captured, 2):
            if (
                first.purchase_reference == second.purchase_reference
                and first.amount == second.amount
                and first.currency == second.currency
            ):
                return DuplicateEvidence(
                    decision=DuplicateDecision.CONFIRMED,
                    matching_charge_ids=(first.charge_id, second.charge_id),
                    purchase_reference=first.purchase_reference,
                    amount=first.amount,
                    currency=first.currency,
                    rationale=(
                        "Two captured charges share account, purchase reference, "
                        "amount, and currency."
                    ),
                )
        return DuplicateEvidence(
            decision=DuplicateDecision.NOT_FOUND,
            rationale="No pair of captured charges satisfies the duplicate rule.",
        )

    def validate_duplicate(self, evidence: DuplicateEvidence) -> BillingValidation:
        if evidence.decision != DuplicateDecision.CONFIRMED:
            return BillingValidation(
                valid=False,
                checked_charge_ids=(),
                reason="Duplicate evidence is not confirmed.",
            )
        charges = tuple(
            self._charges_by_id.get(charge_id)
            for charge_id in evidence.matching_charge_ids
        )
        if any(charge is None for charge in charges):
            return BillingValidation(
                valid=False,
                checked_charge_ids=evidence.matching_charge_ids,
                reason="One or more evidence charges no longer exist.",
            )
        first, second = charges
        assert first is not None and second is not None
        valid = (
            first.account_id == second.account_id
            and first.status == second.status == ChargeStatus.CAPTURED
            and first.purchase_reference == second.purchase_reference
            == evidence.purchase_reference
            and first.amount == second.amount == evidence.amount
            and first.currency == second.currency == evidence.currency
        )
        return BillingValidation(
            valid=valid,
            checked_charge_ids=evidence.matching_charge_ids,
            reason=(
                "Billing records still match the duplicate evidence."
                if valid
                else "Billing records no longer match the duplicate evidence."
            ),
        )

    def submit_refund(
        self,
        *,
        account_id: str,
        charge_id: str,
        idempotency_key: str,
    ) -> RefundRecord:
        if not idempotency_key.strip():
            raise ValueError("idempotency_key cannot be empty")
        charge = self._charges_by_id.get(charge_id)
        if charge is None or charge.account_id != account_id:
            raise ValueError("refund charge must exist on the supplied account")
        with self._refund_lock:
            existing = self._refunds_by_key.get(idempotency_key)
            if existing is not None:
                if (
                    existing.account_id != account_id
                    or existing.original_charge_id != charge_id
                    or existing.amount != charge.amount
                    or existing.currency != charge.currency
                ):
                    raise IdempotencyConflictError(
                        "idempotency key is already bound to a different refund"
                    )
                return existing
            digest = sha256(idempotency_key.encode("utf-8")).hexdigest()[:16]
            refund = RefundRecord(
                refund_id=f"refund-{digest}",
                idempotency_key=idempotency_key,
                account_id=account_id,
                original_charge_id=charge_id,
                amount=charge.amount,
                currency=charge.currency,
                submitted_at=self._submitted_at,
            )
            self._refunds_by_key[idempotency_key] = refund
            if (
                self._uncertain_refund_response_once
                and not self._uncertain_response_emitted
            ):
                self._uncertain_response_emitted = True
                raise UncertainRefundResponseError(
                    "refund stored but response outcome is uncertain"
                )
            return refund

    def verify_refund(self, idempotency_key: str) -> RefundVerification:
        refund = self._refunds_by_key.get(idempotency_key)
        actual_count = 1 if refund is not None else 0
        count = (
            self._verification_count_override
            if self._verification_count_override is not None
            else actual_count
        )
        verified = count == 1 and refund is not None
        return RefundVerification(
            idempotency_key=idempotency_key,
            matching_refund_count=count,
            verified=verified,
            refund_id=refund.refund_id if verified else None,
            reason=(
                "Exactly one matching refund exists."
                if verified
                else f"Expected one matching refund; found {count}."
            ),
        )

    @property
    def refunds(self) -> tuple[RefundRecord, ...]:
        return tuple(self._refunds_by_key[key] for key in sorted(self._refunds_by_key))
