from __future__ import annotations

from agent_framework import Executor, WorkflowContext, executor

from ...application.audit import Audit
from ...application.errors import UncertainRefundResponseError
from ...application.models import RunStatus, WorkflowState
from ..dependencies import WorkflowDependencies


def refund_executors(dependencies: WorkflowDependencies, audit: Audit) -> tuple[Executor, Executor]:
    @executor(id="submit_refund")
    async def submit_refund(state: WorkflowState, ctx: WorkflowContext[WorkflowState]) -> None:
        await audit.node_started(state, "submit_refund")
        for attempt in range(1, dependencies.max_tool_attempts + 1):
            await audit.emit(
                state,
                "tool.call.started",
                "Refund submission tool call started.",
                node="submit_refund",
                retry_attempt=attempt,
                payload={"tool": "shared.billing.submit_refund"},
            )
            await audit.emit(
                state,
                "refund.idempotency.lookup",
                "Refund submission uses the stable run idempotency key.",
                node="submit_refund",
                retry_attempt=attempt,
                payload={"tool": "shared.billing.submit_refund"},
            )
            try:
                submission = await dependencies.refunds.submit(state, dependencies.actions)
                submitted = state.advance(
                    "verify_refund",
                    refund_status="submitted",
                    refund_id=submission.refund["refund_id"],
                )
                await audit.emit(
                    submitted,
                    "tool.call.succeeded",
                    "Refund submission returned a deterministic refund reference.",
                    node="submit_refund",
                    retry_attempt=attempt,
                    payload={
                        "tool": "shared.billing.submit_refund",
                        "refund_id": submission.refund["refund_id"],
                        "recovered_existing": submission.recovered_existing,
                    },
                )
                await audit.node_completed(
                    submitted, "submit_refund", "Refund submission completed."
                )
                await audit.edge(
                    submitted, "submit_refund", "verify_refund", "Refund will be verified."
                )
                await audit.save(submitted)
                await ctx.send_message(submitted)
                return
            except UncertainRefundResponseError:
                await audit.emit(
                    state,
                    "tool.call.failed",
                    "Refund response was uncertain.",
                    node="submit_refund",
                    retry_attempt=attempt,
                    payload={"tool": "shared.billing.submit_refund", "uncertain": True},
                )
                if attempt < dependencies.max_tool_attempts:
                    await audit.emit(
                        state,
                        "tool.call.retried",
                        "Refund response was uncertain; retrying with the same idempotency key.",
                        node="submit_refund",
                        retry_attempt=attempt,
                        payload={"tool": "shared.billing.submit_refund", "uncertain": True},
                    )
        failed = state.advance(
            "route_failure",
            status=RunStatus.FAILED,
            terminal_status="failed",
            refund_status="failed",
            failure_code="refund_submission_failed",
        )
        await audit.edge(failed, "submit_refund", "route_failure", "Refund retries were exhausted.")
        await audit.save(failed)
        await ctx.send_message(failed)

    @executor(id="verify_refund")
    async def verify_refund(state: WorkflowState, ctx: WorkflowContext[WorkflowState]) -> None:
        await audit.node_started(state, "verify_refund")
        await audit.emit(
            state,
            "tool.call.started",
            "Refund verification tool call started.",
            node="verify_refund",
            payload={"tool": "shared.billing.verify_refund"},
        )
        verification = await dependencies.refunds.verify(state, dependencies.actions)
        verified = verification["verified"]
        target = "notify_customer" if verified else "manual_review"
        updated = state.advance(
            target,
            refund_status="verified" if verified else "manual_review",
            refund_id=verification.get("refund_id") or state.refund_id,
            failure_code=None if verified else "refund_verification_mismatch",
        )
        await audit.emit(
            updated,
            "tool.call.succeeded",
            "Refund verification tool call completed.",
            node="verify_refund",
            payload={"tool": "shared.billing.verify_refund"},
        )
        await audit.emit(
            updated,
            "refund.verification",
            verification["reason"],
            node="verify_refund",
            payload={
                "matching_refund_count": verification["matching_refund_count"],
                "verified": verified,
            },
        )
        await audit.node_completed(updated, "verify_refund", "Refund verification completed.")
        await audit.edge(
            updated, "verify_refund", target, f"Verification route selected: {target}."
        )
        await audit.save(updated)
        await ctx.send_message(updated)

    return submit_refund, verify_refund
