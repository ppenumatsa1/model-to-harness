import json
import runpy
from pathlib import Path

import pytest

grade = runpy.run_path(str(Path(__file__).resolve().parents[2] / "evals/start_contract.py"))[
    "grade"
]
accepted_scores = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "scripts/collect_evaluation.py")
)["accepted_scores"]


def test_mapped_and_native_response_namespaces():
    response = json.dumps({"harness_mode": "maf", "verification_result": None})
    expected = json.dumps({"harness_mode": "maf", "verification_result": None})
    assert grade({}, {"response": response, "expected_behavior": expected}) == 1
    assert grade({"output_text": response}, {"expected_behavior": expected}) == 1
    assert grade({}, {"sample.output_text": response, "expected_behavior": expected}) == 1


@pytest.mark.parametrize(
    "actual",
    [
        {"harness_mode": "maf"},
        {"harness_mode": "scripted", "verification_result": None},
        {"harness_mode": "maf", "verification_result": None, "prompt": "forbidden"},
        {"harness_mode": "maf", "verification_result": False},
    ],
)
def test_missing_null_wrong_mode_extra_content_and_wrong_value_fail(actual):
    assert (
        grade(
            {},
            {
                "response": json.dumps(actual),
                "expected_behavior": '{"harness_mode":"maf","verification_result":null}',
            },
        )
        == 0
    )


def test_boolean_is_not_interchangeable_with_number():
    assert (
        grade(
            {},
            {
                "response": '{"harness_mode":"maf","verification_result":0}',
                "expected_behavior": '{"verification_result":false}',
            },
        )
        == 0
    )


@pytest.mark.parametrize("response", ["invalid", "[]", "null", None])
def test_invalid_response_fails(response):
    assert grade({}, {"response": response, "expected_behavior": '{"harness_mode":"maf"}'}) == 0


@pytest.mark.parametrize("expected", ["invalid", "[]", "null", "{}"])
def test_invalid_or_empty_expectations_fail(expected):
    assert (
        grade(
            {},
            {"response": '{"harness_mode":"maf"}', "expected_behavior": expected},
        )
        == 0
    )


def test_missing_response_fails():
    assert grade({}, {"expected_behavior": '{"harness_mode":"maf"}'}) == 0


@pytest.mark.parametrize(
    "results",
    [
        [],
        [{"passed": True, "score": None}],
        [{"passed": None, "score": 1}],
        [{"passed": True, "score": True}],
        [{"passed": True, "score": float("nan")}],
        [{"passed": True, "score": 0}],
        [{"passed": False, "score": 1}],
        [{"passed": True, "score": 1}, {"passed": None, "score": None}],
    ],
)
def test_missing_invalid_or_partial_cloud_scores_fail(results):
    assert accepted_scores(results) is False


def test_all_cloud_scores_must_pass():
    assert accepted_scores([{"passed": True, "score": 1.0}]) is True
