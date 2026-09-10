from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

LANE = next(
    parent
    for parent in Path(__file__).resolve().parents
    if (parent / "azure.yaml").is_file() and (parent / "pyproject.toml").is_file()
)
SPEC = importlib.util.spec_from_file_location(
    "download_eval_results", LANE / "scripts" / "download_eval_results.py"
)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_eval_summary_does_not_turn_missing_scores_into_passes() -> None:
    items = [
        {"results": [{"name": "relevance", "passed": True}]},
        {"results": [{"name": "relevance", "passed": False}]},
        {"results": [{"name": "relevance", "passed": None}]},
        {"status": "pass", "results": []},
        {"error": {"code": "runtime_failed"}},
        {"status": "fail", "results": []},
        {"results": [{"name": "relevance", "error": {"code": "grader_failed"}}]},
    ]
    assert MODULE.summarize_items(items) == {
        "total": 7,
        "passed": 1,
        "failed": 2,
        "errored": 2,
        "unscored": 2,
    }


def test_custom_score_requires_a_matching_explicit_decision() -> None:
    paired = {
        "results": [
            {"name": "business", "metric": "custom_score", "score": 1, "passed": None},
            {"name": "business", "metric": "business", "passed": True, "reason": "Valid."},
        ]
    }
    assert MODULE.summarize_items([paired])["passed"] == 1
    paired["results"][1]["name"] = "another-evaluator"
    assert MODULE.summarize_items([paired])["unscored"] == 1


def test_invalid_results_are_explicit_errors() -> None:
    with pytest.raises(ValueError, match="must contain objects"):
        MODULE.summarize_items([{"results": ["invalid"]}])


def test_eval_report_is_persisted_with_private_permissions(tmp_path: Path) -> None:
    output = tmp_path / "results" / "run.json"
    MODULE.write_report(output, {"counts": {"passed": 1}, "items": []})
    assert json.loads(output.read_text())["counts"]["passed"] == 1
    assert output.stat().st_mode & 0o777 == 0o600
    assert list(output.parent.iterdir()) == [output]
