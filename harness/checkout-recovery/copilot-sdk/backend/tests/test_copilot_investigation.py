import asyncio
import json
import shutil
import sys
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest
from checkout_recovery_copilot.application.ports import InvestigationIncompleteError
from checkout_recovery_copilot.sdk import archive, investigation
from checkout_recovery_copilot.sdk.tools import Evidence
from copilot import ToolInvocation
from model_to_harness_shared import CheckoutSimulator, get_checkout_fixture
from model_to_harness_shared.simulators.checkout import CheckoutDiagnosticReadError


def simulator(fixture_id="recoverable-inventory-reservation"):
    fixture = get_checkout_fixture(fixture_id)
    return CheckoutSimulator(
        order=fixture.order,
        payment_attempt=fixture.payment_attempt,
        reservation=fixture.reservation,
        diagnostic_read_failures=fixture.behavior.diagnostic_read_failures,
    )


def event(kind, **fields):
    return SimpleNamespace(type=kind, data=SimpleNamespace(**fields))


@pytest.fixture
def environment(monkeypatch):
    monkeypatch.delenv("COPILOT_CLI_PATH", raising=False)
    root = Path(".azure/copilot-lifecycle-tests") / uuid4().hex
    root.mkdir(parents=True)
    calls = []
    settings = {
        "omit": None,
        "plain_error": False,
        "hang": False,
        "stop_error": False,
        "delegate": False,
        "logs": False,
        "force_error": False,
        "credential_close_error": False,
        "bridge_close_error": False,
        "bridge_export_failed": False,
        "runtime_version": archive.RUNTIME_VERSION,
        "protocol_version": 3,
    }
    clients = []
    callbacks = []
    sending = asyncio.Event()
    thread_sending = threading.Event()

    class Credential:
        async def __aenter__(self):
            calls.append("credential.enter")
            return self

        async def get_token(self, scope):
            assert scope == "https://ai.azure.com/.default"
            calls.append("token")
            return SimpleNamespace(token="PRIVATE-REFRESHING-TOKEN")

        async def __aexit__(self, *_):
            calls.append("credential.close")
            if settings["credential_close_error"]:
                raise Exception("PRIVATE-CREDENTIAL-CLEANUP")

    class Bridge:
        endpoint = "http://127.0.0.1:1"

        def __init__(self, model, connection_string=None, trace_file=None):
            assert model == "deployment"
            calls.append(("bridge.connection_string", connection_string))
            calls.append(("bridge.trace_file", trace_file))
            self.export_failed = False

        async def __aenter__(self):
            calls.append("bridge.enter")
            return self

        async def __aexit__(self, *_):
            calls.append("bridge.close")
            self.export_failed = settings["bridge_export_failed"]
            if settings["bridge_close_error"]:
                raise Exception("PRIVATE-BRIDGE-CLEANUP")

    class Session:
        def __init__(self, client, identifier, options):
            self.client = client
            self.session_id = identifier
            self.options = options
            self.events = []

        def emit(self, kind, **fields):
            item = event(kind, **fields)
            self.events.append(item)
            self.options["on_event"](item)

        async def invoke(self, name, arguments=None):
            args = arguments or {}
            decision = await self.options["hooks"]["on_pre_tool_use"](
                {"toolName": name, "toolArgs": args}, {}
            )
            assert decision["permissionDecision"] == "allow"
            identifier = str(uuid4())
            self.emit("tool.execution_start", tool_call_id=identifier, tool_name=name)
            if name == "skill":
                self.emit("skill.invoked", name="checkout-triage")
                success = True
            else:
                tool = next(item for item in self.options["tools"] if item.name == name)
                result = await tool.handler(
                    ToolInvocation(
                        session_id=self.session_id,
                        tool_call_id=identifier,
                        tool_name=name,
                        arguments=args,
                    )
                )
                success = result.result_type != "failure"
            self.emit("tool.execution_complete", tool_call_id=identifier, success=success)
            await asyncio.sleep(0)

        async def send_and_wait(self, prompt, **_options):
            calls.append("send")
            sending.set()
            thread_sending.set()
            if settings["plain_error"]:
                raise Exception("PRIVATE-TOKEN-AND-PROMPT")
            if settings["hang"]:
                await asyncio.Event().wait()
            token = self.options["provider"]["bearer_token_provider"]
            callbacks.append(token)
            await token(None)
            await token(None)
            self.emit("assistant.turn_start")
            child = self.options["available_tools"] == ["custom:read_inventory"]
            if child:
                await self.invoke("read_inventory")
            else:
                names = [
                    "skill",
                    "read_order",
                    "read_payment",
                    "delegate_inventory" if settings["delegate"] else "read_inventory",
                    *(["read_logs"] if settings["logs"] else []),
                    "write_plan",
                    "read_plan",
                ]
                for name in names:
                    if name == settings["omit"]:
                        continue
                    args = (
                        {"skill": "checkout-triage"}
                        if name == "skill"
                        else {"content": "Inspect and verify evidence."}
                        if name == "write_plan"
                        else {}
                    )
                    await self.invoke(name, args)
            self.emit("assistant.usage")
            return SimpleNamespace(data=SimpleNamespace(content="Private recommendation"))

        async def disconnect(self):
            calls.append("disconnect")
            native = Path(self.client.options["base_directory"]) / "session-state" / self.session_id
            native.mkdir(parents=True, exist_ok=True)
            (native / "events.jsonl").write_text('{"type":"user.message","native":"unchanged"}\n')
            (native / "workspace.yaml").write_text("native: workspace\n")

        async def abort(self):
            calls.append("abort")

        async def get_events(self):
            return [event("user.message")]

    class Client:
        def __init__(self, **options):
            self.options = options
            self.sessions = []
            clients.append(self)

        async def start(self):
            calls.append("start")

        async def get_status(self):
            return SimpleNamespace(
                version=settings["runtime_version"], protocol_version=settings["protocol_version"]
            )

        async def create_session(self, session_id, **options):
            session = Session(self, session_id, options)
            self.sessions.append(session)
            return session

        async def resume_session(self, identifier, **options):
            calls.append("resume")
            assert options.pop("continue_pending_work") is False
            assert (Path(options["working_directory"]) / "plan.md").stat().st_mode & 0o777 == 0o600
            assert (
                Path(self.options["base_directory"]) / "session-state" / identifier / "events.jsonl"
            ).is_file()
            return await self.create_session(identifier, **options)

        async def stop(self):
            calls.append("stop")
            if settings["stop_error"]:
                raise Exception("PRIVATE-SHUTDOWN-PAYLOAD")

        async def force_stop(self):
            calls.append("force_stop")
            if settings["force_error"]:
                raise Exception("PRIVATE-FORCE-CLEANUP")

    bridge_module = ModuleType("checkout_recovery_copilot.infrastructure.copilot_telemetry")
    bridge_module.CopilotTraceBridge = Bridge
    monkeypatch.setitem(sys.modules, bridge_module.__name__, bridge_module)
    monkeypatch.setattr(investigation, "CopilotClient", Client)
    monkeypatch.setattr(investigation, "DefaultAzureCredential", Credential)
    monkeypatch.setattr(investigation, "ManagedIdentityCredential", Credential)
    monkeypatch.setattr(investigation, "get_cached_cli_path", lambda _: "/pinned/runtime")
    try:
        yield SimpleNamespace(
            root=root,
            calls=calls,
            settings=settings,
            clients=clients,
            callbacks=callbacks,
            sending=sending,
            thread_sending=thread_sending,
            investigator=investigation.CopilotInvestigator(
                "https://fixture.services.ai.azure.com/api/projects/test",
                "deployment",
                state_directory=root,
            ),
        )
    finally:
        shutil.rmtree(root)


def test_full_native_contract_fake_lifecycle_and_refresh(environment):
    result = environment.investigator.investigate(simulator())
    assert result.mode == "copilot"
    assert result.framework_state["evidence"]["native_skill_completed"]
    assert result.framework_state["evidence"]["workspace_read"]
    assert result.framework_state["evidence"]["tool_calls"] == 6
    assert environment.calls.count("token") == 2
    assert environment.calls.index("stop") < environment.calls.index("credential.close")
    assert environment.calls.index("credential.close") < environment.calls.index("bridge.close")
    client = environment.clients[0]
    assert client.options["mode"] == "empty"
    assert client.options["use_logged_in_user"] is False
    assert client.options["telemetry"]["capture_content"] is False
    assert "GITHUB_TOKEN" not in client.options["env"]
    assert "AZURE_CLIENT_SECRET" not in client.options["env"]
    options = client.sessions[0].options
    assert options["provider"]["model_id"] == "checkout-recovery-readonly"
    assert options["provider"]["wire_model"] == "deployment"
    assert options["provider"]["max_prompt_tokens"] == 16000
    assert options["model_capabilities"].supports.reasoning_effort is False
    assert options["reasoning_summary"] == "none"
    assert "builtin:skill" in options["available_tools"]
    assert all(
        name.startswith("custom:") or name == "builtin:skill" for name in options["available_tools"]
    )
    assert options["enable_session_store"] and options["infinite_sessions"]["enabled"]
    assert not options["enable_file_hooks"] and not options["enable_host_git_operations"]
    assert not options["enable_config_discovery"]
    assert options["on_permission_request"](None).kind == "reject"
    assert not list(environment.root.iterdir())
    with pytest.raises(InvestigationIncompleteError):
        asyncio.run(environment.callbacks[0](None))


def test_fresh_client_restore_uses_native_resume(environment):
    first = environment.investigator.investigate(simulator())
    second = environment.investigator.resume_native(simulator(), first.framework_state)
    assert first.framework_state["session_id"] == second.framework_state["session_id"]
    assert second.framework_state["evidence"]["restored_event_count"] == 1
    assert "resume" in environment.calls
    assert (
        environment.clients[0].options["base_directory"]
        != (environment.clients[1].options["base_directory"])
    )


@pytest.mark.parametrize(
    "missing", ["skill", "read_order", "read_payment", "read_inventory", "read_plan"]
)
def test_incomplete_observed_behavior_fails_closed(environment, missing):
    environment.settings["omit"] = missing
    with pytest.raises(InvestigationIncompleteError):
        environment.investigator.investigate(simulator())
    assert "abort" in environment.calls and "stop" in environment.calls
    assert not list(environment.root.iterdir())


def test_optional_connection_string_is_forwarded_to_owned_bridge(environment):
    environment.investigator.connection_string = "synthetic-connection-setting"
    environment.investigator.trace_file = environment.root / "native.jsonl"
    environment.investigator.investigate(simulator())
    assert ("bridge.connection_string", "synthetic-connection-setting") in environment.calls
    assert ("bridge.trace_file", environment.root / "native.jsonl") in environment.calls


def test_explicit_packaged_runtime_path_and_invalid_path_fail_closed(environment, monkeypatch):
    binary = environment.root.resolve() / "packaged-runtime"
    binary.write_text("synthetic packaged runtime")
    monkeypatch.setenv("COPILOT_CLI_PATH", str(binary))
    assert investigation.cached_runtime_path() == str(binary)
    monkeypatch.setenv("COPILOT_CLI_PATH", str(binary) + "-missing")
    assert investigation.cached_runtime_path() is None
    monkeypatch.setenv("COPILOT_CLI_PATH", "relative-runtime")
    assert investigation.cached_runtime_path() is None


def test_native_runtime_resolution_uses_independent_exact_version(environment, monkeypatch):
    requested = []
    monkeypatch.setattr(
        investigation,
        "get_cached_cli_path",
        lambda selected: requested.append(selected) or "/pinned/native-runtime",
    )
    assert investigation.cached_runtime_path() == "/pinned/native-runtime"
    assert requested == ["1.0.85"]


@pytest.mark.parametrize(
    "setting,value",
    [
        ("runtime_version", "1.0.83"),
        ("protocol_version", 2),
    ],
)
def test_unselected_runtime_or_protocol_fails_before_session_creation(environment, setting, value):
    environment.settings[setting] = value
    with pytest.raises(InvestigationIncompleteError, match="unsupported native runtime version"):
        environment.investigator.investigate(simulator())
    assert environment.clients[0].sessions == []
    assert "stop" in environment.calls
    assert not list(environment.root.iterdir())


def test_bounded_child_is_actually_executed(environment):
    environment.settings["delegate"] = True
    result = environment.investigator.investigate(simulator())
    assert result.framework_state["evidence"]["delegation_mode"] == "bounded_child_session"
    assert result.framework_state["evidence"]["child_completed"] is True
    assert len(result.framework_state["sessions"]) == 2
    assert result.selected_tools.count("read_inventory") == 1
    assert environment.clients[0].sessions[1].options["available_tools"] == [
        "custom:read_inventory"
    ]


def test_plain_sdk_failure_is_normalized_without_payload(environment, caplog):
    environment.settings["plain_error"] = True
    with pytest.raises(
        InvestigationIncompleteError, match="Copilot investigation failed"
    ) as raised:
        environment.investigator.investigate(simulator())
    assert raised.value.__cause__ is None
    assert "PRIVATE" not in caplog.text
    assert "abort" in environment.calls and "stop" in environment.calls


def test_timeout_aborts_and_forces_shutdown(environment):
    environment.settings.update(hang=True, stop_error=True)
    environment.investigator.timeout = 0.01
    with pytest.raises(InvestigationIncompleteError):
        environment.investigator.investigate(simulator())
    assert "abort" in environment.calls and "force_stop" in environment.calls
    assert environment.calls[-1] == "bridge.close"
    assert not list(environment.root.iterdir())


def test_no_success_archive_after_forced_shutdown(environment):
    environment.settings["stop_error"] = True
    with pytest.raises(InvestigationIncompleteError, match="no archive was produced"):
        environment.investigator.investigate(simulator())
    assert "force_stop" in environment.calls
    assert not list(environment.root.iterdir())


def test_diagnostic_simulator_failure_is_preserved(environment):
    environment.settings["logs"] = True
    with pytest.raises(CheckoutDiagnosticReadError):
        environment.investigator.investigate(simulator("diagnostic-read-failure"))
    assert "abort" in environment.calls and "stop" in environment.calls


def test_hook_boundaries_and_turn_budget():
    async def check():
        evidence = Evidence()
        for _ in range(24):
            assert (await evidence.pre_tool({"toolName": "read_order"}, {}))[
                "permissionDecision"
            ] == "allow"
        assert (await evidence.pre_tool({"toolName": "read_order"}, {}))[
            "permissionDecision"
        ] == "deny"
        for name, args in [("bash", {}), ("skill", {"skill": "other"}), ("refund", {})]:
            fresh = Evidence()
            assert (await fresh.pre_tool({"toolName": name, "toolArgs": args}, {}))[
                "permissionDecision"
            ] == "deny"
        fresh = Evidence()
        for _ in range(13):
            fresh.event(event("assistant.turn_start"))
        assert not fresh.active and fresh.failed.is_set()

    asyncio.run(check())


def test_scripted_is_explicit_and_has_no_native_state():
    result = investigation.ScriptedInvestigator().investigate(simulator())
    assert result.mode == "scripted"
    assert result.framework_state == {}
    assert json.loads(result.model_dump_json())["selected_tools"] == [
        "read_order",
        "read_payment",
        "read_inventory",
    ]


def test_cancellation_closes_owned_scope_and_callbacks(environment):
    environment.settings["hang"] = True

    async def check():
        task = asyncio.create_task(environment.investigator._invoke(simulator()))
        await environment.sending.wait()
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert "abort" in environment.calls and "stop" in environment.calls
        assert environment.calls[-1] == "bridge.close"
        assert not list(environment.root.iterdir())

    asyncio.run(check())


def test_fixture_flag_reaches_parent_and_child_handlers(environment, monkeypatch):
    from checkout_recovery_copilot.sdk import tools

    captured = []
    monkeypatch.setattr(
        tools,
        "record_fixture_diagnostic",
        lambda _span, name, _result: captured.append(name),
    )
    environment.settings["delegate"] = True
    environment.investigator.fixture_content = True
    environment.investigator.investigate(simulator())
    assert captured == ["read_order", "read_payment", "read_inventory"]
    assert environment.clients[0].options["telemetry"]["capture_content"] is False


def test_sdk_logging_removes_payload_and_traceback(caplog):
    import logging

    investigation.safe_sdk_logging()
    logger = logging.getLogger("copilot._jsonrpc")
    try:
        raise Exception("PRIVATE-PROTOCOL-PAYLOAD")
    except Exception:
        logger.exception("SDK returned %s", "PRIVATE-PROMPT")
    assert "Copilot SDK diagnostic" in caplog.text
    assert "PRIVATE" not in caplog.text
    assert "Traceback" not in caplog.text


def test_child_hook_rejects_parent_capabilities(environment):
    async def check():
        for name in ("read_order", "read_payment", "delegate_inventory", "write_plan", "skill"):
            evidence = Evidence()
            options = investigation.session_options(environment.root, {}, [], evidence, child=True)
            decision = await options["hooks"]["on_pre_tool_use"](
                {"toolName": name, "toolArgs": {"skill": "checkout-triage"}}, {}
            )
            assert decision["permissionDecision"] == "deny"
            assert not evidence.active
        evidence = Evidence()
        options = investigation.session_options(environment.root, {}, [], evidence, child=True)
        decision = await options["hooks"]["on_pre_tool_use"](
            {"toolName": "read_inventory", "toolArgs": {}}, {}
        )
        assert decision["permissionDecision"] == "allow"

    asyncio.run(check())


def test_new_model_turns_and_retries_have_distinct_aggregate_budget():
    evidence = Evidence()
    for _ in range(2):
        evidence.event(event("assistant.turn_start"))
    for _ in range(10):
        evidence.event(event("assistant.turn_retry"))
    assert evidence.model_turns == 2
    assert evidence.model_retries == 10
    assert evidence.active
    evidence.event(event("assistant.turn_retry"))
    assert evidence.model_turns == 2
    assert evidence.model_retries == 11
    assert not evidence.active
    assert str(evidence.failure) == "observed model attempt budget exceeded"


def test_native_transport_environment_is_allowlisted_without_ambient_credentials(
    environment, monkeypatch
):
    expected = {
        "HTTPS_PROXY": "https://proxy.example:443",
        "HTTP_PROXY": "http://proxy.example:8080",
        "NO_PROXY": "127.0.0.1,localhost,::1,.example",
        "SSL_CERT_FILE": "/safe/ca.pem",
        "SSL_CERT_DIR": "/safe/certs",
        "REQUESTS_CA_BUNDLE": "/safe/requests.pem",
        "NODE_EXTRA_CA_CERTS": "/safe/node.pem",
    }
    for name, value in expected.items():
        monkeypatch.setenv(name, value)
    for name in ("GITHUB_TOKEN", "AZURE_CLIENT_SECRET", "OPENAI_API_KEY", "NODE_OPTIONS"):
        monkeypatch.setenv(name, "DO-NOT-PASS")
    environment.investigator.investigate(simulator())
    native_environment = environment.clients[0].options["env"]
    assert all(native_environment[name] == value for name, value in expected.items())
    assert all(
        name not in native_environment
        for name in ("GITHUB_TOKEN", "AZURE_CLIENT_SECRET", "OPENAI_API_KEY", "NODE_OPTIONS")
    )


@pytest.mark.parametrize(
    "name,value",
    [
        ("HTTPS_PROXY", "https://user:PRIVATE@proxy.example"),
        ("HTTP_PROXY", "file:///PRIVATE"),
        ("NO_PROXY", "PRIVATE\nhost"),
        ("SSL_CERT_FILE", "relative-PRIVATE.pem"),
    ],
)
def test_invalid_transport_settings_fail_without_disclosing_values(monkeypatch, name, value):
    monkeypatch.setenv(name, value)
    with pytest.raises(InvestigationIncompleteError) as raised:
        investigation.transport_environment()
    assert "PRIVATE" not in str(raised.value)


def test_bridge_export_failure_is_visible_after_drain_without_failing_investigation(environment):
    environment.settings["bridge_export_failed"] = True
    result = environment.investigator.investigate(simulator())
    assert result.mode == "copilot"
    assert result.framework_state["evidence"]["telemetry_export_failed"] is True
    assert environment.calls.index("stop") < environment.calls.index("bridge.close")
    assert result.framework_state["sessions"]


def test_primary_diagnostic_error_survives_all_async_cleanup_failures(environment, caplog):
    environment.settings.update(
        logs=True,
        stop_error=True,
        force_error=True,
        credential_close_error=True,
        bridge_close_error=True,
    )
    with pytest.raises(CheckoutDiagnosticReadError):
        environment.investigator.investigate(simulator("diagnostic-read-failure"))
    phases = {getattr(record, "cleanup_phase", None) for record in caplog.records}
    assert {"runtime_stop", "runtime_shutdown", "credential", "telemetry"}.issubset(phases)
    assert all(
        getattr(record, "failure_kind", None) == "Exception"
        for record in caplog.records
        if getattr(record, "cleanup_phase", None)
    )
    assert "PRIVATE" not in caplog.text
    assert not list(environment.root.iterdir())


def test_primary_diagnostic_error_survives_workspace_cleanup_failure(
    environment, monkeypatch, caplog
):
    environment.settings["logs"] = True

    def fail_cleanup(_directory):
        raise OSError("PRIVATE-WORKSPACE-CLEANUP")

    with monkeypatch.context() as scoped:
        scoped.setattr(investigation.shutil, "rmtree", fail_cleanup)
        with pytest.raises(CheckoutDiagnosticReadError):
            environment.investigator.investigate(simulator("diagnostic-read-failure"))
    assert any(getattr(record, "cleanup_phase", None) == "workspace" for record in caplog.records)
    assert "PRIVATE" not in caplog.text


def test_archive_failure_remains_mandatory_completion_failure(environment, monkeypatch, caplog):
    def fail_snapshot(*_args):
        raise InvestigationIncompleteError("native session archive validation failed")

    monkeypatch.setattr(archive, "snapshot", fail_snapshot)
    with pytest.raises(InvestigationIncompleteError, match="archive validation failed"):
        environment.investigator.investigate(simulator())
    assert "stop" in environment.calls
    assert not list(environment.root.iterdir())
    assert any(
        getattr(record, "failure_kind", None) == "native_archive_rejected"
        and getattr(record, "archive_phase", None) == "snapshot"
        for record in caplog.records
    )


def test_archive_restore_rejection_has_safe_distinct_logging(environment, caplog):
    result = environment.investigator.investigate(simulator())
    state = result.framework_state
    state["sessions"][state["session_id"]]["../PRIVATE-NATIVE-FILENAME"] = "PRIVATE-PAYLOAD"
    with pytest.raises(InvestigationIncompleteError, match="archive validation failed"):
        environment.investigator.resume_native(simulator(), state)
    assert any(
        getattr(record, "failure_kind", None) == "native_archive_rejected"
        and getattr(record, "archive_phase", None) == "restore"
        for record in caplog.records
    )
    assert "PRIVATE" not in caplog.text
    assert state["session_id"] not in caplog.text
    assert len(environment.clients) == 1


def test_explicit_thread_signal_stops_native_worker_not_just_to_thread_waiter(environment):
    from checkout_recovery_copilot.sdk.cancellation import cancellation_scope, current_signal

    environment.settings["hang"] = True
    signal = threading.Event()

    async def check():
        with cancellation_scope(signal):
            worker = asyncio.create_task(
                asyncio.to_thread(environment.investigator.investigate, simulator())
            )
        assert current_signal() is None
        assert await asyncio.to_thread(environment.thread_sending.wait, 2)
        signal.set()
        with pytest.raises(InvestigationIncompleteError, match="Copilot investigation cancelled"):
            await asyncio.wait_for(worker, timeout=3)
        assert "abort" in environment.calls and "stop" in environment.calls
        assert environment.calls[-1] == "bridge.close"
        assert not list(environment.root.iterdir())

    asyncio.run(check())


def test_pre_cancelled_scope_never_starts_native_process(environment, caplog):
    from checkout_recovery_copilot.sdk.cancellation import cancellation_scope

    signal = threading.Event()
    signal.set()
    with (
        cancellation_scope(signal),
        pytest.raises(InvestigationIncompleteError, match="Copilot investigation cancelled"),
    ):
        environment.investigator.investigate(simulator())
    assert not environment.clients
    assert not list(environment.root.iterdir())
    assert any(
        getattr(record, "failure_kind", None) == "investigation_cancelled"
        and record.getMessage() == "Copilot investigation cancelled"
        for record in caplog.records
    )


def test_lowercase_proxy_settings_are_normalized_and_loopback_is_bypassed(monkeypatch):
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("http_proxy", "http://lower.example:8080")
    monkeypatch.setenv("https_proxy", "https://lower.example:443")
    monkeypatch.setenv("no_proxy", ".lower.example")
    result = investigation.transport_environment()
    assert result["HTTP_PROXY"] == result["http_proxy"] == "http://lower.example:8080"
    assert result["HTTPS_PROXY"] == result["https_proxy"] == "https://lower.example:443"
    assert result["NO_PROXY"] == result["no_proxy"]
    assert {".lower.example", "127.0.0.1", "localhost", "::1"}.issubset(
        result["no_proxy"].split(",")
    )


def test_uppercase_proxy_settings_take_precedence_including_explicit_empty(monkeypatch):
    monkeypatch.setenv("HTTP_PROXY", "http://upper.example:8080")
    monkeypatch.setenv("http_proxy", "http://lower.example:8080")
    monkeypatch.setenv("HTTPS_PROXY", "")
    monkeypatch.setenv("https_proxy", "https://lower.example:443")
    monkeypatch.setenv("NO_PROXY", ".upper.example")
    monkeypatch.setenv("no_proxy", ".lower.example")
    result = investigation.transport_environment()
    assert result["HTTP_PROXY"] == result["http_proxy"] == "http://upper.example:8080"
    assert "HTTPS_PROXY" not in result and "https_proxy" not in result
    assert result["NO_PROXY"] == result["no_proxy"]
    assert ".upper.example" in result["no_proxy"].split(",")
    assert ".lower.example" not in result["no_proxy"].split(",")


@pytest.mark.parametrize("name", ["http_proxy", "https_proxy"])
def test_lowercase_proxy_credentials_are_rejected_without_logging_values(monkeypatch, name):
    monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.setenv(name, "http://PRIVATE:SECRET@proxy.example")
    with pytest.raises(InvestigationIncompleteError, match="invalid native proxy configuration"):
        investigation.transport_environment()


def test_explicit_cancellation_uses_existing_durable_failed_start_path(environment):
    from checkout_recovery_copilot.application.service import CheckoutRecoveryService
    from checkout_recovery_copilot.infrastructure.memory import InMemoryCaseRepository
    from checkout_recovery_copilot.sdk.cancellation import cancellation_scope
    from model_to_harness_shared import CheckoutFailureCode

    environment.settings["hang"] = True
    repository = InMemoryCaseRepository()
    service = CheckoutRecoveryService(repository, investigator=environment.investigator)
    signal = threading.Event()

    async def check():
        with cancellation_scope(signal):
            worker = asyncio.create_task(
                asyncio.to_thread(service.start_case, "recoverable-inventory-reservation")
            )
        assert await asyncio.to_thread(environment.thread_sending.wait, 2)
        signal.set()
        case = await asyncio.wait_for(worker, timeout=3)
        assert case.failure_code == CheckoutFailureCode.HARNESS_FAILED
        assert case.terminal_status is not None
        assert repository.get(case.case_id) == case
        assert "abort" in environment.calls and "stop" in environment.calls
        assert not list(environment.root.iterdir())

    asyncio.run(check())


def test_provider_receipt_labels_modes_and_removes_credentials_paths_and_unknown_names():
    foundry = investigation.safe_provider_metadata(
        "https://user:password@sample.example/private-project/path", "deployment", scripted=False
    )
    assert foundry == {
        "provider_mode": "foundry_responses_entra",
        "endpoint_host": "sample.example",
        "model_deployment": "deployment",
    }
    scripted = investigation.safe_provider_metadata(
        "http://127.0.0.1:1234/private", "not-a-safe-deployment\nPRIVATE", scripted=True
    )
    assert scripted["provider_mode"] == "local_scripted_responses"
    assert scripted["endpoint_host"] == "127.0.0.1"
    assert scripted["model_deployment"] == "redacted"
