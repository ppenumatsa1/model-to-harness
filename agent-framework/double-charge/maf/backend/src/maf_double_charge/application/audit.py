from __future__ import annotations

import logging
from typing import Any

from .models import DurableEvent, WorkflowState
from .ports import Repository

logger = logging.getLogger(__name__)


class Audit:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    async def emit(
        self,
        state: WorkflowState,
        event_type: str,
        summary: str,
        *,
        node: str | None = None,
        transition: str | None = None,
        retry_attempt: int | None = None,
        checkpoint_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        await self.repository.append_event(
            DurableEvent(
                case_id=state.case_id,
                run_id=state.run_id,
                event_type=event_type,
                node=node,
                transition=transition,
                checkpoint_id=checkpoint_id,
                retry_attempt=retry_attempt,
                idempotency_key=(
                    state.idempotency_key
                    if event_type.startswith(("refund.", "tool."))
                    and node in {"submit_refund", "verify_refund"}
                    else None
                ),
                summary=summary,
                payload=payload or {},
            )
        )
        logger.info(
            "Workflow event %s",
            event_type,
            extra={
                "event_type": event_type,
                "case_id": state.case_id,
                "run_id": state.run_id,
                "node": node,
                "transition": transition,
                "checkpoint_id": checkpoint_id,
                "retry_attempt": retry_attempt,
            },
        )

    async def save(self, state: WorkflowState) -> WorkflowState:
        await self.repository.save_state(state)
        return state

    async def node_started(self, state: WorkflowState, node: str) -> None:
        await self.emit(state, "node.started", f"{node} started.", node=node)

    async def node_completed(self, state: WorkflowState, node: str, summary: str) -> None:
        await self.emit(state, "node.completed", summary, node=node)

    async def edge(self, state: WorkflowState, source: str, target: str, reason: str) -> None:
        await self.emit(
            state, "edge.selected", reason, node=source, transition=f"{source}->{target}"
        )
