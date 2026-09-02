import { CopilotKit } from "@copilotkit/react-core/v2";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { SelectedRunAssistant } from "../src/App";

function eventStream(events: object[]) {
  return events.map((event) => `data: ${JSON.stringify(event)}\n\n`).join("");
}

describe("selected-run CopilotKit client", () => {
  it("discovers and runs the selected-run runtime agent", async () => {
    const fetchRuntime = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/copilotkit/info") {
        return Response.json({
          version: "0.1.0",
          actions: [],
          agents: {
            "selected-run": {
              description: "Read-only selected-run audit explainer"
            }
          }
        });
      }
      const request = JSON.parse(String(init?.body));
      return new Response(
        eventStream([
          {
            type: "RUN_STARTED",
            threadId: request.threadId,
            runId: request.runId
          },
          {
            type: "TEXT_MESSAGE_START",
            messageId: "message-1",
            role: "assistant"
          },
          {
            type: "TEXT_MESSAGE_CONTENT",
            messageId: "message-1",
            delta: "Exactly one durable refund was verified. Audit events: 4, 8."
          },
          {
            type: "TEXT_MESSAGE_END",
            messageId: "message-1"
          },
          {
            type: "RUN_FINISHED",
            threadId: request.threadId,
            runId: request.runId,
            outcome: { type: "success" }
          }
        ]),
        { headers: { "Content-Type": "text/event-stream" } }
      );
    });
    vi.stubGlobal("fetch", fetchRuntime);

    render(
      <CopilotKit runtimeUrl="/api/copilotkit">
        <SelectedRunAssistant
          caseId="case-1"
          safeContext={{ status: "completed" }}
        />
      </CopilotKit>
    );

    const button = await screen.findByRole("button", {
      name: "Explain selected run"
    });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);

    await screen.findByText("Exactly one durable refund was verified. Audit events: 4, 8.");
    const runCall = fetchRuntime.mock.calls.find(
      ([url]) => String(url) === "/api/copilotkit/agent/selected-run/run"
    );
    expect(runCall).toBeDefined();
    const request = JSON.parse(String(runCall?.[1]?.body));
    expect(request.threadId).toBe("case-1");
    expect(request.tools).toEqual([]);
    expect(request.messages).toEqual([]);
    expect(request.state).toEqual({});
  });
});
