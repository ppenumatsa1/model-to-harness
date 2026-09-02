// @vitest-environment jsdom

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { WorkflowState } from "../types";

const copilot = vi.hoisted(() => ({
  threadId: "initial-thread",
  addMessage: vi.fn(),
  setMessages: vi.fn(),
  runAgent: vi.fn()
}));

vi.mock("@copilotkit/react-core/v2", () => ({
  useAgent: () => ({
    isReady: true,
    agent: copilot
  })
}));

import { AssistantPanel } from "./AssistantPanel";

describe("AssistantPanel", () => {
  beforeEach(() => {
    copilot.addMessage.mockReset();
    copilot.setMessages.mockReset();
    copilot.runAgent.mockReset();
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
});
