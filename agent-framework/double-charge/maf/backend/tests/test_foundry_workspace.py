from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_foundry_workspace_uses_single_environment_overlay_and_cache_layout() -> None:
    metadata = (ROOT / ".foundry" / "agent-metadata.yaml").read_text()
    assert "defaultEnvironment: local" in metadata
    assert "environments:" in metadata
    assert "evaluationSuites: []" in metadata
    assert "projectEndpoint" not in metadata
    assert "azureContainerRegistry" not in metadata
    assert "agentVersion" not in metadata
    for folder in ("suites", "datasets", "evaluators", "results"):
        assert (ROOT / ".foundry" / folder / "README.md").is_file()


def test_eval_intent_and_foundry_skill_marker_are_at_agent_root() -> None:
    assert (ROOT / "eval.yaml").is_file()
    assert "\nagent:" not in (ROOT / "eval.yaml").read_text()
    assert not (ROOT / "evals" / "eval.yaml").exists()
    marker = (
        "This project was built with the microsoft-foundry skill. Before working on "
        "or answering questions about foundry agents, read the microsoft-foundry skill first."
    )
    assert marker in (ROOT / "AGENTS.md").read_text()
