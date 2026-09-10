from __future__ import annotations

import json

from maf_double_charge.application.errors import (
    RefundIdempotencyConflictError,
    StorageReadinessError,
)
from maf_double_charge.application.models import (
    ApprovalResponse,
    DurableEvent,
    RefundLedgerEntry,
    WorkflowState,
)
from model_to_harness_shared import WorkflowOutcome
from psycopg import AsyncConnection, Error, sql
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool, PoolClosed, PoolTimeout

from .migrations import check_schema, validate_schema


class PostgresRepository:
    def __init__(self, database_url: str, schema: str) -> None:
        validate_schema(schema)
        self.schema = schema
        self.pool = AsyncConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=10,
            open=False,
            kwargs={"row_factory": dict_row},
            configure=self._configure_connection,
        )

    async def _configure_connection(self, conn: AsyncConnection) -> None:
        await conn.execute(
            sql.SQL("SET search_path TO {}, pg_catalog").format(sql.Identifier(self.schema))
        )
        await conn.commit()

    async def initialize(self) -> None:
        try:
            await self.pool.open(wait=True)
            await self.check_ready()
        except (Error, PoolClosed, PoolTimeout) as exc:
            await self.pool.close()
            raise StorageReadinessError("MAF storage is unavailable.") from exc
        except BaseException:
            await self.pool.close()
            raise

    async def close(self) -> None:
        await self.pool.close()

    async def check_ready(self) -> None:
        try:
            async with self.pool.connection() as conn:
                await check_schema(conn, self.schema)
        except (Error, PoolClosed, PoolTimeout) as exc:
            raise StorageReadinessError("MAF storage is unavailable.") from exc

    async def create_run(self, state: WorkflowState) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO runs (run_id, case_id, status, current_step, state, checkpoint_id)
                VALUES (%s, %s, %s, %s, %s::jsonb, %s)
                """,
                (
                    state.run_id,
                    state.case_id,
                    state.status.value,
                    state.current_step,
                    state.model_dump_json(),
                    state.checkpoint_id,
                ),
            )

    async def save_state(self, state: WorkflowState) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                """
                UPDATE runs SET status = %s, current_step = %s, state = %s::jsonb,
                    checkpoint_id = %s, updated_at = now()
                WHERE run_id = %s
                """,
                (
                    state.status.value,
                    state.current_step,
                    state.model_dump_json(),
                    state.checkpoint_id,
                    state.run_id,
                ),
            )

    async def get_state(self, run_id: str) -> WorkflowState | None:
        async with self.pool.connection() as conn:
            result = await conn.execute("SELECT state FROM runs WHERE run_id = %s", (run_id,))
            row = await result.fetchone()
        return WorkflowState.model_validate(row["state"]) if row else None

    async def get_state_by_case(self, case_id: str) -> WorkflowState | None:
        async with self.pool.connection() as conn:
            result = await conn.execute("SELECT state FROM runs WHERE case_id = %s", (case_id,))
            row = await result.fetchone()
        return WorkflowState.model_validate(row["state"]) if row else None

    async def save_memory(self, case_id: str, memory: dict[str, object]) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO selected_memory (case_id, memory) VALUES (%s, %s::jsonb)
                ON CONFLICT (case_id) DO UPDATE SET memory = EXCLUDED.memory, updated_at = now()
                """,
                (case_id, json.dumps(memory, default=str)),
            )

    async def get_memory(self, case_id: str) -> dict[str, object]:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                "SELECT memory FROM selected_memory WHERE case_id = %s", (case_id,)
            )
            row = await result.fetchone()
        return row["memory"] if row else {}

    async def append_event(self, event: DurableEvent) -> DurableEvent:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                """
                INSERT INTO execution_events
                    (event_id, case_id, run_id, event_type, node, transition,
                     checkpoint_id, retry_attempt, idempotency_key, summary, payload, created_at)
                VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s)
                RETURNING sequence
                """,
                (
                    event.event_id,
                    event.case_id,
                    event.run_id,
                    event.event_type,
                    event.node,
                    event.transition,
                    event.checkpoint_id,
                    event.retry_attempt,
                    event.idempotency_key,
                    event.summary,
                    json.dumps(event.payload, default=str),
                    event.created_at,
                ),
            )
            row = await result.fetchone()
        return event.model_copy(update={"sequence": row["sequence"]})

    async def list_events(self, run_id: str, after: int = 0) -> list[DurableEvent]:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                """
                SELECT sequence, event_id::text, case_id, run_id, event_type, node, transition,
                       checkpoint_id, retry_attempt, idempotency_key, summary, payload, created_at
                FROM execution_events WHERE run_id = %s AND sequence > %s ORDER BY sequence
                """,
                (run_id, after),
            )
            rows = await result.fetchall()
        return [DurableEvent.model_validate(row) for row in rows]

    async def save_approval(
        self, run_id: str, checkpoint_id: str, response: ApprovalResponse
    ) -> None:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                """
                INSERT INTO approvals (run_id, checkpoint_id, response) VALUES (%s, %s, %s::jsonb)
                ON CONFLICT (run_id) DO NOTHING RETURNING run_id
                """,
                (run_id, checkpoint_id, response.model_dump_json()),
            )
            if await result.fetchone() is not None:
                return
            result = await conn.execute(
                "SELECT checkpoint_id, response FROM approvals WHERE run_id = %s", (run_id,)
            )
            row = await result.fetchone()
            existing = ApprovalResponse.model_validate(row["response"]) if row else None
            if (
                existing is None
                or row["checkpoint_id"] != checkpoint_id
                or not existing.same_intent(response)
            ):
                raise ValueError("approval already resolved with another decision")

    async def get_approval(self, run_id: str) -> ApprovalResponse | None:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                "SELECT response FROM approvals WHERE run_id = %s", (run_id,)
            )
            row = await result.fetchone()
        return ApprovalResponse.model_validate(row["response"]) if row else None

    async def save_outcome(self, outcome: WorkflowOutcome) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                """
                INSERT INTO outcomes (run_id, outcome) VALUES (%s, %s::jsonb)
                ON CONFLICT (run_id) DO UPDATE SET outcome = EXCLUDED.outcome
                """,
                (outcome.run_id, outcome.model_dump_json()),
            )

    async def get_outcome(self, run_id: str) -> WorkflowOutcome | None:
        async with self.pool.connection() as conn:
            result = await conn.execute("SELECT outcome FROM outcomes WHERE run_id = %s", (run_id,))
            row = await result.fetchone()
        return WorkflowOutcome.model_validate(row["outcome"]) if row else None

    async def set_checkpoint(self, run_id: str, checkpoint_id: str) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                """
                UPDATE runs SET checkpoint_id = %s,
                    state = jsonb_set(state, '{checkpoint_id}', to_jsonb(%s::text)),
                    updated_at = now()
                WHERE run_id = %s
                """,
                (checkpoint_id, checkpoint_id, run_id),
            )

    async def get_refund(self, idempotency_key: str) -> RefundLedgerEntry | None:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                """
                SELECT idempotency_key, request_fingerprint, account_id, charge_id,
                       amount, currency, refund_id, refund, created_by_run_id, created_at
                FROM refund_ledger WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            )
            row = await result.fetchone()
        return RefundLedgerEntry.model_validate(row) if row else None

    async def store_refund(self, entry: RefundLedgerEntry) -> tuple[RefundLedgerEntry, bool]:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                """
                INSERT INTO refund_ledger (
                    idempotency_key, request_fingerprint, account_id, charge_id,
                    amount, currency, refund_id, refund, created_by_run_id, created_at
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                ON CONFLICT (idempotency_key) DO NOTHING RETURNING idempotency_key
                """,
                (
                    entry.idempotency_key,
                    entry.request_fingerprint,
                    entry.account_id,
                    entry.charge_id,
                    entry.amount,
                    entry.currency,
                    entry.refund_id,
                    json.dumps(entry.refund, default=str),
                    entry.created_by_run_id,
                    entry.created_at,
                ),
            )
            created = await result.fetchone() is not None
            result = await conn.execute(
                """
                SELECT idempotency_key, request_fingerprint, account_id, charge_id,
                       amount, currency, refund_id, refund, created_by_run_id, created_at
                FROM refund_ledger WHERE idempotency_key = %s
                """,
                (entry.idempotency_key,),
            )
            row = await result.fetchone()
            if row is None:
                raise StorageReadinessError("Refund ledger write did not produce a durable row.")
            stored = RefundLedgerEntry.model_validate(row)
            if stored.request_fingerprint != entry.request_fingerprint:
                raise RefundIdempotencyConflictError(
                    "idempotency key is already bound to a different refund request"
                )
        return stored, created

    async def count_refunds(self, idempotency_key: str) -> int:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                "SELECT count(*) AS count FROM refund_ledger WHERE idempotency_key = %s",
                (idempotency_key,),
            )
            row = await result.fetchone()
        return int(row["count"])
