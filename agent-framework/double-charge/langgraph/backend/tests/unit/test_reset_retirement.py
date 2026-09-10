import os
import subprocess
import sys
from pathlib import Path

import pytest

RESET = Path(__file__).resolve().parents[3] / "scripts" / "reset_db.py"


@pytest.mark.parametrize("arguments", [[], ["--force"], ["--confirm", "--local-only"]])
def test_retired_reset_cannot_mutate_storage_or_import_database_dependencies(arguments):
    result = subprocess.run(
        [sys.executable, "-S", str(RESET), *arguments],
        env={
            **os.environ,
            "DATABASE_URL": "postgresql://do-not-connect.invalid/production",
            "LANGGRAPH_SCHEMA": "langgraph_app_cutover",
            "LANGGRAPH_CHECKPOINT_SCHEMA": "langgraph_checkpoints_cutover",
        },
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 1
    assert result.stdout == ""
    assert "Database reset is disabled" in result.stderr
    assert "new, distinct LANGGRAPH_SCHEMA and LANGGRAPH_CHECKPOINT_SCHEMA" in result.stderr
    assert "scripts/setup_db.py" in result.stderr
    assert "left untouched" in result.stderr
    assert "do-not-connect" not in result.stderr
    assert "Traceback" not in result.stderr
