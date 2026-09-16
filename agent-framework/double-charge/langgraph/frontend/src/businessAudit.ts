import type { NativeEvent } from "./types";

export interface BusinessEntry {
  id: string;
  recordedAt: string;
  title: string;
  description: string;
  actor: string;
  evidence: { label: string; value: string }[];
}

const HUMAN = new Set(["run_started", "approval_command_recorded", "resume_command_recorded"]);
const DUPLICATE = new Set(["confirmed", "duplicate", "yes"]);
const NOT_DUPLICATE = new Set(["not_found", "no_duplicate", "not_duplicate", "no"]);
const UNKNOWN_ACTOR = "Actor unknown / not recorded";

function actorFor(event: NativeEvent): string {
  const { audit_version, actor_type, actor_id, actor_source } = event.data;
  if (audit_version !== 2) return UNKNOWN_ACTOR;
  if (HUMAN.has(event.event_type)) {
    return actor_type === "human" && actor_source === "operator_supplied" &&
      typeof actor_id === "string" && actor_id.trim()
      ? `${event.event_type === "approval_command_recorded" ? "Reviewer" : "Operator"}: ${actor_id} (operator-provided; not authenticated)`
      : UNKNOWN_ACTOR;
  }
  return actor_type === "system" && actor_id === "langgraph-workflow" && actor_source === "system"
    ? "System" : UNKNOWN_ACTOR;
}

export function resolutionLabel(status: unknown): string {
  const labels: Record<string, string> = {
    completed_refunded: "Case closed — refunded", completed_no_refund: "Case closed — no refund",
    closed_denied: "Case closed — refund denied", completed: "Case completed",
    manual_review: "Manual review required", failed: "Case processing failed"
  };
  return typeof status === "string" && labels[status] ? labels[status] : "Resolution pending";
}

const REFUNDS: Record<string, string> = {
  not_requested: "Refund not requested.", not_required: "No refund required.",
  not_submitted: "Refund not submitted.", submitted: "Refund recorded; verification not yet confirmed.",
  uncertain: "Refund outcome uncertain; review persisted evidence before another command.",
  failed: "Refund submission failed.", verified: "Refund verified.",
  mismatch: "Refund evidence did not match the expected result.", denied: "Refund denied."
};
const FAILURES: Record<string, string> = {
  refund_outcome_uncertain: "The refund outcome remains uncertain.",
  refund_verification_mismatch: "Refund evidence did not match the expected result.",
  billing_validation_failed: "Billing evidence could not be validated.",
  policy_ineligible: "The refund did not meet policy requirements.",
  transient_billing_read: "Billing information could not be retrieved after retries.",
  approval_denied: "The reviewer denied the refund."
};

function evidence(data: Record<string, unknown>, fields: [string, string][]): BusinessEntry["evidence"] {
  return fields.flatMap(([key, label]) => {
    const value = data[key];
    if (typeof value === "string" && value.trim()) return [{ label, value }];
    if (typeof value === "number" && Number.isFinite(value)) return [{ label, value: String(value) }];
    if (typeof value === "boolean") return [{ label, value: value ? "Yes" : "No" }];
    if (Array.isArray(value) && value.length && value.every((item) => typeof item === "string")) {
      return [{ label, value: value.join(", ") }];
    }
    return [];
  });
}

function milestone(event: NativeEvent): BusinessEntry | undefined {
  const data = event.data;
  const actor = actorFor(event);
  const versioned = data.audit_version === 2;
  let title: string;
  let description: string;
  let fields: [string, string][] = [];
  switch (event.event_type) {
    case "run_started":
      title = "Case opened";
      description = "The case was submitted for double-charge review.";
      break;
    case "decision_summary":
      title = typeof data.decision === "string" && DUPLICATE.has(data.decision) ? "Duplicate charge detected"
        : typeof data.decision === "string" && NOT_DUPLICATE.has(data.decision) ? "No duplicate charge found"
          : "Duplicate assessment recorded";
      description = "The duplicate-charge assessment was recorded; validation and resolution are separate steps.";
      fields = [["matching_charge_ids", "Matching charges"]];
      break;
    case "parallel_branch_completed":
      if (data.branch !== "billing" && data.branch !== "policy") return undefined;
      title = data.branch === "billing"
        ? data.ok === true ? "Billing check passed" : data.ok === false ? "Billing check requires review" : "Billing check recorded"
        : data.eligible === true ? "Refund eligible under policy" : data.eligible === false ? "Refund not eligible under policy" : "Policy check recorded";
      description = "Billing and policy assessments are recorded independently.";
      fields = [["checked_charge_ids", "Checked charges"], ["policy_code", "Policy reference"]];
      break;
    case "human_approval_requested":
      title = "Review requested";
      description = "Processing is paused for an explicit reviewer decision.";
      break;
    case "approval_command_recorded":
      title = data.decision === "approve" ? "Refund approved" : data.decision === "deny" ? "Refund denied" : "Reviewer decision recorded";
      description = "The decision was recorded. It does not itself resume processing.";
      fields = [["reason", "Reviewer reason"]];
      break;
    case "resume_command_recorded":
      title = "Resume requested";
      description = "The operator requested resume. This request alone does not confirm execution continued.";
      break;
    case "run_resumed":
      title = versioned && actor === "System" ? "Processing continued" : "Historical resume record";
      description = versioned && actor === "System"
        ? "Native execution continued after validating the persisted review decision."
        : "Actual continuation is not established by this legacy or unattributed resume record.";
      break;
    case "refund_idempotency_lookup":
      if (data.recovered_existing !== true) return undefined;
      title = "Existing refund reused";
      description = "An existing refund reference was recovered. Verification is a separate check.";
      fields = [["refund_id", "Refund reference"]];
      break;
    case "tool_call_succeeded":
      if (event.node === "notify_customer") {
        title = "Customer notification simulated";
        description = "A teaching notification was recorded. This does not confirm delivery to the customer.";
      } else if (event.node === "submit_refund") {
        title = "Refund recorded";
        description = "A refund reference was returned. Verification is a separate check.";
        fields = [["refund_id", "Refund reference"], ["attempt", "Attempt"]];
      } else return undefined;
      break;
    case "refund_verification":
      title = data.verified === true ? "Refund verified" : data.verified === false ? "Refund verification failed" : "Refund verification inconclusive";
      description = data.verified === true ? "The refund check confirmed the expected durable result."
        : data.verified === false ? "The refund check did not confirm the expected result; review is required."
          : "An explicit verification result was not recorded. A count alone does not prove a matching refund.";
      fields = [["verified", "Verification passed"], ["verified_count", "Matching refund count"], ["refund_id", "Refund reference"]];
      break;
    case "run_completed":
    case "run_failed": {
      title = resolutionLabel(data.terminal_status);
      if (data.terminal_status === "completed") {
        title = data.refund_status === "verified" ? "Case closed — refunded"
          : data.refund_status === "denied" ? "Case closed — refund denied"
            : data.refund_status === "not_required" ? "Case closed — no refund" : "Case completed";
      }
      const refund = typeof data.refund_status === "string" ? REFUNDS[data.refund_status] : undefined;
      const failure = typeof data.failure_code === "string" ? FAILURES[data.failure_code] : undefined;
      const notification = data.notification_status === "sent"
        ? "Notification simulated; delivery is not confirmed."
        : data.notification_status === "not_sent" ? "No customer notification recorded."
          : data.notification_status === "failed" ? "Simulated notification failed." : "Notification result not recorded.";
      description = [refund ?? "Refund result not recorded.", failure, notification].filter(Boolean).join(" ");
      break;
    }
    case "tool_call_failed":
    case "tool_call_retried": {
      const retry = event.event_type === "tool_call_retried";
      if (event.node === "submit_refund") {
        title = retry ? "Refund submission retried" : "Refund submission needs review";
        description = data.uncertain === true
          ? "A refund may exist despite the uncertain response. Do not assume success or submit a new refund."
          : "Refund submission was not confirmed.";
      } else if (event.node === "load_account") {
        title = retry ? "Billing information retrieval retried" : "Billing information unavailable";
        description = "Billing information is needed to assess the case.";
      } else if (event.node === "billing_validation" || event.node === "policy_validation") {
        title = retry ? "Case validation retried" : "Case validation needs review";
        description = "The validation step could not confirm the evidence.";
      } else if (event.node === "verify_refund") {
        title = retry ? "Refund verification retried" : "Refund verification unavailable";
        description = "The refund has not been confirmed by this check.";
      } else if (event.node === "notify_customer") {
        title = "Simulated notification failed";
        description = "No successful customer delivery is established.";
      } else return undefined;
      fields = [["attempt", "Attempt"]];
      break;
    }
    default: return undefined;
  }
  return { id: event.event_id, recordedAt: event.timestamp, title, description, actor, evidence: evidence(data, fields) };
}

export function businessAudit(events: NativeEvent[]) {
  const ids = new Set<string>();
  const sequences = new Set<number>();
  const ordered = [...events].sort((a, b) => a.sequence - b.sequence).filter((event) => {
    if (ids.has(event.event_id) || sequences.has(event.sequence)) return false;
    ids.add(event.event_id);
    sequences.add(event.sequence);
    return true;
  });
  const entries = ordered.flatMap((event) => {
    if (event.event_type === "tool_call_failed" && ordered.some((other) =>
      (other.event_type === "tool_call_retried" && other.node === event.node && other.data.attempt === event.data.attempt) ||
      (other.event_type === "parallel_branch_completed" &&
        ((event.node === "billing_validation" && other.data.branch === "billing") ||
         (event.node === "policy_validation" && other.data.branch === "policy")))
    )) return [];
    const entry = milestone(event);
    return entry ? [entry] : [];
  });
  return { entries, incompatible: ordered.some((event) => actorFor(event) === UNKNOWN_ACTOR) };
}
