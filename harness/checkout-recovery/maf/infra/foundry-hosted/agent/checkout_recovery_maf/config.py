from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CHECKOUT_RECOVERY_", extra="ignore")

    foundry_project_endpoint: str | None = None
    foundry_model_deployment: str | None = None
    database_url: str | None = None
    max_auto_inventory_quantity: int = 1
    execution_mode: Literal["scripted", "maf"] = "scripted"
    environment: Literal["development", "production"] = "development"
    api_token: str | None = None

    def validate_runtime(self, *, host: Literal["api", "hosted"] = "api") -> None:
        if self.environment == "production" and (
            not self.database_url
            or (host == "api" and not self.api_token)
            or self.execution_mode != "maf"
        ):
            raise ValueError("production requires PostgreSQL, API token, and MAF execution")
        if host == "hosted" and (not self.database_url or self.execution_mode != "maf"):
            raise ValueError("Hosted execution requires PostgreSQL and MAF execution")
        if self.execution_mode == "maf" and (
            not self.foundry_project_endpoint or not self.foundry_model_deployment
        ):
            raise ValueError("MAF execution requires a project endpoint and model deployment")
