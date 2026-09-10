from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EventUsage(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class EventData(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    attempt: int | None = None
    branch: str | None = None
    checkpoint_id: str | None = None
    decision: str | None = None
    eligible: bool | None = None
    failure_code: str | None = None
    latency_ms: int | None = None
    model: str | None = None
    refund_id: str | None = None
    retry_in_ms: int | None = None
    route: str | None = None
    tool: str | None = None
    tool_call_id: str | None = None
    usage: EventUsage | None = None
    verified_count: int | None = None


class RunStatus(StrEnum):
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    MANUAL_REVIEW = "manual_review"


class StartCaseRequest(BaseModel):
    complaint: str = Field(min_length=5, max_length=4000)
    customer_id: str = Field(min_length=1, max_length=128)
    scenario_id: str = Field(default="duplicate-confirmed", max_length=128)
    existing_case_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=200)


class StartCaseResponse(BaseModel):
    case_id: str
    run_id: str
    status: RunStatus
    current_step: str
    approval_required: bool
    checkpoint_id: str | None = None


class ApprovalRequest(BaseModel):
    checkpoint_id: str
    decision: Literal["approve", "deny"]
    reviewer_id: str = Field(min_length=1, max_length=128)
    reason: str | None = Field(default=None, max_length=1000)


class ResumeResponse(StartCaseResponse):
    outcome: "OutcomeView | None" = None


class NativeEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sequence: int
    event_id: str
    case_id: str
    run_id: str
    event_type: str
    timestamp: datetime
    node: str | None = None
    status: str | None = None
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("data", mode="before")
    @classmethod
    def allowlisted_data(cls, value: Any) -> dict[str, Any]:
        return EventData.model_validate(value).model_dump(exclude_unset=True)


class OutcomeView(BaseModel):
    case_id: str
    run_id: str
    duplicate_decision: str
    policy_decision: str
    approval_decision: str
    refund_status: str
    refund_id: str | None = None
    notification_status: str
    terminal_status: str
    failure_code: str | None = None
    event_summary: list[str] = Field(default_factory=list)


class CaseView(BaseModel):
    case_id: str
    run_id: str
    status: RunStatus
    current_step: str
    checkpoint_id: str | None = None
    approval_required: bool = False
    workflow_state: dict[str, Any] = Field(default_factory=dict)
    selected_memory: dict[str, Any] = Field(default_factory=dict)
    outcome: OutcomeView | None = None
