from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from ...infrastructure.telemetry import telemetry_context
from ...projections.selected_run import selected_run_facts, selected_run_view
from ..dependencies import (
    ModelDependency,
    RepositoryDependency,
    RunDependency,
    ServiceDependency,
)

router = APIRouter()


@router.get("/api/copilotkit/info")
async def copilotkit_info() -> dict[str, Any]:
    return {
        "mode": "sse",
        "version": "teaching-adapter-v1",
        "agents": {
            "selected-run": {
                "description": (
                    "Read-only selected-run explainer backed by allowlisted durable facts."
                ),
                "capabilities": {},
            }
        },
        "description": (
            "CopilotKit AG-UI runtime. It exposes no workflow command tools or actions."
        ),
    }


@router.get("/api/copilotkit")
async def copilotkit_discovery() -> dict[str, Any]:
    return {
        "name": "selected-run-read-only-bridge",
        "read_only": True,
        "runtime_info": "/api/copilotkit/info",
        "runtime_run": "/api/copilotkit/agent/selected-run/run",
        "selected_run": "/api/copilotkit/runs/{run_id}",
        "commands": {
            "start": "/api/cases",
            "approval": "/api/runs/{run_id}/approval",
            "resume": "/api/runs/{run_id}/resume",
        },
        "note": (
            "CopilotKit receives allowlisted selected-run context only. "
            "Workflow commands remain explicit FastAPI operations."
        ),
    }


@router.get("/api/copilotkit/runs/{run_id}")
async def copilotkit_selected_run(
    run_id: str, state: RunDependency, repository: RepositoryDependency
) -> dict[str, Any]:
    return selected_run_view(state, await repository.list_events(run_id))


@router.post("/api/copilotkit/agent/selected-run/run")
async def copilotkit_run(
    request: Request,
    service: ServiceDependency,
    repository: RepositoryDependency,
    model: ModelDependency,
) -> StreamingResponse:
    try:
        payload = await request.json()
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="invalid AG-UI request") from exc
    required = {"threadId", "runId", "state", "messages", "tools", "context"}
    if not isinstance(payload, dict) or not required.issubset(payload):
        raise HTTPException(status_code=422, detail="invalid AG-UI RunAgentInput")
    if (
        not isinstance(payload["threadId"], str)
        or not isinstance(payload["runId"], str)
        or not isinstance(payload["messages"], list)
        or not isinstance(payload["tools"], list)
        or not isinstance(payload["context"], list)
    ):
        raise HTTPException(status_code=422, detail="invalid AG-UI RunAgentInput")
    selected_run_id = payload["threadId"]
    try:
        state = await service.get_state(selected_run_id)
    except KeyError:
        selected_case = await repository.get_state_by_case(selected_run_id)
        if selected_case is None:
            raise HTTPException(status_code=404, detail="selected run or case not found") from None
        selected_run_id = selected_case.run_id
        state = await service.get_state(selected_run_id)
    question = next(
        (
            message.get("content")
            for message in reversed(payload["messages"])
            if isinstance(message, dict)
            and message.get("role") == "user"
            and isinstance(message.get("content"), str)
        ),
        None,
    )
    if not question:
        raise HTTPException(status_code=422, detail="a user question is required")
    _, facts = selected_run_facts(state, await repository.list_events(selected_run_id))
    with telemetry_context(case_id=state.case_id, run_id=selected_run_id):
        result = await model.explain_run(question, facts)
    message_id = f"message-{uuid4().hex}"
    thread_id = payload["threadId"]
    invocation_run_id = payload["runId"]
    protocol_events = [
        {
            "type": "RUN_STARTED",
            "threadId": thread_id,
            "runId": invocation_run_id,
        },
        {
            "type": "TEXT_MESSAGE_START",
            "messageId": message_id,
            "role": "assistant",
        },
        {
            "type": "TEXT_MESSAGE_CONTENT",
            "messageId": message_id,
            "delta": result.text,
        },
        {"type": "TEXT_MESSAGE_END", "messageId": message_id},
        {
            "type": "RUN_FINISHED",
            "threadId": thread_id,
            "runId": invocation_run_id,
        },
    ]

    async def stream() -> AsyncIterator[str]:
        for event in protocol_events:
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")
