"""Re-read deployed business records; never use an agent's completion claim as evidence."""

import argparse
import json
import os
from pathlib import Path

from checkout_recovery_maf.infrastructure import PostgresCaseRepository
from checkout_recovery_maf.projections import project_case
from model_to_harness_shared import CheckoutSimulator, get_checkout_fixture


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    repository = PostgresCaseRepository(os.environ["CHECKOUT_RECOVERY_DATABASE_URL"])
    repository.open()
    verified = []
    try:
        for path in args.reports:
            for row in json.loads(path.read_text()):
                case_id = row["actual"]["case_id"]
                case = repository.get(case_id)
                assert case is not None, "Expected deployed case is missing"
                actual = project_case(case).model_dump(mode="json")
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
                    session = connection.execute(
                        """SELECT framework_state->'workspace'->>'plan.md' IS NOT NULL AS has_plan
                           FROM checkout_recovery_maf_sessions WHERE case_id = %s""",
                        (case_id,),
                    ).fetchone()
                    assert session and session["has_plan"]
                    if case.approval_request_id:
                        approval = connection.execute(
                            "SELECT decision FROM checkout_recovery_approvals WHERE case_id = %s",
                            (case_id,),
                        ).fetchone()
                        assert approval and approval["decision"] == case.approval_decision.value
                        assert events.count("approval_recorded") == 1
                verified.append({"case_id": case_id, "fixture_id": case.fixture_id, "passed": True})
    finally:
        repository.close()
    args.output.write_text(json.dumps(verified, indent=2) + "\n")
    print(f"PostgreSQL business/audit/intent/session evidence verified: {len(verified)} cases")


if __name__ == "__main__":
    main()
