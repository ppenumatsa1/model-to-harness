"""Verify version-pinned Responses commands with individually owned sessions."""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from api_harness import SCENARIOS, AcceptanceError, require, verify_outcome
from release import SERVICE, ReleaseError, Runner, active_agent, azd_args, environment_values

if TYPE_CHECKING:
    from azure.ai.projects import AIProjectClient
    from openai import OpenAI


def response_result(raw: str) -> dict[str, Any]:
    try:
        body = raw.strip().replace("\r\n", "\n")
        if body.startswith("HTTP/"):
            header, separator, body = body.partition("\n\n")
            status = header.splitlines()[0].split()
            require(
                bool(separator) and len(status) > 1 and status[1].startswith("2"),
                "Hosted command did not return HTTP success",
            )
        response = None
        if body.lstrip().startswith("{"):
            response = json.loads(body)
        else:
            for frame in body.split("\n\n"):
                data = "\n".join(
                    line[5:].lstrip() for line in frame.splitlines() if line.startswith("data:")
                )
                if not data or data == "[DONE]":
                    continue
                event = json.loads(data)
                require(isinstance(event, dict), "Malformed Responses event")
                require(
                    event.get("type") not in {"error", "response.failed", "response.incomplete"},
                    "Hosted Responses stream failed or was incomplete",
                )
                if event.get("type") == "response.completed":
                    require(response is None, "Multiple completed Responses in one command")
                    response = event.get("response")
        require(isinstance(response, dict), "Hosted stream lacks a completed response")
        require(
            response.get("status") == "completed" and not response.get("error"),
            "Hosted response was not completed successfully",
        )
        texts = [
            content["text"]
            for output in response.get("output", [])
            if isinstance(output, dict) and output.get("type") == "message"
            for content in output.get("content", [])
            if isinstance(content, dict)
            and content.get("type") == "output_text"
            and isinstance(content.get("text"), str)
        ]
        require(len(texts) == 1, "Expected one structured hosted command result")
        result = json.loads(texts[0])
        require(
            isinstance(result, dict) and result.get("ok") is True,
            "Hosted workflow command returned an application error",
        )
        case = result.get("case")
        require(
            isinstance(case, dict) and bool(case.get("case_id")) and bool(case.get("run_id")),
            "Hosted result lacks durable case/run identity",
        )
        return result
    except (ValueError, TypeError, KeyError):
        raise AcceptanceError("Malformed structured Responses result") from None


def invoke(runner: Runner, environment: str, version: str, command: dict[str, Any]):
    session_id = f"langgraph-check-{uuid4().hex}"
    try:
        runner.run(
            azd_args(
                environment,
                "ai",
                "agent",
                "sessions",
                "create",
                "--agent-name",
                SERVICE,
                "--version",
                version,
                "--session-id",
                session_id,
                "--output",
                "json",
            )
        )
        raw = runner.run(
            azd_args(
                environment,
                "ai",
                "agent",
                "invoke",
                SERVICE,
                json.dumps(command),
                "--protocol",
                "responses",
                "--session-id",
                session_id,
                "--new-conversation",
                "--output",
                "raw",
            )
        )
        return response_result(raw)
    finally:
        try:
            runner.run(
                azd_args(
                    environment,
                    "ai",
                    "agent",
                    "sessions",
                    "stop",
                    session_id,
                    "--agent-name",
                    SERVICE,
                    "--no-prompt",
                )
            )
        except ReleaseError:
            raise AcceptanceError(f"Failed to stop owned hosted session {session_id}") from None
        print(json.dumps({"stopped_session": session_id, "version": version}), flush=True)


def invoke_sdk(
    project: AIProjectClient, client: OpenAI, version: str, command: dict[str, Any]
) -> dict[str, Any]:
    from azure.ai.projects.models import VersionRefIndicator
    from azure.core.exceptions import AzureError

    session_id = f"langgraph-check-{uuid4().hex}"
    try:
        session = project.agents.create_session(
            agent_name=SERVICE,
            version_indicator=VersionRefIndicator(agent_version=version),
            agent_session_id=session_id,
        )
        deadline = time.monotonic() + 300
        while session.status == "creating" and time.monotonic() < deadline:
            time.sleep(2)
            session = project.agents.get_session(agent_name=SERVICE, session_id=session_id)
        require(
            session.agent_session_id == session_id
            and isinstance(session.version_indicator, VersionRefIndicator)
            and session.version_indicator.agent_version == version
            and session.status in {"active", "idle"},
            "Hosted session is not ready on the requested version",
        )
        conversation = client.conversations.create()
        response = client.responses.create(
            input=json.dumps(command),
            conversation=conversation.id,
            stream=False,
            extra_body={"agent_session_id": session_id},
        )
        return response_result(response.model_dump_json())
    finally:
        try:
            project.agents.stop_session(agent_name=SERVICE, session_id=session_id)
        except AzureError:
            raise AcceptanceError(f"Failed to stop owned hosted session {session_id}") from None
        print(json.dumps({"stopped_session": session_id, "version": version}), flush=True)


def run_scenarios(
    send: Callable[[dict[str, Any]], dict[str, Any]], version: str, *, smoke: bool = False
) -> None:
    for scenario, decision, terminal in SCENARIOS[:1] if smoke else SCENARIOS:
        identifier = f"langgraph-hosted-{uuid4().hex}"
        started = send(
            {
                "action": "start",
                "scenario_id": scenario,
                "complaint": "Please investigate two captured charges for one purchase.",
                "customer_id": identifier,
                "case_id": identifier,
                "idempotency_key": identifier,
            }
        )["case"]
        require(started.get("case_id") == identifier, "Start changed requested case identity")
        run_id = started["run_id"]
        result = started
        if decision:
            require(
                started.get("status") == "paused" and started.get("approval_required") is True,
                "Approval scenario did not pause durably",
            )
            checkpoint = started.get("checkpoint_id")
            require(bool(checkpoint), "Approval pause lacks a checkpoint identifier")
            recorded = send(
                {
                    "action": "approval",
                    "case_id": identifier,
                    "checkpoint_id": checkpoint,
                    "decision": decision,
                    "reviewer_id": identifier,
                }
            )["case"]
            require(recorded.get("status") == "paused", "Approval implicitly resumed the graph")
            require(
                recorded.get("outcome") is None,
                "Approval pause must not have a terminal outcome",
            )
            result = send({"action": "resume", "case_id": identifier})["case"]
        require(
            result.get("case_id") == identifier and result.get("run_id") == run_id,
            "Hosted reconstruction changed durable identity",
        )
        verify_outcome(result.get("outcome"), terminal)
        print(
            json.dumps(
                {
                    "scenario": scenario,
                    "case_id": identifier,
                    "run_id": run_id,
                    "version": version,
                    "terminal_status": terminal,
                }
            ),
            flush=True,
        )
    print("LangGraph hosted explicit-command acceptance passed", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", default="langgraph")
    parser.add_argument("--version", required=True)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--transport", choices=("azd", "sdk"), default="azd")
    args = parser.parse_args()
    runner = Runner()
    if args.transport == "azd":
        version = active_agent(
            runner.json(
                azd_args(args.environment, "ai", "agent", "show", SERVICE, "--output", "json")
            )
        )
        require(version == args.version, "Requested version differs from active deployment")
        run_scenarios(
            lambda command: invoke(runner, args.environment, version, command),
            version,
            smoke=args.smoke,
        )
        return

    from azure.ai.projects import AIProjectClient
    from azure.core.exceptions import AzureError
    from azure.identity import DefaultAzureCredential
    from openai import OpenAIError
    from prepare_hosted_eval import selected_endpoint

    values = environment_values(runner, args.environment)
    endpoint = selected_endpoint(values, args.environment, args.version)
    try:
        with (
            DefaultAzureCredential(process_timeout=60) as credential,
            AIProjectClient(
                endpoint=endpoint, credential=credential, allow_preview=True, retry_total=0
            ) as project,
            project.get_openai_client(agent_name=SERVICE, max_retries=0, timeout=300) as client,
        ):
            deployed = project.agents.get_version(agent_name=SERVICE, agent_version=args.version)
            require(
                active_agent(deployed.as_dict()) == args.version,
                "Requested version differs from active deployment",
            )
            run_scenarios(
                lambda command: invoke_sdk(project, client, args.version, command),
                args.version,
                smoke=args.smoke,
            )
    except (AzureError, OpenAIError) as error:
        raise AcceptanceError(
            f"Hosted SDK request failed ({type(error).__name__}); no retry"
        ) from None


if __name__ == "__main__":
    try:
        main()
    except (AcceptanceError, ReleaseError) as error:
        raise SystemExit(str(error)) from None
