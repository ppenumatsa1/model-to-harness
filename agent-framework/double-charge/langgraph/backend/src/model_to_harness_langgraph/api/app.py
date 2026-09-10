from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from ..application.ports import AuditRepository
from ..application.service import CaseNotFoundError, InvalidCommandError
from ..bootstrap import open_runtime
from ..config import Settings, get_settings
from ..infrastructure.domain_gateway import DomainGateway
from ..infrastructure.model_client import ComplaintModel
from ..infrastructure.telemetry import execution_span
from .routes import create_router


def create_app(
    *,
    settings: Settings | None = None,
    audit: AuditRepository | None = None,
    gateway: DomainGateway | None = None,
    model: ComplaintModel | None = None,
    checkpointer: Any | None = None,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with open_runtime(
            settings, audit=audit, gateway=gateway, model=model, checkpointer=checkpointer
        ) as runtime:
            app.state.runtime = runtime
            app.state.audit = runtime.audit
            app.state.service = runtime.service
            yield

    app = FastAPI(
        title="Model to Harness: LangGraph",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def trace_request(request: Request, call_next):
        with execution_span("http.request", **{"http.request.method": request.method}) as span:
            response = await call_next(request)
            route = request.scope.get("route")
            if route is not None:
                span.set_attribute("http.route", route.path)
            span.set_attribute("http.response.status_code", response.status_code)
            return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Last-Event-ID"],
    )

    @app.exception_handler(CaseNotFoundError)
    async def not_found(_: Request, exc: CaseNotFoundError) -> JSONResponse:
        return JSONResponse({"detail": f"Case not found: {exc}"}, status_code=404)

    @app.exception_handler(InvalidCommandError)
    async def invalid_command(_: Request, exc: InvalidCommandError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=409)

    app.include_router(create_router(settings))
    return app
