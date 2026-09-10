import logging
import re
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from psycopg import AsyncConnection, errors, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from ...application.ports import (
    ApprovalCommandConflictError,
    CommandInProgressError,
    RefundIdempotencyConflictError,
    _approval_identity,
    safe_event_data,
)
from ...application.records import NativeEvent


class PostgresAuditRepository:
    def __init__(self, database_url: str, schema: str = "langgraph_app_cutover") -> None:
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", schema):
            raise ValueError("LANGGRAPH_SCHEMA must be a lowercase SQL identifier")
        self.schema = schema
        self._database_url = database_url
        self.pool = AsyncConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=8,
            open=False,
            kwargs={"autocommit": True, "row_factory": dict_row},
        )

    def _q(self, template: str) -> sql.Composed:
        return sql.SQL(template).format(schema=sql.Identifier(self.schema))

    @asynccontextmanager
    async def command_lock(self, case_id: str):
        # Guards must not occupy the pool used by the guarded workflow's audit writes.
        async with await AsyncConnection.connect(
            self._database_url, autocommit=True, row_factory=dict_row
        ) as connection:
            key = f"{self.schema}:command:{case_id}"
            result = await connection.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s, 0)) AS acquired", (key,)
            )
            if not (await result.fetchone())["acquired"]:
                raise CommandInProgressError("Another command is executing for this case")
            try:
                yield
            finally:
                await connection.execute(
                    "SELECT pg_advisory_unlock(hashtextextended(%s, 0))", (key,)
                )

    async def open(self) -> None:
        await self.pool.open(wait=True)

    async def verify(self) -> None:
        from .migrations import verify_application

        async with self.pool.connection() as connection:
            await verify_application(connection, self.schema)

    async def close(self) -> None:
        await self.pool.close()

    async def ping(self) -> bool:
        try:
            async with self.pool.connection() as conn:
                await conn.execute("SELECT 1")
            return True
        except (errors.OperationalError, errors.InterfaceError):
            logging.getLogger(__name__).warning(
                "Audit readiness failed", extra={"safe_event": "audit_readiness_failed"}
            )
            return False

    async def create_run(self, record: dict[str, Any]) -> None:
        query = self._q(
            """INSERT INTO {schema}.runs
               (run_id, case_id, customer_id, status, current_step, checkpoint_id,
                approval_required, state, outcome)
               VALUES (%(run_id)s, %(case_id)s, %(customer_id)s, %(status)s,
                       %(current_step)s, %(checkpoint_id)s, %(approval_required)s,
                       %(state)s::jsonb, %(outcome)s::jsonb)"""
        )
        values = {
            **record,
            "state": Jsonb(record["state"]),
            "outcome": Jsonb(record["outcome"]) if record["outcome"] is not None else None,
        }
        async with self.pool.connection() as conn:
            await conn.execute(query, values)

    async def update_run(self, run_id: str, updates: dict[str, Any]) -> None:
        allowed = {
            "status",
            "current_step",
            "checkpoint_id",
            "approval_required",
            "state",
            "outcome",
        }
        if not updates or updates.keys() - allowed:
            raise ValueError("Run updates must contain only supported application fields")
        selected = updates
        values = {
            key: Jsonb(value) if key in {"state", "outcome"} and value is not None else value
            for key, value in selected.items()
        }
        assignments = [
            sql.SQL("{} = {}").format(sql.Identifier(key), sql.Placeholder(key)) for key in selected
        ]
        query = sql.SQL(
            "UPDATE {}.runs SET {}, updated_at = now() WHERE run_id = %(run_id)s"
        ).format(
            sql.Identifier(self.schema),
            sql.SQL(", ").join(assignments),
        )
        async with self.pool.connection() as conn:
            await conn.execute(query, {"run_id": run_id, **values})

    async def get_run_by_case(self, case_id: str) -> dict[str, Any] | None:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                self._q("SELECT * FROM {schema}.runs WHERE case_id = %s"),
                (case_id,),
            )
            return await result.fetchone()

    async def append_event(self, **kwargs: Any) -> NativeEvent:
        event_id = str(uuid4())
        data = safe_event_data(kwargs.pop("data", None))
        dedupe_key = kwargs.pop("dedupe_key", None)
        query = self._q(
            """INSERT INTO {schema}.events
               (event_id, case_id, run_id, event_type, node, status, summary, data, dedupe_key)
               VALUES (%(event_id)s, %(case_id)s, %(run_id)s, %(event_type)s,
                       %(node)s, %(status)s, %(summary)s, %(data)s::jsonb, %(dedupe_key)s)
               ON CONFLICT (run_id, dedupe_key)
               DO UPDATE SET dedupe_key = EXCLUDED.dedupe_key
               RETURNING sequence, event_id::text, case_id, run_id, event_type,
                         event_time AS timestamp, node, status, summary, data"""
        )
        async with self.pool.connection() as conn:
            result = await conn.execute(
                query,
                {
                    "event_id": event_id,
                    "data": Jsonb(data),
                    "dedupe_key": dedupe_key,
                    **kwargs,
                },
            )
            row = await result.fetchone()
        return NativeEvent.model_validate(row)

    async def list_events(self, run_id: str, after: int = 0) -> list[NativeEvent]:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                self._q(
                    """SELECT sequence, event_id::text, case_id, run_id, event_type,
                              event_time AS timestamp, node, status, summary, data
                       FROM {schema}.events
                       WHERE run_id = %s AND sequence > %s ORDER BY sequence"""
                ),
                (run_id, after),
            )
            rows = await result.fetchall()
        return [NativeEvent.model_validate(row) for row in rows]

    async def save_approval(self, run_id: str, approval: dict[str, Any]) -> None:
        async with self.pool.connection() as conn:
            inserted = await conn.execute(
                self._q(
                    """INSERT INTO {schema}.approvals
                       (run_id, checkpoint_id, decision, reviewer_id, reason, consumed)
                       VALUES (%(run_id)s, %(checkpoint_id)s, %(decision)s,
                               %(reviewer_id)s, %(reason)s, false)
                       ON CONFLICT (run_id) DO NOTHING
                       RETURNING run_id"""
                ),
                {"run_id": run_id, **approval},
            )
            if await inserted.fetchone():
                return
            selected = await conn.execute(
                self._q("SELECT * FROM {schema}.approvals WHERE run_id = %s"),
                (run_id,),
            )
            existing = await selected.fetchone()
        if existing is None or _approval_identity(existing) != _approval_identity(approval):
            raise ApprovalCommandConflictError(
                "A different approval command is already recorded for this run"
            )

    async def get_pending_approval(self, run_id: str) -> dict[str, Any] | None:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                self._q("SELECT * FROM {schema}.approvals WHERE run_id = %s AND consumed = false"),
                (run_id,),
            )
            return await result.fetchone()

    async def get_approval(self, run_id: str) -> dict[str, Any] | None:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                self._q("SELECT * FROM {schema}.approvals WHERE run_id = %s"),
                (run_id,),
            )
            return await result.fetchone()

    async def consume_approval(self, run_id: str) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                self._q("UPDATE {schema}.approvals SET consumed = true WHERE run_id = %s"),
                (run_id,),
            )

    async def get_refund(self, idempotency_key: str) -> dict[str, Any] | None:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                self._q(
                    """SELECT idempotency_key, request_fingerprint, refund_id,
                              case_id, run_id, customer_id, created_at
                       FROM {schema}.refunds WHERE idempotency_key = %s"""
                ),
                (idempotency_key,),
            )
            return await result.fetchone()

    async def record_refund(self, refund: dict[str, Any]) -> dict[str, Any]:
        try:
            async with self.pool.connection() as conn:
                inserted = await conn.execute(
                    self._q(
                        """INSERT INTO {schema}.refunds
                           (idempotency_key, request_fingerprint, refund_id,
                            case_id, run_id, customer_id)
                           VALUES (%(idempotency_key)s, %(request_fingerprint)s,
                                   %(refund_id)s, %(case_id)s, %(run_id)s, %(customer_id)s)
                           ON CONFLICT (idempotency_key) DO NOTHING
                           RETURNING idempotency_key, request_fingerprint, refund_id,
                                     case_id, run_id, customer_id, created_at"""
                    ),
                    refund,
                )
                created = await inserted.fetchone()
                if created:
                    return created
                selected = await conn.execute(
                    self._q(
                        """SELECT idempotency_key, request_fingerprint, refund_id,
                                  case_id, run_id, customer_id, created_at
                           FROM {schema}.refunds WHERE idempotency_key = %s"""
                    ),
                    (refund["idempotency_key"],),
                )
                existing = await selected.fetchone()
        except errors.UniqueViolation as exc:
            raise RefundIdempotencyConflictError(
                "Refund ID is already bound to another idempotency key"
            ) from exc
        if (
            existing is None
            or existing["request_fingerprint"] != refund["request_fingerprint"]
            or existing["refund_id"] != refund["refund_id"]
        ):
            raise RefundIdempotencyConflictError(
                "Idempotency key is already bound to a different refund request"
            )
        return existing

    async def upsert_memory(self, customer_id: str, case_id: str, facts: dict[str, Any]) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                self._q(
                    """INSERT INTO {schema}.selected_memory (customer_id, case_id, facts)
                       VALUES (%s, %s, %s::jsonb)
                       ON CONFLICT (customer_id, case_id) DO UPDATE
                       SET facts = EXCLUDED.facts, updated_at = now()"""
                ),
                (customer_id, case_id, Jsonb(facts)),
            )

    async def get_memory(self, customer_id: str, case_id: str) -> dict[str, Any]:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                self._q(
                    "SELECT facts FROM {schema}.selected_memory WHERE customer_id=%s AND case_id=%s"
                ),
                (customer_id, case_id),
            )
            row = await result.fetchone()
        return row["facts"] if row else {}
