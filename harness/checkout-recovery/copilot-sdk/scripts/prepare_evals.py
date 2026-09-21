"""Materialize explicit-command start evaluation rows from the shared business contract."""

import json
from pathlib import Path

from model_to_harness_shared import get_checkout_fixture

ROOT = Path(__file__).resolve().parents[1]
AGENT = ROOT / "infra/foundry-hosted/agent"


def main() -> None:
    rows = []
    for case in json.loads((ROOT / "evals/checkout_recovery_cases.json").read_text()):
        expected = get_checkout_fixture(case["fixture_id"]).expected.model_dump(mode="json")
        expected.update({"phase": "closed", "harness_mode": "copilot"})
        if case["approval_command"] is not None:
            expected = {
                "phase": "waiting_approval",
                "harness_mode": "copilot",
                "approval_decision": "pending",
                "terminal_status": None,
                "verification_result": None,
            }
        rows.append(
            {
                "query": json.dumps({"action": "start", "fixture_id": case["fixture_id"]}),
                "expected_behavior": json.dumps(expected),
            }
        )
    target = AGENT / ".foundry/datasets/checkout-start-contract.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("".join(json.dumps(row) + "\n" for row in rows))
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
