"""Create a pinned eval group and private MCP request; never start an evaluation run."""

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
from release import LANE, SERVICE, ReleaseError, Runner, active_agent, azd_args

AGENT_ROOT = LANE / "infra/foundry-hosted/agent"
ARTIFACT_ROOT = LANE / ".azure/release"
PINS = {"builtin.task_completion": "19", "builtin.relevance": "12"}
MAPPINGS = {
    "query": "{{item.query}}",
    "response": "{{sample.output_items}}",
    "tool_calls": "{{sample.tool_calls}}",
    "tool_definitions": "{{sample.tool_definitions}}",
}
CASE_CONTRACTS = {
    "maf-no-duplicate": ("no-duplicate", "completed_no_refund", None),
    "maf-no-duplicate-rephrased": ("no-duplicate", "completed_no_refund", None),
    "maf-explicit-approval-pause": ("duplicate-confirmed", "waiting_approval", "paused"),
    "maf-bounded-read-failure": ("transient-failure", "failed", "failed"),
}


class SetupError(ValueError):
    """A safe validation message that contains no dataset or credential values."""


def selected_endpoint(values: Any, environment: str, version: str) -> str:
    if not isinstance(values, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in values.items()
    ):
        raise SetupError("The selected azd environment must be a JSON object of strings")
    if values.get("AZURE_ENV_NAME", environment) != environment:
        raise SetupError("azd returned a different environment")
    if values.get("AGENT_MODEL_HARNESS_MAF_NAME") != SERVICE:
        raise SetupError("The selected environment must identify the MAF hosted agent")
    if values.get("AGENT_MODEL_HARNESS_MAF_VERSION") != version:
        raise SetupError("The requested version must match the selected azd deployment")
    endpoints = {
        values[key].rstrip("/")
        for key in (
            "FOUNDRY_PROJECT_ENDPOINT",
            "AZURE_AI_PROJECT_ENDPOINT",
            "AZURE_AIPROJECT_ENDPOINT",
        )
        if values.get(key)
    }
    if len(endpoints) != 1:
        raise SetupError("The selected environment needs one unambiguous Foundry project endpoint")
    endpoint = endpoints.pop()
    try:
        parsed = urlsplit(endpoint)
        port = parsed.port
    except ValueError:
        raise SetupError("The selected project endpoint is malformed") from None
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
        raise SetupError("A public Azure Foundry project HTTPS endpoint is required")
    return endpoint


def load_intent(config_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        raise SetupError("Could not read the evaluation YAML; details suppressed") from None
    if not isinstance(config, dict) or set(config) - {
        "name",
        "agent",
        "dataset",
        "evaluators",
        "options",
        "max_samples",
    }:
        raise SetupError("Unsupported evaluation configuration fields")
    if not isinstance(config.get("name"), str) or not re.fullmatch(
        r"[A-Za-z0-9_-]{1,80}", config["name"]
    ):
        raise SetupError("Evaluation names require 1-80 letters, digits, underscores or hyphens")
    agent = config.get("agent")
    if (
        not isinstance(agent, dict)
        or agent.get("name") != SERVICE
        or set(agent) - {"name", "version"}
    ):
        raise SetupError("Evaluation intent must target only the MAF hosted agent")
    evaluators = config.get("evaluators")
    if not isinstance(evaluators, list) or len(evaluators) != len(PINS):
        raise SetupError("Both reviewed evaluators must be explicitly version-pinned")
    pins = {}
    for evaluator in evaluators:
        if not isinstance(evaluator, dict) or set(evaluator) != {"name", "version"}:
            raise SetupError("Evaluator entries accept only name and version, without overrides")
        name, version = evaluator["name"], evaluator["version"]
        if not isinstance(name, str) or name not in PINS or name in pins or PINS[name] != version:
            raise SetupError("Evaluator names and versions must match the reviewed pins")
        pins[name] = version
    options = config.get("options")
    if (
        not isinstance(options, dict)
        or set(options) != {"eval_model"}
        or not isinstance(options["eval_model"], str)
        or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", options["eval_model"])
    ):
        raise SetupError("options.eval_model must identify the existing judge deployment")
    if config.get("max_samples", 4) != 4:
        raise SetupError("The acceptance suite must retain all four reviewed cases")
    dataset = config.get("dataset")
    if (
        not isinstance(dataset, dict)
        or set(dataset) != {"local_uri"}
        or not isinstance(dataset["local_uri"], str)
    ):
        raise SetupError("The reviewed local dataset is required")
    source = (AGENT_ROOT / dataset["local_uri"]).resolve()
    if not source.is_relative_to(AGENT_ROOT.resolve()):
        raise SetupError("The dataset must remain inside the selected hosted agent root")
    try:
        rows = [
            json.loads(line)
            for line in source.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, json.JSONDecodeError):
        raise SetupError("Could not read the reviewed JSONL dataset; details suppressed") from None
    validate_cases(rows)
    return config, rows


def validate_cases(rows: list[Any]) -> None:
    if len(rows) != len(CASE_CONTRACTS):
        raise SetupError("The acceptance suite must contain exactly the four reviewed cases")
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise SetupError("Each evaluation case needs its reviewed identifier")
        identifier = row["id"]
        if identifier not in CASE_CONTRACTS or identifier in seen:
            raise SetupError("Evaluation case identifiers must match the reviewed suite exactly")
        seen.add(identifier)
        scenario, terminal, status = CASE_CONTRACTS[identifier]
        try:
            command = json.loads(row["query"])
        except (KeyError, TypeError, json.JSONDecodeError):
            raise SetupError("Each query must encode an explicit start command") from None
        if (
            not isinstance(command, dict)
            or command.get("action") != "start"
            or command.get("scenario_id") != scenario
            or set(command)
            - {
                "action",
                "scenario_id",
                "complaint",
                "customer_id",
                "existing_case_id",
                "idempotency_key",
            }
            or not all(
                isinstance(command.get(key), str) and command[key].strip()
                for key in ("complaint", "customer_id")
            )
            or not isinstance(row.get("ground_truth"), str)
            or not row["ground_truth"].strip()
            or row.get("expected_terminal_status") != terminal
            or row.get("expected_refund_status") != "not_requested"
            or row.get("expected_status") != status
            or (
                identifier == "maf-explicit-approval-pause"
                and row.get("expected_approval_required") is not True
            )
        ):
            raise SetupError("A reviewed scenario or its expected outcome was changed")


def unique_cases(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for row in rows:
        command = json.loads(row["query"])
        command["existing_case_id"] = f"maf-eval-case-{uuid4().hex}"
        command["idempotency_key"] = f"maf-eval-command-{uuid4().hex}"
        result.append({**row, "query": json.dumps(command)})
    return result


def group_definition(config: dict[str, Any], name: str) -> dict[str, Any]:
    model = config["options"]["eval_model"]
    return {
        "name": name,
        # Match the proven cloud group's permissive source schema; validate rows locally.
        "data_source_config": {
            "type": "custom",
            "item_schema": {},
            "include_sample_schema": True,
        },
        "testing_criteria": [
            {
                "type": "azure_ai_evaluator",
                "name": evaluator.removeprefix("builtin."),
                "evaluator_name": evaluator,
                "evaluator_version": version,
                "initialization_parameters": {"deployment_name": model, "model": model},
                "data_mapping": dict(MAPPINGS),
            }
            for evaluator, version in PINS.items()
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


def prepare(environment: str, version: str, config_path: Path, runner: Runner) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", environment):
        raise SetupError("A valid selected azd environment is required")
    if not re.fullmatch(r"[1-9][0-9]*", version):
        raise SetupError("An explicit numeric deployed agent version is required")
    config, rows = load_intent(config_path)
    if config["agent"].get("version", version) != version:
        raise SetupError("The YAML agent version conflicts with the requested version")
    values = runner.json(
        azd_args(environment, "env", "get-values", "--output", "json"),
        cwd=AGENT_ROOT.parent,
    )
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
            raise SetupError("The requested version does not match the active hosted deployment")
        for name, pin in PINS.items():
            evaluator = project.beta.evaluators.get_version(name=name, version=pin).as_dict()
            if (
                evaluator.get("name") != name
                or evaluator.get("version") != pin
                or evaluator.get("evaluator_type") != "builtin"
                or "turn" not in evaluator.get("supported_evaluation_levels", [])
            ):
                raise SetupError("The catalog did not verify a requested turn-level evaluator pin")
        identifier = uuid4().hex
        name = f"{config['name']}-{environment}-v{version}-{identifier}"
        definition = group_definition(config, name)
        input_data = unique_cases(rows)
        directory = ARTIFACT_ROOT / f"hosted-eval-{identifier}"
        directory.mkdir(parents=True, mode=0o700)
        write_private_json(directory / "definition.json", definition)
        write_private_json(directory / "input-data.json", input_data)
        created = client.evals.create(**definition)
        if not isinstance(created.id, str) or not re.fullmatch(r"eval_[A-Za-z0-9_-]+", created.id):
            raise SetupError("Group creation returned no valid evaluation ID; do not blindly retry")
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
                f"Group {created.id} was created, but private artifact persistence failed. "
                "No run was started; inspect the setup directory before retrying."
            ) from None
    return {
        "evaluationId": created.id,
        "environment": environment,
        "agentVersion": version,
        "items": len(input_data),
        "request": str(output),
        "nextTool": "evaluation_agent_batch_eval_create",
        "runCreated": False,
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
        summary = prepare(args.environment, args.version, args.config, Runner())
    except SetupError as error:
        raise SystemExit(str(error)) from None
    except (AzureError, OpenAIError, OSError, ReleaseError) as error:
        raise SystemExit(
            f"Evaluation setup failed ({type(error).__name__}); private details suppressed. "
            "No run was started. Inspect private artifacts before retrying group creation."
        ) from None
    print(json.dumps(summary))


if __name__ == "__main__":
    main()
