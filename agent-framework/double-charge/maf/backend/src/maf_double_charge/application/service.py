from __future__ import annotations

import json
from hashlib import sha256
from typing import Any
from uuid import uuid4

from model_to_harness_shared import WorkflowOutcome, get_fixture

from ..projections.selected_run import selected_run_facts, selected_run_view
from ..projections.workspace import WorkspaceView, workspace_view
from .audit import Audit
from .commands import ApprovalCommand, ResumeCommand, ScenarioInput
from .errors import StartExecutionError
from .history import CaseCursor, CasePage
from .models import ApprovalResponse, DurableEvent, RunStatus, StartResult, WorkflowState
from .ports import ModelClient, ModelResult, Repository, WorkflowRunner


class DoubleChargeService:
    def __init__(
        self, repository: Repository, runner: WorkflowRunner, model: ModelClient
    ) -> None:
        self.repository = repository
        self.runner = runner
        self.model = model
        self.audit = Audit(repository)

    async def start(self, command: ScenarioInput) -> StartResult:
        fixture = get_fixture(command.scenario_id)
        if command.account_id and command.account_id != fixture.scenario_input.account_id:
            raise ValueError("account_id does not match the selected deterministic fixture")
        case_id = command.existing_case_id or f"case-{uuid4().hex[:12]}"
        state = WorkflowState(
            case_id=case_id,
            run_id=f"run-{uuid4().hex[:12]}",
            complaint=command.complaint,
            customer_id=command.customer_id,
            scenario_id=command.scenario_id,
            idempotency_key=(
                command.idempotency_key
                or fixture.scenario_input.idempotency_key
                or f"refund-{case_id}"
            ),
        )
        request_id = str(command.request_id) if command.request_id is not None else None
        if request_id is not None:
            fingerprint = sha256(
                json.dumps(
                    command.model_dump(mode="json", exclude={"request_id"}),
                    sort_keys=True, separators=(",", ":"),
                ).encode()
            ).hexdigest()
            recorded = await self.repository.claim_start(request_id, fingerprint, state)
            if recorded is not None:
                return recorded
        else:
            await self.repository.create_run(state)
        try:
            await self.repository.save_memory(
                case_id, {"customer_id": command.customer_id, "fixture_id": command.scenario_id}
            )
            await self.audit.emit(
                state, "run.started", "Double-charge workflow started.", node="normalize_complaint",
                actor_id=command.operator_id,
            )
            await self.runner.start(state)
            current = await self.get_state(state.run_id)
            result = StartResult(
                case_id=current.case_id,
                run_id=current.run_id,
                status=current.status,
                current_step=current.current_step,
                approval_required=current.approval_required,
                checkpoint_id=current.checkpoint_id,
            )
            if request_id is not None:
                await self.repository.complete_start(request_id, result)
        except (KeyError, ValueError) as error:
            if request_id is None:
                raise
            # Transport validation errors must not discard a committed Start identity.
            raise StartExecutionError(case_id, state.run_id) from error
        return result

    async def record_approval(self, run_id: str, command: ApprovalCommand) -> WorkflowState:
        state = await self.get_state(run_id)
        if state.status != RunStatus.PAUSED or not state.approval_required:
            raise ValueError("run is not waiting for approval")
        if state.checkpoint_id != command.checkpoint_id:
            raise ValueError("checkpoint_id does not match the current durable checkpoint")
        response = ApprovalResponse(
            decision=command.decision, reviewer_id=command.reviewer_id, reason=command.reason
        )
        existing = await self.repository.get_approval(run_id)
        if existing is not None:
            if not existing.same_intent(response):
                raise ValueError("approval already resolved with another decision")
            return state
        await self.repository.save_approval(run_id, command.checkpoint_id, response)
        await self.audit.emit(
            state,
            "approval.recorded",
            "Approval command was durably recorded; resume remains an explicit operation.",
            node="approval_checkpoint",
            checkpoint_id=command.checkpoint_id,
            payload={
                "decision": command.decision.value,
                "reviewer_id": command.reviewer_id,
                "reason": command.reason,
            },
            actor_id=command.reviewer_id,
        )
        return state

    async def resume(
        self, run_id: str, checkpoint_id: str, *, operator_id: str
    ) -> WorkflowState:
        command = ResumeCommand(checkpoint_id=checkpoint_id, operator_id=operator_id)
        state = await self.get_state(run_id)
        if state.status != RunStatus.PAUSED:
            raise ValueError("run is not paused")
        if state.checkpoint_id != checkpoint_id:
            raise ValueError("checkpoint_id does not match the paused run")
        approval = await self.repository.get_approval(run_id)
        if approval is None:
            raise ValueError("record an approval decision before resuming")
        await self.audit.emit(
            state,
            "workflow.resumed",
            "Resume command recorded; workflow continuation has been requested.",
            node="approval_checkpoint",
            checkpoint_id=checkpoint_id,
            actor_id=command.operator_id,
        )
        await self.runner.resume(state, checkpoint_id, approval)
        return await self.get_state(run_id)

    async def get_state(self, run_id: str) -> WorkflowState:
        state = await self.repository.get_state(run_id)
        if state is None:
            raise KeyError(f"unknown run: {run_id}")
        return state

    async def get_outcome(self, run_id: str) -> WorkflowOutcome | None:
        return await self.repository.get_outcome(run_id)

    async def list_cases(self, limit: int = 10, cursor: str | None = None) -> CasePage:
        before = CaseCursor.decode(cursor) if cursor is not None else None
        records = await self.repository.list_cases(
            limit + 1, (before.created_at, before.run_id) if before else None
        )
        items = records[:limit]
        has_more = len(records) > limit
        next_cursor = (
            CaseCursor(created_at=items[-1].created_at, run_id=items[-1].run_id).encode()
            if has_more else None
        )
        return CasePage(items=items, next_cursor=next_cursor, has_more=has_more)

    async def get_case_state(self, case_id: str) -> WorkflowState:
        state = await self.repository.get_state_by_case(case_id)
        if state is None:
            raise KeyError(f"unknown case: {case_id}")
        return state

    async def get_case_workspace(self, case_id: str) -> WorkspaceView:
        return await self._workspace(await self.get_case_state(case_id))

    async def get_workspace(self, run_id: str) -> WorkspaceView:
        return await self._workspace(await self.get_state(run_id))

    async def _workspace(self, state: WorkflowState) -> WorkspaceView:
        approval = await self.repository.get_approval(state.run_id)
        memory = await self.repository.get_memory(state.case_id)
        outcome = await self.repository.get_outcome(state.run_id)
        created_at = await self.repository.get_run_created_at(state.run_id)
        return workspace_view(
            state, approval=approval, memory=memory, outcome=outcome, created_at=created_at
        )

    async def list_events(
        self, run_id: str, after: int = 0, limit: int | None = None
    ) -> list[DurableEvent]:
        await self.get_state(run_id)
        return await self.repository.list_events(run_id, after=after, limit=limit)

    async def get_selected_run(self, run_id: str) -> dict[str, Any]:
        state = await self.get_state(run_id)
        return selected_run_view(state, await self.repository.list_events(run_id))

    async def resolve_selected_run(self, selection_id: str) -> WorkflowState:
        try:
            return await self.get_state(selection_id)
        except KeyError:
            selected_case = await self.get_case_state(selection_id)
            return await self.get_state(selected_case.run_id)

    async def explain_selected_run(self, state: WorkflowState, question: str) -> ModelResult:
        _, facts = selected_run_facts(state, await self.repository.list_events(state.run_id))
        return await self.model.explain_run(question, facts)
