"""Exercise all fixtures over an owned loopback Responses 2.1 HTTP server, using real Copilot."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from dotenv import dotenv_values
from e2e import CONTRACT, verify_case
from prepare_hosted import AGENT_ROOT, LANE_ROOT
from verify_hosted import response_result

SETTINGS = (
    "CHECKOUT_COPILOT_DATABASE_URL",
    "CHECKOUT_COPILOT_FOUNDRY_PROJECT_ENDPOINT",
    "CHECKOUT_COPILOT_FOUNDRY_MODEL_DEPLOYMENT",
    "CHECKOUT_COPILOT_MAX_AUTO_INVENTORY_QUANTITY",
)


class LocalHostedError(RuntimeError):
    pass


def save(path: Path, value) -> None:
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")


def child_environment(directory: Path) -> dict[str, str]:
    values = dotenv_values(LANE_ROOT / ".env", interpolate=False)
    values.update({key: os.environ[key] for key in SETTINGS if key in os.environ})
    if any(not values.get(key) for key in SETTINGS[:3]):
        raise LocalHostedError(
            "Local Hosted requires the lane database, project and model settings"
        )
    database = urlsplit(values["CHECKOUT_COPILOT_DATABASE_URL"])
    if database.hostname != "127.0.0.1" or database.port != 45432:
        raise LocalHostedError("Local Hosted requires the lane-owned loopback PostgreSQL port")
    allowed = {
        "PATH",
        "HOME",
        "USER",
        "LOGNAME",
        "LANG",
        "LC_ALL",
        "AZURE_CONFIG_DIR",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "REQUESTS_CA_BUNDLE",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "NO_PROXY",
    }
    environment = {key: value for key, value in os.environ.items() if key in allowed}
    environment.update({key: values[key] for key in SETTINGS if values.get(key)})
    environment.update(
        {
            "PYTHONPATH": str(AGENT_ROOT),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
            "TMPDIR": str(directory),
            "AZURE_TOKEN_CREDENTIALS": "AzureCliCredential",
            "CHECKOUT_COPILOT_EXECUTION_MODE": "copilot",
            "CHECKOUT_COPILOT_ENVIRONMENT": "development",
            "CHECKOUT_COPILOT_STATE_DIRECTORY": str(directory / "private-native"),
            "CHECKOUT_COPILOT_TRACE_FIXTURE_CONTENT": "false",
            "CHECKOUT_COPILOT_TRACE_FILE": "",
            "COPILOT_CLI_EXTRACT_DIR": str(AGENT_ROOT / "copilot-runtime"),
            "COPILOT_SKIP_CLI_DOWNLOAD": "true",
            "ENABLE_SENSITIVE_DATA": "false",
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "false",
            "APPLICATIONINSIGHTS_CONNECTION_STRING": "",
            "OTEL_TRACES_EXPORTER": "none",
            "OTEL_METRICS_EXPORTER": "none",
            "OTEL_LOGS_EXPORTER": "none",
        }
    )
    return environment


def command_for(method: str, path: str, body: dict | None) -> dict:
    if method != "POST":
        raise LocalHostedError("Only explicit POST commands are supported")
    if path == "/api/cases" and body is not None:
        return {"action": "start", **body}
    parts = path.strip("/").split("/")
    if len(parts) != 4 or parts[:2] != ["api", "cases"]:
        raise LocalHostedError("Unsupported checkout command path")
    if parts[3] == "approval" and body is not None:
        return {"action": "approval", "case_id": parts[2], **body}
    if parts[3] == "resume" and body is None:
        return {"action": "resume", "case_id": parts[2]}
    raise LocalHostedError("Unsupported checkout command")


class ResponsesTransport:
    def __init__(self, client: httpx.Client, journal: dict, path: Path):
        self.client, self.journal, self.path = client, journal, path

    def __call__(self, base_url: str, method: str, path: str, body: dict | None = None) -> dict:
        command = command_for(method, path, body)
        record = {"command": command, "status": "submitting"}
        self.journal["commands"].append(record)
        save(self.path, self.journal)
        try:
            response = self.client.post(
                base_url + "/responses",
                json={"input": json.dumps(command), "stream": False, "store": False},
            )
            record.update(
                http_status=response.status_code,
                response_sha256=sha256(response.content).hexdigest(),
            )
            try:
                envelope = response.json()
            except ValueError:
                envelope = {}
            if isinstance(envelope, dict):
                record["response_status"] = envelope.get("status")
                record["response_id"] = envelope.get("id")
                if isinstance(envelope.get("error"), dict):
                    record["response_error"] = {
                        key: envelope["error"][key]
                        for key in ("code", "type")
                        if key in envelope["error"]
                    }
            if response.status_code != 200:
                raise LocalHostedError("Responses HTTP request failed")
            result = response_result(response.text)
            record.update(status="responded", result=result)
            return result
        except Exception as error:
            record.update(status="failed", error_type=type(error).__name__)
            raise LocalHostedError(
                "Local Responses command failed; inspect safe evidence"
            ) from None
        finally:
            save(self.path, self.journal)


async def serve(port: int) -> None:
    import main as hosted

    try:
        await hosted.create_host().run_async(host="127.0.0.1", port=port)
    finally:
        await hosted._close_runtime()


def wait_ready(process: subprocess.Popen, client: httpx.Client, base_url: str) -> None:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise LocalHostedError("Owned Hosted process exited before readiness")
        try:
            if client.get(base_url + "/readiness", timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise LocalHostedError("Owned Hosted process did not become ready")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=18088)
    parser.add_argument(
        "--output", type=Path, default=LANE_ROOT / ".acceptance/local-hosted/e2e.json"
    )
    parser.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.serve:
        asyncio.run(serve(args.port))
        return
    if not 1024 <= args.port <= 65535:
        raise LocalHostedError("Use an unprivileged loopback port")
    output = args.output.resolve()
    journal_path = output.with_name(output.stem + "-commands.json")
    if output.exists() or journal_path.exists():
        raise LocalHostedError("Acceptance evidence exists; reconcile before a new attempt")
    directory = output.parent
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    environment = child_environment(directory)
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", args.port))
    if not (AGENT_ROOT / "runtime-manifest.json").is_file():
        raise LocalHostedError(
            "Regenerate the canonical package with prepare_hosted.py --with-runtime"
        )
    journal = {
        "transport": "local-responses-http",
        "route": "/responses",
        "port": args.port,
        "commands": [],
    }
    rows = []
    base_url = f"http://127.0.0.1:{args.port}"
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--serve", "--port", str(args.port)],
        cwd=directory,
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    journal["pid"] = process.pid
    save(journal_path, journal)
    try:
        with httpx.Client(timeout=180, trust_env=False) as client:
            wait_ready(process, client, base_url)
            transport = ResponsesTransport(client, journal, journal_path)
            for fixture in json.loads(CONTRACT.read_text()):
                fixture["request_id"] = str(uuid4())
                row = {
                    "fixture_id": fixture["fixture_id"],
                    "request_id": fixture["request_id"],
                    "passed": False,
                }
                rows.append(row)
                save(output, rows)
                first_command = len(journal["commands"])
                try:
                    row.update(verify_case(base_url, fixture, request_fn=transport))
                    row["passed"] = row["actual"].get("harness_mode") == "copilot"
                except (Exception, SystemExit) as error:
                    row["error_type"] = type(error).__name__
                    replies = journal["commands"][first_command:]
                    actual = next(
                        (item["result"] for item in reversed(replies) if "result" in item), None
                    )
                    if actual is not None:
                        row["actual"] = actual
                save(output, rows)
    finally:
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10)
            journal["forced_shutdown"] = True
        journal["process_returncode"] = process.returncode
        journal["process_reaped"] = process.poll() is not None
        save(journal_path, journal)
    if len(rows) != 7 or not all(row["passed"] for row in rows):
        raise LocalHostedError(
            "Local Responses seven-fixture gate failed; retain original evidence"
        )
    if journal.get("forced_shutdown"):
        raise LocalHostedError("Owned Hosted process required forced shutdown")
    print("Local Responses HTTP: seven real-Copilot fixtures passed; owned process stopped")


if __name__ == "__main__":
    try:
        main()
    except (LocalHostedError, OSError):
        raise SystemExit("Local Hosted verification failed; inspect safe evidence") from None
