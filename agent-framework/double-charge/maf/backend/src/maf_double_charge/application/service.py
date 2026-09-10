from __future__ import annotations

from uuid import uuid4

from model_to_harness_shared import WorkflowOutcome, get_fixture

from .audit import Audit
from .commands import ApprovalCommand, ScenarioInput
from .models import ApprovalResponse, RunStatus, StartResult, WorkflowState
from .ports import Repository, WorkflowRunner


class DoubleChargeService:
    def __init__(self, repository: Repository, runner: WorkflowRunner) -> None:
        self.repository = repository
        self.runner = runner
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
        await self.repository.create_run(state)
        await self.repository.save_memory(
            case_id, {"customer_id": command.customer_id, "fixture_id": command.scenario_id}
        )
        await self.audit.emit(
            state, "run.started", "Double-charge workflow started.", node="normalize_complaint"
        )
        await self.runner.start(state)
        current = await self.get_state(state.run_id)
        return StartResult(
            case_id=current.case_id,
            run_id=current.run_id,
            status=current.status,
            current_step=current.current_step,
            approval_required=current.approval_required,
            checkpoint_id=current.checkpoint_id,
        )

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
            payload={"decision": command.decision.value, "reviewer_id": command.reviewer_id},
        )
        return state

    async def resume(self, run_id: str, checkpoint_id: str) -> WorkflowState:
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
            "Workflow resumed from the durable MAF checkpoint.",
            node="approval_checkpoint",
            checkpoint_id=checkpoint_id,
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
