from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from agent_framework import (
    Case,
    Default,
    Executor,
    Workflow,
    WorkflowBuilder,
    WorkflowContext,
    executor,
    handler,
    response_handler,
)

from .model_client import ModelClient
from .models import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalResponse,
    BranchResult,
    DurableEvent,
    RunStatus,
    WorkflowState,
)
from .refunds import DurableRefundService
from .repository import Repository
from .shared_actions import (
    BillingReadError,
    RootSharedActions,
    UncertainRefundResponseError,
)

logger = logging.getLogger(__name__)


@dataclass
class WorkflowDependencies:
    repository: Repository
    model: ModelClient
    actions: RootSharedActions
    refunds: DurableRefundService
    max_tool_attempts: int


class Audit:
    def __init__(self, dependencies: WorkflowDependencies) -> None:
        self.dependencies = dependencies

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
        event = DurableEvent(
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
        await self.dependencies.repository.append_event(event)
        logger.info(
            summary,
            extra={
                "case_id": state.case_id,
                "run_id": state.run_id,
                "node": node,
                "transition": transition,
                "checkpoint_id": checkpoint_id,
                "retry_attempt": retry_attempt,
                "idempotency_key": event.idempotency_key,
            },
        )

    async def save(self, state: WorkflowState) -> WorkflowState:
        await self.dependencies.repository.save_state(state)
        return state

    async def node_started(self, state: WorkflowState, node: str) -> None:
        await self.emit(state, "node.started", f"{node} started.", node=node)

    async def node_completed(self, state: WorkflowState, node: str, summary: str) -> None:
        await self.emit(state, "node.completed", summary, node=node)

    async def edge(self, state: WorkflowState, source: str, target: str, reason: str) -> None:
        await self.emit(
            state,
            "edge.selected",
            reason,
            node=source,
            transition=f"{source}->{target}",
        )


class ApprovalExecutor(Executor):
    def __init__(self, audit: Audit, dependencies: WorkflowDependencies) -> None:
        super().__init__(id="approval_checkpoint")
        self.audit = audit
        self.dependencies = dependencies

    @handler
    async def request(
        self,
        state: WorkflowState,
        ctx: WorkflowContext[WorkflowState],
    ) -> None:
        await self.audit.node_started(state, self.id)
        evidence = self.dependencies.actions.last_evidence
        if evidence is None:
            failed = state.advance(
                "route_failure",
                status=RunStatus.FAILED,
                terminal_status="failed",
                failure_code="billing_validation_failed",
            )
            await self.audit.save(failed)
            await ctx.send_message(failed)
            return
        self.dependencies.actions.request_approval(evidence.model_dump(mode="json"), state.case_id)
        paused = state.advance(
            self.id,
            status=RunStatus.PAUSED,
            approval_required=True,
            terminal_status="waiting_approval",
        )
        await self.audit.save(paused)
        await self.audit.emit(
            paused,
            "approval.requested",
            "Human approval is required before submitting the refund.",
            node=self.id,
            payload={
                "amount": str(evidence.amount) if evidence.amount is not None else None,
                "currency": evidence.currency,
                "evidence_summary": evidence.rationale,
            },
        )
        await ctx.request_info(
            ApprovalRequest(
                case_id=paused.case_id,
                run_id=paused.run_id,
                evidence_summary=evidence.rationale,
                amount=str(evidence.amount) if evidence.amount is not None else None,
                currency=evidence.currency,
            ),
            ApprovalResponse,
            request_id=f"approval::{paused.run_id}",
        )

    @response_handler(
        request=ApprovalRequest,
        response=ApprovalResponse,
        output=WorkflowState,
    )
    async def resolve(
        self,
        original_request,
        response,
        ctx,
    ) -> None:
        state = await self.dependencies.repository.get_state(original_request.run_id)
        if state is None:
            raise RuntimeError("run state disappeared before approval resume")
        self.dependencies.actions.resolve_approval(
            response.decision, response.reviewer_id, response.reason
        )
        resumed = state.advance(
            self.id,
            status=RunStatus.RUNNING,
            approval_required=False,
            approval_decision=response.decision,
            terminal_status=None,
        )
        await self.audit.save(resumed)
        await self.audit.emit(
            resumed,
            "approval.resolved",
            f"Approval was {response.decision.value} by {response.reviewer_id}.",
            node=self.id,
            checkpoint_id=state.checkpoint_id,
            payload={"decision": response.decision.value, "reviewer_id": response.reviewer_id},
        )
        target = (
            "submit_refund"
            if response.decision == ApprovalDecision.APPROVE
            else "close_denied"
        )
        await self.audit.edge(resumed, self.id, target, f"Approval route selected: {target}.")
        await ctx.send_message(resumed)


def build_workflow(dependencies: WorkflowDependencies, run_id: str) -> Workflow:
    audit = Audit(dependencies)

    @executor(id="normalize_complaint")
    async def normalize(
        state: WorkflowState, ctx: WorkflowContext[WorkflowState]
    ) -> None:
        await audit.node_started(state, "normalize_complaint")
        await audit.emit(
            state,
            "model.call.started",
            "Complaint normalization model call started.",
            node="normalize_complaint",
        )
        result = await dependencies.model.normalize_complaint(state.complaint)
        memory = await dependencies.repository.get_memory(state.case_id)
        await dependencies.repository.save_memory(
            state.case_id,
            {
                **memory,
                "customer_id": state.customer_id,
                "last_normalized_issue": result.text,
            },
        )
        normalized = state.advance(
            "load_account",
            normalized_complaint=result.text,
        )
        await audit.emit(
            normalized,
            "model.call.completed",
            "Complaint normalized into a concise factual statement.",
            node="normalize_complaint",
            payload={"model": result.model, "latency_ms": result.latency_ms},
        )
        await audit.node_completed(
            normalized, "normalize_complaint", "Complaint normalization completed."
        )
        await audit.edge(
            normalized,
            "normalize_complaint",
            "load_account",
            "Normalized complaint is ready for deterministic account loading.",
        )
        await audit.save(normalized)
        await ctx.send_message(normalized)

    @executor(id="load_account")
    async def load_account(
        state: WorkflowState, ctx: WorkflowContext[WorkflowState]
    ) -> None:
        await audit.node_started(state, "load_account")
        attempts = min(dependencies.actions.maximum_read_attempts, dependencies.max_tool_attempts)
        for attempt in range(1, attempts + 1):
            await audit.emit(
                state,
                "tool.call.started",
                "Billing account read started.",
                node="load_account",
                retry_attempt=attempt,
                payload={"tool": "shared.billing.load_charges"},
            )
            try:
                summary = await asyncio.to_thread(dependencies.actions.load_account)
                loaded = state.advance("detect_duplicate", account_summary=summary)
                await audit.emit(
                    loaded,
                    "tool.call.succeeded",
                    f"Loaded {summary['charge_count']} charge records.",
                    node="load_account",
                    retry_attempt=attempt,
                    payload={"tool": "shared.billing.load_charges"},
                )
                await audit.node_completed(loaded, "load_account", "Account loading completed.")
                await audit.edge(
                    loaded, "load_account", "detect_duplicate", "Billing read succeeded."
                )
                await audit.save(loaded)
                await ctx.send_message(loaded)
                return
            except BillingReadError:
                await audit.emit(
                    state,
                    "tool.call.failed",
                    (
                        "Transient billing read failed; retrying."
                        if attempt < attempts
                        else "Transient billing read exhausted its bounded retry."
                    ),
                    node="load_account",
                    retry_attempt=attempt,
                    payload={"tool": "shared.billing.load_charges", "transient": True},
                )
                if attempt < attempts:
                    await audit.emit(
                        state,
                        "tool.call.retried",
                        "Transient billing read failed; retrying.",
                        node="load_account",
                        retry_attempt=attempt,
                        payload={"tool": "shared.billing.load_charges", "transient": True},
                    )
        failed = state.advance(
            "route_failure",
            status=RunStatus.FAILED,
            terminal_status="failed",
            failure_code="transient_billing_read",
        )
        await audit.edge(failed, "load_account", "route_failure", "Billing retries were exhausted.")
        await audit.save(failed)
        await ctx.send_message(failed)

    @executor(id="detect_duplicate")
    async def detect_duplicate(
        state: WorkflowState, ctx: WorkflowContext[WorkflowState]
    ) -> None:
        await audit.node_started(state, "detect_duplicate")
        evidence = await asyncio.to_thread(dependencies.actions.detect_duplicate)
        found = evidence["decision"] == "confirmed"
        next_step = "prepare_validation" if found else "close_no_duplicate"
        updated = state.advance(
            next_step,
            duplicate_found=found,
            duplicate_summary=evidence["rationale"],
            duplicate_evidence=evidence,
        )
        await audit.emit(
            updated,
            "decision.summary",
            evidence["rationale"],
            node="detect_duplicate",
            payload={
                "decision": evidence["decision"],
                "matching_charge_count": len(evidence["matching_charge_ids"]),
                "amount": evidence.get("amount"),
                "currency": evidence.get("currency"),
            },
        )
        await audit.node_completed(updated, "detect_duplicate", "Duplicate decision completed.")
        await audit.edge(
            updated,
            "detect_duplicate",
            next_step,
            f"Duplicate route selected: {evidence['decision']}.",
        )
        await audit.save(updated)
        await ctx.send_message(updated)

    @executor(id="prepare_validation")
    async def prepare_validation(
        state: WorkflowState, ctx: WorkflowContext[WorkflowState]
    ) -> None:
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
    async def billing_validation(
        state: WorkflowState, ctx: WorkflowContext[BranchResult]
    ) -> None:
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
    async def policy_validation(
        state: WorkflowState, ctx: WorkflowContext[BranchResult]
    ) -> None:
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

    approval = ApprovalExecutor(audit, dependencies)

    @executor(id="submit_refund")
    async def submit_refund(
        state: WorkflowState, ctx: WorkflowContext[WorkflowState]
    ) -> None:
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
                submission = await dependencies.refunds.submit(
                    state, dependencies.actions
                )
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
    async def verify_refund(
        state: WorkflowState, ctx: WorkflowContext[WorkflowState]
    ) -> None:
        await audit.node_started(state, "verify_refund")
        await audit.emit(
            state,
            "tool.call.started",
            "Refund verification tool call started.",
            node="verify_refund",
            payload={"tool": "shared.billing.verify_refund"},
        )
        verification = await dependencies.refunds.verify(
            state, dependencies.actions
        )
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

    @executor(id="notify_customer")
    async def notify_customer(
        state: WorkflowState, ctx: WorkflowContext[WorkflowState]
    ) -> None:
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
            "close_case",
            notification_status="sent",
            notification_summary=result.text,
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

    def terminal_executor(
        executor_id: str,
        terminal_status: str,
        *,
        run_status: RunStatus = RunStatus.COMPLETED,
        refund_status: str | None = None,
        notification_status: str | None = None,
    ):
        @executor(id=executor_id)
        async def terminal(
            state: WorkflowState, ctx: WorkflowContext[None, WorkflowState]
        ) -> None:
            await audit.node_started(state, executor_id)
            updates: dict[str, Any] = {
                "status": run_status,
                "terminal_status": terminal_status,
            }
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

    close_case = terminal_executor("close_case", "completed_refunded")
    close_no_duplicate = terminal_executor("close_no_duplicate", "completed_no_refund")
    close_denied = terminal_executor("close_denied", "closed_denied")
    route_failure = terminal_executor(
        "route_failure",
        "failed",
        run_status=RunStatus.FAILED,
        notification_status="not_sent",
    )
    manual_review = terminal_executor(
        "manual_review",
        "manual_review",
        run_status=RunStatus.MANUAL_REVIEW,
        refund_status="manual_review",
        notification_status="not_sent",
    )

    return (
        WorkflowBuilder(
            name=f"double-charge-{run_id}",
            description="Durable double-charge workflow with explicit fan-out, fan-in, and HITL.",
            start_executor=normalize,
            output_from=[
                close_case,
                close_no_duplicate,
                close_denied,
                route_failure,
                manual_review,
            ],
        )
        .add_edge(normalize, load_account)
        .add_switch_case_edge_group(
            load_account,
            [
                Case(lambda state: state.failure_code is None, detect_duplicate),
                Default(route_failure),
            ],
        )
        .add_switch_case_edge_group(
            detect_duplicate,
            [
                Case(lambda state: state.duplicate_found is True, prepare_validation),
                Default(close_no_duplicate),
            ],
        )
        .add_fan_out_edges(prepare_validation, [billing_validation, policy_validation])
        .add_fan_in_edges([billing_validation, policy_validation], join_validations)
        .add_switch_case_edge_group(
            join_validations,
            [
                Case(
                    lambda state: bool(
                        state.billing_validation
                        and state.billing_validation.ok
                        and state.policy_validation
                        and state.policy_validation.ok
                    ),
                    approval,
                ),
                Default(route_failure),
            ],
        )
        .add_switch_case_edge_group(
            approval,
            [
                Case(
                    lambda state: state.approval_decision == ApprovalDecision.APPROVE,
                    submit_refund,
                ),
                Default(close_denied),
            ],
        )
        .add_switch_case_edge_group(
            submit_refund,
            [
                Case(lambda state: state.failure_code is None, verify_refund),
                Default(route_failure),
            ],
        )
        .add_switch_case_edge_group(
            verify_refund,
            [
                Case(lambda state: state.refund_status == "verified", notify_customer),
                Default(manual_review),
            ],
        )
        .add_edge(notify_customer, close_case)
        .build()
    )
