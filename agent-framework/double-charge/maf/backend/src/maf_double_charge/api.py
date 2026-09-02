from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from model_to_harness_shared import SCENARIO_FIXTURES, WorkflowOutcome

from .agui import project_events
from .config import Settings, get_settings
from .logging_setup import configure_logging
from .model_client import FakeModelClient, FoundryModelClient, ModelClient
from .models import (
    WORKFLOW_GRAPH,
    ApprovalCommand,
    CaseView,
    DurableEvent,
    ResumeCommand,
    ScenarioInput,
    StartResponse,
)
from .orchestrator import DoubleChargeOrchestrator
from .repository import PostgresRepository, Repository
from .telemetry import configure_telemetry


def create_app(
    *,
    settings: Settings | None = None,
    repository: Repository | None = None,
    model: ModelClient | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    configure_telemetry(settings)
    repository = repository or PostgresRepository(settings.database_url, settings.database_schema)
    model = model or FoundryModelClient(settings)
    orchestrator = DoubleChargeOrchestrator(repository, model, settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        await repository.initialize()
        yield
        await repository.close()
        close = getattr(model, "close", None)
        if close is not None:
            await close()

    app = FastAPI(
        title="Model to Harness — MAF Double Charge",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.repository = repository
    app.state.model = model
    app.state.orchestrator = orchestrator
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Last-Event-ID"],
    )

    safe_event_types = {
        "decision.summary",
        "parallel.joined",
        "approval.requested",
        "approval.recorded",
        "approval.resolved",
        "refund.verification",
        "run.completed",
        "run.failed",
    }

    async def selected_run_facts(
        run_id: str,
    ) -> tuple[Any, list[DurableEvent], dict[str, Any]]:
        try:
            state = await orchestrator.get_state(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        allowlisted = [
            event
            for event in await repository.list_events(run_id)
            if event.event_type in safe_event_types
        ]
        facts = {
            "status": state.status,
            "current_step": state.current_step,
            "terminal_status": state.terminal_status,
            "refund_status": state.refund_status,
            "latest_summary": allowlisted[-1].summary if allowlisted else "No decision yet.",
            "event_summaries": [event.summary for event in allowlisted[-8:]],
        }
        return state, allowlisted, facts

    @app.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready")
    async def ready() -> dict[str, str]:
        try:
            if isinstance(repository, PostgresRepository):
                async with repository.pool.connection() as conn:
                    await conn.execute("SELECT 1")
            return {"status": "ready"}
        except Exception as exc:
            raise HTTPException(status_code=503, detail="database is not ready") from exc

    @app.get("/api/scenarios")
    async def scenarios() -> list[dict[str, Any]]:
        return [
            {
                "id": fixture.fixture_id,
                "description": fixture.description,
                "expected_terminal_status": fixture.expected.terminal_status,
                "tags": sorted(fixture.tags),
            }
            for fixture in SCENARIO_FIXTURES.values()
        ]

    @app.get("/api/workflow/graph")
    async def workflow_graph() -> dict[str, Any]:
        return WORKFLOW_GRAPH

    @app.get("/api/copilotkit/info")
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

    @app.get("/api/copilotkit")
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

    @app.get("/api/copilotkit/runs/{run_id}")
    async def copilotkit_selected_run(run_id: str) -> dict[str, Any]:
        state, run_events, _ = await selected_run_facts(run_id)
        return {
            "read_only": True,
            "run": {
                "run_id": state.run_id,
                "case_id": state.case_id,
                "status": state.status,
                "current_step": state.current_step,
                "approval_required": state.approval_required,
                "terminal_status": state.terminal_status,
                "refund_status": state.refund_status,
            },
            "events": [
                {
                    "sequence": event.sequence,
                    "event_type": event.event_type,
                    "summary": event.summary,
                }
                for event in run_events
            ],
            "safety": (
                "No complaint text, prompts, secrets, checkpoint bodies, "
                "idempotency keys, or unrestricted tool payloads."
            ),
        }

    @app.post("/api/copilotkit/agent/selected-run/run")
    async def copilotkit_run(request: Request) -> StreamingResponse:
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
            await orchestrator.get_state(selected_run_id)
        except KeyError:
            selected_case = await repository.get_state_by_case(selected_run_id)
            if selected_case is None:
                raise HTTPException(
                    status_code=404, detail="selected run or case not found"
                ) from None
            selected_run_id = selected_case.run_id
        messages = payload["messages"]
        question = next(
            (
                message.get("content")
                for message in reversed(messages)
                if isinstance(message, dict)
                and message.get("role") == "user"
                and isinstance(message.get("content"), str)
            ),
            None,
        )
        if not question:
            raise HTTPException(status_code=422, detail="a user question is required")
        _, _, facts = await selected_run_facts(selected_run_id)
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

    @app.post("/api/cases", response_model=StartResponse)
    async def start_case(command: ScenarioInput) -> StartResponse:
        try:
            return await orchestrator.start(command)
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.get("/api/cases/{case_id}", response_model=CaseView)
    async def get_case(case_id: str) -> CaseView:
        state = await repository.get_state_by_case(case_id)
        if state is None:
            raise HTTPException(status_code=404, detail="case not found")
        outcome = await repository.get_outcome(state.run_id)
        return CaseView(
            state=state,
            memory=await repository.get_memory(case_id),
            outcome=outcome,
        )

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        try:
            state = await orchestrator.get_state(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        return {
            "state": state,
            "memory": await repository.get_memory(state.case_id),
            "outcome": await orchestrator.get_outcome(run_id),
            "graph": WORKFLOW_GRAPH,
        }

    @app.get("/api/runs/{run_id}/events", response_model=list[DurableEvent])
    async def events(run_id: str, after: int = Query(default=0, ge=0)) -> list[DurableEvent]:
        try:
            await orchestrator.get_state(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        return await repository.list_events(run_id, after=after)

    @app.get("/api/runs/{run_id}/history", response_model=list[DurableEvent])
    async def history(run_id: str) -> list[DurableEvent]:
        return await events(run_id, after=0)

    @app.get("/api/runs/{run_id}/outcome", response_model=WorkflowOutcome)
    async def outcome(run_id: str) -> WorkflowOutcome:
        result = await orchestrator.get_outcome(run_id)
        if result is None:
            raise HTTPException(status_code=409, detail="run has not reached a terminal outcome")
        return result

    @app.post("/api/runs/{run_id}/approval")
    async def approval(run_id: str, command: ApprovalCommand) -> dict[str, Any]:
        try:
            state = await orchestrator.record_approval(run_id, command)
            return {"status": "recorded", "run_id": run_id, "state": state}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/runs/{run_id}/resume")
    async def resume(run_id: str, command: ResumeCommand) -> dict[str, Any]:
        try:
            state = await orchestrator.resume(run_id, command.checkpoint_id)
            return {"status": state.status, "state": state}
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}/ag-ui")
    async def ag_ui_stream(
        request: Request,
        run_id: str,
        after: int = Query(default=0, ge=0),
        follow: bool = False,
    ) -> StreamingResponse:
        try:
            state = await orchestrator.get_state(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="run not found") from exc
        header_after = request.headers.get("last-event-id")
        cursor = max(after, int(header_after)) if header_after and header_after.isdigit() else after

        async def stream() -> AsyncIterator[str]:
            nonlocal cursor, state
            idle_ticks = 0
            while True:
                durable = await repository.list_events(run_id, after=cursor)
                if durable:
                    state = await orchestrator.get_state(run_id)
                    for item in durable:
                        for projected in project_events([item], state):
                            yield f"id: {item.sequence}\ndata: {json.dumps(projected)}\n\n"
                        cursor = item.sequence
                    idle_ticks = 0
                else:
                    yield ": keepalive\n\n"
                    idle_ticks += 1
                if not follow or idle_ticks >= 30:
                    break
                await asyncio.sleep(1)

        return StreamingResponse(stream(), media_type="text/event-stream")

    return app


def create_test_app() -> FastAPI:
    from .repository import InMemoryRepository

    settings = Settings(foundry_project_endpoint=None, foundry_model=None)
    return create_app(
        settings=settings,
        repository=InMemoryRepository(),
        model=FakeModelClient(),
    )
