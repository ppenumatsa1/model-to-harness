from ipaddress import ip_address
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def checkout_env_file(module_path: Path = Path(__file__)) -> Path | None:
    """Discover only the editable checkout lane, independent of the working directory."""
    package = module_path.resolve().parent
    if (
        package.name == "checkout_recovery_copilot"
        and package.parent.name == "src"
        and package.parent.parent.name == "backend"
    ):
        lane = package.parent.parent.parent
        if (
            lane.name == "copilot-sdk"
            and lane.parent.name == "checkout-recovery"
            and (lane / "pyproject.toml").is_file()
        ):
            return lane / ".env"
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CHECKOUT_COPILOT_",
        env_file=checkout_env_file(),
        env_file_encoding="utf-8",
        populate_by_name=True,
        extra="ignore",
    )

    api_host: str = "127.0.0.1"
    api_port: int = Field(default=8030, ge=1, le=65535)
    frontend_origin: str = "http://127.0.0.1:5180"
    foundry_project_endpoint: str | None = None
    foundry_model_deployment: str | None = None
    database_url: str | None = Field(default=None, repr=False)
    trace_fixture_content: bool = False
    trace_file: Path | None = None
    max_auto_inventory_quantity: int = 1
    execution_mode: Literal["scripted", "copilot"] = "scripted"
    environment: Literal["development", "production"] = "development"
    api_token: str | None = Field(default=None, repr=False)
    applicationinsights_connection_string: str | None = Field(
        default=None,
        validation_alias="APPLICATIONINSIGHTS_CONNECTION_STRING",
        repr=False,
    )

    @field_validator("trace_file", mode="before")
    @classmethod
    def empty_trace_file_disables_receipt(cls, value):
        return None if value == "" else value

    @field_validator("api_host")
    @classmethod
    def validate_api_host(cls, value: str) -> str:
        try:
            ip_address(value)
            return value
        except ValueError:
            if (
                value
                and all(
                    label
                    and len(label) <= 63
                    and label[0].isalnum()
                    and label[-1].isalnum()
                    and all(
                        character.isascii() and (character.isalnum() or character == "-")
                        for character in label
                    )
                    for label in value.split(".")
                )
                and len(value) <= 253
            ):
                return value
        raise ValueError("API host must be an IP address or hostname, without a scheme or port")

    @field_validator("frontend_origin")
    @classmethod
    def validate_frontend_origin(cls, value: str) -> str:
        try:
            origin = urlsplit(value)
            port = origin.port
            valid = (
                origin.scheme in {"http", "https"}
                and origin.hostname
                and origin.username is None
                and origin.password is None
                and origin.path in {"", "/"}
                and not origin.query
                and not origin.fragment
                and (port is None or 1 <= port <= 65535)
                and not any(character.isspace() for character in value)
                and "\\" not in value
                and "?" not in value
                and "#" not in value
            )
            if valid:
                cls.validate_api_host(origin.hostname)
                return value.rstrip("/")
        except ValueError:
            pass
        raise ValueError("frontend origin must be an HTTP(S) origin without credentials or a path")

    def validate_runtime(self, *, host: Literal["api", "hosted"] = "api") -> None:
        if self.environment == "production" and self.trace_file is not None:
            raise ValueError("local trace files are not permitted in production")
        if self.environment == "production" and (
            not self.database_url
            or (host == "api" and not self.api_token)
            or self.execution_mode != "copilot"
        ):
            raise ValueError("production requires PostgreSQL, API token, and Copilot execution")
        if host == "hosted" and (not self.database_url or self.execution_mode != "copilot"):
            raise ValueError("Hosted execution requires PostgreSQL and Copilot execution")
        if self.execution_mode == "copilot" and (
            not self.foundry_project_endpoint or not self.foundry_model_deployment
        ):
            raise ValueError("Copilot execution requires a project endpoint and model deployment")
