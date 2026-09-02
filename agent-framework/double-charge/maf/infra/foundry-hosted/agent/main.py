from __future__ import annotations

import asyncio
import json
from typing import Any
from uuid import uuid4

from azure.ai.agentserver.responses import ResponsesAgentServerHost, TextResponse

from maf_double_charge.config import get_settings
from maf_double_charge.model_client import FoundryModelClient
from maf_double_charge.models import ApprovalCommand, ResumeCommand, ScenarioInput
from maf_double_charge.orchestrator import DoubleChargeOrchestrator
from maf_double_charge.repository import PostgresRepository

_lock = asyncio.Lock()
_orchestrator: DoubleChargeOrchestrator | None = None
_repository: PostgresRepository | None = None


async def _runtime() -> tuple[DoubleChargeOrchestrator, PostgresRepository]:
    global _orchestrator, _repository
    if _orchestrator is not None and _repository is not None:
        return _orchestrator, _repository
    async with _lock:
        if _orchestrator is None or _repository is None:
            settings = get_settings()
            repository = PostgresRepository(settings.database_url, settings.database_schema)
            await repository.initialize()
            _repository = repository
            _orchestrator = DoubleChargeOrchestrator(
                repository,
                FoundryModelClient(settings),
                settings,
            )
    return _orchestrator, _repository


def _payload(create_response: Any) -> dict[str, Any]:
    if isinstance(create_response, dict):
        return create_response
    if hasattr(create_response, "model_dump"):
        return create_response.model_dump()
    return {}


def _input_text(payload: dict[str, Any]) -> str:
    raw_input = payload.get("input")
    if isinstance(raw_input, str):
        return raw_input.strip()
    if isinstance(raw_input, dict):
        raw_input = [raw_input]
    if not isinstance(raw_input, list):
        return ""
    parts: list[str] = []
    for item in raw_input:
        if not isinstance(item, dict):
            continue
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
    return " ".join(parts).strip()


def _conversation_id(payload: dict[str, Any]) -> str:
    conversation = payload.get("conversation")
    if isinstance(conversation, str) and conversation.strip():
        return conversation.strip()
    if isinstance(conversation, dict) and isinstance(conversation.get("id"), str):
        return conversation["id"].strip()
    return f"foundry-{uuid4().hex[:16]}"


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
    orchestrator, repository = await _runtime()
    action = str(command.get("action", "start")).strip().lower()
    if action == "start":
        started = await orchestrator.start(
            ScenarioInput(
                complaint=str(command.get("complaint") or "I may have been charged twice."),
                customer_id=str(command.get("customer_id") or "foundry-customer"),
                account_id=command.get("account_id"),
                scenario_id=str(command.get("scenario_id") or "duplicate-confirmed"),
                existing_case_id=str(command.get("case_id") or conversation_id),
                idempotency_key=command.get("idempotency_key"),
            )
        )
        run_id = started.run_id
    elif action == "approval":
        run_id = str(command["run_id"])
        await orchestrator.record_approval(
            run_id,
            ApprovalCommand.model_validate(command),
        )
    elif action == "resume":
        run_id = str(command["run_id"])
        await orchestrator.resume(
            run_id,
            ResumeCommand.model_validate(command).checkpoint_id,
        )
    else:
        raise ValueError("action must be start, approval, or resume")

    state = await orchestrator.get_state(run_id)
    outcome = await orchestrator.get_outcome(run_id)
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
    result = await _execute(_command(_input_text(payload)), _conversation_id(payload))
    return TextResponse(context, create_response, text=json.dumps(result, default=str))


host = ResponsesAgentServerHost()
host.response_handler(response_handler)


if __name__ == "__main__":
    host.run()
