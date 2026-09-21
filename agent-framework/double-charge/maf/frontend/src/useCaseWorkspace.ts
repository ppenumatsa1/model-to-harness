import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type { DurableEvent, RunView } from "./types";

export type ConnectionState = "idle" | "connecting" | "live" | "reconnecting" | "error";

export function mergeEvents(current: DurableEvent[], incoming: DurableEvent): DurableEvent[] {
  if (current.some((event) => event.event_id === incoming.event_id || event.sequence === incoming.sequence)) {
    return current;
  }
  return [...current, incoming].sort((left, right) => left.sequence - right.sequence);
}

export function useCaseWorkspace(caseId: string | undefined, pendingCreation: boolean) {
  const [run, setRun] = useState<RunView>();
  const [events, setEvents] = useState<DurableEvent[]>([]);
  const [connection, setConnection] = useState<ConnectionState>("idle");
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
    let snapshotRevision = 0;
    let runId: string | undefined;
    const abort = new AbortController();
    setRun(undefined);
    setEvents([]);
    setError(undefined);
    setLoading(Boolean(caseId));
    setConnection(caseId ? "connecting" : "idle");

    function acceptSnapshot(view: RunView) {
      if (!active || view.state.case_id !== caseId || (runId && view.state.run_id !== runId)) return;
      snapshotRevision += 1;
      setRun(view);
    }

    async function refreshSnapshot() {
      if (!caseId || !active) return;
      const revision = snapshotRevision;
      const view = await api.case(caseId, abort.signal);
      if (revision === snapshotRevision) acceptSnapshot(view);
    }
    refreshRef.current = async (expectedCaseId) => {
      if (!expectedCaseId || expectedCaseId === caseId) await refreshSnapshot();
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
      if (!active || !runId) return;
      const stream = new EventSource(`/api/runs/${encodeURIComponent(runId)}/events/stream?after=${cursor}`);
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
          const event = JSON.parse((message as MessageEvent).data) as DurableEvent;
          if (event.case_id !== caseId || event.run_id !== runId) return;
          if (!Number.isSafeInteger(event.sequence) || !event.event_id || typeof event.summary !== "string") {
            throw new Error("Invalid audit event");
          }
          cursor = Math.max(cursor, event.sequence);
          failures = 0;
          setEvents((existing) => mergeEvents(existing, event));
        } catch {
          disconnect("Invalid native audit event. Reconnecting.");
        }
      });
      stream.addEventListener("snapshot", (message) => {
        if (!current()) return;
        try {
          acceptSnapshot(JSON.parse((message as MessageEvent).data) as RunView);
          failures = 0;
        } catch {
          disconnect("Invalid case snapshot. Reconnecting.");
        }
      });
      stream.onerror = (event) => {
        if (!current()) return;
        let message = "Native audit connection interrupted. Reconnecting.";
        if ("data" in event && typeof event.data === "string") {
          try {
            const detail = JSON.parse(event.data) as { message?: string };
            if (typeof detail.message === "string") message = detail.message;
          } catch { /* Keep the safe connection error for malformed error frames. */ }
        }
        disconnect(message);
      };
    }

    async function discover(remaining = 30) {
      if (!caseId) return;
      try {
        const view = await api.case(caseId, abort.signal);
        if (!active) return;
        runId = view.state.run_id;
        acceptSnapshot(view);
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

  // Never render a previous selection during the render preceding effect cleanup.
  const selectedRun = run?.state.case_id === caseId ? run : undefined;
  return {
    run: selectedRun,
    events: selectedRun ? events.filter((event) => event.run_id === selectedRun.state.run_id) : [],
    connection, error, loading, refresh, retry
  };
}
