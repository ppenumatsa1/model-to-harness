from typing import Any

from ..application.records import ApprovalRequest as ApprovalCommand
from ..application.records import ResumeRequest, StartCaseResponse
from ..application.records import StartCaseRequest as StartCommand


def start_request(**values: Any) -> StartCommand:
    return StartCommand.model_validate({"operator_id": "test-operator", **values})


def approval_request(**values: Any) -> ApprovalCommand:
    return ApprovalCommand.model_validate({"reason": "Test evidence reviewed", **values})


def resume_request(started: StartCaseResponse) -> ResumeRequest:
    return ResumeRequest(checkpoint_id=started.checkpoint_id or "", operator_id="test-operator")
