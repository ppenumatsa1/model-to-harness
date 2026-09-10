from contextlib import asynccontextmanager

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from model_to_harness_langgraph import bootstrap
from model_to_harness_langgraph.config import Settings
from model_to_harness_langgraph.testing.audit import InMemoryAuditRepository
from model_to_harness_langgraph.testing.fakes import FakeDomainGateway, FakeModel


@pytest.fixture(autouse=True)
def no_export(monkeypatch):
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)


async def test_injected_resources_are_borrowed_and_never_replaced(monkeypatch):
    async def forbidden(*args, **kwargs):
        raise AssertionError("Injected runtime must not touch production storage")

    monkeypatch.setattr(bootstrap, "setup_storage", forbidden)
    audit, model, saver = InMemoryAuditRepository(), FakeModel(), InMemorySaver()
    async with bootstrap.open_runtime(
        Settings(_env_file=None),
        audit=audit,
        model=model,
        gateway=FakeDomainGateway(),
        checkpointer=saver,
    ) as runtime:
        assert runtime.audit is audit
        assert runtime.service.workflow.model is model
        assert runtime.checkpointer is saver
        await runtime.verify()
    assert await audit.ping()


async def test_partial_audit_open_failure_closes_owned_pool(monkeypatch):
    calls = []

    async def verify(settings, *, verify_only):
        assert verify_only is True
        calls.append("verify")

    class Audit:
        def __init__(self, *args):
            pass

        async def open(self):
            calls.append("open")
            raise RuntimeError("opening failed")

        async def close(self):
            calls.append("close")

    monkeypatch.setattr(bootstrap, "setup_storage", verify)
    monkeypatch.setattr(bootstrap, "PostgresAuditRepository", Audit)
    with pytest.raises(RuntimeError, match="opening failed"):
        async with bootstrap.open_runtime(Settings(_env_file=None)):
            pytest.fail("Startup should fail")
    assert calls == ["verify", "open", "close"]


async def test_model_startup_failure_unwinds_saver_and_audit(monkeypatch, caplog):
    calls = []

    async def verify(settings, *, verify_only):
        assert verify_only

    class Audit:
        def __init__(self, *args):
            pass

        async def open(self):
            calls.append("audit_open")

        async def close(self):
            calls.append("audit_close")

    @asynccontextmanager
    async def saver(*args):
        calls.append("saver_open")
        try:
            yield InMemorySaver()
        finally:
            calls.append("saver_close")

    @asynccontextmanager
    async def model(*args):
        raise RuntimeError("model construction failed SECRET")
        yield  # pragma: no cover

    monkeypatch.setattr(bootstrap, "setup_storage", verify)
    monkeypatch.setattr(bootstrap, "PostgresAuditRepository", Audit)
    monkeypatch.setattr(bootstrap.AsyncPostgresSaver, "from_conn_string", saver)
    monkeypatch.setattr(bootstrap, "open_model", model)
    with pytest.raises(RuntimeError, match="model construction"):
        async with bootstrap.open_runtime(Settings(_env_file=None)):
            pytest.fail("No fake production fallback is permitted")
    assert calls == ["audit_open", "saver_open", "saver_close", "audit_close"]
    failures = [r for r in caplog.records if r.message == "runtime_startup_failed"]
    assert len(failures) == 1
    assert failures[0].error_type == "RuntimeError"
    assert "SECRET" not in caplog.text


def test_imports_do_not_construct_model_or_database_and_defaults_are_fresh():
    import importlib

    settings = Settings(_env_file=None)
    assert settings.langgraph_schema == "langgraph_app_cutover"
    assert settings.langgraph_checkpoint_schema == "langgraph_checkpoints_cutover"
    importlib.import_module("model_to_harness_langgraph.api.app")
    importlib.import_module("model_to_harness_langgraph.projections.hosted_adapter")
    for old in ("app", "audit", "checkpointing", "workflow", "service", "model_adapter"):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(f"model_to_harness_langgraph.{old}")


async def test_real_model_boundary_unwinds_credential_and_http_clients_on_constructor_error(
    monkeypatch,
):
    from model_to_harness_langgraph.infrastructure import model_client

    calls = []

    class AsyncResource:
        def __init__(self, name):
            self.name = name

        async def __aenter__(self):
            calls.append(f"open-{self.name}")
            return self

        async def __aexit__(self, *args):
            calls.append(f"close-{self.name}")

    class SyncClient:
        def __enter__(self):
            calls.append("open-sync")
            return self

        def __exit__(self, *args):
            calls.append("close-sync")

    class SyncCredential:
        def __enter__(self):
            calls.append("open-sync-credential")
            return self

        def __exit__(self, *args):
            calls.append("close-sync-credential")

    def fail_model(**kwargs):
        assert "azure_ad_async_token_provider" in kwargs
        raise RuntimeError("model SDK constructor rejected configuration")

    monkeypatch.setattr(model_client, "DefaultAzureCredential", lambda: AsyncResource("credential"))
    monkeypatch.setattr(model_client, "SyncDefaultAzureCredential", SyncCredential)
    monkeypatch.setattr(model_client.httpx, "Client", SyncClient)
    monkeypatch.setattr(model_client.httpx, "AsyncClient", lambda: AsyncResource("async"))
    monkeypatch.setattr(model_client, "get_bearer_token_provider", lambda *_: object())
    monkeypatch.setattr(model_client, "AzureChatOpenAI", fail_model)
    with pytest.raises(RuntimeError, match="SDK constructor"):
        async with model_client.open_model(
            Settings(
                _env_file=None,
                azure_openai_endpoint="https://example.test",
                azure_openai_deployment="model",
            )
        ):
            pytest.fail("Model construction must fail explicitly")
    assert calls == [
        "open-sync-credential",
        "open-credential",
        "open-sync",
        "open-async",
        "close-async",
        "close-sync",
        "close-credential",
        "close-sync-credential",
    ]
