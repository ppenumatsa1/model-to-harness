from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from textwrap import dedent


def test_safe_state_import_and_privacy_without_optional_ag_ui(tmp_path: Path) -> None:
    lane = Path(__file__).resolve().parents[3]
    script = dedent("""
        import importlib.abc
        import json
        import sys

        sys.path[:0] = sys.argv[1:]

        class DenyAgUi(importlib.abc.MetaPathFinder):
            def find_spec(self, fullname, path=None, target=None):
                if fullname == "ag_ui" or fullname.startswith("ag_ui."):
                    raise ModuleNotFoundError("AG-UI must remain optional", name=fullname)
                return None

        sys.meta_path.insert(0, DenyAgUi())
        from maf_double_charge.application.models import BranchResult, WorkflowState
        from maf_double_charge.projections.workspace import safe_state

        state = WorkflowState(
            case_id="PRIVATE-case", run_id="PRIVATE-run", complaint="PRIVATE-complaint",
            customer_id="PRIVATE-customer", scenario_id="duplicate-confirmed",
            idempotency_key="PRIVATE-key", checkpoint_id="PRIVATE-checkpoint",
            duplicate_found=True, duplicate_summary="Duplicate charge confirmed.",
            duplicate_evidence={"prompt": "PRIVATE-prompt"},
            billing_validation=BranchResult(
                branch="billing_validation", ok=True, summary="Billing validated.",
                evidence={"checked_charge_ids": ["charge-1"], "credentials": "PRIVATE-secret",
                          "raw_result": {"password": "PRIVATE-password"}},
            ),
            policy_validation=BranchResult(
                branch="policy_validation", ok=True, summary="Refund allowed.",
                evidence={"policy_code": "duplicate-charge", "decision": "allow",
                          "tool_arguments": "PRIVATE-arguments"},
            ),
        )
        projected = safe_state(state)
        assert projected.billing_validation.evidence == {"checked_charge_ids": ["charge-1"]}
        assert projected.policy_validation.evidence == {
            "policy_code": "duplicate-charge", "decision": "allow",
        }
        investigation = projected.model_dump(mode="json", include={
            "duplicate_found", "duplicate_summary", "billing_validation", "policy_validation",
        })
        assert investigation["duplicate_found"] is True
        assert investigation["duplicate_summary"] == "Duplicate charge confirmed."
        assert investigation["billing_validation"]["ok"] is True
        assert investigation["policy_validation"]["ok"] is True
        assert "PRIVATE" not in json.dumps(investigation)
        assert not any(name == "ag_ui" or name.startswith("ag_ui.") for name in sys.modules)
        print("safe_state import, findings and privacy passed without AG-UI")
    """)
    result = subprocess.run(
        [
            sys.executable, "-I", "-B", "-c", script,
            str(lane / "backend/src"), str(lane.parents[2] / "shared/src"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "safe_state import, findings and privacy passed without AG-UI" in result.stdout
