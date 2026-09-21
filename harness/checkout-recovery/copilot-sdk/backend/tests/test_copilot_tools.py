import asyncio
import shutil
from pathlib import Path
from uuid import uuid4

import pytest
from checkout_recovery_copilot.application.ports import InvestigationIncompleteError
from checkout_recovery_copilot.sdk import tools as tool_module
from checkout_recovery_copilot.sdk.tools import MAX_PLAN_BYTES, Evidence, build_tools
from copilot import ToolInvocation
from model_to_harness_shared import CheckoutSimulator, get_checkout_fixture


@pytest.fixture
def workspace():
    path = Path(".azure/copilot-tool-tests") / uuid4().hex
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path)


def fixture_simulator():
    fixture = get_checkout_fixture("recoverable-inventory-reservation")
    return CheckoutSimulator(
        order=fixture.order,
        payment_attempt=fixture.payment_attempt,
        reservation=fixture.reservation,
    )


def invoke(tools, name, arguments):
    tool = next(item for item in tools if item.name == name)
    return tool.handler(
        ToolInvocation(
            session_id=str(uuid4()), tool_call_id="test", tool_name=name, arguments=arguments
        )
    )


@pytest.mark.parametrize(
    "name,args",
    [
        ("read_order", {"order_id": "other-case"}),
        ("write_plan", {"path": "/outside", "content": "bad"}),
        ("write_plan", {"content": "x" * (MAX_PLAN_BYTES + 1)}),
        ("write_plan", {"content": ""}),
        ("write_plan", {"content": None}),
        ("read_plan", {"path": "../other"}),
        ("read_inventory", []),
    ],
)
def test_tools_reject_unbounded_or_invalid_arguments(workspace, name, args):
    async def check():
        evidence = Evidence()
        tools = build_tools(fixture_simulator(), workspace, evidence, lambda: None)
        result = await invoke(tools, name, args)
        assert result.result_type == "failure"
        assert isinstance(evidence.failure, InvestigationIncompleteError)
        assert not evidence.active
        assert not list(workspace.iterdir())

    asyncio.run(check())


def test_plan_symlink_denied_and_late_callbacks_closed(workspace):
    async def check():
        evidence = Evidence()
        tools = build_tools(fixture_simulator(), workspace, evidence, lambda: None)
        original = workspace / "original"
        original.write_text("unchanged")
        (workspace / "plan.md").symlink_to(original.resolve())
        assert (await invoke(tools, "write_plan", {"content": "bad"})).result_type == "failure"
        assert original.read_text() == "unchanged"
        assert (await invoke(tools, "read_order", {})).result_type == "failure"
        assert evidence.selected == []

    asyncio.run(check())


def test_diagnostics_do_not_mutate_authoritative_simulator(workspace):
    async def check():
        simulator = fixture_simulator()
        before = simulator.snapshot()
        evidence = Evidence()
        tools = build_tools(simulator, workspace, evidence, lambda: None)
        for name in ("read_order", "read_payment", "read_inventory", "read_logs"):
            assert (await invoke(tools, name, {})).result_type == "success"
        assert simulator.snapshot() == before
        assert all("refund" not in tool.name and "approve" not in tool.name for tool in tools)

    asyncio.run(check())


def test_delegate_is_once_only_and_child_has_single_capability(workspace):
    async def check():
        evidence = Evidence()
        count = 0

        async def delegate():
            nonlocal count
            count += 1

        tools = build_tools(fixture_simulator(), workspace, evidence, delegate)
        assert (await invoke(tools, "delegate_inventory", {})).result_type == "success"
        assert (await invoke(tools, "delegate_inventory", {})).result_type == "failure"
        assert count == 1
        children = build_tools(fixture_simulator(), workspace, evidence, delegate, child=True)
        assert [tool.name for tool in children] == ["read_inventory"]

    asyncio.run(check())


@pytest.mark.parametrize("enabled", [False, True])
def test_fixture_content_is_explicit_and_excludes_other_tool_payloads(
    workspace, monkeypatch, enabled
):
    captured = []
    monkeypatch.setattr(
        tool_module,
        "record_fixture_diagnostic",
        lambda span, name, result: captured.append((span, name, result)),
    )

    async def check():
        evidence = Evidence()
        tools = build_tools(
            fixture_simulator(), workspace, evidence, lambda: None, fixture_content=enabled
        )
        for name in ("read_order", "read_payment", "read_inventory", "read_logs"):
            await invoke(tools, name, {})
        await invoke(tools, "write_plan", {"content": "PRIVATE-WORKSPACE-NOT-TELEMETRY"})
        await invoke(tools, "read_plan", {})

    asyncio.run(check())
    assert [item[1] for item in captured] == (
        ["read_order", "read_payment", "read_inventory"] if enabled else []
    )
    if enabled:
        assert [set(item[2]) for item in captured] == [
            {"status"},
            {"status", "amount_minor"},
            {"status", "quantity"},
        ]
        assert all(item[0] is not None for item in captured)
        assert "PRIVATE" not in repr(captured)


def test_unknown_fixture_payload_is_not_recorded(caplog):
    class Span:
        attributes = {}

        def set_attribute(self, name, value):
            self.attributes[name] = value

    span = Span()
    tool_module.record_fixture_diagnostic(
        span, "read_order", {"status": "checkout_failed", "secret": "PRIVATE-UNKNOWN-CANARY"}
    )
    assert span.attributes == {}
    assert "PRIVATE" not in caplog.text
