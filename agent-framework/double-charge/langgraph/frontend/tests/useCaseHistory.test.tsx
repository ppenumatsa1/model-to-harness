import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api } from "../src/api";
import { useCaseHistory } from "../src/useCaseHistory";
import { deferred, summaryFor, viewFor } from "./workspaceFixtures";
import type { CasePage, CaseSummary } from "../src/types";

vi.mock("../src/api", () => ({ api: { cases: vi.fn() } }));
const read = vi.mocked(api.cases);
let rows: CaseSummary[];
function pageAfter(cursor?: string): CasePage {
  const start = cursor ? rows.findIndex((row) => row.case_id === cursor) + 1 : 0;
  const items = rows.slice(start, start + 10);
  const has_more = start + items.length < rows.length;
  return { items, has_more, next_cursor: has_more ? items.at(-1)!.case_id : null };
}

describe("history frontiers and live freshness", () => {
  beforeEach(() => {
    read.mockReset();
    rows = Array.from({ length: 25 }, (_, i) => summaryFor(i + 1));
    read.mockImplementation(async (cursor) => pageAfter(cursor));
  });
  afterEach(cleanup);
  it("bridges more than a page of new cases without stranding unloaded middle pages", async () => {
    const { result } = renderHook(useCaseHistory);
    await waitFor(() => expect(result.current.items).toHaveLength(10));
    await act(async () => result.current.loadMore());
    expect(result.current.items).toHaveLength(20);
    rows = [...Array.from({ length: 11 }, (_, i) => summaryFor(i - 10)), ...rows];
    await act(async () => result.current.refresh());
    expect(result.current.items).toHaveLength(30);
    await act(async () => result.current.loadMore());
    expect(result.current.items).toHaveLength(31);
    await act(async () => result.current.loadMore());
    expect(result.current.items.map((row) => row.case_id)).toEqual(rows.map((row) => row.case_id));
    expect(result.current.items).toHaveLength(36);
    expect(result.current.hasMore).toBe(false);
    expect(read.mock.calls.map(([cursor]) => cursor)).toEqual([undefined, "case-10", undefined, "case--1", "case-20"]);
  });
  it("adopts pagination after initially empty history", async () => {
    rows = [];
    const { result } = renderHook(useCaseHistory);
    await waitFor(() => expect(result.current.loaded).toBe(true));
    rows = Array.from({ length: 25 }, (_, i) => summaryFor(i + 1));
    await act(async () => result.current.refresh());
    expect(result.current.hasMore).toBe(true);
    await act(async () => result.current.loadMore());
    await act(async () => result.current.loadMore());
    expect(result.current.items).toHaveLength(25);
    expect(result.current.hasMore).toBe(false);
  });
  it.each(["refresh-first", "load-more-first"])("serializes both intentions during %s", async (order) => {
    const { result } = renderHook(useCaseHistory);
    await waitFor(() => expect(result.current.items).toHaveLength(10));
    const pending = deferred<CasePage>();
    read.mockReturnValueOnce(pending.promise);
    const earlier = pageAfter(order === "load-more-first" ? "case-10" : undefined);
    act(() => {
      if (order === "refresh-first") { void result.current.refresh(); void result.current.loadMore(); }
      else { void result.current.loadMore(); void result.current.refresh(); }
    });
    expect(read).toHaveBeenCalledTimes(2);
    await act(async () => pending.resolve(earlier));
    await waitFor(() => expect(read).toHaveBeenCalledTimes(3));
    expect(result.current.items).toHaveLength(20);
    await act(async () => result.current.loadMore());
    expect(result.current.items).toHaveLength(25);
  });
  it("prevents a late history row from regressing a newer native snapshot", async () => {
    rows[0] = { ...rows[0], status: "paused" };
    const { result } = renderHook(useCaseHistory);
    await waitFor(() => expect(result.current.items).toHaveLength(10));
    const pending = deferred<CasePage>();
    const stale = pageAfter();
    read.mockReturnValueOnce(pending.promise);
    act(() => { void result.current.refresh(); });
    const latest = viewFor("case-1");
    latest.created_at = rows[0].created_at;
    latest.state.status = "completed";
    latest.state.current_step = "completed";
    latest.state.updated_at = "2026-09-16T11:00:00Z";
    act(() => result.current.update(latest));
    await act(async () => pending.resolve(stale));
    expect(result.current.items.find((item) => item.case_id === "case-1")?.status).toBe("completed");
    await act(async () => result.current.refresh());
    expect(result.current.items.find((item) => item.case_id === "case-1")?.status).toBe("completed");
  });
});
