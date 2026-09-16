import { describe, expect, it } from "vitest";
import { businessAudit } from "./businessAudit";
import { businessEvent } from "./test/workspaceFixtures";

describe("deterministic business audit projection", () => {
  it("shows only chronological approved-case milestones with independently attributed decisions and resume", () => {
    const events = [
      businessEvent("run.started", 1),
      businessEvent("node.started", 2),
      businessEvent("decision.summary", 3, { decision: "confirmed", matching_charge_ids: ["charge-a", "charge-b"], matching_charge_count: 2, amount: 40, currency: "USD" }),
      businessEvent("parallel.branch.completed", 4, { branch: "billing_validation", ok: true, checked_charge_ids: ["charge-a", "charge-b"] }),
      businessEvent("parallel.branch.completed", 5, { branch: "policy_validation", ok: true, policy_code: "duplicate-policy", decision: "eligible" }),
      businessEvent("approval.requested", 6),
      businessEvent("approval.recorded", 7, { decision: "approve", reason: "Matched both charges" }),
      businessEvent("workflow.resumed", 8, { actor_id: "different-resumer" }),
      businessEvent("workflow.continued", 9),
      businessEvent("approval.resolved", 10, { decision: "approve" }),
      businessEvent("tool.call.succeeded", 11, { refund_id: "refund-1" }, "submit_refund"),
      businessEvent("refund.verification", 12, { verified: true, matching_refund_count: 1 }),
      businessEvent("notification.sent", 13),
      businessEvent("run.completed", 14, { terminal_status: "completed_refunded", refund_status: "verified", notification_status: "sent", failure_code: null }),
      businessEvent("maf.native.completed", 15)
    ];
    const { entries, incompatible } = businessAudit([...events].reverse());
    expect(incompatible).toBe(false);
    expect(entries.map((entry) => entry.title)).toEqual([
      "Case opened", "Duplicate charge detected", "Billing check passed", "Refund eligible under policy",
      "Review requested", "Refund approved", "Resume requested", "Processing continued", "Refund recorded",
      "Refund verified", "Customer notification simulated", "Case closed — refunded"
    ]);
    expect(entries[0].actor).toBe("Operator: operator-test (operator-provided; not authenticated)");
    expect(entries[5].actor).toBe("Reviewer: reviewer-test (operator-provided; not authenticated)");
    expect(entries[6].actor).toContain("different-resumer");
    expect(entries[7].actor).toBe("System");
    expect(entries[1].evidence).toContainEqual({ label: "Matching charges", value: "charge-a, charge-b" });
    expect(entries[3].evidence).toContainEqual({ label: "Policy reference", value: "duplicate-policy" });
    expect(entries[5].evidence).toEqual([{ label: "Reviewer reason", value: "Matched both charges" }]);
  });

  it("records a denial once without turning approval application into another human decision", () => {
    const entries = businessAudit([
      businessEvent("approval.recorded", 2, { decision: "deny", reason: "Evidence insufficient" }),
      businessEvent("approval.resolved", 3, { decision: "deny" }),
      businessEvent("run.completed", 4, { terminal_status: "closed_denied", refund_status: "denied", notification_status: "not_sent" })
    ]).entries;
    expect(entries.map((entry) => entry.title)).toEqual(["Refund denied", "Case closed — refund denied"]);
    expect(entries[1].description).toContain("Refund denied.");
  });

  it.each([
    ["not_found", "No duplicate charge found"],
    ["unknown", "Duplicate assessment recorded"]
  ])("does not invent a positive duplicate decision for %s", (decision, title) => {
    const entries = businessAudit([
      businessEvent("decision.summary", 1, { decision, matching_charge_count: 0 }),
      businessEvent("run.completed", 2, { terminal_status: "completed_no_refund", refund_status: "not_required", notification_status: "not_sent" })
    ]).entries;
    expect(entries[0].title).toBe(title);
    expect(entries[1].title).toBe("Case closed — no refund");
    expect(entries).toHaveLength(2);
  });

  it("shows policy rejection separately and hides its duplicate technical failure", () => {
    const entries = businessAudit([
      businessEvent("tool.call.failed", 1, { ok: false }, "policy_validation"),
      businessEvent("parallel.branch.completed", 2, { branch: "policy_validation", decision: "ineligible", ok: false, policy_code: "outside-window" }),
      businessEvent("run.completed", 3, { terminal_status: "completed_no_refund", refund_status: "not_required", notification_status: "not_sent", failure_code: "policy_ineligible" })
    ]).entries;
    expect(entries.map((entry) => entry.title)).toEqual(["Refund not eligible under policy", "Case closed — no refund"]);
    expect(entries[1].description).toContain("did not meet policy requirements");
  });

  it("distinguishes uncertain retries and recovered refund references from explicit verification", () => {
    const failed = { ...businessEvent("tool.call.failed", 1, { uncertain: true }, "submit_refund"), retry_attempt: 1 };
    const retry = { ...businessEvent("tool.call.retried", 2, { uncertain: true }, "submit_refund"), retry_attempt: 1 };
    const recovered = { ...businessEvent("tool.call.succeeded", 3, { recovered_existing: true, refund_id: "refund-existing" }, "submit_refund"), retry_attempt: 2 };
    const partial = businessAudit([failed, retry, recovered]).entries;
    expect(partial.map((entry) => entry.title)).toEqual(["Refund submission retried", "Existing refund reused"]);
    expect(partial[0].description).toContain("may exist; do not assume success");
    expect(partial[1].description).toContain("Verification is a separate check");
    expect(partial[1].evidence).toContainEqual({ label: "Attempt", value: "2" });
    const complete = businessAudit([failed, retry, recovered, businessEvent("refund.verification", 4, { verified: true, matching_refund_count: 1 })]).entries;
    expect(complete.at(-1)?.title).toBe("Refund verified");
    expect(complete.at(-1)?.evidence).toContainEqual({ label: "Verification passed", value: "Yes" });
  });

  it("shows a failed verification and manual-review closure without claiming a refund succeeded", () => {
    const entries = businessAudit([
      businessEvent("refund.verification", 1, { verified: false, matching_refund_count: 2 }),
      businessEvent("run.failed", 2, { terminal_status: "manual_review", refund_status: "manual_review", notification_status: "not_sent", failure_code: "refund_verification_mismatch" })
    ]).entries;
    expect(entries.map((entry) => entry.title)).toEqual(["Refund verification failed", "Manual review required"]);
    expect(entries[0].evidence).toContainEqual({ label: "Verification passed", value: "No" });
    expect(entries[1].description).toContain("did not match");
    expect(businessAudit([businessEvent("refund.verification", 3, { verified: "true" })]).entries[0].title).toBe("Refund verification inconclusive");
  });

  it("does not fill future milestones or fabricate a closure from an unknown terminal payload", () => {
    const opened = businessEvent("run.started", 1);
    expect(businessAudit([opened, opened, businessEvent("checkpoint.created", 3), businessEvent("model.call.completed", 4)]).entries).toHaveLength(1);
    const closure = businessAudit([businessEvent("run.completed", 5)]).entries[0];
    expect(closure.title).toBe("Resolution pending");
    expect(closure.description).toContain("Refund result not recorded");
  });

  it.each([
    { audit_version: 1 }, { audit_version: null }, { actor_id: "" },
    { actor_type: "unknown" }, { actor_source: "authenticated" },
    { actor_type: "system", actor_source: "system", actor_id: "maf-workflow" }
  ])("rejects incompatible human attribution %j without inventing System", (payload) => {
    const projection = businessAudit([businessEvent("run.started", 1, payload)]);
    expect(projection).toEqual({ entries: [], incompatible: true });
  });

  it("rejects an unknown system actor while retaining legitimate actions", () => {
    const projection = businessAudit([
      businessEvent("run.started", 1),
      businessEvent("workflow.continued", 2, { actor_id: "unknown-system" })
    ]);
    expect(projection.incompatible).toBe(true);
    expect(projection.entries).toHaveLength(1);
    expect(projection.entries[0].actor).toContain("Operator:");
  });
});
