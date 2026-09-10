from __future__ import annotations

from copy import deepcopy

from agent_framework import WorkflowCheckpoint, WorkflowCheckpointException

from .repository import InMemoryRepository


class InMemoryRunCheckpointStorage:
    """Run-scoped checkpoint adapter backed by the explicitly retained test repository."""

    def __init__(self, repository: InMemoryRepository, run_id: str) -> None:
        self.repository = repository
        self.run_id = run_id
        self.checkpoints = repository.run_checkpoints.setdefault(run_id, {})

    async def save(self, checkpoint: WorkflowCheckpoint) -> str:
        existing = self.checkpoints.get(checkpoint.checkpoint_id)
        if existing is not None and existing.workflow_name != checkpoint.workflow_name:
            raise WorkflowCheckpointException("checkpoint belongs to another workflow")
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
        return [
            item.checkpoint_id for item in await self.list_checkpoints(workflow_name=workflow_name)
        ]

    async def get_latest(self, *, workflow_name: str) -> WorkflowCheckpoint | None:
        items = await self.list_checkpoints(workflow_name=workflow_name)
        return items[-1] if items else None

    async def delete(self, checkpoint_id: str) -> bool:
        return self.checkpoints.pop(checkpoint_id, None) is not None
