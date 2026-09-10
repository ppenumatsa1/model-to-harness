from typing import Any, Literal

from langgraph.types import interrupt

from ...application.ports import ApprovalCommandConflictError
from ..state import DoubleChargeState
from .context import NodeContext


class ApprovalNodes(NodeContext):
    async def request_approval(self, state: DoubleChargeState) -> dict[str, Any]:
        node = "request_approval"
        checkpoint_label = f"approval:{state['run_id']}"
        await self._event(
            state,
            "checkpoint_created",
            "Durable approval checkpoint created",
            node=node,
            status="paused",
            data={"checkpoint_id": checkpoint_label},
            dedupe_key=f"checkpoint:{state['run_id']}",
        )
        await self._event(
            state,
            "human_approval_requested",
            "Refund approval is required before submission",
            node=node,
            status="paused",
            data={"checkpoint_id": checkpoint_label},
            dedupe_key=f"approval-request:{state['run_id']}",
        )
        response = interrupt(
            {
                "kind": "refund_approval",
                "case_id": state["case_id"],
                "run_id": state["run_id"],
                "summary": "Duplicate charge and policy evidence passed; approve refund?",
            }
        )
        approval = await self.audit.get_approval(state["run_id"])
        if (
            not isinstance(response, dict)
            or approval is None
            or any(
                response.get(key) != approval.get(key)
                for key in ("decision", "reviewer_id", "reason")
            )
        ):
            raise ApprovalCommandConflictError(
                "Native resume requires the recorded approval command"
            )
        decision = approval["decision"]
        await self._event(
            state,
            "human_approval_resolved",
            f"Reviewer decision recorded: {decision}",
            node=node,
            status="resumed",
            data={"decision": decision},
            dedupe_key=f"approval-resolved:{state['run_id']}",
        )
        return {
            "approval_decision": decision,
            "approval_reviewer": str(response.get("reviewer_id", "unknown")),
            "approval_reason": response.get("reason"),
            "approval_checkpoint_label": checkpoint_label,
            "status": "running",
            "current_step": node,
        }

    def route_approval(self, state: DoubleChargeState) -> Literal["approved", "denied"]:
        return "approved" if state.get("approval_decision") == "approve" else "denied"
