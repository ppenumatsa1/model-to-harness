from __future__ import annotations

import argparse
import asyncio
import json

from model_to_harness_shared import (
    EVALUATION_CASES,
    EvaluationResult,
    get_fixture,
)
from model_to_harness_shared import (
    ApprovalDecision as SharedApprovalDecision,
)

from .config import Settings
from .model_client import FakeModelClient
from .models import ApprovalCommand, ApprovalDecision, ScenarioInput
from .orchestrator import DoubleChargeOrchestrator
from .repository import InMemoryRepository


async def evaluate() -> list[EvaluationResult]:
    results: list[EvaluationResult] = []
    for case in EVALUATION_CASES:
        fixture = get_fixture(case.fixture_id)
        repository = InMemoryRepository()
        orchestrator = DoubleChargeOrchestrator(
            repository,
            FakeModelClient(),
            Settings(foundry_project_endpoint=None, foundry_model=None),
        )
        source = fixture.scenario_input
        started = await orchestrator.start(
            ScenarioInput(
                complaint=source.complaint_text,
                customer_id=source.customer_id,
                account_id=source.account_id,
                scenario_id=source.fixture_id,
                existing_case_id=source.existing_case_id,
                idempotency_key=source.idempotency_key,
            )
        )
        if started.approval_required and started.checkpoint_id:
            decision = (
                ApprovalDecision.APPROVE
                if fixture.approval_decision == SharedApprovalDecision.APPROVED
                else ApprovalDecision.DENY
            )
            await orchestrator.record_approval(
                started.run_id,
                ApprovalCommand(
                    checkpoint_id=started.checkpoint_id,
                    decision=decision,
                    reviewer_id="evaluation-runner",
                ),
            )
            await orchestrator.resume(started.run_id, started.checkpoint_id)
        outcome = await orchestrator.get_outcome(started.run_id)
        if outcome is None:
            results.append(
                EvaluationResult(
                    case_id=case.case_id,
                    passed=False,
                    mismatches={"outcome": ("terminal outcome", "missing")},
                )
            )
            continue
        mismatches = case.expected.compare(outcome)
        results.append(
            EvaluationResult(
                case_id=case.case_id,
                passed=not mismatches,
                mismatches=mismatches,
            )
        )
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Print machine-readable results")
    args = parser.parse_args()
    results = asyncio.run(evaluate())
    if args.json:
        print(json.dumps([item.model_dump(mode="json") for item in results], indent=2))
    else:
        for item in results:
            print(f"{'PASS' if item.passed else 'FAIL'} {item.case_id} {item.mismatches or ''}")
    if not all(item.passed for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

