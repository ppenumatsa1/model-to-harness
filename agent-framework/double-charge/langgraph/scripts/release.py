"""Independent LangGraph release gates. Default execution is a read-only ARM preview."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from contextlib import contextmanager
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import unquote, urlsplit

LANE = Path(__file__).resolve().parents[1]
ROOT = LANE.parents[2]
SERVICE = "model-harness-langgraph"
SCHEMAS = ("langgraph_app_cutover", "langgraph_checkpoints_cutover")
SCHEMA_ENV = ("LANGGRAPH_SCHEMA", "LANGGRAPH_CHECKPOINT_SCHEMA")
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


class ReleaseError(RuntimeError):
    pass


def command_operation(command: list[str]) -> str:
    executable = Path(command[0]).name
    families = {
        "az": (
            ("deployment", "group", "show"),
            ("deployment", "group", "list"),
            ("deployment", "group", "what-if"),
            ("deployment", "group", "create"),
            ("containerapp", "show"),
            ("acr", "show"),
            ("acr", "build"),
            ("acr", "manifest", "show-metadata"),
            ("resource", "show"),
            ("cognitiveservices", "account", "deployment", "show"),
            ("postgres", "flexible-server", "show"),
        ),
        "azd": (
            ("env", "get-values"),
            ("ai", "agent", "show"),
            ("ai", "agent", "invoke"),
            ("ai", "agent", "session", "start"),
            ("ai", "agent", "session", "stop"),
        ),
    }
    for family in families.get(executable, ()):
        if command[1 : len(family) + 1] == list(family):
            return " ".join((executable, *family))
    return executable


def safe_cli_error_codes(*outputs: str) -> list[str]:
    allowed = {
        "AuthorizationFailed",
        "AuthenticationFailed",
        "DeploymentNotFound",
        "DeploymentFailed",
        "DeploymentWhatIfResourceError",
        "ServerStoppedError",
        "ResourceNotFound",
        "ResourceGroupNotFound",
        "SubscriptionNotFound",
        "InvalidApiVersionParameter",
        "InvalidResourceType",
        "InvalidResourceNamespace",
        "NoRegisteredProviderFound",
        "MissingSubscriptionRegistration",
        "InvalidTemplate",
        "InvalidTemplateDeployment",
        "PreflightValidationCheckFailed",
        "InvalidAuthenticationToken",
        "InvalidAuthenticationTokenTenant",
        "ExpiredAuthenticationToken",
        "RequestDisallowedByPolicy",
        "Conflict",
        "BadRequest",
        "InvalidRequest",
        "InternalServerError",
        "ServiceUnavailable",
    }
    codes: list[str] = []

    def collect(document: Any) -> None:
        if isinstance(document, dict):
            code = document.get("code")
            if isinstance(code, str) and code in allowed and code not in codes:
                codes.append(code)
            for key in ("error", "details", "innererror", "innerError"):
                collect(document.get(key))
        elif isinstance(document, list):
            for item in document:
                collect(item)

    for output in outputs:
        for line in output.splitlines():
            candidate = line.removeprefix("ERROR: ").strip()
            match = re.match(r"(?:\(([A-Za-z]+)\)|Code:\s*([A-Za-z]+)|([A-Za-z]+)\s+-)", candidate)
            if match:
                code = match[1] or match[2] or match[3]
                if code in allowed and code not in codes:
                    codes.append(code)
        candidate = output.strip().removeprefix("ERROR: ").strip()
        try:
            collect(json.loads(candidate))
        except json.JSONDecodeError:
            pass
        if "unrecognized arguments:" in output and "UnrecognizedArguments" not in codes:
            codes.append("UnrecognizedArguments")
    return codes


class Runner:
    """Cloud output may include secure parameters; report only the failed operation."""

    def run(
        self, command: list[str], *, cwd: Path = LANE, env: dict[str, str] | None = None
    ) -> str:
        if Path(command[0]).name == "azd":
            env = {**os.environ, **(env or {}), "AZURE_DEV_USER_AGENT": "microsoft_foundry_skill"}
        try:
            result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True)
        except OSError:
            raise ReleaseError(f"Cannot execute {command_operation(command)}") from None
        if result.returncode:
            if command_operation(command) == "az deployment group what-if":
                persist_arm_preview(
                    {
                        "operation": command_operation(command),
                        "returncode": result.returncode,
                        "stdout": result.stdout,
                        "stderr": result.stderr,
                    }
                )
            codes = safe_cli_error_codes(result.stdout, result.stderr)
            detail = f"; Azure/CLI codes: {', '.join(codes)}" if codes else ""
            if "ServerStoppedError" in codes:
                detail += "; explicitly start existing PostgreSQL after review before retrying"
            raise ReleaseError(
                f"{command_operation(command)} failed with exit {result.returncode}{detail}; "
                "output suppressed to protect configuration"
            )
        return result.stdout

    def json(self, command: list[str], **kwargs: Any) -> Any:
        content = self.run(command, **kwargs)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            if command_operation(command) == "az deployment group what-if":
                persist_arm_preview(
                    {
                        "operation": command_operation(command),
                        "error": "InvalidJsonOutput",
                        "stdout": content,
                    }
                )
            raise ReleaseError(f"{command_operation(command)} did not return valid JSON") from None


def azd_args(environment: str, *args: str) -> list[str]:
    if not environment.strip():
        raise ReleaseError("An explicit azd environment name is required")
    return ["azd", *args, "--environment", environment]


def environment_values(runner: Runner, environment: str) -> dict[str, str]:
    values = runner.json(
        azd_args(environment, "env", "get-values", "--output", "json"),
    )
    if not isinstance(values, dict) or not all(
        isinstance(key, str) and isinstance(value, str) for key, value in values.items()
    ):
        raise ReleaseError("azd environment must contain string configuration values")
    return values


def active_agent(payload: dict[str, Any]) -> str:
    if not isinstance(payload, dict) or str(payload.get("status", "")).lower() not in {
        "active",
        "deployed",
    }:
        raise ReleaseError("Hosted agent is not active or deployed")
    version = payload.get("version")
    alternate = payload.get("agent_version")
    if version is not None and alternate is not None and str(version) != str(alternate):
        raise ReleaseError("Hosted status contains conflicting version identifiers")
    value = version if version is not None else alternate
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not str(value).strip():
        raise ReleaseError("Hosted status lacks an immutable version identifier")
    return str(value)


def postgres_preflight(state: str, *, apply: bool) -> str:
    normalized = state.lower()
    if normalized not in {"ready", "stopped"}:
        raise ReleaseError("PostgreSQL is in an unexpected state; resolve it before release")
    if normalized == "stopped" and apply:
        raise ReleaseError(
            "PostgreSQL is Stopped; explicitly start the existing server after review, "
            "then rerun release. No automatic start, SKU change, or retry was attempted"
        )
    return normalized


def required(values: dict[str, Any], key: str) -> Any:
    if key not in values or values[key] in (None, ""):
        raise ReleaseError(f"Required existing configuration missing: {key}")
    return values[key]


def validate_schemas(selected: tuple[str, str], current: tuple[str, str], update: bool) -> None:
    if selected[0] == selected[1]:
        raise ReleaseError("Application and checkpoint schemas must be distinct")
    for name in selected:
        if not re.fullmatch(r"langgraph_[a-z0-9_]{1,54}", name):
            raise ReleaseError(
                "Schemas must be LangGraph-owned SQL identifiers (max 63 characters)"
            )
        if name in {"langgraph_app", "langgraph_checkpoints"}:
            raise ReleaseError("Legacy schemas are not cutover targets")
    if update and selected != current:
        raise ReleaseError("Update-existing must verify the deployed schema pair without migration")
    if not update and set(selected) & set(current):
        raise ReleaseError("Fresh cutover requires two distinct new schemas")


def immutable_image(image: str, registry: str, repository: str) -> str:
    prefix = f"{registry}/{repository}@"
    if not image.startswith(prefix) or not DIGEST.fullmatch(image[len(prefix) :]):
        raise ReleaseError("Expected an immutable digest in the selected lane registry/repository")
    return image


def verify_code_archive(root: Path, content: bytes, expected_hash: str) -> str:
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected_hash.removeprefix("sha256:"):
        raise ReleaseError("Hosted archive hash does not match the authoritative version")
    manifest = json.loads((root / "SOURCE_MANIFEST.json").read_text())
    expected = {*manifest, "SOURCE_MANIFEST.json"}
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        names = [item.filename for item in archive.infolist() if not item.is_dir()]
        if len(names) != len(set(names)) or set(names) - {".agentignore"} != expected:
            raise ReleaseError("Hosted archive contains missing, duplicate, or unexpected files")
        for name in names:
            path = PurePosixPath(name)
            if path.is_absolute() or ".." in path.parts or "\\" in name:
                raise ReleaseError("Hosted archive contains an unsafe path")
            if archive.read(name) != (root / name).read_bytes():
                raise ReleaseError("Hosted archive differs from the prepared source")
        for name, value in manifest.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != value:
                raise ReleaseError("Hosted source manifest does not match archive content")
    return digest


def verify_hosted_environment(actual: dict[str, str], expected: dict[str, str]) -> None:
    if "APPLICATIONINSIGHTS_CONNECTION_STRING" in actual:
        raise ReleaseError("Hosted environment must not override platform-reserved App Insights")
    if not expected or actual != expected:
        raise ReleaseError("Hosted environment differs from the selected release")


@contextmanager
def private_parameters(parameters: dict[str, Any]):
    with tempfile.TemporaryDirectory(prefix="langgraph-arm-") as directory:
        path = Path(directory) / "parameters.json"
        with open(path, "x", opener=lambda name, flags: os.open(name, flags, 0o600)) as handle:
            json.dump(
                {
                    "$schema": "https://schema.management.azure.com/schemas/"
                    "2019-04-01/deploymentParameters.json#",
                    "contentVersion": "1.0.0.0",
                    "parameters": {key: {"value": value} for key, value in parameters.items()},
                },
                handle,
            )
        yield path


def persist_arm_preview(result: dict[str, Any]) -> Path:
    azure = LANE / ".azure"
    directory = azure / "release"
    if azure.is_symlink() or directory.is_symlink():
        raise ReleaseError("Private ARM evidence directory must not be a symbolic link")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.chmod(0o700)
    descriptor, name = tempfile.mkstemp(
        prefix=f"arm-what-if-{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-",
        suffix=".json",
        dir=directory,
    )
    path = Path(name)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o600)
        json.dump(result, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    kinds = {"Create", "Delete", "Deploy", "Modify", "NoChange", "Ignore", "Unsupported"}
    summaries = []
    changes = result.get("changes")
    for change in changes if isinstance(changes, list) else []:
        if not isinstance(change, dict):
            summaries.append({"resource_id": "[unavailable]", "change_type": "Unknown"})
            continue
        resource_id = change.get("resourceId")
        safe_id = isinstance(resource_id, str) and re.fullmatch(
            r"/subscriptions/[0-9a-fA-F-]+/resourceGroups/[A-Za-z0-9_.()-]+/"
            r"providers/[A-Za-z0-9_ ./()-]+",
            resource_id,
        )
        kind = change.get("changeType")
        summaries.append(
            {
                "resource_id": resource_id if safe_id else "[unavailable]",
                "change_type": kind if isinstance(kind, str) and kind in kinds else "Unknown",
            }
        )
    print(
        json.dumps(
            {
                "arm_preview_artifact": str(path),
                "succeeded": result.get("status") == "Succeeded" and not result.get("error"),
                "resource_changes": summaries,
            }
        )
    )
    return path


def stage_sources(destination: Path, runner: Runner) -> dict[str, str]:
    """A positive build allowlist, not a broad repository copy plus fragile exclusions."""
    lane_prefix = LANE.relative_to(ROOT).as_posix()
    selected = runner.run(
        ["git", "ls-files", "-z", "--", "LICENSE", "shared", lane_prefix], cwd=ROOT
    ).split("\0")
    files: dict[str, str] = {}
    lane_files = {"pyproject.toml", "uv.lock", "README.md"}
    for name in selected:
        if not name:
            continue
        path = PurePosixPath(name)
        if any(part.startswith(".") for part in path.parts):
            continue
        if any(part in {"__pycache__", "node_modules", "dist", "results"} for part in path.parts):
            continue
        allowed = name == "LICENSE"
        if name.startswith("shared/"):
            relative = name.removeprefix("shared/")
            allowed = relative in {"pyproject.toml", "README.md"} or (
                relative.startswith("src/") and path.suffix in {".py", ".typed"}
            )
        if name.startswith(lane_prefix + "/"):
            relative = name.removeprefix(lane_prefix + "/")
            allowed = (
                relative in lane_files
                or (relative.startswith("backend/src/") and path.suffix in {".py", ".typed"})
                or (relative.startswith("backend/migrations/") and path.suffix == ".sql")
                or (
                    relative.startswith("frontend/src/")
                    and path.suffix in {".ts", ".tsx", ".js", ".jsx", ".css", ".json", ".svg"}
                )
                or relative
                in {
                    "frontend/package.json",
                    "frontend/package-lock.json",
                    "frontend/index.html",
                    "frontend/tsconfig.json",
                    "frontend/tsconfig.node.json",
                    "frontend/tsconfig.app.json",
                    "frontend/vite.config.ts",
                    "infra/container/Dockerfile",
                    "infra/app/frontend.Dockerfile",
                    "infra/app/nginx.conf.template",
                    "infra/foundry-hosted/agent/requirements.txt",
                }
            )
        if not allowed:
            continue
        source = ROOT / name
        if source.is_symlink() or not source.is_file():
            raise ReleaseError("Build inputs must be regular tracked files")
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        files[name] = hashlib.sha256(target.read_bytes()).hexdigest()
    if not files:
        raise ReleaseError("Build staging is empty")
    return files


def delta_leaves(deltas: list[dict[str, Any]], prefix: str = ""):
    for delta in deltas:
        if not isinstance(delta, dict):
            raise ReleaseError("ARM delta is malformed")
        part = delta.get("path")
        if not isinstance(part, str) or not part:
            raise ReleaseError("ARM delta has no property path")
        path = (
            f"{prefix}[{part}]"
            if prefix and part.isdecimal()
            else (f"{prefix}.{part}" if prefix else part)
        )
        children = delta.get("children")
        if children is not None and not isinstance(children, list):
            raise ReleaseError("ARM delta children are malformed")
        if children:
            yield from delta_leaves(children, path)
        else:
            yield path, delta


def app_reference_parameters(
    apps: dict[str, dict[str, Any]], registry_endpoint: str
) -> dict[str, str]:
    containers = {}
    for kind, app in apps.items():
        configuration = app["properties"]["configuration"]
        if configuration.get("activeRevisionsMode") != "Single" or (
            configuration["ingress"].get("traffic") != [{"latestRevision": True, "weight": 100}]
        ):
            raise ReleaseError("Release requires existing single-revision latest traffic")
        registries = configuration.get("registries", [])
        identities = app.get("identity", {}).get("userAssignedIdentities", {})
        if (
            len(registries) != 1
            or registries[0].get("server") != registry_endpoint
            or str(registries[0].get("identity", "")).lower()
            not in {identity.lower() for identity in identities}
        ):
            raise ReleaseError("Container App registry/identity differs from discovered ACR")
        items = app["properties"]["template"]["containers"]
        if len(items) != 1:
            raise ReleaseError("Release requires one existing container per app")
        containers[kind] = {item["name"]: item.get("value") for item in items[0].get("env", [])}
    client_id = required(containers["backend"], "AZURE_CLIENT_ID")
    identities = apps["backend"]["identity"]["userAssignedIdentities"]
    if not any(identity.get("clientId") == client_id for identity in identities.values()):
        raise ReleaseError("Backend client ID is not its existing managed identity")
    backend_host = required(apps["backend"]["properties"]["configuration"]["ingress"], "fqdn")
    if containers["frontend"].get("BACKEND_HOST") != backend_host:
        raise ReleaseError("Frontend proxy does not target the discovered private backend")
    return {
        "registryEndpoint": registry_endpoint,
        "backendClientId": client_id,
        "backendHost": backend_host,
    }


def canonical_environment(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list) or any(not isinstance(item, dict) for item in items):
        raise ReleaseError("Container environment must be an array of objects")
    # ARM omits empty values, including CLI-added empty values beside secretRef.
    return [
        {key: value for key, value in item.items() if key != "value" or value != ""}
        for item in items
    ]


def validate_what_if(
    result: dict[str, Any],
    app_ids: set[str],
    *,
    rollout: bool = False,
    expected: dict[str, dict[str, Any]] | None = None,
) -> None:
    if result.get("status") != "Succeeded" or result.get("error") or result.get("diagnostics"):
        raise ReleaseError("Full ARM what-if did not succeed")
    changes = result.get("changes")
    if not isinstance(changes, list) or not changes:
        raise ReleaseError("Full ARM what-if returned no resource evidence")
    seen_apps = set()
    for change in changes:
        resource = str(change.get("resourceId", "")).lower()
        kind = change.get("changeType")
        if not resource or change.get("unsupportedReason") or change.get("diagnostics"):
            raise ReleaseError("ARM what-if contains unevaluated resource evidence")
        if resource in app_ids:
            seen_apps.add(resource)
        if kind == "NoChange":
            if change.get("delta"):
                raise ReleaseError("NoChange resource contains contradictory property deltas")
            continue
        # FullResourcePayloads includes identical before/after for resources outside the template.
        # Never accept Ignore for a managed app: that can indicate unevaluated/short-circuited work.
        if (
            kind == "Ignore"
            and resource not in app_ids
            and not change.get("delta")
            and isinstance(change.get("before"), dict)
            and change["before"] == change.get("after")
        ):
            continue
        if kind != "Modify" or resource not in app_ids:
            raise ReleaseError("Unapproved ARM change type; inspect the private preview artifact")
        if not isinstance(change.get("before"), dict) or not isinstance(change.get("after"), dict):
            raise ReleaseError("ARM what-if must include full before/after payloads")
        if rollout and (expected is None or resource not in expected):
            raise ReleaseError("Rollout requires exact desired runtime payloads")
        properties = change["after"].get("properties", {})
        containers = properties.get("template", {}).get("containers", [])
        if len(containers) != 1:
            raise ReleaseError("ARM proposed an unexpected container topology")
        actual = containers[0]
        wanted = expected[resource] if rollout and expected is not None else {}
        if rollout and any(
            (
                canonical_environment(actual.get(key)) != canonical_environment(value)
                if key == "env"
                else actual.get(key) != value
            )
            for key, value in wanted.items()
        ):
            raise ReleaseError("ARM runtime payload differs from the reviewed image/environment")
        deltas = change.get("delta")
        if not isinstance(deltas, list) or not deltas:
            raise ReleaseError("Modified resource lacks property-level evidence")
        for path, delta in delta_leaves(deltas):
            before = change["before"].get("properties", {})
            # Evidence-backed service fields only; do not normalize arbitrary deleted properties.
            if (
                path == "properties.runningStatus"
                and delta.get("propertyChangeType") == "Delete"
                and before.get("runningStatus") == "Running"
                and "runningStatus" not in properties
            ):
                continue
            if (
                path == "properties.configuration.ingress.exposedPort"
                and delta.get("propertyChangeType") == "Delete"
                and before.get("configuration", {}).get("ingress", {}).get("exposedPort") == 0
                and "exposedPort" not in properties.get("configuration", {}).get("ingress", {})
            ):
                continue
            if not rollout:
                raise ReleaseError("Baseline ARM preview contains meaningful app changes")
            allowed = bool(
                re.fullmatch(
                    r"properties\.template\.containers\[0\]\."
                    r"(image|probes(?:\[.*)?|env\[\d+\]\.value)",
                    path,
                )
            )
            if path == "properties.configuration.ingress.targetPort":
                allowed = bool(wanted.get("probes")) and (
                    properties.get("configuration", {}).get("ingress", {}).get("targetPort") == 8000
                )
            if not allowed:
                raise ReleaseError("ARM proposed changes outside approved runtime properties")
    if seen_apps != app_ids:
        raise ReleaseError("ARM what-if did not evaluate both lane Container Apps")


class Release:
    def __init__(self, args: argparse.Namespace, runner: Runner | None = None):
        self.args = args
        self.runner = runner or Runner()

    def az(self, *args: str) -> list[str]:
        return [
            "az",
            *args,
            "--subscription",
            self.subscription,
            "--only-show-errors",
            "-o",
            "json",
        ]

    def app(self, name: str) -> dict[str, Any]:
        return self.runner.json(self.az("containerapp", "show", "-g", self.group, "-n", name))

    def discover(self) -> None:
        self.values = environment_values(self.runner, self.args.environment)
        self.subscription = required(self.values, "AZURE_SUBSCRIPTION_ID")
        self.group = required(self.values, "AZURE_RESOURCE_GROUP")
        deployment = self.runner.json(
            self.az("deployment", "group", "show", "-g", self.group, "-n", self.args.deployment)
        )
        properties = deployment["properties"]
        if properties.get("provisioningState") != "Succeeded":
            raise ReleaseError("Existing deployment is not Succeeded")
        self.outputs = {
            key: value.get("value") for key, value in properties.get("outputs", {}).items()
        }
        previous = {
            key: value.get("value") for key, value in properties.get("parameters", {}).items()
        }
        self.apps = {
            kind: self.app(required(self.outputs, kind + "Name"))
            for kind in ("backend", "frontend")
        }
        self.app_ids = {app["id"].lower() for app in self.apps.values()}
        containers = {
            kind: app["properties"]["template"]["containers"][0] for kind, app in self.apps.items()
        }
        self.current_env = {
            item["name"]: item.get("value") for item in containers["backend"].get("env", [])
        }
        current = tuple(required(self.current_env, key) for key in SCHEMA_ENV)
        validate_schemas(self.args.schemas, current, self.args.update_existing)
        for kind, app in self.apps.items():
            ingress = app["properties"]["configuration"]["ingress"]
            if ingress.get("external") is not (kind == "frontend"):
                raise ReleaseError("Release requires private API and public same-origin frontend")
            if app["properties"].get("provisioningState", "").lower() != "succeeded":
                raise ReleaseError("Existing Container Apps must be healthy before release")
        self.registry = required(self.outputs, "registryName")
        registry = self.runner.json(self.az("acr", "show", "-n", self.registry))
        self.registry_server = required(registry, "loginServer")
        project_id = required(self.values, "AZURE_AI_PROJECT_ID")
        if project_id.lower() != str(required(self.outputs, "foundryProjectId")).lower():
            raise ReleaseError("azd project disagrees with the existing ARM deployment")
        match = re.fullmatch(
            r"/subscriptions/([^/]+)/resourceGroups/([^/]+)/providers/"
            r"Microsoft.CognitiveServices/accounts/([^/]+)/projects/([^/]+)",
            project_id,
            re.IGNORECASE,
        )
        if (
            not match
            or match[1].lower() != self.subscription.lower()
            or (match[2].lower() != self.group.lower())
        ):
            raise ReleaseError("Foundry project must belong to the selected subscription/group")
        self.runner.json(
            self.az("resource", "show", "--ids", project_id, "--api-version", "2025-06-01")
        )
        model = required(self.values, "AZURE_AI_MODEL_DEPLOYMENT_NAME")
        if model != required(self.outputs, "modelDeploymentName"):
            raise ReleaseError("Model deployment differs from the current lane")
        self.runner.json(
            self.az(
                "cognitiveservices",
                "account",
                "deployment",
                "show",
                "-g",
                self.group,
                "-n",
                match[3],
                "--deployment-name",
                model,
            )
        )
        endpoint = required(self.outputs, "foundryProjectEndpoint")
        for key in ("AZURE_AI_PROJECT_ENDPOINT", "FOUNDRY_PROJECT_ENDPOINT"):
            if self.values.get(key) and self.values[key].rstrip("/") != endpoint.rstrip("/"):
                raise ReleaseError("Foundry endpoint configuration disagrees")
        self.database_url = required(self.values, "DATABASE_URL")
        database = urlsplit(self.database_url)
        if (
            database.scheme not in {"postgres", "postgresql"}
            or database.hostname != required(self.outputs, "postgresHost")
            or unquote(database.path.lstrip("/")) != required(self.outputs, "postgresDatabaseName")
            or not database.username
            or not database.password
            or "sslmode=require" not in database.query
        ):
            raise ReleaseError("DATABASE_URL does not match the selected existing PostgreSQL")
        server_name = database.hostname.split(".")[0]
        server = self.runner.json(
            self.az("postgres", "flexible-server", "show", "-g", self.group, "-n", server_name)
        )
        self.postgres_state = postgres_preflight(
            str(server.get("state", "")), apply=self.args.apply
        )
        location = required(previous, "location")
        if location != required(self.values, "AZURE_LOCATION"):
            raise ReleaseError("Existing location disagrees with azd environment")
        self.parameters = {
            "location": location,
            "namePrefix": previous.get("namePrefix", "mth-lg"),
            "foundryAccountName": match[3],
            "foundryProjectName": match[4],
            "modelDeploymentName": model,
            "postgresAdministratorLogin": unquote(database.username),
            "postgresAdministratorPassword": unquote(database.password),
            "postgresDatabaseName": unquote(database.path.lstrip("/")),
            "postgresServerName": server_name,
            "tags": previous.get("tags", {}),
            "langgraphSchema": current[0],
            "langgraphCheckpointSchema": current[1],
            "backendImage": required(containers["backend"], "image"),
            "frontendImage": required(containers["frontend"], "image"),
            "backendTargetPort": self.apps["backend"]["properties"]["configuration"]["ingress"][
                "targetPort"
            ],
            "enableBackendProbes": bool(containers["backend"].get("probes")),
        }
        self.parameters.update(app_reference_parameters(self.apps, self.registry_server))
        if any("helloworld" in self.parameters[key] for key in ("backendImage", "frontendImage")):
            raise ReleaseError("Cannot cut over from placeholder app images")
        configured = self.values.get("POSTGRES_ADMINISTRATOR_PASSWORD")
        if configured and configured != self.parameters["postgresAdministratorPassword"]:
            raise ReleaseError("Conflicting PostgreSQL passwords; refusing credential rotation")

    def arm(self, parameters: dict[str, Any], *, preview: bool) -> dict[str, Any]:
        with private_parameters(parameters) as path:
            command = self.az(
                "deployment",
                "group",
                "what-if" if preview else "create",
                "-g",
                self.group,
                "-n",
                self.args.deployment,
                "--template-file",
                str(LANE / "infra/main.bicep"),
                "--parameters",
                f"@{path}",
            )
            if preview:
                command.extend(["--result-format", "FullResourcePayloads", "--no-pretty-print"])
            result = self.runner.json(command)
        if preview:
            persist_arm_preview(result)
        if not preview and result.get("properties", {}).get("provisioningState") != "Succeeded":
            raise ReleaseError("ARM rollout did not finish Succeeded")
        return result

    def source(self) -> str:
        commit = self.runner.run(["git", "rev-parse", "HEAD"], cwd=ROOT).strip()
        if not re.fullmatch(r"[a-f0-9]{40}", commit):
            raise ReleaseError("Source HEAD must resolve to a full commit")
        dirty = self.runner.run(
            [
                "git",
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--",
                "LICENSE",
                "shared",
                LANE.relative_to(ROOT).as_posix(),
            ],
            cwd=ROOT,
        ).strip()
        if dirty and self.args.apply:
            raise ReleaseError("Apply requires clean, validated lane and shared source")
        return commit

    def build(self, commit: str) -> dict[str, str]:
        with tempfile.TemporaryDirectory(prefix="langgraph-build-") as directory:
            stage = Path(directory)
            manifest = stage_sources(stage, self.runner)
            if self.source() != commit:
                raise ReleaseError("Source changed during build staging; refusing image build")
            fingerprint = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
            images = {}
            for kind, dockerfile in (
                ("backend", "infra/container/Dockerfile"),
                ("frontend", "infra/app/frontend.Dockerfile"),
            ):
                repository = f"{SERVICE}-{kind}"
                tag = f"{commit[:12]}-{fingerprint[:16]}"
                result = self.runner.json(
                    self.az(
                        "acr",
                        "build",
                        "--registry",
                        self.registry,
                        "--image",
                        f"{repository}:{tag}",
                        "--file",
                        str(stage / LANE.relative_to(ROOT) / dockerfile),
                        str(stage),
                        "--build-arg",
                        f"SOURCE_COMMIT={commit}",
                        "--build-arg",
                        f"SOURCE_SHA256={fingerprint}",
                        "--no-logs",
                    )
                )
                if result.get("status") != "Succeeded":
                    raise ReleaseError("ACR build did not finish Succeeded")
                outputs = result.get("outputImages", [])
                candidates = [
                    item
                    for item in outputs
                    if item.get("repository") == repository and item.get("tag") == tag
                ]
                if len(candidates) != 1:
                    raise ReleaseError("ACR build did not return exactly one expected image")
                digest = required(candidates[0], "digest")
                image = f"{self.registry_server}/{repository}@{digest}"
                images[kind + "Image"] = immutable_image(image, self.registry_server, repository)
                manifest_info = self.runner.json(
                    self.az(
                        "acr",
                        "manifest",
                        "show-metadata",
                        "--registry",
                        self.registry,
                        "--name",
                        f"{repository}@{digest}",
                    )
                )
                if manifest_info.get("digest") != digest:
                    raise ReleaseError("Registry digest differs from successful ACR build output")
            print(
                json.dumps({"source_commit": commit, "build_source_sha256": fingerprint, **images})
            )
            return images

    def setup(self) -> None:
        env = {**os.environ, "DATABASE_URL": self.database_url}
        env.update(dict(zip(SCHEMA_ENV, self.args.schemas, strict=True)))
        command = [sys.executable, "scripts/setup_db.py"]
        if self.args.update_existing:
            self.runner.run([*command, "--verify-only"], env=env)
            return

        from psycopg import AsyncConnection, Error

        async def apply_fresh() -> None:
            async with await AsyncConnection.connect(
                self.database_url,
                connect_timeout=15,
                autocommit=True,
                options="-c default_transaction_read_only=on",
            ) as connection:
                # Hold session locks across the separately owned application/native setup command.
                for schema in sorted(self.args.schemas):
                    result = await connection.execute(
                        "SELECT pg_try_advisory_lock(hashtextextended(%s, 0))",
                        (f"langgraph:release:{schema}",),
                    )
                    row = await result.fetchone()
                    if row is None or row[0] is not True:
                        raise ReleaseError("Another release owns a selected schema; no retry")
                result = await connection.execute(
                    "SELECT nspname FROM pg_namespace WHERE nspname = ANY(%s)",
                    (list(self.args.schemas),),
                )
                if await result.fetchall():
                    raise ReleaseError("Fresh release requires BOTH schema namespaces to be absent")
                self.runner.run([*command, "--require-fresh"], env=env)

        try:
            asyncio.run(apply_fresh())
        except Error:
            raise ReleaseError(
                "Fresh schema preflight/setup failed; database details suppressed"
            ) from None

    def verify_rollout(self, desired: dict[str, Any]) -> None:
        deadline = time.monotonic() + self.args.timeout
        while time.monotonic() < deadline:
            ready = True
            for kind in ("backend", "frontend"):
                app = self.app(self.outputs[kind + "Name"])
                properties = app["properties"]
                if str(properties.get("provisioningState", "")).lower() in {
                    "failed",
                    "canceled",
                    "cancelled",
                }:
                    raise ReleaseError("Container App rollout failed")
                ready &= (
                    properties.get("runningStatus") == "Running"
                    and properties.get("latestRevisionName") is not None
                    and properties.get("latestReadyRevisionName")
                    == properties["latestRevisionName"]
                    and properties["template"]["containers"][0]["image"] == desired[kind + "Image"]
                    and properties["configuration"]["ingress"]["external"] is (kind == "frontend")
                )
                if kind == "backend":
                    env = {
                        item["name"]: item.get("value")
                        for item in properties["template"]["containers"][0].get("env", [])
                    }
                    ready &= all(
                        env.get(key) == value
                        for key, value in zip(SCHEMA_ENV, self.args.schemas, strict=True)
                    )
            if ready:
                return
            time.sleep(5)
        raise ReleaseError("Timed out waiting for verified healthy Container App revisions")

    def execute(self) -> None:
        self.discover()
        commit = self.source()
        baseline = self.arm(self.parameters, preview=True)
        validate_what_if(baseline, self.app_ids)
        if self.args.update_existing:
            if self.postgres_state != "ready":
                raise ReleaseError(
                    "ARM preview succeeded, but existing-schema verification is blocked by "
                    "Stopped PostgreSQL; explicitly start the server after review"
                )
            self.setup()
        if not self.args.apply:
            print(
                json.dumps(
                    {
                        "gate": "discovery-and-baseline-what-if",
                        "mutation": False,
                        "source_commit": commit,
                        "schemas": self.args.schemas,
                        "postgres_state": self.postgres_state,
                        "required_before_apply": (
                            "explicitly start existing PostgreSQL after review"
                            if self.postgres_state == "stopped"
                            else None
                        ),
                    }
                )
            )
            return
        images = self.build(commit)
        desired = {
            **self.parameters,
            **images,
            "langgraphSchema": self.args.schemas[0],
            "langgraphCheckpointSchema": self.args.schemas[1],
            "backendTargetPort": 8000,
            "enableBackendProbes": True,
        }
        expected = {}
        for kind, app in self.apps.items():
            container = app["properties"]["template"]["containers"][0]
            environment = [dict(item) for item in container.get("env", [])]
            if kind == "backend":
                for item in environment:
                    if item["name"] in SCHEMA_ENV:
                        item["value"] = self.args.schemas[SCHEMA_ENV.index(item["name"])]
            expected[app["id"].lower()] = {"image": images[kind + "Image"], "env": environment}
            if kind == "backend":
                expected[app["id"].lower()]["probes"] = [
                    {
                        "type": probe,
                        "httpGet": {"path": path, "port": 8000},
                        "initialDelaySeconds": delay,
                        "periodSeconds": delay,
                    }
                    for probe, path, delay in (
                        ("Liveness", "/health", 30),
                        ("Readiness", "/ready", 15),
                    )
                ]
        validate_what_if(
            self.arm(desired, preview=True), self.app_ids, rollout=True, expected=expected
        )
        if self.source() != commit:
            raise ReleaseError("Source changed after build; refusing rollout")
        if not self.args.update_existing:
            self.setup()
        self.arm(desired, preview=False)
        self.verify_rollout(desired)
        print(
            json.dumps(
                {
                    "gate": "app-rollout-verified",
                    "schemas": self.args.schemas,
                    "hosted_deployment": "separate explicit transport command required",
                }
            )
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", default=os.environ.get("AZURE_ENV_NAME") or "langgraph")
    parser.add_argument("--deployment", default=SERVICE)
    parser.add_argument("--schema", default=SCHEMAS[0])
    parser.add_argument("--checkpoint-schema", default=SCHEMAS[1])
    parser.add_argument("--update-existing", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--timeout", type=int, default=600)
    args = parser.parse_args()
    args.schemas = (args.schema, args.checkpoint_schema)
    try:
        Release(args).execute()
    except (ReleaseError, KeyError, TypeError, ValueError, OSError) as exc:
        message = str(exc) if isinstance(exc, ReleaseError) else type(exc).__name__
        parser.exit(1, f"Release blocked: {message}\n")


if __name__ == "__main__":
    main()
