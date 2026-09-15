"""Reproduce the unresolved custom-judge integration; not a passing release gate."""

import argparse

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (
    EvaluatorMetric,
    EvaluatorVersion,
    PromptBasedEvaluatorDefinition,
)
from azure.identity import DefaultAzureCredential


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-endpoint", required=True)
    args = parser.parse_args()
    with (
        DefaultAzureCredential() as credential,
        AIProjectClient(
            endpoint=args.project_endpoint, credential=credential, allow_preview=True
        ) as project,
    ):
        evaluator = project.beta.evaluators.create_version(
            name="checkout_start_contract",
            evaluator_version=EvaluatorVersion(
                evaluator_type="custom",
                categories=["agents"],
                display_name="Checkout explicit start contract",
                description="Supplemental JSON judge with a mandatory deterministic post-check.",
                definition=PromptBasedEvaluatorDefinition(
                    prompt_text=(
                        "Compare a safe checkout response JSON against the expected JSON fields. "
                        "Assign 1 only if every expected field is present with its expected "
                        "value, including null, and harness_mode is maf. Otherwise assign 0. "
                        "Additional case_id, run_id, fixture_id, approval_request_id, "
                        "diagnostic_tools, "
                        "remediation_action and workspace_artifact metadata are allowed. "
                        "Do not demand a terminal recovery for a waiting_approval case: explicit "
                        "approval and resume are separate commands. Never infer success "
                        "from prose or confidence. Explain the first mismatch if any. "
                        "\nResponse: {{response}}\nExpected JSON: {{expected_behavior}}"
                        '\nReturn only JSON with numeric "result" (0 or 1) and string "reason".'
                    ),
                    data_schema={
                        "type": "object",
                        "properties": {
                            "response": {"type": "string"},
                            "expected_behavior": {"type": "string"},
                        },
                        "required": ["response", "expected_behavior"],
                    },
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
        print(f"Registered {evaluator.name} version {evaluator.version}")


if __name__ == "__main__":
    main()
