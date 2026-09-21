import type { NativeEvent } from "../types";

export function Timeline({ events, selected = true }: { events: NativeEvent[]; selected?: boolean }) {
  return <section className="panel timeline-panel" aria-label="Execution timeline">
    <header><span className="eyebrow">Native durable events</span><h2>Execution timeline</h2></header>
    <ol className="timeline" aria-label="Execution events" tabIndex={0}>
      {events.map((event) => <li key={event.event_id}>
        <span className="sequence">{event.sequence}</span>
        <div><strong>{event.event_type.replaceAll("_", " ")}</strong>
          <p>{event.summary}</p>
          <small>{event.node} · {new Date(event.timestamp).toLocaleString()}</small>
          {typeof event.data.attempt === "number" && <p>Attempt {event.data.attempt}</p>}
          {typeof event.data.checkpoint_id === "string" && <p>Checkpoint <code>{event.data.checkpoint_id}</code></p>}
        </div>
      </li>)}
    </ol>
    {!events.length && <p className="empty">{selected ? "No committed events received yet." : "Select a case to inspect its audit trail."}</p>}
  </section>;
}
