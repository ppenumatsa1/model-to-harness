from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, ValidationError

from ..application.records import ApprovalRequest, StartCaseRequest
from ..application.service import CaseNotFoundError, InvalidCommandError, WorkflowService


class _HostedCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HostedStartCommand(_HostedCommand):
    action: Literal["start"] = "start"
    complaint: str = Field(default="I may have been charged twice.", min_length=5, max_length=4000)
    customer_id: str = Field(default="foundry-customer", min_length=1, max_length=128)
    scenario_id: str = Field(default="duplicate-confirmed", max_length=128)
    case_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str | None = Field(default=None, max_length=200)


class HostedApprovalCommand(_HostedCommand):
    action: Literal["approval"]
    case_id: str = Field(min_length=1, max_length=128)
    checkpoint_id: str = Field(min_length=1, max_length=256)
    decision: Literal["approve", "deny"]
    reviewer_id: str = Field(min_length=1, max_length=128)
    reason: str | None = Field(default=None, max_length=1000)


class HostedResumeCommand(_HostedCommand):
    action: Literal["resume"]
    case_id: str = Field(min_length=1, max_length=128)


HostedCommand = Annotated[
    HostedStartCommand | HostedApprovalCommand | HostedResumeCommand,
    Field(discriminator="action"),
]
_COMMAND_ADAPTER = TypeAdapter(HostedCommand)


def parse_hosted_command(text: str) -> HostedCommand:
    stripped = text.strip()
    if stripped.startswith("{"):
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            raise ValueError("JSON input must be an object")
        payload.setdefault("action", "start")
    else:
        payload = {
            "action": "start",
            "complaint": stripped or "I may have been charged twice.",
        }
    return _COMMAND_ADAPTER.validate_python(payload)


async def dispatch_hosted_command(
    service: WorkflowService,
    command: HostedCommand,
    conversation_chain_id: str,
) -> dict[str, Any]:
    if isinstance(command, HostedStartCommand):
        case_id = command.case_id or _conversation_case_id(conversation_chain_id)
        await service.start(
            StartCaseRequest(
                complaint=command.complaint,
                customer_id=command.customer_id,
                scenario_id=command.scenario_id,
                existing_case_id=case_id,
                idempotency_key=command.idempotency_key,
            )
        )
    elif isinstance(command, HostedApprovalCommand):
        case_id = command.case_id
        await service.submit_approval(
            case_id,
            ApprovalRequest(
                checkpoint_id=command.checkpoint_id,
                decision=command.decision,
                reviewer_id=command.reviewer_id,
                reason=command.reason,
            ),
        )
    else:
        case_id = command.case_id
        await service.resume(case_id)

    case = await service.get_case(case_id)
    events = await service.list_events(case_id)
    return {
        "ok": True,
        "command": command.action,
        "case": {
            "case_id": case.case_id,
            "run_id": case.run_id,
            "status": case.status,
            "current_step": case.current_step,
            "approval_required": case.approval_required,
            "checkpoint_id": case.checkpoint_id,
            "outcome": case.outcome.model_dump(mode="json") if case.outcome else None,
        },
        "events": [
            {
                "sequence": event.sequence,
                "event_type": event.event_type,
                "summary": event.summary,
                "node": event.node,
                "status": event.status,
            }
            for event in events[-20:]
        ],
    }


def safe_hosted_error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, CaseNotFoundError):
        code = "case_not_found"
        message = "The requested case does not exist."
    elif isinstance(exc, InvalidCommandError):
        code = "command_conflict"
        message = str(exc)
    elif isinstance(exc, (json.JSONDecodeError, ValidationError, ValueError)):
        code = "invalid_request"
        message = "Input must be a valid start, approval, or resume command."
    else:
        code = "internal_error"
        message = "The workflow command could not be completed."
    return {"ok": False, "error": {"code": code, "message": message}}


def _conversation_case_id(conversation_chain_id: str) -> str:
    digest = hashlib.sha256(conversation_chain_id.encode("utf-8")).hexdigest()[:24]
    return f"foundry-{digest}"
