import asyncio
import importlib.util
import json
import logging
import sys
import threading
import traceback
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, Mock

import pytest
from checkout_recovery_maf.application import CheckoutRecoveryService
from checkout_recovery_maf.infrastructure import InMemoryCaseRepository
from psycopg import OperationalError

ENTRYPOINT = Path(__file__).resolve().parents[2] / "infra/foundry-hosted/agent/main.py"


@pytest.fixture
def hosted(monkeypatch):
    sdk = ModuleType("azure.ai.agentserver.responses")
    sdk.ResponsesAgentServerHost = Mock()
    sdk.TextResponse = lambda *args, text: text
    monkeypatch.setitem(sys.modules, sdk.__name__, sdk)
    spec = importlib.util.spec_from_file_location("checkout_hosted_test", ENTRYPOINT)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


async def test_hosted_initializes_once_under_concurrent_requests_and_closes_off_loop(
    hosted, monkeypatch
):
    monkeypatch.setenv("CHECKOUT_RECOVERY_EXECUTION_MODE", "scripted")
    loop_thread = threading.get_ident()
    threads = []
    runtime = Mock()
    runtime.start.side_effect = lambda: threads.append(threading.get_ident())
    runtime.close.side_effect = lambda: threads.append(threading.get_ident())
    hosted.create_runtime = Mock(return_value=runtime)
    services = await asyncio.gather(*(hosted._checkout_service() for _ in range(4)))
    assert all(service is runtime.service for service in services)
    hosted.create_runtime.assert_called_once()
    assert hosted.create_runtime.call_args.args[0].execution_mode == "maf"
    assert hosted.create_runtime.call_args.kwargs == {"host": "hosted"}
    runtime.start.assert_called_once_with()
    await hosted._close_runtime()
    await hosted._close_runtime()
    runtime.close.assert_called_once_with()
    assert len(threads) == 2
    assert all(thread != loop_thread for thread in threads)
    assert hosted._runtime is None


async def test_hosted_startup_failure_does_not_publish_runtime_and_can_retry(hosted):
    runtime = Mock()
    runtime.start.side_effect = RuntimeError("startup failed")
    hosted.create_runtime = Mock(return_value=runtime)
    with pytest.raises(RuntimeError, match="startup failed"):
        await hosted._checkout_service()
    runtime.close.assert_called_once_with()
    assert hosted._runtime is None
    replacement = Mock()
    hosted.create_runtime.return_value = replacement
    assert await hosted._checkout_service() is replacement.service
    await hosted._close_runtime()
    replacement.close.assert_called_once_with()


async def test_hosted_cancelled_startup_closes_unpublished_runtime(hosted):
    started = threading.Event()
    release = threading.Event()
    runtime = Mock()

    def start():
        started.set()
        assert release.wait(5), "startup release timed out"

    runtime.start.side_effect = start
    hosted.create_runtime = Mock(return_value=runtime)
    task = asyncio.create_task(hosted._checkout_service())
    try:
        assert await asyncio.to_thread(started.wait, 5)
        task.cancel()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    runtime.close.assert_called_once_with()
    assert hosted._runtime is None


async def test_hosted_main_closes_runtime_after_host_failure(hosted):
    runtime = Mock()
    hosted._runtime = runtime
    host = Mock()
    host.run_async = AsyncMock(side_effect=RuntimeError("host failed"))
    hosted.create_host = Mock(return_value=host)
    with pytest.raises(RuntimeError, match="host failed"):
        await hosted.main()
    runtime.close.assert_called_once_with()
    assert hosted._runtime is None


def test_host_creation_disables_content_before_sdk_initialization(hosted, monkeypatch):
    monkeypatch.setenv("OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT", "true")

    def construct():
        import os

        assert os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] == "false"
        return Mock()

    hosted.ResponsesAgentServerHost = Mock(side_effect=construct)
    host = hosted.create_host()
    host.response_handler.assert_called_once_with(hosted.response_handler)
    assert hosted._runtime is None


@pytest.mark.parametrize(
    "input_value",
    [
        '{"action":"resume","case_id":"case"}',
        {"role": "user", "content": '{"action":"resume","case_id":"case"}'},
        [
            {"role": "user", "content": [{"text": '{"action":"resume","case_id":"case"}'}]},
            {"role": "assistant", "content": '{"action":"approval"}'},
        ],
        [{"content": [{"input_text": '{"action":"resume","case_id":"case"}'}]}],
    ],
)
def test_hosted_preserves_supported_input_shapes(hosted, input_value):
    payload = {"input": input_value}
    expected = {"action": "resume", "case_id": "case"}
    assert hosted._command(payload) == expected
    assert hosted._command(Mock(model_dump=Mock(return_value=payload))) == expected


async def test_hosted_explicit_commands_keep_safe_outputs_and_retry_identity(hosted):
    service = CheckoutRecoveryService(InMemoryCaseRepository())
    hosted._checkout_service = AsyncMock(return_value=service)
    start = {
        "action": "start",
        "fixture_id": "captured-payment-approved-remediation",
        "request_id": "00000000-0000-0000-0000-000000000123",
    }
    result = await hosted._execute(start)
    assert result["case_id"] == start["request_id"]
    assert result["approval_decision"] == "pending"
    assert result["terminal_status"] is None
    assert await hosted._execute(start) == result
    approval = {
        "action": "approval",
        "case_id": result["case_id"],
        "approval_request_id": result["approval_request_id"],
        "decision": "approved",
        "reviewer_id": "reviewer",
        "reason": "Reviewed",
    }
    approved = await hosted._execute(approval)
    assert approved["terminal_status"] is None
    resumed = await hosted._execute({"action": "resume", "case_id": result["case_id"]})
    assert resumed["terminal_status"] == "recovered"
    assert resumed == service.get_case_response(result["case_id"]).model_dump(mode="json")
    assert not {"order_id", "operation_id", "approval_reason", "framework_state"} & resumed.keys()


async def test_hosted_commands_execute_off_event_loop(hosted):
    service = CheckoutRecoveryService(InMemoryCaseRepository())
    real_start = service.start_case
    loop_thread = threading.get_ident()

    def start(*args):
        assert threading.get_ident() != loop_thread
        return real_start(*args)

    service.start_case = Mock(side_effect=start)
    hosted._checkout_service = AsyncMock(return_value=service)
    await hosted._execute({"action": "start", "fixture_id": "recoverable-inventory-reservation"})
    service.start_case.assert_called_once()


@pytest.mark.parametrize(
    "text",
    [
        "PRIVATE-CONTENT-CANARY",
        "[]",
        '{"action":"start","fixture_id":"PRIVATE-CONTENT-CANARY"}',
        '{"action":"approve","reason":"PRIVATE-CONTENT-CANARY"}',
        '{"action":"start","fixture_id":"denied-approval","extra":"PRIVATE-CONTENT-CANARY"}',
        '{"action":"resume","case_id":"PRIVATE-CONTENT-CANARY"}',
    ],
)
async def test_hosted_rejections_never_return_or_log_input(hosted, caplog, text):
    hosted._checkout_service = AsyncMock(
        return_value=CheckoutRecoveryService(InMemoryCaseRepository())
    )
    with caplog.at_level(logging.WARNING):
        response = await hosted.response_handler({"input": text})
    assert json.loads(response) == {"error": "checkout command was rejected"}
    assert "PRIVATE-CONTENT-CANARY" not in caplog.text


async def test_hosted_persistence_failure_has_sanitized_traceback_and_logs(hosted, caplog):
    service = Mock()
    service.start_case.side_effect = OperationalError("PRIVATE-CREDENTIAL-CANARY")
    hosted._checkout_service = AsyncMock(return_value=service)
    with caplog.at_level(logging.ERROR):
        try:
            await hosted.response_handler(
                {"input": '{"action":"start","fixture_id":"recoverable-inventory-reservation"}'}
            )
        except RuntimeError as error:
            assert str(error) == "checkout persistence command failed"
            assert "PRIVATE-CREDENTIAL-CANARY" not in traceback.format_exc()
        else:
            pytest.fail("database failure cannot become a successful response")
    assert "PRIVATE-CREDENTIAL-CANARY" not in caplog.text
