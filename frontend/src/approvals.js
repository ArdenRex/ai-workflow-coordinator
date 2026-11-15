// Display helpers for the approval inbox and the activity list. Pure functions, no network.
export const APPROVAL_LABELS = { PENDING: "Waiting for you", APPROVED: "Approved", REJECTED: "Rejected", EXPIRED: "Expired", EXECUTED: "Done" };
export const APPROVAL_TONES = { PENDING: "warn", APPROVED: "ok", EXECUTED: "ok", REJECTED: "bad", EXPIRED: "off" };
export const RISK_LABELS = { low: "Low risk", medium: "Medium risk", high: "High risk" };
export const RISK_TONES = { low: "ok", medium: "warn", high: "bad" };

// "notes.task.update" -> "notes task update": a readable name for the action the AI wants to take.
export const toolLabel = (toolId) => String(toolId || "").replace(/[._]/g, " ").trim();

const EVENT_TEXT = {
  "approval.requested": "Approval requested", "approval.approved": "Approval granted", "approval.rejected": "Approval refused",
  "approval.expired": "Approval expired", "approval.executed": "Approved action completed", "approval.withdrawn": "Approval withdrawn",
  "approval.decision_refused": "Approval decision refused", "execution.created": "Action recorded", "execution.denied": "Action blocked",
  "execution.succeeded": "Action succeeded", "execution.failed": "Action failed", "execution.started": "Action started",
};
export function eventLabel(type) {
  if (EVENT_TEXT[type]) return EVENT_TEXT[type];
  const t = String(type || "").replace(/[._]/g, " ").trim();
  return t ? t.charAt(0).toUpperCase() + t.slice(1) : "Event";
}

// Summarises the inbox for the heading: how many wait for a decision and how many of those this person may decide.
export function inboxCounts(items) {
  const pending = items.filter((a) => a.status === "PENDING");
  return { pending: pending.length, decidable: pending.filter((a) => a.can_decide).length };
}

// Stable, readable rendering of the tool input the approver is asked to review (keys sorted, values as JSON).
export function inputLines(input) {
  if (!input || typeof input !== "object") return [];
  return Object.keys(input).sort().map((k) => {
    const v = input[k];
    return { key: k, value: typeof v === "string" ? v : JSON.stringify(v) };
  });
}

export const detailText = (d) => Object.entries(d || {}).filter(([, v]) => v !== null && v !== undefined && v !== "")
  .map(([k, v]) => `${k.replace(/_/g, " ")}: ${v}`).join(" · ");
