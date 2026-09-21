"""Verify the deliberately selected SDK/runtime pair without inference or authentication."""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

SDK_VERSION = "1.0.13"
RUNTIME_VERSION = "1.0.85"
PROTOCOL_VERSION = 3


def require_sdk() -> None:
    if version("github-copilot-sdk") != SDK_VERSION:
        raise ValueError("Installed Copilot SDK differs from the selected delivery version")


def validate_status(status: object) -> None:
    if (
        getattr(status, "version", None) != RUNTIME_VERSION
        or getattr(status, "protocol_version", None) != PROTOCOL_VERSION
    ):
        raise ValueError("Actual Copilot runtime version or protocol differs from delivery pins")


def selected_binary(binary: Path) -> str:
    if not binary.is_file() or binary.is_symlink() or not os.access(binary, os.X_OK):
        raise ValueError("Selected runtime must be an executable regular file")
    return str(binary.resolve())


async def verify_runtime(binary: Path, state: Path) -> None:
    require_sdk()
    from copilot import CopilotClient, RuntimeConnection

    client = CopilotClient(
        connection=RuntimeConnection.for_stdio(
            path=await asyncio.to_thread(selected_binary, binary)
        ),
        mode="empty",
        working_directory=str(state),
        base_directory=str(state),
        use_logged_in_user=False,
        log_level="error",
        env={
            "PATH": os.environ.get("PATH", ""),
            "HOME": str(state),
            "TMPDIR": str(state),
            "COPILOT_SKIP_CLI_DOWNLOAD": "true",
        },
    )
    try:
        async with asyncio.timeout(45):
            await client.start()
            validate_status(await client.get_status())
    finally:
        try:
            async with asyncio.timeout(10):
                await client.stop()
        except Exception:
            async with asyncio.timeout(10):
                await client.force_stop()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--state-root", required=True, type=Path)
    args = parser.parse_args()
    state = args.state_root.resolve() / f".runtime-verification-{uuid4().hex}"
    state.mkdir(parents=True, mode=0o700)
    try:
        asyncio.run(verify_runtime(args.binary, state))
    finally:
        shutil.rmtree(state)
    print(
        f"Verified SDK {SDK_VERSION}; actual runtime {RUNTIME_VERSION}; protocol {PROTOCOL_VERSION}"
    )


if __name__ == "__main__":
    main()
