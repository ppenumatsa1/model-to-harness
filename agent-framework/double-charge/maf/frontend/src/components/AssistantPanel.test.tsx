// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { deferred } from "../test/workspaceFixtures";
import type { WorkflowState } from "../types";

const copilot = vi.hoisted(() => ({
  threadId: "initial-thread",
  addMessage: vi.fn(),
  setMessages: vi.fn(),
  runAgent: vi.fn(),
  detachActiveRun: vi.fn()
}));

vi.mock("@copilotkit/react-core/v2", () => ({
  useAgent: () => ({
    isReady: true,
    agent: copilot
  })
}));

import { AssistantPanel } from "./AssistantPanel";

describe("AssistantPanel", () => {
  afterEach(cleanup);
  beforeEach(() => {
    copilot.addMessage.mockReset();
    copilot.setMessages.mockReset();
    copilot.runAgent.mockReset();
    copilot.detachActiveRun.mockReset();
    copilot.detachActiveRun.mockResolvedValue(undefined);
    copilot.runAgent.mockResolvedValue({
      result: null,
      newMessages: [
        {
          id: "answer-1",
          role: "assistant",
          content: "This answer came through the read-only runtime."
        }
      ]
    });
  });

  it("uses the CopilotKit agent runtime with selected-run context", async () => {
    render(
      <AssistantPanel
        state={{ run_id: "run-selected", approval_required: false } as WorkflowState}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Explain selected run" }));

    await waitFor(() => expect(copilot.runAgent).toHaveBeenCalledWith());
    expect(copilot.threadId).toBe("run-selected");
    expect(copilot.addMessage).toHaveBeenCalledWith(
      expect.objectContaining({
        role: "user",
        content: "Why is this run in its current status?"
      })
    );
    expect(
      await screen.findByText("This answer came through the read-only runtime.")
    ).not.toBeNull();
  });

  it("ignores an old run explanation after the selected case changes", async () => {
    const late = deferred<{ newMessages: { role: string; content: string }[] }>();
    copilot.runAgent.mockReturnValueOnce(late.promise);
    const { rerender } = render(<AssistantPanel state={{ run_id: "old-run" } as WorkflowState} />);
    fireEvent.click(screen.getByRole("button", { name: "Explain selected run" }));
    rerender(<AssistantPanel state={{ run_id: "new-run" } as WorkflowState} />);
    expect(screen.getByRole("button", { name: "Explaining…" })).toBeDisabled();
    await act(async () => late.resolve({ newMessages: [{ role: "assistant", content: "Old private case explanation" }] }));
    expect(copilot.detachActiveRun).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Old private case explanation")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Explain selected run" }));
    expect(await screen.findByText("This answer came through the read-only runtime.")).toBeVisible();
    expect(copilot.threadId).toBe("new-run");
  });
});
