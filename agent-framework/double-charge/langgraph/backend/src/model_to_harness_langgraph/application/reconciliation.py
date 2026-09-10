from typing import Any

from ..projections.outcome import map_framework_outcome
from ..projections.state import public_state
from .ports import AuditRepository
from .records import OutcomeView, RunStatus, StartCaseResponse


class ResultReconciler:
    def __init__(self, audit: AuditRepository) -> None:
        self.audit = audit

    async def persist(self, result: dict[str, Any]) -> StartCaseResponse:
        interrupts = result.get("__interrupt__", ())
        snapshot = public_state(result)
        if interrupts:
            pending = interrupts[0]
            checkpoint_id = str(getattr(pending, "id", f"approval:{result['run_id']}"))
            await self.audit.append_event(
                case_id=result["case_id"],
                run_id=result["run_id"],
                event_type="checkpoint_bound",
                summary="LangGraph interrupt identifier bound to the approval command",
                node="request_approval",
                status="paused",
                data={"checkpoint_id": checkpoint_id},
                dedupe_key=f"checkpoint-bound:{result['run_id']}",
            )
            await self.audit.update_run(
                result["run_id"],
                {
                    "status": "paused",
                    "current_step": "request_approval",
                    "checkpoint_id": checkpoint_id,
                    "approval_required": True,
                    "state": snapshot,
                },
            )
            return StartCaseResponse(
                case_id=result["case_id"],
                run_id=result["run_id"],
                status=RunStatus.PAUSED,
                current_step="request_approval",
                approval_required=True,
                checkpoint_id=checkpoint_id,
            )

        if not result.get("terminal_status"):
            current_step = str(result.get("current_step", "running"))
            await self.audit.update_run(
                result["run_id"],
                {
                    "status": "running",
                    "current_step": current_step,
                    "checkpoint_id": result.get("approval_checkpoint_label"),
                    "approval_required": False,
                    "state": snapshot,
                    "outcome": None,
                },
            )
            return StartCaseResponse(
                case_id=result["case_id"],
                run_id=result["run_id"],
                status=RunStatus.RUNNING,
                current_step=current_step,
                approval_required=False,
                checkpoint_id=result.get("approval_checkpoint_label"),
            )

        status = str(result["terminal_status"])
        outcome = await self._outcome(result)
        await self.audit.update_run(
            result["run_id"],
            {
                "status": status,
                "current_step": str(result.get("current_step", status)),
                "checkpoint_id": result.get("approval_checkpoint_label"),
                "approval_required": False,
                "state": snapshot,
                "outcome": outcome.model_dump(mode="json"),
            },
        )
        return StartCaseResponse(
            case_id=result["case_id"],
            run_id=result["run_id"],
            status=RunStatus(status),
            current_step=str(result.get("current_step", status)),
            approval_required=False,
            checkpoint_id=result.get("approval_checkpoint_label"),
        )

    async def _outcome(self, state: dict[str, Any]) -> OutcomeView:
        events = await self.audit.list_events(state["run_id"])
        shared = map_framework_outcome(state, events)
        return OutcomeView(
            case_id=shared.case_id,
            run_id=shared.run_id,
            duplicate_decision=str(shared.duplicate_decision),
            policy_decision=str(shared.policy_decision),
            approval_decision=str(shared.approval_decision),
            refund_status=str(shared.refund_status),
            refund_id=shared.refund_id,
            notification_status=str(shared.notification_status),
            terminal_status=str(shared.terminal_status),
            failure_code=str(shared.failure_code),
            event_summary=[event.event_type for event in events],
        )
