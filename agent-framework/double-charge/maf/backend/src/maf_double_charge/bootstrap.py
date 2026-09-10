from __future__ import annotations

import asyncio
from contextlib import AsyncExitStack
from dataclasses import dataclass, field

from .application.ports import ModelClient, Repository
from .application.service import DoubleChargeService
from .config import Settings, get_settings
from .infrastructure.logging import configure_logging
from .infrastructure.persistence.maf_checkpoints import PostgresRunCheckpointStorage
from .infrastructure.persistence.postgres import PostgresRepository
from .infrastructure.simulated_actions import SimulatedActions
from .infrastructure.telemetry import TelemetryHandle, configure_telemetry
from .maf.clients import FoundryModelClient
from .maf.runner import CheckpointStorageFactory, MafWorkflowRunner


@dataclass
class Runtime:
    service: DoubleChargeService
    repository: Repository
    model: ModelClient
    settings: Settings
    host: str = "api"
    _telemetry: TelemetryHandle | None = field(default=None, init=False, repr=False)
    _started: bool = field(default=False, init=False)
    _closed: bool = field(default=False, init=False)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock, init=False, repr=False)

    async def start(self) -> None:
        async with self._lock:
            if self._closed:
                raise RuntimeError("runtime is closed")
            if self._started:
                return
            try:
                configure_logging(self.settings.log_level)
                self._telemetry = configure_telemetry(self.settings, host=self.host)
                await self.repository.initialize()
            except BaseException:
                await self._close_resources()
                raise
            self._started = True

    async def close(self) -> None:
        async with self._lock:
            await self._close_resources()

    async def _close_resources(self) -> None:
        if self._closed:
            return
        self._closed = True
        async with AsyncExitStack() as stack:
            if self._telemetry is not None:
                stack.push_async_callback(asyncio.to_thread, self._telemetry.shutdown)
            stack.push_async_callback(self.repository.close)
            stack.push_async_callback(self.model.close)


def create_runtime(
    settings: Settings | None = None,
    *,
    repository: Repository | None = None,
    model: ModelClient | None = None,
    checkpoint_storage_factory: CheckpointStorageFactory | None = None,
    host: str = "api",
) -> Runtime:
    settings = settings if settings is not None else get_settings()
    if repository is not None and checkpoint_storage_factory is None:
        raise ValueError("an injected repository requires an explicit checkpoint_storage_factory")
    model = model if model is not None else FoundryModelClient(settings)
    repository = (
        repository
        if repository is not None
        else PostgresRepository(settings.database_url, settings.database_schema)
    )
    checkpoint_storage_factory = (
        checkpoint_storage_factory
        if checkpoint_storage_factory is not None
        else PostgresRunCheckpointStorage
    )
    runner = MafWorkflowRunner(
        repository,
        model,
        checkpoint_storage_factory=checkpoint_storage_factory,
        actions_factory=SimulatedActions.for_fixture,
        max_tool_attempts=settings.max_tool_attempts,
    )
    return Runtime(
        service=DoubleChargeService(repository, runner),
        repository=repository,
        model=model,
        settings=settings,
        host=host,
    )
