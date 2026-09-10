from __future__ import annotations

import asyncio
import json
import os
from typing import Any
from uuid import uuid4

from azure.ai.agentserver.responses import ResponsesAgentServerHost, TextResponse
from maf_double_charge.application.commands import ApprovalCommand, ResumeCommand, ScenarioInput
from maf_double_charge.bootstrap import Runtime, create_runtime
from maf_double_charge.infrastructure.telemetry import (
    apply_hosted_instrumentation_policy,
    telemetry_context,
)

_lock = asyncio.Lock()
_active_runtime: Runtime | None = None


async def _runtime() -> Runtime:
    global _active_runtime
    if _active_runtime is not None:
        return _active_runtime
    async with _lock:
        if _active_runtime is None:
            runtime = create_runtime(host="hosted")
            try:
                await runtime.start()
            except BaseException:
                await runtime.close()
                raise
            _active_runtime = runtime
    return _active_runtime


def _payload(create_response: Any) -> dict[str, Any]:
    if isinstance(create_response, dict):
        return create_response
    if hasattr(create_response, "model_dump"):
        return create_response.model_dump()
    if hasattr(create_response, "as_dict"):
        return create_response.as_dict()
    return {}


def _input_text(payload: dict[str, Any]) -> str:
    raw_input = payload.get("input")
    if isinstance(raw_input, str):
        return raw_input.strip()
    if isinstance(raw_input, dict):
        raw_input = [raw_input]
    if not isinstance(raw_input, list):
        return ""
    for item in reversed(raw_input):
        if not isinstance(item, dict) or item.get("role", "user") != "user":
            continue
        parts: list[str] = []
        content = item.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for part in content:
                if not isinstance(part, dict):
                    continue
                text = part.get("text") or part.get("input_text")
                if isinstance(text, str):
                    parts.append(text)
        if parts:
            return " ".join(parts).strip()
    return ""


def _conversation_id(payload: dict[str, Any]) -> str | None:
    conversation = payload.get("conversation")
    if isinstance(conversation, str) and conversation.strip():
        return conversation.strip()
    if isinstance(conversation, dict) and isinstance(conversation.get("id"), str):
        return conversation["id"].strip()
    return None


def _command(text: str) -> dict[str, Any]:
    if text.startswith("{"):
        parsed = json.loads(text)
        if not isinstance(parsed, dict):
            raise ValueError("JSON input must be an object")
        return parsed
    return {
        "action": "start",
        "complaint": text,
        "customer_id": "foundry-customer",
        "scenario_id": "duplicate-confirmed",
    }


async def _execute(command: dict[str, Any], conversation_id: str) -> dict[str, Any]:
    runtime = await _runtime()
    service, repository = runtime.service, runtime.repository
    action = str(command.get("action", "start")).strip().lower()
    if action == "start":
        started = await service.start(
            ScenarioInput(
                complaint=str(command.get("complaint") or "I may have been charged twice."),
                customer_id=str(command.get("customer_id") or "foundry-customer"),
                account_id=command.get("account_id"),
                scenario_id=str(command.get("scenario_id") or "duplicate-confirmed"),
                existing_case_id=str(
                    command.get("existing_case_id") or command.get("case_id") or conversation_id
                ),
                idempotency_key=command.get("idempotency_key"),
            )
        )
        run_id = started.run_id
    elif action == "approval":
        run_id = str(command["run_id"])
        state = await service.get_state(run_id)
        run_id = state.run_id
        with telemetry_context(case_id=state.case_id, run_id=state.run_id):
            await service.record_approval(
                run_id,
                ApprovalCommand.model_validate(command),
            )
    elif action == "resume":
        run_id = str(command["run_id"])
        state = await service.get_state(run_id)
        run_id = state.run_id
        with telemetry_context(case_id=state.case_id, run_id=state.run_id):
            await service.resume(
                run_id,
                ResumeCommand.model_validate(command).checkpoint_id,
            )
    else:
        raise ValueError("action must be start, approval, or resume")

    state = await service.get_state(run_id)
    outcome = await service.get_outcome(run_id)
    events = await repository.list_events(run_id)
    return {
        "case_id": state.case_id,
        "run_id": state.run_id,
        "status": state.status,
        "current_step": state.current_step,
        "approval_required": state.approval_required,
        "checkpoint_id": state.checkpoint_id,
        "terminal_status": state.terminal_status,
        "refund_status": state.refund_status,
        "retry_count": sum(event.event_type == "tool.call.retried" for event in events),
        "outcome": outcome.model_dump(mode="json") if outcome else None,
        "events": [
            {
                "sequence": event.sequence,
                "event_type": event.event_type,
                "summary": event.summary,
            }
            for event in events[-20:]
        ],
    }


async def response_handler(
    create_response: Any,
    context: Any | None = None,
    cancellation_signal: Any | None = None,
) -> Any:
    del cancellation_signal
    payload = _payload(create_response)
    command = _command(_input_text(payload))
    conversation = getattr(context, "conversation_id", None)
    conversation_id = (
        conversation.strip()
        if isinstance(conversation, str) and conversation.strip()
        else _conversation_id(payload)
    )
    correlations = {
        key: value
        for key, value in {
            "conversation_id": conversation_id,
            "response_id": getattr(context, "response_id", None),
            "run_id": command.get("run_id"),
        }.items()
        if isinstance(value, str) and value
    }
    with telemetry_context(**correlations):
        result = await _execute(command, conversation_id or f"foundry-{uuid4().hex[:16]}")
        with telemetry_context(case_id=result["case_id"], run_id=result["run_id"]):
            return TextResponse(context, create_response, text=json.dumps(result, default=str))


def create_host() -> ResponsesAgentServerHost:
    os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "false"
    host = ResponsesAgentServerHost()
    apply_hosted_instrumentation_policy()
    host.response_handler(response_handler)
    return host


async def main() -> None:
    global _active_runtime
    try:
        host = create_host()
        await _runtime()
        await host.run_async()
    finally:
        if _active_runtime is not None:
            await _active_runtime.close()
            _active_runtime = None


if __name__ == "__main__":
    asyncio.run(main())
