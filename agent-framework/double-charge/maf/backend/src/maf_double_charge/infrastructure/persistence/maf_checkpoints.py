from __future__ import annotations

import json

from agent_framework import WorkflowCheckpoint, WorkflowCheckpointException

from .checkpoint_codec import decode_checkpoint, encode_checkpoint
from .postgres import PostgresRepository


class PostgresRunCheckpointStorage:
    def __init__(self, repository: PostgresRepository, run_id: str) -> None:
        self.repository = repository
        self.run_id = run_id

    async def save(self, checkpoint: WorkflowCheckpoint) -> str:
        async with self.repository.pool.connection() as conn:
            result = await conn.execute(
                """
                INSERT INTO maf_checkpoints (checkpoint_id, workflow_name, run_id, checkpoint)
                VALUES (%s, %s, %s, %s::jsonb)
                ON CONFLICT (checkpoint_id) DO UPDATE SET checkpoint = EXCLUDED.checkpoint
                WHERE maf_checkpoints.run_id = EXCLUDED.run_id
                  AND maf_checkpoints.workflow_name = EXCLUDED.workflow_name
                RETURNING checkpoint_id
                """,
                (
                    checkpoint.checkpoint_id,
                    checkpoint.workflow_name,
                    self.run_id,
                    json.dumps(encode_checkpoint(checkpoint)),
                ),
            )
            if await result.fetchone() is None:
                raise WorkflowCheckpointException("checkpoint belongs to another run or workflow")
            # A checkpoint and the business-state pointer become durable together.
            await conn.execute(
                """
                UPDATE runs SET checkpoint_id = %s,
                    state = jsonb_set(state, '{checkpoint_id}', to_jsonb(%s::text)),
                    updated_at = now()
                WHERE run_id = %s
                """,
                (checkpoint.checkpoint_id, checkpoint.checkpoint_id, self.run_id),
            )
        return checkpoint.checkpoint_id

    async def load(self, checkpoint_id: str) -> WorkflowCheckpoint:
        async with self.repository.pool.connection() as conn:
            result = await conn.execute(
                "SELECT checkpoint FROM maf_checkpoints WHERE checkpoint_id = %s AND run_id = %s",
                (checkpoint_id, self.run_id),
            )
            row = await result.fetchone()
        if row is None:
            raise WorkflowCheckpointException(f"checkpoint not found: {checkpoint_id}")
        return decode_checkpoint(row["checkpoint"])

    async def list_checkpoints(self, *, workflow_name: str) -> list[WorkflowCheckpoint]:
        async with self.repository.pool.connection() as conn:
            result = await conn.execute(
                """
                SELECT checkpoint FROM maf_checkpoints
                WHERE workflow_name = %s AND run_id = %s ORDER BY created_at, checkpoint_id
                """,
                (workflow_name, self.run_id),
            )
            rows = await result.fetchall()
        return [decode_checkpoint(row["checkpoint"]) for row in rows]

    async def list_checkpoint_ids(self, *, workflow_name: str) -> list[str]:
        items = await self.list_checkpoints(workflow_name=workflow_name)
        return [item.checkpoint_id for item in items]

    async def get_latest(self, *, workflow_name: str) -> WorkflowCheckpoint | None:
        items = await self.list_checkpoints(workflow_name=workflow_name)
        return items[-1] if items else None

    async def delete(self, checkpoint_id: str) -> bool:
        async with self.repository.pool.connection() as conn:
            result = await conn.execute(
                "DELETE FROM maf_checkpoints WHERE checkpoint_id = %s AND run_id = %s",
                (checkpoint_id, self.run_id),
            )
        return result.rowcount > 0
