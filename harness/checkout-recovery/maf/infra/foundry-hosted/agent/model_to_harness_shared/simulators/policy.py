from collections.abc import Iterable
from datetime import datetime, timezone

from model_to_harness_shared.domain import (
    ChargeRecord,
    ChargeStatus,
    DuplicateDecision,
    DuplicateEvidence,
    PolicyAssessment,
    PolicyDecision,
)


class RefundPolicySimulator:
    def __init__(
        self,
        *,
        maximum_age_days: int = 120,
        evaluated_at: datetime | None = None,
    ) -> None:
        if maximum_age_days < 0:
            raise ValueError("maximum_age_days cannot be negative")
        self._maximum_age_days = maximum_age_days
        self._evaluated_at = evaluated_at or datetime(2026, 1, 15, tzinfo=timezone.utc)

    def assess(
        self,
        evidence: DuplicateEvidence,
        charges: Iterable[ChargeRecord],
    ) -> PolicyAssessment:
        if evidence.decision != DuplicateDecision.CONFIRMED:
            return PolicyAssessment(
                decision=PolicyDecision.NOT_EVALUATED,
                policy_code="duplicate-required",
                reason="Policy is evaluated only for a confirmed duplicate.",
            )
        by_id = {charge.charge_id: charge for charge in charges}
        pair = [by_id.get(charge_id) for charge_id in evidence.matching_charge_ids]
        if any(charge is None for charge in pair):
            return PolicyAssessment(
                decision=PolicyDecision.MANUAL_REVIEW,
                policy_code="evidence-missing",
                reason="Policy evidence is incomplete.",
            )
        complete_pair = [charge for charge in pair if charge is not None]
        if any(charge.status != ChargeStatus.CAPTURED for charge in complete_pair):
            return PolicyAssessment(
                decision=PolicyDecision.INELIGIBLE,
                policy_code="captured-only",
                reason="Only captured charges are refundable.",
            )
        if evidence.amount is None or evidence.amount <= 0:
            return PolicyAssessment(
                decision=PolicyDecision.INELIGIBLE,
                policy_code="positive-amount",
                reason="Refund amount must be positive.",
            )
        newest_charge = max(charge.charged_at for charge in complete_pair)
        age_days = (self._evaluated_at - newest_charge).days
        if age_days < 0:
            return PolicyAssessment(
                decision=PolicyDecision.MANUAL_REVIEW,
                policy_code="future-charge",
                reason="Charge timestamp is after the policy evaluation time.",
            )
        if age_days > self._maximum_age_days:
            return PolicyAssessment(
                decision=PolicyDecision.INELIGIBLE,
                policy_code="refund-window",
                reason=f"Charge age {age_days} days exceeds the refund window.",
            )
        return PolicyAssessment(
            decision=PolicyDecision.ELIGIBLE,
            policy_code="duplicate-charge-v1",
            reason="Confirmed captured duplicate is within the refund window.",
        )
