import { useState } from "react";
import type { Outcome, WorkflowState } from "../types";

type Tab = "state" | "memory" | "outcome";

export function RunInspector({
  state,
  memory,
  outcome
}: {
  state: WorkflowState | null;
  memory: Record<string, unknown>;
  outcome?: Outcome | null;
}) {
  const [tab, setTab] = useState<Tab>("state");
  return (
    <section className="panel inspector-panel" aria-label="Run data inspector">
      <div className="tabs">
        {(["state", "memory", "outcome"] as Tab[]).map((item) => (
          <button aria-pressed={tab === item} className={tab === item ? "active" : ""} key={item} onClick={() => setTab(item)}>
            {item}
          </button>
        ))}
      </div>
      <p className="boundary-note">
        State drives this execution. Selected memory is intentionally retained. Model context is
        temporary and is never the source of truth.
      </p>
      <pre>
        {JSON.stringify(
          tab === "state"
            ? state
            : tab === "memory"
              ? memory
              : outcome ?? { status: "Pending — no persisted outcome is available yet." },
          null,
          2
        )}
      </pre>
    </section>
  );
}
