from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SafeProjection(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)


class ValidationResult(SafeProjection):
    ok: bool
    code: str | None = None
    summary: str = ""


class ValidationResults(SafeProjection):
    billing: ValidationResult | None = None
    policy: ValidationResult | None = None


class PublicState(SafeProjection):
    normalized_complaint: str | None = None
    scenario_id: str | None = None
    current_step: str | None = None
    status: str | None = None
    duplicate_decision: str | None = None
    validation_results: ValidationResults = Field(default_factory=ValidationResults)
    approval_decision: str | None = None
    refund_attempts: int | None = None
    refund_status: str | None = None
    refund_id: str | None = None
    notification_status: str | None = None
    failure_code: str | None = None
    terminal_status: str | None = None
    safe_summaries: list[str] = Field(default_factory=list)


class SelectedMemory(SafeProjection):
    case_id: str | None = None
    duplicate_decision: str | None = None
    refund_status: str | None = None


def public_state(state: dict[str, Any]) -> dict[str, Any]:
    return PublicState.model_validate(state).model_dump(exclude_unset=True)


def selected_memory(memory: dict[str, Any]) -> dict[str, Any]:
    return SelectedMemory.model_validate(memory).model_dump(exclude_unset=True)
