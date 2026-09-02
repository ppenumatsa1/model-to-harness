import type { DurableEvent, WorkflowGraph as Graph, WorkflowState } from "../types";
import { nodeStatuses, selectedTransitions } from "../status";

export function WorkflowGraph({
  graph,
  state,
  events
}: {
  graph: Graph;
  state: WorkflowState | null;
  events: DurableEvent[];
}) {
  const statuses = nodeStatuses(graph, state, events);
  const transitions = selectedTransitions(events);
  const parallel = new Set(graph.parallel_groups.flat());
  return (
    <section className="panel graph-panel" aria-labelledby="graph-title">
      <header className="panel-heading">
        <div>
          <p className="eyebrow">Explicit MAF graph</p>
          <h2 id="graph-title">Nodes, routes, and parallel join</h2>
        </div>
        <span className="framework-pill">WorkflowBuilder</span>
      </header>
      <div className="graph-grid">
        {graph.nodes.map((node, index) => (
          <article
            className={`node-card ${statuses[node]} ${parallel.has(node) ? "parallel" : ""}`}
            key={node}
            data-testid={`node-${node}`}
          >
            <span className="node-index">{String(index + 1).padStart(2, "0")}</span>
            <strong>{node.replaceAll("_", " ")}</strong>
            <small>{parallel.has(node) ? "parallel branch" : statuses[node]}</small>
          </article>
        ))}
      </div>
      <div className="edge-list" aria-label="Workflow edges">
        {graph.edges.map(([source, target, label]) => {
          const key = `${source}->${target}`;
          return (
            <span className={transitions.has(key) ? "edge selected" : "edge"} key={`${key}:${label}`}>
              {source} → {target}
              {label ? ` · ${label}` : ""}
            </span>
          );
        })}
      </div>
    </section>
  );
}

