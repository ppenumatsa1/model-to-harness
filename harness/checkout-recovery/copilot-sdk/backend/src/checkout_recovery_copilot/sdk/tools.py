"""The complete case-local capability boundary exposed to the native loop."""

import asyncio
import json
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from copilot import Tool, ToolInvocation, ToolResult
from model_to_harness_shared import CheckoutSimulator
from opentelemetry import trace

from checkout_recovery_copilot.application.ports import InvestigationIncompleteError
from checkout_recovery_copilot.infrastructure.telemetry import operation, record_fixture_diagnostic

from .cancellation import current_signal

MAX_TOOLS = 24
MAX_MODEL_ATTEMPTS = 12
MAX_PLAN_BYTES = 8192
READ_TOOLS = ("read_order", "read_payment", "read_inventory", "read_logs")
CUSTOM_TOOLS = (*READ_TOOLS, "write_plan", "read_plan", "delegate_inventory")


class Evidence:
    def __init__(self) -> None:
        self.selected: list[str] = []
        self.active = True
        self.tool_calls = 0
        self.model_turns = 0
        self.model_retries = 0
        self.model_usage_events = 0
        self.skill_invoked = False
        self.skill_completed = False
        self.plan_written = False
        self.plan_read = False
        self.delegated = False
        self.child_completed = False
        self.failure: BaseException | None = None
        self.failed = asyncio.Event()
        self.tool_names: dict[str, str] = {}
        self.completed_tools: set[str] = set()
        self.cancellation_signal = current_signal()

    def fail(self, error: BaseException) -> None:
        if self.failure is None:
            self.failure = error
        self.active = False
        self.failed.set()

    def require_active(self) -> None:
        if self.cancellation_signal is not None and self.cancellation_signal.is_set():
            cancelled = asyncio.CancelledError("Copilot investigation cancelled")
            self.fail(cancelled)
            raise cancelled
        if not self.active:
            raise InvestigationIncompleteError("investigation is no longer active")

    async def pre_tool(
        self, data: dict, _invocation: Any, *, child: bool = False
    ) -> dict[str, str]:
        name = data.get("toolName", "").removeprefix("functions.")
        args = data.get("toolArgs", {})
        if self.cancellation_signal is not None and self.cancellation_signal.is_set():
            self.fail(asyncio.CancelledError("Copilot investigation cancelled"))
        allowed = (
            name == "read_inventory"
            if child
            else name in CUSTOM_TOOLS
            or (
                name == "skill"
                and isinstance(args, dict)
                and args.get("skill") == "checkout-triage"
            )
        )
        if not self.active or not allowed or self.tool_calls >= MAX_TOOLS:
            self.fail(InvestigationIncompleteError("tool boundary or budget exceeded"))
            return {"permissionDecision": "deny", "permissionDecisionReason": "case tool boundary"}
        self.tool_calls += 1
        return {"permissionDecision": "allow"}

    def event(self, event: Any) -> None:
        kind = getattr(event.type, "value", event.type)
        data = event.data
        if kind in {"assistant.turn_start", "assistant.turn_retry"}:
            if kind == "assistant.turn_start":
                self.model_turns += 1
            else:
                self.model_retries += 1
            # The pinned SDK has no before-model hook. This is an observed
            # turn/retry limit with cancellation, not an exact HTTP-request cap.
            if self.model_turns + self.model_retries > MAX_MODEL_ATTEMPTS:
                self.fail(InvestigationIncompleteError("observed model attempt budget exceeded"))
        elif kind == "assistant.usage":
            self.model_usage_events += 1
        elif kind == "skill.invoked" and getattr(data, "name", None) == "checkout-triage":
            self.skill_invoked = True
        elif kind == "tool.execution_start":
            self.tool_names[data.tool_call_id] = data.tool_name
        elif kind == "tool.execution_complete":
            name = self.tool_names.get(data.tool_call_id)
            if data.success and name:
                self.completed_tools.add(name)
                if name == "skill":
                    self.skill_completed = True
        elif kind == "session.error":
            self.fail(InvestigationIncompleteError("native session reported an error"))

    def verify(self) -> None:
        if self.failure is not None:
            raise self.failure
        if not set(READ_TOOLS[:3]).issubset(self.selected):
            raise InvestigationIncompleteError("required diagnostic evidence was not gathered")
        if not {*READ_TOOLS[:3], "write_plan", "read_plan"}.issubset(self.completed_tools):
            raise InvestigationIncompleteError("native diagnostic tools did not complete")
        if not (self.skill_invoked and self.skill_completed):
            raise InvestigationIncompleteError("native checkout skill was not completed")
        if not (self.plan_written and self.plan_read):
            raise InvestigationIncompleteError("workspace plan was not written and read")


def build_tools(
    simulator: CheckoutSimulator,
    workspace: Path,
    evidence: Evidence,
    delegate: Callable[[], Awaitable[None]],
    *,
    child: bool = False,
    fixture_content: bool = False,
) -> list[Tool]:
    async def run(name: str, invocation: ToolInvocation) -> ToolResult:
        try:
            evidence.require_active()
            arguments = invocation.arguments
            if not isinstance(arguments, dict):
                raise InvestigationIncompleteError("invalid diagnostic tool arguments")
            expected = {"content"} if name == "write_plan" else set()
            if set(arguments) != expected:
                raise InvestigationIncompleteError("invalid diagnostic tool arguments")
            with operation(f"tool.{name}"):
                result: Any
                if name == "read_order":
                    result = {"status": simulator.order.status.value}
                elif name == "read_payment":
                    result = {
                        "status": simulator.payment_attempt.status.value,
                        "amount_minor": simulator.payment_attempt.amount_minor,
                    }
                elif name == "read_inventory":
                    result = {
                        "status": simulator.reservation.status.value,
                        "quantity": simulator.reservation.quantity,
                    }
                elif name == "read_logs":
                    copy = CheckoutSimulator.from_snapshot(simulator.snapshot())
                    result = {"reason": copy.read_diagnostic().reason}
                elif name == "write_plan":
                    text = arguments["content"]
                    if (
                        not isinstance(text, str)
                        or not text.strip()
                        or len(text.encode("utf-8")) > MAX_PLAN_BYTES
                    ):
                        raise InvestigationIncompleteError("invalid bounded workspace plan")
                    path = workspace / "plan.md"
                    if path.is_symlink():
                        raise InvestigationIncompleteError("invalid workspace")
                    path.write_text(text, encoding="utf-8")
                    path.chmod(0o600)
                    evidence.plan_written = True
                    result = {"written": "plan.md"}
                elif name == "read_plan":
                    path = workspace / "plan.md"
                    if (
                        path.is_symlink()
                        or not path.is_file()
                        or path.stat().st_size > MAX_PLAN_BYTES
                    ):
                        raise InvestigationIncompleteError("workspace plan was not produced")
                    result = {"content": path.read_text(encoding="utf-8")}
                    evidence.plan_read = True
                elif name == "delegate_inventory":
                    if evidence.delegated:
                        raise InvestigationIncompleteError("only one delegation is permitted")
                    evidence.delegated = True
                    await delegate()
                    evidence.require_active()
                    evidence.child_completed = True
                    # Do not use child freeform output as authoritative evidence.
                    result = {
                        "status": simulator.reservation.status.value,
                        "quantity": simulator.reservation.quantity,
                    }
                else:
                    raise InvestigationIncompleteError("unknown diagnostic tool")
                if fixture_content and name in READ_TOOLS[:3]:
                    record_fixture_diagnostic(trace.get_current_span(), name, result)
                evidence.selected.append(name)
                return ToolResult(text_result_for_llm=json.dumps(result))
        except Exception as error:
            # SDK tool dispatch otherwise converts exceptions into retryable text.
            # Preserve deterministic simulator exceptions outside the model loop.
            evidence.fail(error)
            return ToolResult(result_type="failure", error="diagnostic tool failed")

    names = ("read_inventory",) if child else CUSTOM_TOOLS
    tools = []
    for name in names:

        async def handler(invocation: ToolInvocation, tool_name: str = name) -> ToolResult:
            return await run(tool_name, invocation)

        tools.append(
            Tool(
                name=name,
                description={
                    "read_order": "Read this case's order status.",
                    "read_payment": "Read this case's payment status and amount.",
                    "read_inventory": "Read this case's reservation status and quantity.",
                    "read_logs": "Read one bounded deterministic checkout diagnostic.",
                    "write_plan": "Write short diagnostic content to this case's plan.md only.",
                    "read_plan": "Read the private case plan.md only.",
                    "delegate_inventory": "Run the read-only inventory specialist once.",
                }[name],
                parameters={
                    "type": "object",
                    "properties": {"content": {"type": "string", "maxLength": MAX_PLAN_BYTES}}
                    if name == "write_plan"
                    else {},
                    "required": ["content"] if name == "write_plan" else [],
                    "additionalProperties": False,
                },
                handler=handler,
                skip_permission=True,
            )
        )
    return tools
