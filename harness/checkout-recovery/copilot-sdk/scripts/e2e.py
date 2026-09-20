"""Exercise explicit FastAPI start, approval, and resume commands."""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

LANE_ROOT = Path(__file__).resolve().parents[1]
CONTRACT = LANE_ROOT / "evals" / "checkout_recovery_cases.json"


def request_json(
    base_url: str, method: str, path: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    data = json.dumps(body).encode() if body is not None else None
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            **(
                {"X-Checkout-Token": os.environ["CHECKOUT_COPILOT_API_TOKEN"]}
                if os.getenv("CHECKOUT_COPILOT_API_TOKEN")
                else {}
            ),
            **(
                {
                    "Authorization": "Basic "
                    + base64.b64encode(
                        f"{os.environ['CHECKOUT_UI_USERNAME']}:{os.environ['CHECKOUT_UI_PASSWORD']}".encode()
                    ).decode()
                }
                if os.getenv("CHECKOUT_UI_USERNAME")
                else {}
            ),
        },
    )
    try:
        with urlopen(request, timeout=180) as response:
            result = json.loads(response.read())
    except (HTTPError, URLError, json.JSONDecodeError) as error:
        raise SystemExit(f"Command failed: {method} {path} ({type(error).__name__})") from None
    if not isinstance(result, dict):
        raise SystemExit(f"Command returned a non-object response: {method} {path}")
    return result


def verify_case(
    base_url: str, evaluation_case: dict[str, Any], *, request_fn=None
) -> dict[str, Any]:
    send = request_fn or request_json
    started = send(
        base_url,
        "POST",
        "/api/cases",
        {
            "fixture_id": evaluation_case["fixture_id"],
            "request_id": evaluation_case.get("request_id", str(uuid4())),
        },
    )
    case_id = started.get("case_id")
    if not isinstance(case_id, str):
        raise SystemExit("Start response lacks a safe case identifier")

    decision = evaluation_case["approval_command"]
    result = started
    if decision is not None:
        if result.get("phase") != "waiting_approval":
            raise SystemExit("Approval-required case did not durably pause")
        approved = send(
            base_url,
            "POST",
            f"/api/cases/{case_id}/approval",
            {
                "decision": decision,
                "reviewer_id": "delivery-e2e",
                "approval_request_id": result["approval_request_id"],
                "reason": "Reviewed by E2E",
            },
        )
        if approved.get("phase") != "waiting_approval":
            raise SystemExit("Approval command implicitly resumed the case")
        result = send(base_url, "POST", f"/api/cases/{case_id}/resume")

    if result.get("terminal_status") != evaluation_case["expected_terminal_status"]:
        raise SystemExit(f"Unexpected terminal state for {evaluation_case['fixture_id']}")
    from model_to_harness_shared import get_checkout_fixture

    expected = get_checkout_fixture(evaluation_case["fixture_id"]).expected.model_dump(mode="json")
    for field, value in expected.items():
        if result.get(field) != value:
            raise SystemExit(f"Outcome mismatch for {evaluation_case['fixture_id']}: {field}")
    print(f"Verified {evaluation_case['fixture_id']}")
    return {"fixture_id": evaluation_case["fixture_id"], "passed": True, "actual": result}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("CHECKOUT_COPILOT_BASE_URL", "http://127.0.0.1:8030"),
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-copilot", action="store_true")
    args = parser.parse_args()
    cases = json.loads(CONTRACT.read_text())
    results = []
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        if args.output.exists():
            raise SystemExit("E2E evidence already exists; reconcile it before retrying")

    def save() -> None:
        if args.output:
            with os.fdopen(
                os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w"
            ) as stream:
                json.dump(results, stream, indent=2)
                stream.write("\n")

    for evaluation_case in cases:
        evaluation_case["request_id"] = str(uuid4())
        pending = {
            "fixture_id": evaluation_case["fixture_id"],
            "request_id": evaluation_case["request_id"],
            "passed": False,
        }
        results.append(pending)
        save()
        pending.update(verify_case(args.base_url, evaluation_case))
        save()
    if args.require_copilot and any(row["actual"]["harness_mode"] != "copilot" for row in results):
        for row in results:
            row["passed"] = row["actual"]["harness_mode"] == "copilot"
        save()
        raise SystemExit("E2E requires real Copilot investigation for every fixture")
    print("Explicit-command API E2E passed")


if __name__ == "__main__":
    main()
