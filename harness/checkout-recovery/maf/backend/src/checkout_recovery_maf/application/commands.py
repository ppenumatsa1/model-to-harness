from dataclasses import dataclass

from model_to_harness_shared import CheckoutApprovalDecision


@dataclass(frozen=True)
class StartCaseCommand:
    fixture_id: str
    request_id: str | None = None


@dataclass(frozen=True)
class RecordApprovalCommand:
    case_id: str
    decision: CheckoutApprovalDecision
    reviewer_id: str
    approval_request_id: str
    reason: str


@dataclass(frozen=True)
class ResumeCaseCommand:
    case_id: str


type CaseCommand = StartCaseCommand | RecordApprovalCommand | ResumeCaseCommand
