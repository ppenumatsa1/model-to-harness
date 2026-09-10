"""Bind existing eval intent to a verified active version without starting a cloud job."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

import yaml
from release import LANE, SERVICE, Runner, active_agent, azd_args

AGENT_ROOT = LANE / "infra/foundry-hosted/agent"


def bind(config: dict, version: str, dataset: Path) -> dict:
    if config.get("agent", {}).get("name") != SERVICE:
        raise ValueError("Evaluation agent does not match the MAF hosted service")
    result = {**config, "agent": {**config["agent"], "version": version}}
    result["dataset"] = {**config["dataset"], "local_uri": str(dataset.resolve())}
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", default="maf-dev")
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    runner = Runner()
    actual = active_agent(
        runner.json(azd_args(args.environment, "ai", "agent", "show", SERVICE, "--output", "json"))
    )
    if actual != args.version:
        raise SystemExit("Evaluation version must match the actual active deployment")
    config = yaml.safe_load((AGENT_ROOT / "eval.yaml").read_text())
    source = AGENT_ROOT / config["dataset"]["local_uri"]
    directory = LANE / ".azure" / "release" / f"eval-{uuid4().hex}"
    directory.mkdir(parents=True, mode=0o700)
    dataset = directory / "cases.jsonl"
    with open(dataset, "x", opener=lambda name, flags: os.open(name, flags, 0o600)) as handle:
        for line in source.read_text().splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            command = json.loads(item["query"])
            unique = f"maf-eval-{uuid4().hex}"
            command.update(existing_case_id=unique, idempotency_key=unique)
            item["query"] = json.dumps(command)
            handle.write(json.dumps(item) + "\n")
    output = directory / "eval.yaml"
    with open(output, "x", opener=lambda name, flags: os.open(name, flags, 0o600)) as handle:
        json.dump(bind(config, actual, dataset), handle, indent=2)
    print(
        json.dumps(
            {
                "version": actual,
                "config": str(output),
                "next": "For pinned acceptance use scripts/prepare_hosted_eval.py. "
                "Ordinary azd eval run may ignore evaluator version pins and reuse LAST_EVAL_ID. "
                "No evaluation job was created.",
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
