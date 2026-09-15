import asyncio
from pathlib import Path
from typing import Any

from agent_framework import Agent, InMemoryAgentFileStore, SkillsProvider, create_harness_agent
from agent_framework.foundry import FoundryChatClient
from azure.ai.projects.aio import AIProjectClient
from azure.core.exceptions import AzureError
from azure.identity.aio import DefaultAzureCredential
from model_to_harness_shared import CheckoutSimulator
from openai import APIError

from checkout_recovery_maf.application.models import InvestigationResult
from checkout_recovery_maf.application.ports import InvestigationIncompleteError
from checkout_recovery_maf.infrastructure.telemetry import operation


class ScriptedInvestigator:
    """Explicit offline test mode, never a fallback for a failed model call."""

    def investigate(self, simulator: CheckoutSimulator) -> InvestigationResult:
        return InvestigationResult(
            selected_tools=("read_order", "read_payment", "read_inventory"),
            mode="scripted",
        )


class MafInvestigator:
    def __init__(self, endpoint: str, model: str) -> None:
        self.endpoint = endpoint
        self.model = model

    def investigate(self, simulator: CheckoutSimulator) -> InvestigationResult:
        with operation("harness"):
            try:
                return asyncio.run(self._invoke(simulator))
            except (AzureError, APIError, TimeoutError) as error:
                raise InvestigationIncompleteError("harness invocation failed") from error

    async def _invoke(self, simulator: CheckoutSimulator) -> InvestigationResult:
        async with (
            DefaultAzureCredential() as credential,
            AIProjectClient(endpoint=self.endpoint, credential=credential) as project,
        ):
            client = FoundryChatClient(
                project_client=project,
                model=self.model,
                function_invocation_configuration={
                    "max_iterations": 12,
                    "max_function_calls": 24,
                    "max_duration_seconds": 90,
                    "include_detailed_errors": False,
                    "terminate_on_unknown_calls": True,
                },
            )
            return await self.run_with_client(client, simulator)

    @staticmethod
    async def run_with_client(client: Any, simulator: CheckoutSimulator) -> InvestigationResult:
        selected: list[str] = []
        workspace = InMemoryAgentFileStore()
        delegated = False

        def read_order() -> dict[str, str]:
            """Inspect this case's order state; contains no customer identity."""
            with operation("tool.read_order"):
                selected.append("read_order")
                return {"status": simulator.order.status.value}

        def read_payment() -> dict[str, str | int]:
            """Inspect payment status before proposing any checkout remedy."""
            with operation("tool.read_payment"):
                selected.append("read_payment")
                return {
                    "status": simulator.payment_attempt.status.value,
                    "amount_minor": simulator.payment_attempt.amount_minor,
                }

        def read_inventory() -> dict[str, str | int]:
            """Inspect reservation status and quantity for this case only."""
            with operation("tool.read_inventory"):
                selected.append("read_inventory")
                return {
                    "status": simulator.reservation.status.value,
                    "quantity": simulator.reservation.quantity,
                }

        def read_logs() -> dict[str, str]:
            """Inspect the bounded deterministic diagnostic record."""
            with operation("tool.read_logs"):
                selected.append("read_logs")
                snapshot = CheckoutSimulator.from_snapshot(simulator.snapshot())
                return {"reason": snapshot.read_diagnostic().reason}

        child = Agent(
            client=client,
            name="inventory-specialist",
            instructions="Read inventory once. Report only the reservation status and quantity.",
            tools=[read_inventory],
        )

        async def delegate_inventory() -> str:
            """Optionally delegate one read-only inventory inspection to a bounded subagent."""
            nonlocal delegated
            if delegated:
                raise InvestigationIncompleteError("only one delegation is permitted")
            delegated = True
            selected.append("delegate_inventory")
            with operation("subagent"):
                result = await child.run(
                    "Inspect the reservation for the current case.",
                    session=child.create_session(),
                    options={"store": False},
                )
                return result.text

        agent = create_harness_agent(
            client=client,
            name="checkout-recovery",
            agent_instructions=(
                "Investigate the failed checkout. Load the checkout-triage skill. "
                "Use read_order, read_payment and read_inventory (or delegate_inventory) "
                "in whichever order the evidence warrants. read_logs is optional. "
                "Write a short plan to plan.md using the workspace file tools. "
                "You have no business-write tools. Never approve, refund, or claim recovery. "
                "Finish with a brief diagnostic recommendation; application policy and "
                "verification decide the outcome. Do not run shell commands or web searches."
            ),
            tools=[read_order, read_payment, read_inventory, read_logs, delegate_inventory],
            skills_paths=Path(__file__).parent / "skills",
            auto_approval_rules=[SkillsProvider.read_only_tools_auto_approval_rule],
            file_access_store=workspace,
            file_access_disable_readonly_tool_approval=True,
            file_access_disable_write_tool_approval=True,
            disable_file_memory=True,
            disable_web_search=True,
            disable_mode=True,
            max_context_window_tokens=16000,
            max_output_tokens=2000,
            default_options={"store": False},
        )
        session = agent.create_session()
        with operation("model"):
            await asyncio.wait_for(
                agent.run("Checkout failed. Investigate this case safely.", session=session),
                timeout=120,
            )
        required = {"read_order", "read_payment", "read_inventory"}
        if not required.issubset(selected):
            raise InvestigationIncompleteError("required diagnostic evidence was not gathered")
        try:
            plan = await workspace.read("plan.md")
        except FileNotFoundError as error:
            raise InvestigationIncompleteError("workspace plan was not produced") from error
        if not plan:
            raise InvestigationIncompleteError("workspace plan was not produced")
        return InvestigationResult(
            selected_tools=tuple(selected),
            mode="maf",
            framework_state={"session": session.to_dict(), "workspace": {"plan.md": plan}},
        )
