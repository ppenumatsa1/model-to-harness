import type { CheckoutCase, SafeAuditEvent } from "./types";

export type ProgressStep = "case_started" | "diagnostic" | "approval" | "remediation" | "verification" | "outcome";

const orderedSteps: readonly ProgressStep[] = [
  "case_started",
  "diagnostic",
  "approval",
  "remediation",
  "verification",
  "outcome"
];

const eventSteps: Record<string, ProgressStep> = {
  case_started: "case_started",
  diagnostic_completed: "diagnostic",
  approval_recorded: "approval",
  remediation_intent_recorded: "remediation",
  remediation_response_uncertain: "remediation",
  remediation_completed: "remediation",
  verification_completed: "verification",
  case_closed: "outcome"
};

export function completedProgress(events: SafeAuditEvent[]): ProgressStep[] {
  return orderedSteps.filter((step) =>
    events.some((event) => eventSteps[event.code] === step)
  );
}

export function progressLabel(caseRecord: CheckoutCase | null, events: SafeAuditEvent[]): string {
  if (!caseRecord) return "Choose a fixture to begin";
  if (caseRecord.phase === "waiting_approval" && caseRecord.approval_decision === "pending") {
    return "Waiting for a durable reviewer decision";
  }
  if (caseRecord.terminal_status) return `Outcome: ${humanize(caseRecord.terminal_status)}`;
  const complete = completedProgress(events);
  return complete.length ? `Completed: ${humanize(complete.at(-1) ?? "case_started")}` : "Starting";
}

export function needsApproval(caseRecord: CheckoutCase | null): boolean {
  return (
    caseRecord?.phase === "waiting_approval" &&
    caseRecord.approval_decision === "pending"
  );
}

export function canResume(caseRecord: CheckoutCase | null): boolean {
  return (
    caseRecord?.phase === "waiting_approval" &&
    (caseRecord.approval_decision === "approved" || caseRecord.approval_decision === "denied")
  );
}

export function toolLabel(eventCode: string): string {
  const labels: Record<string, string> = {
    diagnostic_completed: "Diagnostic reader",
    remediation_intent_recorded: "Remediation ledger",
    remediation_response_uncertain: "Remediation provider",
    remediation_completed: "Remediation provider",
    verification_completed: "Verification reader"
  };
  return labels[eventCode] ?? "Workflow audit";
}

export function humanize(value: string): string {
  return value.replaceAll("_", " ");
}
