from unittest.mock import Mock

import pytest
from checkout_recovery_maf import bootstrap
from checkout_recovery_maf.application import CheckoutRecoveryService
from checkout_recovery_maf.config import Settings
from checkout_recovery_maf.infrastructure import InMemoryCaseRepository
from checkout_recovery_maf.main import create_app
from fastapi.testclient import TestClient


@pytest.fixture
def settings():
    return Settings(
        execution_mode="scripted",
        environment="development",
        database_url="configured",
        api_token=None,
    )


@pytest.fixture
def resources(monkeypatch):
    repository = Mock()
    telemetry = Mock()
    monkeypatch.setattr(bootstrap, "PostgresCaseRepository", Mock(return_value=repository))
    monkeypatch.setattr(bootstrap, "configure_api_telemetry", Mock(return_value=telemetry))
    return repository, telemetry


def test_owned_runtime_opens_once_and_closes_once(settings, resources):
    repository, telemetry = resources
    runtime = bootstrap.create_runtime(settings)
    repository.open.assert_not_called()
    bootstrap.configure_api_telemetry.assert_not_called()
    runtime.start()
    runtime.start()
    runtime.close()
    runtime.close()
    repository.open.assert_called_once_with()
    repository.ready.assert_called_once_with()
    repository.close.assert_called_once_with()
    telemetry.force_flush.assert_called_once_with()
    telemetry.shutdown.assert_called_once_with()
    with pytest.raises(RuntimeError, match="runtime is closed"):
        runtime.start()


@pytest.mark.parametrize("failure", ["telemetry", "open", "ready", "not-ready"])
def test_startup_failure_closes_owned_resources(settings, resources, failure):
    repository, telemetry = resources
    if failure == "telemetry":
        bootstrap.configure_api_telemetry.side_effect = RuntimeError("startup failed")
    elif failure == "not-ready":
        repository.ready.return_value = False
    else:
        getattr(repository, failure).side_effect = RuntimeError("startup failed")
    runtime = bootstrap.create_runtime(settings)
    with pytest.raises(RuntimeError):
        runtime.start()
    runtime.close()
    repository.close.assert_called_once_with()
    if failure != "telemetry":
        telemetry.shutdown.assert_called_once_with()


@pytest.mark.parametrize("failure", ["repository", "flush"])
def test_shutdown_failure_still_closes_other_owned_resources(settings, resources, failure):
    repository, telemetry = resources
    runtime = bootstrap.create_runtime(settings)
    runtime.start()
    if failure == "repository":
        repository.close.side_effect = RuntimeError("close failed")
    else:
        telemetry.force_flush.side_effect = RuntimeError("flush failed")
    with pytest.raises(RuntimeError):
        runtime.close()
    runtime.close()
    repository.close.assert_called_once_with()
    telemetry.force_flush.assert_called_once_with()
    telemetry.shutdown.assert_called_once_with()


def test_construction_failure_closes_repository(settings, resources):
    repository, _ = resources
    with pytest.raises(ValueError, match="at least one"):
        bootstrap.create_runtime(settings.model_copy(update={"max_auto_inventory_quantity": 0}))
    repository.open.assert_not_called()
    repository.close.assert_called_once_with()
    bootstrap.configure_api_telemetry.assert_not_called()


def test_injected_service_creates_no_unused_resources(settings, resources, monkeypatch):
    repository, telemetry = resources
    injected_repository = Mock(wraps=InMemoryCaseRepository())
    service = CheckoutRecoveryService(injected_repository)
    investigator = Mock(side_effect=AssertionError("unused investigator"))
    monkeypatch.setattr(bootstrap, "ScriptedInvestigator", investigator)
    app = create_app(settings=settings, service=service)
    bootstrap.PostgresCaseRepository.assert_not_called()
    bootstrap.configure_api_telemetry.assert_not_called()
    with TestClient(app) as client:
        assert app.state.runtime.service is service
        assert client.get("/api/health/ready").status_code == 200
        bootstrap.PostgresCaseRepository.assert_not_called()
        investigator.assert_not_called()
    assert not hasattr(app.state, "runtime")
    repository.open.assert_not_called()
    repository.close.assert_not_called()
    assert "open" not in [call[0] for call in injected_repository.mock_calls]
    assert "close" not in [call[0] for call in injected_repository.mock_calls]
    telemetry.shutdown.assert_called_once_with()


def test_app_factory_defers_runtime_until_lifespan(settings, resources):
    repository, _ = resources
    app = create_app(settings=settings)
    bootstrap.PostgresCaseRepository.assert_not_called()
    with TestClient(app):
        repository.open.assert_called_once_with()
        assert app.state.runtime.service is not None
    repository.close.assert_called_once_with()
    assert not hasattr(app.state, "runtime")


def test_app_startup_failure_clears_state_and_closes_once(settings, resources):
    repository, telemetry = resources
    repository.open.side_effect = RuntimeError("startup failed")
    app = create_app(settings=settings)
    with pytest.raises(RuntimeError, match="startup failed"), TestClient(app):
        pytest.fail("startup should fail")
    assert not hasattr(app.state, "runtime")
    repository.close.assert_called_once_with()
    telemetry.shutdown.assert_called_once_with()


def test_hosted_runtime_has_no_api_telemetry_or_token_requirement(settings, resources):
    repository, telemetry = resources
    runtime = bootstrap.create_runtime(
        settings.model_copy(
            update={
                "execution_mode": "maf",
                "environment": "production",
                "foundry_project_endpoint": "https://example.invalid/project",
                "foundry_model_deployment": "model",
            }
        ),
        host="hosted",
    )
    runtime.start()
    runtime.close()
    bootstrap.configure_api_telemetry.assert_not_called()
    telemetry.shutdown.assert_not_called()
    repository.open.assert_called_once_with()
    repository.close.assert_called_once_with()


def test_development_defaults_to_scripted_without_foundry(monkeypatch):
    monkeypatch.delenv("CHECKOUT_RECOVERY_EXECUTION_MODE", raising=False)
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    settings = Settings(
        foundry_project_endpoint=None,
        foundry_model_deployment=None,
        environment="development",
        database_url=None,
        api_token=None,
    )
    assert settings.execution_mode == "scripted"
    with TestClient(create_app(settings=settings)) as client:
        response = client.post(
            "/api/cases", json={"fixture_id": "recoverable-inventory-reservation"}
        )
        assert response.status_code == 201
        assert response.json()["harness_mode"] == "scripted"


def test_explicit_maf_mode_requires_foundry_configuration():
    settings = Settings(
        execution_mode="maf",
        foundry_project_endpoint=None,
        foundry_model_deployment=None,
        environment="development",
    )
    with pytest.raises(ValueError, match="MAF execution requires"):
        create_app(settings=settings)


@pytest.mark.parametrize(
    ("host", "updates"),
    [
        ("api", {"environment": "production"}),
        ("api", {"execution_mode": "maf"}),
        ("hosted", {}),
        ("hosted", {"execution_mode": "maf", "database_url": None}),
    ],
)
def test_invalid_config_rejected_even_with_service_injected(settings, resources, host, updates):
    with pytest.raises(ValueError):
        bootstrap.create_runtime(
            settings.model_copy(update=updates),
            service=CheckoutRecoveryService(InMemoryCaseRepository()),
            host=host,
        )
    bootstrap.PostgresCaseRepository.assert_not_called()
