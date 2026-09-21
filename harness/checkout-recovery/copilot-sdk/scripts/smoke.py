"""Verify public frontend proxy health endpoints without mutating workflow state."""

from __future__ import annotations

import argparse
import os

from e2e import request_json


def get_json(base_url: str, path: str) -> dict[str, str]:
    payload = request_json(base_url, "GET", path)
    if payload != {"status": "live"} and payload != {"status": "ready"}:
        raise SystemExit(f"Health check returned an unexpected safe payload for {path}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("CHECKOUT_COPILOT_BASE_URL", "http://127.0.0.1:8030"),
    )
    args = parser.parse_args()
    if get_json(args.base_url, "/api/health/live") != {"status": "live"}:
        raise SystemExit("Live health check failed")
    if get_json(args.base_url, "/api/health/ready") != {"status": "ready"}:
        raise SystemExit("Readiness health check failed")
    print("Public health smoke passed")


if __name__ == "__main__":
    main()
