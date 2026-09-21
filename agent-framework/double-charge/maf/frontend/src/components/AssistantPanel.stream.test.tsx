import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ProxiedCopilotRuntimeAgent } from "@copilotkit/core";
import { deferred, viewFor } from "../test/workspaceFixtures";

const runtime = vi.hoisted(() => ({ agent: null as ProxiedCopilotRuntimeAgent | null }));
vi.mock("@copilotkit/react-core/v2", () => ({
  useAgent: () => ({ agent: runtime.agent, isReady: true })
}));
import { AssistantPanel } from "./AssistantPanel";

afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it("detaches and settles the installed shared proxy stream before clearing or explaining another case", async () => {
  const requests: { threadId: string; runId: string; stream: ReadableStreamDefaultController<Uint8Array>; cancelled: boolean }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init: RequestInit) => {
    const input = JSON.parse(init.body as string) as { threadId: string; runId: string };
    const request = { ...input, stream: null as unknown as ReadableStreamDefaultController<Uint8Array>, cancelled: false };
    const body = new ReadableStream<Uint8Array>({
      start(controller) { request.stream = controller; },
      cancel() { request.cancelled = true; }
    });
    requests.push(request);
    return new Response(body, { headers: { "content-type": "text/event-stream" } });
  }));
  const agent = new ProxiedCopilotRuntimeAgent({
    agentId: "selected-run", runtimeUrl: "http://isolated.test/api/copilotkit", transport: "single"
  });
  runtime.agent = agent;
  const actualRun = agent.runAgent.bind(agent);
  const settlement = deferred<void>();
  let calls = 0;
  // Keep A's invocation pending even after transport detach to verify both barriers.
  vi.spyOn(agent, "runAgent").mockImplementation(async (...args) => {
    const first = ++calls === 1;
    const result = await actualRun(...args);
    if (first) await settlement.promise;
    return result;
  });
  const detach = vi.spyOn(agent, "detachActiveRun");
  const clear = vi.spyOn(agent, "setMessages");
  const { rerender } = render(<AssistantPanel state={viewFor("case-A").state} />);
  fireEvent.click(screen.getByRole("button", { name: "Explain selected run" }));
  await waitFor(() => expect(requests).toHaveLength(1));
  const send = (index: number, event: object) => {
    requests[index].stream.enqueue(new TextEncoder().encode(`data: ${JSON.stringify(event)}\n\n`));
  };
  await act(async () => {
    send(0, { type: "RUN_STARTED", threadId: "run-case-A", runId: "invocation-A" });
    send(0, { type: "TEXT_MESSAGE_START", messageId: "answer-A", role: "assistant" });
    send(0, { type: "TEXT_MESSAGE_CONTENT", messageId: "answer-A", delta: "Explanation for case-A" });
  });
  await waitFor(() => expect(agent.messages.some((message) => message.content === "Explanation for case-A")).toBe(true));
  const clears = clear.mock.calls.length;
  rerender(<AssistantPanel state={viewFor("case-B").state} />);
  await waitFor(() => expect(detach).toHaveBeenCalledTimes(1));
  expect(screen.getByRole("button", { name: "Explaining…" })).toBeDisabled();
  fireEvent.click(screen.getByRole("button", { name: "Explaining…" }));
  expect(requests).toHaveLength(1);
  expect(clear).toHaveBeenCalledTimes(clears);
  await act(async () => {
    if (!requests[0].cancelled) {
      send(0, { type: "TEXT_MESSAGE_END", messageId: "answer-A" });
      send(0, { type: "RUN_FINISHED", threadId: "run-case-A", runId: "invocation-A" });
      requests[0].stream.close();
    }
    settlement.resolve();
  });
  await waitFor(() => expect(screen.getByRole("button", { name: "Explain selected run" })).toBeEnabled());
  expect(agent.messages).toEqual([]);
  fireEvent.click(screen.getByRole("button", { name: "Explain selected run" }));
  await waitFor(() => expect(requests).toHaveLength(2));
  await act(async () => {
    send(1, { type: "RUN_STARTED", threadId: "run-case-B", runId: "invocation-B" });
    send(1, { type: "TEXT_MESSAGE_START", messageId: "answer-B", role: "assistant" });
    send(1, { type: "TEXT_MESSAGE_CONTENT", messageId: "answer-B", delta: "Explanation for case-B" });
    send(1, { type: "TEXT_MESSAGE_END", messageId: "answer-B" });
    send(1, { type: "RUN_FINISHED", threadId: "run-case-B", runId: "invocation-B" });
    requests[1].stream.close();
  });
  expect(await screen.findByText("Explanation for case-B")).toBeVisible();
  expect(screen.queryByText("Explanation for case-A")).not.toBeInTheDocument();
});
