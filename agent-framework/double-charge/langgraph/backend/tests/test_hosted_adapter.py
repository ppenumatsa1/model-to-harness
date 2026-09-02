import json

from fakes import FakeDomainGateway, FakeModel
from langgraph.checkpoint.memory import InMemorySaver
from model_to_harness_langgraph.audit import InMemoryAuditRepository
from model_to_harness_langgraph.hosted_adapter import (
    dispatch_hosted_command,
    parse_hosted_command,
    safe_hosted_error,
)
from model_to_harness_langgraph.service import InvalidCommandError, WorkflowService
from model_to_harness_langgraph.workflow import DoubleChargeWorkflow


def make_service() -> WorkflowService:
    audit = InMemoryAuditRepository()
    workflow = DoubleChargeWorkflow(
        audit=audit,
        gateway=FakeDomainGateway(),
        model=FakeModel(),
        checkpointer=InMemorySaver(),
    )
    return WorkflowService(workflow, audit)


async def test_hosted_commands_keep_approval_and_resume_separate_and_return_safe_json():
    service = make_service()
    started = await dispatch_hosted_command(
        service,
        parse_hosted_command(
            json.dumps(
                {
                    "action": "start",
                    "complaint": "I was charged twice for one purchase.",
                    "customer_id": "hosted-customer",
                }
            )
        ),
        "conversation-1",
    )

    assert started["ok"] is True
    assert started["case"]["status"] == "paused"
    assert started["case"]["approval_required"] is True
    assert "workflow_state" not in started["case"]
    assert all("data" not in event for event in started["events"])

    case_id = started["case"]["case_id"]
    checkpoint_id = started["case"]["checkpoint_id"]
    approved = await dispatch_hosted_command(
        service,
        parse_hosted_command(
            json.dumps(
                {
                    "action": "approval",
                    "case_id": case_id,
                    "checkpoint_id": checkpoint_id,
                    "decision": "approve",
                    "reviewer_id": "reviewer-1",
                }
            )
        ),
        "conversation-1",
    )
    assert approved["case"]["status"] == "paused"

    resumed = await dispatch_hosted_command(
        service,
        parse_hosted_command(json.dumps({"action": "resume", "case_id": case_id})),
        "conversation-1",
    )
    assert resumed["case"]["status"] == "completed"
    assert resumed["case"]["outcome"]["approval_decision"] == "approved"


def test_plain_text_defaults_to_start_and_errors_are_redacted():
    command = parse_hosted_command("I was charged twice for the same purchase.")
    assert command.action == "start"

    error = safe_hosted_error(RuntimeError("postgresql://user:secret@example/db"))
    assert error == {
        "ok": False,
        "error": {
            "code": "internal_error",
            "message": "The workflow command could not be completed.",
        },
    }
    assert safe_hosted_error(InvalidCommandError("Run is not paused")) == {
        "ok": False,
        "error": {"code": "command_conflict", "message": "Run is not paused"},
    }
