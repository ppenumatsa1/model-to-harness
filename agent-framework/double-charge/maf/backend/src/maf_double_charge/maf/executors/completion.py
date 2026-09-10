from __future__ import annotations

from typing import Any

from agent_framework import Executor, WorkflowContext, executor

from ...application.audit import Audit
from ...application.models import RunStatus, WorkflowState
from ..dependencies import WorkflowDependencies


def notification_executor(dependencies: WorkflowDependencies, audit: Audit) -> Executor:
    @executor(id="notify_customer")
    async def notify_customer(state: WorkflowState, ctx: WorkflowContext[WorkflowState]) -> None:
        await audit.node_started(state, "notify_customer")
        await audit.emit(
            state,
            "model.call.started",
            "Customer notification drafting started.",
            node="notify_customer",
        )
        result = await dependencies.model.draft_notification(
            {
                "refund_status": state.refund_status,
                "refund_id": state.refund_id,
                "duplicate_summary": state.duplicate_summary,
            }
        )
        notified = state.advance(
            "close_case", notification_status="sent", notification_summary=result.text
        )
        await audit.emit(
            notified,
            "model.call.completed",
            "Customer-safe notification drafted.",
            node="notify_customer",
            payload={"model": result.model, "latency_ms": result.latency_ms},
        )
        await audit.emit(
            notified,
            "notification.sent",
            "Simulated customer notification sent.",
            node="notify_customer",
        )
        await audit.node_completed(notified, "notify_customer", "Customer notification completed.")
        await audit.edge(notified, "notify_customer", "close_case", "Notification was sent.")
        await audit.save(notified)
        await ctx.send_message(notified)

    return notify_customer


def terminal_executor(
    audit: Audit,
    executor_id: str,
    terminal_status: str,
    *,
    run_status: RunStatus = RunStatus.COMPLETED,
    refund_status: str | None = None,
    notification_status: str | None = None,
) -> Executor:
    @executor(id=executor_id)
    async def terminal(state: WorkflowState, ctx: WorkflowContext[None, WorkflowState]) -> None:
        await audit.node_started(state, executor_id)
        updates: dict[str, Any] = {"status": run_status, "terminal_status": terminal_status}
        if refund_status is not None:
            updates["refund_status"] = refund_status
        if notification_status is not None:
            updates["notification_status"] = notification_status
        completed = state.advance(executor_id, **updates)
        await audit.save(completed)
        await audit.node_completed(completed, executor_id, f"Run ended as {terminal_status}.")
        await audit.emit(
            completed,
            "run.completed" if run_status == RunStatus.COMPLETED else "run.failed",
            f"Run reached terminal status {terminal_status}.",
            node=executor_id,
        )
        await ctx.yield_output(completed)

    return terminal
