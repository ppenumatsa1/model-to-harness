"""Register the exact contract and create a native Python-grader evaluation group."""

import argparse
import json
from pathlib import Path

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    CodeBasedEvaluatorDefinition,
    EvaluatorMetric,
    EvaluatorVersion,
)
from azure.identity import DefaultAzureCredential

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-endpoint", required=True)
    args = parser.parse_args()
    source = (ROOT / "evals/start_contract.py").read_text()
    schema = {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "expected_behavior": {"type": "string"},
        },
        "required": ["query", "expected_behavior"],
    }
    with (
        DefaultAzureCredential() as credential,
        AIProjectClient(
            endpoint=args.project_endpoint, credential=credential, allow_preview=True
        ) as project,
        project.get_openai_client() as client,
    ):
        registered = project.beta.evaluators.create_version(
            name="checkout_exact_contract",
            evaluator_version=EvaluatorVersion(
                evaluator_type="custom",
                categories=["agents"],
                display_name="Checkout exact start contract",
                description="Catalog identity for the native Python evaluation group.",
                definition=CodeBasedEvaluatorDefinition(
                    code_text=source,
                    data_schema=schema,
                    metrics={
                        "result": EvaluatorMetric(
                            type="continuous",
                            min_value=0,
                            max_value=1,
                            desirable_direction="increase",
                        )
                    },
                ),
            ),
        )
        evaluation = client.evals.create(
            name="checkout-native-exact-contract",
            data_source_config={
                "type": "custom",
                "item_schema": schema,
                "include_sample_schema": True,
            },
            testing_criteria=[
                {
                    "type": "python",
                    "name": "checkout_exact_contract",
                    "pass_threshold": 1,
                    "source": source,
                }
            ],
        )
    target = ROOT / "infra/foundry-hosted/agent/.foundry/evaluators/native-contract-group.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(evaluation.model_dump(mode="json"), indent=2))
    print(f"Catalog: {registered.name}:{registered.version}; evaluation: {evaluation.id}")


if __name__ == "__main__":
    main()
