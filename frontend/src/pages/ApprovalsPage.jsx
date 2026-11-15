import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useWorkspace } from "../auth/WorkspaceContext";
import { APPROVAL_LABELS, APPROVAL_TONES, detailText, eventLabel, inboxCounts, inputLines, RISK_LABELS, RISK_TONES, toolLabel } from "../approvals";

const when = (s) => (s ? new Date(/Z|[+-]\d\d:?\d\d$/.test(s) ? s : `${s}Z`).toLocaleString() : "—");

function Item({ a, wsId, onChange }) {
  const [open, setOpen] = useState(false); const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false); const [err, setErr] = useState("");
  const lines = inputLines(a.input);
  async function decide(approve) {
    if (approve && !window.confirm(`Approve "${toolLabel(a.tool_id)}"? The AI may then carry it out.`)) return;
    setBusy(true); setErr("");
    try { await (approve ? api.approve : api.reject)(wsId, a.id, reason.trim() || null); onChange(); } catch (x) { setErr(x.message); onChange(); } finally { setBusy(false); }
  }
  return (
    <div className="card" data-testid="approval">
      <div className="acts" style={{ justifyContent: "space-between" }}>
        <h2 style={{ margin: 0 }}>{toolLabel(a.tool_id)}</h2>
        <span><span className={`pill ${RISK_TONES[a.risk] || "off"}`}>{RISK_LABELS[a.risk] || a.risk}</span> <span className={`pill ${APPROVAL_TONES[a.status] || "off"}`}>{APPROVAL_LABELS[a.status] || a.status}</span></span>
      </div>
      <p className="hint">{a.agent ? `Requested by the ${a.agent.replace(/_/g, " ")}` : "Requested by a person"} · {when(a.created_at)}
        {a.status === "PENDING" && a.expires_at ? ` · expires ${when(a.expires_at)}` : ""}
        {a.decided_at ? ` · decided ${when(a.decided_at)}` : ""}{a.reason ? ` · note: ${a.reason}` : ""}</p>
      {a.input && <button className="btn-s" onClick={() => setOpen(!open)} aria-expanded={open}>{open ? "Hide details" : "Review details"}</button>}
      {open && (<table className="t" style={{ marginTop: 8 }}><tbody>
        {lines.length === 0 ? <tr><td className="hint">No details were attached.</td></tr> : lines.map((l) => <tr key={l.key}><th>{l.key}</th><td style={{ wordBreak: "break-word" }}>{l.value}</td></tr>)}
      </tbody></table>)}
      {a.status === "PENDING" && !a.can_decide && <p className="hint" style={{ marginTop: 8 }}>This is waiting for a workspace admin. You cannot approve a request you made yourself.</p>}
      {a.can_decide && (<div style={{ marginTop: 10 }}>
        <label className="f" htmlFor={`n-${a.id}`}>Note (optional)</label>
        <input id={`n-${a.id}`} className="auth-input" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
        <div className="acts" style={{ marginTop: 8 }}>
          <button className="btn-s" disabled={busy} onClick={() => decide(true)}>Approve</button>
          <button className="btn-s danger" disabled={busy} onClick={() => decide(false)}>Reject</button>
        </div>
      </div>)}
      {err && <div className="msg err" role="alert">{err}</div>}
    </div>
  );
}

function Inbox({ wsId }) {
  const [items, setItems] = useState(null); const [err, setErr] = useState("");
  const load = useCallback(() => api.approvals(wsId).then((r) => { setItems(r); setErr(""); }).catch((e) => setErr(e.message)), [wsId]);
  useEffect(() => { setItems(null); load(); }, [load]);
  if (err && !items) return <div className="msg err" role="alert">{err}</div>;
  if (!items) return <p className="hint">Loading…</p>;
  const { pending, decidable } = inboxCounts(items);
  const waiting = items.filter((a) => a.status === "PENDING"), past = items.filter((a) => a.status !== "PENDING");
  return (
    <>
      <p style={{ color: "var(--text-2)" }}>{pending === 0 ? "Nothing is waiting for approval." : `${pending} waiting${decidable < pending ? `, ${decidable} for you to decide` : ""}.`}</p>
      {err && <div className="msg err" role="alert">{err}</div>}
      {waiting.map((a) => <Item key={a.id} a={a} wsId={wsId} onChange={load} />)}
      {past.length > 0 && <h2 style={{ marginTop: 24 }}>Earlier</h2>}
      {past.map((a) => <Item key={a.id} a={a} wsId={wsId} onChange={load} />)}
    </>
  );
}

function Activity({ wsId }) {
  const [items, setItems] = useState(null); const [err, setErr] = useState("");
  useEffect(() => { setItems(null); api.activity_workspace(wsId).then(setItems).catch((e) => setErr(e.message)); }, [wsId]);
  if (err) return <div className="msg err" role="alert">{err}</div>;
  if (!items) return <p className="hint">Loading…</p>;
  return (
    <div className="card">
      <h2>What happened</h2>
      {items.length === 0 ? <p className="hint">No activity yet.</p> : (
        <table className="t"><thead><tr><th>When</th><th>What</th><th>Who</th></tr></thead>
          <tbody>{items.map((e) => (<tr key={e.id}><td>{when(e.created_at)}</td>
            <td>{eventLabel(e.event_type)}<div className="hint">{detailText(e.details)}</div></td>
            <td className="hint">{e.actor === "system" ? "system" : e.actor ? `user ${String(e.actor).slice(0, 8)}` : "—"}</td></tr>))}</tbody></table>)}
    </div>
  );
}

export default function ApprovalsPage() {
  const { current, can } = useWorkspace();
  const canAudit = can("audit:read");
  const [tab, setTab] = useState("inbox");
  return (
    <>
      <h1>Approvals & activity</h1>
      <p style={{ color: "var(--text-2)" }}>Risky actions in <strong>{current.name}</strong> wait here until a person approves them.</p>
      {canAudit && (<div className="tabs" role="tablist">
        <button role="tab" aria-selected={tab === "inbox"} onClick={() => setTab("inbox")}>Approvals</button>
        <button role="tab" aria-selected={tab === "activity"} onClick={() => setTab("activity")}>Activity</button>
      </div>)}
      {tab === "inbox" || !canAudit ? <Inbox wsId={current.id} /> : <Activity wsId={current.id} />}
    </>
  );
}
