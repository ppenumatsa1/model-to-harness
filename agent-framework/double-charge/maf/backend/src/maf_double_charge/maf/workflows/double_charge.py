from agent_framework import Case, Default, Workflow, WorkflowBuilder

from ...application.audit import Audit
from ...application.models import ApprovalDecision, RunStatus
from ..dependencies import WorkflowDependencies
from ..executors.approval import ApprovalExecutor
from ..executors.completion import notification_executor, terminal_executor
from ..executors.investigation import investigation_executors
from ..executors.refund import refund_executors
from ..executors.validation import validation_executors


def build_workflow(dependencies: WorkflowDependencies, run_id: str) -> Workflow:
    audit = Audit(dependencies.repository)
    normalize, load_account, detect_duplicate = investigation_executors(dependencies, audit)
    prepare_validation, billing_validation, policy_validation, join_validations = (
        validation_executors(dependencies, audit, run_id)
    )
    approval = ApprovalExecutor(audit, dependencies)
    submit_refund, verify_refund = refund_executors(dependencies, audit)
    notify_customer = notification_executor(dependencies, audit)
    close_case = terminal_executor(audit, "close_case", "completed_refunded")
    close_no_duplicate = terminal_executor(audit, "close_no_duplicate", "completed_no_refund")
    close_denied = terminal_executor(audit, "close_denied", "closed_denied")
    route_failure = terminal_executor(
        audit,
        "route_failure",
        "failed",
        run_status=RunStatus.FAILED,
        notification_status="not_sent",
    )
    manual_review = terminal_executor(
        audit,
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
