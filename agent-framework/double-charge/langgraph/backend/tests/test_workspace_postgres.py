import asyncio
import os
from copy import deepcopy
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from model_to_harness_langgraph.infrastructure.persistence.audit import PostgresAuditRepository
from model_to_harness_langgraph.infrastructure.persistence.migrations import apply_application
from psycopg import AsyncConnection, sql
from psycopg.rows import dict_row

DATABASE = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not DATABASE, reason="Dedicated loopback PostgreSQL required")


@pytest.fixture
async def audit():
    schema = f"lg_workspace_{uuid4().hex[:12]}"
    await apply_application(DATABASE, schema)
    repository = PostgresAuditRepository(DATABASE, schema)
    await repository.open()
    try:
        yield repository
    finally:
        await repository.close()
        async with await AsyncConnection.connect(DATABASE, autocommit=True) as conn:
            await conn.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
            )


async def create_run(audit, suffix="1"):
    await audit.create_run({
        "run_id": f"run-{suffix}", "case_id": f"case-{suffix}", "customer_id": "customer",
        "status": "running", "current_step": "start", "checkpoint_id": None,
        "approval_required": False, "state": {"scenario_id": "duplicate-confirmed"},
        "outcome": None,
    })


async def emit(audit, label, *, run_id="run-1", data=None):
    return await audit.append_event(
        case_id=f"case-{run_id[4:]}", run_id=run_id, event_type=label,
        summary=label, node=None, status=None, data=data, dedupe_key=label,
    )


async def test_committed_sequences_cannot_overtake_blocked_lower_insert(audit):
    await create_run(audit)
    await create_run(audit, "2")
    blocker = 728419
    async with await AsyncConnection.connect(DATABASE, autocommit=True) as setup:
        await setup.execute(
            sql.SQL(
                "CREATE FUNCTION {}.block_first() RETURNS trigger LANGUAGE plpgsql AS $$ "
                "BEGIN IF NEW.event_type='blocked' THEN "
                "PERFORM pg_advisory_xact_lock(728419); END IF; RETURN NEW; END $$"
            ).format(sql.Identifier(audit.schema))
        )
        await setup.execute(
            sql.SQL(
                "CREATE TRIGGER block_first BEFORE INSERT ON {}.events "
                "FOR EACH ROW EXECUTE FUNCTION {}.block_first()"
            ).format(sql.Identifier(audit.schema), sql.Identifier(audit.schema))
        )
    async with await AsyncConnection.connect(DATABASE, autocommit=True) as gate:
        await gate.execute("SELECT pg_advisory_lock(%s)", (blocker,))
        first = asyncio.create_task(emit(audit, "blocked"))
        second = None
        try:
            async with await AsyncConnection.connect(
                DATABASE, autocommit=True, row_factory=dict_row
            ) as probe:
                for _ in range(100):
                    result = await probe.execute(
                        "SELECT count(*) AS waiting FROM pg_locks "
                        "WHERE locktype='advisory' AND objid=%s AND NOT granted",
                        (blocker,),
                    )
                    if (await result.fetchone())["waiting"]:
                        break
                    await asyncio.sleep(0.01)
                else:
                    pytest.fail("First event did not reach the blocked insert")
                second = asyncio.create_task(emit(audit, "parallel", run_id="run-2"))
                await asyncio.sleep(0.05)
                assert not second.done()
                assert await audit.list_events("run-1") == []
                assert await audit.list_events("run-2") == []
                result = await probe.execute(
                    "SELECT pg_sequence_last_value("
                    "pg_get_serial_sequence(%s, 'sequence')) AS value",
                    (f"{audit.schema}.events",),
                )
                assert (await result.fetchone())["value"] == 1
        finally:
            await gate.execute("SELECT pg_advisory_unlock(%s)", (blocker,))
            one = await asyncio.wait_for(first, 5)
            two = await asyncio.wait_for(second, 5) if second else None
        assert two is not None and one.sequence < two.sequence
        assert [event.sequence for event in await audit.list_events("run-2", one.sequence)] == [
            two.sequence
        ]


async def test_duplicate_event_keeps_original_identity_and_terminal_facts(audit):
    await create_run(audit)
    original = await emit(audit, "run_completed", data={
        "terminal_status": "completed", "refund_status": "not_required",
        "notification_status": "not_sent",
    })
    duplicates = await asyncio.gather(*[
        emit(audit, "run_completed", data={"refund_status": "verified", "refund_id": "invented"})
        for _ in range(10)
    ])
    assert all(event == original for event in duplicates)
    assert len(await audit.list_events("run-1")) == 1
    restarted = PostgresAuditRepository(DATABASE, audit.schema)
    await restarted.open()
    try:
        assert await restarted.list_events("run-1") == [original]
    finally:
        await restarted.close()


async def test_complete_keyset_history_and_legacy_read_do_not_mutate_storage(audit):
    for index in range(24):
        await create_run(audit, f"{index:02}")
    timestamp = datetime.now(UTC)
    async with audit.pool.connection() as conn:
        await conn.execute(
            sql.SQL("UPDATE {}.runs SET created_at=%s").format(sql.Identifier(audit.schema)),
            (timestamp,),
        )
        await conn.execute(
            sql.SQL(
                "INSERT INTO {}.approvals "
                "(run_id,checkpoint_id,decision,reviewer_id,reason) "
                "VALUES ('run-00','legacy-checkpoint','approve','legacy-reviewer',NULL)"
            ).format(sql.Identifier(audit.schema))
        )
    first = await audit.list_runs(10)
    assert first[0]["run_id"] == "run-23"
    await create_run(audit, "new")
    second = await audit.list_runs(10, (first[-1]["created_at"], first[-1]["run_id"]))
    third = await audit.list_runs(10, (second[-1]["created_at"], second[-1]["run_id"]))
    assert len({row["run_id"] for row in first + second + third}) == 24
    assert len(third) == 4
    records = await audit.workspace_records("case-00")
    assert records["approval"]["reason"] is None
    assert records["approval"]["reviewer_id"] == "legacy-reviewer"
    assert records["memory"] == {}
    assert (await audit.workspace_records("case-00")) == records
    assert len(await audit.list_runs(100)) == 25


async def test_legacy_native_pause_resumes_without_new_fields_or_fabricated_opener(audit):
    from langgraph.checkpoint.base import create_checkpoint
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from model_to_harness_langgraph.application.records import ResumeRequest
    from model_to_harness_langgraph.application.service import WorkflowService
    from model_to_harness_langgraph.graph.runner import DoubleChargeWorkflow
    from model_to_harness_langgraph.infrastructure.persistence.checkpointing import (
        checkpoint_conninfo,
        ensure_checkpoint_schema,
    )
    from model_to_harness_langgraph.testing.fakes import FakeDomainGateway, FakeModel

    checkpoint_schema = f"lg_legacy_cp_{uuid4().hex[:12]}"
    await create_run(audit)
    legacy_event_id = str(uuid4())
    async with audit.pool.connection() as conn:
        await conn.execute(
            sql.SQL(
                "INSERT INTO {}.events(event_id,case_id,run_id,event_type,summary,data) "
                "VALUES (%s,'case-1','run-1','run_started','Legacy opening action','{{}}'::jsonb)"
            ).format(sql.Identifier(audit.schema)),
            (legacy_event_id,),
        )
    historical_opening = (await audit.list_events("run-1"))[0]
    assert historical_opening.data == {}
    await ensure_checkpoint_schema(DATABASE, checkpoint_schema)
    try:
        async with AsyncPostgresSaver.from_conn_string(
            checkpoint_conninfo(DATABASE, checkpoint_schema)
        ) as saver:
            await saver.setup()
            gateway = FakeDomainGateway()
            preparing = DoubleChargeWorkflow(
                audit=audit, gateway=gateway, model=FakeModel(), checkpointer=saver,
                interrupt_after=["join_validations"],
            )
            await preparing.start({
                "case_id": "case-1", "run_id": "run-1", "customer_id": "customer",
                "complaint": "A fixture-only complaint not retained by the legacy checkpoint.",
                "scenario_id": "duplicate_confirmed", "idempotency_key": "legacy-fixture-refund",
                "current_step": "start", "status": "running", "charges": [], "load_attempts": 0,
                "validation_results": {}, "evidence": [], "refund_attempts": 0,
                "safe_summaries": [], "selected_memory": {},
            })
            original = await saver.aget_tuple(preparing.config("run-1"))
            assert original is not None
            checkpoint = create_checkpoint(
                deepcopy(original.checkpoint), None, original.metadata["step"] + 1
            )
            for field in ("complaint", "operator_id"):
                checkpoint["channel_values"].pop(field, None)
                checkpoint["channel_versions"].pop(field, None)
            # Append a test-owned legacy fixture; the original native checkpoint remains intact.
            await saver.aput(
                original.config, checkpoint,
                {**original.metadata, "step": original.metadata["step"] + 1},
                checkpoint["channel_versions"],
            )
            workflow = DoubleChargeWorkflow(
                audit=audit, gateway=gateway, model=FakeModel(), checkpointer=saver,
            )
            service = WorkflowService(workflow, audit)
            paused = await service.continue_run("case-1")
            assert paused.status == "paused" and paused.checkpoint_id
            native = await workflow.snapshot("run-1")
            assert "complaint" not in native and "operator_id" not in native
            await audit.save_approval("run-1", {
                "checkpoint_id": paused.checkpoint_id, "decision": "approve",
                "reviewer_id": "legacy-reviewer", "reason": None,
            })
            workspace = await service.workspace("case-1")
            assert workspace.can_resume and workspace.state.complaint is None
            assert workspace.approval.reason is None
            result = await service.resume(
                "case-1",
                ResumeRequest(
                    checkpoint_id=paused.checkpoint_id, operator_id="current-resume-operator"
                ),
            )
            assert result.status == "completed"
            assert (await audit.get_approval("run-1"))["reason"] is None
            assert (await audit.get_approval("run-1"))["consumed"] is True
            assert (await service.workspace("case-1")).state.complaint is None
            events = await audit.list_events("run-1")
            assert events[0] == historical_opening
            assert events[0].data == {}
            request = next(e for e in events if e.event_type == "resume_command_recorded")
            assert request.data["actor_id"] == "current-resume-operator"
            resolution = next(e for e in events if e.event_type == "human_approval_resolved")
            assert resolution.data["actor_type"] == "system"
            assert resolution.data["reviewer_id"] == "legacy-reviewer"
            assert resolution.data["reason"] is None
            assert (await saver.aget_tuple(original.config)).checkpoint == original.checkpoint
    finally:
        async with await AsyncConnection.connect(DATABASE, autocommit=True) as conn:
            await conn.execute(
                sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(checkpoint_schema))
            )
