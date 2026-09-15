from pydantic import BaseModel, ConfigDict, Field

from model_to_harness_shared.domain import (
    ApprovalDecision,
    DuplicateDecision,
    FailureCode,
    NotificationStatus,
    PolicyDecision,
    RefundStatus,
    TerminalStatus,
    WorkflowOutcome,
)


class EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExpectedOutcome(EvaluationModel):
    duplicate_decision: DuplicateDecision
    policy_decision: PolicyDecision
    approval_decision: ApprovalDecision
    refund_status: RefundStatus
    notification_status: NotificationStatus
    terminal_status: TerminalStatus
    failure_code: FailureCode = FailureCode.NONE

    def compare(self, outcome: WorkflowOutcome) -> dict[str, tuple[str, str]]:
        mismatches: dict[str, tuple[str, str]] = {}
        for field_name in type(self).model_fields:
            expected = getattr(self, field_name)
            actual = getattr(outcome, field_name)
            if actual != expected:
                mismatches[field_name] = (str(expected), str(actual))
        return mismatches


class EvaluationCase(EvaluationModel):
    case_id: str = Field(min_length=1)
    fixture_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    expected: ExpectedOutcome
    tags: frozenset[str] = frozenset()


class EvaluationResult(EvaluationModel):
    case_id: str = Field(min_length=1)
    passed: bool
    mismatches: dict[str, tuple[str, str]] = Field(default_factory=dict)
