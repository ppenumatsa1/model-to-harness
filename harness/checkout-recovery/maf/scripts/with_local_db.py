"""Run an explicit command against this harness's loopback Compose database."""

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    command = sys.argv[1:]
    if command[:1] == ["--"]:
        command = command[1:]
    if not command:
        raise SystemExit("Usage: python scripts/with_local_db.py -- COMMAND [ARG ...]")
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--project-directory",
            str(root),
            "--env-file",
            str(root / ".env.compose"),
            "-f",
            str(root / "compose.yaml"),
            "config",
            "--format",
            "json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise SystemExit("Cannot resolve local Compose settings; check .env.compose privately.")
    config = json.loads(result.stdout)
    service = config["services"]["postgres"]
    port = service["ports"][0]
    if (
        config["name"] != "checkout-recovery-maf"
        or port["host_ip"] != "127.0.0.1"
        or str(port["published"]) != "35432"
        or port["target"] != 5432
    ):
        raise SystemExit("Refusing a database outside this harness's loopback Compose contract.")
    values = service["environment"]
    if values["POSTGRES_PASSWORD"] == "replace-me":
        raise SystemExit("Generate a private password before using the local database.")
    url = (
        f"postgresql://{quote(values['POSTGRES_USER'], safe='')}:"
        f"{quote(values['POSTGRES_PASSWORD'], safe='')}@127.0.0.1:35432/"
        f"{quote(values['POSTGRES_DB'], safe='')}"
    )
    environment = {
        **os.environ,
        "DATABASE_URL": url,
        "CHECKOUT_RECOVERY_DATABASE_URL": url,
        "CHECKOUT_TEST_DATABASE_URL": url,
        "CHECKOUT_RECOVERY_EXECUTION_MODE": "scripted",
        "CHECKOUT_RECOVERY_ENVIRONMENT": "development",
        "APPLICATIONINSIGHTS_CONNECTION_STRING": "",
        "OTEL_EXPORTER_OTLP_ENDPOINT": "",
        "OTEL_SDK_DISABLED": "false",
        "OTEL_TRACES_EXPORTER": "none",
        "OTEL_METRICS_EXPORTER": "none",
        "OTEL_LOGS_EXPORTER": "none",
    }
    os.chdir(root)
    os.execvpe(command[0], command, environment)


if __name__ == "__main__":
    main()
