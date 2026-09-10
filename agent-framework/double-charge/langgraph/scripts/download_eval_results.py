"""Persist every evaluation row privately and fail on incomplete scoring."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Mapping, Sequence
from typing import Any

from prepare_hosted_eval import AGENT_ROOT, PINS, write_private_json


def summarize_items(items: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = dict.fromkeys(("total", "passed", "failed", "errored", "unscored"), 0)
    expected = {name.removeprefix("builtin.") for name in PINS}
    for item in items:
        counts["total"] += 1
        sample = item.get("sample")
        if (
            item.get("error")
            or (isinstance(sample, Mapping) and sample.get("error"))
            or item.get("status") in {"error", "errored"}
        ):
            counts["errored"] += 1
            continue
        results = item.get("results")
        if not isinstance(results, list) or not results:
            counts["failed" if item.get("status") == "fail" else "unscored"] += 1
            continue
        if not all(isinstance(result, Mapping) for result in results):
            raise ValueError("Evaluation results must contain objects")
        if any(result.get("error") for result in results):
            counts["errored"] += 1
            continue
        decisions: list[bool | None] = []
        scored_names = set()
        for result in results:
            if (
                result.get("metric") == "custom_score"
                and result.get("name")
                and any(
                    other.get("name") == result["name"] and isinstance(other.get("passed"), bool)
                    for other in results
                )
            ):
                continue
            passed = result.get("passed")
            decisions.append(passed if isinstance(passed, bool) else None)
            if isinstance(passed, bool) and isinstance(result.get("name"), str):
                scored_names.add(result["name"].removeprefix("builtin."))
        if item.get("status") == "fail" or False in decisions:
            counts["failed"] += 1
        elif not decisions or None in decisions or scored_names != expected:
            counts["unscored"] += 1
        else:
            counts["passed"] += 1
    return counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-endpoint", required=True)
    parser.add_argument("--eval-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--environment", default="langgraph")
    parser.add_argument("--expected-items", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=900)
    args = parser.parse_args()
    if args.timeout <= 0 or args.expected_items < 1:
        parser.error("Timeout and expected item count must be positive")
    for name in ("eval_id", "run_id", "environment"):
        value = getattr(args, name)
        if not value or any(not (character.isalnum() or character in "_-") for character in value):
            parser.error("Artifact identifiers must contain only letters, digits, '_' or '-'")

    from azure.ai.projects import AIProjectClient
    from azure.core.exceptions import AzureError
    from azure.identity import DefaultAzureCredential
    from openai import OpenAIError

    deadline = time.monotonic() + args.timeout
    try:
        with (
            DefaultAzureCredential(process_timeout=60) as credential,
            AIProjectClient(
                endpoint=args.project_endpoint, credential=credential, retry_total=0
            ) as project,
            project.get_openai_client(max_retries=0, timeout=120) as client,
        ):
            while True:
                run = client.evals.runs.retrieve(run_id=args.run_id, eval_id=args.eval_id)
                if run.status in {"completed", "failed", "canceled", "cancelled"}:
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SystemExit("Evaluation has not reached terminal status; retain its IDs")
                time.sleep(min(30, remaining))
            items = [
                item.model_dump(mode="json")
                for item in client.evals.runs.output_items.list(
                    run_id=args.run_id, eval_id=args.eval_id
                )
            ]
    except (AzureError, OpenAIError) as error:
        raise SystemExit(
            f"Evaluation read failed ({type(error).__name__}); details suppressed"
        ) from None
    counts = summarize_items(items)
    directory = AGENT_ROOT / ".foundry/results" / args.environment / args.eval_id
    directory.mkdir(parents=True, mode=0o700, exist_ok=True)
    output = directory / f"{args.run_id}.json"
    write_private_json(
        output,
        {
            "eval_id": args.eval_id,
            "run_id": args.run_id,
            "status": run.status,
            "counts": counts,
            "run": run.model_dump(mode="json"),
            "items": items,
        },
    )
    print(json.dumps({"status": run.status, "counts": counts, "output": str(output)}))
    if (
        run.status != "completed"
        or counts["total"] != args.expected_items
        or counts["passed"] != counts["total"]
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
