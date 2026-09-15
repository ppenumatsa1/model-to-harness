from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from secrets import compare_digest
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic_settings import BaseSettings, SettingsConfigDict

from checkout_recovery_maf.api.routes import get_service, router
from checkout_recovery_maf.application import CheckoutRecoveryService
from checkout_recovery_maf.infrastructure import InMemoryCaseRepository, PostgresCaseRepository
from checkout_recovery_maf.infrastructure.telemetry import configure_api_telemetry, operation
from checkout_recovery_maf.maf.investigation import MafInvestigator, ScriptedInvestigator


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CHECKOUT_RECOVERY_", extra="ignore")

    foundry_project_endpoint: str | None = None
    foundry_model_deployment: str | None = None
    database_url: str | None = None
    max_auto_inventory_quantity: int = 1
    execution_mode: Literal["scripted", "maf"] = "scripted"
    environment: Literal["development", "production"] = "development"
    api_token: str | None = None


def create_app(
    *,
    service: CheckoutRecoveryService | None = None,
    settings: Settings | None = None,
) -> FastAPI:
    app_settings = settings or Settings()
    if app_settings.environment == "production" and (
        not app_settings.database_url
        or not app_settings.api_token
        or app_settings.execution_mode != "maf"
    ):
        raise ValueError("production requires PostgreSQL, API token, and MAF execution")
    if app_settings.execution_mode == "maf" and (
        not app_settings.foundry_project_endpoint or not app_settings.foundry_model_deployment
    ):
        raise ValueError("MAF execution requires a project endpoint and model deployment")
    investigator = (
        MafInvestigator(
            app_settings.foundry_project_endpoint, app_settings.foundry_model_deployment
        )
        if app_settings.execution_mode == "maf"
        else ScriptedInvestigator()
    )
    repository = (
        PostgresCaseRepository(app_settings.database_url)
        if app_settings.database_url
        else InMemoryCaseRepository()
    )
    app_service = service or CheckoutRecoveryService(
        repository,
        max_auto_inventory_quantity=app_settings.max_auto_inventory_quantity,
        investigator=investigator,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        telemetry = configure_api_telemetry()
        if isinstance(repository, PostgresCaseRepository):
            repository.open()
        try:
            app_service.ready()
            yield
        finally:
            if isinstance(repository, PostgresCaseRepository):
                repository.close()
            if telemetry:
                telemetry.force_flush()
                telemetry.shutdown()

    app = FastAPI(
        title="Checkout Recovery MAF Harness",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.dependency_overrides[get_service] = lambda: app_service

    @app.middleware("http")
    async def authorize(request: Request, call_next):
        if app_settings.api_token and not request.url.path.startswith("/api/health/"):
            if not compare_digest(
                request.headers.get("x-checkout-token", ""), app_settings.api_token
            ):
                return JSONResponse({"detail": "unauthorized"}, status_code=401)
        with operation("api"):
            return await call_next(request)

    app.include_router(router, prefix="/api")
    return app


app = create_app()
