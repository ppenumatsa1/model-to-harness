"""Exercise wheels, or build an isolated hash-pinned Python 3.13 hosted smoke environment."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from prepare_hosted import prepare

LANE = Path(__file__).resolve().parents[1]
ROOT = LANE.parents[2]

WHEEL_CHECK = """
import importlib.resources
import pathlib
import sys
sys.path.insert(0, sys.argv[1])
import model_to_harness_langgraph
import model_to_harness_shared
from model_to_harness_langgraph.api.app import create_app
from model_to_harness_langgraph import bootstrap
from model_to_harness_langgraph.infrastructure.persistence.migrations import load_migrations
import json
installed = pathlib.Path(sys.argv[1]).resolve()
for module in (model_to_harness_langgraph, model_to_harness_shared):
    assert pathlib.Path(module.__file__).resolve().is_relative_to(installed)
sql = importlib.resources.files("model_to_harness_langgraph.infrastructure.persistence") / "sql"
files = list(sql.iterdir())
assert files and any(path.name.endswith(".sql") for path in files)
for path in files:
    if path.name.endswith(".sql"):
        assert path.read_text().strip()
assert callable(create_app)
assert [item.checksum for item in load_migrations()] == json.loads(sys.argv[2])
print("Installed-wheel imports and packaged SQL passed outside checkout")
"""

HOSTED_CHECK = """
import importlib.util
import pathlib
import sys
import asyncio
import json
import os
import socket
from importlib.metadata import version
root = pathlib.Path(sys.argv[1]).resolve()
assert sys.version_info[:2] == (3, 13), "Hosted bundle requires Python 3.13"
for distribution, expected in {
    "azure-ai-agentserver-core": "2.1.0",
    "azure-ai-agentserver-responses": "2.1.0",
    "langgraph": "1.2.11",
    "langgraph-checkpoint-postgres": "3.1.2",
    "opentelemetry-sdk": "1.43.0",
}.items():
    actual = version(distribution)
    assert actual == expected, f"Hosted bundle: {distribution} expected {expected}, got {actual}"
spec = importlib.util.spec_from_file_location("hosted_main", root / "main.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
import model_to_harness_langgraph
assert pathlib.Path(model_to_harness_langgraph.__file__).resolve().is_relative_to(root)
assert callable(module.main)
assert callable(module.create_host)
os.environ["AGENTSERVER_STATE_ROOT"] = str(root.parent / "state")
for signal in ("TRACES", "METRICS", "LOGS"):
    os.environ[f"OTEL_{signal}_EXPORTER"] = "none"
def deny_network(*args, **kwargs):
    raise OSError("Network access is prohibited during package smoke")
socket.socket.connect = deny_network
from httpx import ASGITransport, AsyncClient
from langgraph.checkpoint.memory import InMemorySaver
from model_to_harness_langgraph.config import Settings
from model_to_harness_langgraph.testing.audit import InMemoryAuditRepository
from model_to_harness_langgraph.testing.fakes import FakeModel, FakeDomainGateway
from opentelemetry import trace
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.urllib3 import URLLib3Instrumentor
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
host = module.create_host()
assert not RequestsInstrumentor().is_instrumented_by_opentelemetry
assert not URLLib3Instrumentor().is_instrumented_by_opentelemetry
provider = trace.get_tracer_provider()
assert hasattr(provider, "sampler")
exporter = InMemorySpanExporter()
provider.add_span_processor(SimpleSpanProcessor(exporter))
for trace_id in (1, 1 << 127, (1 << 128) - 1):
    assert provider.sampler.should_sample(None, trace_id, "retention").decision.is_sampled()
async def smoke():
    async with module.open_runtime(
        Settings(_env_file=None), hosted=True,
        audit=InMemoryAuditRepository(), model=FakeModel(),
        gateway=FakeDomainGateway(), checkpointer=InMemorySaver(),
    ) as runtime:
        host.state.runtime = runtime
        async with host.router.lifespan_context(host):
            async with AsyncClient(
                transport=ASGITransport(app=host), base_url="http://smoke"
            ) as client:
                async def command(payload):
                    response = await client.post("/responses", json={
                        "input": json.dumps(payload), "store": False, "stream": False,
                    })
                    assert response.status_code == 200, response.text
                    body = response.json()
                    assert body["status"] == "completed", body
                    texts = [
                        content["text"] for item in body["output"]
                        for content in item.get("content", []) if content["type"] == "output_text"
                    ]
                    result = json.loads("".join(texts))
                    assert result["ok"], result
                    return result["case"]
                started = await command({"action": "start", "case_id": "packaged-smoke"})
                assert started["status"] == "paused"
                await command({
                    "action": "approval", "case_id": started["case_id"],
                    "checkpoint_id": started["checkpoint_id"],
                    "decision": "approve", "reviewer_id": "package-smoke",
                })
                resumed = await command({"action": "resume", "case_id": started["case_id"]})
                assert resumed["status"] == "completed"
asyncio.run(smoke())
spans = exporter.get_finished_spans()
assert any(span.name.startswith("workflow.node.") for span in spans)
assert any(span.name.startswith("execute_tool ") for span in spans)
assert all(
    span.instrumentation_scope.name not in {
        "opentelemetry.instrumentation.requests", "opentelemetry.instrumentation.urllib3"
    }
    for span in spans
)
print("Python 3.13 hosted ASGI start/approve/resume and native sampler checks passed offline")
"""


def hosted_python(workspace: Path, bundle: Path, env: dict[str, str]) -> Path:
    environment = workspace / "hosted-venv"
    executable = environment / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    commands = [
        ["uv", "venv", "--python", "3.13", "--quiet", str(environment)],
        [
            "uv",
            "pip",
            "sync",
            "--python",
            str(executable),
            "--require-hashes",
            "--quiet",
            str(bundle / "requirements.txt"),
        ],
        ["uv", "pip", "check", "--python", str(executable)],
    ]
    for command in commands:
        subprocess.run(command, cwd=workspace, env=env, check=True)
    return executable


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hosted", action="store_true")
    args = parser.parse_args()
    env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
    with tempfile.TemporaryDirectory(prefix="langgraph-package-smoke-") as directory:
        workspace = Path(directory)
        if args.hosted:
            bundle = workspace / "agent"
            prepare(bundle)
            env = {
                key: value
                for key, value in env.items()
                if not key.startswith(
                    ("AZURE_", "FOUNDRY_", "AGENT", "OTEL_", "APPLICATIONINSIGHTS")
                )
                and key not in {"DATABASE_URL", "VIRTUAL_ENV", "CONDA_PREFIX", "PYTHONHOME"}
            }
            executable = hosted_python(workspace, bundle, env)
            result = subprocess.run(
                [str(executable), "-I", "-c", HOSTED_CHECK, str(bundle)],
                cwd=workspace,
                env=env,
                capture_output=True,
                text=True,
            )
            if result.returncode:
                print(result.stdout, end="")
                print(result.stderr, end="", file=sys.stderr)
                raise SystemExit(result.returncode)
            print(
                "Python 3.13 hosted ASGI start/approve/resume "
                "and native sampler checks passed offline"
            )
        else:
            wheels = workspace / "wheels"
            for project in (ROOT / "shared", LANE):
                subprocess.run(
                    ["uv", "build", "--wheel", "--out-dir", str(wheels), str(project)],
                    cwd=workspace,
                    env=env,
                    check=True,
                )
            installed = workspace / "installed"
            subprocess.run(
                [
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    sys.executable,
                    "--target",
                    str(installed),
                    "--no-deps",
                    "--no-index",
                    "--find-links",
                    str(wheels),
                    "model-to-harness-langgraph==0.1.0",
                    "model-to-harness-shared==0.1.0",
                ],
                cwd=workspace,
                env=env,
                check=True,
            )
            subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-c",
                    WHEEL_CHECK,
                    str(installed),
                    json.dumps(
                        [
                            hashlib.sha256(path.read_bytes()).hexdigest()
                            for path in sorted((LANE / "backend/migrations").glob("*.sql"))
                        ]
                    ),
                ],
                cwd=workspace,
                env=env,
                check=True,
            )


if __name__ == "__main__":
    main()
