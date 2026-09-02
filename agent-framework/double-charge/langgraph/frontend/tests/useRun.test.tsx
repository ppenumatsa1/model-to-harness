import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CaseView } from "../src/types";
import { useRun } from "../src/useRun";

const api = vi.hoisted(() => ({
  getCase: vi.fn(),
  getEvents: vi.fn()
}));

vi.mock("../src/api", () => api);

class FakeEventSource {
  static instances: FakeEventSource[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onerror: (() => void) | null = null;

  constructor(public readonly url: string) {
    FakeEventSource.instances.push(this);
  }

  close() {}

  emit(data: string) {
    this.onmessage?.({ data } as MessageEvent<string>);
  }
}

function caseView(caseId: string): CaseView {
  return {
    case_id: caseId,
    run_id: `run-${caseId}`,
    status: "running",
    current_step: "load_account",
    approval_required: false,
    workflow_state: {},
    selected_memory: {}
  };
}

describe("useRun selected stream", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    api.getCase.mockImplementation(async (caseId: string) => caseView(caseId));
    api.getEvents.mockResolvedValue([]);
    vi.stubGlobal("EventSource", FakeEventSource);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.clearAllMocks();
  });

  it("resets sequence deduplication and projected events when caseId changes", async () => {
    const { result, rerender } = renderHook(
      ({ caseId }) => useRun(caseId),
      { initialProps: { caseId: "case-one" } }
    );
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      FakeEventSource.instances[0].emit(
        '{"type":"RUN_STARTED","runId":"run-one","sequence":1}'
      );
    });
    expect(result.current.aguiEvents).toHaveLength(1);

    rerender({ caseId: "case-two" });
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(2));
    expect(FakeEventSource.instances[1].url).toContain("after=0");
    expect(result.current.aguiEvents).toEqual([]);

    act(() => {
      FakeEventSource.instances[1].emit(
        '{"type":"RUN_STARTED","runId":"run-two","sequence":1}'
      );
    });
    expect(result.current.aguiEvents).toEqual([
      expect.objectContaining({ runId: "run-two", sequence: 1 })
    ]);
  });

  it("keeps result and end projections that share one native sequence", async () => {
    const { result } = renderHook(() => useRun("case-one"));
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));

    act(() => {
      FakeEventSource.instances[0].emit(
        '{"type":"TOOL_CALL_RESULT","runId":"run-one","sequence":7,"toolCallId":"tool-1"}'
      );
      FakeEventSource.instances[0].emit(
        '{"type":"TOOL_CALL_END","runId":"run-one","sequence":7,"toolCallId":"tool-1"}'
      );
    });

    expect(result.current.aguiEvents.map((event) => event.type)).toEqual([
      "TOOL_CALL_RESULT",
      "TOOL_CALL_END"
    ]);
  });
});
