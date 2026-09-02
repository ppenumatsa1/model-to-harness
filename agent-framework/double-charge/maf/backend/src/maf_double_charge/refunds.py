from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from typing import Any

from .models import RefundLedgerEntry, WorkflowState
from .repository import RefundIdempotencyConflictError, Repository
from .shared_actions import RootSharedActions, UncertainRefundResponseError


def request_fingerprint(request: dict[str, Any]) -> str:
    canonical = json.dumps(request, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class RefundSubmission:
    refund: dict[str, Any]
    recovered_existing: bool


class DurableRefundService:
    def __init__(self, repository: Repository) -> None:
        self.repository = repository

    async def submit(
        self,
        state: WorkflowState,
        actions: RootSharedActions,
    ) -> RefundSubmission:
        request = actions.refund_request(state.idempotency_key)
        fingerprint = request_fingerprint(request)
        existing = await self.repository.get_refund(state.idempotency_key)
        if existing is not None:
            if existing.request_fingerprint != fingerprint:
                raise RefundIdempotencyConflictError(
                    "idempotency key is already bound to a different refund request"
                )
            return RefundSubmission(refund=existing.refund, recovered_existing=True)

        try:
            refund = await asyncio.to_thread(
                actions.submit_refund, state.idempotency_key
            )
        except UncertainRefundResponseError:
            refund = actions.find_refund(state.idempotency_key)
            if refund is not None:
                await self._store(state, request, fingerprint, refund)
            raise

        stored, created = await self._store(state, request, fingerprint, refund)
        return RefundSubmission(refund=stored.refund, recovered_existing=not created)

    async def _store(
        self,
        state: WorkflowState,
        request: dict[str, Any],
        fingerprint: str,
        refund: dict[str, Any],
    ) -> tuple[RefundLedgerEntry, bool]:
        entry = RefundLedgerEntry(
            idempotency_key=state.idempotency_key,
            request_fingerprint=fingerprint,
            account_id=request["account_id"],
            charge_id=request["charge_id"],
            amount=request["amount"],
            currency=request["currency"],
            refund_id=refund["refund_id"],
            refund=refund,
            created_by_run_id=state.run_id,
        )
        return await self.repository.store_refund(entry)

    async def verify(
        self,
        state: WorkflowState,
        actions: RootSharedActions,
    ) -> dict[str, Any]:
        entry = await self.repository.get_refund(state.idempotency_key)
        durable_count = await self.repository.count_refunds(state.idempotency_key)
        override = actions.verification_count_override
        count = override if override is not None else durable_count
        verified = count == 1 and entry is not None
        return {
            "idempotency_key": state.idempotency_key,
            "matching_refund_count": count,
            "verified": verified,
            "refund_id": entry.refund_id if verified and entry is not None else None,
            "reason": (
                "Exactly one matching durable refund exists."
                if verified
                else f"Expected one matching durable refund; found {count}."
            ),
        }
