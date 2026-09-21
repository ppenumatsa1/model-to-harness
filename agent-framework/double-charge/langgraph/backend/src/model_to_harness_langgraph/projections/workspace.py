from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..application.records import NativeEvent, OutcomeView, RunStatus
from .state import PublicState, selected_memory

NodeStatus = Literal["pending", "running", "completed", "failed", "paused", "skipped"]


class CaseSummary(BaseModel):
    case_id: str
    run_id: str
    customer_id: str
    scenario_id: str | None = None
    status: RunStatus
    current_step: str
    terminal_status: str | None = None
    created_at: datetime
    updated_at: datetime


class CasePage(BaseModel):
    items: list[CaseSummary]
    has_more: bool
    next_cursor: str | None = None


class WorkspaceState(PublicState):
    case_id: str
    run_id: str
    customer_id: str
    complaint: str | None = Field(default=None, max_length=4000)
    scenario_id: str | None = None
    status: str
    current_step: str
    checkpoint_id: str | None = None
    approval_required: bool
    updated_at: datetime


class ApprovalView(BaseModel):
    checkpoint_id: str
    decision: Literal["approve", "deny"]
    reviewer_id: str
    reason: str | None = None
    decided_at: datetime | None = None
    consumed: bool = False


class GraphNode(BaseModel):
    id: str
    label: str


class GraphEdge(BaseModel):
    source: str
    target: str
    label: str | None = None


class GraphView(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    parallel_groups: list[list[str]] = Field(default_factory=list)


class WorkspaceView(BaseModel):
    state: WorkspaceState
    memory: dict[str, Any]
    outcome: OutcomeView | None = None
    approval: ApprovalView | None = None
    can_resume: bool
    can_record_approval: bool
    created_at: datetime
    node_statuses: dict[str, NodeStatus]
    graph: GraphView


def workspace_view(
    records: dict[str, Any], events: list[NativeEvent], graph: dict[str, Any]
) -> WorkspaceView:
    run = records["run"]
    stored = run.get("state") or {}
    state = WorkspaceState.model_validate({
        **stored,
        **{key: run[key] for key in (
            "case_id", "run_id", "customer_id", "status", "current_step",
            "checkpoint_id", "approval_required", "updated_at",
        )},
    })
    approval_record = records["approval"]
    approval = ApprovalView(
        **{key: approval_record[key] for key in (
            "checkpoint_id", "decision", "reviewer_id", "reason", "consumed"
        )},
        decided_at=approval_record.get("created_at"),
    ) if approval_record else None
    awaiting = state.status == "paused" and state.approval_required and bool(state.checkpoint_id)
    matching = approval is not None and approval.checkpoint_id == state.checkpoint_id
    metadata = GraphView.model_validate(graph)
    statuses: dict[str, NodeStatus] = {node.id: "pending" for node in metadata.nodes}
    for event in events:
        if event.node not in statuses:
            continue
        if event.event_type in {"node_started", "tool_call_started", "model_call_started"}:
            statuses[event.node] = "running"
        elif event.event_type in {
            "node_completed", "parallel_branch_completed", "parallel_branch_joined",
            "decision_summary", "human_approval_resolved", "tool_call_succeeded",
            "refund_verification",
        }:
            statuses[event.node] = "failed" if event.status == "failed" else "completed"
        elif event.event_type == "human_approval_requested":
            statuses[event.node] = "paused"
        elif event.event_type == "tool_call_failed":
            statuses[event.node] = "failed"
    if awaiting:
        statuses["request_approval"] = "paused"
    return WorkspaceView(
        state=state,
        memory=selected_memory(records["memory"]),
        outcome=OutcomeView.model_validate(run["outcome"]) if run.get("outcome") else None,
        approval=approval,
        can_resume=bool(awaiting and matching and not approval.consumed),
        can_record_approval=bool(awaiting and approval is None),
        created_at=run["created_at"],
        node_statuses=statuses,
        graph=metadata,
    )
