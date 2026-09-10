from collections import defaultdict
from typing import Any

from model_to_harness_langgraph.infrastructure.domain_gateway import ToolResult


class FakeModel:
    async def normalize(self, complaint: str) -> str:
        return "Customer reports two charges for one purchase."

    async def draft_notification(self, facts: dict[str, str]) -> str:
        return f"Case {facts['case_id']}: refund {facts['refund_status']}."


class FakeDomainGateway:
    def __init__(self) -> None:
        self.load_calls: defaultdict[str, int] = defaultdict(int)
        self.refund_calls: defaultdict[str, int] = defaultdict(int)
        self.refunds: dict[str, str] = {}

    async def load_account(self, run_id: str, customer_id: str, scenario_id: str) -> ToolResult:
        del run_id, customer_id
        self.load_calls[scenario_id] += 1
        if scenario_id == "transient_failure" and self.load_calls[scenario_id] < 3:
            return ToolResult(
                ok=False,
                code="TRANSIENT_BILLING_READ",
                transient=True,
                safe_summary="Billing read was temporarily unavailable",
            )
        return ToolResult(
            ok=True,
            value={
                "charges": [
                    {
                        "charge_id": "ch-1",
                        "purchase_reference": "purchase-7",
                        "amount": "42.00",
                    },
                    {
                        "charge_id": "ch-2",
                        "purchase_reference": "purchase-7",
                        "amount": "42.00",
                    },
                ]
            },
            safe_summary="Two charge records loaded",
        )

    async def detect_duplicate(
        self,
        run_id: str,
        customer_id: str,
        charges: list[dict[str, Any]],
        scenario_id: str,
    ) -> ToolResult:
        del run_id, customer_id, scenario_id
        # The no-duplicate fixture is represented by changing the loaded records in
        # production; tests override this method in NoDuplicateGateway.
        duplicate = (
            len(charges) == 2
            and charges[0]["purchase_reference"] == charges[1]["purchase_reference"]
        )
        return ToolResult(
            ok=True,
            value={
                "decision": "duplicate" if duplicate else "no_duplicate",
                "evidence": {"charge_ids": [item["charge_id"] for item in charges]},
            },
            safe_summary=(
                "Two captured charges share purchase reference and amount"
                if duplicate
                else "No matching duplicate pair was found"
            ),
        )

    async def validate_billing(
        self,
        run_id: str,
        customer_id: str,
        charges: list[dict[str, Any]],
        duplicate_evidence: dict[str, Any],
        scenario_id: str,
    ) -> ToolResult:
        del run_id, customer_id, charges, duplicate_evidence, scenario_id
        return ToolResult(
            ok=True,
            value={"captured": True},
            safe_summary="Both charges are captured",
        )

    async def validate_policy(
        self,
        run_id: str,
        customer_id: str,
        charges: list[dict[str, Any]],
        duplicate_evidence: dict[str, Any],
        scenario_id: str,
    ) -> ToolResult:
        del run_id, customer_id, charges, duplicate_evidence, scenario_id
        return ToolResult(
            ok=True,
            value={"within_window": True},
            safe_summary="Refund is within the policy window",
        )

    async def submit_refund(
        self,
        run_id: str,
        customer_id: str,
        duplicate_evidence: dict[str, Any],
        idempotency_key: str,
        scenario_id: str,
    ) -> ToolResult:
        del run_id, customer_id, duplicate_evidence
        self.refund_calls[idempotency_key] += 1
        refund_id = self.refunds.setdefault(idempotency_key, "rf-1")
        if scenario_id == "retry_safe_refund" and self.refund_calls[idempotency_key] == 1:
            return ToolResult(
                ok=False,
                uncertain=True,
                value={"refund_id": refund_id},
                safe_summary="Refund accepted but response was uncertain",
            )
        return ToolResult(
            ok=True,
            value={"refund_id": refund_id},
            safe_summary="Existing idempotent refund returned"
            if self.refund_calls[idempotency_key] > 1
            else "Refund submitted",
        )

    async def verify_refund(
        self,
        run_id: str,
        customer_id: str,
        idempotency_key: str,
        scenario_id: str,
        durable_refund_id: str | None,
    ) -> ToolResult:
        del run_id, customer_id
        count = 2 if scenario_id == "verification_mismatch" else 1
        return ToolResult(
            ok=count == 1,
            value={
                "matching_refunds": count,
                "refund_id": durable_refund_id or self.refunds.get(idempotency_key, "rf-1"),
            },
            code=None if count == 1 else "VERIFY_MISMATCH",
            safe_summary=f"Found {count} matching refund record(s)",
        )

    async def send_notification(
        self,
        run_id: str,
        customer_id: str,
        message: str,
        scenario_id: str,
    ) -> ToolResult:
        del run_id, customer_id, message, scenario_id
        return ToolResult(ok=True, safe_summary="Customer notification sent")


class NoDuplicateGateway(FakeDomainGateway):
    async def load_account(self, run_id: str, customer_id: str, scenario_id: str) -> ToolResult:
        del run_id, customer_id, scenario_id
        return ToolResult(
            ok=True,
            value={
                "charges": [
                    {
                        "charge_id": "ch-1",
                        "purchase_reference": "purchase-7",
                        "amount": "42.00",
                    }
                ]
            },
            safe_summary="One charge record loaded",
        )
