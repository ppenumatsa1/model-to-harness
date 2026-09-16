import { businessAudit, resolutionLabel } from "../businessAudit";
import type { DurableEvent, RunView } from "../types";

export function AuditPanel({ events, run }: { events: DurableEvent[]; run: RunView | null }) {
  const { entries, incompatible } = businessAudit(events);
  return (
    <section className="panel audit-panel" aria-labelledby="audit-title">
      <header className="panel-heading"><div>
        <h2 id="audit-title">Audit trail</h2>
        <p><span className="environment-badge">Simulation</span></p>
        {run && <dl>
          <dt>Case</dt><dd>{run.state.case_id}</dd>
          <dt>Customer</dt><dd>{run.state.customer_id}</dd>
          <dt>Current resolution (snapshot)</dt>
          <dd>{resolutionLabel(run.outcome?.terminal_status ?? run.state.terminal_status)}</dd>
        </dl>}
      </div></header>
      <p className="boundary-note">Recorded business actions, oldest first. Technical records remain in the execution timeline.</p>
      {incompatible && <p className="boundary-note" role="status">Some records have incompatible audit versions or actor information and cannot appear as business actions.</p>}
      <ol className="audit-events" aria-label="Business actions" tabIndex={0}>
        {entries.map((entry) => (
          <li key={entry.id}>
            <strong>{entry.title}</strong>
            <p>{entry.description}</p>
            <p>{entry.actor}</p>
            <time dateTime={entry.recordedAt}>{new Date(entry.recordedAt).toLocaleString()}</time>
            {entry.evidence.length > 0 && <details>
              <summary>Business evidence</summary>
              <dl>{entry.evidence.map(({ label, value }) => (
                <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
              ))}</dl>
            </details>}
          </li>
        ))}
      </ol>
      {!entries.length && <p className="empty">{run ? "No business actions recorded yet." : "Select a case to view its audit trail."}</p>}
    </section>
  );
}
