import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { CasePage, CaseSummary, Workspace } from "./types";

function compareNewest(a: CaseSummary, b: CaseSummary) {
  return b.created_at.localeCompare(a.created_at) || b.run_id.localeCompare(a.run_id);
}

interface LoadedRange {
  ids: Set<string>;
  oldest?: CaseSummary;
  next_cursor: string | null;
  has_more: boolean;
}

function rangeFor(page: CasePage): LoadedRange {
  return { ids: new Set(page.items.map((item) => item.case_id)), oldest: page.items.at(-1),
    next_cursor: page.next_cursor, has_more: page.has_more };
}

function joinRanges(newer: LoadedRange, other: LoadedRange): LoadedRange {
  const tail = other.oldest && (!newer.oldest || compareNewest(newer.oldest, other.oldest) < 0) ? other : newer;
  return { ...tail, ids: new Set([...newer.ids, ...other.ids]) };
}

export function useCaseHistory() {
  const [items, setItems] = useState<CaseSummary[]>([]);
  const [page, setPage] = useState<LoadedRange>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();
  const inFlight = useRef(false);
  const ranges = useRef<LoadedRange[]>([]);
  const mounted = useRef(false);
  const lastOperation = useRef(false);
  const queuedRefresh = useRef(false);
  const queuedMore = useRef(false);
  const revisions = useRef(new Map<string, number>());
  const snapshots = useRef(new Map<string, CaseSummary>());

  const load = useCallback(async (more = false) => {
    if (inFlight.current) {
      if (more) queuedMore.current = true;
      else queuedRefresh.current = true;
      return;
    }
    const cursor = more ? ranges.current[0]?.next_cursor ?? undefined : undefined;
    if (more && !cursor) return;
    const startedRevisions = new Map(revisions.current);
    inFlight.current = true;
    lastOperation.current = more;
    setLoading(true);
    setError(undefined);
    try {
      const result = await api.cases(cursor);
      if (!mounted.current) return;
      setItems((current) => {
        const merged = new Map(current.map((item) => [item.case_id, item]));
        result.items.forEach((item) => {
          const changed = revisions.current.get(item.case_id) !== startedRevisions.get(item.case_id);
          const live = snapshots.current.get(item.case_id);
          merged.set(item.case_id, live && (changed || live.updated_at > item.updated_at) ? live : item);
        });
        return [...merged.values()].sort(compareNewest);
      });
      let head = rangeFor(result);
      const previous = [...ranges.current];
      if (more && previous.length) {
        head = joinRanges(head, previous.shift()!);
        head.next_cursor = result.next_cursor;
        head.has_more = result.has_more;
      }
      // Refreshing a disjoint head must walk the gap before reusing an older frontier.
      const retained: LoadedRange[] = [];
      for (const range of previous) {
        if ([...range.ids].some((id) => head.ids.has(id))) head = joinRanges(head, range);
        else if (range.ids.size) retained.push(range);
      }
      ranges.current = [head, ...retained];
      setPage(head);
    } catch (caught) {
      if (mounted.current) setError(caught instanceof Error ? caught.message : "Could not load cases.");
    } finally {
      inFlight.current = false;
      if (mounted.current) {
        setLoading(false);
        if (queuedRefresh.current) {
          queuedRefresh.current = false;
          void load();
        } else if (queuedMore.current) {
          queuedMore.current = false;
          void load(true);
        }
      }
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    void load();
    const focus = () => void load();
    window.addEventListener("focus", focus);
    return () => {
      mounted.current = false;
      window.removeEventListener("focus", focus);
    };
  }, [load]);

  const update = useCallback((view: Workspace, insert = false) => {
    const summary: CaseSummary = {
      case_id: view.state.case_id, run_id: view.state.run_id,
      customer_id: view.state.customer_id, scenario_id: view.state.scenario_id,
      created_at: view.created_at, updated_at: view.state.updated_at,
      status: view.state.status, current_step: view.state.current_step,
      terminal_status: view.state.terminal_status ?? null
    };
    revisions.current.set(summary.case_id, (revisions.current.get(summary.case_id) ?? 0) + 1);
    snapshots.current.set(summary.case_id, summary);
    setItems((current) => {
      if (!insert && !current.some((item) => item.case_id === summary.case_id)) return current;
      return [...current.filter((item) => item.case_id !== summary.case_id), summary].sort(compareNewest);
    });
  }, []);

  return { items, loading, error, hasMore: page?.has_more ?? false, loaded: Boolean(page),
    refresh: () => load(), loadMore: () => load(true), retry: () => load(lastOperation.current), update };
}
