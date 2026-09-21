"""Local, no-model native runtime gate. Receipts contain metadata, never state."""

import asyncio
import json
import shutil
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

from checkout_recovery_copilot.sdk import archive
from checkout_recovery_copilot.sdk.investigation import cached_runtime_path
from copilot import CopilotClient, RuntimeConnection
from copilot._cli_version import CLI_VERSION
from copilot.generated.rpc import PermissionDecisionReject


async def main() -> None:
    binary = cached_runtime_path()
    if not binary:
        raise RuntimeError("explicit pinned native runtime must already be provisioned")
    assert version("github-copilot-sdk") == archive.SDK_VERSION
    root = await asyncio.to_thread(
        (Path(".acceptance") / f"sdk-{archive.SDK_VERSION}" / "capabilities").resolve
    )
    directory = root / uuid4().hex
    directory.mkdir(parents=True, mode=0o700)
    scratch = directory / "runtime-scratch"
    scratch.mkdir(mode=0o700)
    receipt = {
        "sdk_version": version("github-copilot-sdk"),
        "expected_sdk": archive.SDK_VERSION,
        "expected_runtime": archive.RUNTIME_VERSION,
        "sdk_default_runtime": CLI_VERSION,
        "provider_mode": "no_model_capability_probe",
        "endpoint_host": "127.0.0.1",
        "model_deployment": "local-capability-gate",
    }
    client = CopilotClient(
        connection=RuntimeConnection.for_stdio(path=binary),
        mode="empty",
        base_directory=str(directory / "native"),
        working_directory=str(directory),
        use_logged_in_user=False,
        log_level="error",
        env={"HOME": str(directory), "TMPDIR": str(scratch)},
    )
    try:
        await client.start()
        status = await client.get_status()
        assert status.version == archive.RUNTIME_VERSION == "1.0.85"
        assert status.protocol_version == 3
        receipt["runtime_version"] = status.version
        receipt["protocol_version"] = status.protocol_version
        skill_path = await asyncio.to_thread(Path(__file__).resolve)
        session = await client.create_session(
            session_id=str(uuid4()),
            model="local-capability-gate",
            provider={
                "type": "openai",
                "base_url": "http://127.0.0.1:1/v1",
                "api_key": "no-network-probe",
            },
            available_tools=["builtin:skill"],
            on_permission_request=lambda *_: PermissionDecisionReject(),
            enable_config_discovery=False,
            skip_custom_instructions=True,
            enable_skills=True,
            included_builtin_skills=[],
            skill_directories=[
                str(skill_path.parents[1] / "backend/src/checkout_recovery_copilot/sdk/skills")
            ],
            enable_session_store=True,
            enable_host_git_operations=False,
            enable_file_hooks=False,
            infinite_sessions={"enabled": True},
        )
        receipt["session_created"] = bool(session.session_id)
        await session.disconnect()
        receipt["disconnected"] = True
        await client.stop()
        receipt["native_files"] = sorted(
            str(path.relative_to(directory)) for path in directory.rglob("*") if path.is_file()
        )
    finally:
        await client.force_stop()
        shutil.rmtree(directory)
    target = root / "report.capabilities.json"
    target.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
