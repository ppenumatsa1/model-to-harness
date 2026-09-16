import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type { NativeEvent, Workspace } from "./types";

export function mergeEvents(current: NativeEvent[], incoming: NativeEvent): NativeEvent[] {
  if (current.some((event) => event.event_id === incoming.event_id || event.sequence === incoming.sequence)) return current;
  return [...current, incoming].sort((a, b) => a.sequence - b.sequence);
}

export function useCaseWorkspace(caseId: string | undefined, pendingCreation: boolean) {
  const [run, setRun] = useState<Workspace>();
  const [events, setEvents] = useState<NativeEvent[]>([]);
  const [connection, setConnection] = useState<"idle" | "connecting" | "live" | "reconnecting" | "error">("idle");
  const [error, setError] = useState<string>();
  const [loading, setLoading] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const pendingRef = useRef(pendingCreation);
  pendingRef.current = pendingCreation;
  const refreshRef = useRef<(expectedCaseId?: string) => Promise<void>>(async () => {});
  const refresh = useCallback((expectedCaseId?: string) => refreshRef.current(expectedCaseId), []);
  const retry = useCallback(() => setAttempt((value) => value + 1), []);

  useEffect(() => {
    let active = true;
    let source: EventSource | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let cursor = 0;
    let failures = 0;
    let revision = 0;
    let runId: string | undefined;
    const abort = new AbortController();
    setRun(undefined);
    setEvents([]);
    setError(undefined);
    setLoading(Boolean(caseId));
    setConnection(caseId ? "connecting" : "idle");

    function accept(view: Workspace) {
      if (!active || view.state.case_id !== caseId || (runId && view.state.run_id !== runId)) return;
      revision += 1;
      setRun(view);
    }
    async function refreshSnapshot() {
      if (!active || !caseId) return;
      const started = revision;
      const view = await api.case(caseId, abort.signal);
      if (started === revision) accept(view);
    }
    refreshRef.current = async (expected) => {
      if (!expected || expected === caseId) await refreshSnapshot();
    };
    function disconnect(message: string) {
      if (!active) return;
      source?.close();
      source = undefined;
      if (timer) clearTimeout(timer);
      failures += 1;
      setError(message);
      setConnection(failures > 8 ? "error" : "reconnecting");
      if (failures <= 8) timer = setTimeout(connect, Math.min(1000 * 2 ** (failures - 1), 15000));
    }
    function connect() {
      if (!active || !caseId || !runId) return;
      const stream = new EventSource(`/api/cases/${encodeURIComponent(caseId)}/events/stream?after=${cursor}&follow=true`);
      source = stream;
      const current = () => active && source === stream;
      stream.onopen = () => {
        if (!current()) return;
        setConnection("live");
        setError(undefined);
        void refreshSnapshot().catch(() => {
          if (current()) disconnect("Could not refresh the persisted case. Reconnecting.");
        });
      };
      stream.addEventListener("audit", (message) => {
        if (!current()) return;
        try {
          const event = JSON.parse((message as MessageEvent).data) as NativeEvent;
          if (event.case_id !== caseId || event.run_id !== runId) return;
          if (!Number.isSafeInteger(event.sequence) || event.sequence <= 0 || !event.event_id ||
              typeof event.event_type !== "string" || typeof event.summary !== "string" ||
              typeof event.timestamp !== "string" || !event.data || typeof event.data !== "object") {
            throw new Error("Invalid audit event");
          }
          cursor = Math.max(cursor, event.sequence);
          failures = 0;
          setEvents((existing) => mergeEvents(existing, event));
        } catch { disconnect("Invalid native audit event. Reconnecting."); }
      });
      stream.addEventListener("snapshot", (message) => {
        if (!current()) return;
        try {
          accept(JSON.parse((message as MessageEvent).data) as Workspace);
          failures = 0;
        } catch { disconnect("Invalid case snapshot. Reconnecting."); }
      });
      stream.onerror = () => {
        if (current()) disconnect("Native audit connection interrupted. Reconnecting.");
      };
    }
    async function discover(remaining = 30) {
      if (!caseId) return;
      try {
        const view = await api.case(caseId, abort.signal);
        if (!active) return;
        runId = view.state.run_id;
        accept(view);
        setLoading(false);
        connect();
      } catch (caught) {
        if (!active) return;
        if (caught instanceof ApiError && caught.status === 404 && pendingRef.current && remaining > 0) {
          timer = setTimeout(() => void discover(remaining - 1), 1000);
          return;
        }
        setLoading(false);
        setConnection("error");
        setError(caught instanceof Error ? caught.message : "Could not load this case.");
      }
    }
    void discover();
    return () => {
      active = false;
      abort.abort();
      source?.close();
      if (timer) clearTimeout(timer);
      refreshRef.current = async () => {};
    };
  }, [caseId, attempt]);

  const selectedRun = run?.state.case_id === caseId ? run : undefined;
  return {
    run: selectedRun,
    events: selectedRun ? events.filter((event) => event.run_id === selectedRun.state.run_id) : [],
    connection, error, loading, refresh, retry
  };
}
