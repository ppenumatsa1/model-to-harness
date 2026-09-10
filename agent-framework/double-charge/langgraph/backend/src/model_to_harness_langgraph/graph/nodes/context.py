import hashlib
import logging
from typing import Any

from ...application.ports import AuditRepository
from ...infrastructure.domain_gateway import DomainGateway, ToolResult
from ...infrastructure.model_client import ComplaintModel
from ...infrastructure.telemetry import correlation
from ..state import DoubleChargeState

logger = logging.getLogger(__name__)


class NodeContext:
    audit: AuditRepository
    gateway: DomainGateway
    model: ComplaintModel

    async def _event(
        self,
        state: DoubleChargeState,
        event_type: str,
        summary: str,
        *,
        node: str | None = None,
        status: str | None = None,
        data: dict[str, Any] | None = None,
        dedupe_key: str | None = None,
    ) -> None:
        await self.audit.append_event(
            case_id=state["case_id"],
            run_id=state["run_id"],
            event_type=event_type,
            summary=summary,
            node=node,
            status=status,
            data=data,
            dedupe_key=dedupe_key
            or (
                f"{node}:{event_type}:{(data or {}).get('attempt', 0)}:"
                f"{(data or {}).get('tool', '')}:{status or ''}"
            ),
        )
        logger.info(
            event_type,
            extra={
                "safe_event": event_type,
                "case_id_hash": correlation(state["case_id"]),
                "run_id_hash": correlation(state["run_id"]),
                "node": node,
                "retry_count": data.get("attempt") if data else None,
                "idempotency_key_hash": _key_hash(state.get("idempotency_key")),
            },
        )

    async def _tool_start(
        self, state: DoubleChargeState, node: str, tool: str, attempt: int | None = None
    ) -> None:
        tool_call_id = f"{state['run_id']}:{node}:{attempt or 1}"
        await self._event(
            state,
            "tool_call_started",
            f"{tool} started",
            node=node,
            status="running",
            data={"tool": tool, "attempt": attempt, "tool_call_id": tool_call_id},
        )

    async def _tool_end(
        self,
        state: DoubleChargeState,
        node: str,
        tool: str,
        result: ToolResult,
        attempt: int | None = None,
    ) -> None:
        tool_call_id = f"{state['run_id']}:{node}:{attempt or 1}"
        await self._event(
            state,
            "tool_call_succeeded" if result.ok else "tool_call_failed",
            result.safe_summary or f"{tool} {'completed' if result.ok else 'failed'}",
            node=node,
            status="completed" if result.ok else "failed",
            data={
                "tool": tool,
                "attempt": attempt,
                "tool_call_id": tool_call_id,
                "failure_code": result.code,
            },
        )


def _key_hash(key: str | None) -> str | None:
    if not key:
        return None
    return hashlib.sha256(key.encode()).hexdigest()
