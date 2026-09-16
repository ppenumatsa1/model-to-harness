from typing import Any

from .records import EventData


def audit_data(
    data: dict[str, Any] | None = None, *, actor_id: str | None = None
) -> dict[str, Any]:
    return EventData.model_validate(
        {
            **(data or {}),
            "audit_version": 2,
            "actor_type": "human" if actor_id is not None else "system",
            "actor_id": actor_id if actor_id is not None else "langgraph-workflow",
            "actor_source": "operator_supplied" if actor_id is not None else "system",
        }
    ).model_dump(exclude_unset=True)
