from __future__ import annotations

import pytest
from maf_double_charge.application.service import DoubleChargeService
from maf_double_charge.bootstrap import Runtime, create_runtime
from maf_double_charge.config import Settings
from maf_double_charge.testing.checkpoints import InMemoryRunCheckpointStorage
from maf_double_charge.testing.model import FakeModelClient
from maf_double_charge.testing.repository import InMemoryRepository


@pytest.fixture
def repository() -> InMemoryRepository:
    return InMemoryRepository()


@pytest.fixture
def model() -> FakeModelClient:
    return FakeModelClient()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        foundry_project_endpoint=None,
        foundry_model=None,
        applicationinsights_connection_string=None,
        otel_exporter_otlp_endpoint=None,
        log_level="ERROR",
        max_tool_attempts=3,
    )


@pytest.fixture
async def runtime(
    repository: InMemoryRepository,
    model: FakeModelClient,
    settings: Settings,
):
    value = create_runtime(
        settings,
        repository=repository,
        model=model,
        checkpoint_storage_factory=InMemoryRunCheckpointStorage,
    )
    await value.start()
    try:
        yield value
    finally:
        await value.close()


@pytest.fixture
def service(runtime: Runtime) -> DoubleChargeService:
    return runtime.service
