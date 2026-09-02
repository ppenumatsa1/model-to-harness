import operator
from typing import Annotated, Any

from typing_extensions import TypedDict


def merge_dicts(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {**left, **right}


class DoubleChargeState(TypedDict, total=False):
    case_id: str
    run_id: str
    thread_id: str
    complaint: str
    normalized_complaint: str
    customer_id: str
    scenario_id: str
    idempotency_key: str
    current_step: str
    status: str
    charges: list[dict[str, Any]]
    duplicate_decision: str
    duplicate_evidence: dict[str, Any]
    load_attempts: int
    validation_results: Annotated[dict[str, Any], merge_dicts]
    evidence: Annotated[list[dict[str, Any]], operator.add]
    approval_decision: str
    approval_reviewer: str
    approval_reason: str | None
    approval_checkpoint_label: str | None
    refund_attempts: int
    refund_status: str
    refund_id: str | None
    notification_status: str
    selected_memory: dict[str, Any]
    failure_code: str | None
    terminal_status: str
    safe_summaries: Annotated[list[str], operator.add]
