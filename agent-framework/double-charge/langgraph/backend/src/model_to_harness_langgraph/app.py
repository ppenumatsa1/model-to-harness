import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from .agui import project_events
from .audit import AuditRepository, PostgresAuditRepository
from .checkpointing import checkpoint_conninfo, ensure_checkpoint_schema
from .config import Settings, get_settings
from .contracts import (
    ApprovalRequest,
    CaseView,
    CopilotRunPayload,
    ExplainRequest,
    ExplainResponse,
    HealthResponse,
    NativeEvent,
    StartCaseRequest,
    StartCaseResponse,
)
from .domain_gateway import DomainGateway, SharedDomainGateway, shared_package_available
from .logging_setup import configure_logging
from .model_adapter import ComplaintModel, FoundryComplaintModel
from .observability import configure_optional_azure_monitor
from .service import CaseNotFoundError, InvalidCommandError, WorkflowService
from .workflow import DoubleChargeWorkflow


def create_app(
    *,
    settings: Settings | None = None,
    audit: AuditRepository | None = None,
    gateway: DomainGateway | None = None,
    model: ComplaintModel | None = None,
    checkpointer: Any | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)
    configure_optional_azure_monitor()
    injected = all(item is not None for item in (audit, gateway, model, checkpointer))

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            runtime_audit = audit
            runtime_checkpointer = checkpointer
            if not injected:
                runtime_audit = PostgresAuditRepository(
                    settings.database_url, settings.langgraph_schema
                )
                await runtime_audit.setup()
                stack.push_async_callback(runtime_audit.close)
                await ensure_checkpoint_schema(
                    settings.database_url,
                    settings.langgraph_checkpoint_schema,
                )
                runtime_checkpointer = await stack.enter_async_context(
                    AsyncPostgresSaver.from_conn_string(
                        checkpoint_conninfo(
                            settings.database_url,
                            settings.langgraph_checkpoint_schema,
                        )
                    )
                )
                await runtime_checkpointer.setup()
            assert runtime_audit is not None
            runtime_gateway = gateway or SharedDomainGateway()
            runtime_model = model or FoundryComplaintModel(settings)
            workflow = DoubleChargeWorkflow(
                audit=runtime_audit,
                gateway=runtime_gateway,
                model=runtime_model,
                checkpointer=runtime_checkpointer,
            )
            app.state.audit = runtime_audit
            app.state.service = WorkflowService(workflow, runtime_audit)
            yield

    app = FastAPI(
        title="Model to Harness: LangGraph",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Last-Event-ID"],
    )

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

    @app.exception_handler(CaseNotFoundError)
    async def not_found(_: Request, exc: CaseNotFoundError) -> JSONResponse:
        return JSONResponse({"detail": f"Case not found: {exc}"}, status_code=404)

    @app.exception_handler(InvalidCommandError)
    async def invalid_command(_: Request, exc: InvalidCommandError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    @app.get("/health", response_model=HealthResponse)
    async def health(request: Request) -> HealthResponse:
        db = await request.app.state.audit.ping()
        ready = db and settings.model_ready and shared_package_available()
        return HealthResponse(
            status="ok" if ready else "degraded",
            database=db,
            model_configured=settings.model_ready,
            shared_package=shared_package_available(),
        )

    @app.get("/ready")
    async def ready(request: Request) -> dict[str, str]:
        if not await request.app.state.audit.ping():
            raise HTTPException(status_code=503, detail="Database is not ready")
        return {"status": "ready"}

    @app.get("/api/scenarios")
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

    @app.get("/api/copilotkit/info")
    async def copilotkit_info_get() -> dict[str, Any]:
        return copilot_info()

    @app.post("/api/copilotkit/agent/selected-run/run")
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

    @app.post("/api/cases", response_model=StartCaseResponse, status_code=201)
    async def start_case(body: StartCaseRequest, request: Request) -> StartCaseResponse:
        return await service(request).start(body)

    @app.get("/api/cases/{case_id}", response_model=CaseView)
    async def get_case(case_id: str, request: Request) -> CaseView:
        return await service(request).get_case(case_id)

    @app.get("/api/cases/{case_id}/events", response_model=list[NativeEvent])
    async def events(
        case_id: str,
        request: Request,
        after: int = Query(default=0, ge=0),
    ) -> list[NativeEvent]:
        return await service(request).list_events(case_id, after)

    @app.get("/api/cases/{case_id}/history", response_model=list[NativeEvent])
    async def history(case_id: str, request: Request) -> list[NativeEvent]:
        return await service(request).list_events(case_id)

    @app.post("/api/cases/{case_id}/approval", status_code=202)
    async def approve(
        case_id: str, body: ApprovalRequest, request: Request
    ) -> dict[str, str]:
        await service(request).submit_approval(case_id, body)
        return {"status": "recorded"}

    @app.post("/api/cases/{case_id}/resume", response_model=StartCaseResponse)
    async def resume(case_id: str, request: Request) -> StartCaseResponse:
        return await service(request).resume(case_id)

    @app.post("/api/cases/{case_id}/explain", response_model=ExplainResponse)
    async def explain(
        case_id: str, body: ExplainRequest, request: Request
    ) -> ExplainResponse:
        answer, sequences = await service(request).explain(case_id, body.question)
        return ExplainResponse(answer=answer, cited_sequences=sequences)

    @app.get("/api/cases/{case_id}/agui")
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

    return app
