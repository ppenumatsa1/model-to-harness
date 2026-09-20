import type { CheckoutCase } from "./types";

export type StatusTone = "neutral" | "active" | "warning" | "success" | "danger";

export interface StatusPresentation {
  label: string;
  tone: StatusTone;
}

export function caseStatus(caseRecord: CheckoutCase | null): StatusPresentation {
  if (!caseRecord) return { label: "Ready for a fixture", tone: "neutral" };
  if (caseRecord.phase === "waiting_approval") {
    return caseRecord.approval_decision === "pending"
      ? { label: "Approval required", tone: "warning" }
      : { label: "Ready to resume", tone: "active" };
  }
  switch (caseRecord.terminal_status) {
    case "recovered":
      return { label: "Recovered", tone: "success" };
    case "failed":
      return { label: "Failed", tone: "danger" };
    case "manual_review":
      return { label: "Manual review", tone: "warning" };
    case "closed_denied":
      return { label: "Closed after denial", tone: "neutral" };
    default:
      return { label: "In progress", tone: "active" };
  }
}
