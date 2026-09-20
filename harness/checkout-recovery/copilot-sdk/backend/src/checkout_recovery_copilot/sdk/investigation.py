"""One fully owned native Copilot lifecycle per synchronous investigation."""

import asyncio
import logging
import os
import re
import shutil
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path
from typing import Any, NoReturn
from urllib.parse import urlsplit
from uuid import uuid4

from azure.core.exceptions import AzureError
from azure.identity.aio import DefaultAzureCredential, ManagedIdentityCredential
from copilot import CopilotClient, ModelCapabilitiesOverride, RuntimeConnection
from copilot._cli_download import get_cache_dir, get_cached_cli_path
from copilot._cli_version import get_runtime_platform
from copilot._jsonrpc import JsonRpcError
from copilot.generated.rpc import PermissionDecisionReject
from copilot.session import ModelSupportsOverride
from model_to_harness_shared import CheckoutSimulator
from model_to_harness_shared.simulators.checkout import CheckoutDiagnosticReadError

from checkout_recovery_copilot.application.models import InvestigationResult
from checkout_recovery_copilot.application.ports import InvestigationIncompleteError
from checkout_recovery_copilot.infrastructure.telemetry import operation

from . import archive
from .cancellation import current_signal, disarm_cancellation_watch, watch_cancellation
from .tools import CUSTOM_TOOLS, MAX_PLAN_BYTES, Evidence, build_tools

logger = logging.getLogger(__name__)
INSTRUCTIONS = (
    "Investigate one synthetic failed checkout. First invoke the native "
    "checkout-triage skill using the skill tool. Read order, payment and inventory "
    "using the supplied tools, in whichever order the evidence warrants. "
    "Optionally use read_logs or delegate_inventory once instead of directly reading "
    "inventory. Write a short diagnostic plan using write_plan, then read_plan. "
    "Finish with a short recommendation. You have no business-write tools. Never "
    "approve, refund, remediate, or claim recovery. Application policy and verification "
    "decide the outcome. No shell, web, unrestricted files or additional agents."
)
PROMPT = "Checkout failed. Investigate this case safely using the checkout-triage skill."
TRANSPORT_ENVIRONMENT = (
    "HTTPS_PROXY",
    "HTTP_PROXY",
    "NO_PROXY",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "NODE_EXTRA_CA_CERTS",
)


def safe_provider_metadata(endpoint: str, deployment: str, *, scripted: bool) -> dict[str, str]:
    host = urlsplit(endpoint).hostname or ""
    return {
        "provider_mode": "local_scripted_responses" if scripted else "foundry_responses_entra",
        "endpoint_host": host
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.:-]{0,252}", host)
        else "redacted",
        "model_deployment": deployment
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", deployment)
        else "redacted",
    }


def transport_environment() -> dict[str, str]:
    result = {}
    for name in TRANSPORT_ENVIRONMENT:
        value = os.getenv(name)
        if name in {"HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"} and name not in os.environ:
            value = os.getenv(name.lower())
        if not value:
            continue
        if len(value) > 4096 or any(ord(character) < 32 for character in value):
            raise InvestigationIncompleteError("invalid native transport configuration")
        if name in {"HTTP_PROXY", "HTTPS_PROXY"}:
            try:
                proxy = urlsplit(value)
                _ = proxy.port
            except ValueError:
                raise InvestigationIncompleteError("invalid native proxy configuration") from None
            if (
                proxy.scheme not in {"http", "https"}
                or not proxy.hostname
                or proxy.username
                or proxy.password
                or proxy.query
                or proxy.fragment
            ):
                raise InvestigationIncompleteError("invalid native proxy configuration")
        elif name != "NO_PROXY" and not Path(value).is_absolute():
            raise InvestigationIncompleteError("native certificate paths must be absolute")
        result[name] = value
    bypass = [item.strip() for item in result.get("NO_PROXY", "").split(",") if item.strip()]
    for host in ("127.0.0.1", "localhost", "::1"):
        if host not in bypass:
            bypass.append(host)
    result["NO_PROXY"] = ",".join(bypass)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY"):
        if name in result:
            result[name.lower()] = result[name]
    return result


def _cleanup_failure(phase: str, error: BaseException) -> None:
    logger.error(
        "Copilot owned cleanup failed",
        extra={"cleanup_phase": phase, "failure_kind": type(error).__name__},
    )


@asynccontextmanager
async def _owned_context(resource: Any, phase: str) -> AsyncIterator[Any]:
    entered = await resource.__aenter__()
    try:
        yield entered
    except BaseException as primary:
        try:
            await resource.__aexit__(type(primary), primary, primary.__traceback__)
        except BaseException as cleanup:
            _cleanup_failure(phase, cleanup)
        raise
    else:
        try:
            await resource.__aexit__(None, None, None)
        except BaseException as cleanup:
            _cleanup_failure(phase, cleanup)
            raise


class _SafeSdkLog(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = "Copilot SDK diagnostic"
        record.args = ()
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        return True


def safe_sdk_logging() -> None:
    for name in ("copilot.client", "copilot.session", "copilot._jsonrpc"):
        sdk_logger = logging.getLogger(name)
        if not any(isinstance(item, _SafeSdkLog) for item in sdk_logger.filters):
            sdk_logger.addFilter(_SafeSdkLog())


def cached_runtime_path() -> str | None:
    configured = os.getenv("COPILOT_CLI_PATH")
    if configured:
        path = Path(configured).expanduser()
        return str(path) if path.is_absolute() and path.is_file() else None
    legacy = get_cached_cli_path(archive.RUNTIME_VERSION)
    if legacy:
        return legacy
    # The pinned SDK also caches the hostless wrapper without the legacy alias.
    pair = get_cache_dir(archive.RUNTIME_VERSION) / "prebuilds" / get_runtime_platform()
    required = (
        pair / "copilot-runtime",
        pair / "runtime.node",
        pair / ".hostless-runtime-assets-v2",
    )
    return str(required[0]) if all(path.is_file() for path in required) else None


def session_options(
    workspace: Path, provider: dict, tools: list, evidence: Evidence, *, child: bool = False
) -> dict[str, Any]:
    names = ["read_inventory"] if child else list(CUSTOM_TOOLS)

    async def pre_tool(data: dict, invocation: Any) -> dict[str, str]:
        return await evidence.pre_tool(data, invocation, child=child)

    return {
        "provider": provider,
        "model_capabilities": ModelCapabilitiesOverride(
            supports=ModelSupportsOverride(reasoning_effort=False)
        ),
        "reasoning_summary": "none",
        "tools": tools,
        "available_tools": [f"custom:{name}" for name in names]
        + ([] if child else ["builtin:skill"]),
        "on_permission_request": lambda *_: PermissionDecisionReject(),
        "hooks": {"on_pre_tool_use": pre_tool},
        "on_event": evidence.event,
        "working_directory": str(workspace),
        "system_message": {
            "mode": "replace",
            "content": "Read inventory exactly once; report only status and quantity."
            if child
            else INSTRUCTIONS,
        },
        "enable_config_discovery": False,
        "skip_custom_instructions": True,
        "enable_on_demand_instruction_discovery": False,
        "enable_managed_settings": False,
        "enable_file_hooks": False,
        "enable_host_git_operations": False,
        "enable_file_change_tracking": False,
        "enable_skills": not child,
        "included_builtin_skills": [],
        "skill_directories": [] if child else [str(Path(__file__).parent / "skills")],
        "instruction_directories": [],
        "plugin_directories": [],
        "mcp_servers": {},
        "custom_agents": [],
        "custom_agents_local_only": True,
        "enable_session_store": True,
        "enable_session_telemetry": True,
        "skip_embedding_retrieval": True,
        "coauthor_enabled": False,
        "manage_schedule_enabled": False,
        "request_extensions": False,
        "request_canvas_renderer": False,
        "infinite_sessions": {"enabled": True},
    }


async def guarded_turn(session: Any, prompt: str, evidence: Evidence, deadline: float) -> None:
    sending = asyncio.create_task(session.send_and_wait(prompt, timeout=deadline))
    failed = asyncio.create_task(evidence.failed.wait())
    try:
        done, _ = await asyncio.wait({sending, failed}, return_when=asyncio.FIRST_COMPLETED)
        if failed in done and evidence.failure is not None:
            raise evidence.failure
        result = await sending
        if result is None:
            raise InvestigationIncompleteError("native session did not complete")
        if evidence.failure is not None:
            raise evidence.failure
    finally:
        for task in (sending, failed):
            if not task.done():
                task.cancel()
        await asyncio.gather(sending, failed, return_exceptions=True)


async def shutdown(client: Any, sessions: list[Any], evidence: Evidence, *, abort: bool) -> bool:
    evidence.active = False
    process = getattr(client, "_cli_process", None)
    graceful = True
    try:
        async with asyncio.timeout(8):
            if abort:
                for session in reversed(sessions):
                    try:
                        await asyncio.wait_for(session.abort(), timeout=1)
                    except Exception as cleanup:
                        _cleanup_failure("abort", cleanup)
            for session in reversed(sessions):
                await session.disconnect()
            await client.stop()
    except Exception as cleanup:
        graceful = False
        _cleanup_failure("runtime_stop", cleanup)
        await asyncio.wait_for(client.force_stop(), timeout=3)
    finally:
        # force_stop kills but does not reap the pinned SDK's Popen. Hold its
        # handle before shutdown clears it, and never touch unrelated processes.
        if process is not None:
            primary = sys.exception()
            try:
                if process.poll() is None:
                    process.kill()
                await asyncio.to_thread(process.wait, timeout=3)
            except Exception as cleanup:
                _cleanup_failure("process_reap", cleanup)
                if primary is None:
                    raise InvestigationIncompleteError("native runtime failed to stop") from None
    return graceful


class ScriptedInvestigator:
    """Explicit deterministic test mode, never a model-error fallback."""

    def investigate(self, simulator: CheckoutSimulator) -> InvestigationResult:
        return InvestigationResult(
            selected_tools=("read_order", "read_payment", "read_inventory"),
            mode="scripted",
        )


class CopilotInvestigator:
    def __init__(
        self,
        project_endpoint: str,
        model_deployment: str,
        *,
        state_directory: str | Path | None = None,
        timeout_seconds: float = 120,
        fixture_content: bool = False,
        connection_string: str | None = None,
        trace_file: Path | None = None,
    ) -> None:
        parsed = urlsplit(project_endpoint)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("a HTTPS Foundry project endpoint is required")
        if not model_deployment or not 0 < timeout_seconds <= 120:
            raise ValueError("a deployment and a timeout of at most 120 seconds are required")
        self.endpoint = project_endpoint.rstrip("/") + "/openai/v1/"
        self.model = model_deployment
        self.state_directory = Path(
            state_directory or os.getenv("CHECKOUT_COPILOT_STATE_DIRECTORY", ".azure/copilot-sdk")
        ).resolve()
        self.timeout = timeout_seconds
        # Only validated Python diagnostic fields opt in; native capture stays off.
        self.fixture_content = fixture_content
        self.connection_string = connection_string
        self.trace_file = trace_file

    def investigate(self, simulator: CheckoutSimulator) -> InvestigationResult:
        return self._run(simulator)

    def resume_native(
        self, simulator: CheckoutSimulator, framework_state: dict[str, Any]
    ) -> InvestigationResult:
        """Private diagnostic continuity probe; NOT the application's Resume command."""
        return self._run(simulator, framework_state)

    def _run(
        self, simulator: CheckoutSimulator, framework_state: dict[str, Any] | None = None
    ) -> InvestigationResult:
        with operation("harness"):
            try:
                return asyncio.run(self._invoke(simulator, framework_state))
            except asyncio.CancelledError:
                signal = current_signal()
                if signal is not None and signal.is_set():
                    logger.error(
                        "Copilot investigation cancelled",
                        extra={"failure_kind": "investigation_cancelled"},
                    )
                    raise InvestigationIncompleteError("Copilot investigation cancelled") from None
                raise
            except (InvestigationIncompleteError, CheckoutDiagnosticReadError):
                raise
            except (AzureError, JsonRpcError, TimeoutError, OSError, RuntimeError) as error:
                self._failed(error)
            except Exception as error:
                # Pinned SDK dispatch also raises untyped Exception. Do not hide
                # unrelated programming errors under a general fallback.
                if type(error) is not Exception:
                    raise
                self._failed(error)

    @staticmethod
    def _failed(error: Exception) -> NoReturn:
        logger.error("Copilot investigation failed", extra={"failure_kind": type(error).__name__})
        raise InvestigationIncompleteError("Copilot investigation failed") from None

    async def _invoke(
        self, simulator: CheckoutSimulator, state: dict[str, Any] | None = None
    ) -> InvestigationResult:
        async with watch_cancellation():
            result = await self._invoke_owned(simulator, state)
            signal = current_signal()
            if signal is not None and signal.is_set():
                raise asyncio.CancelledError("Copilot investigation cancelled")
            return result

    async def _invoke_owned(
        self, simulator: CheckoutSimulator, state: dict[str, Any] | None = None
    ) -> InvestigationResult:
        from checkout_recovery_copilot.infrastructure.copilot_telemetry import CopilotTraceBridge

        safe_sdk_logging()
        if version("github-copilot-sdk") != archive.SDK_VERSION:
            raise InvestigationIncompleteError("unsupported Copilot SDK version")
        binary = cached_runtime_path()
        if not binary:
            raise InvestigationIncompleteError("pinned Copilot runtime must be provisioned first")
        self.state_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        directory = self.state_directory / uuid4().hex
        directory.mkdir(mode=0o700)
        base = directory / "native"
        workspace = directory / "workspace"
        workspace.mkdir(mode=0o700)
        evidence = Evidence()
        try:
            if state is not None:
                try:
                    archive.restore(base, state)
                except (InvestigationIncompleteError, OSError):
                    logger.error(
                        "Copilot native archive rejected",
                        extra={
                            "failure_kind": "native_archive_rejected",
                            "archive_phase": "restore",
                        },
                    )
                    raise
                identifier = archive.session_id(state.get("session_id"))
                if identifier not in state["sessions"]:
                    raise InvestigationIncompleteError("native session is absent from archive")
                archived_workspace = state.get("workspace")
                if not isinstance(archived_workspace, dict):
                    raise InvestigationIncompleteError("invalid archived workspace")
                plan = archived_workspace.get("plan.md", "")
                if not isinstance(plan, str) or len(plan.encode("utf-8")) > MAX_PLAN_BYTES:
                    raise InvestigationIncompleteError("invalid archived workspace")
                (workspace / "plan.md").write_text(plan, encoding="utf-8")
                (workspace / "plan.md").chmod(0o600)
            else:
                identifier = str(uuid4())
            async with _owned_context(
                CopilotTraceBridge(
                    self.model,
                    connection_string=self.connection_string,
                    trace_file=self.trace_file,
                ),
                "telemetry",
            ) as bridge:
                credential = (
                    ManagedIdentityCredential()
                    if os.getenv("FOUNDRY_AGENT_NAME")
                    else DefaultAzureCredential()
                )
                async with _owned_context(credential, "credential"):

                    async def token(_request: Any) -> str:
                        evidence.require_active()
                        access_token = await credential.get_token("https://ai.azure.com/.default")
                        evidence.require_active()
                        return access_token.token

                    provider = {
                        "type": "openai",
                        "base_url": self.endpoint,
                        "wire_api": "responses",
                        # Keep provider deployment names out of the runtime's
                        # coding-model presets (1.0.85 adds reasoning.effort to
                        # gpt-4.1-mini even when reasoning support is disabled).
                        "model_id": "checkout-recovery-readonly",
                        "wire_model": self.model,
                        "bearer_token_provider": token,
                        "max_prompt_tokens": 16000,
                        "max_output_tokens": 2000,
                    }
                    environment = {
                        "PATH": os.environ.get("PATH", ""),
                        **transport_environment(),
                    }
                    for name, folder in (
                        ("HOME", "home"),
                        ("TMPDIR", "runtime-scratch"),
                        ("XDG_CONFIG_HOME", "config"),
                        ("XDG_CACHE_HOME", "cache"),
                    ):
                        path = directory / folder
                        path.mkdir(mode=0o700)
                        environment[name] = str(path)
                    environment.update(
                        {
                            "OTEL_BSP_SCHEDULE_DELAY": "500",
                            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "false",
                            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_TOOL_CONTENT": "false",
                        }
                    )
                    client = CopilotClient(
                        connection=RuntimeConnection.for_stdio(path=binary),
                        mode="empty",
                        working_directory=str(workspace),
                        base_directory=str(base),
                        use_logged_in_user=False,
                        log_level="error",
                        env=environment,
                        telemetry={
                            "otlp_endpoint": bridge.endpoint,
                            "otlp_protocol": "http/protobuf",
                            "capture_content": False,
                        },
                    )
                    sessions: list[Any] = []
                    completed = False
                    restored_events = 0
                    try:
                        async with asyncio.timeout(self.timeout):
                            await client.start()
                            status = await client.get_status()
                            if (
                                status.version != archive.RUNTIME_VERSION
                                or status.protocol_version != 3
                            ):
                                raise InvestigationIncompleteError(
                                    "unsupported native runtime version"
                                )

                            async def delegate() -> None:
                                before = evidence.selected.count("read_inventory")
                                child = await client.create_session(
                                    model=self.model,
                                    session_id=str(uuid4()),
                                    **session_options(
                                        workspace,
                                        provider,
                                        build_tools(
                                            simulator,
                                            workspace,
                                            evidence,
                                            delegate,
                                            child=True,
                                            fixture_content=self.fixture_content,
                                        ),
                                        evidence,
                                        child=True,
                                    ),
                                )
                                sessions.append(child)
                                with operation("subagent"):
                                    await guarded_turn(
                                        child,
                                        "Inspect this case's inventory once.",
                                        evidence,
                                        self.timeout,
                                    )
                                if evidence.selected.count("read_inventory") != before + 1:
                                    raise InvestigationIncompleteError(
                                        "inventory child did not read once"
                                    )
                                await child.disconnect()

                            options = session_options(
                                workspace,
                                provider,
                                build_tools(
                                    simulator,
                                    workspace,
                                    evidence,
                                    delegate,
                                    fixture_content=self.fixture_content,
                                ),
                                evidence,
                            )
                            if state is None:
                                session = await client.create_session(
                                    model=self.model, session_id=identifier, **options
                                )
                            else:
                                session = await client.resume_session(
                                    identifier,
                                    model=self.model,
                                    continue_pending_work=False,
                                    **options,
                                )
                            sessions.append(session)
                            if state is not None:
                                restored_events = len(await session.get_events())
                                if not restored_events:
                                    raise InvestigationIncompleteError(
                                        "native history was not restored"
                                    )
                            with operation("model"):
                                await guarded_turn(session, PROMPT, evidence, self.timeout)
                            evidence.verify()
                            completed = True
                    finally:
                        disarm_cancellation_watch()
                        primary = sys.exception()
                        graceful = False
                        try:
                            graceful = await shutdown(
                                client, sessions, evidence, abort=not completed
                            )
                        except BaseException as cleanup:
                            _cleanup_failure("runtime_shutdown", cleanup)
                            if primary is None:
                                raise
                        if completed and not graceful:
                            raise InvestigationIncompleteError(
                                "native runtime did not shut down cleanly; no archive was produced"
                            )
                # The receiver stays alive until native shutdown has flushed OTLP.
            provenance = {
                "sdk_version": archive.SDK_VERSION,
                "runtime_version": status.version,
                "protocol_version": status.protocol_version,
            }
            try:
                snapshot = archive.snapshot(
                    base, [item.session_id for item in sessions], provenance
                )
            except (InvestigationIncompleteError, OSError):
                logger.error(
                    "Copilot native archive rejected",
                    extra={"failure_kind": "native_archive_rejected", "archive_phase": "snapshot"},
                )
                raise
            snapshot.update(
                {
                    "session_id": identifier,
                    "workspace": {"plan.md": (workspace / "plan.md").read_text(encoding="utf-8")},
                    "evidence": {
                        "native_skill_invoked": evidence.skill_invoked,
                        "native_skill_completed": evidence.skill_completed,
                        "workspace_written": evidence.plan_written,
                        "workspace_read": evidence.plan_read,
                        "delegation_mode": "bounded_child_session"
                        if evidence.delegated
                        else "not_used",
                        "child_completed": evidence.child_completed,
                        "tool_calls": evidence.tool_calls,
                        "native_tools_completed": sorted(evidence.completed_tools),
                        "model_turns_observed": evidence.model_turns,
                        "model_retry_attempts_observed": evidence.model_retries,
                        "model_attempts_observed": evidence.model_turns + evidence.model_retries,
                        "model_usage_events": evidence.model_usage_events,
                        "model_budget": ("observed_attempts_cancel_after_12_not_hard_request_cap"),
                        "telemetry_export_failed": bridge.export_failed,
                        "restored_event_count": restored_events,
                    },
                }
            )
            return InvestigationResult(
                selected_tools=tuple(evidence.selected), mode="copilot", framework_state=snapshot
            )
        finally:
            evidence.active = False
            primary = sys.exception()
            try:
                shutil.rmtree(directory)
            except Exception as cleanup:
                _cleanup_failure("workspace", cleanup)
                if primary is None:
                    raise
