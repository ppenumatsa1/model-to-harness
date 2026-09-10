import pytest
from model_to_harness_langgraph.application.ports import safe_event_data
from model_to_harness_langgraph.projections.state import public_state, selected_memory
from pydantic import ValidationError


def test_nested_event_usage_is_allowlisted_and_invalid_tool_objects_are_rejected():
    assert safe_event_data(
        {
            "usage": {"input_tokens": 9, "output_tokens": 4, "prompt": "SECRET"},
            "tool_arguments": {"token": "SECRET"},
        }
    ) == {"usage": {"input_tokens": 9, "output_tokens": 4}}
    with pytest.raises(ValidationError):
        safe_event_data({"tool": {"unrestricted": "SECRET"}})


def test_nested_public_state_and_memory_are_typed_allowlisted_projections():
    assert public_state(
        {
            "current_step": "join_validations",
            "checkpoint": {"secret": "SECRET"},
            "validation_results": {
                "billing": {"ok": True, "summary": "Validated", "raw_result": "SECRET"},
                "unrestricted_branch": {"SECRET": "SECRET"},
            },
        }
    ) == {
        "current_step": "join_validations",
        "validation_results": {"billing": {"ok": True, "summary": "Validated"}},
    }
    assert selected_memory({"case_id": "case-1", "credential": "SECRET"}) == {"case_id": "case-1"}
