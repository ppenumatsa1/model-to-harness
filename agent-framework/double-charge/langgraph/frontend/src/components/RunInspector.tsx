import { useState } from "react";
import type { Workspace } from "../types";

export function RunInspector({ run }: { run?: Workspace }) {
  const [tab, setTab] = useState<"state" | "memory" | "outcome">("state");
  return <section className="panel inspector-panel" aria-label="Run data inspector">
    <div className="tabs">{(["state", "memory", "outcome"] as const).map((name) =>
      <button key={name} aria-pressed={tab === name} onClick={() => setTab(name)}>{name}</button>
    )}</div>
    <p className="boundary-note">{tab === "memory"
      ? "Selected memory is intentionally separate. An empty object while paused means no selected memory has been persisted yet."
      : "Safe persisted projection only. State ≠ memory ≠ audit ≠ model context. No raw checkpoint payloads."}</p>
    <pre>{JSON.stringify(tab === "state" ? run?.state ?? {}
      : tab === "memory" ? run?.memory ?? {} : run?.outcome ?? { status: "Pending — no persisted outcome is available yet." }, null, 2)}</pre>
  </section>;
}
