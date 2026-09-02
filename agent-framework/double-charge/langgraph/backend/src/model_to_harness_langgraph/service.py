from typing import Any
from uuid import uuid4

from langgraph.types import Command

from .audit import ApprovalCommandConflictError, AuditRepository
from .contracts import (
    ApprovalRequest,
    CaseView,
    NativeEvent,
    OutcomeView,
    RunStatus,
    StartCaseRequest,
    StartCaseResponse,
)
from .outcome import map_framework_outcome
from .workflow import DoubleChargeWorkflow

PUBLIC_STATE_KEYS = {
    "normalized_complaint",
    "scenario_id",
    "current_step",
    "status",
    "duplicate_decision",
    "validation_results",
    "approval_decision",
    "refund_attempts",
    "refund_status",
    "refund_id",
    "notification_status",
    "failure_code",
    "terminal_status",
    "safe_summaries",
}


class CaseNotFoundError(LookupError):
    pass


class InvalidCommandError(ValueError):
    pass


class WorkflowService:
    def __init__(self, workflow: DoubleChargeWorkflow, audit: AuditRepository) -> None:
        self.workflow = workflow
        self.audit = audit

    async def start(self, request: StartCaseRequest) -> StartCaseResponse:
        case_id = request.existing_case_id or f"case-{uuid4().hex[:12]}"
        run_id = f"run-{uuid4().hex[:12]}"
        thread_id = f"langgraph:{run_id}"
        idempotency_key = request.idempotency_key or f"refund:{case_id}"
        state = {
            "case_id": case_id,
            "run_id": run_id,
            "thread_id": thread_id,
            "complaint": request.complaint,
            "customer_id": request.customer_id,
            "scenario_id": request.scenario_id,
            "idempotency_key": idempotency_key,
            "current_step": "start",
            "status": "running",
            "charges": [],
            "load_attempts": 0,
            "validation_results": {},
            "evidence": [],
            "refund_attempts": 0,
            "safe_summaries": [],
            "selected_memory": {},
        }
        await self.audit.create_run(
            {
                "run_id": run_id,
                "case_id": case_id,
                "customer_id": request.customer_id,
                "status": "running",
                "current_step": "start",
                "checkpoint_id": None,
                "approval_required": False,
                "state": {},
                "outcome": None,
            }
        )
        await self.audit.append_event(
            case_id=case_id,
            run_id=run_id,
            event_type="run_started",
            summary="Double-charge workflow started",
            node="start",
            status="running",
        )
        result = await self.workflow.graph.ainvoke(
            state,
            config={"configurable": {"thread_id": thread_id}},
        )
        return await self._persist_result(result)

    async def submit_approval(self, case_id: str, approval: ApprovalRequest) -> None:
        run = await self._require_run(case_id)
        existing = await self.audit.get_approval(run["run_id"])
        if run["status"] != RunStatus.PAUSED and existing is None:
            raise InvalidCommandError("Run is not waiting for approval")
        if existing is None and approval.checkpoint_id != run["checkpoint_id"]:
            raise InvalidCommandError("Checkpoint does not match the pending interrupt")
        try:
            await self.audit.save_approval(run["run_id"], approval.model_dump())
        except ApprovalCommandConflictError as exc:
            raise InvalidCommandError(str(exc)) from exc
        await self.audit.append_event(
            case_id=case_id,
            run_id=run["run_id"],
            event_type="approval_command_recorded",
            summary=f"Reviewer command recorded: {approval.decision}",
            node="request_approval",
            status="pending_resume",
            data={"decision": approval.decision, "checkpoint_id": approval.checkpoint_id},
            dedupe_key=f"approval-command:{run['run_id']}",
        )

    async def resume(self, case_id: str) -> StartCaseResponse:
        run = await self._require_run(case_id)
        if run["status"] != RunStatus.PAUSED:
            raise InvalidCommandError("Run is not paused")
        approval = await self.audit.get_pending_approval(run["run_id"])
        if not approval:
            raise InvalidCommandError("Record an approval command before resuming")
        await self.audit.append_event(
            case_id=case_id,
            run_id=run["run_id"],
            event_type="run_resumed",
            summary="Durable run resumed from the approval checkpoint",
            node="request_approval",
            status="running",
            data={"checkpoint_id": run["checkpoint_id"]},
            dedupe_key=f"resume:{run['run_id']}",
        )
        command = Command(
            resume={
                "decision": approval["decision"],
                "reviewer_id": approval["reviewer_id"],
                "reason": approval.get("reason"),
            }
        )
        result = await self.workflow.graph.ainvoke(
            command,
            config={"configurable": {"thread_id": f"langgraph:{run['run_id']}"}},
        )
        await self.audit.consume_approval(run["run_id"])
        return await self._persist_result(result)

    async def get_case(self, case_id: str) -> CaseView:
        run = await self._require_run(case_id)
        memory = await self.audit.get_memory(run["customer_id"], case_id)
        return CaseView(
            case_id=case_id,
            run_id=run["run_id"],
            status=RunStatus(run["status"]),
            current_step=run["current_step"],
            checkpoint_id=run.get("checkpoint_id"),
            approval_required=bool(run.get("approval_required")),
            workflow_state=run.get("state") or {},
            selected_memory=memory,
            outcome=OutcomeView.model_validate(run["outcome"]) if run.get("outcome") else None,
        )

    async def continue_run(self, case_id: str) -> StartCaseResponse:
        """Continue a durable graph after a worker-level recovery breakpoint."""
        run = await self._require_run(case_id)
        result = await self.workflow.graph.ainvoke(
            None,
            config={"configurable": {"thread_id": f"langgraph:{run['run_id']}"}},
        )
        return await self._persist_result(result)

    async def list_events(self, case_id: str, after: int = 0) -> list[NativeEvent]:
        run = await self._require_run(case_id)
        return await self.audit.list_events(run["run_id"], after)

    async def explain(self, case_id: str, question: str) -> tuple[str, list[int]]:
        events = await self.list_events(case_id)
        relevant = [
            event
            for event in events
            if event.event_type
            in {
                "decision_summary",
                "parallel_branch_joined",
                "human_approval_requested",
                "human_approval_resolved",
                "refund_verification",
                "run_completed",
                "run_failed",
            }
        ][-5:]
        if not relevant:
            return (
                "The run has started, but no allowlisted decision summary is available yet.",
                [],
            )
        answer = " ".join(event.summary for event in relevant)
        if "state" in question.lower() or "memory" in question.lower():
            answer += (
                " Workflow state drives the current execution; selected memory contains only "
                "narrow case facts retained separately after a terminal step."
            )
        return answer, [event.sequence for event in relevant]

    async def _persist_result(self, result: dict[str, Any]) -> StartCaseResponse:
        interrupts = result.get("__interrupt__", ())
        snapshot = _public_state(result)
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

    async def _require_run(self, case_id: str) -> dict[str, Any]:
        run = await self.audit.get_run_by_case(case_id)
        if not run:
            raise CaseNotFoundError(case_id)
        return run


def _public_state(state: dict[str, Any]) -> dict[str, Any]:
    return {key: state[key] for key in PUBLIC_STATE_KEYS if key in state}
