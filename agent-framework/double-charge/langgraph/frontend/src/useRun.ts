import { useCallback, useEffect, useRef, useState } from "react";

import { getCase, getEvents } from "./api";
import { parseAguiEvent } from "./agui";
import type { AguiEvent, CaseView, NativeEvent } from "./types";

export function useRun(caseId?: string) {
  const [run, setRun] = useState<CaseView>();
  const [events, setEvents] = useState<NativeEvent[]>([]);
  const [aguiEvents, setAguiEvents] = useState<AguiEvent[]>([]);
  const [connection, setConnection] = useState<
    "idle" | "connecting" | "live" | "disconnected" | "malformed"
  >("idle");
  const seen = useRef(new Set<string>());
  const lastSequence = useRef(0);
  const selectedCase = useRef(caseId);
  selectedCase.current = caseId;

  const refresh = useCallback(async () => {
    if (!caseId) return;
    const [nextRun, nextEvents] = await Promise.all([getCase(caseId), getEvents(caseId)]);
    if (selectedCase.current !== caseId) return;
    setRun(nextRun);
    setEvents(nextEvents);
  }, [caseId]);

  useEffect(() => {
    seen.current.clear();
    lastSequence.current = 0;
    setRun(undefined);
    setEvents([]);
    setAguiEvents([]);
    setConnection(caseId ? "connecting" : "idle");
  }, [caseId]);

  useEffect(() => {
    if (!caseId) return;
    void refresh();
    const interval = window.setInterval(() => void refresh(), 1500);
    return () => window.clearInterval(interval);
  }, [caseId, refresh]);

  useEffect(() => {
    if (!caseId) return;
    setConnection("connecting");
    const after = lastSequence.current;
    const source = new EventSource(`/api/cases/${caseId}/agui?after=${after}`);
    source.onopen = () => setConnection("live");
    source.onmessage = (message) => {
      if (selectedCase.current !== caseId) return;
      try {
        const parsed = parseAguiEvent(message.data);
        const projectionKey = [
          parsed.sequence,
          parsed.type,
          parsed.messageId,
          parsed.toolCallId,
          parsed.name
        ].join(":");
        if (!seen.current.has(projectionKey)) {
          seen.current.add(projectionKey);
          lastSequence.current = Math.max(lastSequence.current, parsed.sequence);
          setAguiEvents((current) => [...current, parsed]);
        }
      } catch {
        setConnection("malformed");
      }
    };
    source.onerror = () => setConnection("disconnected");
    return () => source.close();
  }, [caseId]);

  return { run, events, aguiEvents, connection, refresh };
}
