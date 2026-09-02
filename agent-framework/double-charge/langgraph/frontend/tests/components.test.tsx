import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Graph, Timeline } from "../src/App";
import type { CaseView, NativeEvent } from "../src/types";

const run: CaseView = {
  case_id: "case-1",
  run_id: "run-1",
  status: "paused",
  current_step: "request_approval",
  approval_required: true,
  checkpoint_id: "checkpoint-1",
  workflow_state: {},
  selected_memory: {}
};

const events: NativeEvent[] = [
  {
    sequence: 1,
    event_id: "event-1",
    case_id: "case-1",
    run_id: "run-1",
    event_type: "parallel_branch_started",
    timestamp: "2026-01-01T00:00:00Z",
    node: "dispatch_validations",
    status: "running",
    summary: "Billing and policy validation started in parallel",
    data: { branch: "billing+policy" }
  }
];

describe("teaching views", () => {
  it("shows the parallel graph and durable timeline", () => {
    render(
      <>
        <Graph run={run} events={events} />
        <Timeline events={events} />
      </>
    );
    expect(screen.getByText("billing validation")).toBeInTheDocument();
    expect(screen.getByText("policy validation")).toBeInTheDocument();
    expect(
      screen.getByText("Billing and policy validation started in parallel")
    ).toBeInTheDocument();
    expect(screen.getByText("paused")).toBeInTheDocument();
  });
});

