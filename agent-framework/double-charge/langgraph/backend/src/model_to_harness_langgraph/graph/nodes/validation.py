from typing import Any, Literal

from ...infrastructure.telemetry import execute_tool
from ..state import DoubleChargeState
from .context import NodeContext


class ValidationNodes(NodeContext):
    async def dispatch_validations(self, state: DoubleChargeState) -> dict[str, Any]:
        await self._event(
            state,
            "parallel_branch_started",
            "Billing and refund-policy validation started in parallel",
            node="dispatch_validations",
            data={"branch": "billing+policy"},
        )
        return {"current_step": "parallel_validation"}

    async def billing_validation(self, state: DoubleChargeState) -> dict[str, Any]:
        node = "billing_validation"
        await self._tool_start(state, node, "billing.validate_charge")
        result = await execute_tool(
            "validate_billing",
            self.gateway.validate_billing,
            state["run_id"],
            state["customer_id"],
            state["charges"],
            state["duplicate_evidence"],
            state["scenario_id"],
        )
        await self._tool_end(state, node, "billing.validate_charge", result)
        await self._event(
            state,
            "parallel_branch_completed",
            result.safe_summary or "Billing validation completed",
            node=node,
            data={"branch": "billing", "eligible": result.ok},
        )
        return {
            "validation_results": {
                "billing": {
                    "ok": result.ok,
                    "code": result.code,
                    "summary": result.safe_summary,
                }
            },
            "evidence": [{"source": "billing", **result.value}],
        }

    async def policy_validation(self, state: DoubleChargeState) -> dict[str, Any]:
        node = "policy_validation"
        await self._tool_start(state, node, "policy.validate_refund")
        result = await execute_tool(
            "validate_policy",
            self.gateway.validate_policy,
            state["run_id"],
            state["customer_id"],
            state["charges"],
            state["duplicate_evidence"],
            state["scenario_id"],
        )
        await self._tool_end(state, node, "policy.validate_refund", result)
        await self._event(
            state,
            "parallel_branch_completed",
            result.safe_summary or "Refund-policy validation completed",
            node=node,
            data={"branch": "policy", "eligible": result.ok},
        )
        return {
            "validation_results": {
                "policy": {
                    "ok": result.ok,
                    "code": result.code,
                    "summary": result.safe_summary,
                }
            },
            "evidence": [{"source": "policy", **result.value}],
        }

    async def join_validations(self, state: DoubleChargeState) -> dict[str, Any]:
        results = state.get("validation_results", {})
        eligible = bool(
            results.get("billing", {}).get("ok") and results.get("policy", {}).get("ok")
        )
        await self._event(
            state,
            "parallel_branch_joined",
            "Parallel validations joined; refund evidence is sufficient"
            if eligible
            else "Parallel validations joined; evidence is insufficient",
            node="join_validations",
            data={"eligible": eligible},
        )
        failure_code = None
        if not eligible:
            failure_code = next(
                (
                    result.get("code")
                    for result in results.values()
                    if not result.get("ok") and result.get("code")
                ),
                "VALIDATION_FAILED",
            )
        return {
            "current_step": "join_validations",
            "failure_code": failure_code,
            "safe_summaries": [
                "Billing and policy checks both passed."
                if eligible
                else "At least one required validation failed."
            ],
        }

    def route_validation(self, state: DoubleChargeState) -> Literal["eligible", "failed"]:
        results = state.get("validation_results", {})
        return (
            "eligible"
            if results.get("billing", {}).get("ok") and results.get("policy", {}).get("ok")
            else "failed"
        )
