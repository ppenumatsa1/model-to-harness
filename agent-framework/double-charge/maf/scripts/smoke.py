from __future__ import annotations

import os

import httpx


def main() -> None:
    base = os.getenv("MAF_BASE_URL", "http://127.0.0.1:8010")
    with httpx.Client(base_url=base, timeout=30) as client:
        assert client.get("/health/live").json()["status"] == "ok"
        response = client.post(
            "/api/cases",
            json={
                "complaint": "I was charged twice for one purchase.",
                "customer_id": "customer-100",
                "scenario_id": "no-duplicate",
            },
        )
        response.raise_for_status()
        started = response.json()
        outcome = client.get(f"/api/runs/{started['run_id']}/outcome")
        outcome.raise_for_status()
        assert outcome.json()["terminal_status"] == "completed_no_refund"
    print("MAF smoke test passed")


if __name__ == "__main__":
    main()

