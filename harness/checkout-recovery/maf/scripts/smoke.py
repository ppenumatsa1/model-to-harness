"""Verify public frontend proxy health endpoints without mutating workflow state."""

from __future__ import annotations

import argparse
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def get_json(base_url: str, path: str) -> dict[str, str]:
    request = Request(f"{base_url.rstrip('/')}{path}", method="GET")
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read())
    except (HTTPError, URLError, json.JSONDecodeError) as error:
        raise SystemExit(f"Health check failed for {path}: {type(error).__name__}") from None
    if payload != {"status": "live"} and payload != {"status": "ready"}:
        raise SystemExit(f"Health check returned an unexpected safe payload for {path}")
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=os.getenv("CHECKOUT_RECOVERY_BASE_URL", "http://127.0.0.1:8000"),
    )
    args = parser.parse_args()
    if get_json(args.base_url, "/api/health/live") != {"status": "live"}:
        raise SystemExit("Live health check failed")
    if get_json(args.base_url, "/api/health/ready") != {"status": "ready"}:
        raise SystemExit("Readiness health check failed")
    print("Public health smoke passed")


if __name__ == "__main__":
    main()
