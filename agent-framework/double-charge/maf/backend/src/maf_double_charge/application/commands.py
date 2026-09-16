from pydantic import BaseModel, Field, field_validator

from .models import ApprovalDecision


class OperatorCommand(BaseModel):
    operator_id: str = Field(min_length=1, max_length=128)

    @field_validator("operator_id", mode="before")
    @classmethod
    def trim_operator(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ScenarioInput(OperatorCommand):
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
    reason: str = Field(min_length=1, max_length=1000)

    @field_validator("reviewer_id", "reason", mode="before")
    @classmethod
    def trim_review(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class ResumeCommand(OperatorCommand):
    checkpoint_id: str
