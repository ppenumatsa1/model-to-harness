import pytest
from checkout_recovery_maf.bootstrap import Settings, create_app
from fastapi.testclient import TestClient


def test_health_and_explicit_commands_have_safe_responses() -> None:
    with TestClient(create_app()) as client:
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
    with TestClient(create_app()) as client:
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
    with TestClient(create_app(settings=Settings(api_token="test-proxy-token"))) as client:
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
        create_app(settings=Settings(environment="production"))
    with pytest.raises(ValueError, match="production requires"):
        create_app(
            settings=Settings(
                environment="production",
                database_url="configured",
                api_token="configured",
                execution_mode="scripted",
            )
        )
