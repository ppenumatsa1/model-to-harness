from __future__ import annotations

import argparse
import asyncio
import json

from model_to_harness_shared import (
    EVALUATION_CASES,
    EvaluationCase,
    EvaluationResult,
    ScenarioFixture,
    get_fixture,
)
from model_to_harness_shared import (
    ApprovalDecision as SharedApprovalDecision,
)

from .application.commands import ApprovalCommand, ScenarioInput
from .application.models import ApprovalDecision
from .application.service import DoubleChargeService
from .bootstrap import create_runtime
from .config import Settings
from .testing.checkpoints import InMemoryRunCheckpointStorage
from .testing.model import FakeModelClient
from .testing.repository import InMemoryRepository


async def evaluate() -> list[EvaluationResult]:
    results: list[EvaluationResult] = []
    for case in EVALUATION_CASES:
        fixture = get_fixture(case.fixture_id)
        repository = InMemoryRepository()
        runtime = create_runtime(
            Settings(
                foundry_project_endpoint=None,
                foundry_model=None,
                applicationinsights_connection_string=None,
                otel_exporter_otlp_endpoint=None,
            ),
            repository=repository,
            model=FakeModelClient(),
            checkpoint_storage_factory=InMemoryRunCheckpointStorage,
        )
        await runtime.start()
        try:
            result = await evaluate_case(runtime.service, case, fixture)
            results.append(result)
        finally:
            await runtime.close()
    return results


async def evaluate_case(
    service: DoubleChargeService, case: EvaluationCase, fixture: ScenarioFixture
) -> EvaluationResult:
    source = fixture.scenario_input
    started = await service.start(
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
        await service.record_approval(
            started.run_id,
            ApprovalCommand(
                checkpoint_id=started.checkpoint_id,
                decision=decision,
                reviewer_id="evaluation-runner",
            ),
        )
        await service.resume(started.run_id, started.checkpoint_id)
    outcome = await service.get_outcome(started.run_id)
    if outcome is None:
        return EvaluationResult(
            case_id=case.case_id,
            passed=False,
            mismatches={"outcome": ("terminal outcome", "missing")},
        )
    mismatches = case.expected.compare(outcome)
    return EvaluationResult(
        case_id=case.case_id,
        passed=not mismatches,
        mismatches=mismatches,
    )


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
