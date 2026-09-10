"""Read-only verification of a downloaded, version-pinned hosted definition and code archive."""

from __future__ import annotations

import argparse
import json
import tempfile
import zipfile
from pathlib import Path

from prepare_hosted import prepare
from release import (
    LANE,
    SCHEMA_ENV,
    ReleaseError,
    validate_schemas,
    verify_code_archive,
    verify_hosted_code_configuration,
    verify_hosted_environment,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--definition", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--expected-environment", type=Path, required=True)
    parser.add_argument("--source", type=Path, default=LANE / "infra/foundry-hosted/agent")
    args = parser.parse_args()
    try:
        document = json.loads(args.definition.read_text())
        if str(document.get("version")) != args.version or document.get("status") != "active":
            raise ReleaseError("Hosted version is not the selected active immutable version")
        definition = document["definition"]
        configuration = definition["code_configuration"]
        verify_hosted_code_configuration(configuration)
        expected = json.loads(args.expected_environment.read_text())
        mandatory = {
            "APP_ENV",
            "DATABASE_URL",
            *SCHEMA_ENV,
            "AZURE_OPENAI_ENDPOINT",
            "AZURE_OPENAI_DEPLOYMENT",
            "OTEL_SERVICE_NAME",
            "OTEL_TRACES_SAMPLER",
            "OTEL_PYTHON_DISABLED_INSTRUMENTATIONS",
            "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT",
            "AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED",
            "AZURE_TRACING_ENABLED",
        }
        if not isinstance(expected, dict) or any(
            not isinstance(expected.get(key), str) or not expected[key] for key in mandatory
        ):
            raise ReleaseError("Expected environment must include the full production contract")
        if (
            expected["APP_ENV"] != "production"
            or expected["OTEL_TRACES_SAMPLER"] != "always_on"
            or expected["OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT"] != "false"
            or expected["AZURE_TRACING_GEN_AI_CONTENT_RECORDING_ENABLED"] != "false"
            or expected["OTEL_PYTHON_DISABLED_INSTRUMENTATIONS"] != "requests,urllib3,httpx"
            or expected["AZURE_TRACING_ENABLED"] != "false"
        ):
            raise ReleaseError("Expected hosted environment violates telemetry/production policy")
        schemas = tuple(expected[key] for key in SCHEMA_ENV)
        validate_schemas(schemas, schemas, True)
        verify_hosted_environment(definition["environment_variables"], expected)
        with tempfile.TemporaryDirectory(prefix="langgraph-verify-source-") as directory:
            fresh = prepare(Path(directory) / "agent")
            if json.loads((args.source / "SOURCE_MANIFEST.json").read_text()) != fresh:
                raise ReleaseError("Prepared hosted source is stale relative to the checkout")
        digest = verify_code_archive(
            args.source, args.archive.read_bytes(), configuration["content_hash"]
        )
    except (ReleaseError, KeyError, ValueError, TypeError, OSError, zipfile.BadZipFile) as exc:
        message = str(exc) if isinstance(exc, ReleaseError) else type(exc).__name__
        parser.exit(1, f"Hosted verification blocked: {message}\n")
    print(json.dumps({"verified_hosted_version": args.version, "archive_sha256": digest}))


if __name__ == "__main__":
    main()
