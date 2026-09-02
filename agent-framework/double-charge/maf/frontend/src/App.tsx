import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api, fetchAgui } from "./api";
import { ApprovalPanel } from "./components/ApprovalPanel";
import { AssistantPanel } from "./components/AssistantPanel";
import { RunInspector } from "./components/RunInspector";
import { Timeline } from "./components/Timeline";
import { WorkflowGraph } from "./components/WorkflowGraph";
import { freshRunClientState } from "./runClientState";
import type {
  AguiEvent,
  DurableEvent,
  RunView,
  Scenario,
  WorkflowGraph as Graph
} from "./types";

const EMPTY_GRAPH: Graph = { nodes: [], edges: [], parallel_groups: [] };

export default function App() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [graph, setGraph] = useState<Graph>(EMPTY_GRAPH);
  const [scenarioId, setScenarioId] = useState("duplicate-confirmed");
  const [complaint, setComplaint] = useState("I was charged twice for the same purchase.");
  const [customerId, setCustomerId] = useState("customer-100");
  const [runId, setRunId] = useState<string>();
  const [run, setRun] = useState<RunView>();
  const [events, setEvents] = useState<DurableEvent[]>([]);
  const [aguiEvents, setAguiEvents] = useState<AguiEvent[]>([]);
  const [aguiCursor, setAguiCursor] = useState(0);
  const [malformed, setMalformed] = useState(0);
  const [aguiDisconnected, setAguiDisconnected] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const activeRunRef = useRef<string | undefined>(undefined);

  useEffect(() => {
    Promise.all([api.scenarios(), api.graph()])
      .then(([available, workflow]) => {
        setScenarios(available);
        setGraph(workflow);
      })
      .catch((reason: Error) => setError(reason.message));
  }, []);

  const refresh = useCallback(async () => {
    if (!runId) return;
    const targetRunId = runId;
    const [latestRun, latestEvents] = await Promise.all([
      api.run(targetRunId),
      api.events(targetRunId)
    ]);
    if (activeRunRef.current !== targetRunId) return;
    setRun(latestRun);
    setEvents(latestEvents);
    try {
      const projection = await fetchAgui(targetRunId, aguiCursor);
      if (activeRunRef.current !== targetRunId) return;
      setAguiEvents((current) => [...current, ...projection.events]);
      setMalformed((current) => current + projection.malformed);
      setAguiDisconnected(false);
      if (projection.lastSequence) setAguiCursor(projection.lastSequence);
    } catch {
      setAguiDisconnected(true);
    }
  }, [aguiCursor, runId]);

  useEffect(() => {
    if (!runId) return;
    void refresh().catch((reason: Error) => setError(reason.message));
    const timer = window.setInterval(() => {
      void refresh().catch((reason: Error) => setError(reason.message));
    }, 2000);
    return () => window.clearInterval(timer);
  }, [refresh, runId]);

  const scenario = useMemo(
    () => scenarios.find((item) => item.id === scenarioId),
    [scenarioId, scenarios]
  );

  async function execute(action: () => Promise<void>) {
    setBusy(true);
    setError(undefined);
    try {
      await action();
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unexpected error");
    } finally {
      setBusy(false);
    }
  }

  async function startRun() {
    setBusy(true);
    setError(undefined);
    try {
      const started = await api.start({
        complaint,
        customer_id: customerId,
        scenario_id: scenarioId
      });
      const fresh = freshRunClientState();
      activeRunRef.current = started.run_id;
      setRunId(started.run_id);
      setRun(fresh.run);
      setEvents(fresh.events);
      setAguiEvents(fresh.aguiEvents);
      setAguiCursor(fresh.aguiCursor);
      setMalformed(fresh.malformed);
      setAguiDisconnected(fresh.aguiDisconnected);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unexpected error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main>
      <header className="hero">
        <div>
          <p className="eyebrow">Model → workflow → durable harness</p>
          <h1>Double-charge workflow lab</h1>
          <p>
            A teaching-focused Microsoft Agent Framework app with explicit routes, parallel
            validation, durable approval, retry evidence, and framework-neutral outcomes.
          </p>
        </div>
        <div className="hero-status">
          <span>{run?.state.status ?? "ready"}</span>
          <strong>{run?.state.current_step?.replaceAll("_", " ") ?? "choose a fixture"}</strong>
        </div>
      </header>

      <section className="panel composer">
        <div className="composer-copy">
          <p className="eyebrow">Deterministic fixture + model normalization</p>
          <h2>Start a support case</h2>
          <p>{scenario?.description}</p>
        </div>
        <div className="composer-form">
          <label>
            Fixture
            <select value={scenarioId} onChange={(event) => setScenarioId(event.target.value)}>
              {scenarios.map((item) => (
                <option value={item.id} key={item.id}>
                  {item.id}
                </option>
              ))}
            </select>
          </label>
          <label>
            Customer ID
            <input value={customerId} onChange={(event) => setCustomerId(event.target.value)} />
          </label>
          <label className="wide">
            Complaint
            <textarea value={complaint} onChange={(event) => setComplaint(event.target.value)} />
          </label>
          <button
            disabled={busy}
            onClick={startRun}
          >
            {busy ? "Running…" : "Start workflow"}
          </button>
        </div>
      </section>

      {error && <div className="error-banner">{error}</div>}

      <ApprovalPanel
        state={run?.state ?? null}
        busy={busy}
        onApprove={(decision, reviewer, reason) =>
          execute(async () => {
            const state = run?.state;
            if (!state?.checkpoint_id || !runId) throw new Error("No approval checkpoint");
            await api.approve(runId, {
              checkpoint_id: state.checkpoint_id,
              decision,
              reviewer_id: reviewer,
              reason
            });
          })
        }
        onResume={() =>
          execute(async () => {
            const checkpoint = run?.state.checkpoint_id;
            if (!runId || !checkpoint) throw new Error("No checkpoint to resume");
            await api.resume(runId, checkpoint);
          })
        }
      />

      <div className="workspace">
        <WorkflowGraph graph={graph} state={run?.state ?? null} events={events} />
        <Timeline
          events={events}
          aguiEvents={aguiEvents}
          malformed={malformed}
          disconnected={aguiDisconnected}
        />
      </div>
      <div className="workspace lower">
        <RunInspector
          state={run?.state ?? null}
          memory={run?.memory ?? {}}
          outcome={run?.outcome}
        />
        <AssistantPanel state={run?.state ?? null} />
      </div>
    </main>
  );
}
