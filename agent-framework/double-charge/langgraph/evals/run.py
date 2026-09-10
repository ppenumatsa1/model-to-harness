"""Run shared evaluation fixtures against the real LangGraph app in-process."""

import asyncio
import importlib
import json
from typing import Any

from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from model_to_harness_langgraph.api.app import create_app
from model_to_harness_langgraph.config import Settings
from model_to_harness_langgraph.infrastructure.domain_gateway import SharedDomainGateway
from model_to_harness_langgraph.testing.audit import InMemoryAuditRepository


def _shared_cases() -> list[Any]:
    module = importlib.import_module("model_to_harness_shared")
    return list(module.EVALUATION_CASES)


class EvaluationModel:
    async def normalize(self, complaint: str) -> str:
        return complaint.strip()

    async def draft_notification(self, facts: dict[str, str]) -> str:
        return f"Case {facts['case_id']} completed with refund status {facts['refund_status']}."


async def main() -> None:
    failures: list[str] = []
    app = create_app(
        settings=Settings(database_url="unused"),
        audit=InMemoryAuditRepository(),
        gateway=SharedDomainGateway(),
        model=EvaluationModel(),
        checkpointer=InMemorySaver(),
    )
    async with app.router.lifespan_context(app):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://evaluation",
        ) as client:
            for raw_case in _shared_cases():
                case = (
                    raw_case.model_dump(mode="json")
                    if hasattr(raw_case, "model_dump")
                    else raw_case
                )
                shared = importlib.import_module("model_to_harness_shared")
                fixture = shared.get_fixture(case["fixture_id"])
                scenario_input = fixture.scenario_input.model_dump(mode="json")
                response = await client.post(
                    "/api/cases",
                    json={
                        "complaint": scenario_input["complaint_text"],
                        "customer_id": scenario_input["customer_id"],
                        "scenario_id": case["fixture_id"],
                    },
                )
                response.raise_for_status()
                started = response.json()
                if started["status"] == "paused":
                    decision = "deny" if str(fixture.approval_decision) == "denied" else "approve"
                    response = await client.post(
                        f"/api/cases/{started['case_id']}/approval",
                        json={
                            "checkpoint_id": started["checkpoint_id"],
                            "decision": decision,
                            "reviewer_id": "evaluation-runner",
                        },
                    )
                    response.raise_for_status()
                    response = await client.post(f"/api/cases/{started['case_id']}/resume")
                    response.raise_for_status()
                response = await client.get(f"/api/cases/{started['case_id']}")
                response.raise_for_status()
                actual = response.json()["outcome"]
                expected = case["expected"]
                keys = (
                    "duplicate_decision",
                    "policy_decision",
                    "approval_decision",
                    "refund_status",
                    "terminal_status",
                    "failure_code",
                )
                mismatches = [key for key in keys if expected.get(key) != actual.get(key)]
                if mismatches:
                    failures.append(f"{case['fixture_id']}: {', '.join(mismatches)}")
                print(json.dumps({"scenario": case["fixture_id"], "mismatches": mismatches}))
    if failures:
        raise SystemExit("Evaluation failures:\n" + "\n".join(failures))


if __name__ == "__main__":
    asyncio.run(main())
