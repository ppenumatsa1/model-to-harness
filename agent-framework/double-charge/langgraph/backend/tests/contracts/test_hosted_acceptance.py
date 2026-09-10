from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def harness(monkeypatch):
    lane = Path(__file__).resolve().parents[3]
    monkeypatch.syspath_prepend(str(lane / "scripts"))
    return importlib.import_module("hosted_harness")


def envelope(result, status="completed"):
    return json.dumps(
        {
            "status": status,
            "output": [
                {
                    "type": "message",
                    "content": [{"type": "output_text", "text": json.dumps(result)}],
                }
            ],
        }
    )


def test_parser_preserves_native_case_envelope(harness):
    result = {"ok": True, "case": {"case_id": "case-test", "run_id": "run-test"}, "events": []}
    assert harness.response_result(envelope(result)) == result
    raw = "HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n\r\n"
    raw += "data: " + json.dumps(
        {"type": "response.completed", "response": json.loads(envelope(result))}
    )
    raw += "\r\n\r\ndata: [DONE]\r\n\r\n"
    assert harness.response_result(raw) == result


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "data: [DONE]\n\n",
        "HTTP/1.1 500 Error\n\n{}",
        'data: {"type":"response.failed"}\n\n',
        envelope({"ok": False, "error": {"code": "command_conflict"}}),
        envelope({"ok": True, "case": {"run_id": "run-test"}}),
        envelope(
            {"ok": True, "case": {"case_id": "case-test", "run_id": "run-test"}}, "incomplete"
        ),
        envelope([]),
        "[]",
    ],
)
def test_parser_rejects_success_shaped_failures(harness, raw):
    with pytest.raises(harness.AcceptanceError):
        harness.response_result(raw)


def test_azd_owns_pinned_session_and_stops_on_command_failure(harness):
    class Runner:
        def __init__(self):
            self.calls = []

        def run(self, command):
            self.calls.append(command)
            if "invoke" in command:
                raise harness.ReleaseError("expected command failure")
            return "{}"

    runner = Runner()
    with pytest.raises(harness.ReleaseError):
        harness.invoke(runner, "langgraph", "14", {"action": "start"})
    create, invoke, stop = runner.calls
    assert "--version" in create and "14" in create
    assert "--version" not in invoke and "--new-conversation" in invoke
    session = create[create.index("--session-id") + 1]
    assert session.startswith("langgraph-check-")
    assert session in invoke and session in stop
    assert "delete" not in stop


def test_native_hosted_scenarios_use_case_commands_and_separate_resume(harness):
    commands = []
    current = {}

    def send(command):
        nonlocal current
        commands.append(command)
        if command["action"] == "start":
            scenario, decision, terminal = next(
                item for item in harness.SCENARIOS if item[0] == command["scenario_id"]
            )
            current = {
                "case_id": command["case_id"],
                "run_id": "run-test",
                "status": "paused" if decision else "completed",
                "approval_required": bool(decision),
                "checkpoint_id": "interrupt-test",
                "outcome": None
                if decision
                else {
                    "terminal_status": terminal,
                    "refund_status": "not_requested",
                },
            }
            current["terminal"] = terminal
        elif command["action"] == "resume":
            terminal = current["terminal"]
            current = {
                **current,
                "status": "completed",
                "outcome": {
                    "terminal_status": terminal,
                    "refund_status": (
                        "verified"
                        if terminal == "completed_refunded"
                        else "manual_review"
                        if terminal == "manual_review"
                        else "not_requested"
                    ),
                    "refund_id": "refund-test",
                },
            }
        return {"ok": True, "case": dict(current)}

    harness.run_scenarios(send, "14")
    assert len(commands) == 17
    assert sum(command["action"] == "resume" for command in commands) == 5
    for command in commands:
        assert "existing_case_id" not in command
        assert "run_id" not in command
        if command["action"] == "resume":
            assert set(command) == {"action", "case_id"}
