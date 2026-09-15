from uuid import UUID

from model_to_harness_shared import CheckoutApprovalDecision
from pydantic import BaseModel, ConfigDict, Field


class StartCaseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fixture_id: str = Field(min_length=1, max_length=120)
    request_id: UUID | None = None


class ApprovalCommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: CheckoutApprovalDecision
    reviewer_id: str = Field(min_length=1, max_length=120)
    approval_request_id: UUID
    reason: str = Field(min_length=1, max_length=500)
