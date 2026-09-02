from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_env: str = "local"
    log_level: str = "INFO"
    database_url: str = (
        "postgresql://model_to_harness:local-development-only"
        "@localhost:5432/model_to_harness"
    )
    langgraph_schema: str = "langgraph_app"
    langgraph_checkpoint_schema: str = "langgraph_checkpoints"
    cors_origins: str = "http://localhost:5173"
    azure_openai_endpoint: str | None = None
    azure_openai_deployment: str | None = None
    azure_openai_api_version: str = "2024-10-21"
    model_temperature: float | None = Field(default=None, ge=0, le=1)

    @property
    def allowed_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def model_ready(self) -> bool:
        return bool(self.azure_openai_endpoint and self.azure_openai_deployment)


@lru_cache
def get_settings() -> Settings:
    return Settings()
