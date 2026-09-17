import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { ApprovalPanel } from "./components/ApprovalPanel";
import { AssistantPanel } from "./components/AssistantPanel";
import { AuditPanel } from "./components/AuditPanel";
import { RunInspector } from "./components/RunInspector";
import { Timeline } from "./components/Timeline";
import { WorkflowGraph } from "./components/WorkflowGraph";
import { useCaseHistory } from "./useCaseHistory";
import { useCaseWorkspace } from "./useCaseWorkspace";
import type { Scenario } from "./types";
import { clearStartIntent, readStartIntent, saveStartIntent, type StartIntent } from "./startIntent";

function urlCase() {
  return new URL(window.location.href).searchParams.get("case") || undefined;
}

export default function App() {
  const [initialStart] = useState<{ payload?: StartIntent; error?: string }>(() => {
    try {
      return { payload: readStartIntent(window.sessionStorage) };
    } catch {
      return { error: "Pending Start storage could not be read. Resolve it before starting another case." };
    }
  });
  const [startIntent, setStartIntent] = useState(initialStart.payload);
  const [startStorageError, setStartStorageError] = useState(initialStart.error);
  const starting = useRef(false);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioError, setScenarioError] = useState<string>();
  const [scenarioAttempt, setScenarioAttempt] = useState(0);
  const [scenarioId, setScenarioId] = useState("duplicate-confirmed");
  const [complaint, setComplaint] = useState("I was charged twice for the same purchase.");
  const [customerId, setCustomerId] = useState("customer-100");
  const [operatorId, setOperatorId] = useState("");
  const [caseId, setCaseId] = useState<string | undefined>(() => urlCase() ?? initialStart.payload?.existing_case_id);
  const [pendingStart, setPendingStart] = useState<string>();
  const [commands, setCommands] = useState<Record<string, string | undefined>>({});
  const [commandErrors, setCommandErrors] = useState<Record<string, string | undefined>>({});
  const selected = useRef(caseId);
  selected.current = caseId;
  const selectionVersion = useRef(0);
  const history = useCaseHistory();
  const workspace = useCaseWorkspace(caseId, pendingStart === caseId);
  const { run, events } = workspace;
  const busy = Boolean(caseId && commands[caseId]);
  const scenario = scenarios.find((item) => item.id === scenarioId);

  useEffect(() => {
    let active = true;
    setScenarioError(undefined);
    api.scenarios().then((available) => {
      if (active) setScenarios(available);
    }).catch(() => {
      if (active) setScenarioError("Could not load scenarios.");
    });
    return () => { active = false; };
  }, [scenarioAttempt]);

  useEffect(() => {
    const restore = () => {
      selectionVersion.current += 1;
      selected.current = urlCase();
      setCaseId(selected.current);
    };
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);

  useEffect(() => {
    if (run) history.update(run, pendingStart === run.state.case_id);
  }, [run, pendingStart, history.update]);

  function selectCase(id?: string) {
    selectionVersion.current += 1;
    selected.current = id;
    setCaseId(id);
    if (!id) setOperatorId("");
    const url = new URL(window.location.href);
    if (id) url.searchParams.set("case", id);
    else url.searchParams.delete("case");
    window.history.pushState({}, "", url);
  }

  async function command(target: string, label: string, action: () => Promise<unknown>) {
    const version = selectionVersion.current;
    setCommands((current) => ({ ...current, [target]: label }));
    setCommandErrors((current) => ({ ...current, [target]: undefined }));
    try {
      await action();
      if (selected.current === target && selectionVersion.current === version) await workspace.refresh(target);
    } catch (caught) {
      const detail = caught instanceof Error ? caught.message : "Request failed.";
      setCommandErrors((current) => ({
        ...current,
        [target]: `${label}: ${detail} The command outcome may be unknown; review persisted evidence before retrying.`
      }));
      if (selected.current === target && selectionVersion.current === version) {
        await workspace.refresh(target).catch(() => {});
      }
    } finally {
      setCommands((current) => ({ ...current, [target]: undefined }));
      void history.refresh();
    }
  }

  async function startRun() {
    if (!operatorId.trim() || startIntent || starting.current || startStorageError) return;
    const id = crypto.randomUUID();
    const payload = {
      request_id: crypto.randomUUID(),
      complaint: complaint.trim(), customer_id: customerId.trim(), scenario_id: scenarioId,
      operator_id: operatorId.trim(),
      existing_case_id: id, idempotency_key: `refund-${id}-${crypto.randomUUID()}`
    };
    try {
      saveStartIntent(window.sessionStorage, payload);
      setStartIntent(payload);
    } catch {
      setStartStorageError("Cannot retain the Start request. Nothing was submitted.");
      return;
    }
    await submitStart(payload);
  }

  async function submitStart(payload: StartIntent) {
    if (starting.current) return;
    starting.current = true;
    const id = payload.existing_case_id;
    setPendingStart(id);
    selectCase(id);
    try {
      await command(id, "Starting workflow", async () => {
        try {
          await api.start(payload);
        } catch (error) {
          if (error instanceof ApiError && error.status >= 400 && error.status < 500
            && ![408, 429].includes(error.status) && error.code !== "start_in_progress") {
            clearStartIntent(window.sessionStorage);
            setStartIntent(undefined);
          }
          throw error;
        }
        clearStartIntent(window.sessionStorage);
        setStartIntent(undefined);
      });
    } finally {
      setPendingStart(undefined);
      starting.current = false;
    }
  }

  return (
    <div className="app-shell case-workspace">
      <aside className="navigation-rail case-history" aria-label="Persisted cases">
        <a className="brand" href="#workspace">
          <span className="brand-mark" aria-hidden="true">M</span>
          <span><strong>MAF</strong><small>Workflow Lab</small></span>
        </a>
        <h2>Cases</h2>
        <button onClick={() => selectCase()}>New case</button>
        <p>All persisted MAF cases · newest first</p>
        <ol className="case-list">
          {history.items.map((item) => (
            <li key={item.case_id}>
              <button aria-current={caseId === item.case_id ? "page" : undefined}
                aria-label={`Select case ${item.case_id}: ${item.customer_id}, ${item.scenario_id}, ${item.terminal_status ?? item.status}`}
                onClick={() => selectCase(item.case_id)}>
                <strong>{item.customer_id}</strong>
                <span>{item.scenario_id}</span>
                <small>{item.terminal_status ?? item.status} · {item.current_step.replaceAll("_", " ")}</small>
                <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time>
                <small>Case {item.case_id}</small>
              </button>
            </li>
          ))}
        </ol>
        {history.loading && <p role="status">Loading cases…</p>}
        {history.error && <div role="alert">{history.error} <button onClick={() => void history.retry()}>Retry cases</button></div>}
        {history.loaded && !history.items.length && <p>No persisted cases yet. Start a new case.</p>}
        {history.hasMore && <button disabled={history.loading} onClick={() => void history.loadMore()}>Load more</button>}
        {history.loaded && history.items.length > 0 && !history.hasMore && <p>End of case history</p>}
      </aside>

      <main id="workspace">
        <header className="page-heading">
          <div>
            <p className="eyebrow">Microsoft Agent Framework</p>
            <h1>Double-charge case workspace</h1>
            <p>Native committed audit is the source of truth. Decisions and resume are explicit commands.</p>
          </div>
        </header>

        {startStorageError && <div role="alert">{startStorageError}</div>}
        {startIntent && <div role="status">
          A Start request is pending. Retry its original command; do not create a replacement case.
          <button disabled={Boolean(pendingStart)} onClick={() => void submitStart(startIntent)}>Retry same Start request</button>
        </div>}
        {!caseId ? (
          <section className="panel composer" aria-labelledby="composer-title">
            <div className="composer-copy">
              <p className="eyebrow">New support case</p>
              <h2 id="composer-title">Compose a case for review</h2>
              <p>{scenario?.description ?? "Loading available scenarios…"}</p>
            </div>
            <form className="composer-form" onSubmit={(event) => { event.preventDefault(); void startRun(); }}>
              <label>Scenario fixture
                <select value={scenarioId} onChange={(event) => setScenarioId(event.target.value)}>
                  {scenarios.map((item) => <option value={item.id} key={item.id}>{item.id}</option>)}
                </select>
              </label>
              <label>Customer ID
                <input required maxLength={128} value={customerId} onChange={(event) => setCustomerId(event.target.value)} />
              </label>
              <label>Operator identity
                <input required maxLength={128} value={operatorId} aria-describedby="operator-identity-note"
                  onChange={(event) => setOperatorId(event.target.value)} />
              </label>
              <p id="operator-identity-note" className="boundary-note">Operator-provided identity; not authenticated.</p>
              <label className="wide">Customer complaint
                <textarea required minLength={3} maxLength={4000} value={complaint} onChange={(event) => setComplaint(event.target.value)} />
              </label>
              <button className="primary-action" disabled={Boolean(pendingStart) || Boolean(startIntent) || Boolean(startStorageError) || !scenarios.length || !customerId.trim() || !operatorId.trim() || complaint.trim().length < 3}>
                {pendingStart ? "Another case is starting…" : "Start workflow"}
              </button>
              {scenarioError && <div role="alert">{scenarioError} <button type="button" onClick={() => setScenarioAttempt((value) => value + 1)}>Retry scenarios</button></div>}
            </form>
          </section>
        ) : (
          <>
            <section className="panel case-context" aria-label="Selected case context">
              <h2>Selected case</h2>
              <p>Case <code>{caseId}</code></p>
              {run && <dl>
                <dt>Scenario fixture</dt><dd>{run.state.scenario_id}</dd>
                <dt>Customer ID</dt><dd>{run.state.customer_id}</dd>
                <dt>Customer complaint</dt><dd>{run.state.complaint}</dd>
                <dt>Status / current step</dt><dd>{run.state.status} / {run.state.current_step.replaceAll("_", " ")}</dd>
              </dl>}
              {workspace.loading && <p role="status">{pendingStart === caseId ? "Waiting for the new case to be persisted…" : "Loading selected case…"}</p>}
              {busy && <p role="status">{commands[caseId]}… Observation remains live.</p>}
            </section>
            {commandErrors[caseId] && <div className="error-banner" role="alert">{commandErrors[caseId]}</div>}
            <ApprovalPanel key={run?.state.run_id ?? caseId} run={run ?? null} busy={busy}
              onApprove={(decision, reviewer, reason) => {
                if (!run?.state.checkpoint_id) return Promise.resolve();
                return command(caseId, "Recording decision", () => api.approve(run.state.run_id, {
                  checkpoint_id: run.state.checkpoint_id!, decision, reviewer_id: reviewer, reason
                }));
              }}
              onResume={(resumeOperator) => {
                if (!run?.state.checkpoint_id) return Promise.resolve();
                return command(caseId, "Resuming checkpoint", () => api.resume(run.state.run_id, run.state.checkpoint_id!, resumeOperator));
              }} />
          </>
        )}
        <div className="observation-status" role="status">
          Native audit: {workspace.connection}
        </div>
        {workspace.error && <div className="error-banner" role="alert">
          {workspace.error} <button onClick={workspace.retry}>Retry observation</button>
        </div>}
        <Timeline events={events} selected={Boolean(caseId)} />
        <RunInspector key={caseId ?? "draft"} state={run?.state ?? null} memory={run?.memory ?? {}} outcome={run?.outcome} />
        <details className="supporting-view">
          <summary>Workflow graph</summary>
          <WorkflowGraph graph={run?.graph ?? { nodes: [], edges: [], parallel_groups: [] }} state={run?.state ?? null} events={events} />
        </details>
        <details className="supporting-view">
          <summary>Safe run explainer</summary>
          <AssistantPanel state={run?.state ?? null} />
        </details>
      </main>
      <aside className="audit-rail" aria-label="Audit trail">
        <AuditPanel events={events} run={run ?? null} />
      </aside>
    </div>
  );
}
