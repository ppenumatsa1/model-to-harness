"""Wait for an existing Foundry evaluation and inspect every output item."""

import argparse
import importlib.util
import json
import time
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.identity import DefaultAzureCredential

ROOT = Path(__file__).resolve().parents[1]


def accepted_scores(results: list[dict[str, object]]) -> bool:
    return bool(results) and all(
        result.get("passed") is True
        and type(result.get("score")) in (int, float)
        and result["score"] == 1
        for result in results
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-endpoint", required=True)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--eval-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--expected-items", type=int, default=7)
    parser.add_argument("--show-definition", action="store_true")
    args = parser.parse_args()
    with (
        DefaultAzureCredential() as credential,
        AIProjectClient(endpoint=args.project_endpoint, credential=credential) as project,
        project.get_openai_client() as client,
    ):
        if args.show_definition:
            definition = client.evals.retrieve(args.eval_id)
            print(definition.model_dump_json(indent=2))
        deadline = time.monotonic() + 900
        while True:
            run = client.evals.runs.retrieve(run_id=args.run_id, eval_id=args.eval_id)
            if run.status.lower() in {"completed", "failed", "cancelled"}:
                break
            if time.monotonic() >= deadline:
                raise SystemExit("Evaluation still running after 15 minutes; retain its IDs")
            time.sleep(30)
        rows = [
            row.model_dump(mode="json")
            for row in client.evals.runs.output_items.list(run_id=args.run_id, eval_id=args.eval_id)
        ]
    target = (
        ROOT
        / "infra/foundry-hosted/agent/.foundry/results"
        / args.environment
        / args.eval_id
        / f"{args.run_id}.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"run": run.model_dump(mode="json"), "items": rows}, indent=2))
    passed = 0
    spec = importlib.util.spec_from_file_location(
        "checkout_contract", ROOT / "evals/start_contract.py"
    )
    contract = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(contract)
    for index, row in enumerate(rows):
        results = row.get("results", [])
        data = row.get("datasource_item", {})
        exact = contract.grade({}, {**data, "response": data.get("sample.output_text")}) == 1
        successful = accepted_scores(results) and exact
        passed += successful
        print(
            json.dumps(
                {"item": index, "passed": successful, "exact_contract": exact, "results": results}
            )
        )
    print(f"Evaluation {run.status}: {passed}/{len(rows)} passed; evidence: {target}")
    if run.status.lower() != "completed" or passed != args.expected_items or len(rows) != passed:
        raise SystemExit("Evaluation acceptance failed; inspect persisted output items")


if __name__ == "__main__":
    main()
