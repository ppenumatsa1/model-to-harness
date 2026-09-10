from __future__ import annotations

import copy
import importlib
import json
import stat
from pathlib import Path

import pytest


@pytest.fixture
def setup(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[3] / "scripts"))
    return importlib.import_module("prepare_hosted_eval")


def test_reviewed_intent_and_unique_native_commands(setup):
    config, rows = setup.load_intent(setup.AGENT_ROOT / "eval.yaml")
    assert config["agent"] == {"name": "model-harness-langgraph"}
    unique = setup.unique_cases(rows)
    assert len(unique) == 4
    assert all("case_id" not in json.loads(row["query"]) for row in rows)
    commands = [json.loads(row["query"]) for row in unique]
    assert len({command["case_id"] for command in commands}) == 4
    assert len({command["idempotency_key"] for command in commands}) == 4
    assert all("existing_case_id" not in command for command in commands)
    definition = setup.group_definition(config, "reviewed-test")
    for criterion in definition["testing_criteria"]:
        assert criterion["evaluator_version"] == setup.PINS[criterion["evaluator_name"]]
        assert criterion["data_mapping"]["response"] == "{{sample.output_items}}"
        parameters = criterion["initialization_parameters"]
        assert parameters["model"] == parameters["deployment_name"]


def test_rejects_missing_duplicate_or_weakened_cases(setup):
    _, rows = setup.load_intent(setup.AGENT_ROOT / "eval.yaml")
    bad = copy.deepcopy(rows)
    bad[2]["expected_terminal_status"] = "completed_refunded"
    for changed in (rows[:2], [rows[0]] * 4, bad):
        with pytest.raises(setup.SetupError):
            setup.validate_cases(changed)


def test_endpoint_is_bound_to_selected_lane_and_version(setup):
    values = {
        "AZURE_ENV_NAME": "langgraph",
        "AGENT_MODEL_HARNESS_LANGGRAPH_NAME": "model-harness-langgraph",
        "AGENT_MODEL_HARNESS_LANGGRAPH_VERSION": "14",
        "FOUNDRY_PROJECT_ENDPOINT": "https://example.services.ai.azure.com/api/projects/langgraph",
    }
    assert setup.selected_endpoint(values, "langgraph", "14") == values["FOUNDRY_PROJECT_ENDPOINT"]
    with pytest.raises(setup.SetupError):
        setup.selected_endpoint(values, "langgraph", "13")
    values["AZURE_AI_PROJECT_ENDPOINT"] = "https://other.services.ai.azure.com/api/projects/other"
    with pytest.raises(setup.SetupError):
        setup.selected_endpoint(values, "langgraph", "14")


def test_private_atomic_artifact_mode(setup, tmp_path):
    target = tmp_path / "request.json"
    target.write_text("{}")
    target.chmod(0o644)
    setup.write_private_json(target, {"safe": True})
    assert json.loads(target.read_text()) == {"safe": True}
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert list(tmp_path.iterdir()) == [target]


def test_all_evaluators_must_score_every_item(setup):
    download = importlib.import_module("download_eval_results")
    passed = {
        "status": "pass",
        "results": [
            {"name": "task_completion", "passed": True},
            {"name": "relevance", "passed": True},
        ],
    }
    null = copy.deepcopy(passed)
    null["results"][1]["passed"] = None
    missing = copy.deepcopy(passed)
    missing["results"].pop()
    failed = copy.deepcopy(passed)
    failed["results"][0]["passed"] = False
    assert download.summarize_items(
        [passed, null, missing, failed, {"sample": {"error": "error"}}]
    ) == {"total": 5, "passed": 1, "failed": 1, "errored": 1, "unscored": 2}
    assert download.summarize_items([])["passed"] == 0


async def test_reviewed_seed_matches_real_native_hosted_dispatch(setup):
    from langgraph.checkpoint.memory import InMemorySaver
    from model_to_harness_langgraph.bootstrap import open_runtime
    from model_to_harness_langgraph.config import Settings
    from model_to_harness_langgraph.infrastructure.domain_gateway import SharedDomainGateway
    from model_to_harness_langgraph.projections.hosted_adapter import (
        dispatch_hosted_command,
        parse_hosted_command,
    )
    from model_to_harness_langgraph.testing.audit import InMemoryAuditRepository
    from model_to_harness_langgraph.testing.fakes import FakeModel

    _, rows = setup.load_intent(setup.AGENT_ROOT / "eval.yaml")
    async with open_runtime(
        Settings(_env_file=None),
        audit=InMemoryAuditRepository(),
        gateway=SharedDomainGateway(),
        model=FakeModel(),
        checkpointer=InMemorySaver(),
    ) as runtime:
        for row in setup.unique_cases(rows):
            result = await dispatch_hosted_command(
                runtime.service, parse_hosted_command(row["query"]), row["id"]
            )
            assert result["ok"] is True
            case = result["case"]
            if row.get("expected_status") is not None:
                assert case["status"] == row["expected_status"]
            if row.get("expected_approval_required"):
                assert case["approval_required"] is True
                assert case["checkpoint_id"]
                assert case["outcome"] is None
            else:
                assert case["outcome"]["terminal_status"] == row["expected_terminal_status"]
                assert case["outcome"]["refund_status"] == row["expected_refund_status"]


async def test_read_only_business_evidence_covers_real_postgres_matrix(setup):
    import os
    from uuid import uuid4

    from model_to_harness_langgraph.bootstrap import open_runtime
    from model_to_harness_langgraph.config import Settings
    from model_to_harness_langgraph.infrastructure.domain_gateway import SharedDomainGateway
    from model_to_harness_langgraph.infrastructure.persistence.migrations import setup_storage
    from model_to_harness_langgraph.projections.hosted_adapter import (
        dispatch_hosted_command,
        parse_hosted_command,
    )
    from model_to_harness_langgraph.testing.fakes import FakeModel
    from psycopg import AsyncConnection, sql

    database = os.getenv("TEST_DATABASE_URL")
    if not database:
        pytest.skip("TEST_DATABASE_URL is required for durable acceptance evidence")
    evidence = importlib.import_module("verify_business_evidence")
    suffix = uuid4().hex[:12]
    schemas = (f"langgraph_app_{suffix}", f"langgraph_checkpoints_{suffix}")
    settings = Settings(
        _env_file=None,
        database_url=database,
        langgraph_schema=schemas[0],
        langgraph_checkpoint_schema=schemas[1],
    )
    rows = []
    try:
        await setup_storage(settings)
        async with open_runtime(
            settings, model=FakeModel(), gateway=SharedDomainGateway()
        ) as runtime:

            async def send(command):
                return await dispatch_hosted_command(
                    runtime.service, parse_hosted_command(json.dumps(command)), suffix
                )

            for scenario, decision, terminal in evidence.SCENARIOS:
                identifier = f"evidence-{uuid4().hex}"
                started = (
                    await send(
                        {
                            "action": "start",
                            "case_id": identifier,
                            "scenario_id": scenario,
                            "customer_id": identifier,
                            "complaint": "Please investigate two captured charges.",
                            "idempotency_key": identifier,
                        }
                    )
                )["case"]
                if decision:
                    await send(
                        {
                            "action": "approval",
                            "case_id": identifier,
                            "checkpoint_id": started["checkpoint_id"],
                            "decision": decision,
                            "reviewer_id": identifier,
                        }
                    )
                    await send({"action": "resume", "case_id": identifier})
                rows.append(
                    {
                        "scenario": scenario,
                        "case_id": identifier,
                        "run_id": started["run_id"],
                        "terminal_status": terminal,
                    }
                )
        await evidence.verify(database, schemas, rows)
    finally:
        async with await AsyncConnection.connect(database, autocommit=True) as connection:
            for schema in schemas:
                await connection.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
                )
