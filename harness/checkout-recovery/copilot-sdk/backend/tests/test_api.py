import hashlib
import json

import pytest
from checkout_recovery_copilot.application import CheckoutRecoveryService
from checkout_recovery_copilot.config import Settings
from checkout_recovery_copilot.infrastructure import InMemoryCaseRepository
from checkout_recovery_copilot.main import create_app
from fastapi.testclient import TestClient


def test_health_and_explicit_commands_have_safe_responses() -> None:
    with TestClient(
        create_app(settings=Settings(_env_file=None, execution_mode="scripted"))
    ) as client:
        assert client.get("/api/health/live").json() == {"status": "live"}
        started = client.post(
            "/api/cases", json={"fixture_id": "captured-payment-approved-remediation"}
        )
        assert started.status_code == 201
        body = started.json()
        assert body["approval_decision"] == "pending"
        assert "operation_id" not in body
        assert "request_fingerprint" not in body
        assert "order_id" not in body

        case_id = body["case_id"]
        approved = client.post(
            f"/api/cases/{case_id}/approval",
            json={
                "decision": "approved",
                "reviewer_id": "reviewer-1",
                "approval_request_id": body["approval_request_id"],
                "reason": "Reviewed",
            },
        )
        assert approved.status_code == 200
        resumed = client.post(f"/api/cases/{case_id}/resume")
        assert resumed.status_code == 200
        assert resumed.json()["terminal_status"] == "recovered"


def test_invalid_approval_and_unknown_case_are_safe_errors() -> None:
    with TestClient(
        create_app(settings=Settings(_env_file=None, execution_mode="scripted"))
    ) as client:
        missing = client.post(
            "/api/cases/missing/approval",
            json={
                "decision": "approved",
                "reviewer_id": "reviewer-1",
                "approval_request_id": "00000000-0000-0000-0000-000000000001",
                "reason": "Reviewed",
            },
        )
        assert missing.status_code == 404
        rejected = client.post(
            "/api/cases",
            json={"fixture_id": "recoverable-inventory-reservation"},
        )
        case_id = rejected.json()["case_id"]
        invalid = client.post(
            f"/api/cases/{case_id}/approval",
            json={
                "decision": "approved",
                "reviewer_id": "reviewer-1",
                "approval_request_id": "00000000-0000-0000-0000-000000000001",
                "reason": "Reviewed",
            },
        )
        assert invalid.status_code == 409


def test_configured_api_token_is_required_for_business_commands() -> None:
    with TestClient(
        create_app(
            settings=Settings(
                _env_file=None, api_token="test-proxy-token", execution_mode="scripted"
            )
        )
    ) as client:
        assert client.get("/api/health/ready").status_code == 200
        assert client.post("/api/cases", json={"fixture_id": "denied-approval"}).status_code == 401
        accepted = client.post(
            "/api/cases",
            json={"fixture_id": "denied-approval"},
            headers={"X-Checkout-Token": "test-proxy-token"},
        )
        assert accepted.status_code == 201


def test_production_refuses_scripted_or_missing_security_configuration() -> None:
    with pytest.raises(ValueError, match="production requires"):
        create_app(settings=Settings(_env_file=None, environment="production"))
    with pytest.raises(ValueError, match="production requires"):
        create_app(
            settings=Settings(
                _env_file=None,
                environment="production",
                database_url="configured",
                api_token="configured",
                execution_mode="scripted",
            )
        )


def test_openapi_preserves_business_contract_apart_from_harness_branding():
    app = create_app(settings=Settings(_env_file=None, execution_mode="scripted"))
    document = app.openapi()
    assert document["info"]["title"] == "Checkout Recovery Copilot Harness"
    document["info"]["title"] = "Checkout Recovery MAF Harness"
    schema = json.dumps(document, sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(schema.encode()).hexdigest() == (
        "e16d83e045dc63c2454acd74577e547da739e5da5d33b7b42c555cef6a5cbd42"
    )


def test_query_and_start_retry_http_contracts():
    with TestClient(
        create_app(settings=Settings(_env_file=None, execution_mode="scripted"))
    ) as client:
        command = {
            "fixture_id": "captured-payment-approved-remediation",
            "request_id": "00000000-0000-0000-0000-000000000123",
        }
        started = client.post("/api/cases", json=command)
        assert started.status_code == 201
        case = started.json()
        case_id = case["case_id"]
        retried = client.post("/api/cases", json=command)
        assert retried.status_code == 201
        assert retried.json() == case
        assert client.get(f"/api/cases/{case_id}").json() == case
        artifact = client.get(f"/api/cases/{case_id}/workspace-artifact")
        assert artifact.status_code == 200
        assert artifact.json() == case["workspace_artifact"]
        events = client.get(f"/api/cases/{case_id}/events")
        assert events.status_code == 200
        assert all(set(event) == {"code", "occurred_at", "summary"} for event in events.json())
        conflict = client.post(
            "/api/cases", json={**command, "fixture_id": "recoverable-inventory-reservation"}
        )
        assert conflict.status_code == 409
        assert conflict.json() == {"detail": "start request conflicts"}
        unknown = client.post("/api/cases", json={"fixture_id": "private-unknown-fixture"})
        assert unknown.status_code == 404
        assert unknown.json() == {"detail": "fixture not found"}
        invalid = client.post("/api/cases", json={"fixture_id": "x", "request_id": "invalid"})
        assert invalid.status_code == 422


@pytest.mark.parametrize("suffix", ["", "/events", "/workspace-artifact"])
def test_missing_query_http_contract(suffix):
    with TestClient(
        create_app(settings=Settings(_env_file=None, execution_mode="scripted"))
    ) as client:
        response = client.get(f"/api/cases/missing{suffix}")
        assert response.status_code == 404
        assert response.json() == {"detail": "case not found"}


def test_auth_contract_covers_queries_docs_and_unknown_routes():
    settings = Settings(_env_file=None, execution_mode="scripted", api_token="test-proxy-token")
    with TestClient(create_app(settings=settings)) as client:
        for path in ["/api/cases/missing", "/openapi.json", "/docs", "/unknown"]:
            rejected = client.get(path, headers={"X-Checkout-Token": "wrong"})
            assert rejected.status_code == 401
            assert rejected.json() == {"detail": "unauthorized"}
        assert client.get("/api/health/live").status_code == 200
        assert client.get("/api/health/ready").status_code == 200
        assert client.get("/api/health/unknown").status_code == 404
        assert (
            client.get(
                "/openapi.json", headers={"X-Checkout-Token": "test-proxy-token"}
            ).status_code
            == 200
        )


def test_readiness_failure_preserves_safe_503(monkeypatch):
    service = CheckoutRecoveryService(InMemoryCaseRepository())
    with TestClient(
        create_app(settings=Settings(_env_file=None, execution_mode="scripted"), service=service)
    ) as client:
        monkeypatch.setattr(service, "ready", lambda: False)
        response = client.get("/api/health/ready")
        assert response.status_code == 503
        assert response.json() == {"detail": "database unavailable"}
