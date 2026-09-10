from __future__ import annotations

import argparse
import os
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


def json_request(client: httpx.Client, method: str, path: str, **kwargs):
    response = client.request(method, path, **kwargs)
    response.raise_for_status()
    return response.json()


def check_scenario(client: httpx.Client, scenario: str, decision: str | None, terminal: str):
    identifier = f"maf-release-{uuid4().hex}"
    started = json_request(
        client,
        "POST",
        "/api/cases",
        json={
            "complaint": "Please investigate two captured charges for a single purchase.",
            "customer_id": identifier,
            "scenario_id": scenario,
            "existing_case_id": identifier,
            "idempotency_key": identifier,
        },
    )
    run_id = started["run_id"]
    if decision:
        assert started["status"] == "paused" and started["approval_required"]
        checkpoint = started["checkpoint_id"]
        assert checkpoint
        json_request(
            client,
            "POST",
            f"/api/runs/{run_id}/approval",
            json={"checkpoint_id": checkpoint, "decision": decision, "reviewer_id": identifier},
        )
        state = json_request(client, "GET", f"/api/runs/{run_id}")
        assert state["state"]["status"] == "paused", "Approval must not implicitly resume"
        json_request(
            client,
            "POST",
            f"/api/runs/{run_id}/resume",
            json={"checkpoint_id": checkpoint},
        )
    outcome = json_request(client, "GET", f"/api/runs/{run_id}/outcome")
    events = json_request(client, "GET", f"/api/runs/{run_id}/events")
    assert outcome["terminal_status"] == terminal
    if terminal == "completed_refunded":
        assert outcome["refund_id"] and outcome["refund_status"] == "verified"
        repeated = client.post(
            f"/api/runs/{run_id}/resume",
            json={"checkpoint_id": started["checkpoint_id"]},
        )
        assert repeated.status_code == 409, "A terminal run must reject duplicate resume"
        repeated_outcome = json_request(client, "GET", f"/api/runs/{run_id}/outcome")
        assert repeated_outcome["refund_id"] == outcome["refund_id"]
    if scenario == "retry-safe-refund":
        assert sum(event["event_type"] == "tool.call.retried" for event in events) == 1
    print(f"Passed {scenario} ({decision or 'no approval'}): {terminal}; run_id={run_id}")


def main(*, smoke_only: bool = False) -> None:
    parser = argparse.ArgumentParser(description="Explicit MAF API workflow acceptance checks")
    parser.add_argument("--base-url", default=os.getenv("MAF_BASE_URL", "http://127.0.0.1:8010"))
    args = parser.parse_args()
    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=180) as client:
        for path in ("/health/live", "/health/ready", "/api/scenarios", "/api/workflow/graph"):
            json_request(client, "GET", path)
        for scenario in SCENARIOS[:1] if smoke_only else SCENARIOS:
            check_scenario(client, *scenario)
    print("MAF API smoke passed" if smoke_only else "MAF API E2E passed")


if __name__ == "__main__":
    main()
