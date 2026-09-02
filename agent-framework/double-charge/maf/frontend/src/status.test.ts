import { describe, expect, it } from "vitest";
import { nodeStatuses, selectedTransitions } from "./status";
import type { DurableEvent, WorkflowGraph, WorkflowState } from "./types";

const graph: WorkflowGraph = {
  nodes: ["prepare_validation", "billing_validation", "policy_validation", "approval_checkpoint"],
  edges: [["prepare_validation", "billing_validation"]],
  parallel_groups: [["billing_validation", "policy_validation"]]
};

const baseEvent = {
  event_id: "event",
  case_id: "case",
  run_id: "run",
  summary: "safe summary",
  payload: {},
  created_at: "2026-01-01T00:00:00Z"
};

describe("workflow status projection", () => {
  it("shows parallel completion, selected edges, and a paused approval", () => {
    const events: DurableEvent[] = [
      {
        ...baseEvent,
        sequence: 1,
        event_type: "node.completed",
        node: "billing_validation"
      },
      {
        ...baseEvent,
        event_id: "edge",
        sequence: 2,
        event_type: "edge.selected",
        transition: "prepare_validation->billing_validation"
      }
    ];
    const state = {
      status: "paused",
      approval_required: true
    } as WorkflowState;
    expect(nodeStatuses(graph, state, events)).toMatchObject({
      billing_validation: "complete",
      approval_checkpoint: "paused"
    });
    expect(selectedTransitions(events).has("prepare_validation->billing_validation")).toBe(true);
  });
});
