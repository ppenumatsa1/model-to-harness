"""Reproducible lane-owned IaC release. Private release state stays in ignored .azure/."""

import argparse
import json
import os
import secrets
import subprocess
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
        ],
    )
    parser.add_argument("--environment", required=True)
    parser.add_argument("--operator-ip")
    parser.add_argument("--backend-image")
    parser.add_argument("--frontend-image")
    args = parser.parse_args()
    env = json.loads(run(["azd", "env", "get-values", "-e", args.environment, "--output", "json"]))
    folder = ROOT / ".azure" / args.environment
    private = folder / "release-secrets.json"
    params_path = folder / "release.parameters.json"
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
                str(folder / "deployed-api-e2e.json"),
            ]
        elif args.step == "evidence":
            command = [
                "uv",
                "run",
                "python",
                "scripts/verify_business.py",
                str(folder / "deployed-api-e2e.json"),
                str(folder / "hosted-e2e-v2.json"),
                "--output",
                str(folder / "business-evidence.json"),
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
