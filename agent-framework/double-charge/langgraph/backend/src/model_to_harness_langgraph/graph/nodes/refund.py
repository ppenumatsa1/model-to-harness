import hashlib
import json
from typing import Any, Literal

from ...application.ports import RefundIdempotencyConflictError
from ...infrastructure.domain_gateway import ToolResult
from ...infrastructure.telemetry import execute_tool
from ..state import DoubleChargeState
from .context import NodeContext


class RefundNodes(NodeContext):
    async def submit_refund(self, state: DoubleChargeState) -> dict[str, Any]:
        node = "submit_refund"
        attempt = state.get("refund_attempts", 0) + 1
        request_fingerprint = _refund_fingerprint(state)
        existing = await self.audit.get_refund(state["idempotency_key"])
        if existing is not None:
            if existing["request_fingerprint"] != request_fingerprint:
                await self._event(
                    state,
                    "refund_idempotency_lookup",
                    "Idempotency key is bound to a different refund request",
                    node=node,
                    status="failed",
                    data={"failure_code": "REFUND_IDEMPOTENCY_CONFLICT"},
                )
                return {
                    "refund_attempts": attempt,
                    "refund_status": "failed",
                    "failure_code": "REFUND_IDEMPOTENCY_CONFLICT",
                    "current_step": node,
                }
            await self._event(
                state,
                "refund_idempotency_lookup",
                "Existing durable refund found for the same request",
                node=node,
                status="completed",
                data={"refund_id": existing["refund_id"]},
            )
            return {
                "refund_attempts": attempt,
                "refund_status": "submitted",
                "refund_id": existing["refund_id"],
                "failure_code": None,
                "current_step": node,
            }
        await self._tool_start(state, node, "billing.submit_refund", attempt)
        result = await execute_tool(
            "submit_refund",
            self.gateway.submit_refund,
            state["run_id"],
            state["customer_id"],
            state["duplicate_evidence"],
            state["idempotency_key"],
            state["scenario_id"],
        )
        refund_id = result.value.get("refund_id")
        if (result.ok or result.uncertain) and not refund_id:
            result = ToolResult(
                ok=False,
                code="REFUND_SUBMISSION_FAILED",
                safe_summary="Refund response did not include a durable refund identifier",
            )
        if (result.ok or result.uncertain) and refund_id:
            try:
                durable = await self.audit.record_refund(
                    {
                        "idempotency_key": state["idempotency_key"],
                        "request_fingerprint": request_fingerprint,
                        "refund_id": refund_id,
                        "case_id": state["case_id"],
                        "run_id": state["run_id"],
                        "customer_id": state["customer_id"],
                    }
                )
                refund_id = durable["refund_id"]
            except RefundIdempotencyConflictError:
                result = ToolResult(
                    ok=False,
                    code="REFUND_IDEMPOTENCY_CONFLICT",
                    safe_summary="Durable idempotency key conflicts with another request",
                )
        await self._tool_end(state, node, "billing.submit_refund", result, attempt)
        if result.uncertain and attempt < 2:
            await self._event(
                state,
                "tool_call_retried",
                "Refund response was uncertain; retrying with the same idempotency key",
                node=node,
                status="retrying",
                data={"tool": "billing.submit_refund", "attempt": attempt, "route": "retry"},
            )
        return {
            "refund_attempts": attempt,
            "refund_status": (
                "uncertain" if result.uncertain else "submitted" if result.ok else "failed"
            ),
            "refund_id": refund_id,
            "failure_code": result.code if not result.ok and not result.uncertain else None,
            "current_step": node,
        }

    def route_refund(self, state: DoubleChargeState) -> Literal["retry", "submitted", "failed"]:
        if state.get("refund_status") == "submitted":
            return "submitted"
        if state.get("refund_status") == "uncertain" and state.get("refund_attempts", 0) < 2:
            return "retry"
        return "failed"

    async def verify_refund(self, state: DoubleChargeState) -> dict[str, Any]:
        node = "verify_refund"
        await self._event(
            state,
            "refund_idempotency_lookup",
            "Checking refund by idempotency key",
            node=node,
        )
        durable = await self.audit.get_refund(state["idempotency_key"])
        result = await execute_tool(
            "verify_refund",
            self.gateway.verify_refund,
            state["run_id"],
            state["customer_id"],
            state["idempotency_key"],
            state["scenario_id"],
            durable["refund_id"] if durable else None,
        )
        reported_count = result.value.get("matching_refunds", 0)
        count = reported_count if type(reported_count) is int and reported_count >= 0 else 0
        verified = (
            result.ok
            and type(count) is int
            and count == 1
            and durable is not None
            and result.value.get("refund_id") == durable["refund_id"]
        )
        await self._event(
            state,
            "refund_verification",
            result.safe_summary or f"Refund verification found {count} matching record(s)",
            node=node,
            status="completed" if verified else "failed",
            data={"verified_count": count, "refund_id": result.value.get("refund_id")},
        )
        return {
            "refund_status": "verified" if verified else "mismatch",
            "refund_id": durable["refund_id"] if durable else state.get("refund_id"),
            "failure_code": None if verified else result.code or "VERIFY_MISMATCH",
            "current_step": node,
        }

    def route_verification(
        self, state: DoubleChargeState
    ) -> Literal["verified", "manual_review", "failed"]:
        if state.get("refund_status") == "verified":
            return "verified"
        if state.get("failure_code") == "VERIFY_MISMATCH":
            return "manual_review"
        return "failed"


def _refund_fingerprint(state: DoubleChargeState) -> str:
    evidence = state.get("duplicate_evidence", {})
    request = {
        "customer_id": state["customer_id"],
        "charge_ids": sorted(evidence.get("matching_charge_ids", [])),
        "amount": evidence.get("amount"),
        "currency": evidence.get("currency"),
    }
    encoded = json.dumps(request, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()
