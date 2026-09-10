"""Read-only durable evidence for explicitly listed API/hosted acceptance runs."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path

from api_harness import SCENARIOS, AcceptanceError, require, verify_outcome
from psycopg import AsyncConnection, Error, sql
from psycopg.rows import dict_row
from release import ReleaseError, Runner, environment_values


def records(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text().splitlines():
        if not line.startswith("{"):
            continue
        value = json.loads(line)
        if isinstance(value, dict) and "scenario" in value:
            rows.append(value)
    require(len(rows) == len(SCENARIOS), "Evidence requires one full seven-scenario harness output")
    require(
        {row.get("scenario") for row in rows} == {case[0] for case in SCENARIOS},
        "Evidence scenario set does not match the reviewed matrix",
    )
    for key in ("run_id", "case_id"):
        require(
            all(isinstance(row.get(key), str) and row[key] for row in rows)
            and len({row[key] for row in rows}) == len(rows),
            "Evidence contains missing or duplicate durable identifiers",
        )
    return rows


async def verify(database: str, schemas: tuple[str, str], rows: list[dict]) -> None:
    for schema in schemas:
        require(
            re.fullmatch(r"langgraph_[a-z0-9_]{1,54}", schema) is not None,
            "Evidence schemas must be explicitly LangGraph-owned",
        )
    app, checkpoint = map(sql.Identifier, schemas)
    async with await AsyncConnection.connect(
        database,
        autocommit=True,
        row_factory=dict_row,
        options="-c default_transaction_read_only=on",
        connect_timeout=15,
    ) as connection:
        for row in rows:
            scenario, decision, terminal = next(
                case for case in SCENARIOS if case[0] == row["scenario"]
            )
            cursor = await connection.execute(
                sql.SQL("SELECT run_id, case_id, outcome FROM {}.runs WHERE run_id=%s").format(app),
                (row["run_id"],),
            )
            run = await cursor.fetchone()
            require(
                run is not None and run["case_id"] == row["case_id"],
                "Durable run identity mismatch",
            )
            verify_outcome(run["outcome"], terminal)
            cursor = await connection.execute(
                sql.SQL(
                    "SELECT refund_id, request_fingerprint FROM {}.refunds WHERE run_id=%s"
                ).format(app),
                (row["run_id"],),
            )
            refunds = await cursor.fetchall()
            expected_refunds = 1 if terminal in {"completed_refunded", "manual_review"} else 0
            require(len(refunds) == expected_refunds, "Durable refund count does not match outcome")
            if refunds:
                require(
                    bool(refunds[0]["request_fingerprint"]), "Durable refund fingerprint missing"
                )
            if terminal == "completed_refunded":
                require(
                    refunds[0]["refund_id"] == run["outcome"]["refund_id"],
                    "Verified outcome differs from durable refund identifier",
                )
            cursor = await connection.execute(
                sql.SQL("SELECT decision, consumed FROM {}.approvals WHERE run_id=%s").format(app),
                (row["run_id"],),
            )
            approval = await cursor.fetchone()
            require(
                (approval is None and decision is None)
                or (
                    approval is not None
                    and approval["decision"] == decision
                    and approval["consumed"] is True
                ),
                "Durable approval does not match explicit consumed decision",
            )
            cursor = await connection.execute(
                sql.SQL("SELECT count(*) AS count FROM {}.checkpoints WHERE thread_id=%s").format(
                    checkpoint
                ),
                (f"langgraph:{row['run_id']}",),
            )
            checkpoint_count = (await cursor.fetchone())["count"]
            require(checkpoint_count > 0, "Native checkpoints missing for run thread")
            cursor = await connection.execute(
                sql.SQL("SELECT count(*) AS count FROM {}.events WHERE run_id=%s").format(app),
                (row["run_id"],),
            )
            event_count = (await cursor.fetchone())["count"]
            require(event_count > 0, "Durable audit events missing")
            print(
                json.dumps(
                    {
                        "scenario": scenario,
                        "run_id": row["run_id"],
                        "terminal_status": terminal,
                        "refund_rows": len(refunds),
                        "events": event_count,
                        "checkpoints": checkpoint_count,
                        "read_only": True,
                        "passed": True,
                    }
                ),
                flush=True,
            )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", default="langgraph")
    parser.add_argument("--schema", default="langgraph_app_cutover")
    parser.add_argument("--checkpoint-schema", default="langgraph_checkpoints_cutover")
    parser.add_argument("--records", required=True, type=Path)
    args = parser.parse_args()
    rows = records(args.records)
    values = environment_values(Runner(), args.environment)
    schemas = (args.schema, args.checkpoint_schema)
    require(
        (values.get("LANGGRAPH_SCHEMA"), values.get("LANGGRAPH_CHECKPOINT_SCHEMA")) == schemas,
        "Evidence schemas differ from selected deployment",
    )
    asyncio.run(verify(values["DATABASE_URL"], schemas, rows))


if __name__ == "__main__":
    try:
        main()
    except AcceptanceError as error:
        raise SystemExit(str(error)) from None
    except (Error, ReleaseError, OSError, ValueError, KeyError) as error:
        raise SystemExit(
            f"Business evidence failed ({type(error).__name__}); details suppressed"
        ) from None
