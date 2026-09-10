from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy

from ...infrastructure.telemetry import instrument_node
from ..state import DoubleChargeState

if TYPE_CHECKING:
    from ..runner import DoubleChargeWorkflow


def build_graph(self: "DoubleChargeWorkflow") -> StateGraph:
    builder = StateGraph(DoubleChargeState)
    builder.add_node(
        "normalize_complaint",
        instrument_node("normalize_complaint", self.normalize_complaint),
        retry_policy=RetryPolicy(max_attempts=2),
    )
    builder.add_node("load_account", instrument_node("load_account", self.load_account))
    builder.add_node("detect_duplicate", instrument_node("detect_duplicate", self.detect_duplicate))
    builder.add_node(
        "dispatch_validations", instrument_node("dispatch_validations", self.dispatch_validations)
    )
    builder.add_node(
        "billing_validation", instrument_node("billing_validation", self.billing_validation)
    )
    builder.add_node(
        "policy_validation", instrument_node("policy_validation", self.policy_validation)
    )
    builder.add_node("join_validations", instrument_node("join_validations", self.join_validations))
    builder.add_node("request_approval", instrument_node("request_approval", self.request_approval))
    builder.add_node("submit_refund", instrument_node("submit_refund", self.submit_refund))
    builder.add_node("verify_refund", instrument_node("verify_refund", self.verify_refund))
    builder.add_node(
        "notify_customer",
        instrument_node("notify_customer", self.notify_customer),
        retry_policy=RetryPolicy(max_attempts=2),
    )
    builder.add_node(
        "close_no_duplicate", instrument_node("close_no_duplicate", self.close_no_duplicate)
    )
    builder.add_node("close_denied", instrument_node("close_denied", self.close_denied))
    builder.add_node("close_success", instrument_node("close_success", self.close_success))
    builder.add_node("fail_load", instrument_node("fail_load", self.fail_load))
    builder.add_node("fail_validation", instrument_node("fail_validation", self.fail_validation))
    builder.add_node("fail_refund", instrument_node("fail_refund", self.fail_refund))
    builder.add_node("manual_review", instrument_node("manual_review", self.manual_review))

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
