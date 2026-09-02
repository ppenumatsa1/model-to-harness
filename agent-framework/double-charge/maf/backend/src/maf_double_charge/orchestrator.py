from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from agent_framework import Workflow, WorkflowEvent
from model_to_harness_shared import DuplicateEvidence, WorkflowOutcome, get_fixture

from .checkpoints import checkpoint_storage_for
from .config import Settings
from .model_client import ModelClient
from .models import (
    ApprovalCommand,
    ApprovalResponse,
    DurableEvent,
    RunStatus,
    ScenarioInput,
    StartResponse,
    WorkflowState,
)
from .outcomes import map_outcome
from .refunds import DurableRefundService
from .repository import Repository
from .shared_actions import ActionRegistry, RootSharedActions
from .workflow import WorkflowDependencies, build_workflow

logger = logging.getLogger(__name__)


@dataclass
class RunRuntime:
    workflow: Workflow
    checkpoint_storage: Any
    actions: RootSharedActions


class DoubleChargeOrchestrator:
    def __init__(
        self,
        repository: Repository,
        model: ModelClient,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.model = model
        self.settings = settings
        self.actions = ActionRegistry()
        self.refunds = DurableRefundService(repository)
        self._runtimes: dict[str, RunRuntime] = {}

    async def _emit(
        self,
        state: WorkflowState,
        event_type: str,
        summary: str,
        **kwargs: Any,
    ) -> DurableEvent:
        return await self.repository.append_event(
            DurableEvent(
                case_id=state.case_id,
                run_id=state.run_id,
                event_type=event_type,
                summary=summary,
                node=kwargs.get("node"),
                transition=kwargs.get("transition"),
                checkpoint_id=kwargs.get("checkpoint_id"),
                retry_attempt=kwargs.get("retry_attempt"),
                idempotency_key=kwargs.get("idempotency_key"),
                payload=kwargs.get("payload", {}),
            )
        )

    def _build_runtime(self, state: WorkflowState) -> RunRuntime:
        actions = self.actions.get_or_restore(state.run_id, state.scenario_id)
        if state.duplicate_evidence:
            actions.last_evidence = DuplicateEvidence.model_validate(state.duplicate_evidence)
        if state.approval_required and actions.last_evidence is not None:
            actions.request_approval(state.duplicate_evidence, state.case_id)
        dependencies = WorkflowDependencies(
            repository=self.repository,
            model=self.model,
            actions=actions,
            refunds=self.refunds,
            max_tool_attempts=self.settings.max_tool_attempts,
        )
        runtime = RunRuntime(
            workflow=build_workflow(dependencies, state.run_id),
            checkpoint_storage=checkpoint_storage_for(self.repository, state.run_id),
            actions=actions,
        )
        self._runtimes[state.run_id] = runtime
        return runtime

    async def _runtime(self, state: WorkflowState) -> RunRuntime:
        return self._runtimes.get(state.run_id) or self._build_runtime(state)

    async def _fresh_resume_runtime(self, state: WorkflowState) -> RunRuntime:
        existing = await self._runtime(state)
        dependencies = WorkflowDependencies(
            repository=self.repository,
            model=self.model,
            actions=existing.actions,
            refunds=self.refunds,
            max_tool_attempts=self.settings.max_tool_attempts,
        )
        runtime = RunRuntime(
            workflow=build_workflow(dependencies, state.run_id),
            checkpoint_storage=existing.checkpoint_storage,
            actions=existing.actions,
        )
        self._runtimes[state.run_id] = runtime
        return runtime

    async def start(self, command: ScenarioInput) -> StartResponse:
        fixture = get_fixture(command.scenario_id)
        if command.account_id and command.account_id != fixture.scenario_input.account_id:
            raise ValueError("account_id does not match the selected deterministic fixture")
        case_id = command.existing_case_id or f"case-{uuid4().hex[:12]}"
        run_id = f"run-{uuid4().hex[:12]}"
        idempotency_key = (
            command.idempotency_key
            or fixture.scenario_input.idempotency_key
            or f"refund-{case_id}"
        )
        state = WorkflowState(
            case_id=case_id,
            run_id=run_id,
            complaint=command.complaint,
            customer_id=command.customer_id,
            scenario_id=command.scenario_id,
            idempotency_key=idempotency_key,
        )
        await self.repository.create_run(state)
        await self.repository.save_memory(
            case_id,
            {"customer_id": command.customer_id, "fixture_id": command.scenario_id},
        )
        await self._emit(
            state,
            "run.started",
            "Double-charge workflow started.",
            node="normalize_complaint",
        )
        runtime = self._build_runtime(state)
        await self._execute(runtime, state=state)
        current = await self._require_state(run_id)
        return StartResponse(
            case_id=current.case_id,
            run_id=current.run_id,
            status=current.status,
            current_step=current.current_step,
            approval_required=current.approval_required,
            checkpoint_id=current.checkpoint_id,
        )

    async def record_approval(self, run_id: str, command: ApprovalCommand) -> WorkflowState:
        state = await self._require_state(run_id)
        if state.status != RunStatus.PAUSED or not state.approval_required:
            raise ValueError("run is not waiting for approval")
        if state.checkpoint_id != command.checkpoint_id:
            raise ValueError("checkpoint_id does not match the current durable checkpoint")
        response = ApprovalResponse(
            decision=command.decision,
            reviewer_id=command.reviewer_id,
            reason=command.reason,
        )
        await self.repository.save_approval(run_id, command.checkpoint_id, response)
        await self._emit(
            state,
            "approval.recorded",
            "Approval command was durably recorded; resume remains an explicit operation.",
            node="approval_checkpoint",
            checkpoint_id=command.checkpoint_id,
            payload={"decision": command.decision.value, "reviewer_id": command.reviewer_id},
        )
        return state

    async def resume(self, run_id: str, checkpoint_id: str) -> WorkflowState:
        state = await self._require_state(run_id)
        if state.status != RunStatus.PAUSED:
            raise ValueError("run is not paused")
        if state.checkpoint_id != checkpoint_id:
            raise ValueError("checkpoint_id does not match the paused run")
        approval = await self.repository.get_approval(run_id)
        if approval is None:
            raise ValueError("record an approval decision before resuming")
        runtime = await self._fresh_resume_runtime(state)
        await self._emit(
            state,
            "workflow.resumed",
            "Workflow resumed from the durable MAF checkpoint.",
            node="approval_checkpoint",
            checkpoint_id=checkpoint_id,
        )
        await self._execute(
            runtime,
            checkpoint_id=checkpoint_id,
            responses={f"approval::{run_id}": approval},
        )
        return await self._require_state(run_id)

    async def _execute(
        self,
        runtime: RunRuntime,
        *,
        state: WorkflowState | None = None,
        checkpoint_id: str | None = None,
        responses: dict[str, ApprovalResponse] | None = None,
    ) -> None:
        result = await runtime.workflow.run(
            message=state,
            checkpoint_id=checkpoint_id,
            responses=responses,
            checkpoint_storage=runtime.checkpoint_storage,
            include_status_events=True,
        )
        current = state or await self._state_from_runtime(runtime)
        if current is None:
            raise RuntimeError("workflow completed without persisted state")
        await self._persist_native_events(current, list(result), result.status_timeline())
        latest = await runtime.checkpoint_storage.get_latest(
            workflow_name=runtime.workflow.name
        )
        current = await self._require_state(current.run_id)
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
                await self._emit(
                    current,
                    "checkpoint.created",
                    "MAF saved a durable checkpoint at the approval boundary.",
                    node="approval_checkpoint",
                    checkpoint_id=latest.checkpoint_id,
                    payload={"workflow_name": runtime.workflow.name},
                )
        current = await self._require_state(current.run_id)
        if current.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.MANUAL_REVIEW}:
            events = await self.repository.list_events(current.run_id)
            await self.repository.save_outcome(map_outcome(current, events))

    async def _state_from_runtime(self, runtime: RunRuntime) -> WorkflowState | None:
        for run_id, candidate in self._runtimes.items():
            if candidate is runtime:
                return await self.repository.get_state(run_id)
        return None

    async def _persist_native_events(
        self,
        state: WorkflowState,
        events: list[WorkflowEvent[Any]],
        status_events: list[WorkflowEvent[Any]],
    ) -> None:
        seen: set[tuple[object, ...]] = set()
        for event in [*events, *status_events]:
            event_data = vars(event)
            event_type = str(event_data["type"])
            identity = (
                event_type,
                event_data.get("executor_id"),
                event_data.get("_request_id"),
                event_data.get("iteration"),
                str(event_data.get("state")),
            )
            if identity in seen:
                continue
            seen.add(identity)
            await self._emit(
                state,
                f"maf.native.{event_type}",
                f"MAF emitted {event_type}.",
                node=event_data.get("executor_id") or event_data.get("_source_executor_id"),
                payload={
                    "iteration": event_data.get("iteration"),
                    "state": (
                        str(event_data["state"]) if event_data.get("state") is not None else None
                    ),
                },
            )

    async def _require_state(self, run_id: str) -> WorkflowState:
        state = await self.repository.get_state(run_id)
        if state is None:
            raise KeyError(f"unknown run: {run_id}")
        return state

    async def get_state(self, run_id: str) -> WorkflowState:
        return await self._require_state(run_id)

    async def get_outcome(self, run_id: str) -> WorkflowOutcome | None:
        return await self.repository.get_outcome(run_id)
