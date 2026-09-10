from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


def summarize_items(items: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    counts = dict.fromkeys(("total", "passed", "failed", "errored", "unscored"), 0)
    for item in items:
        counts["total"] += 1
        sample = item.get("sample")
        sample_error = sample.get("error") if isinstance(sample, Mapping) else None
        if item.get("error") or sample_error or item.get("status") in {"error", "errored"}:
            counts["errored"] += 1
            continue
        results = item.get("results")
        if not isinstance(results, list) or not results:
            counts["failed" if item.get("status") == "fail" else "unscored"] += 1
            continue
        if not all(isinstance(result, Mapping) for result in results):
            raise ValueError("evaluation results must contain objects")
        if any(result.get("error") for result in results):
            counts["errored"] += 1
            continue
        decisions: list[bool | None] = []
        for result in results:
            passed = result.get("passed")
            if (
                result.get("metric") == "custom_score"
                and result.get("name")
                and any(
                    other.get("name") == result["name"]
                    and isinstance(other.get("passed"), bool)
                    for other in results
                )
            ):
                continue
            decisions.append(passed if isinstance(passed, bool) else None)
        if item.get("status") == "fail" or False in decisions:
            counts["failed"] += 1
        elif not decisions or None in decisions:
            counts["unscored"] += 1
        else:
            counts["passed"] += 1
    return counts


def write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".eval-report-", dir=path.parent) as directory:
        temporary = Path(directory) / "report.json"
        with temporary.open("w", encoding="utf-8") as output:
            temporary.chmod(0o600)
            json.dump(report, output, indent=2, default=str)
            output.write("\n")
        temporary.replace(path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Download every Foundry evaluation result row and report explicit outcomes."
    )
    parser.add_argument(
        "--project-endpoint",
        default=os.getenv("FOUNDRY_PROJECT_ENDPOINT") or os.getenv("AZURE_AI_PROJECT_ENDPOINT"),
    )
    parser.add_argument("--eval-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-items", type=int)
    parser.add_argument("--timeout", type=float, default=900)
    args = parser.parse_args()
    if not args.project_endpoint:
        parser.error("--project-endpoint or FOUNDRY_PROJECT_ENDPOINT is required")
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    if args.expected_items is not None and args.expected_items < 1:
        parser.error("--expected-items must be positive")

    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    deadline = time.monotonic() + args.timeout
    terminal = {"completed", "failed", "canceled", "cancelled"}
    with (
        DefaultAzureCredential() as credential,
        AIProjectClient(endpoint=args.project_endpoint, credential=credential) as project,
        project.get_openai_client() as client,
    ):
        while True:
            run = client.evals.runs.retrieve(run_id=args.run_id, eval_id=args.eval_id)
            if run.status in terminal:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"evaluation run did not complete: {args.run_id}")
            time.sleep(min(15, remaining))
        items = [
            item.model_dump(mode="json")
            for item in client.evals.runs.output_items.list(
                run_id=args.run_id, eval_id=args.eval_id
            )
        ]
    counts = summarize_items(items)
    report = {
        "eval_id": args.eval_id,
        "run_id": args.run_id,
        "status": run.status,
        "report_url": run.report_url,
        "counts": counts,
        "run": run.model_dump(mode="json"),
        "items": items,
    }
    write_report(args.output, report)
    print(json.dumps({"status": run.status, "counts": counts, "output": str(args.output)}))
    expected = args.expected_items
    if (
        run.status != "completed"
        or not items
        or counts["passed"] != counts["total"]
        or (expected is not None and counts["total"] != expected)
    ):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
