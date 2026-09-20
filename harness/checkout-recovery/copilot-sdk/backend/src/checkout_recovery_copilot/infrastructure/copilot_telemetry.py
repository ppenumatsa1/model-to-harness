"""Receive native CLI OTLP on a case-owned loopback socket without rewriting ancestry."""

import asyncio
import json
import logging
import os
import re
import socket
from pathlib import Path
from threading import Lock

from aiohttp import web
from google.protobuf.message import DecodeError
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.sdk.util.instrumentation import InstrumentationScope
from opentelemetry.trace import SpanContext, SpanKind, Status, StatusCode, TraceFlags

logger = logging.getLogger(__name__)
_RECEIPT_LOCK = Lock()
MAX_RECEIPT_BYTES = 32 * 1024 * 1024
AGENT_NAME = "checkout-recovery-copilot"
TOOLS = frozenset({
    "read_order", "read_payment", "read_inventory", "read_logs",
    "delegate_inventory", "write_plan", "read_plan", "skill",
})
TIMING_PHASES = frozenset({
    "construction_input", "construction_lock", "construction_options",
    "native_session_materialization", "construction_plan_parse", "session_host_configuration",
    "session_update_options_feature_flags", "session_update_options_skills_cache",
    "session_update_options_plugin_caches", "session_update_options_tail",
    "session_update_options", "session_pending_noop", "session_completion",
    "custom_agent_configuration", "additional_directory_permissions", "session_descriptor",
    "session_construction", "host_request_preparation", "host_callback_request_encoding",
    "host_callback_reply_delivery", "host_callback_response_decoding", "host_callback",
    "host_response_merge", "host_initialization", "response_adoption", "factory_validation",
    "external_tool_registration", "command_registration", "capability_registration",
    "permission_registration", "factory_registration", "hook_registration",
    "connection_configuration", "canvas_registration", "session_event_drain",
    "connection_finalization", "connection_readiness", "model_resolution",
    "content_exclusion_policy_resolution", "content_exclusion_preparation", "custom_agent_loading",
    "skills_loading", "mcp_bridge_reconciliation", "mcp_initialization",
    "github_mcp_authentication", "lsp_initialization", "prompt_environment", "mcp_catalog",
    "system_message_inputs", "skills_custom_agents", "tool_descriptors", "powershell_prompt",
    "system_prompt", "tool_cache_validation", "tool_initialization_attempt", "turn_preparation",
    "context_assembly", "turn_setup", "user_message_prompt_hooks", "user_message_preamble_context",
    "user_message_preamble_producers", "user_message_attachment_gate",
    "user_message_attachment_preparation", "user_message_preamble_assembly",
    "user_prompt_transformed", "user_message_event_emission", "user_message_emission",
    "pre_request_capability_pruning", "pre_request_compaction", "pre_request_jit_instruction",
    "pre_request_truncation", "pre_request_response_limits", "pre_request_immediate_prompts",
    "pre_request_image_processing", "pre_request_finalization", "attempt_pre_request",
    "attempt_cache_control", "attempt_message_assembly", "attempt_incremental_input",
    "attempt_request_capture", "model_request_preparation", "model_physical_dispatch_to_completion",
})
COUNTERS = frozenset({
    "gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens",
    "github.copilot.session.timing.modelCallCount",
    "github.copilot.session.timing.modelCallOutputCount",
    "github.copilot.session.timing.modelCallToolRequestCount",
})
SAFE_VALUES = {
    "gen_ai.operation.name": {"chat", "execute_tool", "invoke_agent"},
    "gen_ai.provider.name": {"openai", "azure.ai.openai"},
    "gen_ai.tool.name": TOOLS,
    "gen_ai.tool.type": {"function", "extension"},
    "error.type": {"TimeoutError", "AuthenticationError", "RateLimitError", "APIError"},
}
FINISH_REASONS = frozenset({
    "stop", "tool_calls", "length", "content_filter", "error", "end_turn",
    "max_tokens", "tool_use", "completed",
})


def native_span(span, model_deployment: str) -> ReadableSpan:
    if len(span.trace_id) != 16 or len(span.span_id) != 8:
        raise ValueError("invalid native trace identity")
    if span.parent_span_id and len(span.parent_span_id) != 8:
        raise ValueError("invalid native parent identity")
    if not int.from_bytes(span.trace_id) or not int.from_bytes(span.span_id):
        raise ValueError("zero native trace identity")
    if span.kind not in range(6) or span.status.code not in range(3):
        raise ValueError("invalid native span metadata")

    def context(span_id):
        return SpanContext(
            int.from_bytes(span.trace_id), int.from_bytes(span_id),
            False, TraceFlags(TraceFlags.SAMPLED),
        )

    attributes = {
        "checkout.native": True,
        "gen_ai.agent.name": AGENT_NAME,
        "checkout.model.configured_deployment": model_deployment,
    }
    version = os.getenv("FOUNDRY_AGENT_VERSION", "")
    if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", version):
        attributes["gen_ai.agent.version"] = version
    for entry in span.attributes:
        key, value = entry.key, entry.value
        if key in COUNTERS and value.WhichOneof("value") == "int_value":
            if value.int_value >= 0:
                attributes[key] = value.int_value
        elif value.string_value in SAFE_VALUES.get(key, ()):
            attributes[key] = value.string_value
        elif key in {"gen_ai.request.model", "gen_ai.response.model"}:
            if value.string_value in {model_deployment, "checkout-recovery-readonly"}:
                attributes[key] = value.string_value
                if value.string_value == "checkout-recovery-readonly":
                    attributes["checkout.model.profile"] = value.string_value
        elif key in {"gen_ai.response.id", "gen_ai.tool.call.id", "gen_ai.conversation.id"}:
            if re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", value.string_value):
                target = "checkout.copilot.session_id" if key == "gen_ai.conversation.id" else key
                attributes[target] = value.string_value
        elif key == "gen_ai.response.finish_reasons":
            reasons = tuple(item.string_value for item in value.array_value.values)
            if reasons and all(reason in FINISH_REASONS for reason in reasons):
                attributes[key] = reasons
    name, role = "copilot.runtime", "runtime"
    if span.name.startswith("chat "):
        role = "model_response" if "gen_ai.response.id" in attributes else "model_request"
        name = f"chat {model_deployment} [{role}]"
    elif span.name.startswith("execute_tool "):
        tool = span.name.removeprefix("execute_tool ")
        name, role = f"execute_tool {tool if tool in TOOLS else 'other'}", "tool"
    elif span.name == "invoke_agent" or span.name.startswith("invoke_agent "):
        name, role = "invoke_agent copilot", "agent"
    elif span.name.startswith("external_tool "):
        name, role = "copilot.external_tool_callback", "tool_callback"
    elif span.name in {"session.provisioning", "session.first_turn"}:
        name, role = span.name, "session"
    elif span.name.startswith("session.timing."):
        if span.name.removeprefix("session.timing.") in TIMING_PHASES:
            name = span.name
    attributes["checkout.span_role"] = role
    return ReadableSpan(
        name=name, context=context(span.span_id),
        parent=context(span.parent_span_id) if span.parent_span_id else None,
        resource=Resource({"service.name": AGENT_NAME}),
        attributes=attributes, kind=SpanKind(max(0, span.kind - 1)),
        start_time=span.start_time_unix_nano, end_time=span.end_time_unix_nano,
        status=Status(
            {0: StatusCode.UNSET, 1: StatusCode.OK, 2: StatusCode.ERROR}[span.status.code]
        ),
        instrumentation_scope=InstrumentationScope("github.copilot"),
    )


def save_spans(path: Path, spans: list[ReadableSpan]) -> None:
    payload = "".join(json.dumps({
        "name": span.name,
        "trace_id": f"{span.context.trace_id:032x}",
        "span_id": f"{span.context.span_id:016x}",
        "parent_id": f"{span.parent.span_id:016x}" if span.parent else None,
        "attributes": dict(span.attributes),
    }) + "\n" for span in spans).encode()
    with _RECEIPT_LOCK:
        descriptor = os.open(
            path, os.O_APPEND | os.O_CREAT | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600
        )
        try:
            if os.fstat(descriptor).st_size + len(payload) > MAX_RECEIPT_BYTES:
                raise OSError("local trace receipt size limit exceeded")
            os.fchmod(descriptor, 0o600)
            remaining = memoryview(payload)
            while remaining:
                written = os.write(descriptor, remaining)
                if written <= 0:
                    raise OSError("local trace receipt write made no progress")
                remaining = remaining[written:]
        finally:
            os.close(descriptor)


class CopilotTraceBridge:
    def __init__(
        self, model_deployment: str, connection_string: str | None = None,
        trace_file: Path | None = None, *, exporter: SpanExporter | None = None,
    ) -> None:
        self.model_deployment = model_deployment
        self.connection_string = connection_string
        self.trace_file = trace_file
        self.exporter = exporter
        self.endpoint = ""
        self.runner: web.AppRunner | None = None
        self.export_failed = False

    async def __aenter__(self):
        try:
            await self.start()
        except BaseException:
            await self.close()
            raise
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        await self.close()

    async def start(self) -> None:
        if self.runner is not None:
            return
        if self.connection_string and self.exporter is None:
            from azure.monitor.opentelemetry.exporter import AzureMonitorTraceExporter

            self.exporter = AzureMonitorTraceExporter(
                connection_string=self.connection_string, disable_offline_storage=True,
            )
        application = web.Application(client_max_size=2 * 1024 * 1024)
        application.router.add_post("/v1/traces", self.receive)
        self.runner = web.AppRunner(application, access_log=None)
        await self.runner.setup()
        sock = socket.socket()
        try:
            sock.bind(("127.0.0.1", 0))
            sock.setblocking(False)
            port = sock.getsockname()[1]
            await web.SockSite(self.runner, sock).start()
        except BaseException:
            sock.close()
            raise
        self.endpoint = f"http://127.0.0.1:{port}"

    async def receive(self, request: web.Request) -> web.Response:
        message = ExportTraceServiceRequest()
        try:
            message.ParseFromString(await request.read())
            spans = [
                native_span(span, self.model_deployment)
                for resource in message.resource_spans
                for scope in resource.scope_spans
                for span in scope.spans
            ]
        except web.HTTPRequestEntityTooLarge:
            self.export_failed = True
            logger.warning("Rejected oversized native telemetry batch")
            raise
        except (DecodeError, ValueError):
            self.export_failed = True
            logger.warning("Rejected malformed native telemetry batch")
            return web.Response(status=400)
        if self.trace_file:
            try:
                await asyncio.to_thread(save_spans, self.trace_file, spans)
            except OSError as error:
                self.export_failed = True
                logger.error("Native trace receipt write failed (%s)", type(error).__name__)
                return web.Response(status=503)
        if self.exporter and spans:
            exported = False
            try:
                result = await asyncio.to_thread(self.exporter.export, spans)
                exported = result == SpanExportResult.SUCCESS
            finally:
                if not exported:
                    self.export_failed = True
                    logger.error("Native Copilot telemetry export failed")
            if not exported:
                return web.Response(status=503)
        return web.Response(body=b"", content_type="application/x-protobuf")

    async def close(self) -> None:
        try:
            if self.runner is not None:
                await self.runner.cleanup()
        finally:
            self.runner = None
            if self.exporter is not None:
                await asyncio.to_thread(self.exporter.shutdown)
                self.exporter = None
