from __future__ import annotations

import json
import sys
from types import ModuleType

import pytest
from agent_framework import WorkflowCheckpoint, WorkflowCheckpointException, WorkflowEvent
from maf_double_charge.application.commands import ApprovalCommand, ScenarioInput
from maf_double_charge.application.models import (
    ApprovalDecision,
    ApprovalResponse,
    BranchResult,
    NodeStatus,
    RunStatus,
    WorkflowState,
)
from maf_double_charge.application.service import DoubleChargeService
from maf_double_charge.infrastructure.persistence.checkpoint_codec import (
    ALLOWED_CHECKPOINT_TYPES,
    decode_checkpoint,
    encode_checkpoint,
)
from maf_double_charge.infrastructure.simulated_actions import SimulatedActions
from maf_double_charge.maf.messages import ApprovalRequest
from maf_double_charge.maf.runner import MafWorkflowRunner
from maf_double_charge.testing.checkpoints import InMemoryRunCheckpointStorage
from maf_double_charge.testing.model import FakeModelClient
from maf_double_charge.testing.repository import InMemoryRepository


def _state() -> WorkflowState:
    return WorkflowState(
        case_id="case-codec",
        run_id="run-codec",
        complaint="I was charged twice.",
        customer_id="customer-100",
        scenario_id="duplicate-confirmed",
        idempotency_key="key-codec",
        billing_validation=BranchResult(branch="billing_validation", ok=True, summary="validated"),
        approval_decision=ApprovalDecision.APPROVE,
    )


def _checkpoint() -> WorkflowCheckpoint:
    state = _state()
    response = ApprovalResponse.model_validate_json(
        ApprovalResponse(
            decision=ApprovalDecision.APPROVE, reviewer_id="codec-test"
        ).model_dump_json()
    )
    request_id = f"approval::{state.run_id}"
    return WorkflowCheckpoint(
        workflow_name="double-charge",
        graph_signature_hash="test-signature",
        state={
            "business_state": state,
            "approval": response,
            "status": RunStatus.PAUSED,
            "node_status": NodeStatus.COMPLETED,
        },
        pending_request_info_events={
            request_id: WorkflowEvent(
                "request_info",
                ApprovalRequest(
                    case_id=state.case_id,
                    run_id=state.run_id,
                    evidence_summary="Duplicate charge confirmed.",
                    amount="49.99",
                    currency="USD",
                ),
                request_id=request_id,
                response_type=ApprovalResponse,
            )
        },
    )


def test_codec_preserves_final_types_and_timezone() -> None:
    checkpoint = _checkpoint()
    restored = decode_checkpoint(json.loads(json.dumps(encode_checkpoint(checkpoint))))
    assert restored.state == checkpoint.state
    assert isinstance(restored.state["business_state"], WorkflowState)
    assert isinstance(restored.state["business_state"].billing_validation, BranchResult)
    assert isinstance(restored.state["business_state"].status, RunStatus)
    assert isinstance(restored.state["business_state"].approval_decision, ApprovalDecision)
    assert restored.state["status"] == RunStatus.PAUSED
    assert restored.state["node_status"] == NodeStatus.COMPLETED
    assert restored.state["approval"].decided_at.tzinfo is not None
    request = restored.pending_request_info_events["approval::run-codec"]
    assert isinstance(request.data, ApprovalRequest)
    assert request.data.run_id == "run-codec"
    assert request.response_type is ApprovalResponse


def test_codec_rejects_old_root_module_checkpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    old_path = "maf_double_charge.models"
    module = ModuleType(old_path)
    module.WorkflowState = WorkflowState
    with monkeypatch.context() as patch:
        patch.setitem(sys.modules, old_path, module)
        patch.setattr(WorkflowState, "__module__", old_path)
        encoded = encode_checkpoint(
            WorkflowCheckpoint(
                workflow_name="old-workflow",
                graph_signature_hash="old-signature",
                state={
                    "business_state": _state().model_copy(
                        update={
                            "billing_validation": None,
                            "approval_decision": None,
                        }
                    )
                },
            )
        )
    with pytest.raises(WorkflowCheckpointException):
        decode_checkpoint(encoded)
    assert not any(path.startswith(f"{old_path}:") for path in ALLOWED_CHECKPOINT_TYPES)


async def test_inmemory_checkpoint_lifecycle_is_explicit_and_copy_isolated() -> None:
    repository = InMemoryRepository()
    await repository.initialize()
    checkpoint = _checkpoint()
    state = checkpoint.state["business_state"]
    await repository.create_run(state)
    storage = InMemoryRunCheckpointStorage(repository, state.run_id)
    await storage.save(checkpoint)
    checkpoint.state.clear()
    restored = await storage.load(checkpoint.checkpoint_id)
    assert restored.state["business_state"] == state
    restored.state.clear()
    assert (await storage.get_latest(workflow_name="double-charge")).state
    assert await storage.list_checkpoint_ids(workflow_name="double-charge") == [
        checkpoint.checkpoint_id
    ]
    assert await storage.list_checkpoints(workflow_name="another-workflow") == []
    assert (await repository.get_state(state.run_id)).checkpoint_id == checkpoint.checkpoint_id
    reconstructed = InMemoryRunCheckpointStorage(repository, state.run_id)
    assert (await reconstructed.load(checkpoint.checkpoint_id)).state["business_state"] == state
    other_run = InMemoryRunCheckpointStorage(repository, "another-run")
    fresh_storage = InMemoryRunCheckpointStorage(InMemoryRepository(), state.run_id)
    with pytest.raises(WorkflowCheckpointException, match="not found"):
        await fresh_storage.load(checkpoint.checkpoint_id)
    with pytest.raises(WorkflowCheckpointException, match="not found"):
        await other_run.load(checkpoint.checkpoint_id)
    assert await reconstructed.delete(checkpoint.checkpoint_id)
    assert not await storage.delete(checkpoint.checkpoint_id)
    assert await storage.get_latest(workflow_name="double-charge") is None
    await repository.close()


async def test_reconstructed_native_runner_restores_memory_checkpoints() -> None:
    repository = InMemoryRepository()
    await repository.initialize()

    def reconstruct_service() -> DoubleChargeService:
        return DoubleChargeService(
            repository,
            MafWorkflowRunner(
                repository,
                FakeModelClient(),
                checkpoint_storage_factory=InMemoryRunCheckpointStorage,
                actions_factory=SimulatedActions.for_fixture,
                max_tool_attempts=3,
            ),
        )

    service = reconstruct_service()
    started = await service.start(
        ScenarioInput(
            complaint="I was charged twice.",
            customer_id="customer-100",
            scenario_id="duplicate-confirmed",
        )
    )
    assert started.status == RunStatus.PAUSED
    assert started.checkpoint_id
    await service.record_approval(
        started.run_id,
        ApprovalCommand(
            checkpoint_id=started.checkpoint_id,
            decision=ApprovalDecision.APPROVE,
            reviewer_id="memory-restart-reviewer",
        ),
    )
    await repository.close()
    await repository.initialize()
    reconstructed = reconstruct_service()
    terminal = await reconstructed.resume(started.run_id, started.checkpoint_id)
    assert terminal.terminal_status == "completed_refunded"
    assert terminal.refund_status == "verified"
    assert await repository.count_refunds(terminal.idempotency_key) == 1
    await repository.close()
