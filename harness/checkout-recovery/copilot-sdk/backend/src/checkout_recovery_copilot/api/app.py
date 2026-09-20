from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from secrets import compare_digest

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from checkout_recovery_copilot.application import CheckoutRecoveryService
from checkout_recovery_copilot.bootstrap import create_runtime
from checkout_recovery_copilot.config import Settings
from checkout_recovery_copilot.infrastructure.telemetry import operation, record_api_response

from .routers import cases, health


def create_app(
    *,
    service: CheckoutRecoveryService | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    app_settings = settings if settings is not None else Settings()
    app_settings.validate_runtime()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        runtime = create_runtime(app_settings, service=service)
        app.state.runtime = runtime
        try:
            runtime.start()
            yield
        finally:
            try:
                runtime.close()
            finally:
                del app.state.runtime

    app = FastAPI(
        title="Checkout Recovery Copilot Harness",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def authorize(request: Request, call_next):
        with operation("api"):
            if (
                app_settings.api_token
                and not request.url.path.startswith("/api/health/")
                and not compare_digest(
                    request.headers.get("x-checkout-token", ""), app_settings.api_token
                )
            ):
                response = JSONResponse({"detail": "unauthorized"}, status_code=401)
            else:
                response = await call_next(request)
            record_api_response(request.method, response.status_code)
            return response

    app.include_router(health.router, prefix="/api")
    app.include_router(cases.router, prefix="/api")
    return app
