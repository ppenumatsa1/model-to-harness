import base64
import json
from io import BytesIO

import e2e
import pytest
import smoke


@pytest.mark.parametrize("authenticated", [False, True])
def test_health_smoke_uses_command_transport_auth(monkeypatch, authenticated):
    monkeypatch.delenv("CHECKOUT_UI_USERNAME", raising=False)
    monkeypatch.delenv("CHECKOUT_COPILOT_API_TOKEN", raising=False)
    if authenticated:
        monkeypatch.setenv("CHECKOUT_UI_USERNAME", "test-user")
        monkeypatch.setenv("CHECKOUT_UI_PASSWORD", "test-password")
    seen = []

    def open_request(request, timeout):
        seen.append(request)
        return BytesIO(json.dumps({"status": "ready"}).encode())

    monkeypatch.setattr(e2e, "urlopen", open_request)
    assert smoke.get_json("https://example.test", "/api/health/ready") == {"status": "ready"}
    expected = (
        "Basic " + base64.b64encode(b"test-user:test-password").decode()
        if authenticated else None
    )
    assert seen[0].get_header("Authorization") == expected
