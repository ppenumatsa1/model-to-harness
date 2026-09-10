import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FOUNDRY = ROOT / ".foundry"


def test_foundry_workspace_is_single_environment_metadata_and_cache_only():
    metadata = (FOUNDRY / "agent-metadata.yaml").read_text()
    assert metadata.startswith("defaultEnvironment: local\n")
    assert metadata.count("\n  local:\n") == 1
    assert "evaluationSuites: []" in metadata
    assert "agentName" not in metadata
    assert "http://" not in metadata
    assert "https://" not in metadata
    assert "resourceId" not in metadata
    assert "subscription" not in metadata.lower()

    for directory in ("suites", "datasets", "evaluators", "results"):
        assert (FOUNDRY / directory).is_dir()

    assert (ROOT / "eval.yaml").is_file()
    assert "\nagent:" not in (ROOT / "eval.yaml").read_text()
    assert not (FOUNDRY / "eval.yaml").exists()

    azure_yaml = (ROOT / "azure.yaml").read_text()
    assert "host: azure.ai.agent" in azure_yaml
    assert "runtime: python_3_13" in azure_yaml
    assert "protocol: responses" in azure_yaml
    assert "version: 2.0.0" in azure_yaml
    assert "DATABASE_URL: postgresql://" not in azure_yaml


def test_foundry_template_requires_discovered_location_and_existing_ai_resources():
    bicep = (ROOT / "infra" / "main.bicep").read_text()
    assert re.search(r"(?m)^param location string[ \t]*$", bicep)
    assert re.search(r"(?m)^param foundryAccountName string[ \t]*$", bicep)
    resources = re.findall(
        r"(?m)^[ \t]*resource\s+\w+\s+'(Microsoft\.CognitiveServices/[^']+)'\s+"
        r"(existing\s+)?=\s*\{",
        bicep,
    )
    existing_ai_kinds = {
        "Microsoft.CognitiveServices/accounts",
        "Microsoft.CognitiveServices/accounts/projects",
        "Microsoft.CognitiveServices/accounts/deployments",
    }
    existing_ai_resources = [
        (kind.split("@")[0], existing)
        for kind, existing in resources
        if kind.split("@")[0] in existing_ai_kinds
    ]
    assert {kind for kind, _ in existing_ai_resources} == existing_ai_kinds
    assert all(existing.strip() == "existing" for _, existing in existing_ai_resources)
    assert "param modelDeploymentName string = 'model-harness-gpt-5-6-sol'" in bicep
    assert "name: modelDeploymentName" in bicep
    assert re.search(
        r"@secure\(\)\s+@description\('[^']+'\)\s+param postgresAdministratorPassword string",
        bicep,
    )
    assert "placeholder-only" not in bicep
    azure_yaml = (ROOT / "azure.yaml").read_text()
    for parameter, schema, variable in (
        ("langgraphSchema", "langgraph_app_cutover", "LANGGRAPH_SCHEMA"),
        (
            "langgraphCheckpointSchema",
            "langgraph_checkpoints_cutover",
            "LANGGRAPH_CHECKPOINT_SCHEMA",
        ),
    ):
        assert f"param {parameter} string = '{schema}'" in bicep
        assert re.search(rf"name: '{variable}'\s+value: {parameter}\b", bicep)
        assert re.search(rf"name: {variable}\s+value: \$\{{{variable}\}}", azure_yaml)


def test_hosted_evaluation_keeps_reviewed_evaluator_and_model_pins():
    hosted_eval = (ROOT / "infra" / "foundry-hosted" / "agent" / "eval.yaml").read_text()
    assert re.findall(
        r'(?m)^  - name: (builtin\.\w+)\n    version: "(\d+)"[ \t]*$',
        hosted_eval,
    ) == [
        ("builtin.task_completion", "19"),
        ("builtin.relevance", "12"),
    ]
    assert "eval_model: model-harness-gpt-5-6-sol" in hosted_eval
    assert re.search(r"(?m)^max_samples: 4[ \t]*$", hosted_eval)


def test_foundry_guidance_keeps_runtime_prompts_and_tools_in_backend_source():
    marker = (
        "This project was built with the microsoft-foundry skill. Before working on "
        "or answering questions about foundry agents, read the microsoft-foundry skill first."
    )
    agents = (ROOT / "AGENTS.md").read_text()
    readme = (FOUNDRY / "README.md").read_text()

    assert marker in agents
    assert "Runtime prompts and tools remain backend source code" in readme
    assert "metadata, cache, and result storage only" in readme
