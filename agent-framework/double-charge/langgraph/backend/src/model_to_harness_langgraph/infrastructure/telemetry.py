import hashlib
import os
from collections.abc import Awaitable, Callable, Iterator, Mapping
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from functools import wraps
from importlib.metadata import entry_points
from typing import Any

from langgraph.errors import GraphInterrupt
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from .domain_gateway import ToolResult

HOSTED_TRANSPORT_OPTOUTS = frozenset({"requests", "urllib3"})


def correlation(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


@dataclass
class Telemetry:
    providers: tuple[Any, ...] = ()

    def close(self) -> None:
        # Hosted SDK providers are never in this owned tuple.
        providers, self.providers = self.providers, ()
        with ExitStack() as stack:
            for provider in providers:
                stack.callback(provider.shutdown)
                stack.callback(provider.force_flush)


def verify_telemetry_policy(*, hosted: bool = False) -> None:
    for variable in (
        "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT",
        "AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED",
    ):
        if os.getenv(variable, "false").lower() not in {"false", "0", ""}:
            raise RuntimeError("Telemetry message-content capture must be disabled")
    if hosted:
        active = sorted(
            {
                entry.name
                for entry in entry_points(group="opentelemetry_instrumentor")
                if entry.name in HOSTED_TRANSPORT_OPTOUTS
                and entry.load()().is_instrumented_by_opentelemetry
            }
        )
        if active:
            raise RuntimeError(
                "Redundant hosted transport instrumentation is active: " + ", ".join(active)
            )
    if not hosted and not os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        return
    provider = trace.get_tracer_provider()
    sampler = getattr(provider, "sampler", None)
    if sampler is None:
        raise RuntimeError("Telemetry provider must be initialized before runtime startup")
    if sampler.get_description() not in {"AlwaysOnSampler", "ApplicationInsightsSampler1.0"}:
        raise RuntimeError("Workflow telemetry requires a supported complete-retention sampler")
    # Use the public sampler API. Do not mutate OTel private span data or SDK providers.
    for trace_id in (1, (1 << 127), (1 << 128) - 1):
        if not sampler.should_sample(
            None, trace_id, "workflow.retention.probe"
        ).decision.is_sampled():
            raise RuntimeError("Workflow telemetry requires complete native trace retention")


def configure_telemetry(*, hosted: bool = False) -> Telemetry:
    if hosted:
        verify_telemetry_policy(hosted=True)
        return Telemetry()
    if not os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        verify_telemetry_policy()
        return Telemetry()
    from azure.monitor.opentelemetry import configure_azure_monitor
    from opentelemetry import metrics
    from opentelemetry._logs import get_logger_provider
    from opentelemetry.sdk.resources import Resource

    if hasattr(trace.get_tracer_provider(), "sampler"):
        raise RuntimeError("API telemetry cannot replace an existing SDK provider")
    getters = (trace.get_tracer_provider, metrics.get_meter_provider, get_logger_provider)
    before = tuple(getter() for getter in getters)

    def owned_providers() -> Telemetry:
        return Telemetry(
            tuple(
                current
                for previous, getter in zip(before, getters, strict=True)
                if (current := getter()) is not previous
            )
        )

    try:
        configure_azure_monitor(
            connection_string=os.environ["APPLICATIONINSIGHTS_CONNECTION_STRING"],
            logger_name="model_to_harness_langgraph",
            resource=Resource.create(
                {
                    "service.name": os.getenv("OTEL_SERVICE_NAME", "model-to-harness-langgraph"),
                    "deployment.environment": os.getenv("APP_ENV", "local"),
                }
            ),
            sampling_ratio=1.0,
            instrumentation_options={
                name: {"enabled": False}
                for name in (
                    "azure_sdk",
                    "requests",
                    "urllib",
                    "urllib3",
                    "httpx",
                    "psycopg2",
                    "fastapi",
                )
            },
        )
    except BaseException:
        owned_providers().close()
        raise
    owned = owned_providers()
    try:
        verify_telemetry_policy()
    except BaseException:
        owned.close()
        raise
    return owned


@contextmanager
def execution_span(name: str, **attributes: str | int | bool) -> Iterator[trace.Span]:
    tracer = trace.get_tracer("model_to_harness_langgraph.execution")
    with tracer.start_as_current_span(
        name,
        attributes={"workflow.trace_source": "native_execution", **attributes},
        record_exception=False,
        set_status_on_exception=False,
    ) as span:
        try:
            yield span
        except GraphInterrupt:
            span.set_attribute("workflow.interrupted", True)
            raise
        except BaseException as exc:
            span.set_attribute("error.type", type(exc).__name__)
            span.set_status(Status(StatusCode.ERROR))
            raise


def instrument_node[State: Mapping[str, Any]](
    name: str, function: Callable[[State], Awaitable[dict[str, Any]]]
) -> Callable[[State], Awaitable[dict[str, Any]]]:
    @wraps(function)
    async def execute(state: State) -> dict[str, Any]:
        with execution_span(
            f"workflow.node.{name}",
            **{
                "workflow.node": name,
                "workflow.case_id_hash": correlation(state["case_id"]),
                "workflow.run_id_hash": correlation(state["run_id"]),
            },
        ):
            return await function(state)

    return execute


async def execute_tool[**P](
    name: str, function: Callable[P, Awaitable[ToolResult]], *args: P.args, **kwargs: P.kwargs
) -> ToolResult:
    with execution_span(
        f"execute_tool {name}",
        **{"gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": name},
    ) as span:
        result = await function(*args, **kwargs)
        span.set_attribute("workflow.tool.ok", result.ok)
        span.set_attribute("workflow.tool.uncertain", result.uncertain)
        if not result.ok:
            span.set_status(Status(StatusCode.ERROR))
        return result
