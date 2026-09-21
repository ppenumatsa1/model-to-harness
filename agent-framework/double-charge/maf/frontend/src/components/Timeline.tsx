import type { DurableEvent } from "../types";

export function Timeline({ events, selected }: { events: DurableEvent[]; selected: boolean }) {
  return (
    <section className="panel timeline-panel" aria-labelledby="timeline-title">
      <header className="panel-heading">
        <div>
          <p className="eyebrow">Native committed audit</p>
          <h2 id="timeline-title">Execution timeline</h2>
        </div>
        <span>{events.length} events</span>
      </header>
      <ol className="timeline" aria-label="Execution events" tabIndex={0}>
        {events.map((event) => (
          <li key={event.event_id}>
            <span className="sequence">{event.sequence}</span>
            <div>
              <p>{event.summary || event.event_type.replaceAll(".", " ").replaceAll("_", " ")}</p>
              <div className="event-line">
                <strong>{event.event_type}</strong>
                {event.node && <code>{event.node.replaceAll("_", " ")}</code>}
                {event.retry_attempt != null && <span className="retry">attempt {event.retry_attempt}</span>}
              </div>
              {event.transition && <small>{event.transition}</small>}
              {event.event_type.startsWith("maf.native.") && <small> Framework observation persisted after workflow execution returned.</small>}
              <details>
                <summary>Technical event details</summary>
                <pre>{JSON.stringify(event, null, 2)}</pre>
              </details>
            </div>
          </li>
        ))}
      </ol>
      {!events.length && <div className="empty">{selected ? "No committed events received yet." : "Select or start a case to inspect execution."}</div>}
    </section>
  );
}
