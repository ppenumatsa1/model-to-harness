from __future__ import annotations

from pydantic import BaseModel

from ..application import commands
from ..application.models import CaseSummary, RunStatus
from ..projections.workspace import WorkspaceView


class ScenarioInput(commands.ScenarioInput):
    def to_command(self) -> commands.ScenarioInput:
        return commands.ScenarioInput(**self.model_dump())


class StartResponse(BaseModel):
    case_id: str
    run_id: str
    status: RunStatus
    current_step: str
    approval_required: bool
    checkpoint_id: str | None = None


class ApprovalCommand(commands.ApprovalCommand):
    def to_command(self) -> commands.ApprovalCommand:
        return commands.ApprovalCommand(**self.model_dump())


class ResumeCommand(commands.ResumeCommand):
    def to_command(self) -> commands.ResumeCommand:
        return commands.ResumeCommand(**self.model_dump())


class CaseView(WorkspaceView):
    pass


class CasePage(BaseModel):
    items: list[CaseSummary]
    next_cursor: str | None = None
    has_more: bool
