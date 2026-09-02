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

    bicep = (ROOT / "infra" / "main.bicep").read_text()
    assert "param location string = 'northcentralus'" in bicep
    assert "gpt-5.6-sol" in bicep
    assert "@secure()" in bicep
    assert "placeholder-only" not in bicep


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
