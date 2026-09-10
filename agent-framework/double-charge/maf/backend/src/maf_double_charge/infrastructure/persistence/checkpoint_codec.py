from __future__ import annotations

from typing import Any

from agent_framework import WorkflowCheckpoint
from agent_framework._workflows._checkpoint_encoding import (  # type: ignore[import-not-found]
    decode_checkpoint_value,
    encode_checkpoint_value,
)

# The sole SDK-internal seam follows MAF FileCheckpointStorage's restricted codec.
# Only fresh, final-path application records are accepted; there is no legacy reader.
ALLOWED_CHECKPOINT_TYPES = frozenset(
    {
        "maf_double_charge.maf.messages:ApprovalRequest",
        "maf_double_charge.application.models:ApprovalResponse",
        "maf_double_charge.application.models:ApprovalDecision",
        "maf_double_charge.application.models:BranchResult",
        "maf_double_charge.application.models:NodeStatus",
        "maf_double_charge.application.models:RunStatus",
        "maf_double_charge.application.models:WorkflowState",
        "pydantic_core._pydantic_core:TzInfo",
    }
)


def encode_checkpoint(checkpoint: WorkflowCheckpoint) -> dict[str, Any]:
    return encode_checkpoint_value(checkpoint.to_dict())


def decode_checkpoint(value: dict[str, Any]) -> WorkflowCheckpoint:
    return WorkflowCheckpoint.from_dict(
        decode_checkpoint_value(value, allowed_types=ALLOWED_CHECKPOINT_TYPES)
    )
