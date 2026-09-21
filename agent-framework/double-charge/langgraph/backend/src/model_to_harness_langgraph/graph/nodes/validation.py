from dataclasses import replace
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
            data={
                "branch": "billing", "eligible": result.ok, "ok": result.ok,
                "failure_code": result.code,
                "checked_charge_ids": result.value.get("checked_charge_ids", [])[:100],
            },
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
        ineligible = (
            result.code == "POLICY_INELIGIBLE"
            and result.value.get("decision") == "ineligible"
        )
        await self._tool_end(
            state,
            node,
            "policy.validate_refund",
            replace(result, ok=True) if ineligible else result,
        )
        await self._event(
            state,
            "parallel_branch_completed",
            result.safe_summary or "Refund-policy validation completed",
            node=node,
            data={
                "branch": "policy", "eligible": result.ok, "ok": result.ok or ineligible,
                "failure_code": result.code,
                "policy_code": result.value.get("policy_code"),
                "decision": result.value.get("decision"),
            },
        )
        return {
            "validation_results": {
                "policy": {
                    "ok": result.ok,
                    "code": result.code,
                    "decision": result.value.get("decision"),
                    "summary": result.safe_summary,
                }
            },
            "evidence": [{"source": "policy", **result.value}],
        }

    async def join_validations(self, state: DoubleChargeState) -> dict[str, Any]:
        results = state.get("validation_results", {})
        route = self.route_validation(state)
        eligible = route == "eligible"
        summary = (
            "Billing and policy checks both passed."
            if eligible
            else "Policy assessment completed; refund is ineligible."
            if route == "ineligible"
            else "At least one required validation failed."
        )
        await self._event(
            state,
            "parallel_branch_joined",
            summary,
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
            "safe_summaries": [summary],
        }

    def route_validation(
        self, state: DoubleChargeState
    ) -> Literal["eligible", "ineligible", "failed"]:
        results = state.get("validation_results", {})
        if not results.get("billing", {}).get("ok"):
            return "failed"
        policy = results.get("policy", {})
        if policy.get("ok"):
            return "eligible"
        if policy.get("code") == "POLICY_INELIGIBLE" and policy.get("decision") == "ineligible":
            return "ineligible"
        return "failed"
