"""Reproducible lane-owned IaC release. Private release state stays in ignored .azure/."""

import argparse
import json
import os
import re
import secrets
import subprocess
import time
from copy import deepcopy
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str]) -> str:
    result = subprocess.run(
        args,
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
        env=os.environ,
    )
    if result.returncode:
        error = result.stderr or "No diagnostic output"
        for value in args:
            if value.startswith("postgresql://"):
                error = error.replace(value, "[database credential redacted]")
        raise SystemExit(f"Release command failed ({args[0]}): {error}")
    return result.stdout


def write_private(path: Path, data: dict) -> None:
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as stream:
        json.dump(data, stream, indent=2)


def require_source(commit: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise SystemExit("A full source commit is required")
    if run(["git", "rev-parse", "HEAD"]).strip() != commit:
        raise SystemExit("Source commit does not match HEAD")
    if run(["git", "status", "--porcelain"]).strip():
        raise SystemExit("Release requires a clean worktree")


def image_reference(image: str, registry: str, repository: str) -> str:
    prefix = f"{registry}/{repository}@sha256:"
    if not image.startswith(prefix) or not re.fullmatch(r"[0-9a-f]{64}", image[len(prefix) :]):
        raise SystemExit("Expected a lane-owned immutable image digest")
    return image.removeprefix(registry + "/")


def stable_app(app: dict) -> dict:
    template = deepcopy(app["properties"]["template"])
    for container in template["containers"]:
        container.pop("image", None)
        for variable in container.get("env", []):
            # CLI updates serialize an unused secret-reference value as "" instead of null.
            if variable.get("secretRef") and variable.get("value") in (None, ""):
                variable.pop("value", None)
    identity = deepcopy(app.get("identity"))
    if identity:
        # Principal metadata is read-only and can differ between CLI response shapes.
        identity = {
            "type": identity["type"],
            "userAssignedIdentities": sorted(identity.get("userAssignedIdentities", {})),
        }
    return {
        "identity": identity,
        "environment": app["properties"]["managedEnvironmentId"],
        "configuration": app["properties"]["configuration"],
        "template": template,
    }


def update_existing(args: argparse.Namespace, env: dict, folder: Path) -> None:
    """Update only the two existing app images; never submit the foundation template."""
    require_source(args.source_commit or "")
    if not args.backend_image or not args.frontend_image or not args.output_dir:
        raise SystemExit("Existing-app update requires both images and --output-dir")
    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    receipt_path = output / ("update-started.json" if args.apply else "update-preview.json")
    if receipt_path.exists():
        raise SystemExit("Release receipt already exists; reconcile it before retrying")
    preview_path = output / "update-preview.json"
    if args.apply and not preview_path.exists():
        raise SystemExit("Apply requires a saved preview in the same --output-dir")
    outputs = json.loads((folder / "app-outputs.json").read_text())
    subscription, group = env["AZURE_SUBSCRIPTION_ID"], env["AZURE_RESOURCE_GROUP"]

    def az(*arguments: str) -> list[str]:
        return ["az", *arguments, "--subscription", subscription, "-o", "json"]

    registry = outputs["registryLoginServer"]["value"]
    registry_name = outputs["registryName"]["value"]
    plans = []
    for kind, repository, image in (
        ("backend", "checkout-recovery-maf-api", args.backend_image),
        ("frontend", "checkout-recovery-maf-web", args.frontend_image),
    ):
        name = outputs[kind + "AppName"]["value"]
        before = json.loads(run(az("containerapp", "show", "-g", group, "-n", name)))
        expected_id = (
            f"/subscriptions/{subscription}/resourceGroups/{group}"
            f"/providers/Microsoft.App/containerApps/{name}"
        )
        if before["id"].lower() != expected_id.lower():
            raise SystemExit("Existing app identity differs from selected environment")
        containers = before["properties"]["template"]["containers"]
        if len(containers) != 1 or containers[0]["name"] != kind:
            raise SystemExit("Expected exactly one lane-owned app container")
        reference = image_reference(image, registry, repository)
        metadata = json.loads(
            run(
                az(
                    "acr",
                    "repository",
                    "show",
                    "--name",
                    registry_name,
                    "--image",
                    reference,
                )
            )
        )
        tags = [tag for tag in metadata.get("tags", []) if tag.startswith(args.source_commit + "-")]
        if metadata["digest"] != image.split("@")[1] or len(tags) != 1:
            raise SystemExit("Image lacks an unambiguous matching source-commit tag")
        plans.append(
            {
                "name": name,
                "container": kind,
                "before": before,
                "image": image,
                "manifest": reference,
                "tag": repository + ":" + tags[0],
            }
        )
    proposal = {
        "source_commit": args.source_commit,
        "subscription": subscription,
        "resource_group": group,
        "registry": registry,
        "apps": plans,
    }
    if args.apply and json.loads(preview_path.read_text()) != proposal:
        raise SystemExit("Source, images or app configuration changed since the saved preview")
    require_source(args.source_commit)
    with os.fdopen(os.open(receipt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w") as file:
        json.dump(proposal, file, indent=2)
    print(
        json.dumps(
            {
                "apply": args.apply,
                "source_commit": args.source_commit,
                "image_only_updates": [{"name": p["name"], "image": p["image"]} for p in plans],
            }
        )
    )
    if not args.apply:
        return
    for plan in plans:
        for reference in (plan["manifest"], plan["tag"]):
            run(
                az(
                    "acr",
                    "repository",
                    "update",
                    "--name",
                    registry_name,
                    "--image",
                    reference,
                    "--write-enabled",
                    "false",
                    "--delete-enabled",
                    "false",
                )
            )
            locked = json.loads(
                run(
                    az(
                        "acr",
                        "repository",
                        "show",
                        "--name",
                        registry_name,
                        "--image",
                        reference,
                    )
                )
            )
            attributes = locked["changeableAttributes"]
            if (
                locked["digest"] != plan["image"].split("@")[1]
                or attributes["writeEnabled"]
                or attributes["deleteEnabled"]
            ):
                raise SystemExit("Image tag/manifest immutability was not verified")

    def ready_revision(plan: dict) -> dict | None:
        after = json.loads(run(az("containerapp", "show", "-g", group, "-n", plan["name"])))
        properties = after["properties"]
        if stable_app(after) != stable_app(plan["before"]):
            raise SystemExit("An app setting other than its image changed; inspect receipt")
        if properties["template"]["containers"][0]["image"] != plan["image"]:
            raise SystemExit("Live app image differs from the approved image")
        revision = properties["latestRevisionName"]
        health = json.loads(
            run(
                az(
                    "containerapp",
                    "revision",
                    "show",
                    "-g",
                    group,
                    "-n",
                    plan["name"],
                    "--revision",
                    revision,
                )
            )
        )["properties"]
        if (
            properties["latestReadyRevisionName"] == revision
            and health.get("healthState") == "Healthy"
            and health.get("active") is True
        ):
            return {"name": plan["name"], "revision": revision, "image": plan["image"]}
        return None

    for plan in plans:
        require_source(args.source_commit)
        current = json.loads(run(az("containerapp", "show", "-g", group, "-n", plan["name"])))
        if current["properties"] != plan["before"]["properties"]:
            raise SystemExit("App changed since preview; refusing concurrent deployment")
        run(
            az(
                "containerapp",
                "update",
                "-g",
                group,
                "-n",
                plan["name"],
                "--container-name",
                plan["container"],
                "--image",
                plan["image"],
            )
        )
        deadline = time.monotonic() + 300
        while True:
            if ready_revision(plan) is not None:
                break
            if time.monotonic() >= deadline:
                raise SystemExit("New app revision was not ready before the deadline")
            time.sleep(10)
    require_source(args.source_commit)
    revisions = [ready_revision(plan) for plan in plans]
    if any(revision is None for revision in revisions):
        raise SystemExit("An app is no longer ready at final readback")
    result = {"source_commit": args.source_commit, "apps": revisions, "passed": True}
    write_private(output / "update-completed.json", result)
    print(json.dumps(result))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "step",
        choices=[
            "prepare",
            "preview",
            "foundation",
            "configure",
            "apps",
            "migrate",
            "e2e",
            "browser",
            "evidence",
            "update-existing",
        ],
    )
    parser.add_argument("--environment", required=True)
    parser.add_argument("--operator-ip")
    parser.add_argument("--backend-image")
    parser.add_argument("--frontend-image")
    parser.add_argument("--source-commit")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--hosted-report", type=Path)
    args = parser.parse_args()
    env = json.loads(run(["azd", "env", "get-values", "-e", args.environment, "--output", "json"]))
    folder = ROOT / ".azure" / args.environment
    private = folder / "release-secrets.json"
    params_path = folder / "release.parameters.json"
    if args.step == "update-existing":
        update_existing(args, env, folder)
        return
    if args.step in {"e2e", "evidence"} and args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
    evidence_folder = args.output_dir or folder
    if args.step in {"migrate", "e2e", "browser", "evidence"}:
        outputs = json.loads((folder / "app-outputs.json").read_text())
        values = json.loads(private.read_text())
        process_env = {
            **os.environ,
            "CHECKOUT_RECOVERY_DATABASE_URL": env["CHECKOUT_RECOVERY_DATABASE_URL"],
            "CHECKOUT_UI_USERNAME": values["uiUsername"],
            "CHECKOUT_UI_PASSWORD": values["uiPassword"],
            "CHECKOUT_RECOVERY_BASE_URL": outputs["frontendUrl"]["value"],
        }
        if args.step == "migrate":
            command = ["uv", "run", "python", "scripts/migrate.py", "--apply"]
        elif args.step == "e2e":
            command = [
                "uv",
                "run",
                "python",
                "scripts/e2e.py",
                "--require-maf",
                "--output",
                str(evidence_folder / "deployed-api-e2e.json"),
            ]
        elif args.step == "evidence":
            if not args.hosted_report:
                parser.error("evidence requires --hosted-report for the accepted version")
            command = [
                "uv",
                "run",
                "python",
                "scripts/verify_business.py",
                str(evidence_folder / "deployed-api-e2e.json"),
                str(args.hosted_report),
                "--output",
                str(evidence_folder / "business-evidence.json"),
            ]
        else:
            process_env["CHECKOUT_E2E_BASE_URL"] = outputs["frontendUrl"]["value"]
            command = ["npm", "--prefix", "frontend", "run", "test:e2e"]
        subprocess.run(command, cwd=ROOT, env=process_env, check=True)
        return
    if args.step == "prepare":
        if not args.operator_ip:
            parser.error("--operator-ip is required for migration access")
        if private.exists():
            values = json.loads(private.read_text())
        else:
            values = {
                "postgresPassword": secrets.token_urlsafe(36),
                "apiToken": secrets.token_urlsafe(36),
                "uiUsername": "checkout-reviewer",
                "uiPassword": secrets.token_urlsafe(24),
            }
            write_private(private, values)
        digest = subprocess.run(
            ["openssl", "passwd", "-apr1", "-stdin"],
            input=values["uiPassword"],
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip()
        params = {
            "foundryProjectEndpoint": env["AZURE_AI_PROJECT_ENDPOINT"],
            "foundryModelDeployment": env["CHECKOUT_RECOVERY_FOUNDRY_MODEL_DEPLOYMENT"],
            "foundryAccountName": env["AZURE_AI_ACCOUNT_NAME"],
            "foundryProjectName": env["AZURE_AI_PROJECT_NAME"],
            "postgresAdministratorPassword": values["postgresPassword"],
            "apiToken": values["apiToken"],
            "uiHtpasswd": values["uiUsername"] + ":" + digest,
            "operatorIp": args.operator_ip,
        }
        write_private(params_path, {"parameters": {k: {"value": v} for k, v in params.items()}})
        print(f"Prepared private release configuration for {args.environment}")
        return
    if args.step == "configure":
        outputs = json.loads((folder / "app-outputs.json").read_text())
        values = json.loads(private.read_text())
        url = (
            f"postgresql://checkoutadmin:{quote(values['postgresPassword'], safe='')}@"
            f"{outputs['postgresHost']['value']}:5432/checkout_recovery?sslmode=require"
        )
        run(["azd", "env", "set", "CHECKOUT_RECOVERY_DATABASE_URL", url, "-e", args.environment])
        print("Configured hosted PostgreSQL secret without printing its value")
        return
    params = json.loads(params_path.read_text())
    if args.step == "apps":
        if not args.backend_image or not args.frontend_image:
            parser.error("--backend-image and --frontend-image are required")
        params["parameters"].update(
            {
                "backendImage": {"value": args.backend_image},
                "frontendImage": {"value": args.frontend_image},
                "deployApps": {"value": True},
            }
        )
        write_private(params_path, params)
    command = [
        "az",
        "deployment",
        "group",
        "what-if" if args.step == "preview" else "create",
        "--resource-group",
        env["AZURE_RESOURCE_GROUP"],
        "--template-file",
        str(ROOT / "infra/app/main.bicep"),
        "--parameters",
        "@" + str(params_path),
    ]
    if args.step == "preview":
        print(run(command + ["--result-format", "ResourceIdOnly"]))
    else:
        if args.step == "apps":
            print(run([*command[:3], "what-if", *command[4:], "--result-format", "ResourceIdOnly"]))
        outputs = json.loads(
            run(
                command
                + ["--name", "checkout-application", "--query", "properties.outputs", "-o", "json"]
            )
        )
        write_private(folder / "app-outputs.json", outputs)
        print(json.dumps(outputs, indent=2))


if __name__ == "__main__":
    main()
