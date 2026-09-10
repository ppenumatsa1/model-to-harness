from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, Concatenate
from uuid import uuid4

from ..projections.state import public_state, selected_memory
from .ports import (
    ApprovalCommandConflictError,
    AuditRepository,
    CommandInProgressError,
    WorkflowRunner,
)
from .reconciliation import ResultReconciler
from .records import (
    ApprovalRequest,
    CaseView,
    NativeEvent,
    OutcomeView,
    RunStatus,
    StartCaseRequest,
    StartCaseResponse,
)


class CaseNotFoundError(LookupError):
    pass


class InvalidCommandError(ValueError):
    pass


def serialized_command[Target: (StartCaseRequest, str), Result, **P](
    function: Callable[Concatenate[WorkflowService, Target, P], Awaitable[Result]],
) -> Callable[Concatenate[WorkflowService, Target, P], Awaitable[Result]]:
    @wraps(function)
    async def execute(
        self: WorkflowService, target: Target, *args: P.args, **kwargs: P.kwargs
    ) -> Result:
        key = target.existing_case_id if isinstance(target, StartCaseRequest) else target
        if key is None:
            return await function(self, target, *args, **kwargs)
        try:
            async with self.audit.command_lock(key):
                return await function(self, target, *args, **kwargs)
        except CommandInProgressError as exc:
            raise InvalidCommandError(str(exc)) from exc

    return execute


class WorkflowService:
    def __init__(self, workflow: WorkflowRunner, audit: AuditRepository) -> None:
        self.workflow = workflow
        self.audit = audit
        self.results = ResultReconciler(audit)

    @serialized_command
    async def start(self, request: StartCaseRequest) -> StartCaseResponse:
        case_id = request.existing_case_id or f"case-{uuid4().hex[:12]}"
        if await self.audit.get_run_by_case(case_id):
            raise InvalidCommandError("A run already exists for this case")
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
        with self.workflow.trace_run(run_id, case_id=case_id, command="start"):
            result = await self.workflow.start(state)
        return await self.results.persist(result)

    @serialized_command
    async def submit_approval(self, case_id: str, approval: ApprovalRequest) -> None:
        run = await self._require_run(case_id)
        snapshot = await self.workflow.snapshot(run["run_id"])
        if snapshot is not None:
            await self.results.persist(snapshot)
            run = await self._require_run(case_id)
        existing = await self.audit.get_approval(run["run_id"])
        if existing is None and snapshot is None:
            raise InvalidCommandError("No durable approval interrupt is available")
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

    @serialized_command
    async def resume(self, case_id: str) -> StartCaseResponse:
        run = await self._require_run(case_id)
        approval = await self.audit.get_pending_approval(run["run_id"])
        if not approval:
            raise InvalidCommandError("Record an approval command before resuming")
        snapshot = await self.workflow.snapshot(run["run_id"])
        if snapshot is None:
            raise InvalidCommandError("No durable graph checkpoint is available")
        if not snapshot.get("__interrupt__"):
            if not snapshot.get("approval_decision"):
                raise InvalidCommandError("Run is not waiting for this approval")
            if snapshot["approval_decision"] != approval["decision"]:
                raise InvalidCommandError("Native checkpoint conflicts with recorded approval")
            with self.workflow.trace_run(run["run_id"], case_id=case_id, command="resume"):
                result = (
                    snapshot
                    if snapshot.get("terminal_status")
                    else (await self.workflow.continue_run(run["run_id"]))
                )
            response = await self.results.persist(result)
            await self.audit.consume_approval(run["run_id"])
            return response
        bound = await self.results.persist(snapshot)
        if bound.checkpoint_id != approval["checkpoint_id"]:
            raise InvalidCommandError("Recorded approval does not match the native interrupt")
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
        command = {
            "decision": approval["decision"],
            "reviewer_id": approval["reviewer_id"],
            "reason": approval.get("reason"),
        }
        with self.workflow.trace_run(
            run["run_id"],
            case_id=case_id,
            command="resume",
        ):
            result = await self.workflow.resume(run["run_id"], command)
        response = await self.results.persist(result)
        await self.audit.consume_approval(run["run_id"])
        return response

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
            workflow_state=public_state(run.get("state") or {}),
            selected_memory=selected_memory(memory),
            outcome=OutcomeView.model_validate(run["outcome"]) if run.get("outcome") else None,
        )

    @serialized_command
    async def continue_run(self, case_id: str) -> StartCaseResponse:
        """Continue a durable graph after a worker-level recovery breakpoint."""
        run = await self._require_run(case_id)
        snapshot = await self.workflow.snapshot(run["run_id"])
        if snapshot is None:
            raise InvalidCommandError("No durable graph checkpoint is available")
        if snapshot.get("__interrupt__"):
            return await self.results.persist(snapshot)
        if snapshot.get("approval_decision"):
            approval = await self.audit.get_approval(run["run_id"])
            if approval is None or approval["decision"] != snapshot["approval_decision"]:
                raise InvalidCommandError("Native checkpoint conflicts with recorded approval")
        with self.workflow.trace_run(
            run["run_id"],
            case_id=case_id,
            command="continue",
        ):
            result = (
                snapshot
                if snapshot.get("terminal_status")
                else (await self.workflow.continue_run(run["run_id"]))
            )
        response = await self.results.persist(result)
        if result.get("approval_decision") and await self.audit.get_pending_approval(run["run_id"]):
            await self.audit.consume_approval(run["run_id"])
        return response

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

    async def _require_run(self, case_id: str) -> dict[str, Any]:
        run = await self.audit.get_run_by_case(case_id)
        if not run:
            raise CaseNotFoundError(case_id)
        return run
