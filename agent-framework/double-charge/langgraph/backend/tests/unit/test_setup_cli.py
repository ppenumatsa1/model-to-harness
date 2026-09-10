import subprocess
import sys
from pathlib import Path

import pytest
from model_to_harness_langgraph.config import Settings
from model_to_harness_langgraph.infrastructure.persistence.migrations import setup_storage

SETUP = Path(__file__).resolve().parents[3] / "scripts" / "setup_db.py"


async def test_conflicting_setup_modes_rejected_before_any_connection():
    with pytest.raises(ValueError, match="mutually exclusive"):
        await setup_storage(
            Settings(_env_file=None, database_url="must-not-connect"),
            verify_only=True,
            require_fresh=True,
        )


def test_setup_cli_rejects_conflicting_modes():
    result = subprocess.run(
        [sys.executable, str(SETUP), "--require-fresh", "--verify-only"],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )
    assert result.returncode == 2
    assert "not allowed with argument" in result.stderr
    assert "Traceback" not in result.stderr
