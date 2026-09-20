"""Foundry Responses 2.0 adapter for explicit checkout-recovery commands."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import UUID

from azure.ai.agentserver.responses import ResponsesAgentServerHost, TextResponse
from checkout_recovery_copilot.application import (
    CaseNotFoundError,
    CheckoutRecoveryService,
    InvalidCaseCommandError,
    RecordApprovalCommand,
    ResumeCaseCommand,
    StartCaseCommand,
)
from checkout_recovery_copilot.bootstrap import Runtime, create_runtime
from checkout_recovery_copilot.config import Settings
from checkout_recovery_copilot.projections import project_case
from checkout_recovery_copilot.sdk.archive import RUNTIME_VERSION, SDK_VERSION
from checkout_recovery_copilot.sdk.cancellation import cancellation_scope
from model_to_harness_shared import CheckoutApprovalDecision
from psycopg import Error as DatabaseError
from pydantic import BaseModel, ConfigDict, Field, ValidationError


class StartCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: str
    fixture_id: str = Field(min_length=1, max_length=120)
    request_id: UUID | None = None

    def to_command(self) -> StartCaseCommand:
        return StartCaseCommand(self.fixture_id, str(self.request_id) if self.request_id else None)


class ApprovalCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: str
    case_id: str = Field(min_length=1)
    decision: CheckoutApprovalDecision
    reviewer_id: str = Field(min_length=1, max_length=120)
    approval_request_id: UUID
    reason: str = Field(min_length=1, max_length=500)

    def to_command(self) -> RecordApprovalCommand:
        return RecordApprovalCommand(
            self.case_id,
            self.decision,
            self.reviewer_id,
            str(self.approval_request_id),
            self.reason,
        )


class ResumeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    action: str
    case_id: str = Field(min_length=1)

    def to_command(self) -> ResumeCaseCommand:
        return ResumeCaseCommand(self.case_id)


_runtime_lock = asyncio.Lock()
_runtime: Runtime | None = None
_packaged_runtime = Path(__file__).resolve().parent / "copilot-runtime"
_runtime_stage: TemporaryDirectory | None = None
_runtime_executables = {
    "copilot-runtime/prebuilds/linux-x64/" + name
    for name in (
        "copilot-runtime", "runtime.node", "ripgrep/bin/linux-x64/rg", "tgrep/bin/linux-x64/tgrep"
    )
}


def _stage_packaged_runtime() -> TemporaryDirectory:
    metadata = json.loads((_packaged_runtime.parent / "runtime-manifest.json").read_text())
    if (
        metadata["sdk_version"], metadata["version"], metadata["protocol_version"]
    ) != (SDK_VERSION, RUNTIME_VERSION, 3):
        raise ValueError("Unsupported packaged Copilot runtime")
    state_root = Path(os.environ.get(
        "CHECKOUT_COPILOT_STATE_DIRECTORY", str(Path.home() / ".checkout-recovery-copilot")
    ))
    state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    stage = TemporaryDirectory(prefix="runtime-", dir=state_root)
    try:
        for name, digest in metadata["files"].items():
            relative = Path(name)
            if (
                relative.is_absolute() or ".." in relative.parts
                or relative.parts[:1] != ("copilot-runtime",)
            ):
                raise ValueError("Invalid packaged runtime path")
            source = _packaged_runtime.parent / relative
            if any(path.is_symlink() for path in (source, *source.parents)):
                raise ValueError("Packaged runtime symlinks are forbidden")
            target = Path(stage.name) / relative
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            actual = sha256()
            with source.open("rb") as reader, target.open("xb") as writer:
                while chunk := reader.read(64 * 1024):
                    actual.update(chunk)
                    writer.write(chunk)
            target.chmod(0o600)
            if actual.hexdigest() != digest:
                raise ValueError("Packaged runtime digest mismatch")
        for name in _runtime_executables & metadata["files"].keys():
            (Path(stage.name) / name).chmod(0o700)
        binary = Path(stage.name) / "copilot-runtime/prebuilds/linux-x64/copilot-runtime"
        if not os.access(binary, os.X_OK):
            raise RuntimeError("Hosted staging filesystem is not executable")
    except BaseException:
        stage.cleanup()
        raise
    return stage


def _payload(create_response: Any) -> dict[str, Any]:
    if isinstance(create_response, dict):
        return create_response
    if hasattr(create_response, "model_dump"):
        value = create_response.model_dump()
        if isinstance(value, dict):
            return value
    return {}


def _input_text(payload: dict[str, Any]) -> str:
    value = payload.get("input")
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return ""
    for item in reversed(value):
        if not isinstance(item, dict) or item.get("role", "user") != "user":
            continue
        content = item.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            for part in reversed(content):
                if isinstance(part, dict):
                    text = part.get("text") or part.get("input_text")
                    if isinstance(text, str):
                        return text
    return ""


def _command(create_response: Any) -> dict[str, Any]:
    try:
        command = json.loads(_input_text(_payload(create_response)))
    except json.JSONDecodeError as error:
        raise ValueError("command must be a JSON object") from error
    if not isinstance(command, dict):
        raise ValueError("command must be a JSON object")
    return command


async def _checkout_service() -> CheckoutRecoveryService:
    global _runtime, _runtime_stage
    async with _runtime_lock:
        if _runtime is None:
            os.environ.setdefault(
                "CHECKOUT_COPILOT_STATE_DIRECTORY",
                str(Path.home() / ".checkout-recovery-copilot"),
            )
            if await asyncio.to_thread(_packaged_runtime.is_dir):
                if _runtime_stage is None:
                    _runtime_stage = await asyncio.to_thread(_stage_packaged_runtime)
                os.environ["COPILOT_CLI_EXTRACT_DIR"] = str(
                    Path(_runtime_stage.name) / "copilot-runtime"
                )
                os.environ["COPILOT_SKIP_CLI_DOWNLOAD"] = "true"
            runtime = create_runtime(
                Settings(_env_file=None, execution_mode="copilot"), host="hosted"
            )
            startup = asyncio.create_task(asyncio.to_thread(runtime.start))
            try:
                interrupted = False
                while True:
                    try:
                        await asyncio.shield(startup)
                        break
                    except asyncio.CancelledError:
                        if startup.cancelled():
                            raise
                        interrupted = True
                if interrupted:
                    raise asyncio.CancelledError
            except BaseException:
                await asyncio.to_thread(runtime.close)
                raise
            _runtime = runtime
        return _runtime.service


async def _close_runtime() -> None:
    global _runtime, _runtime_stage
    async with _runtime_lock:
        runtime, _runtime = _runtime, None
        try:
            if runtime is not None:
                await asyncio.to_thread(runtime.close)
        finally:
            stage, _runtime_stage = _runtime_stage, None
            if stage is not None:
                await asyncio.to_thread(stage.cleanup)


async def _execute(
    command: dict[str, Any],
    cancellation_signal: asyncio.Event | None = None,
    shutdown_signal: asyncio.Event | None = None,
) -> dict[str, Any]:
    action = command.get("action")
    if action == "start":
        validated = StartCommand.model_validate(command).to_command()
    elif action == "approval":
        validated = ApprovalCommand.model_validate(command).to_command()
    elif action == "resume":
        validated = ResumeCommand.model_validate(command).to_command()
    else:
        raise ValueError("action must be start, approval, or resume")
    service = await _checkout_service()
    cancellation = threading.Event()
    watchers = []
    readonly_start = isinstance(validated, StartCaseCommand)

    async def mirror(signal: asyncio.Event) -> None:
        await signal.wait()
        cancellation.set()

    if readonly_start:
        for signal in (cancellation_signal, shutdown_signal):
            if signal is not None:
                if signal.is_set():
                    cancellation.set()
                watchers.append(asyncio.create_task(mirror(signal)))
        with cancellation_scope(cancellation):
            worker = asyncio.create_task(asyncio.to_thread(service.execute, validated))
    else:
        worker = asyncio.create_task(asyncio.to_thread(service.execute, validated))
    interrupted = False
    try:
        while True:
            try:
                case = await asyncio.shield(worker)
                break
            except asyncio.CancelledError:
                if worker.cancelled():
                    raise
                interrupted = True
                if readonly_start:
                    cancellation.set()
                # A cancelled await cannot stop a thread: wait for its durable outcome.
    finally:
        for watcher in watchers:
            watcher.cancel()
        await asyncio.gather(*watchers, return_exceptions=True)
    if interrupted:
        raise asyncio.CancelledError
    return project_case(case).model_dump(mode="json")


async def response_handler(
    create_response: Any,
    context: Any | None = None,
    cancellation_signal: Any | None = None,
) -> Any:
    try:
        result = await _execute(
            _command(create_response), cancellation_signal, getattr(context, "shutdown", None)
        )
    except (CaseNotFoundError, InvalidCaseCommandError, ValidationError, ValueError, KeyError):
        logging.getLogger(__name__).warning("Checkout command rejected by application policy")
        result = {"error": "checkout command was rejected"}
    except DatabaseError:
        logging.getLogger(__name__).error("Checkout persistence command failed")
        raise RuntimeError("checkout persistence command failed") from None
    return TextResponse(context, create_response, text=json.dumps(result, separators=(",", ":")))


def create_host() -> ResponsesAgentServerHost:
    # Must be set before the platform initializes any Responses instrumentation.
    os.environ["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] = "false"
    host = ResponsesAgentServerHost()
    host.response_handler(response_handler)
    return host


async def main() -> None:
    try:
        await create_host().run_async()
    finally:
        await _close_runtime()


if __name__ == "__main__":
    asyncio.run(main())
