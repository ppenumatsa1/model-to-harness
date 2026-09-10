import time
from typing import Any, Literal

from ...infrastructure.telemetry import execute_tool
from ..state import DoubleChargeState
from .context import NodeContext


class InvestigationNodes(NodeContext):
    async def normalize_complaint(self, state: DoubleChargeState) -> dict[str, Any]:
        node = "normalize_complaint"
        await self._event(state, "node_started", "Complaint normalization started", node=node)
        await self._event(
            state,
            "model_call_started",
            "Configured model is normalizing the complaint",
            node=node,
            data={"model": "configured-foundry-deployment"},
        )
        started = time.monotonic()
        normalized = await self.model.normalize(state["complaint"])
        latency_ms = int((time.monotonic() - started) * 1000)
        await self._event(
            state,
            "model_call_completed",
            "Complaint normalized without changing business facts",
            node=node,
            data={"model": "configured-foundry-deployment", "latency_ms": latency_ms},
        )
        return {
            "normalized_complaint": normalized,
            "current_step": node,
            "safe_summaries": ["Complaint normalized into a concise factual statement."],
        }

    async def load_account(self, state: DoubleChargeState) -> dict[str, Any]:
        node = "load_account"
        attempt = state.get("load_attempts", 0) + 1
        await self._tool_start(state, node, "billing.load_account", attempt)
        result = await execute_tool(
            "load_account",
            self.gateway.load_account,
            state["run_id"],
            state["customer_id"],
            state["scenario_id"],
        )
        await self._tool_end(state, node, "billing.load_account", result, attempt)
        if not result.ok and result.transient and attempt < 2:
            await self._event(
                state,
                "tool_call_retried",
                "Transient account read failed; bounded retry selected",
                node=node,
                status="retrying",
                data={"tool": "billing.load_account", "attempt": attempt, "route": "retry"},
            )
        return {
            "load_attempts": attempt,
            "charges": result.value.get("charges", []) if result.ok else [],
            "failure_code": result.code if not result.ok else None,
            "status": "running",
            "current_step": node,
        }

    def route_load(self, state: DoubleChargeState) -> Literal["retry", "loaded", "failed"]:
        if state.get("charges"):
            return "loaded"
        if state.get("load_attempts", 0) < 2 and state.get("failure_code", "").startswith(
            "TRANSIENT"
        ):
            return "retry"
        return "failed"

    async def detect_duplicate(self, state: DoubleChargeState) -> dict[str, Any]:
        node = "detect_duplicate"
        await self._tool_start(state, node, "billing.detect_duplicate")
        result = await execute_tool(
            "detect_duplicate",
            self.gateway.detect_duplicate,
            state["run_id"],
            state["customer_id"],
            state["charges"],
            state["scenario_id"],
        )
        await self._tool_end(state, node, "billing.detect_duplicate", result)
        decision = str(result.value.get("decision", "unknown")) if result.ok else "failed"
        evidence = result.value.get("evidence", {}) if result.ok else {}
        await self._event(
            state,
            "decision_summary",
            result.safe_summary or f"Duplicate decision: {decision}",
            node=node,
            data={"decision": decision},
        )
        return {
            "duplicate_decision": decision,
            "duplicate_evidence": evidence,
            "failure_code": result.code if not result.ok else None,
            "current_step": node,
            "safe_summaries": [result.safe_summary or f"Duplicate decision: {decision}"],
        }

    def route_duplicate(
        self, state: DoubleChargeState
    ) -> Literal["duplicate", "no_duplicate", "failed"]:
        decision = state.get("duplicate_decision")
        if decision in {"duplicate", "confirmed", "yes"}:
            return "duplicate"
        if decision in {"not_duplicate", "no_duplicate", "not_found", "no"}:
            return "no_duplicate"
        return "failed"
