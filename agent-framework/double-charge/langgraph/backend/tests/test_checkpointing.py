import pytest
from model_to_harness_langgraph.checkpointing import checkpoint_conninfo
from psycopg.conninfo import conninfo_to_dict


def test_checkpoint_conninfo_preserves_connection_and_pins_search_path():
    raw = (
        "postgresql://app:local-password@db.example:5432/workflows"
        "?application_name=teaching&options=-cstatement_timeout%3D5000"
    )

    values = conninfo_to_dict(checkpoint_conninfo(raw, "langgraph_checkpoints"))

    assert values["host"] == "db.example"
    assert values["port"] == "5432"
    assert values["dbname"] == "workflows"
    assert values["application_name"] == "teaching"
    assert "-cstatement_timeout=5000" in values["options"]
    assert "-csearch_path=langgraph_checkpoints" in values["options"]


@pytest.mark.parametrize(
    "schema",
    ["public,evil", "LangGraph", "with-dash", "x;drop schema public"],
)
def test_checkpoint_conninfo_rejects_unsafe_schema(schema):
    with pytest.raises(ValueError, match="lowercase SQL identifier"):
        checkpoint_conninfo("postgresql://localhost/workflows", schema)

