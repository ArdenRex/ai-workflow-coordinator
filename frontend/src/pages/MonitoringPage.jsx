import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useWorkspace } from "../auth/WorkspaceContext";
import { age, attentionList, connectionState, duration, headlineCounts, pct, SEVERITY_TONES, WINDOWS } from "../monitoring";

const REFRESH_MS = 30000;
const when = (s) => (s ? new Date(/Z|[+-]\d\d:?\d\d$/.test(s) ? s : `${s}Z`).toLocaleString() : "—");
const Tile = ({ label, value, tone }) => (<div className="card" style={{ flex: "1 1 140px", marginBottom: 0 }}>
  <div className="hint">{label}</div><div style={{ fontSize: 28, fontWeight: 700, color: tone === "bad" && value > 0 ? "#ffb3ba" : "var(--text)" }}>{value}</div></div>);

export default function MonitoringPage({ onNavigate }) {
  const { current, can } = useWorkspace();
  const allowed = can("audit:read");
  const [windowSeconds, setWindow] = useState(86400);
  const [ov, setOv] = useState(null); const [err, setErr] = useState(""); const [at, setAt] = useState(null);
  const load = useCallback(() => api.overview(current.id, windowSeconds).then((r) => { setOv(r); setErr(""); setAt(new Date()); }).catch((e) => setErr(e.message)), [current.id, windowSeconds]);
  useEffect(() => {
    if (!allowed) return undefined;
    setOv(null); load();
    const t = setInterval(load, REFRESH_MS);
    return () => clearInterval(t);
  }, [allowed, load]);

  if (!allowed) return (<><h1>Monitoring</h1><div className="card"><p className="hint">Monitoring is available to workspace admins and owners. Ask an admin if you need to see how the AI is doing.</p></div></>);
  const counts = headlineCounts(ov), attention = attentionList(ov);
  const h = ov && ov.health, s = ov && ov.summary, alerts = ov ? ov.alerts.alerts : [];
  return (
    <>
      <h1>Monitoring</h1>
      <p style={{ color: "var(--text-2)" }}>How the AI is doing in <strong>{current.name}</strong>. Refreshes every 30 seconds{at ? ` · updated ${at.toLocaleTimeString()}` : ""}.</p>
      <div className="tabs" role="tablist" aria-label="Time window">
        {WINDOWS.map((w) => <button key={w.seconds} role="tab" aria-selected={windowSeconds === w.seconds} onClick={() => setWindow(w.seconds)}>{w.label}</button>)}
      </div>
      {err && <div className="msg err" role="alert">{err}</div>}
      {!ov && !err && <p className="hint">Loading…</p>}
      {ov && (<>
        <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 16 }}>
          <Tile label="Completed" value={counts.completed} /><Tile label="Pending approval" value={counts.pending} />
          <Tile label="In progress" value={counts.inProgress} /><Tile label="Failed" value={counts.failed} tone="bad" />
        </div>
        <div className="card">
          <h2>Needs attention</h2>
          {alerts.length === 0 && attention.length === 0 ? <p className="hint">Nothing needs attention right now.</p> : (<>
            {alerts.map((a) => <div key={a.rule} style={{ marginTop: 8 }}><span className={`pill ${SEVERITY_TONES[a.severity] || "off"}`}>{a.severity}</span> {a.message}</div>)}
            {attention.length > 0 && <ul style={{ margin: "10px 0 0 18px", color: "var(--text-2)" }}>{attention.map((t) => <li key={t}>{t}</li>)}</ul>}
          </>)}
          {counts.pending > 0 && onNavigate && <div className="acts" style={{ marginTop: 10 }}><button className="btn-s" onClick={() => onNavigate("approvals")}>Open approvals</button></div>}
        </div>
        <div className="card">
          <h2>Connections</h2>
          {h.connections.connections.length === 0 ? <p className="hint">No active connections.</p> : (
            <table className="t"><thead><tr><th>System</th><th>Status</th><th>Last tested</th></tr></thead>
              <tbody>{h.connections.connections.map((c) => { const st = connectionState(c.state); return (
                <tr key={c.credential_id}><td>{c.name}<div className="hint">{c.provider}</div></td><td><span className={`pill ${st.tone}`}>{st.text}</span></td><td className="hint">{when(c.last_tested_at)}</td></tr>); })}</tbody></table>)}
        </div>
        <div className="card">
          <h2>Actions</h2>
          <p className="hint">{s.executions.total} in this period · failure rate {pct(s.executions.failure_rate)} · average {duration(s.executions.avg_duration_ms)} · slowest {duration(s.executions.max_duration_ms)}</p>
          <p className="hint">Approvals: {s.approvals.pending} waiting{s.approvals.oldest_pending_age_seconds !== null ? ` (oldest ${age(s.approvals.oldest_pending_age_seconds)})` : ""} · {s.approvals.decided_in_window} decided · average decision {age(s.approvals.avg_decision_seconds)} · {s.denials_in_window} blocked by policy</p>
          {s.recent_failures.length > 0 && (<table className="t" style={{ marginTop: 8 }}><thead><tr><th>Failed action</th><th>When</th></tr></thead>
            <tbody>{s.recent_failures.map((f) => <tr key={f.execution_id}><td>{f.tool_id}<div className="hint">{f.error || ""}</div></td><td className="hint">{when(f.finished_at)}</td></tr>)}</tbody></table>)}
        </div>
        <div className="card">
          <h2>Automation</h2>
          <p className="hint">Workflow runs: {Object.entries(h.workflow_runs.by_status).map(([k, v]) => `${v} ${k}`).join(", ") || "none"} · {h.workflow_runs.steps_waiting_retry} step{h.workflow_runs.steps_waiting_retry === 1 ? "" : "s"} waiting to retry</p>
          <p className="hint">Schedules: {h.schedules.enabled} on, {h.schedules.disabled} off{h.schedules.auto_disabled ? ` (${h.schedules.auto_disabled} switched off automatically)` : ""}, {h.schedules.overdue} overdue · Events: {h.events.received_in_window} received, {h.events.dispatched_in_window} dispatched</p>
          <p className="hint">Alerts are shown here only; they are not sent anywhere.</p>
        </div>
      </>)}
    </>
  );
}
