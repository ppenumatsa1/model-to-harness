import os
from contextlib import AsyncExitStack
from uuid import uuid4

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from model_to_harness_langgraph.application.ports import (
    ApprovalCommandConflictError,
    RefundIdempotencyConflictError,
)
from model_to_harness_langgraph.application.records import ApprovalRequest, StartCaseRequest
from model_to_harness_langgraph.application.service import InvalidCommandError, WorkflowService
from model_to_harness_langgraph.bootstrap import open_runtime
from model_to_harness_langgraph.config import Settings
from model_to_harness_langgraph.graph.runner import DoubleChargeWorkflow
from model_to_harness_langgraph.infrastructure.domain_gateway import SharedDomainGateway
from model_to_harness_langgraph.infrastructure.persistence.audit import PostgresAuditRepository
from model_to_harness_langgraph.infrastructure.persistence.checkpointing import (
    checkpoint_conninfo,
    ensure_checkpoint_schema,
)
from model_to_harness_langgraph.infrastructure.persistence.migrations import (
    apply_application,
    setup_storage,
)
from model_to_harness_langgraph.testing.fakes import FakeModel
from psycopg import AsyncConnection, sql

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is required for PostgreSQL integration coverage",
)


async def test_postgres_pause_reconstruct_uncertain_refund_and_schema_isolation():
    assert TEST_DATABASE_URL is not None
    suffix = uuid4().hex[:10]
    app_schema = f"langgraph_app_{suffix}"
    checkpoint_schema = f"langgraph_checkpoints_{suffix}"
    case_id: str | None = None
    run_id: str | None = None

    async with await AsyncConnection.connect(TEST_DATABASE_URL, autocommit=True) as inspection:
        public_before = await _public_checkpoint_tables(inspection)
    assert not public_before

    try:
        audit1 = PostgresAuditRepository(TEST_DATABASE_URL, app_schema)
        await apply_application(TEST_DATABASE_URL, app_schema)
        await audit1.open()
        await ensure_checkpoint_schema(TEST_DATABASE_URL, checkpoint_schema)
        async with AsyncPostgresSaver.from_conn_string(
            checkpoint_conninfo(TEST_DATABASE_URL, checkpoint_schema)
        ) as saver1:
            await saver1.setup()
            workflow1 = DoubleChargeWorkflow(
                audit=audit1,
                gateway=SharedDomainGateway(),
                model=FakeModel(),
                checkpointer=saver1,
            )
            service1 = WorkflowService(workflow1, audit1)
            started = await service1.start(
                StartCaseRequest(
                    complaint="I was charged twice for the same purchase.",
                    customer_id="customer-postgres",
                    scenario_id="retry-safe-refund",
                    idempotency_key=f"durable-refund-{suffix}",
                )
            )
            case_id, run_id = started.case_id, started.run_id
            assert started.status == "paused"
            checkpoint_id = started.checkpoint_id or ""
        await audit1.close()

        audit2 = PostgresAuditRepository(TEST_DATABASE_URL, app_schema)
        await audit2.open()
        async with AsyncPostgresSaver.from_conn_string(
            checkpoint_conninfo(TEST_DATABASE_URL, checkpoint_schema)
        ) as saver2:
            workflow2 = DoubleChargeWorkflow(
                audit=audit2,
                gateway=SharedDomainGateway(),
                model=FakeModel(),
                checkpointer=saver2,
                interrupt_after=["submit_refund"],
            )
            service2 = WorkflowService(workflow2, audit2)
            approval = ApprovalRequest(
                checkpoint_id=checkpoint_id,
                decision="approve",
                reviewer_id="postgres-reviewer",
                reason="Approved once",
            )
            await service2.submit_approval(case_id, approval)
            await service2.submit_approval(case_id, approval)
            with pytest.raises(InvalidCommandError):
                await service2.submit_approval(
                    case_id,
                    approval.model_copy(update={"decision": "deny"}),
                )
            interrupted_retry = await service2.resume(case_id)
            assert interrupted_retry.status == "running"
            durable = await audit2.get_refund(f"durable-refund-{suffix}")
            assert durable is not None
            durable_refund_id = durable["refund_id"]
            await audit2.save_approval(run_id, approval.model_dump())
            with pytest.raises(ApprovalCommandConflictError):
                await audit2.save_approval(
                    run_id,
                    approval.model_copy(update={"reviewer_id": "other"}).model_dump(),
                )
            assert await audit2.get_pending_approval(run_id) is None
            await audit2.record_refund(durable)
            with pytest.raises(RefundIdempotencyConflictError):
                await audit2.record_refund({**durable, "request_fingerprint": "different"})
            events = await audit2.list_events(run_id)
            assert sum(event.event_type == "approval_command_recorded" for event in events) == 1
        await audit2.close()

        audit3 = PostgresAuditRepository(TEST_DATABASE_URL, app_schema)
        await audit3.open()
        async with AsyncPostgresSaver.from_conn_string(
            checkpoint_conninfo(TEST_DATABASE_URL, checkpoint_schema)
        ) as saver3:
            workflow3 = DoubleChargeWorkflow(
                audit=audit3,
                gateway=SharedDomainGateway(),
                model=FakeModel(),
                checkpointer=saver3,
            )
            service3 = WorkflowService(workflow3, audit3)
            completed = await service3.continue_run(case_id)
            assert completed.status == "completed"
            outcome = (await service3.get_case(case_id)).outcome
            assert outcome and outcome.refund_id == durable_refund_id
            assert outcome.refund_status == "verified"
        await audit3.close()

        async with await AsyncConnection.connect(TEST_DATABASE_URL, autocommit=True) as inspection:
            refund_count = await inspection.execute(
                sql.SQL("SELECT count(*) FROM {}.refunds WHERE run_id = %s").format(
                    sql.Identifier(app_schema)
                ),
                (run_id,),
            )
            assert (await refund_count.fetchone())[0] == 1
            for table in (
                "checkpoint_migrations",
                "checkpoints",
                "checkpoint_blobs",
                "checkpoint_writes",
            ):
                relation = await inspection.execute(
                    "SELECT to_regclass(%s)",
                    (f"{checkpoint_schema}.{table}",),
                )
                assert (await relation.fetchone())[0] is not None
            assert not await _public_checkpoint_tables(inspection)
    finally:
        async with await AsyncConnection.connect(TEST_DATABASE_URL, autocommit=True) as cleanup:
            await cleanup.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(app_schema))
            )
            await cleanup.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                    sql.Identifier(checkpoint_schema)
                )
            )


async def _public_checkpoint_tables(connection: AsyncConnection) -> set[str]:
    result = await connection.execute(
        """SELECT tablename FROM pg_tables
           WHERE schemaname = 'public' AND tablename = ANY(%s)""",
        (
            [
                "checkpoint_migrations",
                "checkpoints",
                "checkpoint_blobs",
                "checkpoint_writes",
            ],
        ),
    )
    return {row[0] for row in await result.fetchall()}


@pytest.mark.parametrize("breakpoint", ["detect_duplicate", "dispatch_validations"])
async def test_postgres_validation_restart_uses_checkpointed_evidence(breakpoint, monkeypatch):
    assert TEST_DATABASE_URL is not None
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    suffix = uuid4().hex[:12]
    settings = Settings(
        _env_file=None,
        database_url=TEST_DATABASE_URL,
        langgraph_schema=f"lg_evidence_app_{suffix}",
        langgraph_checkpoint_schema=f"lg_evidence_cp_{suffix}",
        log_level="ERROR",
    )

    class FreshGateway(SharedDomainGateway):
        async def detect_duplicate(self, *args):
            raise AssertionError("Checkpointed duplicate detection must not execute again")

    class FreshModel(FakeModel):
        async def normalize(self, complaint):
            raise AssertionError("Checkpointed normalization must not execute again")

    try:
        await setup_storage(settings, require_fresh=True)
        async with AsyncExitStack() as stack:
            audit = PostgresAuditRepository(TEST_DATABASE_URL, settings.langgraph_schema)
            stack.push_async_callback(audit.close)
            await audit.open()
            saver = await stack.enter_async_context(
                AsyncPostgresSaver.from_conn_string(
                    checkpoint_conninfo(TEST_DATABASE_URL, settings.langgraph_checkpoint_schema)
                )
            )
            workflow = DoubleChargeWorkflow(
                audit=audit,
                checkpointer=saver,
                gateway=SharedDomainGateway(),
                model=FakeModel(),
                interrupt_after=[breakpoint],
            )
            started = await WorkflowService(workflow, audit).start(
                StartCaseRequest(
                    complaint="I was charged twice for the same purchase.",
                    customer_id="checkpoint-evidence-customer",
                    scenario_id="duplicate-confirmed",
                    idempotency_key=f"checkpoint-evidence-{suffix}",
                )
            )
            assert started.status == "running"
            snapshot = await workflow.snapshot(started.run_id)
            assert snapshot is not None
            assert snapshot["duplicate_evidence"]["decision"] == "confirmed"
            assert len(snapshot["duplicate_evidence"]["matching_charge_ids"]) == 2
            assert snapshot["validation_results"] == {}

        async with open_runtime(
            settings, gateway=FreshGateway(), model=FreshModel()
        ) as reconstructed:
            paused = await reconstructed.service.continue_run(started.case_id)
            assert paused.status == "paused"
            assert paused.checkpoint_id is not None
            case = await reconstructed.service.get_case(started.case_id)
            assert case.outcome is None
            assert case.workflow_state["validation_results"]["billing"]["ok"] is True
            assert case.workflow_state["validation_results"]["policy"]["ok"] is True
            await reconstructed.service.submit_approval(
                started.case_id,
                ApprovalRequest(
                    checkpoint_id=paused.checkpoint_id,
                    decision="approve",
                    reviewer_id="checkpoint-evidence-reviewer",
                ),
            )
            assert (await reconstructed.service.resume(started.case_id)).status == "completed"
            case = await reconstructed.service.get_case(started.case_id)
            assert case.outcome is not None
            assert case.outcome.refund_status == "verified"
            events = await reconstructed.service.list_events(started.case_id)
            assert sum(event.event_type == "parallel_branch_completed" for event in events) == 2
            assert sum(event.event_type == "parallel_branch_joined" for event in events) == 1
    finally:
        async with await AsyncConnection.connect(TEST_DATABASE_URL, autocommit=True) as cleanup:
            for schema in (settings.langgraph_schema, settings.langgraph_checkpoint_schema):
                await cleanup.execute(
                    sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema))
                )
