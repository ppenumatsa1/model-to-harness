import asyncio
import importlib.util
import json
import logging
import sys
import threading
import traceback
from hashlib import sha256
from pathlib import Path
from types import ModuleType
from unittest.mock import AsyncMock, Mock

import httpx
import pytest
from checkout_recovery_copilot.application import CheckoutRecoveryService
from checkout_recovery_copilot.application.ports import InvestigationIncompleteError
from checkout_recovery_copilot.infrastructure import InMemoryCaseRepository
from psycopg import OperationalError

ENTRYPOINT = Path(__file__).resolve().parents[2] / "infra/foundry-hosted/agent/main.py"


@pytest.fixture
def hosted(monkeypatch, tmp_path):
    monkeypatch.delenv("CHECKOUT_COPILOT_STATE_DIRECTORY", raising=False)
    sdk = ModuleType("azure.ai.agentserver.responses")
    sdk.ResponsesAgentServerHost = Mock()
    sdk.TextResponse = lambda *args, text: text
    monkeypatch.setitem(sys.modules, sdk.__name__, sdk)
    spec = importlib.util.spec_from_file_location("checkout_hosted_test", ENTRYPOINT)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    module._packaged_runtime = tmp_path / "copilot-runtime"
    monkeypatch.setattr(module.Path, "home", lambda: tmp_path)
    return module


@pytest.mark.parametrize("invalid", [None, "digest", "path", "symlink", "version"])
def test_stages_verified_runtime_from_nonexecutable_source(hosted, tmp_path, invalid):
    binary = hosted._packaged_runtime / "prebuilds/linux-x64/copilot-runtime"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"synthetic pinned executable")
    binary.chmod(0o444)
    name = binary.relative_to(tmp_path).as_posix()
    digest = sha256(binary.read_bytes()).hexdigest()
    if invalid == "symlink":
        original = binary.with_name("original")
        binary.rename(original)
        binary.symlink_to(original)
    metadata = {
        "sdk_version": hosted.SDK_VERSION,
        "version": "wrong" if invalid == "version" else hosted.RUNTIME_VERSION,
        "protocol_version": 3,
        "files": {
            "../escape" if invalid == "path" else name:
                "0" * 64 if invalid == "digest" else digest
        },
    }
    auxiliary = hosted._packaged_runtime / "prebuilds/linux-x64/ripgrep/bin/linux-x64/rg"
    auxiliary.parent.mkdir(parents=True)
    auxiliary.write_bytes(b"synthetic auxiliary")
    auxiliary.chmod(0o444)
    data_file = hosted._packaged_runtime / "prebuilds/linux-x64/data.json"
    data_file.write_bytes(b"{}")
    for path in (auxiliary, data_file):
        metadata["files"][path.relative_to(tmp_path).as_posix()] = sha256(
            path.read_bytes()
        ).hexdigest()
    (tmp_path / "runtime-manifest.json").write_text(json.dumps(metadata))
    if invalid:
        with pytest.raises(ValueError):
            hosted._stage_packaged_runtime()
    else:
        with hosted._stage_packaged_runtime() as stage:
            staged = Path(stage) / name
            assert staged.read_bytes() == binary.read_bytes()
            assert staged.stat().st_mode & 0o777 == 0o700
            assert binary.stat().st_mode & 0o777 == 0o444
            assert (Path(stage) / auxiliary.relative_to(tmp_path)).stat().st_mode & 0o777 == 0o700
            assert (Path(stage) / data_file.relative_to(tmp_path)).stat().st_mode & 0o777 == 0o600
            assert Path(stage).parent == tmp_path / ".checkout-recovery-copilot"


@pytest.mark.parametrize("configured", [None, "/explicit/private/state"])
async def test_hosted_uses_writable_home_for_native_state(
    hosted, monkeypatch, tmp_path, configured
):
    monkeypatch.setattr(hosted.Path, "home", lambda: tmp_path)
    if configured:
        monkeypatch.setenv("CHECKOUT_COPILOT_STATE_DIRECTORY", configured)
    hosted.create_runtime = Mock(return_value=Mock())
    await hosted._checkout_service()
    assert hosted.os.environ["CHECKOUT_COPILOT_STATE_DIRECTORY"] == (
        configured or str(tmp_path / ".checkout-recovery-copilot")
    )
    await hosted._close_runtime()


async def test_hosted_initializes_once_under_concurrent_requests_and_closes_off_loop(
    hosted, monkeypatch
):
    monkeypatch.setenv("CHECKOUT_COPILOT_EXECUTION_MODE", "scripted")
    loop_thread = threading.get_ident()
    threads = []
    runtime = Mock()
    runtime.start.side_effect = lambda: threads.append(threading.get_ident())
    runtime.close.side_effect = lambda: threads.append(threading.get_ident())
    hosted.create_runtime = Mock(return_value=runtime)
    services = await asyncio.gather(*(hosted._checkout_service() for _ in range(4)))
    assert all(service is runtime.service for service in services)
    hosted.create_runtime.assert_called_once()
    assert hosted.create_runtime.call_args.args[0].execution_mode == "copilot"
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
        await asyncio.sleep(0)
        runtime.close.assert_not_called()
        assert not task.done()
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
    service.execute.side_effect = OperationalError("PRIVATE-CREDENTIAL-CANARY")
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


@pytest.mark.parametrize("already_cancelled", [True, False])
@pytest.mark.parametrize("channel", ["request", "shutdown"])
async def test_hosted_cancelled_start_persists_failure_without_side_effects(
    hosted, caplog, already_cancelled, channel
):
    from checkout_recovery_copilot.sdk.cancellation import current_signal

    entered = threading.Event()
    exited = threading.Event()
    calls = []

    class Investigator:
        def investigate(self, simulator):
            calls.append(simulator)
            entered.set()
            signal = current_signal()
            assert signal is not None and signal.wait(5)
            exited.set()
            raise InvestigationIncompleteError("PRIVATE-CANCELLATION-CANARY")

    repository = InMemoryCaseRepository()
    service = CheckoutRecoveryService(repository, investigator=Investigator())
    hosted._checkout_service = AsyncMock(return_value=service)
    signal = asyncio.Event()
    if already_cancelled:
        signal.set()
    command = {
        "action": "start",
        "fixture_id": "recoverable-inventory-reservation",
        "request_id": "00000000-0000-0000-0000-000000000111",
    }
    options = (
        {"cancellation_signal": signal}
        if channel == "request"
        else {"context": Mock(shutdown=signal)}
    )
    task = asyncio.create_task(hosted.response_handler({"input": json.dumps(command)}, **options))
    assert await asyncio.to_thread(entered.wait, 5)
    signal.set()
    response = json.loads(await asyncio.wait_for(task, 5))
    assert exited.is_set()
    assert response["terminal_status"] == "failed"
    assert response["failure_code"] == "harness_failed"
    assert repository.remediation_intent_for(command["request_id"]) is None
    assert repository.framework_state_for(command["request_id"]) in (None, {})
    assert await hosted._execute(command, signal) == response
    assert len(calls) == 1
    events = [event.code.value for event in repository.events_for(command["request_id"])]
    assert events.count("case_started") == events.count("case_closed") == 1
    assert "PRIVATE-CANCELLATION-CANARY" not in json.dumps(response) + caplog.text


async def test_hosted_task_cancellation_waits_for_failed_start_commit(hosted):
    from checkout_recovery_copilot.sdk.cancellation import current_signal

    entered = threading.Event()
    exited = threading.Event()

    class Investigator:
        def investigate(self, simulator):
            entered.set()
            signal = current_signal()
            assert signal is not None and signal.wait(5)
            exited.set()
            raise InvestigationIncompleteError("cancelled")

    repository = InMemoryCaseRepository()
    hosted._checkout_service = AsyncMock(
        return_value=CheckoutRecoveryService(repository, investigator=Investigator())
    )
    identifier = "00000000-0000-0000-0000-000000000112"
    task = asyncio.create_task(
        hosted._execute(
            {
                "action": "start",
                "fixture_id": "recoverable-inventory-reservation",
                "request_id": identifier,
            }
        )
    )
    assert await asyncio.to_thread(entered.wait, 5)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert exited.is_set()
    assert repository.get(identifier).terminal_status.value == "failed"
    assert repository.remediation_intent_for(identifier) is None


@pytest.mark.parametrize("action", ["approval", "resume"])
async def test_hosted_accepted_business_commands_finish_when_await_cancelled(hosted, action):
    from checkout_recovery_copilot.sdk.cancellation import current_signal

    repository = InMemoryCaseRepository()
    service = CheckoutRecoveryService(repository)
    hosted._checkout_service = AsyncMock(return_value=service)
    started = await hosted._execute(
        {"action": "start", "fixture_id": "captured-payment-approved-remediation"}
    )
    approval = {
        "action": "approval",
        "case_id": started["case_id"],
        "approval_request_id": started["approval_request_id"],
        "decision": "approved",
        "reviewer_id": "reviewer",
        "reason": "Reviewed",
    }
    if action == "resume":
        await hosted._execute(approval)
    original = service.execute
    entered = threading.Event()
    release = threading.Event()

    def execute(command):
        assert current_signal() is None
        entered.set()
        assert release.wait(5)
        return original(command)

    service.execute = execute
    command = (
        approval if action == "approval" else {"action": "resume", "case_id": started["case_id"]}
    )
    signal = asyncio.Event()
    signal.set()
    task = asyncio.create_task(hosted._execute(command, signal))
    try:
        assert await asyncio.to_thread(entered.wait, 5)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        task.cancel()
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    result = service.get_case_response(started["case_id"])
    assert result.approval_decision == "approved"
    if action == "resume":
        assert result.terminal_status == "recovered"
    else:
        assert result.phase == "waiting_approval"


@pytest.fixture
def local_hosted(monkeypatch):
    scripts = ENTRYPOINT.parents[3] / "scripts"
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location(
        "checkout_local_hosted", scripts / "verify_local_hosted.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_hosted_uses_actual_responses_route(local_hosted, tmp_path):
    actual = {"case_id": "case", "harness_mode": "copilot", "phase": "waiting_approval"}
    seen = []

    def handle(request):
        seen.append(request)
        assert request.url.path == "/responses"
        payload = json.loads(request.content)
        assert payload["store"] is False
        assert json.loads(payload["input"]) == {
            "action": "start",
            "fixture_id": "fixture",
            "request_id": "request",
        }
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "id": "response",
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": json.dumps(actual)}],
                    }
                ],
            },
        )

    journal = {"commands": []}
    path = tmp_path / "commands.json"
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        transport = local_hosted.ResponsesTransport(client, journal, path)
        assert (
            transport(
                "http://127.0.0.1:18088",
                "POST",
                "/api/cases",
                {"fixture_id": "fixture", "request_id": "request"},
            )
            == actual
        )
    assert len(seen) == 1
    assert journal["commands"][0]["http_status"] == 200
    assert journal["commands"][0]["response_status"] == "completed"
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("http_status", [400, 500])
def test_local_hosted_preserves_failure_status_without_error_payload(
    local_hosted, tmp_path, http_status
):
    journal = {"commands": []}
    path = tmp_path / "commands.json"

    def handle(request):
        return httpx.Response(
            http_status,
            json={
                "status": "failed",
                "error": {"code": "server_error", "message": "PRIVATE-CREDENTIAL-CANARY"},
            },
        )

    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        transport = local_hosted.ResponsesTransport(client, journal, path)
        with pytest.raises(local_hosted.LocalHostedError):
            transport("http://127.0.0.1:18088", "POST", "/api/cases/case/resume")
    record = journal["commands"][0]
    assert record["http_status"] == http_status
    assert record["response_status"] == "failed"
    assert record["response_error"] == {"code": "server_error"}
    assert record["status"] == "failed"
    assert "PRIVATE-CREDENTIAL-CANARY" not in path.read_text()


def test_local_hosted_commands_never_infer_approval(local_hosted):
    assert local_hosted.command_for("POST", "/api/cases/case/resume", None) == {
        "action": "resume",
        "case_id": "case",
    }
    assert local_hosted.command_for("POST", "/api/cases/case/approval", {"decision": "denied"}) == {
        "action": "approval",
        "case_id": "case",
        "decision": "denied",
    }
    with pytest.raises(local_hosted.LocalHostedError):
        local_hosted.command_for("GET", "/api/cases/case/resume", None)


def test_local_hosted_environment_is_local_and_capture_off(local_hosted, tmp_path, monkeypatch):
    monkeypatch.setattr(local_hosted, "LANE_ROOT", tmp_path)
    (tmp_path / ".env").write_text(
        "CHECKOUT_COPILOT_DATABASE_URL=postgresql://local@127.0.0.1:45432/checkout\n"
        "CHECKOUT_COPILOT_FOUNDRY_PROJECT_ENDPOINT=https://example.test/api/projects/project\n"
        "CHECKOUT_COPILOT_FOUNDRY_MODEL_DEPLOYMENT=gpt-4.1-mini\n"
        "FOUNDRY_AGENT_NAME=do-not-copy\nPRIVATE_SECRET=do-not-copy\n"
    )
    monkeypatch.setenv("FOUNDRY_AGENT_NAME", "do-not-inherit")
    monkeypatch.setenv("PRIVATE_SECRET", "do-not-inherit")
    environment = local_hosted.child_environment(tmp_path)
    assert "FOUNDRY_AGENT_NAME" not in environment
    assert "PRIVATE_SECRET" not in environment
    assert environment["AZURE_TOKEN_CREDENTIALS"] == "AzureCliCredential"
    assert environment["ENABLE_SENSITIVE_DATA"] == "false"
    assert environment["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] == "false"
