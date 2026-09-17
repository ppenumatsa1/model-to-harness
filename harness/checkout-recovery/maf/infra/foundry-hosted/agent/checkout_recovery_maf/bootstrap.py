from contextlib import ExitStack
from dataclasses import dataclass, field
from threading import RLock
from typing import Literal

from opentelemetry.sdk.trace import TracerProvider

from checkout_recovery_maf.application import CheckoutRecoveryService
from checkout_recovery_maf.config import Settings
from checkout_recovery_maf.infrastructure import InMemoryCaseRepository, PostgresCaseRepository
from checkout_recovery_maf.infrastructure.telemetry import configure_api_telemetry
from checkout_recovery_maf.maf.investigation import MafInvestigator, ScriptedInvestigator


@dataclass
class Runtime:
    """Synchronous, checkout-owned resources; Hosted owns its SDK telemetry separately."""

    service: CheckoutRecoveryService
    host: Literal["api", "hosted"] = "api"
    _repository: PostgresCaseRepository | None = field(default=None, repr=False)
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
                    self._telemetry = configure_api_telemetry()
                if self._repository is not None:
                    self._repository.open()
                if not self.service.ready():
                    raise RuntimeError("database unavailable")
            except BaseException:
                self.close()
                raise
            self._started = True

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
    settings = settings if settings is not None else Settings()
    settings.validate_runtime(host=host)
    if service is not None:
        return Runtime(service=service, host=host)
    investigator = (
        MafInvestigator(settings.foundry_project_endpoint, settings.foundry_model_deployment)
        if settings.execution_mode == "maf"
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
            ),
            host=host,
            _repository=owned_repository,
        )
        stack.pop_all()
        return runtime
