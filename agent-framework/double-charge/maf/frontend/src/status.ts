import type { DurableEvent, WorkflowGraph, WorkflowState } from "./types";

export type VisualStatus = "pending" | "running" | "complete" | "failed" | "paused";

export function nodeStatuses(
  graph: WorkflowGraph,
  state: WorkflowState | null,
  events: DurableEvent[]
): Record<string, VisualStatus> {
  const result = Object.fromEntries(graph.nodes.map((node) => [node, "pending"])) as Record<
    string,
    VisualStatus
  >;
  for (const event of events) {
    if (!event.node || !(event.node in result)) continue;
    if (event.event_type === "node.started") result[event.node] = "running";
    if (event.event_type === "node.completed") result[event.node] = "complete";
    if (event.event_type === "run.failed") result[event.node] = "failed";
    if (event.event_type === "approval.requested") result[event.node] = "paused";
    if (event.event_type === "approval.resolved") result[event.node] = "complete";
  }
  if (state?.status === "paused") result.approval_checkpoint = "paused";
  return result;
}

export function selectedTransitions(events: DurableEvent[]): Set<string> {
  return new Set(
    events
      .filter((event) => event.event_type === "edge.selected" && event.transition)
      .map((event) => event.transition as string)
  );
}

