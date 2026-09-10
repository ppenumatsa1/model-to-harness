import json
from typing import Any

from ..application.records import NativeEvent


def project_events(event: NativeEvent) -> list[dict[str, Any]]:
    base = {
        "timestamp": event.timestamp.isoformat(),
        "runId": event.run_id,
        "sequence": event.sequence,
    }
    if event.event_type == "run_started":
        return [{**base, "type": "RUN_STARTED", "threadId": event.case_id}]
    if event.event_type in {"run_completed", "run_failed"}:
        return [
            {
                **base,
                "type": "RUN_FINISHED" if event.event_type == "run_completed" else "RUN_ERROR",
                "result": {"summary": event.summary, "status": event.status},
            }
        ]
    if event.event_type == "node_started":
        return [{**base, "type": "STEP_STARTED", "stepName": event.node}]
    if event.event_type in {"parallel_branch_completed", "parallel_branch_joined"}:
        return [
            {
                **base,
                "type": "STEP_FINISHED",
                "stepName": event.node,
                "result": {"summary": event.summary, **event.data},
            }
        ]
    if event.event_type == "tool_call_started":
        return [
            {
                **base,
                "type": "TOOL_CALL_START",
                "toolCallId": event.data.get("tool_call_id", event.event_id),
                "toolCallName": event.data.get("tool", "allowlisted-tool"),
                "parentMessageId": event.run_id,
            }
        ]
    if event.event_type in {"tool_call_succeeded", "tool_call_failed"}:
        tool_call_id = event.data.get("tool_call_id", event.event_id)
        return [
            {
                **base,
                "type": "TOOL_CALL_END",
                "toolCallId": tool_call_id,
            },
            {
                **base,
                "type": "TOOL_CALL_RESULT",
                "messageId": f"tool-result:{event.event_id}",
                "toolCallId": tool_call_id,
                "content": json.dumps(
                    {"summary": event.summary, "status": event.status},
                    separators=(",", ":"),
                ),
                "role": "tool",
            },
        ]
    return [
        {
            **base,
            "type": "CUSTOM",
            "name": event.event_type,
            "value": {
                "node": event.node,
                "status": event.status,
                "summary": event.summary,
                **event.data,
            },
        }
    ]
