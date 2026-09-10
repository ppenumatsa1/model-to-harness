import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from psycopg import Error as DatabaseError

from ..application.records import (
    ApprovalRequest,
    CaseView,
    NativeEvent,
    StartCaseRequest,
    StartCaseResponse,
)
from ..application.service import WorkflowService
from ..config import Settings
from ..infrastructure.domain_gateway import shared_package_available
from ..infrastructure.persistence.migrations import StorageNotReadyError
from ..projections.agui import project_events
from .schemas import CopilotRunPayload, ExplainRequest, ExplainResponse, HealthResponse


def create_router(settings: Settings) -> APIRouter:
    router = APIRouter()

    def service(request: Request) -> WorkflowService:
        return request.app.state.service

    def copilot_info() -> dict[str, Any]:
        return {
            "actions": [],
            "agents": {
                "selected-run": {
                    "description": (
                        "Read-only explanation of allowlisted durable events for one selected run."
                    ),
                }
            },
            "version": "0.1.0",
        }

    @router.get("/health", response_model=HealthResponse)
    async def health(request: Request) -> HealthResponse:
        db = await request.app.state.audit.ping()
        ready = db and settings.model_ready and shared_package_available()
        return HealthResponse(
            status="ok" if ready else "degraded",
            database=db,
            model_configured=settings.model_ready,
            shared_package=shared_package_available(),
        )

    @router.get("/ready")
    async def ready(request: Request) -> dict[str, str]:
        try:
            await request.app.state.runtime.verify()
        except (DatabaseError, StorageNotReadyError, RuntimeError) as exc:
            logging.getLogger(__name__).warning(
                "Storage readiness failed",
                extra={"safe_event": "storage_readiness_failed", "error_type": type(exc).__name__},
            )
            raise HTTPException(status_code=503, detail="Database is not ready") from None
        return {"status": "ready"}

    @router.get("/api/scenarios")
    async def scenarios() -> list[dict[str, str]]:
        return [
            {"id": "duplicate-confirmed", "label": "Duplicate confirmed"},
            {"id": "no-duplicate", "label": "No duplicate"},
            {"id": "approval-denied", "label": "Approval denied"},
            {"id": "transient-failure", "label": "Transient read failure"},
            {"id": "retry-safe-refund", "label": "Retry-safe refund"},
            {"id": "resumed-approval", "label": "Resumed approval"},
            {"id": "verification-mismatch", "label": "Verification mismatch"},
        ]

    @router.get("/api/copilotkit/info")
    async def copilotkit_info_get() -> dict[str, Any]:
        return copilot_info()

    @router.post("/api/copilotkit/agent/selected-run/run")
    async def copilotkit_selected_run(
        request: Request,
        payload: CopilotRunPayload,
    ) -> StreamingResponse:
        answer, sequences = await service(request).explain(
            payload.thread_id,
            "Summarize the selected run from allowlisted durable events.",
        )

        async def generate_selected_run() -> AsyncIterator[str]:
            message_id = f"selected-run:{payload.run_id}"
            cited_answer = (
                f"{answer} Audit events: {', '.join(str(sequence) for sequence in sequences)}."
                if sequences
                else answer
            )
            projected = (
                {
                    "type": "RUN_STARTED",
                    "threadId": payload.thread_id,
                    "runId": payload.run_id,
                },
                {
                    "type": "TEXT_MESSAGE_START",
                    "messageId": message_id,
                    "role": "assistant",
                },
                {
                    "type": "TEXT_MESSAGE_CONTENT",
                    "messageId": message_id,
                    "delta": cited_answer,
                },
                {
                    "type": "TEXT_MESSAGE_END",
                    "messageId": message_id,
                },
                {
                    "type": "RUN_FINISHED",
                    "threadId": payload.thread_id,
                    "runId": payload.run_id,
                    "outcome": {"type": "success"},
                },
            )
            for event in projected:
                yield f"data: {json.dumps(event, separators=(',', ':'))}\n\n"

        return StreamingResponse(
            generate_selected_run(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store"},
        )

    @router.post("/api/cases", response_model=StartCaseResponse, status_code=201)
    async def start_case(body: StartCaseRequest, request: Request) -> StartCaseResponse:
        return await service(request).start(body)

    @router.get("/api/cases/{case_id}", response_model=CaseView)
    async def get_case(case_id: str, request: Request) -> CaseView:
        return await service(request).get_case(case_id)

    @router.get("/api/cases/{case_id}/events", response_model=list[NativeEvent])
    async def events(
        case_id: str,
        request: Request,
        after: int = Query(default=0, ge=0),
    ) -> list[NativeEvent]:
        return await service(request).list_events(case_id, after)

    @router.get("/api/cases/{case_id}/history", response_model=list[NativeEvent])
    async def history(case_id: str, request: Request) -> list[NativeEvent]:
        return await service(request).list_events(case_id)

    @router.post("/api/cases/{case_id}/approval", status_code=202)
    async def approve(case_id: str, body: ApprovalRequest, request: Request) -> dict[str, str]:
        await service(request).submit_approval(case_id, body)
        return {"status": "recorded"}

    @router.post("/api/cases/{case_id}/resume", response_model=StartCaseResponse)
    async def resume(case_id: str, request: Request) -> StartCaseResponse:
        return await service(request).resume(case_id)

    @router.post("/api/cases/{case_id}/explain", response_model=ExplainResponse)
    async def explain(case_id: str, body: ExplainRequest, request: Request) -> ExplainResponse:
        answer, sequences = await service(request).explain(case_id, body.question)
        return ExplainResponse(answer=answer, cited_sequences=sequences)

    @router.get("/api/cases/{case_id}/agui")
    async def agui_stream(
        case_id: str,
        request: Request,
        after: int = Query(default=0, ge=0),
    ) -> StreamingResponse:
        async def generate() -> AsyncIterator[str]:
            cursor = after
            idle = 0
            while idle < 30 and not await request.is_disconnected():
                batch = await service(request).list_events(case_id, cursor)
                if batch:
                    idle = 0
                    for event in batch:
                        cursor = event.sequence
                        for projected in project_events(event):
                            yield (
                                f"id: {event.sequence}\nevent: message\ndata: "
                                f"{json.dumps(projected, separators=(',', ':'))}\n\n"
                            )
                else:
                    idle += 1
                    yield ": keep-alive\n\n"
                await asyncio.sleep(1)

        return StreamingResponse(generate(), media_type="text/event-stream")

    return router
