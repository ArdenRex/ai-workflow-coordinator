import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import { useWorkspace } from "../auth/WorkspaceContext";
import { DECOMPOSITION_TEXT, headlineOf, hintForError, isActive, newKey, PLAN_LABELS, STEP_LABELS, stepOrder, TONES } from "../plans";

const when = (s) => (s ? new Date(/Z|[+-]\d\d:?\d\d$/.test(s) ? s : `${s}Z`).toLocaleString() : "—");
const Pill = ({ text, tone }) => <span className={`pill ${tone || ""}`}>{text}</span>;

function Composer({ wsId, onProposal }) {
  const [goal, setGoal] = useState(""); const [busy, setBusy] = useState(false); const [err, setErr] = useState(null); const [info, setInfo] = useState(null);
  const key = useRef(newKey());
  async function submit(e) {
    e.preventDefault(); setBusy(true); setErr(null); setInfo(null);
    try {
      const r = await api.createPlan(wsId, goal.trim(), key.current);
      if (r.decomposition === "planned") { onProposal({ goal: goal.trim(), planId: r.plan.id, steps: r.proposed_steps || [], message: r.message }); setGoal(""); key.current = newKey(); }
      else setInfo({ text: r.message || DECOMPOSITION_TEXT[r.decomposition] || "No plan was created.", missing: r.missing_information || [] });
    } catch (x) { setErr({ text: x.message, hint: hintForError(x) }); } finally { setBusy(false); }
  }
  return (
    <form className="card" onSubmit={submit}>
      <h2>Give the AI a goal</h2>
      <p className="hint">Describe what you want done. You will see the plan and approve it before anything runs.</p>
      <label className="f" htmlFor="goal">Goal</label>
      <textarea id="goal" className="auth-input" rows={3} maxLength={4000} value={goal} onChange={(e) => { setGoal(e.target.value); key.current = newKey(); }} placeholder="e.g. Summarise what needs my attention this week" />
      {err && <div className="msg err" role="alert">{err.text}{err.hint && <div>{err.hint}</div>}</div>}
      {info && <div className="msg warn" role="status">{info.text}{info.missing.length > 0 && <ul style={{ margin: "6px 0 0 18px" }}>{info.missing.map((m, i) => <li key={i}>{m}</li>)}</ul>}</div>}
      <button className="btn" style={{ width: "auto", padding: "10px 18px" }} disabled={busy || !goal.trim()}>{busy ? "Planning…" : "Create plan"}</button>
    </form>
  );
}

function Proposal({ wsId, p, onRan, onDiscard }) {
  const [busy, setBusy] = useState(false); const [err, setErr] = useState("");
  async function run() { setBusy(true); setErr(""); try { const r = await api.runPlan(wsId, p.planId, p.goal, p.steps); onRan(r.plan); } catch (x) { setErr(x.message); } finally { setBusy(false); } }
  async function discard() { setBusy(true); try { await api.cancelPlan(wsId, p.planId); } catch (_) { /* nothing ran; the plan stays queued */ } onDiscard(); }
  return (
    <div className="card">
      <h2>Review the plan</h2>
      <p className="hint">{p.message}</p>
      <p style={{ margin: "10px 0", color: "var(--text-2)" }}><strong style={{ color: "var(--text)" }}>Goal:</strong> {p.goal}</p>
      <ol className="steps">{p.steps.map((s) => (
        <li key={s.id}><div><strong>{s.id}</strong> <Pill text={s.agent_id} /> {s.depends_on.length > 0 && <span className="hint">after {s.depends_on.join(", ")}</span>}</div>
          <div style={{ color: "var(--text-2)" }}>{s.instruction}</div></li>))}</ol>
      <p className="hint">Steps that change something outside still stop and wait for a human approval.</p>
      {err && <div className="msg err" role="alert">{err}</div>}
      <div className="acts" style={{ marginTop: 12 }}>
        <button className="btn" style={{ width: "auto", padding: "10px 18px", marginTop: 0 }} disabled={busy} onClick={run}>{busy ? "Starting…" : "Approve and run"}</button>
        <button className="btn-s" disabled={busy} onClick={discard}>Discard</button>
      </div>
    </div>
  );
}

function PlanDetail({ wsId, planId, initial, onChanged }) {
  const [plan, setPlan] = useState(initial || null); const [err, setErr] = useState(""); const [busy, setBusy] = useState(false);
  const load = useCallback(() => api.plan(wsId, planId).then((p) => { setPlan(p); setErr(""); return p; }).catch((x) => setErr(x.message)), [wsId, planId]);
  useEffect(() => { setPlan(initial || null); load(); }, [load]);
  useEffect(() => {
    if (!plan || !isActive(plan)) return undefined;
    const t = setInterval(() => { load().then((p) => p && !isActive(p) && onChanged()); }, 3000);
    return () => clearInterval(t);
  }, [plan, load, onChanged]);
  async function cancel() { setBusy(true); try { setPlan(await api.cancelPlan(wsId, planId)); onChanged(); } catch (x) { setErr(x.message); } finally { setBusy(false); } }
  if (err && !plan) return <div className="msg err" role="alert">{err}</div>;
  if (!plan) return <p className="hint">Loading…</p>;
  const head = headlineOf(plan); const s = plan.summary;
  return (
    <div className="card">
      <h2>Plan details <Pill text={PLAN_LABELS[head] || head} tone={TONES[head]} /></h2>
      <p className="hint">Started {when(plan.started_at || plan.created_at)}{plan.finished_at ? ` · finished ${when(plan.finished_at)}` : ""}</p>
      {s && <p style={{ margin: "8px 0", color: "var(--text-2)" }}>{s.finished_steps} of {s.total_steps} steps finished</p>}
      {s && s.needs_attention.approvals.length > 0 && <div className="msg warn" role="status">{s.needs_attention.approvals.length} step(s) are waiting for a human approval before they can continue.</div>}
      <table className="t"><thead><tr><th>Step</th><th>Agent</th><th>Status</th><th>Detail</th></tr></thead>
        <tbody>{stepOrder(plan.steps).map((st) => (
          <tr key={st.key}><td>{st.key}{st.depends_on.length > 0 && <div className="hint">after {st.depends_on.join(", ")}</div>}</td><td>{st.agent_id}</td>
            <td><Pill text={STEP_LABELS[st.status] || st.status} tone={TONES[st.status]} /></td>
            <td style={{ color: "var(--text-3)" }}>{st.error_code ? st.error_code.replace(/_/g, " ") : st.result && st.result.outcome ? String(st.result.outcome).replace(/_/g, " ") : "—"}</td></tr>))}</tbody></table>
      {err && <div className="msg err" role="alert">{err}</div>}
      {isActive(plan) && <div className="acts" style={{ marginTop: 12 }}><button className="btn-s danger" disabled={busy || plan.cancel_requested} onClick={cancel}>{plan.cancel_requested ? "Cancelling…" : "Cancel plan"}</button></div>}
    </div>
  );
}

export default function GoalsPage() {
  const { current, can } = useWorkspace();
  const [plans, setPlans] = useState(null); const [err, setErr] = useState("");
  const [proposal, setProposal] = useState(null); const [selected, setSelected] = useState(null); const [ran, setRan] = useState(null);
  const load = useCallback(() => api.plans(current.id).then(setPlans).catch((e) => setErr(e.message)), [current.id]);
  useEffect(() => { setPlans(null); setProposal(null); setSelected(null); load(); }, [load]);
  if (!can("agent:run")) return (<><h1>Goals &amp; plans</h1><div className="msg err">Your role in this workspace cannot run plans. Ask a workspace admin.</div></>);
  return (
    <>
      <h1>Goals &amp; plans</h1>
      <p style={{ color: "var(--text-2)" }}>Tell the AI what you want done in <strong>{current.name}</strong>.</p>
      {!proposal && <Composer wsId={current.id} onProposal={(p) => { setProposal(p); setSelected(null); load(); }} />}
      {proposal && <Proposal wsId={current.id} p={proposal} onDiscard={() => { setProposal(null); load(); }} onRan={(plan) => { setProposal(null); setRan(plan); setSelected(plan.id); load(); }} />}
      {selected && <PlanDetail key={selected} wsId={current.id} planId={selected} initial={ran && ran.id === selected ? ran : null} onChanged={load} />}
      <div className="card">
        <h2>Recent plans</h2>
        {err && <div className="msg err">{err}</div>}
        {!plans && !err && <p className="hint">Loading…</p>}
        {plans && (plans.length === 0 ? <p className="hint">No plans yet.</p> : (
          <table className="t"><thead><tr><th>Created</th><th>Steps</th><th>Status</th><th /></tr></thead>
            <tbody>{plans.map((p) => (
              <tr key={p.id}><td>{when(p.created_at)}</td><td>{p.step_count}</td><td><Pill text={PLAN_LABELS[p.status] || p.status} tone={TONES[p.status]} /></td>
                <td><button className="btn-s" onClick={() => { setProposal(null); setSelected(p.id); }}>Open</button></td></tr>))}</tbody></table>))}
      </div>
    </>
  );
}
