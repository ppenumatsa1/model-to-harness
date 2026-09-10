from contextlib import contextmanager
from typing import Any

from ..application.ports import AuditRepository
from ..infrastructure.domain_gateway import DomainGateway
from ..infrastructure.model_client import ComplaintModel
from .nodes.approval import ApprovalNodes
from .nodes.completion import CompletionNodes
from .nodes.investigation import InvestigationNodes
from .nodes.refund import RefundNodes
from .nodes.validation import ValidationNodes
from .workflows.double_charge import build_graph


class DoubleChargeWorkflow(
    InvestigationNodes, ValidationNodes, ApprovalNodes, RefundNodes, CompletionNodes
):
    def __init__(
        self,
        *,
        audit: AuditRepository,
        gateway: DomainGateway,
        model: ComplaintModel,
        checkpointer: Any,
        interrupt_after: list[str] | None = None,
    ) -> None:
        self.audit = audit
        self.gateway = gateway
        self.model = model
        self.graph = build_graph(self).compile(
            checkpointer=checkpointer,
            interrupt_after=interrupt_after or [],
        )

    @contextmanager
    def trace_run(self, run_id: str, *, case_id: str, command: str):
        from ..infrastructure.telemetry import correlation, execution_span

        with execution_span(
            "workflow.run",
            **{
                "workflow.case_id_hash": correlation(case_id),
                "workflow.run_id_hash": correlation(run_id),
                "workflow.command": command,
            },
        ):
            yield

    @staticmethod
    def config(run_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": f"langgraph:{run_id}"}}

    async def start(self, state: dict[str, Any]) -> dict[str, Any]:
        return await self.graph.ainvoke(state, config=self.config(state["run_id"]))

    async def resume(self, run_id: str, decision: dict[str, Any]) -> dict[str, Any]:
        from langgraph.types import Command

        return await self.graph.ainvoke(Command(resume=decision), config=self.config(run_id))

    async def continue_run(self, run_id: str) -> dict[str, Any]:
        return await self.graph.ainvoke(None, config=self.config(run_id))

    async def snapshot(self, run_id: str) -> dict[str, Any] | None:
        snapshot = await self.graph.aget_state(self.config(run_id))
        if not snapshot.values:
            return None
        result = dict(snapshot.values)
        interrupts = tuple(item for task in snapshot.tasks for item in task.interrupts)
        if interrupts:
            result["__interrupt__"] = interrupts
        return result
