from __future__ import annotations

from fastapi import FastAPI

from ..api.app import create_app
from ..bootstrap import create_runtime
from ..config import Settings
from .checkpoints import InMemoryRunCheckpointStorage
from .model import FakeModelClient
from .repository import InMemoryRepository


def create_test_app() -> FastAPI:
    settings = Settings(
        foundry_project_endpoint=None,
        foundry_model=None,
        applicationinsights_connection_string=None,
        otel_exporter_otlp_endpoint=None,
    )
    repository = InMemoryRepository()
    runtime = create_runtime(
        settings,
        repository=repository,
        model=FakeModelClient(),
        checkpoint_storage_factory=InMemoryRunCheckpointStorage,
        host="api",
    )
    return create_app(settings=settings, runtime=runtime)
