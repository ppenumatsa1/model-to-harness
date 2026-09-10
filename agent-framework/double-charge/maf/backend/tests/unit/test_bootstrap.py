from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from maf_double_charge import bootstrap
from maf_double_charge.bootstrap import create_runtime
from maf_double_charge.config import Settings
from maf_double_charge.testing.checkpoints import InMemoryRunCheckpointStorage
from maf_double_charge.testing.model import FakeModelClient
from maf_double_charge.testing.repository import InMemoryRepository


def test_injected_storage_requires_explicit_checkpoint_factory(settings: Settings) -> None:
    with pytest.raises(ValueError, match="checkpoint_storage_factory"):
        create_runtime(settings, repository=InMemoryRepository(), model=FakeModelClient())


async def test_runtime_lifecycle_is_explicit_and_idempotent(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = InMemoryRepository()
    repository.initialize = AsyncMock()
    repository.close = AsyncMock()
    model = FakeModelClient()
    model.close = AsyncMock()
    telemetry = MagicMock()
    configure = MagicMock(return_value=telemetry)
    monkeypatch.setattr(bootstrap, "configure_telemetry", configure)
    runtime = create_runtime(
        settings,
        repository=repository,
        model=model,
        checkpoint_storage_factory=InMemoryRunCheckpointStorage,
        host="hosted",
    )
    repository.initialize.assert_not_awaited()
    configure.assert_not_called()
    await runtime.start()
    await runtime.start()
    repository.initialize.assert_awaited_once()
    configure.assert_called_once_with(settings, host="hosted")
    await runtime.close()
    await runtime.close()
    model.close.assert_awaited_once()
    repository.close.assert_awaited_once()
    telemetry.shutdown.assert_called_once()
    with pytest.raises(RuntimeError, match="closed"):
        await runtime.start()


async def test_failed_startup_closes_all_constructed_resources(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = InMemoryRepository()
    repository.initialize = AsyncMock(side_effect=RuntimeError("schema is unavailable"))
    repository.close = AsyncMock()
    model = FakeModelClient()
    model.close = AsyncMock()
    telemetry = MagicMock()
    monkeypatch.setattr(bootstrap, "configure_telemetry", lambda *args, **kwargs: telemetry)
    runtime = create_runtime(
        settings,
        repository=repository,
        model=model,
        checkpoint_storage_factory=InMemoryRunCheckpointStorage,
    )
    with pytest.raises(RuntimeError, match="schema"):
        await runtime.start()
    model.close.assert_awaited_once()
    repository.close.assert_awaited_once()
    telemetry.shutdown.assert_called_once()


async def test_close_attempts_other_resources_after_model_close_failure(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = InMemoryRepository()
    repository.close = AsyncMock()
    model = FakeModelClient()
    model.close = AsyncMock(side_effect=RuntimeError("model close failed"))
    telemetry = MagicMock()
    monkeypatch.setattr(bootstrap, "configure_telemetry", lambda *args, **kwargs: telemetry)
    runtime = create_runtime(
        settings,
        repository=repository,
        model=model,
        checkpoint_storage_factory=InMemoryRunCheckpointStorage,
    )
    await runtime.start()
    with pytest.raises(RuntimeError, match="model close"):
        await runtime.close()
    repository.close.assert_awaited_once()
    telemetry.shutdown.assert_called_once()
