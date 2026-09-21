import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "../src/api";
import { useCaseWorkspace } from "../src/useCaseWorkspace";
import { deferred, eventFor, MockEventSource, viewFor } from "./workspaceFixtures";
import type { Workspace } from "../src/types";

vi.mock("../src/api", async (original) => {
  const actual = await original<typeof import("../src/api")>();
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
  it("deduplicates replay with monotonic noncontiguous cursors and follows terminal memory snapshots", async () => {
    const { result } = renderHook(() => useCaseWorkspace("case-1", false));
    await act(async () => {});
    const first = MockEventSource.latest();
    expect(first.url).toBe("/api/cases/case-1/events/stream?after=0&follow=true");
    await act(async () => first.onopen?.());
    expect(result.current.connection).toBe("live");
    act(() => {
      first.emit("audit", eventFor("case-1", 8));
      first.emit("audit", eventFor("case-1", 21));
      first.emit("audit", eventFor("case-1", 12));
      first.fail();
    });
    expect(first.closed).toBe(true);
    await act(async () => vi.advanceTimersByTimeAsync(1000));
    const second = MockEventSource.latest();
    expect(second.url).toContain("after=21");
    const terminal = viewFor("case-1");
    terminal.state.status = "completed";
    read.mockResolvedValue(terminal);
    await act(async () => second.onopen?.());
    act(() => {
      second.emit("audit", eventFor("case-1", 21));
      second.emit("audit", eventFor("case-1", 29));
    });
    expect(result.current.events.map((event) => event.sequence)).toEqual([8, 12, 21, 29]);
    expect(result.current.run?.state.status).toBe("completed");
    expect(result.current.run?.memory).toEqual({});
    expect(second.closed).toBe(false);
    act(() => second.emit("snapshot", { ...terminal, memory: { refund_status: "verified" } }));
    expect(result.current.run?.memory.refund_status).toBe("verified");
  });
  it("rejects late same-case fetches, stale other-case snapshots and old stream errors", async () => {
    const { result, rerender } = renderHook(({ id }) => useCaseWorkspace(id, false), { initialProps: { id: "case-1" } });
    await act(async () => {});
    const late = deferred<Workspace>();
    read.mockReturnValueOnce(late.promise);
    act(() => MockEventSource.latest().onopen?.());
    const latest = { ...viewFor("case-1"), memory: { refund_status: "verified" } };
    act(() => MockEventSource.latest().emit("snapshot", latest));
    await act(async () => late.resolve(viewFor("case-1")));
    expect(result.current.run?.memory.refund_status).toBe("verified");
    const old = MockEventSource.latest();
    rerender({ id: "case-2" });
    await act(async () => {});
    act(() => { old.emit("snapshot", latest); old.emit("audit", eventFor("case-1")); old.fail(); });
    expect(result.current.run?.state.case_id).toBe("case-2");
    expect(result.current.events).toEqual([]);
    expect(old.closed).toBe(true);
  });
  it("bounds pending discovery and reconnection; explicit observation retry never mutates", async () => {
    read.mockRejectedValue(new ApiError("Not found", 404));
    const { result } = renderHook(() => useCaseWorkspace("new-case", true));
    await act(async () => vi.advanceTimersByTimeAsync(31000));
    expect(read).toHaveBeenCalledTimes(31);
    expect(result.current.connection).toBe("error");
    read.mockResolvedValue(viewFor("new-case"));
    await act(async () => result.current.retry());
    for (let i = 0; i < 9; i += 1) {
      act(() => MockEventSource.latest().fail());
      await act(async () => vi.advanceTimersByTimeAsync(15000));
    }
    expect(result.current.connection).toBe("error");
    const count = MockEventSource.instances.length;
    await act(async () => vi.advanceTimersByTimeAsync(60000));
    expect(MockEventSource.instances).toHaveLength(count);
  });
  it("surfaces malformed frames rather than silently advancing its cursor", async () => {
    const { result } = renderHook(() => useCaseWorkspace("case-1", false));
    await act(async () => {});
    act(() => MockEventSource.latest().emit("audit", { ...eventFor("case-1"), sequence: "999" }));
    expect(result.current.error).toContain("Invalid native audit event");
    await act(async () => vi.advanceTimersByTimeAsync(1000));
    expect(MockEventSource.latest().url).toContain("after=0");
  });
});
