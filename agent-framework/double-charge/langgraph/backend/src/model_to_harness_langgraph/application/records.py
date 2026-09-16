from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

HumanIdentifier = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)
]
CheckpointIdentifier = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]
ApprovalReason = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1000)
]
ShortFact = Annotated[str, StringConstraints(max_length=256)]


class EventUsage(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class EventData(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    audit_version: Literal[2] | None = None
    actor_type: Literal["human", "system"] | None = None
    actor_id: HumanIdentifier | None = None
    actor_source: Literal["operator_supplied", "system"] | None = None
    reviewer_id: HumanIdentifier | None = None
    reason: Annotated[str, StringConstraints(max_length=1000)] | None = None
    attempt: int | None = Field(default=None, ge=0)
    branch: ShortFact | None = None
    checkpoint_id: CheckpointIdentifier | None = None
    decision: ShortFact | None = None
    eligible: bool | None = None
    failure_code: ShortFact | None = None
    latency_ms: int | None = Field(default=None, ge=0)
    model: ShortFact | None = None
    refund_id: ShortFact | None = None
    retry_in_ms: int | None = Field(default=None, ge=0)
    route: ShortFact | None = None
    tool: ShortFact | None = None
    tool_call_id: ShortFact | None = None
    usage: EventUsage | None = None
    verified_count: int | None = Field(default=None, ge=0)
    verified: bool | None = None
    ok: bool | None = None
    uncertain: bool | None = None
    transient: bool | None = None
    recovered_existing: bool | None = None
    simulated: bool | None = None
    matching_charge_ids: list[ShortFact] | None = Field(default=None, max_length=100)
    checked_charge_ids: list[ShortFact] | None = Field(default=None, max_length=100)
    policy_code: ShortFact | None = None
    terminal_status: ShortFact | None = None
    refund_status: ShortFact | None = None
    notification_status: ShortFact | None = None


class RunStatus(StrEnum):
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    MANUAL_REVIEW = "manual_review"


class StartCaseRequest(BaseModel):
    complaint: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=5, max_length=4000)
    ]
    operator_id: HumanIdentifier
    customer_id: HumanIdentifier
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
    checkpoint_id: CheckpointIdentifier
    decision: Literal["approve", "deny"]
    reviewer_id: HumanIdentifier
    reason: ApprovalReason


class ResumeRequest(BaseModel):
    checkpoint_id: CheckpointIdentifier
    operator_id: HumanIdentifier


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
