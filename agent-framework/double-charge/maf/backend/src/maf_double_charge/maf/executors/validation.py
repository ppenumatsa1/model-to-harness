from __future__ import annotations

import asyncio

from agent_framework import Executor, WorkflowContext, executor

from ...application.audit import Audit
from ...application.models import BranchResult, WorkflowState
from ..dependencies import WorkflowDependencies


def validation_executors(
    dependencies: WorkflowDependencies, audit: Audit, run_id: str
) -> tuple[Executor, Executor, Executor, Executor]:
    @executor(id="prepare_validation")
    async def prepare_validation(state: WorkflowState, ctx: WorkflowContext[WorkflowState]) -> None:
        await audit.node_started(state, "prepare_validation")
        prepared = state.advance("parallel_validation")
        await audit.emit(
            prepared,
            "parallel.started",
            "Billing and policy validation started in parallel.",
            node="prepare_validation",
            payload={"branches": ["billing_validation", "policy_validation"]},
        )
        await audit.node_completed(prepared, "prepare_validation", "Validation fan-out emitted.")
        await audit.save(prepared)
        await ctx.send_message(prepared)

    @executor(id="billing_validation")
    async def billing_validation(state: WorkflowState, ctx: WorkflowContext[BranchResult]) -> None:
        await audit.node_started(state, "billing_validation")
        await audit.emit(
            state,
            "tool.call.started",
            "Deterministic billing evidence validation started.",
            node="billing_validation",
            payload={"tool": "shared.billing.validate_duplicate"},
        )
        evidence = dependencies.actions.last_evidence
        if evidence is None:
            result = BranchResult(
                branch="billing_validation",
                ok=False,
                summary="Duplicate evidence is unavailable.",
                failure_code="billing_validation_failed",
            )
        else:
            data = await asyncio.to_thread(
                dependencies.actions.validate_billing, evidence.model_dump(mode="json")
            )
            result = BranchResult(
                branch="billing_validation",
                ok=data["valid"],
                summary=data["reason"],
                failure_code=None if data["valid"] else "billing_validation_failed",
                evidence={"checked_charge_ids": data["checked_charge_ids"]},
            )
        await audit.emit(
            state,
            "tool.call.succeeded" if result.ok else "tool.call.failed",
            result.summary,
            node="billing_validation",
            payload={"tool": "shared.billing.validate_duplicate", "ok": result.ok},
        )
        await audit.emit(
            state,
            "parallel.branch.completed",
            result.summary,
            node="billing_validation",
            payload={"branch": result.branch, "ok": result.ok},
        )
        await audit.node_completed(state, "billing_validation", result.summary)
        await ctx.send_message(result)

    @executor(id="policy_validation")
    async def policy_validation(state: WorkflowState, ctx: WorkflowContext[BranchResult]) -> None:
        await audit.node_started(state, "policy_validation")
        await audit.emit(
            state,
            "tool.call.started",
            "Deterministic refund-policy assessment started.",
            node="policy_validation",
            payload={"tool": "shared.policy.assess"},
        )
        evidence = dependencies.actions.last_evidence
        if evidence is None:
            result = BranchResult(
                branch="policy_validation",
                ok=False,
                summary="Duplicate evidence is unavailable.",
                failure_code="policy_ineligible",
            )
        else:
            data = await asyncio.to_thread(
                dependencies.actions.validate_policy,
                evidence.model_dump(mode="json"),
                state.account_summary,
            )
            result = BranchResult(
                branch="policy_validation",
                ok=data["decision"] == "eligible",
                summary=data["reason"],
                failure_code=None if data["decision"] == "eligible" else "policy_ineligible",
                evidence={"policy_code": data["policy_code"], "decision": data["decision"]},
            )
        await audit.emit(
            state,
            "tool.call.succeeded" if result.ok else "tool.call.failed",
            result.summary,
            node="policy_validation",
            payload={"tool": "shared.policy.assess", "ok": result.ok},
        )
        await audit.emit(
            state,
            "parallel.branch.completed",
            result.summary,
            node="policy_validation",
            payload={"branch": result.branch, "ok": result.ok},
        )
        await audit.node_completed(state, "policy_validation", result.summary)
        await ctx.send_message(result)

    @executor(id="join_validations")
    async def join_validations(
        results: list[BranchResult], ctx: WorkflowContext[WorkflowState]
    ) -> None:
        state = await dependencies.repository.get_state(run_id)
        if state is None:
            raise RuntimeError("run state disappeared before validation join")
        await audit.node_started(state, "join_validations")
        by_branch = {item.branch: item for item in results}
        billing = by_branch["billing_validation"]
        policy = by_branch["policy_validation"]
        valid = billing.ok and policy.ok
        joined = state.advance(
            "approval_checkpoint" if valid else "route_failure",
            billing_validation=billing,
            policy_validation=policy,
            failure_code=billing.failure_code or policy.failure_code,
        )
        join_summary = (
            "Parallel validations joined; both passed."
            if valid
            else "Validation join found a failure."
        )
        await audit.emit(
            joined,
            "parallel.joined",
            join_summary,
            node="join_validations",
            payload={"billing_ok": billing.ok, "policy_ok": policy.ok},
        )
        target = "approval_checkpoint" if valid else "route_failure"
        await audit.edge(
            joined, "join_validations", target, f"Validation route selected: {target}."
        )
        await audit.node_completed(joined, "join_validations", "Validation fan-in completed.")
        await audit.save(joined)
        await ctx.send_message(joined)

    return prepare_validation, billing_validation, policy_validation, join_validations
