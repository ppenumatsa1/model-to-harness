from __future__ import annotations

import pytest
from agent_framework import WorkflowCheckpoint, WorkflowCheckpointException, WorkflowEvent
from maf_double_charge.application.models import (
    ApprovalDecision,
    ApprovalResponse,
    BranchResult,
    RunStatus,
    WorkflowState,
)
from maf_double_charge.infrastructure.persistence.maf_checkpoints import (
    PostgresRunCheckpointStorage,
)
from maf_double_charge.infrastructure.persistence.postgres import PostgresRepository
from maf_double_charge.maf.messages import ApprovalRequest


async def test_new_typed_checkpoints_survive_real_postgres_restart(
    postgres_repository: PostgresRepository, database_url: str, database_schema: str
) -> None:
    state = WorkflowState(
        run_id="run-checkpoint",
        case_id="case-checkpoint",
        complaint="I was charged twice.",
        customer_id="customer-100",
        scenario_id="duplicate-confirmed",
        idempotency_key="refund-key",
        billing_validation=BranchResult(branch="billing_validation", ok=True, summary="Confirmed."),
    )
    await postgres_repository.create_run(state)
    approval = ApprovalResponse.model_validate_json(
        ApprovalResponse(
            decision=ApprovalDecision.APPROVE, reviewer_id="postgres-reviewer"
        ).model_dump_json()
    )
    request_id = f"approval::{state.run_id}"
    checkpoint = WorkflowCheckpoint(
        workflow_name="double-charge",
        graph_signature_hash="new-graph",
        state={"business_state": state, "approval": approval, "status": RunStatus.PAUSED},
        pending_request_info_events={
            request_id: WorkflowEvent(
                "request_info",
                ApprovalRequest(
                    case_id=state.case_id,
                    run_id=state.run_id,
                    evidence_summary="Confirmed duplicate.",
                ),
                request_id=request_id,
                response_type=ApprovalResponse,
            )
        },
    )
    storage = PostgresRunCheckpointStorage(postgres_repository, state.run_id)
    await storage.save(checkpoint)
    assert (
        await postgres_repository.get_state(state.run_id)
    ).checkpoint_id == checkpoint.checkpoint_id
    await postgres_repository.close()
    restarted = PostgresRepository(database_url, database_schema)
    await restarted.initialize()
    try:
        restored_storage = PostgresRunCheckpointStorage(restarted, state.run_id)
        restored = await restored_storage.load(checkpoint.checkpoint_id)
        assert restored.state == checkpoint.state
        assert isinstance(restored.state["business_state"], WorkflowState)
        assert isinstance(restored.state["business_state"].billing_validation, BranchResult)
        assert isinstance(restored.state["approval"], ApprovalResponse)
        request = restored.pending_request_info_events[request_id]
        assert isinstance(request.data, ApprovalRequest)
        assert request.response_type is ApprovalResponse
        assert await restored_storage.list_checkpoint_ids(workflow_name="double-charge") == [
            checkpoint.checkpoint_id
        ]
        assert (
            await restored_storage.get_latest(workflow_name="double-charge")
        ).checkpoint_id == checkpoint.checkpoint_id
        assert await restored_storage.list_checkpoints(workflow_name="other") == []
        other_state = state.model_copy(update={"run_id": "other-run", "case_id": "other-case"})
        await restarted.create_run(other_state)
        other_storage = PostgresRunCheckpointStorage(restarted, other_state.run_id)
        with pytest.raises(WorkflowCheckpointException, match="not found"):
            await other_storage.load(checkpoint.checkpoint_id)
        assert not await other_storage.delete(checkpoint.checkpoint_id)
        with pytest.raises(WorkflowCheckpointException, match="another run"):
            await other_storage.save(checkpoint)
        assert (await restarted.get_state(other_state.run_id)).checkpoint_id is None
        assert await restored_storage.delete(checkpoint.checkpoint_id)
        assert not await restored_storage.delete(checkpoint.checkpoint_id)
        with pytest.raises(WorkflowCheckpointException, match="not found"):
            await restored_storage.load(checkpoint.checkpoint_id)
    finally:
        await restarted.close()
