from pydantic import BaseModel, ConfigDict, Field

from model_to_harness_shared.domain.checkout import (
    CheckoutApprovalDecision,
    CheckoutFailureCode,
    CheckoutRecoveryOutcome,
    CheckoutTerminalStatus,
    DiagnosticDisposition,
    RemediationStatus,
)


class CheckoutEvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ExpectedCheckoutOutcome(CheckoutEvaluationModel):
    diagnostic_disposition: DiagnosticDisposition
    approval_decision: CheckoutApprovalDecision
    remediation_status: RemediationStatus | None = None
    verification_result: bool | None = None
    terminal_status: CheckoutTerminalStatus
    failure_code: CheckoutFailureCode = CheckoutFailureCode.NONE

    def compare(self, outcome: CheckoutRecoveryOutcome) -> dict[str, tuple[str, str]]:
        mismatches: dict[str, tuple[str, str]] = {}
        for field_name in type(self).model_fields:
            expected = getattr(self, field_name)
            actual = getattr(outcome, field_name)
            if actual != expected:
                mismatches[field_name] = (str(expected), str(actual))
        return mismatches


class CheckoutEvaluationCase(CheckoutEvaluationModel):
    case_id: str = Field(min_length=1)
    fixture_id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    expected: ExpectedCheckoutOutcome
    tags: frozenset[str] = frozenset()


class CheckoutEvaluationResult(CheckoutEvaluationModel):
    case_id: str = Field(min_length=1)
    passed: bool
    mismatches: dict[str, tuple[str, str]] = Field(default_factory=dict)
