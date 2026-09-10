from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "_packages"))

from azure.ai.agentserver.responses import (  # noqa: E402
    CreateResponse,
    ResponseContext,
    ResponsesAgentServerHost,
    TextResponse,
)
from model_to_harness_langgraph.bootstrap import Runtime, open_runtime  # noqa: E402
from model_to_harness_langgraph.infrastructure.telemetry import (  # noqa: E402
    correlation,
    execution_span,
    verify_telemetry_policy,
)
from model_to_harness_langgraph.projections.hosted_adapter import (  # noqa: E402
    dispatch_hosted_command,
    parse_hosted_command,
    safe_hosted_error,
)
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor  # noqa: E402
from opentelemetry.instrumentation.requests import RequestsInstrumentor  # noqa: E402
from opentelemetry.instrumentation.urllib3 import URLLib3Instrumentor  # noqa: E402
from opentelemetry.trace import Status, StatusCode  # noqa: E402

logger = logging.getLogger(__name__)


def create_host(
    runtime_factory: Callable[[], AbstractAsyncContextManager[Runtime]] | None = None,
) -> ResponsesAgentServerHost:
    for variable in (
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT",
        "AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED",
        "AZURE_TRACING_ENABLED",
    ):
        os.environ.setdefault(variable, "false")
        if os.environ[variable].lower() not in {"false", "0"}:
            raise RuntimeError("Hosted telemetry message-content capture must be disabled")
    os.environ.setdefault("OTEL_TRACES_SAMPLER", "always_on")
    # The pinned distro's IMDS detector otherwise emits redundant HTTP exception payloads.
    os.environ.setdefault("OTEL_PYTHON_DISABLED_INSTRUMENTATIONS", "requests,urllib3,httpx")
    host = ResponsesAgentServerHost()
    # Microsoft distro 1.3.8 re-enables these despite the standard opt-out environment.
    for instrumentor in (RequestsInstrumentor(), URLLib3Instrumentor(), HTTPXClientInstrumentor()):
        if instrumentor.is_instrumented_by_opentelemetry:
            instrumentor.uninstrument()
        if instrumentor.is_instrumented_by_opentelemetry:
            raise RuntimeError("Hosted HTTP instrumentation opt-out was not applied")
    verify_telemetry_policy(hosted=True)
    if runtime_factory is None:
        runtime_factory = partial(open_runtime, hosted=True)

    @host.response_handler
    async def response_handler(
        request: CreateResponse,
        context: ResponseContext,
        _cancellation_signal: asyncio.Event,
    ) -> TextResponse:
        text = await context.get_input_text() or ""
        conversation_id = (
            context.conversation_chain_id or context.conversation_id or context.response_id
        )
        if not conversation_id:
            raise ValueError("Hosted commands require a conversation identity")
        with execution_span(
            "foundry.responses.invoke",
            **{
                "gen_ai.operation.name": "invoke_agent",
                "gen_ai.agent.name": "model-harness-langgraph",
                "workflow.conversation_id_hash": correlation(conversation_id),
            },
        ) as span:
            try:
                command = parse_hosted_command(text)
                async with runtime_factory() as runtime:
                    result = await dispatch_hosted_command(
                        runtime.service, command, conversation_id
                    )
            except Exception as exc:
                error = safe_hosted_error(exc)
                span.set_attribute("error.type", type(exc).__name__)
                span.set_attribute("workflow.error_type", type(exc).__name__)
                span.set_status(Status(StatusCode.ERROR, error["error"]["code"]))
                if error["error"]["code"] == "internal_error":
                    logger.error(
                        "Hosted workflow command failed",
                        extra={"error_type": type(exc).__name__},
                    )
                result = error
            return TextResponse(
                context,
                request,
                text=json.dumps(result, separators=(",", ":"), sort_keys=True),
            )

    return host


async def main() -> None:
    host = create_host()
    async with open_runtime(hosted=True) as runtime:
        await runtime.verify()
    # Idle hosted compute must not retain application pools or the native saver connection.
    await host.run_async()


if __name__ == "__main__":
    asyncio.run(main())
