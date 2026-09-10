"""Exercise explicit LangGraph commands without changing deployed storage."""

from __future__ import annotations

import argparse
import json
from uuid import uuid4

import httpx

SCENARIOS = (
    ("no-duplicate", None, "completed_no_refund"),
    ("duplicate-confirmed", "approve", "completed_refunded"),
    ("approval-denied", "deny", "closed_denied"),
    ("retry-safe-refund", "approve", "completed_refunded"),
    ("resumed-approval", "approve", "completed_refunded"),
    ("transient-failure", None, "failed"),
    ("verification-mismatch", "approve", "manual_review"),
)


class AcceptanceError(RuntimeError):
    """A public acceptance failure that does not include raw request/response data."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AcceptanceError(message)


def verify_outcome(outcome: object, terminal: str) -> None:
    if not isinstance(outcome, dict):
        raise AcceptanceError("Command did not persist an outcome")
    require(outcome.get("terminal_status") == terminal, "Unexpected terminal outcome")
    if terminal == "completed_refunded":
        require(outcome.get("refund_status") == "verified", "Refund was not verified")
        require(bool(outcome.get("refund_id")), "Verified refund has no identifier")
    elif terminal in {"completed_no_refund", "closed_denied", "failed"}:
        require(outcome.get("refund_status") == "not_requested", "Unexpected refund side effect")
    elif terminal == "manual_review":
        require(
            outcome.get("refund_status") == "manual_review",
            "Verification mismatch was not surfaced",
        )


def request(client: httpx.Client, method: str, path: str, **kwargs):
    response = client.request(method, path, **kwargs)
    if not response.is_success:
        raise AcceptanceError(f"{method} command failed with HTTP {response.status_code}")
    try:
        return response.json()
    except ValueError:
        raise AcceptanceError("API returned invalid JSON") from None


def check_scenario(client: httpx.Client, scenario: str, decision: str | None, terminal: str):
    identifier = f"langgraph-check-{uuid4().hex}"
    started = request(
        client,
        "POST",
        "/api/cases",
        json={
            "complaint": "Please investigate two captured charges for one purchase.",
            "customer_id": identifier,
            "scenario_id": scenario,
            "existing_case_id": identifier,
            "idempotency_key": identifier,
        },
    )
    require(isinstance(started, dict), "Start did not return a case")
    case_id, run_id = started.get("case_id"), started.get("run_id")
    require(case_id == identifier and bool(run_id), "Start returned unexpected case identity")
    if decision:
        require(started.get("status") == "paused", "Approval scenario did not pause")
        require(started.get("approval_required") is True, "Approval requirement missing")
        checkpoint = started.get("checkpoint_id")
        require(bool(checkpoint), "Approval pause has no checkpoint identifier")
        request(
            client,
            "POST",
            f"/api/cases/{case_id}/approval",
            json={"checkpoint_id": checkpoint, "decision": decision, "reviewer_id": identifier},
        )
        recorded = request(client, "GET", f"/api/cases/{case_id}")
        require(recorded.get("status") == "paused", "Approval implicitly resumed execution")
        require(
            recorded.get("outcome") is None,
            "Approval pause must not have a terminal outcome",
        )
        require(
            isinstance(recorded.get("workflow_state"), dict)
            and recorded["workflow_state"].get("refund_status") in {None, "not_requested"}
            and not recorded["workflow_state"].get("refund_id"),
            "Refund occurred before explicit resume",
        )
        request(client, "POST", f"/api/cases/{case_id}/resume")
    finished = request(client, "GET", f"/api/cases/{case_id}")
    require(finished.get("run_id") == run_id, "Resume changed the durable run identity")
    verify_outcome(finished.get("outcome"), terminal)
    if terminal == "completed_refunded":
        repeated = client.post(f"/api/cases/{case_id}/resume")
        require(repeated.status_code in {200, 409}, "Repeated resume failed unexpectedly")
        after_repeat = request(client, "GET", f"/api/cases/{case_id}")
        require(
            after_repeat.get("outcome") == finished.get("outcome"),
            "Repeated resume changed the terminal outcome",
        )
    summary = {
        "scenario": scenario,
        "case_id": case_id,
        "run_id": run_id,
        "terminal_status": terminal,
    }
    print(json.dumps(summary), flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    try:
        with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=300) as client:
            for path in ("/health", "/ready", "/api/scenarios"):
                request(client, "GET", path)
            for scenario in SCENARIOS[:1] if args.smoke else SCENARIOS:
                check_scenario(client, *scenario)
    except (httpx.HTTPError, AcceptanceError) as error:
        message = str(error) if isinstance(error, AcceptanceError) else type(error).__name__
        raise SystemExit(f"LangGraph API acceptance failed: {message}") from None
    print("LangGraph API smoke passed" if args.smoke else "LangGraph API E2E passed")


if __name__ == "__main__":
    main()
