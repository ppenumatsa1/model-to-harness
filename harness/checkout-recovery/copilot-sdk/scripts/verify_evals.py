"""Verify the delivery evaluation dataset against framework-neutral fixtures."""

from __future__ import annotations

import json
import sys
from pathlib import Path

LANE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = LANE_ROOT.parents[2]
sys.path.insert(0, str(REPOSITORY_ROOT / "shared" / "src"))

from model_to_harness_shared import CHECKOUT_SCENARIO_FIXTURES  # noqa: E402


def main() -> None:
    dataset_path = LANE_ROOT / "evals" / "checkout_recovery_cases.json"
    hosted_eval_path = LANE_ROOT / "infra" / "foundry-hosted" / "agent" / "eval.yaml"
    cases = json.loads(dataset_path.read_text())
    if not isinstance(cases, list) or len(cases) != len(CHECKOUT_SCENARIO_FIXTURES):
        raise SystemExit("Evaluation dataset does not cover every checkout fixture")

    expected_ids = set(CHECKOUT_SCENARIO_FIXTURES)
    observed_ids = {item.get("fixture_id") for item in cases if isinstance(item, dict)}
    if observed_ids != expected_ids:
        raise SystemExit("Evaluation fixture IDs differ from the shared contract")
    for item in cases:
        fixture = CHECKOUT_SCENARIO_FIXTURES[item["fixture_id"]]
        expected = fixture.expected
        decision = item["approval_command"]
        if decision != (
            fixture.approval.decision.value
            if fixture.approval.decision.value in {"approved", "denied"}
            else None
        ):
            raise SystemExit(f"Approval contract differs for {fixture.fixture_id}")
        if item["expected_terminal_status"] != expected.terminal_status.value:
            raise SystemExit(f"Terminal-state contract differs for {fixture.fixture_id}")

    if (
        "local_uri: .foundry/datasets/checkout-start-contract.jsonl"
        not in hosted_eval_path.read_text()
    ):
        raise SystemExit("Hosted eval configuration does not reference the start-contract dataset")
    dataset = hosted_eval_path.parent / ".foundry/datasets/checkout-start-contract.jsonl"
    rows = [json.loads(line) for line in dataset.read_text().splitlines()]
    if len(rows) != len(cases):
        raise SystemExit("Hosted start dataset does not cover every fixture")
    for case, row in zip(cases, rows, strict=True):
        query = json.loads(row["query"])
        if query != {"action": "start", "fixture_id": case["fixture_id"]}:
            raise SystemExit("Hosted dataset must contain explicit start commands only")
        expected = json.loads(row["expected_behavior"])
        if case["approval_command"] is not None:
            if expected != {
                "phase": "waiting_approval",
                "harness_mode": "copilot",
                "approval_decision": "pending",
                "terminal_status": None,
                "verification_result": None,
            }:
                raise SystemExit("Hosted start evaluation must not implicitly approve or resume")
        else:
            fixture = CHECKOUT_SCENARIO_FIXTURES[case["fixture_id"]]
            outcome = fixture.expected.model_dump(mode="json")
            if expected != {**outcome, "phase": "closed", "harness_mode": "copilot"}:
                raise SystemExit("Hosted start outcome differs from the shared fixture")
    print("Evaluation contract verified")


if __name__ == "__main__":
    main()
