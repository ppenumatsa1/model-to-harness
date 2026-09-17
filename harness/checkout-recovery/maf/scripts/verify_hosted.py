"""Verify a pinned Hosted Agent version with explicit Responses 2.0 commands."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4


class HostedVerificationError(RuntimeError):
    pass


def run_azd(arguments: list[str]) -> str:
    completed = subprocess.run(
        ["azd", *arguments],
        check=False,
        capture_output=True,
        encoding="utf-8",
    )
    if completed.returncode:
        raise HostedVerificationError(
            f"Hosted command failed ({completed.returncode}): "
            f"{completed.stdout.strip()[-2000:]} {completed.stderr.strip()[:1000]}"
        )
    return completed.stdout


def response_result(raw: str) -> dict[str, Any]:
    body = raw.strip().replace("\r\n", "\n")
    if body.startswith("HTTP/"):
        headers, separator, body = body.partition("\n\n")
        status = headers.splitlines()[0].split()
        if not separator or len(status) < 2 or not status[1].startswith("2"):
            raise HostedVerificationError("Hosted response did not return success")
    if body.lstrip().startswith("{"):
        response, end = json.JSONDecoder().raw_decode(body.lstrip())
        trailing = body.lstrip()[end:].strip()
        if trailing and not trailing.startswith("WARNING: A new version of extension "):
            raise HostedVerificationError("Unexpected data after Hosted response")
    else:
        response = None
        for frame in body.split("\n\n"):
            encoded = "\n".join(
                line[5:].lstrip() for line in frame.splitlines() if line.startswith("data:")
            )
            if not encoded or encoded == "[DONE]":
                continue
            event = json.loads(encoded)
            if event.get("type") in {"error", "response.failed", "response.incomplete"}:
                raise HostedVerificationError("Hosted Responses stream failed")
            if event.get("type") == "response.completed":
                response = event.get("response")
        if response is None:
            raise HostedVerificationError("Hosted Responses stream did not complete")
    if response.get("status") != "completed" or response.get("error"):
        raise HostedVerificationError("Hosted response was not completed")
    texts = [
        content["text"]
        for output in response.get("output", [])
        if output.get("type") == "message"
        for content in output.get("content", [])
        if content.get("type") == "output_text" and isinstance(content.get("text"), str)
    ]
    if len(texts) != 1:
        raise HostedVerificationError("Hosted response lacks one structured result")
    result = json.loads(texts[0])
    if not isinstance(result, dict) or result.get("error"):
        raise HostedVerificationError("Hosted command was rejected")
    return result


def invoke(
    environment: str, agent_name: str, version: str, session_id: str, command: dict[str, Any]
) -> dict[str, Any]:
    raw = run_azd(
        [
            "ai",
            "agent",
            "invoke",
            agent_name,
            json.dumps(command, separators=(",", ":")),
            "--environment",
            environment,
            "--session-id",
            session_id,
            "--protocol",
            "responses",
            "--new-conversation",
            "--output",
            "raw",
            "--no-prompt",
        ]
    )
    return response_result(raw)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--agent-name", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--smoke", action="store_true", help="Run only the first scenario.")
    args = parser.parse_args()
    session_id = f"checkout-recovery-verify-{uuid4().hex}"
    try:
        run_azd(
            [
                "ai",
                "agent",
                "sessions",
                "create",
                "--environment",
                args.environment,
                "--agent-name",
                args.agent_name,
                "--version",
                args.version,
                "--session-id",
                session_id,
                "--output",
                "json",
                "--no-prompt",
            ]
        )
        from model_to_harness_shared import get_checkout_fixture

        contract = Path(__file__).resolve().parents[1] / "evals/checkout_recovery_cases.json"
        results = []
        cases = json.loads(contract.read_text())
        for row in cases[:1] if args.smoke else cases:
            result = invoke(
                args.environment,
                args.agent_name,
                args.version,
                session_id,
                {"action": "start", "fixture_id": row["fixture_id"]},
            )
            case_id = result.get("case_id")
            if not isinstance(case_id, str):
                raise HostedVerificationError("Start lacks a case identifier")
            if row["approval_command"] is not None:
                if result.get("phase") != "waiting_approval":
                    raise HostedVerificationError("Start did not durably pause")
                result = invoke(
                    args.environment,
                    args.agent_name,
                    args.version,
                    session_id,
                    {
                        "action": "approval",
                        "case_id": case_id,
                        "decision": row["approval_command"],
                        "reviewer_id": "hosted-verifier",
                        "approval_request_id": result["approval_request_id"],
                        "reason": "Reviewed by hosted verifier",
                    },
                )
                if result.get("phase") != "waiting_approval":
                    raise HostedVerificationError("Approval implicitly resumed remediation")
                result = invoke(
                    args.environment,
                    args.agent_name,
                    args.version,
                    session_id,
                    {"action": "resume", "case_id": case_id},
                )
            expected = get_checkout_fixture(row["fixture_id"]).expected.model_dump(mode="json")
            for field, value in expected.items():
                if result.get(field) != value:
                    raise HostedVerificationError(f"Outcome mismatch: {row['fixture_id']}: {field}")
            if result.get("harness_mode") != "maf":
                raise HostedVerificationError("Real MAF investigation is required")
            results.append({"fixture_id": row["fixture_id"], "passed": True, "actual": result})
            print(f"Verified hosted {row['fixture_id']}")
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(results, indent=2) + "\n")
        print(
            "Hosted single-scenario smoke passed"
            if args.smoke
            else "Hosted seven-scenario explicit-command E2E passed"
        )
    finally:
        verification_failed = sys.exception() is not None
        try:
            run_azd(
                [
                    "ai",
                    "agent",
                    "sessions",
                    "stop",
                    session_id,
                    "--environment",
                    args.environment,
                    "--agent-name",
                    args.agent_name,
                    "--no-prompt",
                ]
            )
        except HostedVerificationError as error:
            print(f"Owned session cleanup failed: {session_id}: {error}", file=sys.stderr)
            if not verification_failed:
                raise


if __name__ == "__main__":
    main()
