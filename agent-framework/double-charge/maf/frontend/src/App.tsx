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
    <div className="app-shell">
      <aside className="navigation-rail" aria-label="Workspace navigation">
        <a className="brand" href="#workspace" aria-label="MAF Workflow Lab home">
          <span className="brand-mark" aria-hidden="true">M</span>
          <span>
            <strong>MAF</strong>
            <small>Workflow Lab</small>
          </span>
        </a>
        <nav className="primary-nav" aria-label="Workflow sections">
          <a className="nav-item active" href="#case-composer" aria-current="page">
            <span aria-hidden="true">⌁</span>
            <span>Case workspace</span>
          </a>
          <a className="nav-item" href="#workflow-artifacts">
            <span aria-hidden="true">◇</span>
            <span>Workflow artifacts</span>
          </a>
          <a className="nav-item" href="#safe-explainer">
            <span aria-hidden="true">◌</span>
            <span>Safe explainer</span>
          </a>
        </nav>
        <div className="rail-note">
          <span className="rail-note-icon" aria-hidden="true">✓</span>
          <p>
            <strong>Teaching mode</strong>
            Deterministic fixtures and durable evidence.
          </p>
        </div>
      </aside>

      <main id="workspace">
        <header className="top-bar">
          <div className="breadcrumb">
            <span>Support operations</span>
            <span aria-hidden="true">/</span>
            <strong>Double-charge review</strong>
          </div>
          <div className="top-bar-actions">
            <span className="environment-badge">Local workspace</span>
            <span className="run-status" role="status">
              <span className={`status-dot ${run?.state.status ?? "ready"}`} aria-hidden="true" />
              {run?.state.status ?? "Ready for a case"}
            </span>
          </div>
        </header>

        <div className="page-heading">
          <div>
            <p className="eyebrow">Microsoft Agent Framework</p>
            <h1>Double-charge case workspace</h1>
            <p>
              Start a support scenario, then follow its durable decisions, validation evidence,
              and human approval boundary.
            </p>
          </div>
          <div className="current-step">
            <span>Current workflow step</span>
            <strong>{run?.state.current_step?.replaceAll("_", " ") ?? "Choose a fixture"}</strong>
          </div>
        </div>

        <section className="panel composer" id="case-composer" aria-labelledby="composer-title">
          <div className="composer-copy">
            <p className="eyebrow">New support case</p>
            <h2 id="composer-title">Compose a case for review</h2>
            <p>
              Choose a deterministic fixture and provide the customer context. The workflow will
              normalize the complaint before it evaluates refund eligibility.
            </p>
            <div className="fixture-summary">
              <span className="fixture-icon" aria-hidden="true">↗</span>
              <div>
                <strong>Selected scenario</strong>
                <span>{scenario?.description ?? "Loading available scenarios…"}</span>
              </div>
            </div>
          </div>
          <div className="composer-form">
            <label>
              Scenario fixture
              <select
                aria-label="Scenario fixture"
                value={scenarioId}
                onChange={(event) => setScenarioId(event.target.value)}
              >
                {scenarios.map((item) => (
                  <option value={item.id} key={item.id}>
                    {item.id}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Customer ID
              <input
                aria-label="Customer ID"
                value={customerId}
                onChange={(event) => setCustomerId(event.target.value)}
              />
            </label>
            <label className="wide">
              Customer complaint
              <textarea
                aria-label="Customer complaint"
                value={complaint}
                onChange={(event) => setComplaint(event.target.value)}
              />
            </label>
            <button className="primary-action" disabled={busy} onClick={startRun}>
              <span aria-hidden="true">▶</span>
              {busy ? "Starting workflow…" : "Start workflow"}
            </button>
          </div>
        </section>

        {error && <div className="error-banner" role="alert">{error}</div>}

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

        <section className="artifact-heading" id="workflow-artifacts" aria-labelledby="artifacts-title">
          <div>
            <p className="eyebrow">Selected run</p>
            <h2 id="artifacts-title">Workflow artifacts</h2>
          </div>
          <p>Durable events lead; framework projections support the operational view.</p>
        </section>

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
          <div id="safe-explainer">
            <AssistantPanel state={run?.state ?? null} />
          </div>
        </div>
      </main>
    </div>
  );
}
