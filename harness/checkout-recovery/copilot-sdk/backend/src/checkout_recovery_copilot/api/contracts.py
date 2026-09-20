from uuid import UUID

from model_to_harness_shared import CheckoutApprovalDecision
from pydantic import BaseModel, ConfigDict, Field

from checkout_recovery_copilot.application.commands import RecordApprovalCommand, StartCaseCommand


class StartCaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fixture_id: str = Field(min_length=1, max_length=120)
    request_id: UUID | None = None

    def to_command(self) -> StartCaseCommand:
        return StartCaseCommand(self.fixture_id, str(self.request_id) if self.request_id else None)


class ApprovalCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: CheckoutApprovalDecision
    reviewer_id: str = Field(min_length=1, max_length=120)
    approval_request_id: UUID
    reason: str = Field(min_length=1, max_length=500)

    def to_command(self, case_id: str) -> RecordApprovalCommand:
        return RecordApprovalCommand(
            case_id,
            self.decision,
            self.reviewer_id,
            str(self.approval_request_id),
            self.reason,
        )
