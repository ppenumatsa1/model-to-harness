from typing import Any

from ...infrastructure.telemetry import execute_tool
from ..state import DoubleChargeState
from .context import NodeContext


class CompletionNodes(NodeContext):
    async def notify_customer(self, state: DoubleChargeState) -> dict[str, Any]:
        node = "notify_customer"
        events = await self.audit.list_events(state["run_id"])
        if any(
            event.node == node
            and event.event_type == "tool_call_succeeded"
            and event.data.get("tool") == "notification.send"
            for event in events
        ):
            return {"notification_status": "sent", "failure_code": None, "current_step": node}
        await self._event(
            state,
            "model_call_started",
            "Configured model is drafting an allowlisted customer update",
            node=node,
            data={"model": "configured-foundry-deployment"},
        )
        message = await self.model.draft_notification(
            {
                "case_id": state["case_id"],
                "refund_status": state["refund_status"],
                "refund_id": state.get("refund_id") or "not available",
            }
        )
        await self._event(
            state,
            "model_call_completed",
            "Customer update drafted",
            node=node,
            data={"model": "configured-foundry-deployment"},
        )
        await self._tool_start(state, node, "notification.send")
        result = await execute_tool(
            "send_notification",
            self.gateway.send_notification,
            state["run_id"],
            state["customer_id"],
            message,
            state["scenario_id"],
        )
        await self._tool_end(state, node, "notification.send", result)
        return {
            "notification_status": "sent" if result.ok else "failed",
            "failure_code": result.code if not result.ok else None,
            "current_step": node,
        }

    async def _terminal(
        self,
        state: DoubleChargeState,
        *,
        terminal_status: str,
        summary: str,
        refund_status: str | None = None,
        notification_status: str | None = None,
    ) -> dict[str, Any]:
        await self._event(
            state,
            "run_completed" if terminal_status != "failed" else "run_failed",
            summary,
            node=terminal_status,
            status=terminal_status,
            data={"failure_code": state.get("failure_code")},
        )
        selected_memory = {
            "case_id": state["case_id"],
            "duplicate_decision": state.get("duplicate_decision", "unknown"),
            "refund_status": refund_status or state.get("refund_status", "not_requested"),
        }
        await self.audit.upsert_memory(state["customer_id"], state["case_id"], selected_memory)
        return {
            "terminal_status": terminal_status,
            "status": terminal_status,
            "current_step": terminal_status,
            "refund_status": refund_status or state.get("refund_status", "not_requested"),
            "notification_status": notification_status
            or state.get("notification_status", "not_sent"),
            "selected_memory": selected_memory,
            "safe_summaries": [summary],
        }

    async def close_no_duplicate(self, state: DoubleChargeState) -> dict[str, Any]:
        return await self._terminal(
            state,
            terminal_status="completed",
            summary="Case closed because no duplicate charge was found.",
            refund_status="not_required",
        )

    async def close_denied(self, state: DoubleChargeState) -> dict[str, Any]:
        return await self._terminal(
            state,
            terminal_status="completed",
            summary="Case closed without refund after reviewer denial.",
            refund_status="denied",
        )

    async def close_success(self, state: DoubleChargeState) -> dict[str, Any]:
        if state.get("notification_status") != "sent":
            return await self._terminal(
                state,
                terminal_status="failed",
                summary="Refund was verified but customer notification failed.",
            )
        return await self._terminal(
            state,
            terminal_status="completed",
            summary="Exactly one refund was verified and the customer was notified.",
        )

    async def fail_load(self, state: DoubleChargeState) -> dict[str, Any]:
        return await self._terminal(
            state,
            terminal_status="failed",
            summary="Account loading failed after bounded retries.",
            refund_status="not_submitted",
        )

    async def fail_validation(self, state: DoubleChargeState) -> dict[str, Any]:
        return await self._terminal(
            state,
            terminal_status="failed",
            summary="Required deterministic validation failed.",
            refund_status="not_submitted",
        )

    async def fail_refund(self, state: DoubleChargeState) -> dict[str, Any]:
        return await self._terminal(
            state,
            terminal_status="failed",
            summary="Refund processing failed without claiming success.",
        )

    async def manual_review(self, state: DoubleChargeState) -> dict[str, Any]:
        return await self._terminal(
            state,
            terminal_status="manual_review",
            summary="Refund verification mismatch requires manual review.",
        )
