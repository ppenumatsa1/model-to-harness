from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from model_to_harness_shared import (
    ApprovalCommand as SharedApprovalCommand,
)
from model_to_harness_shared import (
    ApprovalDecision as SharedApprovalDecision,
)
from model_to_harness_shared import (
    ApprovalSimulator,
    BillingSimulator,
    DuplicateEvidence,
    RefundPolicySimulator,
    ScenarioFixture,
    get_fixture,
)

from ..application.models import ApprovalDecision


@dataclass
class SimulatedActions:
    """Per-run deterministic action boundary implemented by the root shared package."""

    fixture: ScenarioFixture
    billing: BillingSimulator
    policy: RefundPolicySimulator
    approvals: ApprovalSimulator
    last_evidence: DuplicateEvidence | None = None
    shared_approval_checkpoint_id: str | None = None

    @classmethod
    def for_fixture(cls, fixture_id: str) -> SimulatedActions:
        fixture = get_fixture(fixture_id)
        behavior = fixture.billing_behavior
        return cls(
            fixture=fixture,
            billing=BillingSimulator(
                fixture.charges,
                transient_read_failures=behavior.transient_read_failures,
                uncertain_refund_response_once=behavior.uncertain_refund_response_once,
                verification_count_override=behavior.verification_count_override,
            ),
            policy=RefundPolicySimulator(),
            approvals=ApprovalSimulator(),
        )

    @property
    def account_id(self) -> str:
        return self.fixture.scenario_input.account_id

    @property
    def maximum_read_attempts(self) -> int:
        return self.fixture.maximum_read_attempts

    def load_account(self) -> dict[str, Any]:
        charges = self.billing.load_charges(self.account_id)
        return {
            "account_id": self.account_id,
            "charge_count": len(charges),
            "charges": [charge.model_dump(mode="json") for charge in charges],
        }

    def detect_duplicate(self) -> dict[str, Any]:
        evidence = self.billing.detect_duplicate(self.account_id)
        self.last_evidence = evidence
        return evidence.model_dump(mode="json")

    def validate_billing(self, evidence_data: dict[str, Any]) -> dict[str, Any]:
        evidence = DuplicateEvidence.model_validate(evidence_data)
        self.last_evidence = evidence
        return self.billing.validate_duplicate(evidence).model_dump(mode="json")

    def validate_policy(
        self, evidence_data: dict[str, Any], account_summary: dict[str, Any]
    ) -> dict[str, Any]:
        evidence = DuplicateEvidence.model_validate(evidence_data)
        charge_type = type(self.fixture.charges[0]) if self.fixture.charges else None
        charges = (
            [charge_type.model_validate(item) for item in account_summary["charges"]]
            if charge_type
            else []
        )
        return self.policy.assess(evidence, charges).model_dump(mode="json")

    def request_approval(self, evidence_data: dict[str, Any], case_id: str) -> dict[str, Any]:
        evidence = DuplicateEvidence.model_validate(evidence_data)
        record = self.approvals.request(
            case_id=case_id,
            amount=evidence.amount or Decimal("0.01"),
            currency=evidence.currency or "USD",
        )
        self.shared_approval_checkpoint_id = record.checkpoint_id
        return record.model_dump(mode="json")

    def resolve_approval(
        self, decision: ApprovalDecision, reviewer_id: str, reason: str | None
    ) -> dict[str, Any]:
        if self.shared_approval_checkpoint_id is None:
            raise RuntimeError("shared approval request has not been created")
        shared_decision = (
            SharedApprovalDecision.APPROVED
            if decision == ApprovalDecision.APPROVE
            else SharedApprovalDecision.DENIED
        )
        return self.approvals.resolve(
            SharedApprovalCommand(
                checkpoint_id=self.shared_approval_checkpoint_id,
                decision=shared_decision,
                reviewer_id=reviewer_id,
                reason=reason,
            )
        ).model_dump(mode="json")

    def submit_refund(self, idempotency_key: str) -> dict[str, Any]:
        if self.last_evidence is None or not self.last_evidence.matching_charge_ids:
            raise RuntimeError("duplicate evidence is required before refund submission")
        refund = self.billing.submit_refund(
            account_id=self.account_id,
            charge_id=self.last_evidence.matching_charge_ids[-1],
            idempotency_key=idempotency_key,
        )
        return refund.model_dump(mode="json")

    def refund_request(self, idempotency_key: str) -> dict[str, Any]:
        if self.last_evidence is None or not self.last_evidence.matching_charge_ids:
            raise RuntimeError("duplicate evidence is required before refund submission")
        return {
            "account_id": self.account_id,
            "charge_id": self.last_evidence.matching_charge_ids[-1],
            "amount": str(self.last_evidence.amount or Decimal("0.00")),
            "currency": self.last_evidence.currency or "USD",
            "idempotency_key": idempotency_key,
        }

    def find_refund(self, idempotency_key: str) -> dict[str, Any] | None:
        refund = next(
            (item for item in self.billing.refunds if item.idempotency_key == idempotency_key),
            None,
        )
        return refund.model_dump(mode="json") if refund else None

    @property
    def verification_count_override(self) -> int | None:
        return self.fixture.billing_behavior.verification_count_override

    def verify_refund(self, idempotency_key: str) -> dict[str, Any]:
        return self.billing.verify_refund(idempotency_key).model_dump(mode="json")
