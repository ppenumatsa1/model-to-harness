import {
  type JsonSerializable,
  useAgent,
  useAgentContext
} from "@copilotkit/react-core/v2";
import { FormEvent, useMemo, useState } from "react";

import { recordApproval, resumeCase, startCase } from "./api";
import type { CaseView, NativeEvent, RunStatus } from "./types";
import { useRun } from "./useRun";
import "./styles.css";

const GRAPH = [
  "normalize_complaint",
  "load_account",
  "detect_duplicate",
  "billing_validation",
  "policy_validation",
  "join_validations",
  "request_approval",
  "submit_refund",
  "verify_refund",
  "notify_customer",
  "completed"
];

const SCENARIOS = [
  ["duplicate-confirmed", "Duplicate confirmed"],
  ["no-duplicate", "No duplicate"],
  ["approval-denied", "Approval denied"],
  ["transient-failure", "Transient read failure"],
  ["retry-safe-refund", "Retry-safe refund"],
  ["resumed-approval", "Resumed approval"],
  ["verification-mismatch", "Verification mismatch"]
];

function statusFor(node: string, run: CaseView | undefined, events: NativeEvent[]) {
  if (!run) return "idle";
  if (run.current_step === node) return run.status === "paused" ? "paused" : "active";
  if (events.some((event) => event.node === node)) return "visited";
  if (node === "completed" && ["completed", "failed", "manual_review"].includes(run.status)) {
    return run.status;
  }
  return "idle";
}

export function Graph({ run, events }: { run?: CaseView; events: NativeEvent[] }) {
  return (
    <section className="panel graph-panel" aria-label="Workflow graph">
      <header>
        <div>
          <span className="eyebrow">StateGraph</span>
          <h2>Execution graph</h2>
        </div>
        <span className={`status-pill ${run?.status ?? "idle"}`}>{run?.status ?? "idle"}</span>
      </header>
      <div className="graph">
        {GRAPH.map((node, index) => (
          <div
            className={`node ${statusFor(node, run, events)} ${
              node.includes("validation") && node !== "join_validations" ? "parallel" : ""
            }`}
            key={node}
          >
            <span>{index + 1}</span>
            {node.replaceAll("_", " ")}
          </div>
        ))}
      </div>
      <p className="legend">
        Billing and policy nodes fan out together, then join before the durable approval
        checkpoint.
      </p>
    </section>
  );
}

export function Timeline({ events }: { events: NativeEvent[] }) {
  return (
    <section className="panel timeline-panel" aria-label="Execution timeline">
      <header>
        <div>
          <span className="eyebrow">Native durable events</span>
          <h2>Timeline</h2>
        </div>
        <span className="count">{events.length}</span>
      </header>
      <div className="timeline">
        {events.length === 0 && <p className="empty">Start a case to inspect its audit trail.</p>}
        {events.map((event) => (
          <article key={event.event_id} className={`event ${event.status ?? ""}`}>
            <div className="event-marker">{event.sequence}</div>
            <div>
              <div className="event-title">
                <strong>{event.event_type.replaceAll("_", " ")}</strong>
                <time>{new Date(event.timestamp).toLocaleTimeString()}</time>
              </div>
              <p>{event.summary}</p>
              <div className="chips">
                {event.node && <span>{event.node}</span>}
                {Object.entries(event.data).map(([key, value]) => (
                  <span key={key}>
                    {key}: {String(value)}
                  </span>
                ))}
              </div>
            </div>
          </article>
        ))}
      </div>
    </section>
  );
}

function Inspector({ run }: { run?: CaseView }) {
  const [tab, setTab] = useState<"state" | "memory" | "outcome">("state");
  const value =
    tab === "state"
      ? run?.workflow_state
      : tab === "memory"
        ? run?.selected_memory
        : run?.outcome;
  return (
    <section className="panel inspector">
      <div className="tabs" role="tablist" aria-label="Run records">
        {(["state", "memory", "outcome"] as const).map((name) => (
          <button
            className={tab === name ? "selected" : ""}
            key={name}
            onClick={() => setTab(name)}
            role="tab"
          >
            {name}
          </button>
        ))}
      </div>
      <p className="boundary">
        {tab === "state"
          ? "Current execution projection — not a transcript or checkpoint payload."
          : tab === "memory"
            ? "Narrow customer/case facts retained separately from workflow state."
            : "Framework-neutral terminal contract."}
      </p>
      <pre>{JSON.stringify(value ?? {}, null, 2)}</pre>
    </section>
  );
}

function ApprovalPanel({
  run,
  onDone
}: {
  run: CaseView;
  onDone: () => Promise<void>;
}) {
  const [reviewer, setReviewer] = useState("teaching-reviewer");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const decide = async (decision: "approve" | "deny") => {
    if (!run.checkpoint_id) return;
    setBusy(true);
    try {
      await recordApproval(run.case_id, run.checkpoint_id, decision, reviewer, reason);
      await resumeCase(run.case_id);
      await onDone();
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="approval" aria-label="Human approval">
      <span className="eyebrow">Durable interrupt</span>
      <h2>Reviewer decision required</h2>
      <p>
        The command is recorded first. Resume is a separate API call that supplies it to
        LangGraph&apos;s pending interrupt.
      </p>
      <input
        aria-label="Reviewer identifier"
        value={reviewer}
        onChange={(event) => setReviewer(event.target.value)}
      />
      <textarea
        aria-label="Decision reason"
        placeholder="Optional reason"
        value={reason}
        onChange={(event) => setReason(event.target.value)}
      />
      <div className="approval-actions">
        <button disabled={busy || !reviewer} onClick={() => void decide("deny")}>
          Deny
        </button>
        <button
          className="primary"
          disabled={busy || !reviewer}
          onClick={() => void decide("approve")}
        >
          {busy ? "Resuming…" : "Approve & resume"}
        </button>
      </div>
    </section>
  );
}

export function SelectedRunAssistant({
  caseId,
  safeContext
}: {
  caseId?: string;
  safeContext: JsonSerializable;
}) {
  useAgentContext({
    description:
      "Allowlisted selected LangGraph run summaries. Never includes prompts, chain-of-thought, secrets, or checkpoint payloads.",
    value: safeContext
  });
  const { agent, isReady } = useAgent({
    agentId: "selected-run-panel",
    runtimeAgentId: "selected-run",
    threadId: caseId ?? "no-selected-run"
  });
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const ask = async () => {
    if (!caseId) return;
    setBusy(true);
    setError("");
    try {
      agent.setMessages([]);
      agent.setState({});
      const result = await agent.runAgent({ runId: crypto.randomUUID() });
      const assistant = [...result.newMessages]
        .reverse()
        .find((message) => message.role === "assistant");
      const content = assistant?.content;
      setAnswer(typeof content === "string" ? content : "No safe summary was returned.");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Selected-run explanation failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="panel assistant">
      <span className="eyebrow">CopilotKit selected-run context</span>
      <h2>Safe run explainer</h2>
      <p>
        CopilotKit&apos;s supported AG-UI client invokes the read-only selected-run runtime.
        Workflow commands remain explicit buttons.
      </p>
      <button
        className="primary"
        disabled={!caseId || !isReady || busy}
        onClick={() => void ask()}
      >
        {busy ? "Reading durable events…" : "Explain selected run"}
      </button>
      {error && <p className="error">{error}</p>}
      {answer && (
        <blockquote>{answer}</blockquote>
      )}
    </section>
  );
}

export default function App() {
  const [caseId, setCaseId] = useState<string>();
  const [complaint, setComplaint] = useState(
    "I was charged twice for the same purchase and need the duplicate refunded."
  );
  const [customerId, setCustomerId] = useState("customer-demo");
  const [scenario, setScenario] = useState("duplicate-confirmed");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const { run, events, aguiEvents, connection, refresh } = useRun(caseId);

  const safeContext = useMemo(
    () => ({
      status: run?.status ?? null,
      currentStep: run?.current_step ?? null,
      summaries: events
        .filter((event) =>
          ["decision_summary", "refund_verification", "run_completed", "run_failed"].includes(
            event.event_type
          )
        )
        .map((event) => event.summary)
    }),
    [run, events]
  );

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setStarting(true);
    setError("");
    try {
      const response = await startCase({
        complaint,
        customer_id: customerId,
        scenario_id: scenario
      });
      setCaseId(response.case_id);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not start the workflow");
    } finally {
      setStarting(false);
    }
  };

  return (
    <main>
      <nav>
        <div className="brand-mark">LG</div>
        <div>
          <strong>Double-charge lab</strong>
          <span>LangGraph workstream</span>
        </div>
        <div className={`connection ${connection}`}>
          <i />
          AG-UI {connection} · {aguiEvents.length} projected
        </div>
      </nav>

      <header className="hero">
        <div>
          <span className="eyebrow">Model → graph → durable outcome</span>
          <h1>See every safe workflow decision.</h1>
          <p>
            Parallel deterministic checks, bounded retries, a PostgreSQL checkpoint, and
            explicit human resume — without exposing private model reasoning.
          </p>
        </div>
        <form onSubmit={(event) => void submit(event)}>
          <label>
            Scenario
            <select value={scenario} onChange={(event) => setScenario(event.target.value)}>
              {SCENARIOS.map(([value, label]) => (
                <option value={value} key={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Customer
            <input value={customerId} onChange={(event) => setCustomerId(event.target.value)} />
          </label>
          <label>
            Complaint
            <textarea
              value={complaint}
              onChange={(event) => setComplaint(event.target.value)}
            />
          </label>
          <button className="primary launch" disabled={starting}>
            {starting ? "Running graph…" : "Start durable run"}
          </button>
          {error && <p className="error">{error}</p>}
        </form>
      </header>

      {run?.status === "paused" && <ApprovalPanel run={run} onDone={refresh} />}

      <div className="workspace">
        <Graph run={run} events={events} />
        <Timeline events={events} />
        <Inspector run={run} />
        <SelectedRunAssistant caseId={caseId} safeContext={safeContext} />
      </div>

      <footer>
        <span>State ≠ memory ≠ audit ≠ model context</span>
        <span>{renderOutcome(run?.status, run?.outcome?.failure_code)}</span>
      </footer>
    </main>
  );
}

function renderOutcome(status?: RunStatus, failure?: string) {
  if (!status) return "No selected run";
  return failure ? `${status}: ${failure}` : status;
}
