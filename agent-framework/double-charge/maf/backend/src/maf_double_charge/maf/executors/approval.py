from __future__ import annotations

from agent_framework import Executor, WorkflowContext, handler, response_handler

from ...application.audit import Audit
from ...application.models import ApprovalDecision, ApprovalResponse, RunStatus, WorkflowState
from ..dependencies import WorkflowDependencies
from ..messages import ApprovalRequest


class ApprovalExecutor(Executor):
    def __init__(self, audit: Audit, dependencies: WorkflowDependencies) -> None:
        super().__init__(id="approval_checkpoint")
        self.audit = audit
        self.dependencies = dependencies

    @handler
    async def request(
        self,
        state: WorkflowState,
        ctx: WorkflowContext[WorkflowState],
    ) -> None:
        await self.audit.node_started(state, self.id)
        evidence = self.dependencies.actions.last_evidence
        if evidence is None:
            failed = state.advance(
                "route_failure",
                status=RunStatus.FAILED,
                terminal_status="failed",
                failure_code="billing_validation_failed",
            )
            await self.audit.save(failed)
            await ctx.send_message(failed)
            return
        self.dependencies.actions.request_approval(evidence.model_dump(mode="json"), state.case_id)
        paused = state.advance(
            self.id,
            status=RunStatus.PAUSED,
            approval_required=True,
            terminal_status="waiting_approval",
        )
        await self.audit.save(paused)
        await self.audit.emit(
            paused,
            "approval.requested",
            "Human approval is required before submitting the refund.",
            node=self.id,
            payload={
                "amount": str(evidence.amount) if evidence.amount is not None else None,
                "currency": evidence.currency,
                "evidence_summary": evidence.rationale,
            },
        )
        await ctx.request_info(
            ApprovalRequest(
                case_id=paused.case_id,
                run_id=paused.run_id,
                evidence_summary=evidence.rationale,
                amount=str(evidence.amount) if evidence.amount is not None else None,
                currency=evidence.currency,
            ),
            ApprovalResponse,
            request_id=f"approval::{paused.run_id}",
        )

    @response_handler(
        request=ApprovalRequest,
        response=ApprovalResponse,
        output=WorkflowState,
    )
    async def resolve(self, original_request, response, ctx) -> None:
        state = await self.dependencies.repository.get_state(original_request.run_id)
        if state is None:
            raise RuntimeError("run state disappeared before approval resume")
        self.dependencies.actions.resolve_approval(
            response.decision, response.reviewer_id, response.reason
        )
        resumed = state.advance(
            self.id,
            status=RunStatus.RUNNING,
            approval_required=False,
            approval_decision=response.decision,
            terminal_status=None,
        )
        await self.audit.save(resumed)
        await self.audit.emit(
            resumed,
            "approval.resolved",
            f"Approval was {response.decision.value} by {response.reviewer_id}.",
            node=self.id,
            checkpoint_id=state.checkpoint_id,
            payload={"decision": response.decision.value, "reviewer_id": response.reviewer_id},
        )
        target = (
            "submit_refund" if response.decision == ApprovalDecision.APPROVE else "close_denied"
        )
        await self.audit.edge(resumed, self.id, target, f"Approval route selected: {target}.")
        await ctx.send_message(resumed)
