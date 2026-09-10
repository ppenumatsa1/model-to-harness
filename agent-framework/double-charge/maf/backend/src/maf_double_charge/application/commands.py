from pydantic import BaseModel, Field

from .models import ApprovalDecision


class ScenarioInput(BaseModel):
    complaint: str = Field(min_length=3, max_length=4000)
    customer_id: str = Field(min_length=1, max_length=128)
    account_id: str | None = Field(default=None, max_length=128)
    scenario_id: str = Field(default="duplicate-confirmed", max_length=128)
    existing_case_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=256)


class ApprovalCommand(BaseModel):
    checkpoint_id: str
    decision: ApprovalDecision
    reviewer_id: str = Field(min_length=1, max_length=128)
    reason: str | None = Field(default=None, max_length=1000)


class ResumeCommand(BaseModel):
    checkpoint_id: str
