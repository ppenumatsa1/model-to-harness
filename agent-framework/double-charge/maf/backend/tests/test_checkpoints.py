from __future__ import annotations

import json

from agent_framework import WorkflowCheckpoint
from maf_double_charge.checkpoints import (
    _ALLOWED_CHECKPOINT_TYPES,
    decode_checkpoint_value,
    encode_checkpoint_value,
)
from maf_double_charge.models import ApprovalDecision, ApprovalResponse, RunStatus, ScenarioInput
from maf_double_charge.orchestrator import DoubleChargeOrchestrator


async def test_maf_checkpoint_codec_preserves_typed_approval_request(
    orchestrator: DoubleChargeOrchestrator,
) -> None:
    started = await orchestrator.start(
        ScenarioInput(
            complaint="I was charged twice.",
            customer_id="customer-100",
            scenario_id="duplicate-confirmed",
        )
    )
    assert started.checkpoint_id
    storage = orchestrator._runtimes[started.run_id].checkpoint_storage
    checkpoint = storage.checkpoints[started.checkpoint_id]
    encoded = encode_checkpoint_value(checkpoint.to_dict())
    decoded = decode_checkpoint_value(
        json.loads(json.dumps(encoded)),
        allowed_types=_ALLOWED_CHECKPOINT_TYPES,
    )
    restored = WorkflowCheckpoint.from_dict(decoded)
    request = restored.pending_request_info_events[f"approval::{started.run_id}"]
    assert request.data.run_id == started.run_id
    assert request.request_id == f"approval::{started.run_id}"


def test_maf_checkpoint_codec_allows_workflow_status_enums() -> None:
    encoded = encode_checkpoint_value({"status": RunStatus.COMPLETED})
    decoded = decode_checkpoint_value(
        json.loads(json.dumps(encoded)),
        allowed_types=_ALLOWED_CHECKPOINT_TYPES,
    )
    assert decoded == {"status": RunStatus.COMPLETED}


def test_maf_checkpoint_codec_allows_approval_timestamp_timezone() -> None:
    response = ApprovalResponse(
        decision=ApprovalDecision.APPROVE,
        reviewer_id="checkpoint-test",
    )
    encoded = encode_checkpoint_value({"approval": response})
    decoded = decode_checkpoint_value(
        json.loads(json.dumps(encoded)),
        allowed_types=_ALLOWED_CHECKPOINT_TYPES,
    )
    assert decoded["approval"] == response
