"""Re-read deployed business records; never use an agent's completion claim as evidence."""

import argparse
import json
import os
from pathlib import Path

from checkout_recovery_copilot.infrastructure import PostgresCaseRepository
from checkout_recovery_copilot.projections import project_case
from model_to_harness_shared import CheckoutSimulator, get_checkout_fixture


def verify_harness(actual: dict, state: dict | None, expected_harness: str) -> bool:
    """Keep deterministic business auditing separate from native SDK acceptance."""
    if actual.get("harness_mode") != expected_harness:
        raise AssertionError("Persisted harness mode differs from the required audit mode")
    if expected_harness == "scripted":
        return False
    if expected_harness != "copilot":
        raise ValueError("Unsupported business audit harness")
    from checkout_recovery_copilot.sdk import archive

    identifiers = archive.validate(state)
    if state.get("session_id") not in identifiers:
        raise AssertionError("Primary native session is absent from the archive")
    files = state["sessions"][state["session_id"]]
    if not all(files.get(name) for name in ("events.jsonl", "workspace.yaml")):
        raise AssertionError("Primary native session lacks nonempty events or workspace files")
    workspace = state.get("workspace")
    plan = workspace.get("plan.md") if isinstance(workspace, dict) else None
    if not isinstance(plan, str) or not plan.strip() or len(plan.encode("utf-8")) > 8192:
        raise AssertionError("Expected persisted Copilot workspace plan is missing or oversized")
    evidence = state.get("evidence", {})
    if not isinstance(evidence, dict) or not all(
        evidence.get(key) is True
        for key in (
            "native_skill_invoked",
            "native_skill_completed",
            "workspace_written",
            "workspace_read",
        )
    ):
        raise AssertionError("Expected observed native skill and workspace evidence is missing")
    completed = evidence.get("native_tools_completed")
    required = {"skill", "read_order", "read_payment", "read_inventory", "write_plan", "read_plan"}
    if (
        not isinstance(completed, list)
        or not all(isinstance(name, str) for name in completed)
        or not required <= set(completed)
    ):
        raise AssertionError("Required native tool completions are missing")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--expected-harness",
        choices=("copilot", "scripted"),
        default="copilot",
        help=(
            "Default requires native Copilot evidence; scripted is local deterministic audit only."
        ),
    )
    args = parser.parse_args()
    repository = PostgresCaseRepository(os.environ["CHECKOUT_COPILOT_DATABASE_URL"])
    repository.open()
    verified = []
    try:
        for path in args.reports:
            for row in json.loads(path.read_text()):
                assert row.get("passed") is True, "Only accepted command results may be audited"
                case_id = row["actual"]["case_id"]
                case = repository.get(case_id)
                assert case is not None, "Expected deployed case is missing"
                actual = project_case(case).model_dump(mode="json")
                assert row["actual"].get("harness_mode") == args.expected_harness, (
                    "Reported harness mode differs from the required audit mode"
                )
                native_verified = verify_harness(
                    actual, repository.framework_state_for(case_id), args.expected_harness
                )
                expected = get_checkout_fixture(case.fixture_id).expected.model_dump(mode="json")
                assert all(actual[key] == value for key, value in expected.items())
                events = [event.code.value for event in repository.events_for(case_id)]
                assert events.count("case_started") == 1
                assert events.count("case_closed") == 1
                if case.verification is not None:
                    intent = repository.remediation_intent_for(case_id)
                    assert intent is not None
                    simulator = CheckoutSimulator.from_snapshot(case.simulator_snapshot)
                    evidence = case.verification.evidence
                    rechecked = simulator.verify(
                        operation_id=intent.operation_id,
                        expected_order_status=evidence.expected_order_status,
                        expected_payment_status=evidence.expected_payment_status,
                        expected_reservation_status=evidence.expected_reservation_status,
                        expected_remediation_status=evidence.expected_remediation_status,
                    )
                    assert rechecked == case.verification
                    assert len(simulator.remediation_results) == 1
                    assert events.count("remediation_completed") == 1
                with repository.connection() as connection:
                    if case.approval_request_id:
                        approval = connection.execute(
                            "SELECT decision FROM checkout_recovery_approvals WHERE case_id = %s",
                            (case_id,),
                        ).fetchone()
                        assert approval and approval["decision"] == case.approval_decision.value
                        assert events.count("approval_recorded") == 1
                verified.append(
                    {
                        "case_id": case_id,
                        "fixture_id": case.fixture_id,
                        "harness_mode": args.expected_harness,
                        "native_state_verified": native_verified,
                        "passed": True,
                    }
                )
    finally:
        repository.close()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    with os.fdopen(os.open(args.output, flags, 0o600), "w") as stream:
        json.dump(verified, stream, indent=2)
        stream.write("\n")
    print(
        f"PostgreSQL {args.expected_harness} business/audit/intent evidence verified: "
        f"{len(verified)} cases; native_state_verified={args.expected_harness == 'copilot'}"
    )


if __name__ == "__main__":
    main()
