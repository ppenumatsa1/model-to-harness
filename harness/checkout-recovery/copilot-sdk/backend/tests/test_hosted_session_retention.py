import sys

import pytest
import verify_hosted
from model_to_harness_shared import get_checkout_fixture


@pytest.mark.parametrize("keep", [False, True])
@pytest.mark.parametrize("failed", [False, True])
def test_owned_session_cleanup_is_explicit_without_suppressing_failure(monkeypatch, keep, failed):
    commands = []
    monkeypatch.setattr(verify_hosted, "run_azd", lambda args: commands.append(args) or "{}")
    argv = [
        "verify_hosted.py", "--environment", "test", "--agent-name", "test",
        "--version", "1", "--smoke",
    ]
    if keep:
        argv.append("--keep-session")
    monkeypatch.setattr(sys, "argv", argv)

    def invoke(*args):
        if failed:
            raise verify_hosted.HostedVerificationError("invocation failed")
        command = args[-1]
        expected = get_checkout_fixture(command["fixture_id"]).expected.model_dump(mode="json")
        return {**expected, "case_id": command["request_id"], "harness_mode": "copilot"}

    monkeypatch.setattr(verify_hosted, "invoke", invoke)
    if failed:
        with pytest.raises(verify_hosted.HostedVerificationError, match="invocation failed"):
            verify_hosted.main()
    else:
        verify_hosted.main()
    assert commands[0][:4] == ["ai", "agent", "sessions", "create"]
    stopped = [
        command for command in commands if command[:4] == ["ai", "agent", "sessions", "stop"]
    ]
    assert len(stopped) == (0 if keep else 1)
