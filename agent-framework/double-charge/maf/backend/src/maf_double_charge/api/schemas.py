from __future__ import annotations

from typing import Any

from model_to_harness_shared import WorkflowOutcome
from pydantic import BaseModel, Field

from ..application import commands
from ..application.models import ApprovalDecision, NodeStatus, RunStatus, WorkflowState


class ScenarioInput(BaseModel):
    complaint: str = Field(min_length=3, max_length=4000)
    customer_id: str = Field(min_length=1, max_length=128)
    account_id: str | None = Field(default=None, max_length=128)
    scenario_id: str = Field(default="duplicate-confirmed", max_length=128)
    existing_case_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=256)

    def to_command(self) -> commands.ScenarioInput:
        return commands.ScenarioInput(**self.model_dump())


class StartResponse(BaseModel):
    case_id: str
    run_id: str
    status: RunStatus
    current_step: str
    approval_required: bool
    checkpoint_id: str | None = None


class ApprovalCommand(BaseModel):
    checkpoint_id: str
    decision: ApprovalDecision
    reviewer_id: str = Field(min_length=1, max_length=128)
    reason: str | None = Field(default=None, max_length=1000)

    def to_command(self) -> commands.ApprovalCommand:
        return commands.ApprovalCommand(**self.model_dump())


class ResumeCommand(BaseModel):
    checkpoint_id: str

    def to_command(self) -> commands.ResumeCommand:
        return commands.ResumeCommand(**self.model_dump())


class CaseView(BaseModel):
    state: WorkflowState
    memory: dict[str, Any] = Field(default_factory=dict)
    outcome: WorkflowOutcome | None = None
    node_statuses: dict[str, NodeStatus] = Field(default_factory=dict)
