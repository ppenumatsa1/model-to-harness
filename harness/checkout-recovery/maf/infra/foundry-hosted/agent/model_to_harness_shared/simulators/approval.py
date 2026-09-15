from decimal import Decimal
from hashlib import sha256

from model_to_harness_shared.domain import (
    ApprovalCommand,
    ApprovalDecision,
    ApprovalRecord,
)


class ApprovalConflictError(ValueError):
    pass


class ApprovalSimulator:
    def __init__(self) -> None:
        self._records: dict[str, ApprovalRecord] = {}

    def request(
        self,
        *,
        case_id: str,
        amount: Decimal,
        currency: str,
    ) -> ApprovalRecord:
        digest = sha256(case_id.encode("utf-8")).hexdigest()[:12]
        checkpoint_id = f"checkpoint-{digest}"
        existing = self._records.get(checkpoint_id)
        if existing is not None:
            if existing.amount != amount or existing.currency != currency:
                raise ApprovalConflictError(
                    "approval checkpoint is already bound to different evidence"
                )
            return existing
        record = ApprovalRecord(
            approval_id=f"approval-{digest}",
            case_id=case_id,
            checkpoint_id=checkpoint_id,
            decision=ApprovalDecision.PENDING,
            amount=amount,
            currency=currency,
        )
        self._records[checkpoint_id] = record
        return record

    def resolve(
        self,
        command: ApprovalCommand,
    ) -> ApprovalRecord:
        record = self._records.get(command.checkpoint_id)
        if record is None:
            raise KeyError("approval checkpoint does not exist")
        if record.decision != ApprovalDecision.PENDING:
            if (
                record.decision == command.decision
                and record.reviewer_id == command.reviewer_id
                and record.reason == command.reason
            ):
                return record
            raise ApprovalConflictError("approval checkpoint already has another decision")
        resolved = ApprovalRecord(
            approval_id=record.approval_id,
            case_id=record.case_id,
            checkpoint_id=record.checkpoint_id,
            decision=command.decision,
            amount=record.amount,
            currency=record.currency,
            reviewer_id=command.reviewer_id,
            reason=command.reason,
        )
        self._records[command.checkpoint_id] = resolved
        return resolved
