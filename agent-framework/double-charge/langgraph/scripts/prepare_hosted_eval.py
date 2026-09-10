"""Validate reviewed evaluation intent and create a fresh, pinned group, not a run."""

from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import yaml
from release import LANE, SERVICE, ReleaseError, Runner, active_agent, environment_values

AGENT_ROOT = LANE / "infra/foundry-hosted/agent"
PINS = {"builtin.task_completion": "19", "builtin.relevance": "12"}
CASE_CONTRACTS = {
    "langgraph-no-duplicate": ("no-duplicate", "completed_no_refund", None),
    "langgraph-no-duplicate-rephrased": ("no-duplicate", "completed_no_refund", None),
    "langgraph-explicit-approval-pause": ("duplicate-confirmed", None, "paused"),
    "langgraph-bounded-read-failure": ("transient-failure", "failed", "failed"),
}


class SetupError(ValueError):
    """A safe validation failure, without dataset or credential values."""


def selected_endpoint(values: Any, environment: str, version: str) -> str:
    if not isinstance(values, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in values.items()
    ):
        raise SetupError("Expected an azd environment object of strings")
    if (
        values.get("AZURE_ENV_NAME", environment) != environment
        or values.get("AGENT_MODEL_HARNESS_LANGGRAPH_NAME") != SERVICE
        or values.get("AGENT_MODEL_HARNESS_LANGGRAPH_VERSION") != version
    ):
        raise SetupError(
            "Requested environment, agent and version must match the selected deployment"
        )
    endpoints = {
        values[k].rstrip("/")
        for k in (
            "FOUNDRY_PROJECT_ENDPOINT",
            "AZURE_AI_PROJECT_ENDPOINT",
            "AZURE_AIPROJECT_ENDPOINT",
        )
        if values.get(k)
    }
    if len(endpoints) != 1:
        raise SetupError("An unambiguous selected project endpoint is required")
    endpoint = endpoints.pop()
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError:
        raise SetupError("Malformed project endpoint") from None
    if (
        parsed.scheme != "https"
        or not (parsed.hostname or "").endswith(".services.ai.azure.com")
        or parsed.username
        or parsed.password
        or port
        or parsed.query
        or parsed.fragment
        or not re.fullmatch(r"/api/projects/[A-Za-z0-9_-]+", parsed.path)
    ):
        raise SetupError("Expected a public Azure Foundry project HTTPS endpoint")
    return endpoint


def load_intent(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        config = yaml.safe_load(path.read_text())
    except (OSError, yaml.YAMLError):
        raise SetupError("Could not read evaluation YAML") from None
    if (
        not isinstance(config, dict)
        or set(config) != {"name", "agent", "dataset", "evaluators", "options", "max_samples"}
        or not isinstance(config["name"], str)
        or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,79}", config["name"])
        or config["agent"] != {"name": SERVICE}
        or config["max_samples"] != len(CASE_CONTRACTS)
        or config["evaluators"] != [{"name": k, "version": v} for k, v in PINS.items()]
        or not isinstance(config["options"], dict)
        or set(config["options"]) != {"eval_model"}
        or not isinstance(config["options"]["eval_model"], str)
        or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", config["options"]["eval_model"])
        or not isinstance(config["dataset"], dict)
        or set(config["dataset"]) != {"local_uri"}
        or not isinstance(config["dataset"]["local_uri"], str)
    ):
        raise SetupError("Evaluation intent differs from the reviewed four-case, pinned contract")
    source = (AGENT_ROOT / config["dataset"]["local_uri"]).resolve()
    if not source.is_relative_to(AGENT_ROOT.resolve()):
        raise SetupError("Dataset must remain inside the selected hosted agent root")
    try:
        rows = [json.loads(line) for line in source.read_text().splitlines() if line.strip()]
    except (OSError, ValueError):
        raise SetupError("Could not read reviewed JSONL cases") from None
    validate_cases(rows)
    return config, rows


def validate_cases(rows: list[Any]) -> None:
    if len(rows) != len(CASE_CONTRACTS):
        raise SetupError("All four reviewed cases are required")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise SetupError("Each case needs a reviewed identifier")
        identifier = row["id"]
        if identifier not in CASE_CONTRACTS or identifier in seen:
            raise SetupError("Unexpected or duplicate evaluation case")
        seen.add(identifier)
        scenario, terminal, status = CASE_CONTRACTS[identifier]
        try:
            command = json.loads(row["query"])
        except (KeyError, TypeError, ValueError):
            raise SetupError("Each query must encode a start command") from None
        if (
            not isinstance(command, dict)
            or command.get("action") != "start"
            or command.get("scenario_id") != scenario
            or set(command)
            - {"action", "scenario_id", "complaint", "customer_id", "case_id", "idempotency_key"}
            or not all(
                isinstance(command.get(k), str) and command[k].strip()
                for k in ("complaint", "customer_id")
            )
            or not isinstance(row.get("ground_truth"), str)
            or not row["ground_truth"].strip()
            or row.get("expected_terminal_status") != terminal
            or row.get("expected_refund_status")
            != (None if status == "paused" else "not_requested")
            or row.get("expected_status") != status
            or (status == "paused" and row.get("expected_approval_required") is not True)
        ):
            raise SetupError(
                "Evaluation scenario or expected outcome differs from reviewed contract"
            )


def unique_cases(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        command = json.loads(row["query"])
        command["case_id"] = f"langgraph-eval-{uuid4().hex}"
        command["idempotency_key"] = f"langgraph-eval-{uuid4().hex}"
        result.append({**row, "query": json.dumps(command)})
    return result


def group_definition(config: dict[str, Any], name: str) -> dict[str, Any]:
    model = config["options"]["eval_model"]
    return {
        "name": name,
        "data_source_config": {"type": "custom", "item_schema": {}, "include_sample_schema": True},
        "testing_criteria": [
            {
                "type": "azure_ai_evaluator",
                "name": key.removeprefix("builtin."),
                "evaluator_name": key,
                "evaluator_version": pin,
                "initialization_parameters": {"deployment_name": model, "model": model},
                "data_mapping": {
                    "query": "{{item.query}}",
                    "response": "{{sample.output_items}}",
                    "tool_calls": "{{sample.tool_calls}}",
                    "tool_definitions": "{{sample.tool_definitions}}",
                },
            }
            for key, pin in PINS.items()
        ],
    }


def write_private_json(path: Path, value: Any) -> None:
    staging = path.with_name(f".{path.name}-{uuid4().hex}")
    try:
        with open(
            staging,
            "x",
            encoding="utf-8",
            opener=lambda name, flags: os.open(name, flags, 0o600),
        ) as handle:
            json.dump(value, handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        staging.replace(path)
    finally:
        staging.unlink(missing_ok=True)


def prepare(environment: str, version: str, path: Path, runner: Runner) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", environment) or not re.fullmatch(
        r"[1-9]\d*", version
    ):
        raise SetupError("An explicit environment and numeric deployed version are required")
    config, rows = load_intent(path)
    values = environment_values(runner, environment)
    endpoint = selected_endpoint(values, environment, version)

    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    with (
        DefaultAzureCredential(process_timeout=60) as credential,
        AIProjectClient(
            endpoint=endpoint, credential=credential, allow_preview=True, retry_total=0
        ) as project,
        project.get_openai_client(max_retries=0, timeout=120) as client,
    ):
        deployed = project.agents.get_version(agent_name=SERVICE, agent_version=version).as_dict()
        if deployed.get("name") != SERVICE or active_agent(deployed) != version:
            raise SetupError("Selected agent version is not active")
        for name, pin in PINS.items():
            evaluator = project.beta.evaluators.get_version(name=name, version=pin).as_dict()
            if (
                evaluator.get("name") != name
                or evaluator.get("version") != pin
                or evaluator.get("evaluator_type") != "builtin"
                or "turn" not in evaluator.get("supported_evaluation_levels", [])
            ):
                raise SetupError("Catalog failed to verify a requested evaluator pin")
        identifier = uuid4().hex
        name = f"{config['name']}-{environment}-v{version}-{identifier}"
        definition, input_data = group_definition(config, name), unique_cases(rows)
        directory = LANE / ".azure/release" / f"hosted-eval-{identifier}"
        directory.mkdir(parents=True, mode=0o700)
        write_private_json(directory / "definition.json", definition)
        write_private_json(directory / "input-data.json", input_data)
        created = client.evals.create(**definition)
        if not isinstance(created.id, str) or not re.fullmatch(r"eval_[A-Za-z0-9_-]+", created.id):
            raise SetupError("Group creation returned no valid ID; do not blindly retry")
        request = {
            "projectEndpoint": endpoint,
            "agentName": SERVICE,
            "agentVersion": version,
            "evaluationName": name,
            "runName": name,
            "evaluatorNames": list(PINS),
            "deploymentName": config["options"]["eval_model"],
            "evaluationId": created.id,
            "inputData": input_data,
        }
        output = directory / "batch-request.json"
        try:
            write_private_json(directory / "group.json", {"evaluationId": created.id})
            write_private_json(output, request)
        except OSError:
            raise SetupError(
                f"Group {created.id} exists but artifact persistence failed; no run was started"
            ) from None
    return {
        "evaluationId": created.id,
        "environment": environment,
        "agentVersion": version,
        "items": len(input_data),
        "request": str(output),
        "runCreated": False,
        "nextTool": "evaluation_agent_batch_eval_create",
    }


def main() -> None:
    from azure.core.exceptions import AzureError
    from openai import OpenAIError

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--config", type=Path, default=AGENT_ROOT / "eval.yaml")
    args = parser.parse_args()
    try:
        print(json.dumps(prepare(args.environment, args.version, args.config, Runner())))
    except SetupError as error:
        raise SystemExit(str(error)) from None
    except (AzureError, OpenAIError, OSError, ReleaseError) as error:
        raise SystemExit(
            f"Evaluation setup failed ({type(error).__name__}); no run started. "
            "Inspect private artifacts before retrying group creation."
        ) from None


if __name__ == "__main__":
    main()
