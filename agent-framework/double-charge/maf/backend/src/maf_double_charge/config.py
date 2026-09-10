from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    host: str = "127.0.0.1"
    port: int = 8010
    database_url: str = "postgresql://postgres:postgres@localhost:5432/model_to_harness"
    database_schema: str = Field(default="maf_double_charge", pattern=r"^[a-z][a-z0-9_]*$")
    frontend_origin: str = "http://localhost:5173"
    log_level: str = "INFO"
    foundry_project_endpoint: str | None = None
    foundry_model: str | None = None
    applicationinsights_connection_string: str | None = None
    otel_exporter_otlp_endpoint: str | None = None
    otel_service_name: str | None = None
    otel_service_version: str | None = None
    max_tool_attempts: int = Field(default=3, ge=1, le=5)

    @property
    def foundry_configured(self) -> bool:
        return bool(self.foundry_project_endpoint and self.foundry_model)


@lru_cache
def get_settings() -> Settings:
    return Settings()
