"""Explicit Responses commands; no chat-based approvals and no raw response artifacts."""

from __future__ import annotations

import argparse
import json
from typing import Any
from uuid import uuid4

from e2e import SCENARIOS
from release import SERVICE, ReleaseError, Runner, active_agent, azd_args


def response_result(raw: str) -> dict[str, Any]:
    """Parse azd --output raw: HTTP status/headers followed by JSON or Responses SSE."""
    body = raw.strip().replace("\r\n", "\n")
    if body.startswith("HTTP/"):
        header, separator, body = body.partition("\n\n")
        status = header.splitlines()[0].split()
        if not separator or len(status) < 2 or not status[1].startswith("2"):
            raise ReleaseError("Hosted invocation did not return HTTP success")
    if body.lstrip().startswith("{"):
        response = json.loads(body)
    else:
        response = None
        for frame in body.split("\n\n"):
            data = "\n".join(
                line[5:].lstrip() for line in frame.splitlines() if line.startswith("data:")
            )
            if not data or data == "[DONE]":
                continue
            event = json.loads(data)
            if event.get("type") in {"error", "response.failed", "response.incomplete"}:
                raise ReleaseError("Hosted Responses stream failed or was incomplete")
            if event.get("type") == "response.completed":
                response = event.get("response")
        if response is None:
            raise ReleaseError("Hosted stream lacks a completed response")
    if response.get("status") != "completed" or response.get("error"):
        raise ReleaseError("Hosted response is not completed successfully")
    texts = [
        content["text"]
        for output in response.get("output", [])
        if output.get("type") == "message"
        for content in output.get("content", [])
        if content.get("type") == "output_text" and isinstance(content.get("text"), str)
    ]
    if len(texts) != 1:
        raise ReleaseError("Expected one structured hosted command result")
    result = json.loads(texts[0])
    if not isinstance(result, dict) or not result.get("run_id"):
        raise ReleaseError("Hosted result lacks a workflow run ID")
    return result


def invoke(runner: Runner, environment: str, version: str, command: dict[str, Any]):
    session_id = f"maf-check-{uuid4().hex}"
    try:
        runner.run(
            azd_args(
                environment,
                "ai",
                "agent",
                "sessions",
                "create",
                "--agent-name",
                SERVICE,
                "--version",
                version,
                "--session-id",
                session_id,
                "--output",
                "json",
            )
        )
        raw = runner.run(
            azd_args(
                environment,
                "ai",
                "agent",
                "invoke",
                SERVICE,
                json.dumps(command),
                "--protocol",
                "responses",
                "--version",
                version,
                "--session-id",
                session_id,
                "--new-conversation",
                "--output",
                "raw",
            )
        )
        return response_result(raw)
    finally:
        try:
            runner.run(
                azd_args(
                    environment,
                    "ai",
                    "agent",
                    "sessions",
                    "stop",
                    session_id,
                    "--agent-name",
                    SERVICE,
                    "--no-prompt",
                )
            )
        except ReleaseError as error:
            raise ReleaseError(f"Failed to stop owned hosted session {session_id}") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", default="maf-dev")
    parser.add_argument(
        "--version", required=True, help="Actual active version returned after deploy"
    )
    parser.add_argument("--smoke", action="store_true", help="Only check no-duplicate")
    args = parser.parse_args()
    runner = Runner()
    actual = active_agent(
        runner.json(azd_args(args.environment, "ai", "agent", "show", SERVICE, "--output", "json"))
    )
    if actual != args.version:
        raise SystemExit("Requested version does not match the active deployment")
    for scenario, decision, terminal in SCENARIOS[:1] if args.smoke else SCENARIOS:
        identifier = f"maf-hosted-{uuid4().hex}"
        result = invoke(
            runner,
            args.environment,
            args.version,
            {
                "action": "start",
                "scenario_id": scenario,
                "complaint": "Please investigate two captured charges for one purchase.",
                "customer_id": identifier,
                "existing_case_id": identifier,
                "idempotency_key": identifier,
            },
        )
        if decision:
            assert result["status"] == "paused" and result["approval_required"]
            assert result["refund_status"] == "not_requested"
            command = {"run_id": result["run_id"], "checkpoint_id": result["checkpoint_id"]}
            recorded = invoke(
                runner,
                args.environment,
                args.version,
                {
                    **command,
                    "action": "approval",
                    "decision": decision,
                    "reviewer_id": identifier,
                },
            )
            assert recorded["status"] == "paused" and recorded["refund_status"] == "not_requested"
            result = invoke(runner, args.environment, args.version, {**command, "action": "resume"})
            if terminal == "completed_refunded":
                assert result["outcome"]["refund_id"]
                assert result["refund_status"] == "verified"
        assert result["terminal_status"] == terminal
        if scenario == "retry-safe-refund":
            assert result["retry_count"] == 1
        print(
            json.dumps(
                {
                    "scenario": scenario,
                    "run_id": result["run_id"],
                    "version": args.version,
                    "terminal_status": terminal,
                }
            )
        )
    print("Hosted explicit-command harness passed")


if __name__ == "__main__":
    main()
