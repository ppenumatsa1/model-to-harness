import asyncio
import re
from collections import defaultdict
from copy import deepcopy
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import uuid4

from psycopg import errors, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool

from .contracts import NativeEvent

SAFE_EVENT_DATA_KEYS = {
    "attempt",
    "branch",
    "checkpoint_id",
    "decision",
    "eligible",
    "failure_code",
    "latency_ms",
    "model",
    "refund_id",
    "retry_in_ms",
    "route",
    "tool",
    "tool_call_id",
    "usage",
    "verified_count",
}


def safe_event_data(data: dict[str, Any] | None) -> dict[str, Any]:
    if not data:
        return {}
    return {key: value for key, value in data.items() if key in SAFE_EVENT_DATA_KEYS}


class ApprovalCommandConflictError(ValueError):
    pass


class RefundIdempotencyConflictError(ValueError):
    pass


class AuditRepository(Protocol):
    async def setup(self) -> None: ...

    async def ping(self) -> bool: ...

    async def create_run(self, record: dict[str, Any]) -> None: ...

    async def update_run(self, run_id: str, updates: dict[str, Any]) -> None: ...

    async def get_run_by_case(self, case_id: str) -> dict[str, Any] | None: ...

    async def append_event(
        self,
        *,
        case_id: str,
        run_id: str,
        event_type: str,
        summary: str,
        node: str | None = None,
        status: str | None = None,
        data: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
    ) -> NativeEvent: ...

    async def list_events(self, run_id: str, after: int = 0) -> list[NativeEvent]: ...

    async def save_approval(self, run_id: str, approval: dict[str, Any]) -> None: ...

    async def get_approval(self, run_id: str) -> dict[str, Any] | None: ...

    async def get_pending_approval(self, run_id: str) -> dict[str, Any] | None: ...

    async def consume_approval(self, run_id: str) -> None: ...

    async def get_refund(self, idempotency_key: str) -> dict[str, Any] | None: ...

    async def record_refund(self, refund: dict[str, Any]) -> dict[str, Any]: ...

    async def upsert_memory(
        self, customer_id: str, case_id: str, facts: dict[str, Any]
    ) -> None: ...

    async def get_memory(self, customer_id: str, case_id: str) -> dict[str, Any]: ...


class InMemoryAuditRepository:
    def __init__(self) -> None:
        self.runs: dict[str, dict[str, Any]] = {}
        self.case_to_run: dict[str, str] = {}
        self.events: dict[str, list[NativeEvent]] = defaultdict(list)
        self.approvals: dict[str, dict[str, Any]] = {}
        self.refunds: dict[str, dict[str, Any]] = {}
        self.memories: dict[tuple[str, str], dict[str, Any]] = {}
        self._dedupe: dict[tuple[str, str], NativeEvent] = {}
        self._lock = asyncio.Lock()

    async def setup(self) -> None:
        return None

    async def ping(self) -> bool:
        return True

    async def create_run(self, record: dict[str, Any]) -> None:
        async with self._lock:
            self.runs[record["run_id"]] = deepcopy(record)
            self.case_to_run[record["case_id"]] = record["run_id"]

    async def update_run(self, run_id: str, updates: dict[str, Any]) -> None:
        async with self._lock:
            self.runs[run_id].update(deepcopy(updates))

    async def get_run_by_case(self, case_id: str) -> dict[str, Any] | None:
        run_id = self.case_to_run.get(case_id)
        return deepcopy(self.runs.get(run_id)) if run_id else None

    async def append_event(self, **kwargs: Any) -> NativeEvent:
        dedupe_key = kwargs.pop("dedupe_key", None)
        run_id = kwargs["run_id"]
        async with self._lock:
            if dedupe_key and (run_id, dedupe_key) in self._dedupe:
                return self._dedupe[(run_id, dedupe_key)]
            event = NativeEvent(
                sequence=len(self.events[run_id]) + 1,
                event_id=str(uuid4()),
                timestamp=datetime.now(UTC),
                data=safe_event_data(kwargs.pop("data", None)),
                **kwargs,
            )
            self.events[run_id].append(event)
            if dedupe_key:
                self._dedupe[(run_id, dedupe_key)] = event
            return event

    async def list_events(self, run_id: str, after: int = 0) -> list[NativeEvent]:
        return [deepcopy(event) for event in self.events[run_id] if event.sequence > after]

    async def save_approval(self, run_id: str, approval: dict[str, Any]) -> None:
        candidate = {**deepcopy(approval), "consumed": False}
        async with self._lock:
            existing = self.approvals.get(run_id)
            if existing is None:
                self.approvals[run_id] = candidate
                return
            if _approval_identity(existing) != _approval_identity(candidate):
                raise ApprovalCommandConflictError(
                    "A different approval command is already recorded for this run"
                )

    async def get_pending_approval(self, run_id: str) -> dict[str, Any] | None:
        approval = self.approvals.get(run_id)
        if not approval or approval["consumed"]:
            return None
        return deepcopy(approval)

    async def get_approval(self, run_id: str) -> dict[str, Any] | None:
        return deepcopy(self.approvals.get(run_id))

    async def consume_approval(self, run_id: str) -> None:
        async with self._lock:
            self.approvals[run_id]["consumed"] = True

    async def get_refund(self, idempotency_key: str) -> dict[str, Any] | None:
        return deepcopy(self.refunds.get(idempotency_key))

    async def record_refund(self, refund: dict[str, Any]) -> dict[str, Any]:
        candidate = deepcopy(refund)
        key = candidate["idempotency_key"]
        async with self._lock:
            existing = self.refunds.get(key)
            if existing is None:
                if any(
                    record["refund_id"] == candidate["refund_id"]
                    for record in self.refunds.values()
                ):
                    raise RefundIdempotencyConflictError(
                        "Refund ID is already bound to another idempotency key"
                    )
                self.refunds[key] = candidate
                return deepcopy(candidate)
            if (
                existing["request_fingerprint"] != candidate["request_fingerprint"]
                or existing["refund_id"] != candidate["refund_id"]
            ):
                raise RefundIdempotencyConflictError(
                    "Idempotency key is already bound to a different refund request"
                )
            return deepcopy(existing)

    async def upsert_memory(
        self, customer_id: str, case_id: str, facts: dict[str, Any]
    ) -> None:
        self.memories[(customer_id, case_id)] = deepcopy(facts)

    async def get_memory(self, customer_id: str, case_id: str) -> dict[str, Any]:
        return deepcopy(self.memories.get((customer_id, case_id), {}))


class PostgresAuditRepository:
    def __init__(self, database_url: str, schema: str = "langgraph_app") -> None:
        if not re.fullmatch(r"[a-z_][a-z0-9_]*", schema):
            raise ValueError("LANGGRAPH_SCHEMA must be a lowercase SQL identifier")
        self.schema = schema
        self.pool = AsyncConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=8,
            open=False,
            kwargs={"autocommit": True, "row_factory": dict_row},
        )

    def _q(self, template: str) -> sql.Composed:
        return sql.SQL(template).format(schema=sql.Identifier(self.schema))

    async def setup(self) -> None:
        await self.pool.open()
        statements = [
            "CREATE SCHEMA IF NOT EXISTS {schema}",
            """CREATE TABLE IF NOT EXISTS {schema}.runs (
                run_id text PRIMARY KEY,
                case_id text UNIQUE NOT NULL,
                customer_id text NOT NULL,
                status text NOT NULL,
                current_step text NOT NULL,
                checkpoint_id text,
                approval_required boolean NOT NULL DEFAULT false,
                state jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                outcome jsonb,
                created_at timestamptz NOT NULL DEFAULT now(),
                updated_at timestamptz NOT NULL DEFAULT now()
            )""",
            """CREATE TABLE IF NOT EXISTS {schema}.events (
                sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                event_id uuid NOT NULL UNIQUE,
                case_id text NOT NULL,
                run_id text NOT NULL REFERENCES {schema}.runs(run_id),
                event_type text NOT NULL,
                event_time timestamptz NOT NULL DEFAULT now(),
                node text,
                status text,
                summary text NOT NULL,
                data jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                dedupe_key text,
                UNIQUE (run_id, dedupe_key)
            )""",
            """CREATE INDEX IF NOT EXISTS langgraph_events_run_sequence
               ON {schema}.events(run_id, sequence)""",
            """CREATE TABLE IF NOT EXISTS {schema}.approvals (
                run_id text PRIMARY KEY REFERENCES {schema}.runs(run_id),
                checkpoint_id text NOT NULL,
                decision text NOT NULL CHECK (decision IN ('approve', 'deny')),
                reviewer_id text NOT NULL,
                reason text,
                consumed boolean NOT NULL DEFAULT false,
                created_at timestamptz NOT NULL DEFAULT now()
            )""",
            """CREATE TABLE IF NOT EXISTS {schema}.selected_memory (
                customer_id text NOT NULL,
                case_id text NOT NULL,
                facts jsonb NOT NULL,
                updated_at timestamptz NOT NULL DEFAULT now(),
                PRIMARY KEY (customer_id, case_id)
            )""",
            """CREATE TABLE IF NOT EXISTS {schema}.refunds (
                idempotency_key text PRIMARY KEY,
                request_fingerprint text NOT NULL,
                refund_id text NOT NULL UNIQUE,
                case_id text NOT NULL,
                run_id text NOT NULL,
                customer_id text NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now()
            )""",
        ]
        async with self.pool.connection() as conn:
            for statement in statements:
                await conn.execute(self._q(statement))

    async def close(self) -> None:
        await self.pool.close()

    async def ping(self) -> bool:
        try:
            async with self.pool.connection() as conn:
                await conn.execute("SELECT 1")
            return True
        except Exception:
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
        selected = {key: value for key, value in updates.items() if key in allowed}
        if not selected:
            return
        values = {
            key: Jsonb(value) if key in {"state", "outcome"} and value is not None else value
            for key, value in selected.items()
        }
        assignments = [
            sql.SQL("{} = {}").format(sql.Identifier(key), sql.Placeholder(key))
            for key in selected
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
                self._q(
                    "SELECT * FROM {schema}.approvals WHERE run_id = %s AND consumed = false"
                ),
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

    async def upsert_memory(
        self, customer_id: str, case_id: str, facts: dict[str, Any]
    ) -> None:
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


def _approval_identity(approval: dict[str, Any]) -> tuple[Any, ...]:
    return (
        approval.get("checkpoint_id"),
        approval.get("decision"),
        approval.get("reviewer_id"),
        approval.get("reason"),
    )
