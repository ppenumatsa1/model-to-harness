from __future__ import annotations

from collections.abc import Callable

from agent_framework import CheckpointStorage
from model_to_harness_shared import DuplicateEvidence

from ..application.audit import Audit
from ..application.models import ApprovalResponse, RunStatus, WorkflowState
from ..application.outcomes import map_outcome
from ..application.ports import Actions, ModelClient, Repository
from ..application.refunds import DurableRefundService
from ..infrastructure.telemetry import telemetry_context
from .dependencies import WorkflowDependencies
from .native_events import persist_native_events
from .workflows.double_charge import build_workflow

CheckpointStorageFactory = Callable[[Repository, str], CheckpointStorage]
ActionsFactory = Callable[[str], Actions]


class MafWorkflowRunner:
    def __init__(
        self,
        repository: Repository,
        model: ModelClient,
        *,
        checkpoint_storage_factory: CheckpointStorageFactory,
        actions_factory: ActionsFactory,
        max_tool_attempts: int,
    ) -> None:
        self.repository = repository
        self.model = model
        self.checkpoint_storage_factory = checkpoint_storage_factory
        self.actions_factory = actions_factory
        self.max_tool_attempts = max_tool_attempts
        self.audit = Audit(repository)

    async def start(self, state: WorkflowState) -> None:
        await self._execute(state)

    async def resume(
        self, state: WorkflowState, checkpoint_id: str, approval: ApprovalResponse
    ) -> None:
        await self._execute(state, checkpoint_id=checkpoint_id, approval=approval)

    async def _execute(
        self,
        state: WorkflowState,
        *,
        checkpoint_id: str | None = None,
        approval: ApprovalResponse | None = None,
    ) -> None:
        actions = self.actions_factory(state.scenario_id)
        if state.duplicate_evidence:
            actions.last_evidence = DuplicateEvidence.model_validate(state.duplicate_evidence)
        if state.approval_required and actions.last_evidence is not None:
            actions.request_approval(state.duplicate_evidence, state.case_id)
        workflow = build_workflow(
            WorkflowDependencies(
                repository=self.repository,
                model=self.model,
                actions=actions,
                refunds=DurableRefundService(self.repository),
                max_tool_attempts=self.max_tool_attempts,
            ),
            state.run_id,
        )
        storage = self.checkpoint_storage_factory(self.repository, state.run_id)
        with telemetry_context(case_id=state.case_id, run_id=state.run_id):
            result = await workflow.run(
                message=state if checkpoint_id is None else None,
                checkpoint_id=checkpoint_id,
                responses={f"approval::{state.run_id}": approval} if approval is not None else None,
                checkpoint_storage=storage,
                include_status_events=True,
            )
        await persist_native_events(self.audit, state, list(result), result.status_timeline())
        current = await self._require_state(state.run_id)
        latest = await storage.get_latest(workflow_name=workflow.name)
        if latest and current.status == RunStatus.PAUSED:
            if current.checkpoint_id != latest.checkpoint_id:
                current = current.model_copy(update={"checkpoint_id": latest.checkpoint_id})
                await self.repository.save_state(current)
            events = await self.repository.list_events(current.run_id)
            if not any(
                event.event_type == "checkpoint.created"
                and event.checkpoint_id == latest.checkpoint_id
                for event in events
            ):
                await self.audit.emit(
                    current,
                    "checkpoint.created",
                    "MAF saved a durable checkpoint at the approval boundary.",
                    node="approval_checkpoint",
                    checkpoint_id=latest.checkpoint_id,
                    payload={"workflow_name": workflow.name},
                )
        if current.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.MANUAL_REVIEW}:
            events = await self.repository.list_events(current.run_id)
            await self.repository.save_outcome(map_outcome(current, events))

    async def _require_state(self, run_id: str) -> WorkflowState:
        state = await self.repository.get_state(run_id)
        if state is None:
            raise RuntimeError("workflow completed without persisted state")
        return state
