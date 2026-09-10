from __future__ import annotations

import asyncio

from agent_framework import Executor, WorkflowContext, executor

from ...application.audit import Audit
from ...application.errors import BillingReadError
from ...application.models import RunStatus, WorkflowState
from ..dependencies import WorkflowDependencies


def investigation_executors(
    dependencies: WorkflowDependencies, audit: Audit
) -> tuple[Executor, Executor, Executor]:
    @executor(id="normalize_complaint")
    async def normalize(state: WorkflowState, ctx: WorkflowContext[WorkflowState]) -> None:
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
        normalized = state.advance("load_account", normalized_complaint=result.text)
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
    async def load_account(state: WorkflowState, ctx: WorkflowContext[WorkflowState]) -> None:
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
    async def detect_duplicate(state: WorkflowState, ctx: WorkflowContext[WorkflowState]) -> None:
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

    return normalize, load_account, detect_duplicate
