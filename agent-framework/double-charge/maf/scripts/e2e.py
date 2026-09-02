from __future__ import annotations

import os

import httpx


def main() -> None:
    base = os.getenv("MAF_BASE_URL", "http://127.0.0.1:8010")
    with httpx.Client(base_url=base, timeout=60) as client:
        started = client.post(
            "/api/cases",
            json={
                "complaint": "Two identical captured charges are on my account.",
                "customer_id": "customer-100",
                "scenario_id": "retry-safe-refund",
            },
        )
        started.raise_for_status()
        run = started.json()
        assert run["status"] == "paused"
        checkpoint = run["checkpoint_id"]
        approval = client.post(
            f"/api/runs/{run['run_id']}/approval",
            json={
                "checkpoint_id": checkpoint,
                "decision": "approve",
                "reviewer_id": "e2e-reviewer",
            },
        )
        approval.raise_for_status()
        resumed = client.post(
            f"/api/runs/{run['run_id']}/resume",
            json={"checkpoint_id": checkpoint},
        )
        resumed.raise_for_status()
        outcome = client.get(f"/api/runs/{run['run_id']}/outcome").json()
        events = client.get(f"/api/runs/{run['run_id']}/events").json()
        assert outcome["terminal_status"] == "completed_refunded"
        assert sum(event["event_type"] == "tool.call.retried" for event in events) == 1
        assert outcome["refund_id"]
    print("MAF API E2E passed")


if __name__ == "__main__":
    main()

