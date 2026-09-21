import type { Workspace } from "../types";

export function WorkflowGraph({ run }: { run?: Workspace }) {
  return <section className="panel graph-panel" aria-label="Workflow graph">
    <span className="eyebrow">LangGraph StateGraph</span><h2>Execution graph</h2>
    <p>{run?.state.status ?? "No selected run"}</p>
    <div className="graph-grid">
      {run?.graph.nodes.map((node) => <div key={node.id}
        className={`node-card ${run.node_statuses[node.id] ?? "pending"} ${run.graph.parallel_groups.some((group) => group.includes(node.id)) ? "parallel" : ""}`}>
        <strong>{node.label}</strong><small>{run.node_statuses[node.id] ?? "pending"}</small>
      </div>)}
    </div>
    <ul className="edge-list">{run?.graph.edges.map((edge, index) =>
      <li key={`${edge.source}-${edge.target}-${index}`}>{edge.source} → {edge.target}{edge.label ? ` (${edge.label})` : ""}</li>
    )}</ul>
    <p className="boundary-note">Billing and policy validation fan out in parallel. Node status is a native persisted projection, not proof inferred from a node mention.</p>
  </section>;
}
