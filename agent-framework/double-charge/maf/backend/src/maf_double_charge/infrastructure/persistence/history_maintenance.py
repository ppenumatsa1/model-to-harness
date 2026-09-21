from __future__ import annotations

import json
from datetime import datetime

from psycopg import sql

from ...application.audit import BUSINESS_AUDIT_VERSION
from .postgres import PostgresRepository

_TABLE_KEYS = {
    "execution_events": "run_id",
    "approvals": "run_id",
    "outcomes": "run_id",
    "maf_checkpoints": "run_id",
    "selected_memory": "case_id",
    "refund_ledger": "created_by_run_id",
    "runs": "run_id",
}


async def prune_incompatible_history(
    repository: PostgresRepository,
    *,
    before: datetime,
    apply: bool = False,
    expected_count: int | None = None,
) -> dict[str, int]:
    if before.tzinfo is None or before.utcoffset() is None:
        raise ValueError("History cutoff must include a timezone.")
    if apply and (expected_count is None or expected_count < 0):
        raise ValueError("Apply requires an explicit nonnegative expected case count.")
    async with repository.pool.connection() as conn:
        if apply:
            await conn.execute("SET LOCAL lock_timeout = '5s'")
            await conn.execute(
                sql.SQL("LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE").format(
                    sql.SQL(", ").join(
                        sql.Identifier(repository.schema, name)
                        for name in ("runs", *tuple(_TABLE_KEYS)[:-1])
                    )
                )
            )
        result = await conn.execute(
            """
            SELECT r.run_id, r.case_id, r.status FROM runs r
            WHERE r.created_at < %s AND (
                NOT EXISTS (
                    SELECT 1 FROM execution_events e WHERE e.run_id = r.run_id
                    AND e.event_type = 'run.started'
                    AND e.payload @> %s::jsonb
                    AND jsonb_typeof(e.payload->'actor_id') = 'string'
                    AND btrim(e.payload->>'actor_id') <> ''
                )
                OR EXISTS (
                    SELECT 1 FROM execution_events e WHERE e.run_id = r.run_id
                    AND NOT COALESCE(
                        e.payload->'audit_version' = to_jsonb(%s::int)
                        AND jsonb_typeof(e.payload->'actor_id') = 'string'
                        AND btrim(e.payload->>'actor_id') <> ''
                        AND ((e.payload->>'actor_type' = 'human'
                              AND e.payload->>'actor_source' = 'operator_supplied')
                             OR (e.payload->>'actor_type' = 'system'
                                 AND e.payload->>'actor_source' = 'system'
                                 AND e.payload->>'actor_id' = 'maf-workflow')), false)
                )
            ) ORDER BY r.run_id
            """,
            (
                before,
                json.dumps({"audit_version": BUSINESS_AUDIT_VERSION, "actor_type": "human",
                            "actor_source": "operator_supplied"}),
                BUSINESS_AUDIT_VERSION,
            ),
        )
        targets = await result.fetchall()
        run_ids = [row["run_id"] for row in targets]
        case_ids = [row["case_id"] for row in targets]
        if apply and len(targets) != expected_count:
            raise ValueError("Candidate count changed; preview again before deleting.")
        if apply and any(row["status"] == "running" for row in targets):
            raise ValueError("Incompatible running cases exist; stop execution before cleanup.")
        shared = await conn.execute(
            """
            SELECT count(*) AS count FROM refund_ledger l
            WHERE l.created_by_run_id = ANY(%s) AND EXISTS (
                SELECT 1 FROM runs r WHERE NOT (r.run_id = ANY(%s))
                AND (r.state->>'idempotency_key' = l.idempotency_key
                     OR r.state->>'refund_id' = l.refund_id)
            )
            """,
            (run_ids, run_ids),
        )
        shared_count = (await shared.fetchone())["count"]
        if apply and shared_count:
            raise ValueError("Retained cases reference candidate refund records; cleanup refused.")
        counts = {"running_cases": sum(row["status"] == "running" for row in targets),
                  "shared_refunds": shared_count}
        for table, key in _TABLE_KEYS.items():
            ids = case_ids if key == "case_id" else run_ids
            selected = await conn.execute(
                sql.SQL("SELECT count(*) AS count FROM {} WHERE {} = ANY(%s)").format(
                    sql.Identifier(repository.schema, table), sql.Identifier(key)
                ),
                (ids,),
            )
            counts[table] = (await selected.fetchone())["count"]
        if apply:
            for table, key in _TABLE_KEYS.items():
                await conn.execute(
                    sql.SQL("DELETE FROM {} WHERE {} = ANY(%s)").format(
                        sql.Identifier(repository.schema, table), sql.Identifier(key)
                    ),
                    (case_ids if key == "case_id" else run_ids,),
                )
    return counts
