from __future__ import annotations

import pytest
from maf_double_charge.config import Settings
from maf_double_charge.model_client import FakeModelClient
from maf_double_charge.orchestrator import DoubleChargeOrchestrator
from maf_double_charge.repository import InMemoryRepository


@pytest.fixture
async def repository() -> InMemoryRepository:
    value = InMemoryRepository()
    await value.initialize()
    return value


@pytest.fixture
def model() -> FakeModelClient:
    return FakeModelClient()


@pytest.fixture
def settings() -> Settings:
    return Settings(
        foundry_project_endpoint=None,
        foundry_model=None,
        max_tool_attempts=3,
    )


@pytest.fixture
def orchestrator(
    repository: InMemoryRepository,
    model: FakeModelClient,
    settings: Settings,
) -> DoubleChargeOrchestrator:
    return DoubleChargeOrchestrator(repository, model, settings)

