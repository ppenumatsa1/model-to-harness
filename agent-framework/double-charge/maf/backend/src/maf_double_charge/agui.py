from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ag_ui.core import (
    CustomEvent,
    RunErrorEvent,
    RunFinishedEvent,
    RunStartedEvent,
    StateSnapshotEvent,
    StepFinishedEvent,
    StepStartedEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)

from .models import DurableEvent, WorkflowState


def _dump(event: Any) -> dict[str, Any]:
    return event.model_dump(mode="json", by_alias=True, exclude_none=True)


def project_event(event: DurableEvent, state: WorkflowState | None = None) -> list[dict[str, Any]]:
    metadata = {"sequence": event.sequence, "source": "maf_durable_audit"}
    if event.event_type == "run.started":
        return [
            _dump(
                RunStartedEvent(
                    threadId=event.case_id,
                    runId=event.run_id,
                    metadata=metadata,
                )
            )
        ]
    if event.event_type == "run.completed":
        return [
            _dump(
                RunFinishedEvent(
                    threadId=event.case_id,
                    runId=event.run_id,
                    result={"summary": event.summary},
                    metadata=metadata,
                )
            )
        ]
    if event.event_type == "run.failed":
        return [
            _dump(
                RunErrorEvent(
                    message=event.summary,
                    code=(state.failure_code if state else "workflow_failed"),
                    metadata=metadata,
                )
            )
        ]
    if event.event_type == "node.started" and event.node:
        return [_dump(StepStartedEvent(stepName=event.node, metadata=metadata))]
    if event.event_type == "node.completed" and event.node:
        return [_dump(StepFinishedEvent(stepName=event.node, metadata=metadata))]
    if event.event_type == "tool.call.started":
        tool_id = f"{event.run_id}:{event.node}:{event.retry_attempt or 1}"
        return [
            _dump(
                ToolCallStartEvent(
                    toolCallId=tool_id,
                    toolCallName=str(event.payload.get("tool", event.node or "tool")),
                    metadata=metadata,
                )
            )
        ]
    if event.event_type in {"tool.call.succeeded", "tool.call.failed"}:
        tool_id = f"{event.run_id}:{event.node}:{event.retry_attempt or 1}"
        content = {"status": "succeeded" if event.event_type.endswith("succeeded") else "failed"}
        return [
            _dump(ToolCallEndEvent(toolCallId=tool_id, metadata=metadata)),
            _dump(
                ToolCallResultEvent(
                    messageId=f"result:{tool_id}",
                    toolCallId=tool_id,
                    content=str(content),
                    role="tool",
                    metadata=metadata,
                )
            ),
        ]
    if event.event_type == "tool.call.retried":
        return [
            _dump(
                CustomEvent(
                    name="tool_retry",
                    value={
                        "node": event.node,
                        "attempt": event.retry_attempt,
                        "summary": event.summary,
                    },
                    metadata=metadata,
                )
            )
        ]
    if event.event_type == "edge.selected":
        return [
            _dump(
                CustomEvent(
                    name="edge_selected",
                    value={"transition": event.transition, "summary": event.summary},
                    metadata=metadata,
                )
            )
        ]
    if event.event_type in {
        "parallel.started",
        "parallel.branch.completed",
        "parallel.joined",
        "decision.summary",
        "checkpoint.created",
        "approval.requested",
        "approval.recorded",
        "approval.resolved",
        "refund.idempotency.lookup",
        "refund.verification",
        "notification.sent",
        "workflow.resumed",
    }:
        return [
            _dump(
                CustomEvent(
                    name=event.event_type.replace(".", "_"),
                    value={
                        "node": event.node,
                        "summary": event.summary,
                        "details": event.payload,
                    },
                    metadata=metadata,
                )
            )
        ]
    if event.event_type.startswith("model.call."):
        return [
            _dump(
                CustomEvent(
                    name=event.event_type.replace(".", "_"),
                    value={"node": event.node, "summary": event.summary, **event.payload},
                    metadata=metadata,
                )
            )
        ]
    if event.event_type.startswith("maf.native."):
        return [
            _dump(
                CustomEvent(
                    name="maf_native_event",
                    value={
                        "kind": event.event_type.removeprefix("maf.native."),
                        "node": event.node,
                    },
                    metadata=metadata,
                )
            )
        ]
    return []


def project_events(
    events: Iterable[DurableEvent], state: WorkflowState | None = None
) -> list[dict[str, Any]]:
    projected = [item for event in events for item in project_event(event, state)]
    if state is not None:
        projected.append(
            _dump(
                StateSnapshotEvent(
                    snapshot={
                        "case_id": state.case_id,
                        "run_id": state.run_id,
                        "status": state.status,
                        "current_step": state.current_step,
                        "approval_required": state.approval_required,
                        "checkpoint_id": state.checkpoint_id,
                        "refund_status": state.refund_status,
                        "terminal_status": state.terminal_status,
                    },
                    metadata={"source": "maf_durable_audit"},
                )
            )
        )
    return projected
