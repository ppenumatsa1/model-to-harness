"""Foundry Responses 2.0 adapter for explicit checkout-recovery commands."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any
from uuid import UUID

from azure.ai.agentserver.responses import ResponsesAgentServerHost, TextResponse
from checkout_recovery_maf.application import (
    CaseNotFoundError,
    CheckoutRecoveryService,
    InvalidCaseCommandError,
    RecordApprovalCommand,
    ResumeCaseCommand,
    StartCaseCommand,
)
from checkout_recovery_maf.bootstrap import Runtime, create_runtime
from checkout_recovery_maf.config import Settings
from checkout_recovery_maf.projections import project_case
from model_to_harness_shared import CheckoutApprovalDecision
from psycopg import Error as DatabaseError
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class StartCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: str
    fixture_id: str = Field(min_length=1, max_length=120)
    request_id: UUID | None = None

    def to_command(self) -> StartCaseCommand:
        return StartCaseCommand(self.fixture_id, str(self.request_id) if self.request_id else None)


class ApprovalCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: str
    case_id: str = Field(min_length=1)
    decision: CheckoutApprovalDecision
    reviewer_id: str = Field(min_length=1, max_length=120)
    approval_request_id: UUID
    reason: str = Field(min_length=1, max_length=500)

    def to_command(self) -> RecordApprovalCommand:
        return RecordApprovalCommand(
            self.case_id,
            self.decision,
            self.reviewer_id,
            str(self.approval_request_id),
            self.reason,
        )


class ResumeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: str
    case_id: str = Field(min_length=1)

    def to_command(self) -> ResumeCaseCommand:
        return ResumeCaseCommand(self.case_id)


_runtime_lock = asyncio.Lock()
_runtime: Runtime | None = None


def _payload(create_response: Any) -> dict[str, Any]:
    if isinstance(create_response, dict):
        return create_response
    if hasattr(create_response, "model_dump"):
        value = create_response.model_dump()
        if isinstance(value, dict):
            return value
    return {}


def _input_text(payload: dict[str, Any]) -> str:
    value = payload.get("input")
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return ""
    for item in reversed(value):
        if not isinstance(item, dict) or item.get("role", "user") != "user":
            continue
        content = item.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for part in reversed(content):
                if isinstance(part, dict):
                    text = part.get("text") or part.get("input_text")
                    if isinstance(text, str):
                        return text
    return ""


def _command(create_response: Any) -> dict[str, Any]:
    try:
        command = json.loads(_input_text(_payload(create_response)))
    except json.JSONDecodeError as error:
        raise ValueError("command must be a JSON object") from error
    if not isinstance(command, dict):
        raise ValueError("command must be a JSON object")
    return command


async def _checkout_service() -> CheckoutRecoveryService:
    global _runtime
    async with _runtime_lock:
        if _runtime is None:
            runtime = create_runtime(Settings(_env_file=None, execution_mode="maf"), host="hosted")
            try:
                await asyncio.to_thread(runtime.start)
            except BaseException:
                await asyncio.to_thread(runtime.close)
                raise
            _runtime = runtime
        return _runtime.service


async def _close_runtime() -> None:
    global _runtime
    async with _runtime_lock:
        runtime, _runtime = _runtime, None
        if runtime is not None:
            await asyncio.to_thread(runtime.close)


async def _execute(command: dict[str, Any]) -> dict[str, Any]:
    service = await _checkout_service()
    action = command.get("action")
    if action == "start":
        validated = StartCommand.model_validate(command).to_command()
    elif action == "approval":
        validated = ApprovalCommand.model_validate(command).to_command()
    elif action == "resume":
        validated = ResumeCommand.model_validate(command).to_command()
    else:
        raise ValueError("action must be start, approval, or resume")
    case = await asyncio.to_thread(service.execute, validated)
    return project_case(case).model_dump(mode="json")


async def response_handler(
    create_response: Any,
    context: Any | None = None,
    cancellation_signal: Any | None = None,
) -> Any:
    del cancellation_signal
    try:
        result = await _execute(_command(create_response))
    except (CaseNotFoundError, InvalidCaseCommandError, ValidationError, ValueError, KeyError):
        logging.getLogger(__name__).warning("Checkout command rejected by application policy")
        result = {"error": "checkout command was rejected"}
    except DatabaseError:
        logging.getLogger(__name__).error("Checkout persistence command failed")
        raise RuntimeError("checkout persistence command failed") from None
    return TextResponse(context, create_response, text=json.dumps(result, separators=(",", ":")))


def create_host() -> ResponsesAgentServerHost:
    # Must be set before the platform initializes any Responses instrumentation.
    os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "false"
    host = ResponsesAgentServerHost()
    host.response_handler(response_handler)
    return host


async def main() -> None:
    try:
        await create_host().run_async()
    finally:
        await _close_runtime()


if __name__ == "__main__":
    asyncio.run(main())
