"""Foundry inference-only native continuity proof across fresh Python processes.

Only bounded receipts survive. The opaque native archive moves between workers
in a private ignored directory and is removed after verification.
"""

import argparse
import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from checkout_recovery_copilot.sdk.archive import SDK_VERSION


def worker(phase: str, directory: Path, marker: str, require_delegation: bool) -> int:
    from checkout_recovery_copilot.config import Settings
    from checkout_recovery_copilot.sdk import investigation
    from model_to_harness_shared import CheckoutSimulator, get_checkout_fixture

    settings = Settings()
    if not settings.foundry_project_endpoint or not settings.foundry_model_deployment:
        raise ValueError("comparison model configuration is required")
    fixture = get_checkout_fixture("recoverable-inventory-reservation")
    simulator = CheckoutSimulator(
        order=fixture.order,
        payment_attempt=fixture.payment_attempt,
        reservation=fixture.reservation,
    )
    processes = []
    native_errors = []
    client_type = investigation.CopilotClient
    event_handler = investigation.Evidence.event

    def observed_event(self, event):
        if getattr(event.type, "value", event.type) == "session.error":
            data = event.data
            message = getattr(data, "message", "").lower()
            status = getattr(data, "status_code", None)
            native_errors.append(
                {
                    "http_status": status if isinstance(status, int) else None,
                    "signals": [
                        label
                        for label in (
                            "authentication",
                            "unauthorized",
                            "token",
                            "401",
                            "403",
                            "404",
                            "deployment",
                            "api-version",
                            "unsupported",
                            "reasoning",
                            "max_output_tokens",
                            "rate limit",
                            "429",
                            "reasoning.effort",
                            "reasoning.summary",
                            "reasoning_effort",
                            "reasoning_summary",
                            "max_output_tokens",
                            "rate limit",
                            "429",
                            "connection",
                            "credential",
                            "azure cli",
                            "azure_token_credentials",
                        )
                        if label in message
                    ],
                }
            )
        return event_handler(self, event)

    investigation.Evidence.event = observed_event

    class ObservedClient(client_type):
        async def start(self):
            await super().start()
            if self._cli_process is not None:
                processes.append(self._cli_process)

    investigation.CopilotClient = ObservedClient
    harness = investigation.CopilotInvestigator(
        settings.foundry_project_endpoint,
        settings.foundry_model_deployment,
        connection_string="",
        trace_file=directory / "native-spans.jsonl",
    )
    state_file = directory / "private-native-state.json"
    receipt = {
        "phase": phase,
        "passed": False,
        "worker_pid": os.getpid(),
        "delegation_required": require_delegation,
        **investigation.safe_provider_metadata(harness.endpoint, harness.model, scripted=False),
    }
    try:
        if phase == "initial":
            investigation.PROMPT = (
                "Investigate this synthetic failed checkout using the checkout-triage skill. "
                "Complete the required evidence reads and write/read plan.md. "
                f"The synthetic continuity marker is {marker}. "
                "Include this marker in your final recommendation."
            )
            if require_delegation:
                investigation.PROMPT += (
                    " For this invocation, use delegate_inventory exactly once instead of "
                    "reading inventory directly, so the inventory specialist actually executes."
                )
            result = harness.investigate(simulator)
        else:
            investigation.PROMPT = (
                "This is a fresh-process follow-up on the same synthetic checkout. "
                "Invoke checkout-triage again, re-read order/payment/inventory, and write/read "
                "a new short plan.md. Include the exact synthetic continuity marker from the "
                "earlier user request in your final recommendation. It is deliberately not "
                "repeated in this request. Do not perform remediation."
            )
            if require_delegation:
                investigation.PROMPT += (
                    " For this new invocation, use delegate_inventory exactly once instead "
                    "of reading inventory directly."
                )
            saved = json.loads(state_file.read_text())
            result = harness.resume_native(simulator, saved)
            receipt["same_native_session"] = (
                saved["session_id"] == result.framework_state["session_id"]
            )
        state = result.framework_state
        event_bytes = base64.b64decode(
            state["sessions"][state["session_id"]]["events.jsonl"], validate=True
        )
        # Verification only, not a transcript adapter: native bytes are archived
        # unchanged and interpreted by the runtime when the next worker resumes.
        events = [json.loads(line) for line in event_bytes.splitlines() if line]
        replies = [
            entry.get("data", {}).get("content", "")
            for entry in events
            if entry.get("type") == "assistant.message"
        ]
        recalled = bool(replies and marker in replies[-1])
        receipt.update(
            {
                "passed": recalled,
                "marker_recalled": recalled,
                "provenance": state["provenance"],
                "evidence": state["evidence"],
                "native_file_count": sum(len(files) for files in state["sessions"].values()),
            }
        )
        if require_delegation:
            receipt["passed"] = receipt["passed"] and (
                state["evidence"]["child_completed"]
                and state["evidence"]["delegation_mode"] == "bounded_child_session"
                and len(state["sessions"]) == 2
            )
        if phase == "initial":
            state_file.write_text(json.dumps(state))
            state_file.chmod(0o600)
        elif not receipt.get("same_native_session"):
            receipt["passed"] = False
    except Exception as error:
        receipt["failure_kind"] = type(error).__name__
        if isinstance(error, investigation.InvestigationIncompleteError):
            receipt["failure"] = str(error)
    finally:
        receipt["owned_process_count"] = len(processes)
        receipt["native_error_metadata"] = native_errors
        receipt["all_owned_processes_exited"] = all(p.poll() is not None for p in processes)
        receipt["passed"] = (
            receipt["passed"] and bool(processes) and (receipt["all_owned_processes_exited"])
        )
        path = directory / f"receipt.{phase}.json"
        path.write_text(json.dumps(receipt, indent=2) + "\n")
        path.chmod(0o600)
        print(json.dumps(receipt, indent=2))
    return 0 if receipt["passed"] else 1


def main(args) -> int:
    directory = args.directory.resolve()
    if args.phase:
        return worker(args.phase, directory, args.marker, args.require_delegation)
    # Refuse to place opaque native transcripts in a tracked/unignored location.
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", str(directory / "private-native-state.json")],
        check=False,
    )
    if ignored.returncode:
        raise SystemExit("acceptance directory must be git-ignored")
    directory.mkdir(parents=True, mode=0o700)
    marker = "CHECKOUT-CONTINUITY-" + uuid4().hex
    environment = {**os.environ, "AZURE_TOKEN_CREDENTIALS": "AzureCliCredential"}
    result = 0
    try:
        for phase in ("initial", "resume"):
            completed = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve()),
                    "--phase",
                    phase,
                    "--directory",
                    str(directory),
                    "--marker",
                    marker,
                    *(["--require-delegation"] if args.require_delegation else []),
                ],
                env=environment,
                timeout=155,
                check=False,
            )
            result = completed.returncode
            if result:
                break
    finally:
        (directory / "private-native-state.json").unlink(missing_ok=True)
    receipts = [json.loads(path.read_text()) for path in sorted(directory.glob("receipt.*.json"))]
    summary = {
        "passed": result == 0 and len(receipts) == 2 and all(x["passed"] for x in receipts),
        "distinct_python_processes": len({x["worker_pid"] for x in receipts}) == 2,
        "raw_archive_removed": not (directory / "private-native-state.json").exists(),
        "model_source": "configured_foundry_deployment_inference_only",
        **{
            key: receipts[0].get(key, "unknown") if receipts else "unknown"
            for key in ("provider_mode", "endpoint_host", "model_deployment")
        },
    }
    (directory / "receipt.summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    return 0 if summary["passed"] and summary["distinct_python_processes"] else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--directory",
        type=Path,
        default=Path(".acceptance") / f"sdk-{SDK_VERSION}" / "azure" / uuid4().hex,
    )
    parser.add_argument("--require-delegation", action="store_true")
    parser.add_argument("--phase", choices=["initial", "resume"], help=argparse.SUPPRESS)
    parser.add_argument("--marker", default="", help=argparse.SUPPRESS)
    raise SystemExit(main(parser.parse_args()))
