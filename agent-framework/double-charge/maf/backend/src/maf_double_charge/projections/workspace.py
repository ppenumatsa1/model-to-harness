from __future__ import annotations

from datetime import datetime

from model_to_harness_shared import WorkflowOutcome
from pydantic import BaseModel, Field

from ..application.models import (
    ApprovalDecision,
    BranchResult,
    DurableEvent,
    NodeStatus,
    RunStatus,
    WorkflowState,
)
from ..application.ports import Repository
from .agui import _DETAIL_FIELDS, _TOOL_NAMES
from .workflow_graph import WORKFLOW_GRAPH

Detail = str | bool | int | float | list[str] | None


def selected_details(payload: dict, fields: set[str] | frozenset[str]) -> dict[str, Detail]:
    result: dict[str, Detail] = {}
    for key in fields:
        value = payload.get(key)
        if key not in payload:
            continue
        if value is None or isinstance(value, (str, bool, int, float)):
            result[key] = value
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            result[key] = value
    return result


class BranchView(BaseModel):
    branch: str
    ok: bool
    summary: str
    failure_code: str | None = None
    attempts: int
    evidence: dict[str, Detail] = Field(default_factory=dict)


class StateView(BaseModel):
    case_id: str
    run_id: str
    complaint: str
    customer_id: str
    scenario_id: str
    status: RunStatus
    current_step: str
    normalized_complaint: str | None = None
    duplicate_found: bool | None = None
    duplicate_summary: str | None = None
    billing_validation: BranchView | None = None
    policy_validation: BranchView | None = None
    approval_required: bool
    approval_decision: ApprovalDecision | None = None
    checkpoint_id: str | None = None
    refund_status: str
    refund_id: str | None = None
    notification_status: str
    notification_summary: str | None = None
    terminal_status: str | None = None
    failure_code: str | None = None
    updated_at: datetime


class ApprovalView(BaseModel):
    decision: ApprovalDecision
    reviewer_id: str
    reason: str | None = None
    decided_at: datetime
    checkpoint_id: str | None = None


class SafeEvent(BaseModel):
    sequence: int
    event_id: str
    case_id: str
    run_id: str
    event_type: str
    node: str | None = None
    transition: str | None = None
    checkpoint_id: str | None = None
    retry_attempt: int | None = None
    summary: str
    payload: dict[str, Detail]
    created_at: datetime


class WorkspaceView(BaseModel):
    state: StateView
    memory: dict[str, str]
    outcome: WorkflowOutcome | None = None
    approval: ApprovalView | None = None
    can_resume: bool
    can_record_approval: bool
    created_at: datetime
    node_statuses: dict[str, NodeStatus] = Field(default_factory=dict)
    graph: dict = Field(default_factory=lambda: WORKFLOW_GRAPH)


def safe_state(state: WorkflowState) -> StateView:
    values = state.model_dump(include=set(StateView.model_fields))
    for key in ("billing_validation", "policy_validation"):
        branch: BranchResult | None = getattr(state, key)
        if branch:
            values[key]["evidence"] = selected_details(
                branch.evidence, {"checked_charge_ids", "policy_code", "decision"}
            )
    return StateView.model_validate(values)


def safe_event(event: DurableEvent) -> SafeEvent:
    fields = set(_DETAIL_FIELDS.get(event.event_type, frozenset())) | {
        "audit_version", "actor_id", "actor_type", "actor_source",
    }
    if event.event_type == "decision.summary":
        fields.add("matching_charge_ids")
    if event.event_type in {"run.completed", "run.failed"}:
        fields |= {"terminal_status", "refund_status", "notification_status", "failure_code"}
    if event.event_type.startswith("tool."):
        fields |= {"tool", "ok", "uncertain", "transient", "refund_id", "recovered_existing"}
    if event.event_type.startswith("model."):
        fields |= {"model", "latency_ms"}
    if event.event_type in {"approval.recorded", "approval.resolved"}:
        fields.add("reason")
    if event.event_type == "parallel.branch.completed":
        fields |= {"checked_charge_ids", "policy_code", "decision"}
    values = event.model_dump(include=set(SafeEvent.model_fields))
    values["payload"] = selected_details(event.payload, fields)
    tool = values["payload"].get("tool")
    if "tool" in values["payload"] and (not isinstance(tool, str) or tool not in _TOOL_NAMES):
        del values["payload"]["tool"]
    return SafeEvent.model_validate(values)


async def workspace_view(repository: Repository, state: WorkflowState) -> WorkspaceView:
    approval = await repository.get_approval(state.run_id)
    memory = await repository.get_memory(state.case_id)
    awaiting = (
        state.status == RunStatus.PAUSED and state.approval_required and bool(state.checkpoint_id)
    )
    return WorkspaceView(
        state=safe_state(state),
        memory={
            key: value for key, value in memory.items()
            if key in {"customer_id", "fixture_id", "last_normalized_issue"}
            and isinstance(value, str)
        },
        outcome=await repository.get_outcome(state.run_id),
        approval=ApprovalView(
            **approval.model_dump(), checkpoint_id=state.checkpoint_id
        ) if approval else None,
        can_resume=awaiting and approval is not None,
        can_record_approval=awaiting and approval is None,
        created_at=await repository.get_run_created_at(state.run_id),
    )
