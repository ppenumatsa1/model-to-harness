"""Verify prepared source isolation, ZIP allowlist and the pinned native runtime offline."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from hashlib import sha256
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from prepare_hosted import AGENT_ROOT, LANE_ROOT, runtime_files, source_file, verify_code_archive
from verify_release_dependencies import RELEASE_HOLD, require_release_dependencies


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-runtime", action="store_true")
    args = parser.parse_args()
    require_release_dependencies(LANE_ROOT / "requirements-cloud.lock")
    try:
        requirements = (AGENT_ROOT / "requirements.txt").read_text()
    except (OSError, UnicodeError):
        raise SystemExit(RELEASE_HOLD) from None
    require_release_dependencies(
        LANE_ROOT / "requirements-cloud.lock", requirements=requirements, installed=True
    )
    from cloud_dependencies import verify

    verify(installed=True)
    files = {name: AGENT_ROOT / name for name in ("main.py", "requirements.txt", "eval.yaml")}
    for package in ("checkout_recovery_copilot", "model_to_harness_shared"):
        root = AGENT_ROOT / package
        files.update(
            {
                path.relative_to(AGENT_ROOT).as_posix(): path
                for path in root.rglob("*")
                if path.is_file() and source_file(path.relative_to(root))
            }
        )
    runtime = runtime_files(AGENT_ROOT)
    if args.require_runtime and not runtime:
        raise SystemExit("Prepare with --with-runtime before verifying a deployable package")
    files.update(runtime)
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, path in files.items():
            archive.write(path, name)
    content = output.getvalue()
    result = verify_code_archive(AGENT_ROOT, content, sha256(content).hexdigest())
    env = {
        **os.environ,
        "PYTHONPATH": str(AGENT_ROOT),
        "COPILOT_CLI_EXTRACT_DIR": str(AGENT_ROOT / "copilot-runtime"),
        "COPILOT_SKIP_CLI_DOWNLOAD": "true",
    }
    subprocess.run(
        [
            sys.executable,
            "-c",
            "import main; from importlib.resources import files; "
            "from pathlib import Path; import checkout_recovery_copilot as package; "
            "assert Path(package.__file__).resolve().is_relative_to(Path.cwd()); "
            "import model_to_harness_shared as shared; "
            "assert Path(shared.__file__).resolve().is_relative_to(Path.cwd()); "
            "from checkout_recovery_copilot.sdk import CopilotInvestigator; "
            "assert files('checkout_recovery_copilot').joinpath("
            "'sdk/skills/checkout-triage/SKILL.md').is_file()",
        ],
        cwd=AGENT_ROOT,
        env=env,
        check=True,
    )
    if runtime:
        subprocess.run(
            [
                sys.executable,
                str(LANE_ROOT / "scripts/verify_native_runtime.py"),
                "--binary",
                str(AGENT_ROOT / "copilot-runtime/prebuilds/linux-x64/copilot-runtime"),
                "--state-root",
                str(AGENT_ROOT),
            ],
            cwd=AGENT_ROOT,
            env=env,
            check=True,
            timeout=90,
        )
    print(
        f"Verified Hosted source ZIP: {result['files']} files; native runtime={bool(runtime)}; "
        f"sha256={result['archive_sha256']}; bytes={len(content)}"
    )


if __name__ == "__main__":
    main()
