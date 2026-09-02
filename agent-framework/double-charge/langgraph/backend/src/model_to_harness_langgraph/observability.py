import logging
import os
from datetime import datetime
from typing import Any

logger = logging.getLogger(__name__)
_TELEMETRY_INTERNAL_LOGGERS = (
    "azure.core.pipeline.policies.http_logging_policy",
    "azure.monitor.opentelemetry.exporter",
)
_AZURE_MONITOR_CONFIGURED = False


def configure_optional_azure_monitor() -> bool:
    global _AZURE_MONITOR_CONFIGURED
    if _AZURE_MONITOR_CONFIGURED:
        return True
    connection_string = os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if not connection_string:
        logger.info("Azure Monitor tracing disabled; no connection string configured")
        return False
    if os.getenv("FOUNDRY_PROJECT_ENDPOINT"):
        logger.info("Hosted Responses runtime owns Azure Monitor exporter configuration")
        _AZURE_MONITOR_CONFIGURED = True
        return True
    try:
        from azure.monitor.opentelemetry import configure_azure_monitor
    except ImportError:
        logger.warning("Install the observability extra to enable Azure Monitor tracing")
        return False
    from opentelemetry.sdk.resources import Resource

    resource = Resource.create(
        {
            "service.name": os.getenv("OTEL_SERVICE_NAME", "model-to-harness-langgraph"),
            "deployment.environment": os.getenv("APP_ENV", "local"),
        }
    )
    configure_azure_monitor(connection_string=connection_string, resource=resource)
    # Exporter transport logs must not be exported by the logging pipeline itself.
    for logger_name in _TELEMETRY_INTERNAL_LOGGERS:
        logging.getLogger(logger_name).setLevel(logging.WARNING)
    _AZURE_MONITOR_CONFIGURED = True
    return True


def reset_observability_for_tests() -> None:
    global _AZURE_MONITOR_CONFIGURED
    _AZURE_MONITOR_CONFIGURED = False


def project_durable_node_spans(
    events: list[Any],
    *,
    parent_context: Any | None,
) -> None:
    try:
        from opentelemetry import trace
    except ImportError:
        return

    grouped: dict[str, list[Any]] = {}
    for event in events:
        node = getattr(event, "node", None)
        if isinstance(node, str) and node:
            grouped.setdefault(node, []).append(event)

    tracer = trace.get_tracer("model_to_harness_langgraph.workflow.audit")
    for node, node_events in grouped.items():
        timestamps = [
            timestamp
            for event in node_events
            if isinstance((timestamp := getattr(event, "timestamp", None)), datetime)
        ]
        if not timestamps:
            continue
        start_time = int(min(timestamps).timestamp() * 1_000_000_000)
        end_time = max(
            int(max(timestamps).timestamp() * 1_000_000_000),
            start_time + 1,
        )
        first = node_events[0]
        span = tracer.start_span(
            f"workflow.node.{node}",
            context=parent_context,
            start_time=start_time,
            attributes={
                "workflow.node": node,
                "workflow.case_id": first.case_id,
                "workflow.run_id": first.run_id,
                "workflow.event_count": len(node_events),
                "workflow.trace_source": "durable_audit_projection",
            },
        )
        span.end(end_time=end_time)

    tool_events: dict[str, list[Any]] = {}
    for event in events:
        if getattr(event, "event_type", None) not in {
            "tool_call_started",
            "tool_call_succeeded",
            "tool_call_failed",
            "tool_call_retried",
        }:
            continue
        data = getattr(event, "data", None)
        if not isinstance(data, dict):
            continue
        tool_name = data.get("tool")
        if isinstance(tool_name, str) and tool_name:
            tool_events.setdefault(tool_name, []).append(event)
    for tool_name, matching_events in tool_events.items():
        _project_event_group_span(
            tracer,
            matching_events,
            name=f"execute_tool {tool_name}",
            parent_context=parent_context,
            attributes={
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.tool.name": tool_name,
                "workflow.trace_source": "durable_audit_projection",
            },
        )


def _project_event_group_span(
    tracer: Any,
    events: list[Any],
    *,
    name: str,
    parent_context: Any | None,
    attributes: dict[str, str],
) -> None:
    timestamps = [
        timestamp
        for event in events
        if isinstance((timestamp := getattr(event, "timestamp", None)), datetime)
    ]
    if not timestamps:
        return
    start_time = int(min(timestamps).timestamp() * 1_000_000_000)
    end_time = max(
        int(max(timestamps).timestamp() * 1_000_000_000),
        start_time + 1,
    )
    span = tracer.start_span(
        name,
        context=parent_context,
        start_time=start_time,
        attributes=attributes,
    )
    span.end(end_time=end_time)
