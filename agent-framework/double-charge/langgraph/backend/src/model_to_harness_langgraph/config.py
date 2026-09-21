from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def checkout_env_file(module_file: Path | None = None) -> Path | None:
    package = (module_file or Path(__file__)).resolve().parent
    source, backend, lane = package.parent, package.parent.parent, package.parent.parent.parent
    if (
        source.name == "src"
        and backend.name == "backend"
        and lane.name == "langgraph"
        and (lane / "pyproject.toml").is_file()
    ):
        return lane / ".env"
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=checkout_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "local"
    log_level: str = "INFO"
    host: str = Field(default="127.0.0.1", min_length=1)
    port: int = Field(default=8000, ge=1, le=65535)
    database_url: str = Field(default="", repr=False)
    langgraph_schema: str = "langgraph_app_cutover"
    langgraph_checkpoint_schema: str = "langgraph_checkpoints_cutover"
    cors_origins: str = "http://localhost:5173"
    azure_openai_endpoint: str | None = None
    azure_openai_deployment: str | None = None
    azure_openai_api_version: str = "2024-10-21"
    model_temperature: float | None = Field(default=None, ge=0, le=1)
    telemetry_enabled: bool = True
    applicationinsights_connection_string: str = Field(default="", repr=False)
    otel_service_name: str = "model-to-harness-langgraph"
    otel_instrumentation_genai_capture_message_content: str = "false"
    azure_tracing_gen_ai_content_recording_enabled: str = "false"

    def require_storage(self) -> None:
        if not self.database_url.strip():
            raise RuntimeError("DATABASE_URL is required for real storage; no default is selected")

    def require_model(self) -> None:
        if not self.model_ready:
            raise RuntimeError("AZURE_OPENAI_ENDPOINT and AZURE_OPENAI_DEPLOYMENT are required")

    @property
    def allowed_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def model_ready(self) -> bool:
        return bool(
            self.azure_openai_endpoint
            and self.azure_openai_endpoint.strip()
            and self.azure_openai_deployment
            and self.azure_openai_deployment.strip()
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
