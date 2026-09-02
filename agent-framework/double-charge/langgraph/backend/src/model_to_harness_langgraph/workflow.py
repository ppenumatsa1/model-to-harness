import hashlib
import json
import logging
import time
from contextlib import contextmanager
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy, interrupt

from .audit import AuditRepository, RefundIdempotencyConflictError
from .domain_gateway import DomainGateway, ToolResult
from .model_adapter import ComplaintModel
from .state import DoubleChargeState

logger = logging.getLogger(__name__)


class DoubleChargeWorkflow:
    def __init__(
        self,
        *,
        audit: AuditRepository,
        gateway: DomainGateway,
        model: ComplaintModel,
        checkpointer: Any,
        interrupt_after: list[str] | None = None,
    ) -> None:
        self.audit = audit
        self.gateway = gateway
        self.model = model
        self.graph = self._build().compile(
            checkpointer=checkpointer,
            interrupt_after=interrupt_after or [],
        )

    def _build(self) -> StateGraph:
        builder = StateGraph(DoubleChargeState)
        builder.add_node(
            "normalize_complaint",
            self.normalize_complaint,
            retry_policy=RetryPolicy(max_attempts=2),
        )
        builder.add_node("load_account", self.load_account)
        builder.add_node("detect_duplicate", self.detect_duplicate)
        builder.add_node("dispatch_validations", self.dispatch_validations)
        builder.add_node("billing_validation", self.billing_validation)
        builder.add_node("policy_validation", self.policy_validation)
        builder.add_node("join_validations", self.join_validations)
        builder.add_node("request_approval", self.request_approval)
        builder.add_node("submit_refund", self.submit_refund)
        builder.add_node("verify_refund", self.verify_refund)
        builder.add_node(
            "notify_customer",
            self.notify_customer,
            retry_policy=RetryPolicy(max_attempts=2),
        )
        builder.add_node("close_no_duplicate", self.close_no_duplicate)
        builder.add_node("close_denied", self.close_denied)
        builder.add_node("close_success", self.close_success)
        builder.add_node("fail_load", self.fail_load)
        builder.add_node("fail_validation", self.fail_validation)
        builder.add_node("fail_refund", self.fail_refund)
        builder.add_node("manual_review", self.manual_review)

        builder.add_edge(START, "normalize_complaint")
        builder.add_edge("normalize_complaint", "load_account")
        builder.add_conditional_edges(
            "load_account",
            self.route_load,
            {
                "retry": "load_account",
                "loaded": "detect_duplicate",
                "failed": "fail_load",
            },
        )
        builder.add_conditional_edges(
            "detect_duplicate",
            self.route_duplicate,
            {
                "duplicate": "dispatch_validations",
                "no_duplicate": "close_no_duplicate",
                "failed": "fail_validation",
            },
        )
        builder.add_edge("dispatch_validations", "billing_validation")
        builder.add_edge("dispatch_validations", "policy_validation")
        builder.add_edge("billing_validation", "join_validations")
        builder.add_edge("policy_validation", "join_validations")
        builder.add_conditional_edges(
            "join_validations",
            self.route_validation,
            {"eligible": "request_approval", "failed": "fail_validation"},
        )
        builder.add_conditional_edges(
            "request_approval",
            self.route_approval,
            {"approved": "submit_refund", "denied": "close_denied"},
        )
        builder.add_conditional_edges(
            "submit_refund",
            self.route_refund,
            {
                "retry": "submit_refund",
                "submitted": "verify_refund",
                "failed": "fail_refund",
            },
        )
        builder.add_conditional_edges(
            "verify_refund",
            self.route_verification,
            {
                "verified": "notify_customer",
                "manual_review": "manual_review",
                "failed": "fail_refund",
            },
        )
        builder.add_edge("notify_customer", "close_success")
        for terminal in (
            "close_no_duplicate",
            "close_denied",
            "close_success",
            "fail_load",
            "fail_validation",
            "fail_refund",
            "manual_review",
        ):
            builder.add_edge(terminal, END)
        return builder

    @contextmanager
    def trace_run(self, run_id: str, *, case_id: str, command: str):
        try:
            from opentelemetry import trace
        except ImportError:
            yield None
            return

        tracer = trace.get_tracer("model_to_harness_langgraph.workflow")
        with tracer.start_as_current_span("workflow.run") as span:
            span.set_attribute("workflow.case_id", case_id)
            span.set_attribute("workflow.run_id", run_id)
            span.set_attribute("workflow.command", command)
            parent_context = trace.set_span_in_context(span)
            yield parent_context

    async def _event(
        self,
        state: DoubleChargeState,
        event_type: str,
        summary: str,
        *,
        node: str | None = None,
        status: str | None = None,
        data: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
    ) -> None:
        await self.audit.append_event(
            case_id=state["case_id"],
            run_id=state["run_id"],
            event_type=event_type,
            summary=summary,
            node=node,
            status=status,
            data=data,
            dedupe_key=dedupe_key,
        )
        logger.info(
            summary,
            extra={
                "case_id": state["case_id"],
                "run_id": state["run_id"],
                "node": node,
                "transition": data.get("route") if data else None,
                "checkpoint_id": data.get("checkpoint_id") if data else None,
                "retry_count": data.get("attempt") if data else None,
                "idempotency_key_hash": _key_hash(state.get("idempotency_key")),
            },
        )

    async def _tool_start(
        self, state: DoubleChargeState, node: str, tool: str, attempt: int | None = None
    ) -> None:
        tool_call_id = f"{state['run_id']}:{node}:{attempt or 1}"
        await self._event(
            state,
            "tool_call_started",
            f"{tool} started",
            node=node,
            status="running",
            data={"tool": tool, "attempt": attempt, "tool_call_id": tool_call_id},
        )

    async def _tool_end(
        self,
        state: DoubleChargeState,
        node: str,
        tool: str,
        result: ToolResult,
        attempt: int | None = None,
    ) -> None:
        tool_call_id = f"{state['run_id']}:{node}:{attempt or 1}"
        await self._event(
            state,
            "tool_call_succeeded" if result.ok else "tool_call_failed",
            result.safe_summary or f"{tool} {'completed' if result.ok else 'failed'}",
            node=node,
            status="completed" if result.ok else "failed",
            data={
                "tool": tool,
                "attempt": attempt,
                "tool_call_id": tool_call_id,
                "failure_code": result.code,
            },
        )

    async def normalize_complaint(self, state: DoubleChargeState) -> dict[str, Any]:
        node = "normalize_complaint"
        await self._event(state, "node_started", "Complaint normalization started", node=node)
        await self._event(
            state,
            "model_call_started",
            "Configured model is normalizing the complaint",
            node=node,
            data={"model": "configured-foundry-deployment"},
        )
        started = time.monotonic()
        normalized = await self.model.normalize(state["complaint"])
        latency_ms = int((time.monotonic() - started) * 1000)
        await self._event(
            state,
            "model_call_completed",
            "Complaint normalized without changing business facts",
            node=node,
            data={"model": "configured-foundry-deployment", "latency_ms": latency_ms},
        )
        return {
            "normalized_complaint": normalized,
            "current_step": node,
            "safe_summaries": ["Complaint normalized into a concise factual statement."],
        }

    async def load_account(self, state: DoubleChargeState) -> dict[str, Any]:
        node = "load_account"
        attempt = state.get("load_attempts", 0) + 1
        await self._tool_start(state, node, "billing.load_account", attempt)
        result = await self.gateway.load_account(
            state["run_id"], state["customer_id"], state["scenario_id"]
        )
        await self._tool_end(state, node, "billing.load_account", result, attempt)
        if not result.ok and result.transient and attempt < 2:
            await self._event(
                state,
                "tool_call_retried",
                "Transient account read failed; bounded retry selected",
                node=node,
                status="retrying",
                data={"tool": "billing.load_account", "attempt": attempt, "route": "retry"},
            )
        return {
            "load_attempts": attempt,
            "charges": result.value.get("charges", []) if result.ok else [],
            "failure_code": result.code if not result.ok else None,
            "status": "running",
            "current_step": node,
        }

    def route_load(self, state: DoubleChargeState) -> Literal["retry", "loaded", "failed"]:
        if state.get("charges"):
            return "loaded"
        if state.get("load_attempts", 0) < 2 and state.get("failure_code", "").startswith(
            "TRANSIENT"
        ):
            return "retry"
        return "failed"

    async def detect_duplicate(self, state: DoubleChargeState) -> dict[str, Any]:
        node = "detect_duplicate"
        await self._tool_start(state, node, "billing.detect_duplicate")
        result = await self.gateway.detect_duplicate(
            state["run_id"],
            state["customer_id"],
            state["charges"],
            state["scenario_id"],
        )
        await self._tool_end(state, node, "billing.detect_duplicate", result)
        decision = str(result.value.get("decision", "unknown")) if result.ok else "failed"
        evidence = result.value.get("evidence", {}) if result.ok else {}
        await self._event(
            state,
            "decision_summary",
            result.safe_summary or f"Duplicate decision: {decision}",
            node=node,
            data={"decision": decision},
        )
        return {
            "duplicate_decision": decision,
            "duplicate_evidence": evidence,
            "failure_code": result.code if not result.ok else None,
            "current_step": node,
            "safe_summaries": [result.safe_summary or f"Duplicate decision: {decision}"],
        }

    def route_duplicate(
        self, state: DoubleChargeState
    ) -> Literal["duplicate", "no_duplicate", "failed"]:
        decision = state.get("duplicate_decision")
        if decision in {"duplicate", "confirmed", "yes"}:
            return "duplicate"
        if decision in {"not_duplicate", "no_duplicate", "not_found", "no"}:
            return "no_duplicate"
        return "failed"

    async def dispatch_validations(self, state: DoubleChargeState) -> dict[str, Any]:
        await self._event(
            state,
            "parallel_branch_started",
            "Billing and refund-policy validation started in parallel",
            node="dispatch_validations",
            data={"branch": "billing+policy"},
        )
        return {"current_step": "parallel_validation"}

    async def billing_validation(self, state: DoubleChargeState) -> dict[str, Any]:
        node = "billing_validation"
        await self._tool_start(state, node, "billing.validate_charge")
        result = await self.gateway.validate_billing(
            state["run_id"],
            state["customer_id"],
            state["charges"],
            state["scenario_id"],
        )
        await self._tool_end(state, node, "billing.validate_charge", result)
        await self._event(
            state,
            "parallel_branch_completed",
            result.safe_summary or "Billing validation completed",
            node=node,
            data={"branch": "billing", "eligible": result.ok},
        )
        return {
            "validation_results": {
                "billing": {
                    "ok": result.ok,
                    "code": result.code,
                    "summary": result.safe_summary,
                }
            },
            "evidence": [{"source": "billing", **result.value}],
        }

    async def policy_validation(self, state: DoubleChargeState) -> dict[str, Any]:
        node = "policy_validation"
        await self._tool_start(state, node, "policy.validate_refund")
        result = await self.gateway.validate_policy(
            state["run_id"],
            state["customer_id"],
            state["charges"],
            state["scenario_id"],
        )
        await self._tool_end(state, node, "policy.validate_refund", result)
        await self._event(
            state,
            "parallel_branch_completed",
            result.safe_summary or "Refund-policy validation completed",
            node=node,
            data={"branch": "policy", "eligible": result.ok},
        )
        return {
            "validation_results": {
                "policy": {
                    "ok": result.ok,
                    "code": result.code,
                    "summary": result.safe_summary,
                }
            },
            "evidence": [{"source": "policy", **result.value}],
        }

    async def join_validations(self, state: DoubleChargeState) -> dict[str, Any]:
        results = state.get("validation_results", {})
        eligible = bool(
            results.get("billing", {}).get("ok") and results.get("policy", {}).get("ok")
        )
        await self._event(
            state,
            "parallel_branch_joined",
            "Parallel validations joined; refund evidence is sufficient"
            if eligible
            else "Parallel validations joined; evidence is insufficient",
            node="join_validations",
            data={"eligible": eligible},
        )
        failure_code = None
        if not eligible:
            failure_code = next(
                (
                    result.get("code")
                    for result in results.values()
                    if not result.get("ok") and result.get("code")
                ),
                "VALIDATION_FAILED",
            )
        return {
            "current_step": "join_validations",
            "failure_code": failure_code,
            "safe_summaries": [
                "Billing and policy checks both passed."
                if eligible
                else "At least one required validation failed."
            ],
        }

    def route_validation(self, state: DoubleChargeState) -> Literal["eligible", "failed"]:
        results = state.get("validation_results", {})
        return (
            "eligible"
            if results.get("billing", {}).get("ok") and results.get("policy", {}).get("ok")
            else "failed"
        )

    async def request_approval(self, state: DoubleChargeState) -> dict[str, Any]:
        node = "request_approval"
        checkpoint_label = f"approval:{state['run_id']}"
        await self._event(
            state,
            "checkpoint_created",
            "Durable approval checkpoint created",
            node=node,
            status="paused",
            data={"checkpoint_id": checkpoint_label},
            dedupe_key=f"checkpoint:{state['run_id']}",
        )
        await self._event(
            state,
            "human_approval_requested",
            "Refund approval is required before submission",
            node=node,
            status="paused",
            data={"checkpoint_id": checkpoint_label},
            dedupe_key=f"approval-request:{state['run_id']}",
        )
        response = interrupt(
            {
                "kind": "refund_approval",
                "case_id": state["case_id"],
                "run_id": state["run_id"],
                "summary": "Duplicate charge and policy evidence passed; approve refund?",
            }
        )
        decision = str(response.get("decision", "deny"))
        await self._event(
            state,
            "human_approval_resolved",
            f"Reviewer decision recorded: {decision}",
            node=node,
            status="resumed",
            data={"decision": decision},
            dedupe_key=f"approval-resolved:{state['run_id']}",
        )
        return {
            "approval_decision": decision,
            "approval_reviewer": str(response.get("reviewer_id", "unknown")),
            "approval_reason": response.get("reason"),
            "approval_checkpoint_label": checkpoint_label,
            "status": "running",
            "current_step": node,
        }

    def route_approval(self, state: DoubleChargeState) -> Literal["approved", "denied"]:
        return "approved" if state.get("approval_decision") == "approve" else "denied"

    async def submit_refund(self, state: DoubleChargeState) -> dict[str, Any]:
        node = "submit_refund"
        attempt = state.get("refund_attempts", 0) + 1
        request_fingerprint = _refund_fingerprint(state)
        existing = await self.audit.get_refund(state["idempotency_key"])
        if existing is not None:
            if existing["request_fingerprint"] != request_fingerprint:
                await self._event(
                    state,
                    "refund_idempotency_lookup",
                    "Idempotency key is bound to a different refund request",
                    node=node,
                    status="failed",
                    data={"failure_code": "REFUND_IDEMPOTENCY_CONFLICT"},
                )
                return {
                    "refund_attempts": attempt,
                    "refund_status": "failed",
                    "failure_code": "REFUND_IDEMPOTENCY_CONFLICT",
                    "current_step": node,
                }
            await self._event(
                state,
                "refund_idempotency_lookup",
                "Existing durable refund found for the same request",
                node=node,
                status="completed",
                data={"refund_id": existing["refund_id"]},
            )
            return {
                "refund_attempts": attempt,
                "refund_status": "submitted",
                "refund_id": existing["refund_id"],
                "failure_code": None,
                "current_step": node,
            }
        await self._tool_start(state, node, "billing.submit_refund", attempt)
        result = await self.gateway.submit_refund(
            state["run_id"],
            state["customer_id"],
            state["duplicate_evidence"],
            state["idempotency_key"],
            state["scenario_id"],
        )
        refund_id = result.value.get("refund_id")
        if (result.ok or result.uncertain) and not refund_id:
            result = ToolResult(
                ok=False,
                code="REFUND_SUBMISSION_FAILED",
                safe_summary="Refund response did not include a durable refund identifier",
            )
        if (result.ok or result.uncertain) and refund_id:
            try:
                durable = await self.audit.record_refund(
                    {
                        "idempotency_key": state["idempotency_key"],
                        "request_fingerprint": request_fingerprint,
                        "refund_id": refund_id,
                        "case_id": state["case_id"],
                        "run_id": state["run_id"],
                        "customer_id": state["customer_id"],
                    }
                )
                refund_id = durable["refund_id"]
            except RefundIdempotencyConflictError:
                result = ToolResult(
                    ok=False,
                    code="REFUND_IDEMPOTENCY_CONFLICT",
                    safe_summary="Durable idempotency key conflicts with another request",
                )
        await self._tool_end(state, node, "billing.submit_refund", result, attempt)
        if result.uncertain and attempt < 2:
            await self._event(
                state,
                "tool_call_retried",
                "Refund response was uncertain; retrying with the same idempotency key",
                node=node,
                status="retrying",
                data={"tool": "billing.submit_refund", "attempt": attempt, "route": "retry"},
            )
        return {
            "refund_attempts": attempt,
            "refund_status": (
                "uncertain" if result.uncertain else "submitted" if result.ok else "failed"
            ),
            "refund_id": refund_id,
            "failure_code": result.code if not result.ok and not result.uncertain else None,
            "current_step": node,
        }

    def route_refund(
        self, state: DoubleChargeState
    ) -> Literal["retry", "submitted", "failed"]:
        if state.get("refund_status") == "submitted":
            return "submitted"
        if state.get("refund_status") == "uncertain" and state.get("refund_attempts", 0) < 2:
            return "retry"
        return "failed"

    async def verify_refund(self, state: DoubleChargeState) -> dict[str, Any]:
        node = "verify_refund"
        await self._event(
            state,
            "refund_idempotency_lookup",
            "Checking refund by idempotency key",
            node=node,
        )
        durable = await self.audit.get_refund(state["idempotency_key"])
        result = await self.gateway.verify_refund(
            state["run_id"],
            state["customer_id"],
            state["idempotency_key"],
            state["scenario_id"],
            durable["refund_id"] if durable else None,
        )
        count = int(result.value.get("matching_refunds", 0))
        await self._event(
            state,
            "refund_verification",
            result.safe_summary or f"Refund verification found {count} matching record(s)",
            node=node,
            status="completed" if result.ok and count == 1 else "failed",
            data={"verified_count": count, "refund_id": result.value.get("refund_id")},
        )
        return {
            "refund_status": "verified" if result.ok and count == 1 else "mismatch",
            "refund_id": result.value.get("refund_id", state.get("refund_id")),
            "failure_code": None if result.ok and count == 1 else result.code or "VERIFY_MISMATCH",
            "current_step": node,
        }

    def route_verification(
        self, state: DoubleChargeState
    ) -> Literal["verified", "manual_review", "failed"]:
        if state.get("refund_status") == "verified":
            return "verified"
        if state.get("failure_code") == "VERIFY_MISMATCH":
            return "manual_review"
        return "failed"

    async def notify_customer(self, state: DoubleChargeState) -> dict[str, Any]:
        node = "notify_customer"
        await self._event(
            state,
            "model_call_started",
            "Configured model is drafting an allowlisted customer update",
            node=node,
            data={"model": "configured-foundry-deployment"},
        )
        message = await self.model.draft_notification(
            {
                "case_id": state["case_id"],
                "refund_status": state["refund_status"],
                "refund_id": state.get("refund_id") or "not available",
            }
        )
        await self._event(
            state,
            "model_call_completed",
            "Customer update drafted",
            node=node,
            data={"model": "configured-foundry-deployment"},
        )
        await self._tool_start(state, node, "notification.send")
        result = await self.gateway.send_notification(
            state["run_id"], state["customer_id"], message, state["scenario_id"]
        )
        await self._tool_end(state, node, "notification.send", result)
        return {
            "notification_status": "sent" if result.ok else "failed",
            "failure_code": result.code if not result.ok else None,
            "current_step": node,
        }

    async def _terminal(
        self,
        state: DoubleChargeState,
        *,
        terminal_status: str,
        summary: str,
        refund_status: str | None = None,
        notification_status: str | None = None,
    ) -> dict[str, Any]:
        await self._event(
            state,
            "run_completed" if terminal_status != "failed" else "run_failed",
            summary,
            node=terminal_status,
            status=terminal_status,
            data={"failure_code": state.get("failure_code")},
        )
        selected_memory = {
            "case_id": state["case_id"],
            "duplicate_decision": state.get("duplicate_decision", "unknown"),
            "refund_status": refund_status or state.get("refund_status", "not_requested"),
        }
        await self.audit.upsert_memory(
            state["customer_id"], state["case_id"], selected_memory
        )
        return {
            "terminal_status": terminal_status,
            "status": terminal_status,
            "current_step": terminal_status,
            "refund_status": refund_status or state.get("refund_status", "not_requested"),
            "notification_status": notification_status
            or state.get("notification_status", "not_sent"),
            "selected_memory": selected_memory,
            "safe_summaries": [summary],
        }

    async def close_no_duplicate(self, state: DoubleChargeState) -> dict[str, Any]:
        return await self._terminal(
            state,
            terminal_status="completed",
            summary="Case closed because no duplicate charge was found.",
            refund_status="not_required",
        )

    async def close_denied(self, state: DoubleChargeState) -> dict[str, Any]:
        return await self._terminal(
            state,
            terminal_status="completed",
            summary="Case closed without refund after reviewer denial.",
            refund_status="denied",
        )

    async def close_success(self, state: DoubleChargeState) -> dict[str, Any]:
        return await self._terminal(
            state,
            terminal_status="completed",
            summary="Exactly one refund was verified and the customer was notified.",
        )

    async def fail_load(self, state: DoubleChargeState) -> dict[str, Any]:
        return await self._terminal(
            state,
            terminal_status="failed",
            summary="Account loading failed after bounded retries.",
            refund_status="not_submitted",
        )

    async def fail_validation(self, state: DoubleChargeState) -> dict[str, Any]:
        return await self._terminal(
            state,
            terminal_status="failed",
            summary="Required deterministic validation failed.",
            refund_status="not_submitted",
        )

    async def fail_refund(self, state: DoubleChargeState) -> dict[str, Any]:
        return await self._terminal(
            state,
            terminal_status="failed",
            summary="Refund processing failed without claiming success.",
        )

    async def manual_review(self, state: DoubleChargeState) -> dict[str, Any]:
        return await self._terminal(
            state,
            terminal_status="manual_review",
            summary="Refund verification mismatch requires manual review.",
        )


def _key_hash(key: str | None) -> str | None:
    if not key:
        return None
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def _refund_fingerprint(state: DoubleChargeState) -> str:
    evidence = state.get("duplicate_evidence", {})
    request = {
        "customer_id": state["customer_id"],
        "charge_ids": sorted(evidence.get("matching_charge_ids", [])),
        "amount": evidence.get("amount"),
        "currency": evidence.get("currency"),
    }
    encoded = json.dumps(request, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()
