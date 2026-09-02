from __future__ import annotations

import json
from copy import deepcopy

from agent_framework import WorkflowCheckpoint, WorkflowCheckpointException
from agent_framework._workflows._checkpoint_encoding import (  # type: ignore[import-not-found]
    decode_checkpoint_value,
    encode_checkpoint_value,
)

from .repository import InMemoryRepository, PostgresRepository

_ALLOWED_CHECKPOINT_TYPES = frozenset(
    {
        "maf_double_charge.models:ApprovalRequest",
        "maf_double_charge.models:ApprovalResponse",
        "maf_double_charge.models:ApprovalDecision",
        "maf_double_charge.models:BranchResult",
        "maf_double_charge.models:NodeStatus",
        "maf_double_charge.models:RunStatus",
        "maf_double_charge.models:WorkflowState",
        "pydantic_core._pydantic_core:TzInfo",
    }
)


class InMemoryRunCheckpointStorage:
    def __init__(self, repository: InMemoryRepository, run_id: str) -> None:
        self.repository = repository
        self.run_id = run_id
        self.checkpoints: dict[str, WorkflowCheckpoint] = {}

    async def save(self, checkpoint: WorkflowCheckpoint) -> str:
        self.checkpoints[checkpoint.checkpoint_id] = deepcopy(checkpoint)
        await self.repository.set_checkpoint(self.run_id, checkpoint.checkpoint_id)
        return checkpoint.checkpoint_id

    async def load(self, checkpoint_id: str) -> WorkflowCheckpoint:
        try:
            return deepcopy(self.checkpoints[checkpoint_id])
        except KeyError as exc:
            raise WorkflowCheckpointException(f"checkpoint not found: {checkpoint_id}") from exc

    async def list_checkpoints(self, *, workflow_name: str) -> list[WorkflowCheckpoint]:
        return [
            deepcopy(item)
            for item in self.checkpoints.values()
            if item.workflow_name == workflow_name
        ]

    async def list_checkpoint_ids(self, *, workflow_name: str) -> list[str]:
        items = await self.list_checkpoints(workflow_name=workflow_name)
        return [item.checkpoint_id for item in items]

    async def get_latest(self, *, workflow_name: str) -> WorkflowCheckpoint | None:
        items = await self.list_checkpoints(workflow_name=workflow_name)
        return items[-1] if items else None

    async def delete(self, checkpoint_id: str) -> bool:
        return self.checkpoints.pop(checkpoint_id, None) is not None


class PostgresRunCheckpointStorage:
    def __init__(self, repository: PostgresRepository, run_id: str) -> None:
        self.repository = repository
        self.run_id = run_id

    async def save(self, checkpoint: WorkflowCheckpoint) -> str:
        # MAF's FileCheckpointStorage uses this codec for complex workflow values.
        # Keeping the import here isolates the one SDK-internal compatibility seam.
        encoded = encode_checkpoint_value(checkpoint.to_dict())
        async with self.repository.pool.connection() as conn:
            await conn.execute(
                f"""
                INSERT INTO "{self.repository.schema}".maf_checkpoints
                    (checkpoint_id, workflow_name, run_id, checkpoint)
                VALUES (%s, %s, %s, %s::jsonb)
                ON CONFLICT (checkpoint_id) DO UPDATE SET checkpoint = EXCLUDED.checkpoint
                """,
                (
                    checkpoint.checkpoint_id,
                    checkpoint.workflow_name,
                    self.run_id,
                    json.dumps(encoded),
                ),
            )
            await conn.commit()
        await self.repository.set_checkpoint(self.run_id, checkpoint.checkpoint_id)
        return checkpoint.checkpoint_id

    async def load(self, checkpoint_id: str) -> WorkflowCheckpoint:
        async with self.repository.pool.connection() as conn:
            result = await conn.execute(
                f"""
                SELECT checkpoint FROM "{self.repository.schema}".maf_checkpoints
                WHERE checkpoint_id = %s AND run_id = %s
                """,
                (checkpoint_id, self.run_id),
            )
            row = await result.fetchone()
        if not row:
            raise WorkflowCheckpointException(f"checkpoint not found: {checkpoint_id}")
        decoded = decode_checkpoint_value(
            row["checkpoint"], allowed_types=_ALLOWED_CHECKPOINT_TYPES
        )
        return WorkflowCheckpoint.from_dict(decoded)

    async def list_checkpoints(self, *, workflow_name: str) -> list[WorkflowCheckpoint]:
        async with self.repository.pool.connection() as conn:
            result = await conn.execute(
                f"""
                SELECT checkpoint FROM "{self.repository.schema}".maf_checkpoints
                WHERE workflow_name = %s AND run_id = %s ORDER BY created_at
                """,
                (workflow_name, self.run_id),
            )
            rows = await result.fetchall()
        return [
            WorkflowCheckpoint.from_dict(
                decode_checkpoint_value(
                    row["checkpoint"], allowed_types=_ALLOWED_CHECKPOINT_TYPES
                )
            )
            for row in rows
        ]

    async def list_checkpoint_ids(self, *, workflow_name: str) -> list[str]:
        items = await self.list_checkpoints(workflow_name=workflow_name)
        return [item.checkpoint_id for item in items]

    async def get_latest(self, *, workflow_name: str) -> WorkflowCheckpoint | None:
        items = await self.list_checkpoints(workflow_name=workflow_name)
        return items[-1] if items else None

    async def delete(self, checkpoint_id: str) -> bool:
        async with self.repository.pool.connection() as conn:
            result = await conn.execute(
                f"""
                DELETE FROM "{self.repository.schema}".maf_checkpoints
                WHERE checkpoint_id = %s AND run_id = %s
                """,
                (checkpoint_id, self.run_id),
            )
            await conn.commit()
        return result.rowcount > 0


def checkpoint_storage_for(repository: object, run_id: str):
    if isinstance(repository, InMemoryRepository):
        return InMemoryRunCheckpointStorage(repository, run_id)
    if isinstance(repository, PostgresRepository):
        return PostgresRunCheckpointStorage(repository, run_id)
    raise TypeError(f"unsupported repository type: {type(repository).__name__}")
