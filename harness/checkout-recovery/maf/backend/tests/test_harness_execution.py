import json

import pytest
from agent_framework import BaseChatClient, ChatResponse, Content, FunctionInvocationLayer, Message
from checkout_recovery_maf.application.ports import InvestigationIncompleteError
from checkout_recovery_maf.maf.investigation import MafInvestigator
from model_to_harness_shared import (
    CheckoutDiagnosticReadError,
    CheckoutSimulator,
    get_checkout_fixture,
)


class ScriptedModel(FunctionInvocationLayer, BaseChatClient):
    def __init__(self, order: list[str]):
        super().__init__()
        self.calls = order + ["file_access_write"]
        self.observed_tools: list[str] = []

    async def _inner_get_response(self, *, messages, stream, options, **kwargs):
        assert not stream
        self.observed_tools = [tool.name for tool in options.get("tools", [])]
        if self.calls:
            name = self.calls.pop(0)
            arguments = (
                {"file_name": "plan.md", "content": "Inspect payment and reservation."}
                if name == "file_access_write"
                else {}
            )
            return ChatResponse(
                messages=Message(
                    role="assistant",
                    contents=[
                        Content.from_function_call(
                            call_id=f"call-{len(self.calls)}",
                            name=name,
                            arguments=json.dumps(arguments),
                        )
                    ],
                )
            )
        return ChatResponse(
            messages=Message(
                role="assistant", contents=[Content.from_text("Recommend policy review.")]
            )
        )


@pytest.mark.parametrize(
    "order",
    [
        ["read_order", "read_payment", "read_inventory"],
        ["read_payment", "read_inventory", "read_order"],
    ],
)
async def test_real_maf_harness_executes_model_selected_tools_and_workspace(order):
    fixture = get_checkout_fixture("recoverable-inventory-reservation")
    simulator = CheckoutSimulator(
        order=fixture.order,
        payment_attempt=fixture.payment_attempt,
        reservation=fixture.reservation,
    )
    model = ScriptedModel(order)
    result = await MafInvestigator.run_with_client(model, simulator)
    assert list(result.selected_tools) == order
    assert result.mode == "maf"
    assert result.framework_state["workspace"]["plan.md"]
    assert "load_skill" in model.observed_tools
    assert "submit_remediation" not in model.observed_tools
    assert simulator.remediation_results == ()


async def test_optional_log_tool_cannot_consume_authoritative_failure():
    fixture = get_checkout_fixture("diagnostic-read-failure")
    simulator = CheckoutSimulator(
        order=fixture.order,
        payment_attempt=fixture.payment_attempt,
        reservation=fixture.reservation,
        diagnostic_read_failures=1,
    )
    model = ScriptedModel(["read_logs", "read_order", "read_payment", "read_inventory"])
    await MafInvestigator.run_with_client(model, simulator)
    with pytest.raises(CheckoutDiagnosticReadError):
        simulator.read_diagnostic()


async def test_model_claim_is_not_accepted_without_diagnostic_evidence():
    fixture = get_checkout_fixture("recoverable-inventory-reservation")
    simulator = CheckoutSimulator(
        order=fixture.order,
        payment_attempt=fixture.payment_attempt,
        reservation=fixture.reservation,
    )
    with pytest.raises(InvestigationIncompleteError, match="required diagnostic evidence"):
        await MafInvestigator.run_with_client(ScriptedModel([]), simulator)
