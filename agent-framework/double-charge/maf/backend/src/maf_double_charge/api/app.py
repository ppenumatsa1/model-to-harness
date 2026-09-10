from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ..bootstrap import Runtime, create_runtime
from ..config import Settings, get_settings
from ..infrastructure.telemetry import instrument_api_app
from .routers import approvals, assistant, cases, health, runs, streams


def create_app(
    *,
    settings: Settings | None = None,
    runtime: Runtime | None = None,
) -> FastAPI:
    settings = settings or (runtime.settings if runtime is not None else get_settings())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        active_runtime = runtime if runtime is not None else create_runtime(settings, host="api")
        app.state.runtime = active_runtime
        try:
            await active_runtime.start()
            yield
        finally:
            await active_runtime.close()

    app = FastAPI(
        title="Model to Harness — MAF Double Charge",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.runtime = runtime
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type", "Last-Event-ID"],
    )
    for router in (
        health.router,
        cases.router,
        runs.router,
        approvals.router,
        streams.router,
        assistant.router,
    ):
        app.include_router(router)
    instrument_api_app(app, settings)
    return app
