import type { AguiEvent, DurableEvent } from "../types";

export function Timeline({
  events,
  aguiEvents,
  malformed,
  disconnected
}: {
  events: DurableEvent[];
  aguiEvents: AguiEvent[];
  malformed: number;
  disconnected: boolean;
}) {
  return (
    <section className="panel timeline-panel" aria-labelledby="timeline-title">
      <header className="panel-heading">
        <div>
          <p className="eyebrow">Durable audit first</p>
          <h2 id="timeline-title">Execution timeline</h2>
        </div>
        <div className="stream-health">
          <span className={disconnected || malformed ? "dot warning" : "dot connected"} />
          AG-UI{" "}
          {disconnected
            ? "disconnected"
            : malformed
              ? `${malformed} malformed`
              : `${aguiEvents.length} projected`}
        </div>
      </header>
      <ol className="timeline">
        {events.map((event) => (
          <li key={event.event_id}>
            <span className="sequence">{event.sequence}</span>
            <div>
              <div className="event-line">
                <strong>{event.event_type}</strong>
                {event.node && <code>{event.node}</code>}
                {event.retry_attempt && <span className="retry">attempt {event.retry_attempt}</span>}
              </div>
              <p>{event.summary}</p>
              {event.transition && <small>{event.transition}</small>}
            </div>
          </li>
        ))}
      </ol>
      {!events.length && <div className="empty">Start a fixture to inspect ordered events.</div>}
    </section>
  );
}
