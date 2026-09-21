import type { DurableEvent } from "./types";

export interface BusinessEntry {
  id: string;
  recordedAt: string;
  title: string;
  description: string;
  actor: string;
  evidence: { label: string; value: string }[];
}

const HUMAN_EVENTS = new Set(["run.started", "approval.recorded", "workflow.resumed"]);

function actorFor(event: DurableEvent): string | undefined {
  const { audit_version, actor_type, actor_id, actor_source } = event.payload;
  if (audit_version !== 2) return undefined;
  if (HUMAN_EVENTS.has(event.event_type)) {
    if (actor_type !== "human" || actor_source !== "operator_supplied" || typeof actor_id !== "string" || !actor_id.trim()) return undefined;
    return `${event.event_type === "approval.recorded" ? "Reviewer" : "Operator"}: ${actor_id} (operator-provided; not authenticated)`;
  }
  if (actor_type === "system" && actor_id === "maf-workflow" && actor_source === "system") return "System";
  return undefined;
}

const TERMINAL_LABELS: Record<string, string> = {
  completed_refunded: "Case closed — refunded",
  completed_no_refund: "Case closed — no refund",
  closed_denied: "Case closed — refund denied",
  manual_review: "Manual review required",
  failed: "Case processing failed"
};

export function resolutionLabel(status: unknown): string {
  return typeof status === "string" && TERMINAL_LABELS[status] ? TERMINAL_LABELS[status] : "Resolution pending";
}

const REFUND_LABELS: Record<string, string> = {
  not_started: "Refund not started.", not_required: "No refund required.",
  submitted: "Refund recorded; verification not yet confirmed.", verified: "Refund verified.",
  denied: "Refund denied.", not_approved: "Refund not approved.", manual_review: "Refund requires manual review."
};
const FAILURE_LABELS: Record<string, string> = {
  refund_outcome_uncertain: "The refund outcome remains uncertain; reconciliation is required.",
  refund_verification_mismatch: "Refund evidence did not match the expected result.",
  billing_validation_failed: "Billing evidence could not be validated.",
  policy_ineligible: "The refund did not meet policy requirements.",
  transient_billing_read: "Billing information could not be retrieved after retries.",
  approval_denied: "The reviewer denied the refund."
};

function closureDescription(payload: Record<string, unknown>): string {
  const refund = typeof payload.refund_status === "string" ? REFUND_LABELS[payload.refund_status] : undefined;
  const failure = typeof payload.failure_code === "string" ? FAILURE_LABELS[payload.failure_code] : undefined;
  const notification = payload.notification_status === "sent"
    ? "Notification simulated; delivery is not confirmed."
    : payload.notification_status === "not_sent" || payload.notification_status === "not_started"
      ? "No customer notification recorded." : "Notification result not recorded.";
  return [refund ?? "Refund result not recorded.", failure, notification].filter(Boolean).join(" ");
}

type EvidenceField = readonly [string, string];
const CHARGES: EvidenceField[] = [
  ["matching_charge_ids", "Matching charges"], ["matching_charge_count", "Matching charge count"],
  ["amount", "Amount"], ["currency", "Currency"]
];

function evidenceFor(event: DurableEvent, fields: EvidenceField[]): BusinessEntry["evidence"] {
  return fields.flatMap(([key, label]) => {
    const value = key === "retry_attempt" ? event.retry_attempt : event.payload[key];
    if (typeof value === "string" && value.trim()) return [{ label, value }];
    if (typeof value === "number" && Number.isFinite(value)) return [{ label, value: String(value) }];
    if (typeof value === "boolean") return [{ label, value: value ? "Yes" : "No" }];
    if (Array.isArray(value) && value.length && value.every((item) => typeof item === "string")) return [{ label, value: value.join(", ") }];
    return [];
  });
}

function milestone(event: DurableEvent, actor: string, events: DurableEvent[]): BusinessEntry | undefined {
  const payload = event.payload;
  let title: string;
  let description: string;
  let fields: EvidenceField[] = [];
  switch (event.event_type) {
    case "run.started":
      title = "Case opened";
      description = "The operator submitted this case for double-charge review.";
      break;
    case "decision.summary":
      title = payload.decision === "confirmed" ? "Duplicate charge detected"
        : payload.decision === "not_found"
          ? "No duplicate charge found" : "Duplicate assessment recorded";
      description = payload.decision === "confirmed" ? "Matching charges were identified for validation."
        : title === "No duplicate charge found" ? "The assessment did not identify a duplicate charge."
          : "The duplicate-charge decision requires review.";
      fields = CHARGES;
      break;
    case "parallel.branch.completed":
      if (payload.branch === "billing_validation") {
        title = payload.ok === true ? "Billing check passed" : "Billing check requires review";
        description = payload.ok === true ? "The matching charge evidence passed the billing check." : "Billing evidence was not confirmed as valid.";
        fields = [["checked_charge_ids", "Checked charges"]];
      } else if (payload.branch === "policy_validation") {
        title = payload.decision === "ineligible" ? "Refund not eligible under policy"
          : payload.decision === "eligible" || payload.ok === true ? "Refund eligible under policy" : "Policy check requires review";
        description = "The refund policy assessment was recorded separately from the billing check.";
        fields = [["policy_code", "Policy reference"], ["decision", "Policy result"]];
      } else return undefined;
      break;
    case "approval.requested":
      title = "Review requested";
      description = "Processing is paused for an explicit reviewer decision.";
      fields = [["amount", "Amount"], ["currency", "Currency"]];
      break;
    case "approval.recorded":
      title = payload.decision === "approve" ? "Refund approved" : payload.decision === "deny" ? "Refund denied" : "Reviewer decision recorded";
      description = "The review decision was recorded. It does not itself resume processing.";
      fields = [["reason", "Reviewer reason"]];
      break;
    case "workflow.resumed":
      title = "Resume requested";
      description = "The operator requested resume. This request alone does not confirm that processing continued.";
      break;
    case "workflow.continued":
      title = "Processing continued";
      description = "The workflow entered approval handling and persisted its running state.";
      break;
    case "tool.call.succeeded":
      if (event.node !== "submit_refund") return undefined;
      title = payload.recovered_existing === true ? "Existing refund reused" : "Refund recorded";
      description = "A refund reference was returned. Verification is a separate check.";
      fields = [["refund_id", "Refund reference"], ["retry_attempt", "Attempt"]];
      break;
    case "refund.verification":
      title = payload.verified === true ? "Refund verified" : payload.verified === false ? "Refund verification failed" : "Refund verification inconclusive";
      description = payload.verified === true ? "The refund check confirmed the expected result."
        : payload.verified === false ? "The refund check did not confirm the expected result; review is required."
          : "No explicit verification result was recorded.";
      fields = [["verified", "Verification passed"], ["matching_refund_count", "Matching refund count"], ["refund_id", "Refund reference"]];
      break;
    case "notification.sent":
      title = "Customer notification simulated";
      description = "A simulated notification was recorded. This is not confirmation of delivery to the customer.";
      break;
    case "run.completed":
    case "run.failed":
      title = resolutionLabel(payload.terminal_status);
      description = closureDescription(payload);
      break;
    case "tool.call.failed":
    case "tool.call.retried": {
      const retry = event.event_type === "tool.call.retried";
      if (!retry && events.some((other) => actorFor(other) && (
        (other.event_type === "tool.call.retried" && other.node === event.node && other.retry_attempt === event.retry_attempt)
        || (other.event_type === "parallel.branch.completed" && other.payload.branch === event.node)
      ))) return undefined;
      if (event.node === "submit_refund") {
        title = retry ? "Refund submission retried" : "Refund submission needs review";
        description = payload.uncertain === true
          ? "The refund response was uncertain. A refund may exist; do not assume success or submit a new refund."
          : "Refund submission was not confirmed.";
      } else if (event.node === "load_account") {
        title = retry ? "Billing information retrieval retried" : "Billing information unavailable";
        description = "The case cannot be assessed until billing information is available.";
      } else if (event.node === "billing_validation" || event.node === "policy_validation") {
        title = retry ? "Case validation retried" : "Case validation needs review";
        description = "The validation step could not confirm the evidence.";
      } else if (event.node === "verify_refund") {
        title = retry ? "Refund verification retried" : "Refund verification unavailable";
        description = "The refund has not been confirmed by this check.";
      } else return undefined;
      fields = [["retry_attempt", "Attempt"]];
      break;
    }
    default:
      return undefined;
  }
  return { id: event.event_id, recordedAt: event.created_at, title, description, actor, evidence: evidenceFor(event, fields) };
}

export function businessAudit(events: DurableEvent[]): { entries: BusinessEntry[]; incompatible: boolean } {
  const seenIds = new Set<string>();
  const seenSequences = new Set<number>();
  const ordered = [...events].sort((left, right) => left.sequence - right.sequence).filter((event) => {
    if (seenIds.has(event.event_id) || seenSequences.has(event.sequence)) return false;
    seenIds.add(event.event_id);
    seenSequences.add(event.sequence);
    return true;
  });
  const entries: BusinessEntry[] = [];
  let incompatible = false;
  for (const event of ordered) {
    const actor = actorFor(event);
    if (!actor) { incompatible = true; continue; }
    const entry = milestone(event, actor, ordered);
    if (entry) entries.push(entry);
  }
  return { entries, incompatible };
}
