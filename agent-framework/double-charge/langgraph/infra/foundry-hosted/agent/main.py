from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent / "_packages"))

from azure.ai.agentserver.responses import (  # noqa: E402
    CreateResponse,
    ResponseContext,
    ResponsesAgentServerHost,
    TextResponse,
)
from model_to_harness_langgraph.app import create_app  # noqa: E402
from model_to_harness_langgraph.hosted_adapter import (  # noqa: E402
    dispatch_hosted_command,
    parse_hosted_command,
    safe_hosted_error,
)
from model_to_harness_langgraph.service import WorkflowService  # noqa: E402
from opentelemetry import trace  # noqa: E402
from opentelemetry.trace import Status, StatusCode  # noqa: E402

logger = logging.getLogger(__name__)
host = ResponsesAgentServerHost()
tracer = trace.get_tracer("model_to_harness_langgraph.foundry.responses")
_runtime_lock = asyncio.Lock()
_service: WorkflowService | None = None
_app: Any | None = None
_lifespan: Any | None = None


async def workflow_service() -> WorkflowService:
    global _app, _lifespan, _service
    if _service is not None:
        return _service
    async with _runtime_lock:
        if _service is None:
            app = create_app()
            lifespan = app.router.lifespan_context(app)
            await lifespan.__aenter__()
            _app = app
            _lifespan = lifespan
            _service = app.state.service
    assert _service is not None
    return _service


@host.response_handler
async def response_handler(
    request: CreateResponse,
    context: ResponseContext,
    _cancellation_signal: asyncio.Event,
) -> TextResponse:
    text = await context.get_input_text() or ""
    conversation_id = (
        context.conversation_chain_id
        or context.conversation_id
        or context.response_id
    )
    with tracer.start_as_current_span("foundry.responses.invoke") as span:
        span.set_attribute("gen_ai.operation.name", "invoke_agent")
        span.set_attribute("gen_ai.agent.name", "model-harness-langgraph")
        span.set_attribute("gen_ai.agent.id", "model-harness-langgraph")
        span.set_attribute("gen_ai.conversation.id", conversation_id)
        span.set_attribute("azure.ai.agentserver.conversation_id", conversation_id)
        if context.response_id:
            span.set_attribute("gen_ai.response.id", context.response_id)
        try:
            result = await dispatch_hosted_command(
                await workflow_service(),
                parse_hosted_command(text),
                conversation_id,
            )
        except Exception as exc:
            error = safe_hosted_error(exc)
            span.set_attribute("error.type", type(exc).__name__)
            span.set_status(Status(StatusCode.ERROR, error["error"]["code"]))
            if error["error"]["code"] == "internal_error":
                logger.error(
                    "Hosted workflow command failed",
                    extra={"error_type": type(exc).__name__},
                )
            result = error
        case = result.get("case")
        correlated_result = case if isinstance(case, dict) else result
        for key in ("case_id", "run_id", "status", "current_step"):
            value = correlated_result.get(key)
            if isinstance(value, str):
                span.set_attribute(f"workflow.{key}", value)
        return TextResponse(
            context,
            request,
            text=json.dumps(result, separators=(",", ":"), sort_keys=True),
        )


if __name__ == "__main__":
    host.run()
