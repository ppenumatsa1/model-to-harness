import { describe, expect, it } from "vitest";
import { caseStatus } from "./status";
import type { CheckoutCase } from "./types";

const baseCase: CheckoutCase = {
  case_id: "case-1",
  run_id: "run-1",
  fixture_id: "recoverable-inventory-reservation",
  phase: "closed",
  diagnostic_disposition: "recover_inventory",
  approval_decision: "not_required",
  approval_request_id: null,
  remediation_action: "recreate_inventory_reservation",
  remediation_status: "applied",
  verification_result: true,
  terminal_status: "recovered",
  failure_code: "none",
  workspace_artifact: {
    artifact_id: "artifact-1",
    kind: "checkout_recovery_plan_evidence_summary",
    revision: 3,
    updated_at: "2026-01-01T00:00:00Z"
  }
};

describe("case status", () => {
  it("presents a pending approval as a warning", () => {
    expect(
      caseStatus({
        ...baseCase,
        phase: "waiting_approval",
        approval_decision: "pending",
        terminal_status: null
      })
    ).toEqual({ label: "Approval required", tone: "warning" });
  });

  it("presents recovered and failed terminal outcomes distinctly", () => {
    expect(caseStatus(baseCase)).toEqual({ label: "Recovered", tone: "success" });
    expect(caseStatus({ ...baseCase, terminal_status: "failed" })).toEqual({
      label: "Failed",
      tone: "danger"
    });
  });
});
