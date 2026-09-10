from typing import Any

from agent_framework import WorkflowEvent

from ..application.audit import Audit
from ..application.models import WorkflowState


async def persist_native_events(
    audit: Audit,
    state: WorkflowState,
    events: list[WorkflowEvent[Any]],
    status_events: list[WorkflowEvent[Any]],
) -> None:
    seen: set[tuple[object, ...]] = set()
    for event in [*events, *status_events]:
        event_data = vars(event)
        event_type = str(event_data["type"])
        identity = (
            event_type,
            event_data.get("executor_id"),
            event_data.get("_request_id"),
            event_data.get("iteration"),
            str(event_data.get("state")),
        )
        if identity in seen:
            continue
        seen.add(identity)
        await audit.emit(
            state,
            f"maf.native.{event_type}",
            f"MAF emitted {event_type}.",
            node=event_data.get("executor_id") or event_data.get("_source_executor_id"),
            payload={
                "iteration": event_data.get("iteration"),
                "state": str(event_data["state"]) if event_data.get("state") is not None else None,
            },
        )
