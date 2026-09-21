import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";
import { useCaseWorkspace } from "./useCaseWorkspace";
import { deferred, eventFor, MockEventSource, viewFor } from "./test/workspaceFixtures";
import type { RunView } from "./types";

vi.mock("./api", async (original) => {
  const actual = await original<typeof import("./api")>();
  return { ...actual, api: { ...actual.api, case: vi.fn() } };
});
const read = vi.mocked(api.case);

describe("native case observation", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    read.mockReset();
    read.mockImplementation(async (id) => viewFor(id));
    MockEventSource.instances = [];
    vi.stubGlobal("EventSource", MockEventSource);
  });
  afterEach(() => { cleanup(); vi.useRealTimers(); vi.unstubAllGlobals(); });

  it("reconnects at the last processed noncontiguous sequence, deduplicates replay, and refreshes snapshots", async () => {
    const { result } = renderHook(() => useCaseWorkspace("case-1", false));
    await act(async () => {});
    const first = MockEventSource.latest();
    await act(async () => first.onopen?.());
    expect(result.current.connection).toBe("live");
    act(() => {
      first.emit("audit", eventFor("case-1", 8));
      first.emit("audit", eventFor("case-1", 21));
      first.fail();
    });
    expect(result.current.connection).toBe("reconnecting");
    expect(first.closed).toBe(true);
    await act(async () => vi.advanceTimersByTimeAsync(1000));
    const second = MockEventSource.latest();
    expect(second.url).toContain("after=21");
    const updated = viewFor("case-1");
    updated.state.status = "completed";
    read.mockResolvedValue(updated);
    await act(async () => second.onopen?.());
    act(() => {
      second.emit("audit", eventFor("case-1", 21));
      second.emit("audit", eventFor("case-1", 29));
    });
    expect(result.current.events.map((event) => event.sequence)).toEqual([8, 21, 29]);
    expect(result.current.run?.state.status).toBe("completed");
    expect(result.current.run?.outcome).toBeNull();
    expect(second.closed).toBe(false);
    act(() => second.emit("snapshot", { ...updated, memory: { fixture_id: "snapshot-only-update" } }));
    expect(result.current.run?.memory.fixture_id).toBe("snapshot-only-update");
  });

  it("does not let a reconnect read overwrite a newer streamed snapshot or another selection", async () => {
    const { result, rerender } = renderHook(({ id }) => useCaseWorkspace(id, false), { initialProps: { id: "case-1" } });
    await act(async () => {});
    const late = deferred<RunView>();
    read.mockReturnValueOnce(late.promise);
    act(() => MockEventSource.latest().onopen?.());
    const latest = { ...viewFor("case-1"), memory: { fixture_id: "latest-stream" } };
    act(() => MockEventSource.latest().emit("snapshot", latest));
    await act(async () => late.resolve(viewFor("case-1")));
    expect(result.current.run?.memory.fixture_id).toBe("latest-stream");
    const old = MockEventSource.latest();
    rerender({ id: "case-2" });
    await act(async () => {});
    act(() => {
      old.emit("snapshot", latest);
      old.emit("audit", eventFor("case-1"));
      old.fail();
    });
    expect(result.current.run?.state.case_id).toBe("case-2");
    expect(result.current.events).toEqual([]);
    expect(old.closed).toBe(true);
  });

  it("bounds pending creation discovery and stream reconnection with explicit retry", async () => {
    read.mockRejectedValue(new ApiError("Not found", 404));
    const { result } = renderHook(() => useCaseWorkspace("new-case", true));
    await act(async () => vi.advanceTimersByTimeAsync(31000));
    expect(read).toHaveBeenCalledTimes(31);
    expect(result.current.connection).toBe("error");
    read.mockResolvedValue(viewFor("new-case"));
    await act(async () => result.current.retry());
    for (let index = 0; index < 9; index += 1) {
      act(() => MockEventSource.latest().fail());
      await act(async () => vi.advanceTimersByTimeAsync(15000));
    }
    expect(result.current.connection).toBe("error");
    const count = MockEventSource.instances.length;
    await act(async () => vi.advanceTimersByTimeAsync(60000));
    expect(MockEventSource.instances).toHaveLength(count);
  });
});
