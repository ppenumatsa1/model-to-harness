import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ProxiedCopilotRuntimeAgent } from "@copilotkit/core";
import { deferred } from "./workspaceFixtures";

const runtime = vi.hoisted(() => ({ agent: null as ProxiedCopilotRuntimeAgent | null }));
vi.mock("@copilotkit/react-core/v2", () => ({ useAgent: () => ({ agent: runtime.agent, isReady: true }) }));
import { SelectedRunAssistant } from "../src/components/AssistantPanel";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
it("settles the installed shared runtime before clearing messages or explaining another selected case", async () => {
  const requests: { threadId: string; runId: string; messages: unknown[]; state: object; tools: unknown[];
    stream: ReadableStreamDefaultController<Uint8Array>; cancelled: boolean }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init: RequestInit) => {
    const input = JSON.parse(init.body as string);
    const request = { ...input, stream: null as unknown as ReadableStreamDefaultController<Uint8Array>, cancelled: false };
    const body = new ReadableStream<Uint8Array>({
      start(controller) { request.stream = controller; }, cancel() { request.cancelled = true; }
    });
    requests.push(request);
    return new Response(body, { headers: { "content-type": "text/event-stream" } });
  }));
  const agent = new ProxiedCopilotRuntimeAgent({
    agentId: "selected-run", runtimeUrl: "http://isolated.test/api/copilotkit", transport: "rest"
  });
  runtime.agent = agent;
  const actualRun = agent.runAgent.bind(agent);
  const settlement = deferred<void>();
  let calls = 0;
  vi.spyOn(agent, "runAgent").mockImplementation(async (...args) => {
    const first = ++calls === 1;
    const result = await actualRun(...args);
    if (first) await settlement.promise;
    return result;
  });
  const detach = vi.spyOn(agent, "detachActiveRun");
  const clear = vi.spyOn(agent, "setMessages");
  const { rerender } = render(<SelectedRunAssistant caseId="case-A" />);
  fireEvent.click(screen.getByRole("button", { name: "Explain selected run" }));
  await waitFor(() => expect(requests).toHaveLength(1));
  expect(requests[0].threadId).toBe("case-A");
  expect(requests[0].messages).toEqual([]);
  expect(requests[0].state).toEqual({});
  expect(requests[0].tools).toEqual([]);
  const send = (index: number, event: object) => {
    requests[index].stream.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));
  };
  await act(async () => {
    send(0, { type: "RUN_STARTED", threadId: "case-A", runId: requests[0].runId });
    send(0, { type: "TEXT_MESSAGE_START", messageId: "answer-A", role: "assistant" });
    send(0, { type: "TEXT_MESSAGE_CONTENT", messageId: "answer-A", delta: "Explanation for case-A" });
  });
  await waitFor(() => expect(agent.messages.some((message) => message.content === "Explanation for case-A")).toBe(true));
  const clears = clear.mock.calls.length;
  rerender(<SelectedRunAssistant caseId="case-B" />);
  await waitFor(() => expect(detach).toHaveBeenCalledTimes(1));
  expect(screen.getByRole("button", { name: "Reading durable events…" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Reading durable events…" }));
  expect(requests).toHaveLength(1);
  expect(clear).toHaveBeenCalledTimes(clears);
  await act(async () => {
    if (!requests[0].cancelled) {
      send(0, { type: "TEXT_MESSAGE_END", messageId: "answer-A" });
      send(0, { type: "RUN_FINISHED", threadId: "case-A", runId: requests[0].runId });
      requests[0].stream.close();
    }
    settlement.resolve();
  });
  await waitFor(() => expect(screen.getByRole("button", { name: "Explain selected run" })).toBeEnabled());
  expect(agent.messages).toEqual([]);
  fireEvent.click(screen.getByRole("button", { name: "Explain selected run" }));
  await waitFor(() => expect(requests).toHaveLength(2));
  expect(requests[1].threadId).toBe("case-B");
  expect(requests[1].messages).toEqual([]);
  expect(requests[1].state).toEqual({});
  await act(async () => {
    send(1, { type: "RUN_STARTED", threadId: "case-B", runId: requests[1].runId });
    send(1, { type: "TEXT_MESSAGE_START", messageId: "answer-B", role: "assistant" });
    send(1, { type: "TEXT_MESSAGE_CONTENT", messageId: "answer-B", delta: "Explanation for case-B" });
    send(1, { type: "TEXT_MESSAGE_END", messageId: "answer-B" });
    send(1, { type: "RUN_FINISHED", threadId: "case-B", runId: requests[1].runId });
    requests[1].stream.close();
  });
  expect(await screen.findByText("Explanation for case-B")).toBeVisible();
  expect(screen.queryByText("Explanation for case-A")).not.toBeInTheDocument();
});
