import { describe, expect, it } from "vitest";
import { businessAudit } from "../src/businessAudit";
import { businessEvent } from "./workspaceFixtures";

describe("LG-native business audit", () => {
  it("orders and deduplicates approved milestones without duplicate application or speculative steps", () => {
    const events = [
      businessEvent("run_started", 1),
      businessEvent("decision_summary", 3, { decision: "confirmed", matching_charge_ids: ["charge-safe"] }),
      businessEvent("parallel_branch_completed", 4, { branch: "billing", ok: true }),
      businessEvent("parallel_branch_completed", 5, { branch: "policy", eligible: true }),
      businessEvent("human_approval_requested", 6),
      businessEvent("approval_command_recorded", 8, { decision: "approve", reason: "checked" }),
      businessEvent("resume_command_recorded", 10),
      businessEvent("run_resumed", 11),
      businessEvent("human_approval_resolved", 12, { decision: "approve", reviewer_id: "reviewer-test" }),
      businessEvent("tool_call_succeeded", 15, { refund_id: "refund-safe" }, "submit_refund"),
      businessEvent("refund_verification", 16, { verified: true, verified_count: 1 }),
      businessEvent("tool_call_succeeded", 17, { simulated: true }, "notify_customer"),
      businessEvent("run_completed", 18, { terminal_status: "completed", refund_status: "verified", notification_status: "sent" })
    ];
    const result = businessAudit([...events, events[0]].reverse());
    expect(result.incompatible).toBe(false);
    expect(result.entries.map((entry) => entry.title)).toEqual([
      "Case opened", "Duplicate charge detected", "Billing check passed", "Refund eligible under policy",
      "Review requested", "Refund approved", "Resume requested", "Processing continued",
      "Refund recorded", "Refund verified", "Customer notification simulated", "Case closed — refunded"
    ]);
    expect(result.entries[5].actor).toContain("Reviewer: reviewer-test");
    expect(result.entries[6].actor).toContain("Operator: operator-test");
    expect(result.entries[7].actor).toBe("System");
    expect(result.entries[8].description).toContain("Verification is a separate check");
    expect(result.entries.at(-1)?.description).toContain("delivery is not confirmed");
  });
  it.each(["not_found", "no_duplicate", "not_duplicate", "no"])("renders no-duplicate alias %s without inventing closure", (decision) => {
    const result = businessAudit([businessEvent("decision_summary", 1, { decision })]);
    expect(result.entries.map((entry) => entry.title)).toEqual(["No duplicate charge found"]);
  });
  it("keeps denial and policy rejection distinct from successful refunds", () => {
    expect(businessAudit([
      businessEvent("approval_command_recorded", 1, { decision: "deny" }),
      businessEvent("human_approval_resolved", 2, { decision: "deny" }),
      businessEvent("run_completed", 3, { terminal_status: "completed", refund_status: "denied", notification_status: "not_sent" })
    ]).entries.map((entry) => entry.title)).toEqual(["Refund denied", "Case closed — refund denied"]);
    const policy = businessAudit([
      businessEvent("parallel_branch_completed", 1, { branch: "policy", eligible: false }),
      businessEvent("run_completed", 2, { terminal_status: "completed", refund_status: "not_required", notification_status: "not_sent" })
    ]);
    expect(policy.entries[0].title).toBe("Refund not eligible under policy");
    expect(policy.entries[1].title).toBe("Case closed — no refund");
  });
  it("distinguishes transient retry, uncertain refund recovery, submitted and verified", () => {
    const events = [
      businessEvent("tool_call_failed", 1, { attempt: 1 }, "load_account"),
      businessEvent("tool_call_retried", 2, { attempt: 1 }, "load_account"),
      businessEvent("tool_call_retried", 3, { uncertain: true, attempt: 1 }, "submit_refund"),
      businessEvent("refund_idempotency_lookup", 4),
      businessEvent("refund_idempotency_lookup", 5, { recovered_existing: true, refund_id: "refund" }),
      businessEvent("refund_verification", 6, { verified_count: 1 })
    ];
    const entries = businessAudit(events).entries;
    expect(entries.map((entry) => entry.title)).toEqual([
      "Billing information retrieval retried", "Refund submission retried", "Existing refund reused", "Refund verification inconclusive"
    ]);
    expect(entries[1].description).toContain("A refund may exist");
    expect(entries[2].description).toContain("Verification is a separate check");
    expect(businessAudit([...events, businessEvent("refund_verification", 7, { verified: true })]).entries.at(-1)?.title).toBe("Refund verified");
  });
  it("shows verification mismatch/manual review as immutable historical failure, never success", () => {
    const entries = businessAudit([
      businessEvent("refund_verification", 1, { verified: false, verified_count: 1 }),
      businessEvent("run_completed", 2, { terminal_status: "manual_review", refund_status: "mismatch", notification_status: "not_sent" })
    ]).entries;
    expect(entries[0].title).toBe("Refund verification failed");
    expect(entries[1].title).toBe("Manual review required");
    expect(entries[1].description).toContain("did not match");
    expect(businessAudit([businessEvent("refund_verification", 1, { verified: "true" })]).entries[0].title).toBe("Refund verification inconclusive");
  });
  it.each([
    { audit_version: undefined },
    { actor_type: "human", actor_id: "guessed", actor_source: "operator_supplied" },
    { actor_id: "maf-workflow" },
    { actor_source: "unknown" }
  ])("does not reinterpret unattributed or legacy resume as continued: %j", (data) => {
    const entry = businessAudit([businessEvent("run_resumed", 1, data)]).entries[0];
    expect(entry.title).toBe("Historical resume record");
    expect(entry.actor).toBe("Actor unknown / not recorded");
    expect(entry.description).toContain("not established");
  });
  it("retains legacy milestones with explicit unknown actor and missing facts rather than inventing evidence", () => {
    const result = businessAudit([
      businessEvent("run_started", 1, { audit_version: undefined }),
      businessEvent("run_completed", 2, { audit_version: undefined }),
      businessEvent("checkpoint_created", 3),
      businessEvent("model_call_completed", 4)
    ]);
    expect(result.incompatible).toBe(true);
    expect(result.entries).toHaveLength(2);
    expect(result.entries[0].actor).toBe("Actor unknown / not recorded");
    expect(result.entries[1].title).toBe("Resolution pending");
    expect(result.entries[1].description).toContain("Refund result not recorded.");
  });
  it.each(["load_account", "billing_validation", "policy_validation", "verify_refund", "notify_customer"])("renders bounded failure path %s", (node) => {
    const entry = businessAudit([businessEvent("tool_call_failed", 1, { failure_code: "private-unknown" }, node)]).entries[0];
    expect(entry).toBeDefined();
    expect(JSON.stringify(entry)).not.toContain("private-unknown");
  });
});
