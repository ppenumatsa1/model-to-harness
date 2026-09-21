from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def checkout_env_file(module_path: Path = Path(__file__)) -> Path | None:
    """Select only this editable checkout's lane root, never an installed parent."""
    source = module_path.resolve()
    package = source.parent
    if (
        package.name == "maf_double_charge"
        and package.parent.name == "src"
        and package.parent.parent.name == "backend"
    ):
        lane = package.parent.parent.parent
        if lane.name == "maf" and (lane / "pyproject.toml").is_file():
            return lane / ".env"
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=checkout_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    app_env: str = "development"
    host: str = "127.0.0.1"
    port: int = Field(default=8010, ge=1, le=65535)
    database_url: str = ""
    database_schema: str = Field(default="maf_double_charge", pattern=r"^[a-z][a-z0-9_]*$")
    frontend_origin: str = "http://localhost:5174"
    log_level: str = "INFO"
    foundry_project_endpoint: str | None = None
    foundry_model: str | None = None
    applicationinsights_connection_string: str | None = None
    otel_exporter_otlp_endpoint: str | None = None
    otel_service_name: str | None = None
    otel_service_version: str | None = None
    max_tool_attempts: int = Field(default=3, ge=1, le=5)

    def require_database_url(self) -> str:
        if not self.database_url.strip():
            raise ValueError("DATABASE_URL is required for real MAF storage.")
        return self.database_url

    @property
    def foundry_configured(self) -> bool:
        return bool(self.foundry_project_endpoint and self.foundry_model)


@lru_cache
def get_settings() -> Settings:
    return Settings()
