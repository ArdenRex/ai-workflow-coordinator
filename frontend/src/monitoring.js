// Display helpers for the monitoring page. Pure functions; the API returns counts and fixed codes only.
export const WINDOWS = [{ seconds: 3600, label: "Last hour" }, { seconds: 86400, label: "Last 24 hours" }, { seconds: 604800, label: "Last 7 days" }];
export const SEVERITY_TONES = { critical: "bad", warning: "warn" };
export const CONNECTION_STATES = { ok: { text: "Working", tone: "ok" }, failing: { text: "Failing", tone: "bad" }, stale: { text: "Not tested lately", tone: "warn" }, untested: { text: "Not tested", tone: "off" } };

export const connectionState = (s) => CONNECTION_STATES[s] || { text: s || "Unknown", tone: "off" };
export const pct = (x) => (x === null || x === undefined ? "—" : `${Math.round(x * 1000) / 10}%`);
export function duration(ms) {
  if (ms === null || ms === undefined) return "—";
  if (ms < 1000) return `${ms} ms`;
  return ms < 60000 ? `${Math.round(ms / 100) / 10} s` : `${Math.round(ms / 6000) / 10} min`;
}
export function age(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 90) return `${seconds} s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)} min`;
  return seconds < 129600 ? `${Math.round(seconds / 3600)} h` : `${Math.round(seconds / 86400)} days`;
}
const n = (o, k) => (o && o[k]) || 0;

// The four numbers from the blueprint's activity view: completed, pending approval, in progress, failed.
export function headlineCounts(overview) {
  const by = (overview && overview.summary && overview.summary.executions.by_status) || {};
  const runs = (overview && overview.health && overview.health.agent_runs.by_status) || {};
  return {
    completed: n(by, "succeeded"),
    pending: (overview && overview.summary && overview.summary.approvals.pending) || 0,
    inProgress: n(runs, "running") + n(runs, "queued") + n(runs, "waiting_approval"),
    failed: n(by, "failed"),
  };
}

// "needs attention" reasons in plain words, in the order a person should look at them.
export function attentionList(overview) {
  if (!overview) return [];
  const out = [], h = overview.health, s = overview.summary;
  const failing = n(h.connections.by_state, "failing");
  if (failing) out.push(`${failing} connection${failing > 1 ? "s" : ""} failing`);
  if (n(s.executions.by_status, "failed")) out.push(`${s.executions.by_status.failed} failed action${s.executions.by_status.failed > 1 ? "s" : ""}`);
  if (s.approvals.pending) out.push(`${s.approvals.pending} approval${s.approvals.pending > 1 ? "s" : ""} waiting`);
  if (h.agent_runs.overdue_active) out.push(`${h.agent_runs.overdue_active} overdue agent run${h.agent_runs.overdue_active > 1 ? "s" : ""}`);
  if (h.workflow_runs.overdue_steps) out.push(`${h.workflow_runs.overdue_steps} overdue workflow step${h.workflow_runs.overdue_steps > 1 ? "s" : ""}`);
  if (h.schedules.overdue) out.push(`${h.schedules.overdue} overdue schedule${h.schedules.overdue > 1 ? "s" : ""}`);
  if (h.events.stuck_undispatched) out.push(`${h.events.stuck_undispatched} event${h.events.stuck_undispatched > 1 ? "s" : ""} not dispatched`);
  return out;
}
