"""Deterministic Foundry grader; approval/resume have a separate command E2E gate."""

import json


def grade(sample, item):
    try:
        if "response" in item:
            response = item["response"]
        elif "sample.output_text" in item:
            response = item["sample.output_text"]
        else:
            response = sample["output_text"]
        actual = json.loads(response)
        expected = json.loads(item["expected_behavior"])
    except (KeyError, TypeError, ValueError):
        return 0.0
    if not isinstance(actual, dict) or actual.get("harness_mode") != "maf":
        return 0.0
    if not isinstance(expected, dict) or not expected:
        return 0.0
    allowed = {
        "case_id",
        "run_id",
        "fixture_id",
        "phase",
        "diagnostic_disposition",
        "approval_decision",
        "approval_request_id",
        "diagnostic_tools",
        "harness_mode",
        "remediation_action",
        "remediation_status",
        "verification_result",
        "terminal_status",
        "failure_code",
        "workspace_artifact",
    }
    if set(actual) - allowed:
        return 0.0
    return float(
        all(
            key in actual and type(actual[key]) is type(value) and actual[key] == value
            for key, value in expected.items()
        )
    )
