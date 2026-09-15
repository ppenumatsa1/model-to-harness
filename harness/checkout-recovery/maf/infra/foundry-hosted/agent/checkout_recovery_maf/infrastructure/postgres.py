import json
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any

from model_to_harness_shared import CheckoutApprovalDecision, CheckoutSimulator
from psycopg import Connection
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from checkout_recovery_maf.application.models import AuditEvent, CaseRecord, RemediationIntent


class PostgresCaseRepository:
    """PostgreSQL authority for case state, audit history, and remediation intent."""

    def __init__(self, database_url: str) -> None:
        self._pool = ConnectionPool(
            conninfo=database_url,
            kwargs={"row_factory": dict_row},
            open=False,
        )
        self._active: ContextVar[Connection | None] = ContextVar(
            "checkout_connection", default=None
        )

    @contextmanager
    def connection(self) -> Iterator[Connection]:
        active = self._active.get()
        if active is not None:
            yield active
        else:
            with self._pool.connection() as connection:
                yield connection

    @contextmanager
    def transaction(self, case_id: str) -> Iterator[None]:
        with self._pool.connection() as connection:
            token = self._active.set(connection)
            try:
                connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (case_id,)
                )
                yield
            finally:
                self._active.reset(token)

    def ready(self) -> bool:
        with self.connection() as connection:
            connection.execute("SELECT case_id FROM checkout_recovery_maf_sessions LIMIT 0")
        return True

    def save_framework_state(self, case_id: str, state: dict[str, Any]) -> None:
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO checkout_recovery_maf_sessions (case_id, framework_state)
                   VALUES (%s, %s::jsonb)
                   ON CONFLICT (case_id) DO UPDATE SET
                   framework_state = EXCLUDED.framework_state, updated_at = now()""",
                (case_id, json.dumps(state)),
            )

    def open(self) -> None:
        self._pool.open(wait=True)

    def close(self) -> None:
        self._pool.close()

    def create(self, case: CaseRecord, simulator: CheckoutSimulator) -> None:
        payload = case.model_dump_json()
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO checkout_recovery_cases
                    (case_id, run_id, order_id, fixture_id, phase, state, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)
                """,
                (
                    case.case_id,
                    case.run_id,
                    case.order_id,
                    case.fixture_id,
                    case.phase.value,
                    payload,
                    case.created_at,
                    case.updated_at,
                ),
            )

    def get(self, case_id: str) -> CaseRecord | None:
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT state FROM checkout_recovery_cases WHERE case_id = %s",
                (case_id,),
            )
            row: dict[str, Any] | None = cursor.fetchone()
        if row is None:
            return None
        return CaseRecord.model_validate(row["state"])

    def save(self, case: CaseRecord) -> None:
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                UPDATE checkout_recovery_cases
                SET phase = %s, state = %s::jsonb, updated_at = %s
                WHERE case_id = %s
                """,
                (case.phase.value, case.model_dump_json(), case.updated_at, case.case_id),
            )
            if cursor.rowcount != 1:
                raise KeyError("cannot save an unknown case")

    def save_approval(
        self, case_id: str, decision: CheckoutApprovalDecision, reviewer_id: str
    ) -> None:
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO checkout_recovery_approvals
                    (case_id, decision, reviewer_id, recorded_at)
                VALUES (%s, %s, %s, now())
                ON CONFLICT (case_id) DO NOTHING
                """,
                (case_id, decision.value, reviewer_id),
            )
            cursor.execute(
                """
                SELECT decision, reviewer_id
                FROM checkout_recovery_approvals
                WHERE case_id = %s
                """,
                (case_id,),
            )
            row: dict[str, Any] | None = cursor.fetchone()
        if row != {"decision": decision.value, "reviewer_id": reviewer_id}:
            raise ValueError("case approval is immutable")

    def simulator_for(self, case: CaseRecord) -> CheckoutSimulator:
        return CheckoutSimulator.from_snapshot(case.simulator_snapshot)

    def append_event(self, case_id: str, event: AuditEvent) -> None:
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO checkout_recovery_audit_events (case_id, code, summary, occurred_at)
                VALUES (%s, %s, %s, %s)
                """,
                (case_id, event.code.value, event.summary, event.occurred_at),
            )

    def events_for(self, case_id: str) -> tuple[AuditEvent, ...]:
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT code, summary, occurred_at
                FROM checkout_recovery_audit_events
                WHERE case_id = %s
                ORDER BY event_id
                """,
                (case_id,),
            )
            rows: list[dict[str, Any]] = cursor.fetchall()
        return tuple(AuditEvent.model_validate(row) for row in rows)

    def remediation_intent_for(self, case_id: str) -> RemediationIntent | None:
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT operation_id::text, request_fingerprint, action
                FROM checkout_recovery_remediation_ledger
                WHERE case_id = %s
                """,
                (case_id,),
            )
            row: dict[str, Any] | None = cursor.fetchone()
        if row is None:
            return None
        return RemediationIntent.model_validate(row)

    def save_remediation_intent(self, case_id: str, intent: RemediationIntent) -> None:
        with self.connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO checkout_recovery_remediation_ledger
                    (case_id, operation_id, request_fingerprint, action, created_at)
                VALUES (%s, %s, %s, %s, now())
                ON CONFLICT (case_id) DO NOTHING
                """,
                (
                    case_id,
                    intent.operation_id,
                    intent.request_fingerprint,
                    intent.action.value,
                ),
            )
        existing = self.remediation_intent_for(case_id)
        if existing != intent:
            raise ValueError("case remediation intent is immutable")
