import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { ApprovalPanel } from "./components/ApprovalPanel";
import { SelectedRunAssistant } from "./components/AssistantPanel";
import { AuditPanel } from "./components/AuditPanel";
import { RunInspector } from "./components/RunInspector";
import { Timeline } from "./components/Timeline";
import { WorkflowGraph } from "./components/WorkflowGraph";
import type { Scenario } from "./types";
import { useCaseHistory } from "./useCaseHistory";
import { useCaseWorkspace } from "./useCaseWorkspace";
import "./styles.css";

export { SelectedRunAssistant, Timeline, WorkflowGraph as Graph };

function urlCase() { return new URL(window.location.href).searchParams.get("case") || undefined; }

export default function App() {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [scenarioError, setScenarioError] = useState<string>();
  const [scenarioAttempt, setScenarioAttempt] = useState(0);
  const [scenarioId, setScenarioId] = useState("duplicate-confirmed");
  const [complaint, setComplaint] = useState("I was charged twice for the same purchase.");
  const [customerId, setCustomerId] = useState("customer-demo");
  const [operatorId, setOperatorId] = useState("");
  const [caseId, setCaseId] = useState<string | undefined>(urlCase);
  const [pendingStart, setPendingStart] = useState<string>();
  const [commands, setCommands] = useState<Record<string, string | undefined>>({});
  const [commandErrors, setCommandErrors] = useState<Record<string, string | undefined>>({});
  const selected = useRef(caseId);
  selected.current = caseId;
  const selectionVersion = useRef(0);
  const commandLocks = useRef(new Set<string>());
  const history = useCaseHistory();
  const workspace = useCaseWorkspace(caseId, pendingStart === caseId);
  const { run, events } = workspace;
  const busy = Boolean(caseId && commands[caseId]);

  useEffect(() => {
    let active = true;
    setScenarioError(undefined);
    api.scenarios().then((available) => {
      if (active) setScenarios(available.filter((item) => item.id !== "verification-mismatch"));
    }).catch(() => { if (active) setScenarioError("Could not load scenarios."); });
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
    if (commandLocks.current.has(target)) return;
    commandLocks.current.add(target);
    const version = selectionVersion.current;
    setCommands((current) => ({ ...current, [target]: label }));
    setCommandErrors((current) => ({ ...current, [target]: undefined }));
    try {
      await action();
      if (selected.current === target && selectionVersion.current === version) await workspace.refresh(target);
    } catch (caught) {
      const detail = caught instanceof Error ? caught.message : "Request failed.";
      setCommandErrors((current) => ({
        ...current, [target]: `${label}: ${detail} The command outcome may be unknown; review persisted evidence before retrying. No command was automatically retried.`
      }));
      if (selected.current === target && selectionVersion.current === version) {
        await workspace.refresh(target).catch(() => {});
      }
    } finally {
      commandLocks.current.delete(target);
      setCommands((current) => ({ ...current, [target]: undefined }));
      void history.refresh();
    }
  }
  async function startRun() {
    if (pendingStart || !operatorId.trim() || !customerId.trim() || complaint.trim().length < 5) return;
    const id = crypto.randomUUID();
    const payload = {
      complaint: complaint.trim(), customer_id: customerId.trim(), scenario_id: scenarioId,
      operator_id: operatorId.trim(), existing_case_id: id, idempotency_key: `refund-${id}-${crypto.randomUUID()}`
    };
    setPendingStart(id);
    selectCase(id);
    await command(id, "Starting workflow", () => api.start(payload));
    setPendingStart(undefined);
  }

  return <div className="app-shell case-workspace">
    <aside className="navigation-rail case-history" aria-label="Persisted cases">
      <a className="brand" href="#workspace"><span className="brand-mark">LG</span><span><strong>LangGraph</strong><small>Workflow Lab</small></span></a>
      <h2>Cases</h2><button onClick={() => selectCase()}>New case</button>
      <p>All persisted LangGraph cases · newest first</p>
      <ol className="case-list">{history.items.map((item) => <li key={item.case_id}>
        <button aria-current={caseId === item.case_id ? "page" : undefined}
          aria-label={`Select case ${item.case_id}: ${item.customer_id}, ${item.scenario_id ?? "Not recorded"}, ${item.terminal_status ?? item.status}`}
          onClick={() => selectCase(item.case_id)}>
          <strong>{item.customer_id}</strong><span>{item.scenario_id ?? "Not recorded"}</span>
          <small>{item.terminal_status ?? item.status} · {item.current_step.replaceAll("_", " ")}</small>
          <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time><small>Case {item.case_id}</small>
        </button>
      </li>)}</ol>
      {history.loading && <p role="status">Loading cases…</p>}
      {history.error && <div role="alert">{history.error} <button onClick={() => void history.retry()}>Retry cases</button></div>}
      {history.loaded && !history.items.length && <p>No persisted cases yet. Start a new case.</p>}
      {history.hasMore && <button disabled={history.loading} onClick={() => void history.loadMore()}>Load more</button>}
      {history.loaded && history.items.length > 0 && !history.hasMore && <p>End of case history</p>}
    </aside>
    <main id="workspace">
      <header className="page-heading"><p className="eyebrow">LangGraph StateGraph</p>
        <h1>Double-charge case workspace</h1>
        <p>Native committed audit is the source of truth. Decisions and resume are explicit commands.</p>
      </header>
      {!caseId ? <section className="panel composer" aria-labelledby="composer-title">
        <h2 id="composer-title">Compose a case for review</h2>
        <p>{scenarios.find((item) => item.id === scenarioId)?.description ?? "Choose a deterministic teaching scenario."}</p>
        <form className="composer-form" onSubmit={(event) => { event.preventDefault(); void startRun(); }}>
          <label>Scenario fixture<select value={scenarioId} onChange={(e) => setScenarioId(e.target.value)}>
            {scenarios.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}
          </select></label>
          <label>Customer ID<input required maxLength={128} value={customerId} onChange={(e) => setCustomerId(e.target.value)} /></label>
          <label>Operator identity<input required maxLength={128} value={operatorId} onChange={(e) => setOperatorId(e.target.value)} /></label>
          <p className="boundary-note">Operator-provided identity; not authenticated.</p>
          <label className="wide">Customer complaint<textarea required minLength={5} maxLength={4000} value={complaint} onChange={(e) => setComplaint(e.target.value)} /></label>
          <button className="primary-action" disabled={Boolean(pendingStart) || !scenarios.length || !operatorId.trim() || !customerId.trim() || complaint.trim().length < 5}>
            {pendingStart ? "Another case is starting…" : "Start workflow"}
          </button>
          {scenarioError && <div role="alert">{scenarioError} <button type="button" onClick={() => setScenarioAttempt((value) => value + 1)}>Retry scenarios</button></div>}
        </form>
      </section> : <>
        <section className="panel case-context" aria-label="Selected case context">
          <h2>Selected case</h2><p>Case <code>{caseId}</code></p>
          {run && <dl>
            <dt>Scenario fixture</dt><dd>{run.state.scenario_id ?? "Not recorded"}</dd>
            <dt>Customer ID</dt><dd>{run.state.customer_id}</dd>
            <dt>Customer complaint</dt><dd>{run.state.complaint ?? "Not recorded"}</dd>
            <dt>Status / current step</dt><dd>{run.state.status} / {run.state.current_step.replaceAll("_", " ")}</dd>
          </dl>}
          {workspace.loading && <p role="status">{pendingStart === caseId ? "Waiting for the new case to be persisted…" : "Loading selected case…"}</p>}
          {busy && <p role="status">{commands[caseId]}… Observation remains live.</p>}
        </section>
        {commandErrors[caseId] && <div className="error-banner" role="alert">{commandErrors[caseId]}</div>}
        <ApprovalPanel key={run?.state.run_id ?? caseId} run={run} busy={busy}
          onApprove={(decision, reviewer, reason) => {
            if (!run?.state.checkpoint_id) return Promise.resolve();
            return command(caseId, "Recording decision", () => api.approve(caseId, {
              checkpoint_id: run.state.checkpoint_id!, decision, reviewer_id: reviewer, reason
            }));
          }}
          onResume={(operator) => {
            if (!run?.state.checkpoint_id) return Promise.resolve();
            return command(caseId, "Resuming checkpoint", () => api.resume(caseId, run.state.checkpoint_id!, operator));
          }} />
      </>}
      <div className="observation-status" role="status">Native audit: {workspace.connection}</div>
      {workspace.error && <div className="error-banner" role="alert">{workspace.error} <button onClick={workspace.retry}>Retry observation</button></div>}
      <Timeline events={events} selected={Boolean(caseId)} />
      <RunInspector key={caseId ?? "draft"} run={run} />
      <details className="supporting-view"><summary>Workflow graph</summary><WorkflowGraph run={run} /></details>
      <details className="supporting-view"><summary>Safe run explainer</summary><SelectedRunAssistant caseId={caseId} /></details>
    </main>
    <aside className="audit-rail" aria-label="Audit trail"><AuditPanel events={events} run={run} /></aside>
  </div>;
}
