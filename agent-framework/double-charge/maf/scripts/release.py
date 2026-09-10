"""Reviewed fresh cutover or existing-schema update. Preview is the default; never resets state."""

from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
from contextlib import contextmanager
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
                if version != self.old_version:
                    return version
            time.sleep(5)
        raise ReleaseError("Timed out waiting for a new active hosted version")

    def build(self, commit: str, tag: str) -> None:
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

    def execute(self) -> None:
        commit = self.source_commit()
        self.discover()
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
        print("Deploying hosted direct Python source; waiting for a new active version.")
        self.runner.run(
            azd_args(self.args.environment, "deploy", SERVICE, "--no-prompt"),
            env=migration_env,
        )
        version = self.wait_hosted()
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


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    mode = result.add_mutually_exclusive_group()
    mode.add_argument("--preview", action="store_true", help="Read-only preview (default)")
    mode.add_argument("--apply", action="store_true", help="Execute the reviewed ordered cutover")
    result.add_argument("--environment", default="maf-dev")
    result.add_argument("--schema", default=SCHEMA)
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
