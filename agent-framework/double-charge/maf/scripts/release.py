"""Reviewed fresh cutover or existing-schema update. Preview is the default; never resets state."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import zipfile
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from uuid import uuid4

LANE = Path(__file__).resolve().parents[1]
ROOT = LANE.parents[2]
SERVICE = "model-harness-maf"
DEPLOYMENT = "model-harness-maf-app"
SCHEMA = "maf_double_charge_cutover"
RUNTIME_PARAMETERS = {"backendImage", "frontendImage", "backendTargetPort", "postgresSchema"}
APP_UPDATE_DEPLOYMENT = DEPLOYMENT + "-update"
APP_API_VERSION = "2025-07-01"
DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


class ReleaseError(RuntimeError):
    pass


class Runner:
    """Capture all subprocess output: neither credentials nor raw cloud errors are logged."""

    def run(self, args: list[str], *, cwd: Path = LANE, env: dict[str, str] | None = None) -> str:
        try:
            result = subprocess.run(
                args, cwd=cwd, env=env, text=True, capture_output=True, check=False
            )
        except OSError:
            raise ReleaseError(f"Could not execute {Path(args[0]).name}") from None
        if result.returncode:
            raise ReleaseError(
                f"{Path(args[0]).name} failed (exit {result.returncode}); "
                "output suppressed because it may contain credentials"
            )
        return result.stdout

    def json(self, args: list[str], **kwargs: Any) -> Any:
        try:
            return json.loads(self.run(args, **kwargs))
        except json.JSONDecodeError:
            raise ReleaseError("Command did not return valid JSON; output suppressed") from None


def azd_args(environment: str, *args: str) -> list[str]:
    return ["azd", *args, "--environment", environment]


def environment_values(runner: Runner, environment: str) -> dict[str, str]:
    values = runner.json(azd_args(environment, "env", "get-values", "--output", "json"))
    if not isinstance(values, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in values.items()
    ):
        raise ReleaseError("azd environment must be a JSON object of string values")
    return values


def required(values: dict[str, Any], key: str) -> Any:
    value = values.get(key)
    if value is None or value == "":
        raise ReleaseError(f"Missing required existing configuration: {key}")
    return value


def validate_schema(value: str, old: str, *, update_existing: bool = False) -> str:
    if not re.fullmatch(r"maf_[a-z0-9_]{1,59}", value):
        raise ReleaseError("Release requires a MAF-only schema, at most 63 characters")
    if update_existing:
        if value != old:
            raise ReleaseError("Existing-schema update must use the currently deployed API schema")
    elif value == old:
        raise ReleaseError("Fresh cutover requires a distinct schema; use --update-existing")
    return value


@contextmanager
def private_workspace(parent: Path):
    parent.mkdir(parents=True, exist_ok=True)
    directory = parent / uuid4().hex
    directory.mkdir(mode=0o700)
    try:
        yield directory
    finally:
        shutil.rmtree(directory)


@contextmanager
def parameter_file(parent: Path, parameters: dict[str, Any]):
    with private_workspace(parent) as directory:
        path = directory / "parameters.json"
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


def active_agent(document: dict[str, Any]) -> str:
    status = str(document.get("status", "")).lower()
    if status not in {"active", "deployed"}:
        raise ReleaseError(f"Hosted agent is not active (status {status or 'missing'})")
    version = document.get("version") or document.get("agent_version")
    if not version:
        raise ReleaseError("Hosted status lacks the actual deployed version")
    return str(version)


def verify_code_archive(root: Path, content: bytes, expected_hash: str) -> str:
    digest = hashlib.sha256(content).hexdigest()
    if digest != expected_hash.removeprefix("sha256:"):
        raise ReleaseError("Hosted archive does not match the service content hash")
    expected = [root / "main.py", root / "requirements.txt"]
    for package in ("maf_double_charge", "model_to_harness_shared"):
        directory = root / package
        if not directory.is_dir():
            raise ReleaseError("Prepared hosted package is missing")
        expected.extend(
            path
            for path in directory.rglob("*")
            if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc"
        )
    try:
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            if any(
                ".foundry" in Path(name).parts
                or any(part.startswith(".env") for part in Path(name).parts)
                for name in archive.namelist()
            ):
                raise ReleaseError("Hosted archive contains excluded configuration/cache files")
            files = [item.filename for item in archive.infolist() if not item.is_dir()]
            names = set(files)
            if len(names) != len(files):
                raise ReleaseError("Hosted archive contains duplicate file entries")
            expected_names = {path.relative_to(root).as_posix() for path in expected}
            if names - {".agentignore"} != expected_names:
                raise ReleaseError("Hosted archive file set differs from the prepared source")
            for path in expected:
                if archive.read(path.relative_to(root).as_posix()) != path.read_bytes():
                    raise ReleaseError("Hosted archive differs from the prepared source")
    except (KeyError, OSError, zipfile.BadZipFile):
        raise ReleaseError("Hosted archive or prepared source cannot be verified") from None
    return digest


def app_spec(resource: dict[str, Any], *, redact_secrets: bool = False) -> dict[str, Any]:
    """Keep writable state; remove only known service-owned readback fields."""
    value = deepcopy(resource)
    supported_fields = {
        "id", "name", "type", "apiVersion", "resourceGroup", "systemData",
        "location", "tags", "identity", "properties",
    }
    if any(val is not None for key, val in value.items() if key not in supported_fields):
        raise ReleaseError("App-only update encountered unsupported resource fields")
    properties = required(value, "properties")
    if properties.pop("delegatedIdentities", []) != []:
        raise ReleaseError("App-only update does not support delegated identities")
    readonly = {
        "provisioningState", "runningStatus", "latestRevisionName", "latestReadyRevisionName",
        "latestRevisionFqdn", "customDomainVerificationId", "outboundIpAddresses",
        "eventStreamEndpoint",
    }
    supported = {
        "configuration", "template", "managedEnvironmentId", "environmentId", "workloadProfileName",
    }
    if set(properties) - readonly - supported:
        raise ReleaseError("App-only update encountered unsupported application properties")
    for key in readonly:
        properties.pop(key, None)
    configuration = required(properties, "configuration")
    if configuration.get("identitySettings") == []:
        configuration.pop("identitySettings")
    ingress = required(configuration, "ingress")
    ingress.pop("fqdn", None)
    if ingress.get("exposedPort") == 0:
        ingress.pop("exposedPort")
    for registry in configuration.get("registries") or []:
        if registry.get("identity"):
            for key in ("username", "passwordSecretRef"):
                if registry.get(key) == "":
                    registry.pop(key)
    template = required(properties, "template")
    if template.get("revisionSuffix") == "":
        template.pop("revisionSuffix")
    for container in template.get("containers", []):
        container.get("resources", {}).pop("ephemeralStorage", None)
    identity = required(value, "identity")
    if identity.get("type") != "UserAssigned" or not identity.get("userAssignedIdentities"):
        raise ReleaseError("App-only update requires existing user-assigned identities")
    identity["userAssignedIdentities"] = {
        key: {} for key in identity["userAssignedIdentities"]
    }
    identity.pop("principalId", None)
    identity.pop("tenantId", None)
    if redact_secrets:
        for secret in configuration.get("secrets") or []:
            secret.pop("value", None)

    def without_nulls(item: Any) -> Any:
        if isinstance(item, dict):
            return {key: without_nulls(val) for key, val in item.items() if val is not None}
        if isinstance(item, list):
            return [without_nulls(val) for val in item]
        return item

    return without_nulls({
        "name": required(value, "name"),
        "location": required(value, "location").replace(" ", "").lower(),
        "tags": value.get("tags") or {},
        "identity": identity,
        "properties": properties,
    })


def app_only_what_if(
    result: dict[str, Any],
    baseline: dict[str, dict[str, Any]],
    desired: dict[str, dict[str, Any]],
) -> None:
    if (
        result.get("status") != "Succeeded" or result.get("error")
        or result.get("diagnostics") or not isinstance(result.get("changes"), list)
        or not result["changes"] or set(baseline) != set(desired) or len(baseline) != 2
    ):
        raise ReleaseError("App-only what-if lacks complete successful resource evidence")
    seen: set[str] = set()
    for change in result["changes"]:
        if not isinstance(change, dict):
            raise ReleaseError("App-only what-if contains malformed resource evidence")
        identifier = str(change.get("resourceId", "")).lower()
        if (
            not identifier or identifier in seen or change.get("error")
            or change.get("diagnostics") or change.get("unsupportedReason")
        ):
            raise ReleaseError("App-only what-if has duplicate or incomplete resource evidence")
        seen.add(identifier)
        kind = change.get("changeType")
        before, after = change.get("before"), change.get("after")
        delta = change.get("delta", [])
        if delta is None:
            delta = []
        if not isinstance(delta, list):
            raise ReleaseError("App-only what-if has malformed property evidence")
        if identifier not in baseline:
            if (
                kind not in {"Ignore", "NoChange"} or not isinstance(before, dict)
                or not before or before != after or delta
            ):
                raise ReleaseError(
                    "App-only what-if changes or cannot evaluate an unmanaged resource"
                )
            continue
        if (
            kind not in {"Modify", "NoChange"} or not isinstance(before, dict)
            or not isinstance(after, dict) or not before or not after
            or (kind == "NoChange" and (delta or before != after))
            or (kind == "Modify" and (not delta or before == after))
            or str(before.get("id", "")).lower() != identifier
            or str(after.get("id", "")).lower() != identifier
        ):
            raise ReleaseError("App-only what-if did not fully evaluate both existing apps")
        for entry in delta:
            if not isinstance(entry, dict) or entry.get("path") not in {
                "properties.template.containers", "properties.runningStatus",
                "properties.configuration.ingress.exposedPort",
            }:
                raise ReleaseError("App-only what-if contains a non-image configuration change")
        left, right = deepcopy(before), deepcopy(after)
        # ARM omits these two service defaults even when the HTTP app is unchanged.
        for parent, key, default in (
            ("properties", "runningStatus", "Running"),
            ("ingress", "exposedPort", 0),
        ):
            a, b = left["properties"], right["properties"]
            if parent == "ingress":
                a, b = a["configuration"]["ingress"], b["configuration"]["ingress"]
            if key in a and key not in b:
                if a[key] != default:
                    raise ReleaseError("App-only what-if omitted a nondefault runtime property")
                del a[key]
        current = baseline[identifier]
        expected = desired[identifier]
        before_spec = app_spec(before, redact_secrets=True)
        after_spec = app_spec(after, redact_secrets=True)
        if (
            before_spec != app_spec(current, redact_secrets=True)
            or after_spec != app_spec(expected, redact_secrets=True)
        ):
            raise ReleaseError("App-only what-if differs from verified source or desired app state")
        containers = left["properties"]["template"]["containers"]
        if len(containers) != 1:
            raise ReleaseError("App-only update requires one verified container per app")
        containers[0]["image"] = expected["properties"]["template"]["containers"][0]["image"]
        if left != right:
            raise ReleaseError("App-only what-if changed full resource state outside the image")
    if not set(baseline).issubset(seen):
        raise ReleaseError("App-only what-if omitted a managed application")


class Release:
    def __init__(self, args: argparse.Namespace, runner: Runner | None = None):
        self.args = args
        self.runner = runner or Runner()
        self.workspace = LANE / ".azure" / "release"

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
        if self.args.app_only:
            return self.runner.json(self.az(
                "rest", "--method", "get", "--url",
                f"https://management.azure.com/subscriptions/{self.subscription}"
                f"/resourceGroups/{self.group}/providers/Microsoft.App/containerApps/{name}"
                f"?api-version={APP_API_VERSION}",
            ))
        return self.runner.json(
            self.az("containerapp", "show", "--resource-group", self.group, "--name", name)
        )

    def discover(self) -> None:
        self.values = environment_values(self.runner, self.args.environment)
        self.subscription = required(self.values, "AZURE_SUBSCRIPTION_ID")
        self.group = required(self.values, "AZURE_RESOURCE_GROUP")
        self.location = required(self.values, "AZURE_LOCATION")
        self.deployment = self.runner.json(
            self.az("deployment", "group", "show", "-g", self.group, "-n", DEPLOYMENT)
        )
        properties = self.deployment["properties"]
        if properties.get("provisioningState") != "Succeeded":
            raise ReleaseError(
                "Existing app deployment is not Succeeded; resolve it before cutover"
            )
        self.previous = {
            key: value.get("value") for key, value in properties.get("parameters", {}).items()
        }
        self.outputs = {
            key: value.get("value") for key, value in properties.get("outputs", {}).items()
        }
        self.backend_name = required(self.outputs, "backendName")
        self.frontend_name = required(self.outputs, "frontendName")
        self.backend = self.app(self.backend_name)
        self.frontend = self.app(self.frontend_name)
        backend_container = self.backend["properties"]["template"]["containers"][0]
        frontend_container = self.frontend["properties"]["template"]["containers"][0]
        backend_env = {v["name"]: v.get("value") for v in backend_container.get("env", [])}
        old_schema = required(backend_env, "DATABASE_SCHEMA")
        self.schema = validate_schema(
            self.args.schema, old_schema, update_existing=self.args.update_existing
        )
        ingress = self.backend["properties"]["configuration"]["ingress"]
        if ingress.get("external") is not False:
            raise ReleaseError("Existing API must remain private; refusing an unexpected topology")
        self.registry_name = required(self.outputs, "registryName")
        registry = self.runner.json(self.az("acr", "show", "--name", self.registry_name))
        self.registry_server = required(registry, "loginServer")
        project_id = required(self.values, "AZURE_AI_PROJECT_ID")
        match = re.fullmatch(
            r"/subscriptions/([^/]+)/resourceGroups/([^/]+)/providers/"
            r"Microsoft.CognitiveServices/accounts/([^/]+)/projects/([^/]+)",
            project_id,
            flags=re.IGNORECASE,
        )
        if not match or match[1].lower() != self.subscription.lower() or match[2] != self.group:
            raise ReleaseError("Existing Foundry project must belong to the selected MAF group")
        project = self.runner.json(
            self.az("resource", "show", "--ids", project_id, "--api-version", "2025-06-01")
        )
        self.foundry_principal = required(project.get("identity", {}), "principalId")
        self.hosted_principal = required(
            self.values, "AGENT_MODEL_HARNESS_MAF_INSTANCE_IDENTITY_PRINCIPAL_ID"
        )
        self.old_version = active_agent(
            self.runner.json(
                azd_args(self.args.environment, "ai", "agent", "show", SERVICE, "--output", "json")
            )
        )
        database_url = required(self.values, "DATABASE_URL")
        database = urlsplit(database_url)
        if (
            database.scheme not in {"postgres", "postgresql"}
            or database.hostname != required(self.outputs, "postgresHost")
            or not database.password
            or not database.username
            or not database.path.strip("/")
        ):
            raise ReleaseError("Existing DATABASE_URL does not match the MAF PostgreSQL server")
        server_name = database.hostname.split(".")[0]
        server = self.runner.json(
            self.az("postgres", "flexible-server", "show", "-g", self.group, "-n", server_name)
        )
        self.postgres_state = str(server.get("state", ""))
        if self.args.apply and self.postgres_state.lower() != "ready":
            raise ReleaseError(
                "Existing PostgreSQL server is not Ready; operator must start/check it before apply"
            )
        password = unquote(database.password)
        configured_password = self.values.get("POSTGRES_ADMIN_PASSWORD")
        if configured_password and configured_password != password:
            raise ReleaseError("Existing PostgreSQL password settings disagree; refusing rotation")
        operator_ip = self.args.operator_ip
        if operator_ip is None:
            operator_ip = self.previous.get("operatorIp", "")
        if operator_ip:
            ipaddress.IPv4Address(operator_ip)
        endpoint = self.values.get("FOUNDRY_PROJECT_ENDPOINT") or required(
            self.values, "AZURE_AI_PROJECT_ENDPOINT"
        )
        self.parameters = {
            "location": self.location,
            "namePrefix": self.previous.get("namePrefix", "mth-maf"),
            "foundryAccountName": match[3],
            "foundryProjectName": match[4],
            "foundryProjectEndpoint": endpoint,
            "modelDeploymentName": required(self.values, "AZURE_AI_MODEL_DEPLOYMENT_NAME"),
            "postgresAdministratorPassword": password,
            "postgresAdministratorLogin": unquote(database.username),
            "postgresDatabaseName": database.path.strip("/"),
            "postgresServerName": server_name,
            "operatorIp": operator_ip,
            "postgresSchema": old_schema,
            "backendImage": required(backend_container, "image"),
            "frontendImage": required(frontend_container, "image"),
            "backendTargetPort": required(ingress, "targetPort"),
        }
        if any(
            "helloworld" in self.parameters[key].lower()
            for key in ("backendImage", "frontendImage")
        ):
            raise ReleaseError("Existing app image is a placeholder; refusing direct cutover")
        self.database_url = database_url
        if self.args.app_only:
            self.app_baseline = {
                app["id"].lower(): self.read_app_spec(app)
                for app in (self.backend, self.frontend)
            }

    def read_app_spec(self, app: dict[str, Any]) -> dict[str, Any]:
        spec = app_spec(app)
        props = app["properties"]
        if (
            props.get("provisioningState", "").lower() != "succeeded"
            or props.get("runningStatus") != "Running"
            or not props.get("latestRevisionName")
            or props.get("latestRevisionName") != props.get("latestReadyRevisionName")
            or len(spec["properties"]["template"]["containers"]) != 1
            or spec["properties"]["template"].get("revisionSuffix")
        ):
            raise ReleaseError("App-only update requires healthy existing application revisions")
        configuration = spec["properties"]["configuration"]
        if configuration.get("activeRevisionsMode") != "Single":
            raise ReleaseError("App-only update requires the existing single-revision topology")
        expected_external = app["name"] == self.frontend_name
        if configuration["ingress"].get("external") is not expected_external:
            raise ReleaseError("App-only update must preserve private API and public frontend")
        descriptors = configuration.get("secrets", [])
        if descriptors:
            secrets = self.runner.json(self.az(
                "containerapp", "secret", "list", "-g", self.group, "-n", app["name"],
                "--show-values",
            ))
            if not isinstance(secrets, list):
                raise ReleaseError("Cannot verify existing application secrets")
            by_name = {secret["name"]: secret for secret in secrets}
            if (
                len(by_name) != len(secrets) or len(by_name) != len(descriptors)
                or set(by_name) != {s["name"] for s in descriptors}
            ):
                raise ReleaseError("Existing application secret names disagree")
            for descriptor in descriptors:
                actual = by_name[descriptor["name"]]
                if set(actual) - {"name", "value", "identity", "keyVaultUrl"}:
                    raise ReleaseError("Unsupported application secret representation")
                if actual.get("keyVaultUrl"):
                    actual = {k: v for k, v in actual.items() if k != "value"}
                elif (
                    not isinstance(actual.get("value"), str) or not actual["value"]
                    or set(actual["value"]) == {"*"}
                ):
                    raise ReleaseError("Existing application secret value could not be verified")
                if (
                    {k: v for k, v in actual.items() if k != "value" and v is not None}
                    != {k: v for k, v in descriptor.items() if k != "value" and v is not None}
                ):
                    raise ReleaseError("Existing application secret bindings disagree")
                descriptor.clear()
                descriptor.update(actual)
        return app_spec(spec)

    def app_parameters(self, specs: dict[str, dict[str, Any]]) -> dict[str, Any]:
        apps = {
            "backend": specs[self.backend["id"].lower()],
            "frontend": specs[self.frontend["id"].lower()],
        }
        redacted = {kind: app_spec(spec, redact_secrets=True) for kind, spec in apps.items()}
        secret_values = {
            kind: {
                secret["name"]: secret["value"]
                for secret in spec["properties"]["configuration"].get("secrets", [])
                if "value" in secret
            }
            for kind, spec in apps.items()
        }
        literals = [value for values in secret_values.values() for value in values.values()]

        def contains_secret(value: Any) -> bool:
            if isinstance(value, str):
                return any(secret in value for secret in literals)
            if isinstance(value, dict):
                return any(contains_secret(item) for item in value.values())
            if isinstance(value, list):
                return any(contains_secret(item) for item in value)
            return False

        if contains_secret(redacted):
            raise ReleaseError("Existing app exposes a secret outside its secret configuration")
        return {**redacted, "secretValues": secret_values}

    def deploy_apps_only(
        self, specs: dict[str, dict[str, Any]], *, preview: bool
    ) -> dict[str, Any]:
        with parameter_file(self.workspace, self.app_parameters(specs)) as path:
            command = self.az(
                "deployment", "group", "what-if" if preview else "create",
                "--resource-group", self.group, "--name", APP_UPDATE_DEPLOYMENT,
                "--template-file", str(LANE / "infra/app/update-existing.bicep"),
                "--parameters", f"@{path}", "--mode", "Incremental",
            )
            if preview:
                command.extend([
                    "--result-format", "FullResourcePayloads", "--no-pretty-print",
                    "--validation-level", "Provider",
                ])
            result = self.runner.json(command)
        if preview:
            artifact = self.workspace / f"app-only-what-if-{uuid4().hex}.json"
            with open(
                artifact, "x", opener=lambda name, flags: os.open(name, flags, 0o600)
            ) as handle:
                json.dump(result, handle)
            changes = result.get("changes")
            if not isinstance(changes, list) or any(not isinstance(c, dict) for c in changes):
                raise ReleaseError("App-only what-if has malformed resource evidence")
            print(json.dumps({
                "app_only_preview": str(artifact),
                "changes": [
                    {"resourceId": c.get("resourceId"), "changeType": c.get("changeType")}
                    for c in changes
                ],
            }))
        elif result.get("properties", {}).get("provisioningState") != "Succeeded":
            raise ReleaseError("App-only rollout did not finish Succeeded")
        return result

    def verify_app_state(self, expected: dict[str, dict[str, Any]]) -> None:
        for app in (self.backend, self.frontend):
            actual = self.read_app_spec(self.app(app["name"]))
            if actual != expected[app["id"].lower()]:
                raise ReleaseError("Application state or secrets drifted from the verified release")

    def execute_app_only(self, commit: str) -> None:
        self.verify_existing_schema()
        app_only_what_if(
            self.deploy_apps_only(self.app_baseline, preview=True),
            self.app_baseline, self.app_baseline,
        )
        print(json.dumps({
            "mode": "apply" if self.args.apply else "preview", "app_only": True,
            "environment": self.args.environment, "source_commit": commit,
            "uncommitted_runtime_changes": self.dirty, "schema": self.schema,
        }))
        if not self.args.apply:
            return
        images = self.build(commit, f"{commit}-{uuid4().hex[:12]}")
        desired = deepcopy(self.app_baseline)
        for kind, app in (("backend", self.backend), ("frontend", self.frontend)):
            image = images[kind + "Image"]
            prefix = f"{self.registry_server}/model-harness-maf-{kind}@"
            if not image.startswith(prefix) or not DIGEST.fullmatch(image[len(prefix):]):
                raise ReleaseError("App-only rollout requires verified lane image digests")
            desired[app["id"].lower()]["properties"]["template"]["containers"][0]["image"] = image
        self.source_commit()
        app_only_what_if(
            self.deploy_apps_only(desired, preview=True), self.app_baseline, desired
        )
        self.verify_app_state(self.app_baseline)
        self.source_commit()
        self.deploy_apps_only(desired, preview=False)
        self.wait_apps({**self.parameters, **images})
        self.verify_app_state(desired)
        version = self.deploy_hosted()
        print(json.dumps({
            "released_commit": commit, "app_only": True, **images,
            "hosted_version": version, "schema": self.schema,
        }))

    def verify_existing_schema(self) -> None:
        from maf_double_charge.application.errors import StorageReadinessError
        from maf_double_charge.infrastructure.persistence.migrations import check_schema
        from psycopg import AsyncConnection, Error
        from psycopg.rows import dict_row

        async def verify() -> None:
            async with await AsyncConnection.connect(
                self.database_url, row_factory=dict_row, connect_timeout=15
            ) as connection:
                await connection.execute("SET TRANSACTION READ ONLY")
                await check_schema(
                    connection, self.schema, migrations_dir=LANE / "backend/migrations"
                )

        try:
            asyncio.run(verify())
        except (StorageReadinessError, Error, ValueError):
            raise ReleaseError(
                "Existing schema verification failed; check database access and migration history"
            ) from None

    def source_commit(self) -> str:
        commit = self.runner.run(
            ["git", "rev-parse", "--verify", f"{self.args.source_commit or 'HEAD'}^{{commit}}"],
            cwd=ROOT,
        ).strip()
        if not re.fullmatch("[0-9a-f]{40}", commit):
            raise ReleaseError("Source must resolve to a full Git commit")
        head = self.runner.run(["git", "rev-parse", "HEAD"], cwd=ROOT).strip()
        dirty = self.runner.run(
            [
                "git",
                "status",
                "--porcelain",
                "--untracked-files=all",
                "--",
                "shared",
                "agent-framework/double-charge/maf",
                ".dockerignore",
                "LICENSE",
            ],
            cwd=ROOT,
        ).strip()
        if commit != head or (dirty and self.args.apply):
            raise ReleaseError(
                "Apply requires clean validated runtime sources at the selected HEAD"
            )
        self.dirty = bool(dirty)
        return commit

    def deploy_parameters(
        self, parameters: dict[str, Any], *, preview: bool, suffix: str = ""
    ) -> dict[str, Any]:
        with parameter_file(self.workspace, parameters) as path:
            args = self.az(
                "deployment",
                "group",
                "what-if" if preview else "create",
                "--resource-group",
                self.group,
                "--name",
                DEPLOYMENT + suffix,
                "--template-file",
                str(LANE / "infra" / "app" / "main.bicep"),
                "--parameters",
                f"@{path}",
            )
            if preview:
                args.extend(["--result-format", "FullResourcePayloads", "--no-pretty-print"])
            result = self.runner.json(args)
        if not preview and result.get("properties", {}).get("provisioningState") != "Succeeded":
            raise ReleaseError("ARM deployment did not finish Succeeded")
        if preview and (
            result.get("error")
            or result.get("status") != "Succeeded"
            or not isinstance(result.get("changes"), list)
        ):
            raise ReleaseError("ARM what-if did not finish successfully")
        return result

    def wait_apps(self, parameters: dict[str, Any]) -> None:
        deadline = time.monotonic() + self.args.timeout
        while time.monotonic() < deadline:
            ready = True
            for name in (self.backend_name, self.frontend_name):
                properties = self.app(name)["properties"]
                container = properties["template"]["containers"][0]
                expected_image = parameters[
                    "backendImage" if name == self.backend_name else "frontendImage"
                ]
                state = str(properties.get("provisioningState", "")).lower()
                if state in {"failed", "canceled", "cancelled"}:
                    raise ReleaseError(f"Container App {name} rollout failed")
                if (
                    state != "succeeded"
                    or properties.get("runningStatus") != "Running"
                    or not properties.get("latestRevisionName")
                    or properties.get("latestReadyRevisionName") != properties["latestRevisionName"]
                    or container.get("image") != expected_image
                ):
                    ready = False
                if name == self.backend_name:
                    environment = {
                        item["name"]: item.get("value") for item in container.get("env", [])
                    }
                    if environment.get("DATABASE_SCHEMA") != parameters["postgresSchema"]:
                        ready = False
            if ready:
                return
            time.sleep(5)
        raise ReleaseError("Timed out waiting for healthy Container App revisions")

    def wait_hosted(self) -> str:
        deadline = time.monotonic() + self.args.timeout
        while time.monotonic() < deadline:
            result = self.runner.json(
                azd_args(self.args.environment, "ai", "agent", "show", SERVICE, "--output", "json")
            )
            status = str(result.get("status", "")).lower()
            if status in {"failed", "error", "canceled", "cancelled"}:
                raise ReleaseError("Hosted deployment failed")
            if status in {"active", "deployed"}:
                version = active_agent(result)
                self.verify_hosted_source(version)
                return version
            time.sleep(5)
        raise ReleaseError("Timed out waiting for a verified active hosted version")

    def verify_hosted_source(self, version: str) -> None:
        from azure.ai.projects import AIProjectClient
        from azure.core.exceptions import AzureError
        from azure.identity import DefaultAzureCredential

        try:
            with (
                DefaultAzureCredential() as credential,
                AIProjectClient(
                    endpoint=self.parameters["foundryProjectEndpoint"], credential=credential
                ) as project,
            ):
                actual = project.agents.get_version(
                    agent_name=SERVICE, agent_version=version
                ).as_dict()
                if actual.get("status") != "active":
                    raise ReleaseError("Authoritative hosted version is not active")
                environment = actual["definition"]["environment_variables"]
                expected = {
                    "DATABASE_SCHEMA": self.schema,
                    "DATABASE_URL": self.database_url,
                    "FOUNDRY_PROJECT_ENDPOINT": self.parameters["foundryProjectEndpoint"],
                    "FOUNDRY_MODEL": self.parameters["modelDeploymentName"],
                    "OTEL_TRACES_SAMPLER": "microsoft.fixed_percentage",
                    "OTEL_TRACES_SAMPLER_ARG": "1.0",
                    "OTEL_PYTHON_DISABLED_INSTRUMENTATIONS": (
                        "azure_sdk,httpx,httpx2,requests,urllib,urllib3"
                    ),
                    "AZURE_TRACING_ENABLED": "false",
                    "OTEL_INSTRUMENTATION_GENAI_CAPTURE_MESSAGE_CONTENT": "false",
                }
                if any(environment.get(key) != value for key, value in expected.items()):
                    raise ReleaseError("Hosted version configuration differs from this release")
                content = b"".join(
                    project.agents.download_code(agent_name=SERVICE, agent_version=version)
                )
                digest = verify_code_archive(
                    LANE / "infra/foundry-hosted/agent",
                    content,
                    actual["definition"]["code_configuration"]["content_hash"],
                )
        except (AzureError, KeyError, TypeError):
            raise ReleaseError("Cannot verify the deployed hosted source/configuration") from None
        print(
            json.dumps(
                {
                    "verified_hosted_version": version,
                    "archive_sha256": digest,
                    "reused_identical_version": version == self.old_version,
                }
            )
        )

    def build(self, commit: str, tag: str) -> dict[str, str]:
        images: dict[str, str] = {}
        with private_workspace(self.workspace) as directory:
            archive = directory / "source.tar"
            self.runner.run(
                [
                    "git",
                    "archive",
                    "--format=tar",
                    f"--output={archive}",
                    commit,
                    "--",
                    "LICENSE",
                    ".dockerignore",
                    "shared",
                    "agent-framework/double-charge/maf",
                ],
                cwd=ROOT,
            )
            source = directory / "source"
            source.mkdir()
            with tarfile.open(archive) as bundle:
                bundle.extractall(source, filter="data")
            for kind, dockerfile in (
                ("backend", "infra/container/Dockerfile"),
                ("frontend", "infra/app/frontend.Dockerfile"),
            ):
                image = f"model-harness-maf-{kind}:{tag}"
                result = self.runner.json(
                    self.az(
                        "acr",
                        "build",
                        "--registry",
                        self.registry_name,
                        "--image",
                        image,
                        "--file",
                        str(source / LANE.relative_to(ROOT) / dockerfile),
                        str(source),
                        "--no-logs",
                    )
                )
                if str(result.get("status", "")).lower() != "succeeded":
                    raise ReleaseError(f"ACR {kind} build did not finish Succeeded")
                self.runner.run(
                    self.az(
                        "acr",
                        "repository",
                        "update",
                        "--name",
                        self.registry_name,
                        "--image",
                        image,
                        "--write-enabled",
                        "false",
                        "--delete-enabled",
                        "false",
                    )
                )
                if self.args.app_only:
                    metadata = self.runner.json(self.az(
                        "acr", "repository", "show", "--name", self.registry_name,
                        "--image", image,
                    ))
                    digest = metadata.get("digest", "")
                    outputs = result.get("outputImages", [])
                    if (
                        not isinstance(digest, str) or not DIGEST.fullmatch(digest)
                        or not isinstance(outputs, list) or len(outputs) != 1
                        or not isinstance(outputs[0], dict)
                        or outputs[0].get("digest") != digest
                        or outputs[0].get("registry") != self.registry_server
                        or outputs[0].get("repository") != f"model-harness-maf-{kind}"
                        or outputs[0].get("tag") != tag
                        or metadata.get("changeableAttributes", {}).get("writeEnabled") is not False
                        or metadata.get("changeableAttributes", {}).get("deleteEnabled")
                        is not False
                    ):
                        raise ReleaseError(
                            "Built image digest, provenance or immutability is unverified"
                        )
                    images[kind + "Image"] = (
                        f"{self.registry_server}/model-harness-maf-{kind}@{digest}"
                    )
        return images

    def execute(self) -> None:
        if self.args.app_only and (
            not self.args.update_existing
            or self.args.foundation
            or self.args.operator_ip is not None
        ):
            raise ReleaseError(
                "--app-only requires --update-existing and forbids foundation/firewall changes"
            )
        commit = self.source_commit()
        self.discover()
        if self.args.app_only:
            self.execute_app_only(commit)
            return
        tag = f"{commit}-{uuid4().hex[:12]}"
        final = dict(
            self.parameters,
            postgresSchema=self.schema,
            backendImage=f"{self.registry_server}/model-harness-maf-backend:{tag}",
            frontendImage=f"{self.registry_server}/model-harness-maf-frontend:{tag}",
            backendTargetPort=8010,
        )
        print(
            json.dumps(
                {
                    "mode": "apply" if self.args.apply else "preview",
                    "schema_mode": "existing" if self.args.update_existing else "fresh",
                    "environment": self.args.environment,
                    "resource_group": self.group,
                    "source_commit": commit,
                    "uncommitted_runtime_changes": self.dirty,
                    "hosted_version_before": self.old_version,
                    "foundry_identity": self.foundry_principal,
                    "hosted_identity": self.hosted_principal,
                    "postgres_state": self.postgres_state,
                    "parameters": {
                        key: ("<redacted>" if key == "postgresAdministratorPassword" else value)
                        for key, value in final.items()
                    },
                },
                indent=2,
            )
        )
        preview = self.deploy_parameters(final, preview=True)
        changes = [
            {"resourceId": change.get("resourceId"), "changeType": change.get("changeType")}
            for change in preview.get("changes", [])
        ]
        print(json.dumps({"what_if": changes}, indent=2))
        for change in changes:
            if change["changeType"] not in {"Create", "Delete", "Modify", "NoChange", "Ignore"}:
                raise ReleaseError(
                    "ARM what-if could not determine resource changes; inspect before applying"
                )
            if change["changeType"] == "Delete":
                raise ReleaseError("Cutover does not authorize resource deletion")
            if change["changeType"] == "Create" and re.search(
                r"/providers/(Microsoft.App/(containerApps|managedEnvironments)"
                r"|Microsoft.ContainerRegistry/registries"
                r"|Microsoft.DBforPostgreSQL/flexibleServers)/[^/]+$",
                str(change["resourceId"]),
                flags=re.IGNORECASE,
            ):
                raise ReleaseError(
                    "Cutover must reuse existing apps, registry, environment and server"
                )
        foundation = self.args.foundation or any(
            change["changeType"] in {"Create", "Modify"}
            and "/providers/Microsoft.App/containerApps/" not in str(change["resourceId"])
            for change in changes
        )
        print(f"Foundation apply preserving old images/schema required: {foundation}")
        if self.args.update_existing:
            self.verify_existing_schema()
            print("Existing schema history/checksums verified read-only; no migration will run.")
        if not self.args.apply:
            print("Preview only. No images, schemas, resources, or hosted versions changed.")
            return
        if foundation:
            print("Applying foundation with existing images and schema.")
            self.deploy_parameters(self.parameters, preview=False, suffix="-foundation")
            self.wait_apps(self.parameters)
        migration_env = {
            **os.environ,
            "DATABASE_URL": self.database_url,
            "DATABASE_SCHEMA": self.schema,
        }
        if not self.args.update_existing:
            self.runner.run(
                [
                    str(LANE / ".venv/bin/python"),
                    str(LANE / "scripts/migrate.py"),
                    "--migrations-dir",
                    str(LANE / "backend/migrations"),
                    "--require-empty",
                ],
                env=migration_env,
            )
            print("Explicit fresh-schema SQL migration completed.")
        print("Building archived committed app sources into immutable tags.")
        self.build(commit, tag)
        self.source_commit()
        print("Rolling out final app images and schema.")
        self.deploy_parameters(final, preview=False)
        self.wait_apps(final)
        version = self.deploy_hosted()
        print(
            json.dumps(
                {
                    "released_commit": commit,
                    "hosted_version": version,
                    "schema": self.schema,
                    "frontend_url": required(self.outputs, "frontendUrl"),
                    "next": "Run API, browser, hosted, evaluation and telemetry acceptance gates.",
                },
                indent=2,
            )
        )

    def deploy_hosted(self) -> str:
        migration_env = {
            **os.environ, "DATABASE_URL": self.database_url, "DATABASE_SCHEMA": self.schema,
        }
        self.runner.run(
            azd_args(self.args.environment, "env", "set", "DATABASE_SCHEMA", self.schema)
        )
        self.runner.run(
            azd_args(
                self.args.environment,
                "env",
                "set",
                "FOUNDRY_PROJECT_ENDPOINT",
                self.parameters["foundryProjectEndpoint"],
            )
        )
        self.runner.run([sys.executable, str(LANE / "scripts/prepare_hosted.py")])
        self.source_commit()
        print("Deploying hosted direct Python source; verifying the active version and archive.")
        self.runner.run(
            azd_args(self.args.environment, "deploy", SERVICE, "--no-prompt"),
            env=migration_env,
        )
        return self.wait_hosted()


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    mode = result.add_mutually_exclusive_group()
    mode.add_argument("--preview", action="store_true", help="Read-only preview (default)")
    mode.add_argument("--apply", action="store_true", help="Execute the reviewed ordered cutover")
    result.add_argument("--environment", default="maf-dev")
    result.add_argument("--schema", default=SCHEMA)
    result.add_argument(
        "--app-only", action="store_true",
        help="Update only the existing app images; requires --update-existing",
    )
    result.add_argument(
        "--update-existing",
        action="store_true",
        help="Verify and preserve the current versioned schema instead of creating a fresh one",
    )
    result.add_argument("--source-commit", help="Validated clean HEAD commit (required for apply)")
    result.add_argument("--operator-ip", help="Explicit PostgreSQL operator firewall IPv4 address")
    result.add_argument(
        "--foundation", action="store_true", help="Force existing-runtime IaC first"
    )
    result.add_argument("--timeout", type=int, default=900)
    return result


def main() -> None:
    args = parser().parse_args()
    if args.timeout < 1:
        raise SystemExit("--timeout must be positive")
    if args.apply and not args.source_commit:
        raise SystemExit("--apply requires --source-commit from the validated local gates")
    try:
        Release(args).execute()
    except ReleaseError as error:
        raise SystemExit(str(error)) from None
    except (ValueError, KeyError, TypeError):
        # Do not print arbitrary parser/SDK error values: they can embed secrets.
        raise SystemExit(
            "Release failed closed; no automatic rollback or deletion was attempted."
        ) from None


if __name__ == "__main__":
    main()
