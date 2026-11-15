// Display helpers for plans. The API never returns goal or instruction text for stored plans, only counts and states.
export const PLAN_LABELS = { pending: "Queued", running: "Running", waiting_approval: "Waiting for approval", succeeded: "Done", failed: "Failed", cancelled: "Cancelled" };
export const STEP_LABELS = { pending: "Queued", running: "Running", waiting_approval: "Waiting for approval", succeeded: "Done", failed: "Failed", skipped: "Skipped", cancelled: "Cancelled" };
export const TONES = { succeeded: "ok", running: "warn", pending: "warn", waiting_approval: "warn", failed: "bad", cancelled: "off", skipped: "off" };

export const headlineOf = (plan) => (plan.summary && plan.summary.headline) || plan.status;
export const isActive = (plan) => ["pending", "running"].includes(plan.status);
export const isFinished = (plan) => ["succeeded", "failed", "cancelled"].includes(plan.status);

// Unique key so that a double click or a retry of the same goal does not create two plans.
export const newKey = () => (window.crypto && window.crypto.randomUUID ? window.crypto.randomUUID() : `k-${Date.now()}-${Math.random().toString(36).slice(2)}`);

export const DECOMPOSITION_TEXT = {
  needs_information: "The AI needs a bit more information before it can plan this.",
  no_action: "The AI did not find anything to do for this goal.",
  rejected: "The AI could not turn this goal into a safe plan.",
};

export function hintForError(err) {
  return err && err.status === 502 ? "Connect an AI model on the Connections page first." : "";
}

export const stepOrder = (steps) => [...steps].sort((a, b) => a.key.localeCompare(b.key, undefined, { numeric: true }));
