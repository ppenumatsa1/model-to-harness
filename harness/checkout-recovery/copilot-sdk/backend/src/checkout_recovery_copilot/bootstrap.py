from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Literal

from opentelemetry.sdk.trace import TracerProvider

from checkout_recovery_copilot.application import CheckoutRecoveryService
from checkout_recovery_copilot.config import Settings
from checkout_recovery_copilot.infrastructure import InMemoryCaseRepository, PostgresCaseRepository
from checkout_recovery_copilot.infrastructure.telemetry import configure_api_telemetry, operation
from checkout_recovery_copilot.sdk.investigation import CopilotInvestigator, ScriptedInvestigator


@dataclass
class Runtime:
    """Synchronous, checkout-owned resources; Hosted owns its SDK telemetry separately."""

    service: CheckoutRecoveryService
    host: Literal["api", "hosted"] = "api"
    _repository: PostgresCaseRepository | None = field(default=None, repr=False)
    _health_check: Callable[[], bool] | None = field(default=None, repr=False)
    _telemetry_connection_string: str | None = field(default=None, repr=False)
    _telemetry_trace_file: Path | None = field(default=None, repr=False)
    _telemetry: TracerProvider | None = field(default=None, init=False, repr=False)
    _started: bool = field(default=False, init=False)
    _closed: bool = field(default=False, init=False)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    def start(self) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("runtime is closed")
            if self._started:
                return
            try:
                if self.host == "api":
                    self._telemetry = configure_api_telemetry(
                        connection_string=self._telemetry_connection_string,
                        trace_file=self._telemetry_trace_file,
                    )
                if self._repository is not None:
                    self._repository.open()
                if not self._ready():
                    raise RuntimeError("database unavailable")
            except BaseException:
                self.close()
                raise
            self._started = True

    def _ready(self) -> bool:
        if self._health_check is not None:
            return self._health_check()
        return self.service.ready()

    def ready(self) -> bool:
        with self._lock:
            return self._started and not self._closed and self._ready()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            with ExitStack() as stack:
                if self._telemetry is not None:
                    stack.callback(self._telemetry.shutdown)
                    stack.callback(self._telemetry.force_flush)
                if self._repository is not None:
                    stack.callback(self._repository.close)


def create_runtime(
    settings: Settings | None = None,
    *,
    service: CheckoutRecoveryService | None = None,
    host: Literal["api", "hosted"] = "api",
) -> Runtime:
    if settings is None:
        settings = Settings(_env_file=None) if host == "hosted" else Settings()
    settings.validate_runtime(host=host)
    if service is not None:
        return Runtime(
            service=service,
            host=host,
            _telemetry_connection_string=settings.applicationinsights_connection_string,
            _telemetry_trace_file=settings.trace_file,
        )
    investigator = (
        CopilotInvestigator(
            settings.foundry_project_endpoint,
            settings.foundry_model_deployment,
            connection_string=settings.applicationinsights_connection_string,
            fixture_content=settings.trace_fixture_content,
            trace_file=settings.trace_file,
        )
        if settings.execution_mode == "copilot"
        else ScriptedInvestigator()
    )
    with ExitStack() as stack:
        repository = (
            PostgresCaseRepository(settings.database_url)
            if settings.database_url
            else InMemoryCaseRepository()
        )
        owned_repository = repository if settings.database_url else None
        if owned_repository is not None:
            stack.callback(owned_repository.close)
        runtime = Runtime(
            service=CheckoutRecoveryService(
                repository,
                max_auto_inventory_quantity=settings.max_auto_inventory_quantity,
                investigator=investigator,
                harness_mode=settings.execution_mode,
                instrumentation=operation,
            ),
            host=host,
            _repository=owned_repository,
            _health_check=repository.ready,
            _telemetry_connection_string=settings.applicationinsights_connection_string,
            _telemetry_trace_file=settings.trace_file,
        )
        stack.pop_all()
        return runtime
