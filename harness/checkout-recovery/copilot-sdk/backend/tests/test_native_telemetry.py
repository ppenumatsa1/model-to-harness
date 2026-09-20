import asyncio
import json
from concurrent.futures import ThreadPoolExecutor

import aiohttp
import pytest
from checkout_recovery_copilot.infrastructure import copilot_telemetry
from checkout_recovery_copilot.infrastructure.copilot_telemetry import (
    CopilotTraceBridge,
    native_span,
)
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.proto.trace.v1.trace_pb2 import Span
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult


def native(name="invoke_agent", parent=2):
    return Span(
        name=name,
        trace_id=(1).to_bytes(16),
        span_id=(3).to_bytes(8),
        parent_span_id=parent.to_bytes(8),
        start_time_unix_nano=100,
        end_time_unix_nano=200,
    )


def attribute(span, name, value):
    span.attributes.add(key=name).value.string_value = value


def test_native_conversion_preserves_ancestry_without_unrestricted_content():
    source = native("chat private model")
    attribute(source, "gen_ai.request.model", "allowed-model")
    attribute(source, "gen_ai.response.id", "resp-1")
    attribute(source, "gen_ai.input.messages", "secret-content")
    attribute(source, "db.connection_string", "secret-content")
    attribute(source, "gen_ai.conversation.id", "session-1")
    source.status.code = 2
    source.status.message = "secret-content"
    converted = native_span(source, "allowed-model")
    assert converted.name == "chat allowed-model [model_response]"
    assert converted.context.trace_id == 1
    assert converted.context.span_id == 3
    assert converted.parent.span_id == 2
    assert converted.start_time == 100 and converted.end_time == 200
    assert converted.status.description is None
    assert converted.attributes["checkout.copilot.session_id"] == "session-1"
    assert "gen_ai.conversation.id" not in converted.attributes
    assert converted.instrumentation_scope.name == "github.copilot"
    assert "secret-content" not in converted.to_json()


def test_behavior_profile_and_actual_wire_deployment_remain_distinct():
    source = native("chat checkout-recovery-readonly")
    attribute(source, "gen_ai.request.model", "checkout-recovery-readonly")
    converted = native_span(source, "gpt-4.1-mini")
    assert converted.attributes["gen_ai.request.model"] == "checkout-recovery-readonly"
    assert converted.attributes["checkout.model.profile"] == "checkout-recovery-readonly"
    assert converted.attributes["checkout.model.configured_deployment"] == "gpt-4.1-mini"
    assert converted.name == "chat gpt-4.1-mini [model_request]"


def test_concurrent_receipt_batches_remain_complete_json_lines(tmp_path):
    path = tmp_path / "concurrent.jsonl"
    spans = [native_span(native(), "model")] * 100
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda _: copilot_telemetry.save_spans(path, spans), range(8)))
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 800
    assert all(row["name"] == "invoke_agent copilot" for row in rows)


def test_receipt_partial_writes_and_size_bound_are_explicit(tmp_path, monkeypatch):
    path = tmp_path / "partial.jsonl"
    original = copilot_telemetry.os.write
    monkeypatch.setattr(copilot_telemetry.os, "write", lambda fd, data: original(fd, data[:17]))
    copilot_telemetry.save_spans(path, [native_span(native(), "model")])
    before = path.read_bytes()
    assert json.loads(before)["name"] == "invoke_agent copilot"
    monkeypatch.setattr(copilot_telemetry, "MAX_RECEIPT_BYTES", len(before))
    with pytest.raises(OSError, match="size limit"):
        copilot_telemetry.save_spans(path, [native_span(native(), "model")])
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("invoke_agent", "invoke_agent copilot"),
        ("execute_tool read_order", "execute_tool read_order"),
        ("execute_tool secret-content", "execute_tool other"),
        ("session.timing.context_assembly", "session.timing.context_assembly"),
        ("session.timing.secret-content", "copilot.runtime"),
        ("external_tool secret-content", "copilot.external_tool_callback"),
    ],
)
def test_safe_native_names(name, expected):
    assert native_span(native(name), "model").name == expected


@pytest.mark.parametrize("field", ["trace_id", "span_id", "parent_span_id"])
def test_invalid_id_is_explicitly_rejected(field):
    source = native()
    setattr(source, field, b"bad")
    with pytest.raises(ValueError, match="identity"):
        native_span(source, "model")


class RecordingExporter(SpanExporter):
    def __init__(self, result=SpanExportResult.SUCCESS):
        self.spans = []
        self.stopped = False
        self.result = result

    def export(self, spans):
        self.spans.extend(spans)
        return self.result

    def shutdown(self):
        self.stopped = True


async def test_concurrent_bridges_have_unique_loopback_ports_and_private_receipts(tmp_path):
    exporters = [RecordingExporter(), RecordingExporter()]
    bridges = [
        CopilotTraceBridge("model", trace_file=tmp_path / f"{i}.jsonl", exporter=exporter)
        for i, exporter in enumerate(exporters)
    ]
    async with bridges[0], bridges[1], aiohttp.ClientSession() as client:
        assert bridges[0].endpoint != bridges[1].endpoint
        assert all(bridge.endpoint.startswith("http://127.0.0.1:") for bridge in bridges)
        payload = ExportTraceServiceRequest()
        payload.resource_spans.add().scope_spans.add().spans.add().CopyFrom(native())

        async def send(bridge):
            async with client.post(
                bridge.endpoint + "/v1/traces", data=payload.SerializeToString(),
            ) as response:
                assert response.status == 200

        await asyncio.gather(*(send(bridge) for bridge in bridges))
    for index, exporter in enumerate(exporters):
        assert exporter.stopped
        assert len(exporter.spans) == 1
        receipt = tmp_path / f"{index}.jsonl"
        assert receipt.stat().st_mode & 0o777 == 0o600
        assert json.loads(receipt.read_text())["parent_id"] == "0000000000000002"


async def test_rejected_batches_and_export_failures_are_visible():
    exporter = RecordingExporter(SpanExportResult.FAILURE)
    bridge = CopilotTraceBridge("model", exporter=exporter)
    async with bridge, aiohttp.ClientSession() as client:
        async with client.post(bridge.endpoint + "/v1/traces", data=b"\xff") as response:
            assert response.status == 400
        assert bridge.export_failed
        payload = ExportTraceServiceRequest()
        payload.resource_spans.add().scope_spans.add().spans.add().CopyFrom(native())
        async with client.post(
            bridge.endpoint + "/v1/traces", data=payload.SerializeToString(),
        ) as response:
            assert response.status == 503
    assert exporter.stopped


async def test_receipt_limit_is_a_visible_native_export_failure(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(copilot_telemetry, "MAX_RECEIPT_BYTES", 0)
    bridge = CopilotTraceBridge("model", trace_file=tmp_path / "full.jsonl")
    async with bridge, aiohttp.ClientSession() as client:
        payload = ExportTraceServiceRequest()
        payload.resource_spans.add().scope_spans.add().spans.add().CopyFrom(native())
        async with client.post(
            bridge.endpoint + "/v1/traces", data=payload.SerializeToString(),
        ) as response:
            assert response.status == 503
    assert bridge.export_failed
    assert "Native trace receipt write failed" in caplog.text


async def test_exporter_exception_sets_failure_without_hiding_error():
    class BrokenExporter(RecordingExporter):
        def export(self, spans):
            raise RuntimeError("exporter unavailable")

    bridge = CopilotTraceBridge("model", exporter=BrokenExporter())
    async with bridge, aiohttp.ClientSession() as client:
        payload = ExportTraceServiceRequest()
        payload.resource_spans.add().scope_spans.add().spans.add().CopyFrom(native())
        async with client.post(
            bridge.endpoint + "/v1/traces", data=payload.SerializeToString(),
        ) as response:
            assert response.status == 500
    assert bridge.export_failed


async def test_oversized_native_batch_sets_failure():
    bridge = CopilotTraceBridge("model")
    async with bridge, aiohttp.ClientSession() as client:
        async with client.post(
            bridge.endpoint + "/v1/traces", data=b"x" * (2 * 1024 * 1024 + 1),
        ) as response:
            assert response.status == 413
    assert bridge.export_failed
