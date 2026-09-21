"""Exercise the real pinned runtime with a local scripted Responses peer.

Default mode makes no cloud calls. --azure uses the configured Foundry deployment
and refreshing Entra credential. Receipts contain only bounded evidence metadata.
Neither mode writes raw conversation archives or model output to the receipt.
"""

import argparse
import asyncio
import json
import os
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from aiohttp import web
from checkout_recovery_copilot.sdk import archive, investigation
from checkout_recovery_copilot.sdk.cancellation import cancellation_scope
from model_to_harness_shared import CheckoutSimulator, get_checkout_fixture


class LocalCredential:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        pass

    async def get_token(self, scope):
        assert scope == "https://ai.azure.com/.default"
        return SimpleNamespace(token="synthetic-local-probe")


class ScriptedResponses:
    """Protocol fixture only: the real native runtime still executes every tool."""

    def __init__(self, delegate=False, failure=None):
        self.calls = 0
        self.allowed_tools = set()
        self.delegate = delegate
        self.main_steps = 0
        self.child_steps = 0
        self.resumed_context_observed = False
        self.failure = failure
        self.reasoning_keys = set()
        self.wire_models = set()
        self.request_received = asyncio.Event()

    async def respond(self, request):
        body = await request.json()
        self.wire_models.add(body.get("model"))
        reasoning = body.get("reasoning", {})
        if isinstance(reasoning, dict):
            self.reasoning_keys.update(key for key in reasoning if key in {"summary", "effort"})
        tools = {tool["name"]: tool for tool in body.get("tools", []) if "name" in tool}
        self.allowed_tools.update(tools)
        self.calls += 1
        self.request_received.set()
        if self.failure == "protocol":
            return web.json_response(
                {"error": {"message": "SYNTHETIC-PRIVATE-ERROR-CANARY"}}, status=400
            )
        if self.failure in {"timeout", "cancellation"}:
            await asyncio.sleep(10)
        if self.calls > 24:
            return web.json_response({"error": {"message": "local probe budget"}}, status=429)
        child = len(tools) == 1
        if child:
            sequence = ["read_inventory", None]
            step = self.child_steps % len(sequence)
            self.child_steps += 1
        else:
            sequence = [
                "skill",
                "read_order",
                "read_payment",
                "delegate_inventory" if self.delegate else "read_inventory",
                "write_plan",
                "read_plan",
                None,
            ]
            step = self.main_steps % len(sequence)
            if self.main_steps >= len(sequence) and step == 0:
                self.resumed_context_observed = "Diagnostic evidence gathered." in json.dumps(
                    body.get("input", [])
                )
            self.main_steps += 1
        name = sequence[step]
        if self.failure in {"model-budget", "tool-budget"}:
            name = "read_order"
        elif self.failure == "permission":
            name = "skill"
        response_id = f"resp_{uuid4().hex}"
        if name:
            actual = next((key for key in tools if key.split(".")[-1] == name), name)
            arguments = (
                {"skill": "checkout-triage"}
                if name == "skill"
                else {
                    "content": "Inspect order, payment, and inventory. Verify before remediation."
                }
                if name == "write_plan"
                else {}
            )
            if self.failure == "permission":
                arguments = {"skill": "unapproved-skill"}
            item = {
                "type": "function_call",
                "id": f"fc_{uuid4().hex}",
                "call_id": f"call_{uuid4().hex}",
                "name": actual,
                "arguments": json.dumps(arguments),
                "status": "completed",
            }
        else:
            item = {
                "type": "message",
                "id": f"msg_{uuid4().hex}",
                "role": "assistant",
                "status": "completed",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Diagnostic evidence gathered.",
                        "annotations": [],
                    }
                ],
            }
        items = [item]
        if self.failure == "tool-budget":
            items = [
                {**item, "id": f"fc_{uuid4().hex}", "call_id": f"call_{uuid4().hex}"}
                for _ in range(25)
            ]
        response = {
            "id": response_id,
            "object": "response",
            "created_at": int(time.time()),
            "model": body.get("model", "deployment"),
            "status": "completed",
            "output": items,
            "usage": {
                "input_tokens": 10,
                "output_tokens": 10,
                "total_tokens": 20,
                "input_tokens_details": {"cached_tokens": 0},
                "output_tokens_details": {"reasoning_tokens": 0},
            },
        }
        if not body.get("stream"):
            return web.json_response(response)
        events = [
            ("response.created", {"response": {**response, "status": "in_progress", "output": []}}),
        ]
        for output_index, item in enumerate(items):
            events.append(
                ("response.output_item.added", {"output_index": output_index, "item": item})
            )
            if name:
                events.extend(
                    [
                        (
                            "response.function_call_arguments.delta",
                            {
                                "item_id": item["id"],
                                "output_index": output_index,
                                "delta": item["arguments"],
                            },
                        ),
                        (
                            "response.function_call_arguments.done",
                            {
                                "item_id": item["id"],
                                "output_index": output_index,
                                "arguments": item["arguments"],
                            },
                        ),
                    ]
                )
            else:
                events.extend(
                    [
                        (
                            "response.content_part.added",
                            {
                                "item_id": item["id"],
                                "output_index": 0,
                                "content_index": 0,
                                "part": {"type": "output_text", "text": "", "annotations": []},
                            },
                        ),
                        (
                            "response.output_text.delta",
                            {
                                "item_id": item["id"],
                                "output_index": 0,
                                "content_index": 0,
                                "delta": item["content"][0]["text"],
                            },
                        ),
                        (
                            "response.output_text.done",
                            {
                                "item_id": item["id"],
                                "output_index": 0,
                                "content_index": 0,
                                "text": item["content"][0]["text"],
                            },
                        ),
                        (
                            "response.content_part.done",
                            {
                                "item_id": item["id"],
                                "output_index": 0,
                                "content_index": 0,
                                "part": item["content"][0],
                            },
                        ),
                    ]
                )
            events.append(
                ("response.output_item.done", {"output_index": output_index, "item": item})
            )
        events.append(("response.completed", {"response": response}))
        text = "".join(
            f"event: {kind}\ndata: {json.dumps({'type': kind, 'sequence_number': i, **data})}\n\n"
            for i, (kind, data) in enumerate(events)
        )
        return web.Response(text=text, content_type="text/event-stream")


async def main(args):
    fixture = get_checkout_fixture("recoverable-inventory-reservation")
    simulator = CheckoutSimulator(
        order=fixture.order,
        payment_attempt=fixture.payment_attempt,
        reservation=fixture.reservation,
    )
    runner = None
    peer = None
    processes = []
    client_type = investigation.CopilotClient

    class ObservedClient(client_type):
        async def start(self):
            await super().start()
            if self._cli_process is not None:
                processes.append(self._cli_process)

    investigation.CopilotClient = ObservedClient
    if args.azure:
        from checkout_recovery_copilot.config import Settings

        settings = Settings()
        endpoint = os.getenv("AZURE_AI_PROJECT_ENDPOINT") or settings.foundry_project_endpoint
        model = os.getenv("AZURE_AI_MODEL_DEPLOYMENT_NAME") or settings.foundry_model_deployment
        if not endpoint or not model:
            raise ValueError("configure a Foundry project endpoint and model deployment")
    else:
        peer = ScriptedResponses(delegate=args.delegate, failure=args.failure)
        application = web.Application()
        application.router.add_post("/openai/v1/responses", peer.respond)
        runner = web.AppRunner(application, access_log=None, shutdown_timeout=0.1)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        endpoint = "https://synthetic.services.ai.azure.com/api/projects/local"
        model = os.getenv("COPILOT_PROBE_MODEL", "deployment")
        investigation.DefaultAzureCredential = LocalCredential
        investigation.ManagedIdentityCredential = LocalCredential
    harness = investigation.CopilotInvestigator(
        endpoint,
        model,
        connection_string=None if args.azure else "",
        trace_file=args.trace_file,
    )
    if peer:
        harness.endpoint = f"http://127.0.0.1:{port}/openai/v1/"
    if args.failure == "timeout":
        harness.timeout = 3
    receipt = {
        "mode": "azure" if args.azure else "local-scripted-responses",
        **investigation.safe_provider_metadata(harness.endpoint, model, scripted=peer is not None),
        "passed": False,
    }
    try:
        if args.failure == "cancellation":
            signal = threading.Event()
            with cancellation_scope(signal):
                worker = asyncio.create_task(asyncio.to_thread(harness.investigate, simulator))
            try:
                await asyncio.wait_for(peer.request_received.wait(), timeout=10)
            finally:
                signal.set()
            first = await worker
        else:
            first = await asyncio.to_thread(harness.investigate, simulator)
        second = await asyncio.to_thread(harness.resume_native, simulator, first.framework_state)
        receipt.update(
            {
                "passed": True,
                "provenance": first.framework_state["provenance"],
                "first": first.framework_state["evidence"],
                "resumed": second.framework_state["evidence"],
                "same_session": first.framework_state["session_id"]
                == second.framework_state["session_id"],
                "native_files": sorted(
                    {name for files in first.framework_state["sessions"].values() for name in files}
                ),
            }
        )
    except asyncio.CancelledError:
        if args.failure != "cancellation":
            raise
        receipt["failure_kind"] = "CancelledError"
        receipt["expected_failure"] = "cancellation"
    except Exception as error:
        receipt["failure_kind"] = type(error).__name__
        # Our own fixed failure labels are safe; SDK exception payloads are not.
        if isinstance(error, investigation.InvestigationIncompleteError):
            receipt["failure"] = str(error)
        if not args.failure:
            raise
        receipt["expected_failure"] = args.failure
    finally:
        if runner:
            await runner.cleanup()
        if peer:
            receipt["model_calls"] = peer.calls
            receipt["offered_tool_names"] = sorted(peer.allowed_tools)
            receipt["resumed_context_sent_to_model"] = peer.resumed_context_observed
            receipt["responses_reasoning_keys"] = sorted(peer.reasoning_keys)
            receipt["wire_model_matches_deployment"] = peer.wire_models == {model}
        receipt["owned_processes"] = len(processes)
        receipt["all_owned_processes_exited"] = all(p.poll() is not None for p in processes)
        if args.failure:
            boundary_message = {
                "permission": "tool boundary or budget exceeded",
                "tool-budget": "tool boundary or budget exceeded",
                "model-budget": "observed model attempt budget exceeded",
            }.get(args.failure)
            if boundary_message:
                receipt["boundary_rejection_observed"] = receipt.get("failure") == boundary_message
            receipt["passed"] = (
                receipt.get("failure_kind") == "InvestigationIncompleteError"
                and bool(peer and peer.calls)
                and bool(processes)
                and receipt["all_owned_processes_exited"]
                and (boundary_message is None or receipt["boundary_rejection_observed"])
            )
        label = args.failure or (
            "azure" if args.azure else "delegate" if args.delegate else "native"
        )
        target = args.receipt_directory / f"report.{label}.json"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt, indent=2))
        if not receipt["passed"]:
            raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--azure", action="store_true")
    parser.add_argument("--delegate", action="store_true")
    parser.add_argument("--trace-file", type=Path, default=os.getenv("CHECKOUT_COPILOT_TRACE_FILE"))
    parser.add_argument(
        "--receipt-directory",
        type=Path,
        default=Path(".acceptance") / f"sdk-{archive.SDK_VERSION}" / "local-native",
    )
    mode.add_argument(
        "--failure",
        choices=[
            "protocol",
            "timeout",
            "cancellation",
            "permission",
            "model-budget",
            "tool-budget",
        ],
    )
    asyncio.run(main(parser.parse_args()))
