import pytest
from checkout_recovery_maf.application import CheckoutRecoveryService
from checkout_recovery_maf.infrastructure import InMemoryCaseRepository
from checkout_recovery_maf.maf import (
    DiagnosticToolName,
    HarnessAgentSettings,
    ReadOnlyDiagnosticTool,
    ReadOnlyDiagnosticToolRegistry,
    ToolAccessDeniedError,
    create_harness_agent_if_configured,
)
from checkout_recovery_maf.projections import project_case
from checkout_recovery_maf.testing import FakeAgentFramework, FakeFoundryClientFactory


def test_harness_agent_uses_factory_only_when_explicitly_configured() -> None:
    factory = FakeFoundryClientFactory()
    assert (
        create_harness_agent_if_configured(HarnessAgentSettings(), client_factory=factory) is None
    )
    framework = FakeAgentFramework()
    agent = create_harness_agent_if_configured(
        HarnessAgentSettings(project_endpoint="https://project", model_deployment="model"),
        client_factory=factory,
        importer=lambda _: framework,
    )

    assert agent == {"kind": "harness-agent"}
    assert factory.calls == [("https://project", "model")]
    assert framework.options == {
        "tools": (),
        "disable_file_memory": True,
        "disable_web_search": True,
    }


def test_tool_registry_denies_remediation_and_only_exposes_bounded_reads() -> None:
    registry = ReadOnlyDiagnosticToolRegistry(
        (ReadOnlyDiagnosticTool(DiagnosticToolName.ORDER, lambda: {"status": "checkout_failed"}),)
    )

    assert registry.call("read_order") == {"status": "checkout_failed"}
    with pytest.raises(ToolAccessDeniedError):
        registry.call("submit_remediation")


def test_safe_projection_excludes_private_ledger_and_workspace_content() -> None:
    case = CheckoutRecoveryService(InMemoryCaseRepository()).start_case(
        "recoverable-inventory-reservation"
    )
    response = project_case(case).model_dump()
    rendered = str(response)

    assert "operation_id" not in rendered
    assert "request_fingerprint" not in rendered
    assert "order_id" not in rendered
    assert "content" not in response["workspace_artifact"]
