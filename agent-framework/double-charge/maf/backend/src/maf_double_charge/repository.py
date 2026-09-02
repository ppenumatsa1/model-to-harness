from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from copy import deepcopy
from typing import Protocol

from model_to_harness_shared import WorkflowOutcome
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from .models import ApprovalResponse, DurableEvent, RefundLedgerEntry, WorkflowState


class RefundIdempotencyConflictError(ValueError):
    pass


class Repository(Protocol):
    async def initialize(self) -> None: ...

    async def close(self) -> None: ...

    async def create_run(self, state: WorkflowState) -> None: ...

    async def save_state(self, state: WorkflowState) -> None: ...

    async def get_state(self, run_id: str) -> WorkflowState | None: ...

    async def get_state_by_case(self, case_id: str) -> WorkflowState | None: ...

    async def save_memory(self, case_id: str, memory: dict[str, object]) -> None: ...

    async def get_memory(self, case_id: str) -> dict[str, object]: ...

    async def append_event(self, event: DurableEvent) -> DurableEvent: ...

    async def list_events(self, run_id: str, after: int = 0) -> list[DurableEvent]: ...

    async def save_approval(
        self, run_id: str, checkpoint_id: str, response: ApprovalResponse
    ) -> None: ...

    async def get_approval(self, run_id: str) -> ApprovalResponse | None: ...

    async def save_outcome(self, outcome: WorkflowOutcome) -> None: ...

    async def get_outcome(self, run_id: str) -> WorkflowOutcome | None: ...

    async def set_checkpoint(self, run_id: str, checkpoint_id: str) -> None: ...

    async def get_refund(self, idempotency_key: str) -> RefundLedgerEntry | None: ...

    async def store_refund(
        self, entry: RefundLedgerEntry
    ) -> tuple[RefundLedgerEntry, bool]: ...

    async def count_refunds(self, idempotency_key: str) -> int: ...


class InMemoryRepository:
    def __init__(self) -> None:
        self.states: dict[str, WorkflowState] = {}
        self.case_runs: dict[str, str] = {}
        self.events: dict[str, list[DurableEvent]] = defaultdict(list)
        self.approvals: dict[str, tuple[str, ApprovalResponse]] = {}
        self.outcomes: dict[str, WorkflowOutcome] = {}
        self.memory: dict[str, dict[str, object]] = {}
        self.refunds: dict[str, RefundLedgerEntry] = {}
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        return None

    async def close(self) -> None:
        return None

    async def create_run(self, state: WorkflowState) -> None:
        async with self._lock:
            self.states[state.run_id] = deepcopy(state)
            self.case_runs[state.case_id] = state.run_id

    async def save_state(self, state: WorkflowState) -> None:
        async with self._lock:
            self.states[state.run_id] = deepcopy(state)

    async def get_state(self, run_id: str) -> WorkflowState | None:
        state = self.states.get(run_id)
        return deepcopy(state) if state else None

    async def get_state_by_case(self, case_id: str) -> WorkflowState | None:
        run_id = self.case_runs.get(case_id)
        return await self.get_state(run_id) if run_id else None

    async def save_memory(self, case_id: str, memory: dict[str, object]) -> None:
        self.memory[case_id] = deepcopy(memory)

    async def get_memory(self, case_id: str) -> dict[str, object]:
        return deepcopy(self.memory.get(case_id, {}))

    async def append_event(self, event: DurableEvent) -> DurableEvent:
        async with self._lock:
            saved = event.model_copy(update={"sequence": len(self.events[event.run_id]) + 1})
            self.events[event.run_id].append(saved)
            return deepcopy(saved)

    async def list_events(self, run_id: str, after: int = 0) -> list[DurableEvent]:
        return [deepcopy(event) for event in self.events[run_id] if event.sequence > after]

    async def save_approval(
        self, run_id: str, checkpoint_id: str, response: ApprovalResponse
    ) -> None:
        async with self._lock:
            existing = self.approvals.get(run_id)
            if existing and existing != (checkpoint_id, response):
                raise ValueError("approval already resolved with another decision")
            self.approvals[run_id] = (checkpoint_id, deepcopy(response))

    async def get_approval(self, run_id: str) -> ApprovalResponse | None:
        record = self.approvals.get(run_id)
        return deepcopy(record[1]) if record else None

    async def save_outcome(self, outcome: WorkflowOutcome) -> None:
        self.outcomes[outcome.run_id] = deepcopy(outcome)

    async def get_outcome(self, run_id: str) -> WorkflowOutcome | None:
        outcome = self.outcomes.get(run_id)
        return deepcopy(outcome) if outcome else None

    async def set_checkpoint(self, run_id: str, checkpoint_id: str) -> None:
        state = await self.get_state(run_id)
        if state:
            await self.save_state(state.model_copy(update={"checkpoint_id": checkpoint_id}))

    async def get_refund(self, idempotency_key: str) -> RefundLedgerEntry | None:
        async with self._lock:
            entry = self.refunds.get(idempotency_key)
            return deepcopy(entry) if entry else None

    async def store_refund(
        self, entry: RefundLedgerEntry
    ) -> tuple[RefundLedgerEntry, bool]:
        async with self._lock:
            existing = self.refunds.get(entry.idempotency_key)
            if existing is not None:
                if existing.request_fingerprint != entry.request_fingerprint:
                    raise RefundIdempotencyConflictError(
                        "idempotency key is already bound to a different refund request"
                    )
                return deepcopy(existing), False
            self.refunds[entry.idempotency_key] = deepcopy(entry)
            return deepcopy(entry), True

    async def count_refunds(self, idempotency_key: str) -> int:
        async with self._lock:
            return int(idempotency_key in self.refunds)


class PostgresRepository:
    def __init__(self, database_url: str, schema: str) -> None:
        self.schema = schema
        self.pool = AsyncConnectionPool(
            conninfo=database_url,
            min_size=1,
            max_size=10,
            open=False,
            kwargs={"row_factory": dict_row},
        )

    async def initialize(self) -> None:
        await self.pool.open()
        async with self.pool.connection() as conn:
            await conn.execute(f'CREATE SCHEMA IF NOT EXISTS "{self.schema}"')
            await conn.execute(
                f"""
                CREATE TABLE IF NOT EXISTS "{self.schema}".runs (
                    run_id text PRIMARY KEY,
                    case_id text UNIQUE NOT NULL,
                    status text NOT NULL,
                    current_step text NOT NULL,
                    state jsonb NOT NULL,
                    checkpoint_id text,
                    created_at timestamptz NOT NULL DEFAULT now(),
                    updated_at timestamptz NOT NULL DEFAULT now()
                );
                CREATE TABLE IF NOT EXISTS "{self.schema}".execution_events (
                    sequence bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    event_id uuid UNIQUE NOT NULL,
                    case_id text NOT NULL,
                    run_id text NOT NULL REFERENCES "{self.schema}".runs(run_id),
                    event_type text NOT NULL,
                    node text,
                    transition text,
                    checkpoint_id text,
                    retry_attempt integer,
                    idempotency_key text,
                    summary text NOT NULL,
                    payload jsonb NOT NULL DEFAULT '{{}}'::jsonb,
                    created_at timestamptz NOT NULL
                );
                CREATE INDEX IF NOT EXISTS execution_events_run_sequence_idx
                    ON "{self.schema}".execution_events(run_id, sequence);
                CREATE TABLE IF NOT EXISTS "{self.schema}".approvals (
                    run_id text PRIMARY KEY REFERENCES "{self.schema}".runs(run_id),
                    checkpoint_id text UNIQUE NOT NULL,
                    response jsonb NOT NULL,
                    resolved_at timestamptz NOT NULL DEFAULT now()
                );
                CREATE TABLE IF NOT EXISTS "{self.schema}".outcomes (
                    run_id text PRIMARY KEY REFERENCES "{self.schema}".runs(run_id),
                    outcome jsonb NOT NULL,
                    created_at timestamptz NOT NULL DEFAULT now()
                );
                CREATE TABLE IF NOT EXISTS "{self.schema}".selected_memory (
                    case_id text PRIMARY KEY,
                    memory jsonb NOT NULL,
                    updated_at timestamptz NOT NULL DEFAULT now()
                );
                CREATE TABLE IF NOT EXISTS "{self.schema}".maf_checkpoints (
                    checkpoint_id text PRIMARY KEY,
                    workflow_name text NOT NULL,
                    run_id text NOT NULL REFERENCES "{self.schema}".runs(run_id),
                    checkpoint jsonb NOT NULL,
                    created_at timestamptz NOT NULL DEFAULT now()
                );
                CREATE INDEX IF NOT EXISTS maf_checkpoints_workflow_created_idx
                    ON "{self.schema}".maf_checkpoints(workflow_name, created_at DESC);
                CREATE TABLE IF NOT EXISTS "{self.schema}".refund_ledger (
                    idempotency_key text PRIMARY KEY,
                    request_fingerprint text NOT NULL,
                    account_id text NOT NULL,
                    charge_id text NOT NULL,
                    amount numeric(19, 4) NOT NULL,
                    currency text NOT NULL,
                    refund_id text UNIQUE NOT NULL,
                    refund jsonb NOT NULL,
                    created_by_run_id text NOT NULL
                        REFERENCES "{self.schema}".runs(run_id),
                    created_at timestamptz NOT NULL DEFAULT now()
                );
                """
            )
            await conn.commit()

    async def close(self) -> None:
        await self.pool.close()

    async def create_run(self, state: WorkflowState) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                f"""
                INSERT INTO "{self.schema}".runs
                    (run_id, case_id, status, current_step, state, checkpoint_id)
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
            await conn.commit()

    async def save_state(self, state: WorkflowState) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                f"""
                UPDATE "{self.schema}".runs SET
                    status = %s, current_step = %s, state = %s::jsonb,
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
            await conn.commit()

    async def get_state(self, run_id: str) -> WorkflowState | None:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                f'SELECT state FROM "{self.schema}".runs WHERE run_id = %s', (run_id,)
            )
            row = await result.fetchone()
        return WorkflowState.model_validate(row["state"]) if row else None

    async def get_state_by_case(self, case_id: str) -> WorkflowState | None:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                f'SELECT state FROM "{self.schema}".runs WHERE case_id = %s', (case_id,)
            )
            row = await result.fetchone()
        return WorkflowState.model_validate(row["state"]) if row else None

    async def save_memory(self, case_id: str, memory: dict[str, object]) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                f"""
                INSERT INTO "{self.schema}".selected_memory (case_id, memory)
                VALUES (%s, %s::jsonb)
                ON CONFLICT (case_id) DO UPDATE SET
                    memory = EXCLUDED.memory, updated_at = now()
                """,
                (case_id, json.dumps(memory, default=str)),
            )
            await conn.commit()

    async def get_memory(self, case_id: str) -> dict[str, object]:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                f'SELECT memory FROM "{self.schema}".selected_memory WHERE case_id = %s',
                (case_id,),
            )
            row = await result.fetchone()
        return row["memory"] if row else {}

    async def append_event(self, event: DurableEvent) -> DurableEvent:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                f"""
                INSERT INTO "{self.schema}".execution_events
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
            await conn.commit()
        return event.model_copy(update={"sequence": row["sequence"]})

    async def list_events(self, run_id: str, after: int = 0) -> list[DurableEvent]:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                f"""
                SELECT sequence, event_id::text, case_id, run_id, event_type, node, transition,
                       checkpoint_id, retry_attempt, idempotency_key, summary, payload, created_at
                FROM "{self.schema}".execution_events
                WHERE run_id = %s AND sequence > %s ORDER BY sequence
                """,
                (run_id, after),
            )
            rows = await result.fetchall()
        return [DurableEvent.model_validate(row) for row in rows]

    async def save_approval(
        self, run_id: str, checkpoint_id: str, response: ApprovalResponse
    ) -> None:
        async with self.pool.connection() as conn:
            try:
                await conn.execute(
                    f"""
                    INSERT INTO "{self.schema}".approvals (run_id, checkpoint_id, response)
                    VALUES (%s, %s, %s::jsonb)
                    """,
                    (run_id, checkpoint_id, response.model_dump_json()),
                )
                await conn.commit()
            except Exception:
                await conn.rollback()
                result = await conn.execute(
                    f"""
                    SELECT checkpoint_id, response
                    FROM "{self.schema}".approvals WHERE run_id = %s
                    """,
                    (run_id,),
                )
                row = await result.fetchone()
                same_response = row and row["response"] == response.model_dump(mode="json")
                if not row or row["checkpoint_id"] != checkpoint_id or not same_response:
                    raise ValueError("approval already resolved with another decision") from None

    async def get_approval(self, run_id: str) -> ApprovalResponse | None:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                f'SELECT response FROM "{self.schema}".approvals WHERE run_id = %s', (run_id,)
            )
            row = await result.fetchone()
        return ApprovalResponse.model_validate(row["response"]) if row else None

    async def save_outcome(self, outcome: WorkflowOutcome) -> None:
        async with self.pool.connection() as conn:
            await conn.execute(
                f"""
                INSERT INTO "{self.schema}".outcomes (run_id, outcome)
                VALUES (%s, %s::jsonb)
                ON CONFLICT (run_id) DO UPDATE SET outcome = EXCLUDED.outcome
                """,
                (outcome.run_id, outcome.model_dump_json()),
            )
            await conn.commit()

    async def get_outcome(self, run_id: str) -> WorkflowOutcome | None:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                f'SELECT outcome FROM "{self.schema}".outcomes WHERE run_id = %s', (run_id,)
            )
            row = await result.fetchone()
        return WorkflowOutcome.model_validate(row["outcome"]) if row else None

    async def set_checkpoint(self, run_id: str, checkpoint_id: str) -> None:
        state = await self.get_state(run_id)
        if state:
            await self.save_state(state.model_copy(update={"checkpoint_id": checkpoint_id}))

    async def get_refund(self, idempotency_key: str) -> RefundLedgerEntry | None:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                f"""
                SELECT idempotency_key, request_fingerprint, account_id, charge_id,
                       amount, currency, refund_id, refund, created_by_run_id, created_at
                FROM "{self.schema}".refund_ledger
                WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            )
            row = await result.fetchone()
        return RefundLedgerEntry.model_validate(row) if row else None

    async def store_refund(
        self, entry: RefundLedgerEntry
    ) -> tuple[RefundLedgerEntry, bool]:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                f"""
                INSERT INTO "{self.schema}".refund_ledger (
                    idempotency_key, request_fingerprint, account_id, charge_id,
                    amount, currency, refund_id, refund, created_by_run_id, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING idempotency_key
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
            await conn.commit()
        stored = await self.get_refund(entry.idempotency_key)
        if stored is None:
            raise RuntimeError("refund ledger write did not produce a durable row")
        if stored.request_fingerprint != entry.request_fingerprint:
            raise RefundIdempotencyConflictError(
                "idempotency key is already bound to a different refund request"
            )
        return stored, created

    async def count_refunds(self, idempotency_key: str) -> int:
        async with self.pool.connection() as conn:
            result = await conn.execute(
                f"""
                SELECT count(*) AS count
                FROM "{self.schema}".refund_ledger
                WHERE idempotency_key = %s
                """,
                (idempotency_key,),
            )
            row = await result.fetchone()
        return int(row["count"])
