import { useCallback, useEffect, useState } from "react";
import { api } from "../api";
import { useWorkspace } from "../auth/WorkspaceContext";
import PasswordInput from "../components/PasswordInput";
import { buildConnection, PROVIDERS, PROVIDER_IDS, statusOf } from "../providers";

const EMPTY = { name: "", base_url: "", secret: "", allow_write: false };
const when = (s) => (s ? new Date(/Z|[+-]\d\d:?\d\d$/.test(s) ? s : `${s}Z`).toLocaleString() : "never");

function AddForm({ wsId, onDone }) {
  const [provider, setProvider] = useState("slack");
  const [form, setForm] = useState({ ...EMPTY, base_url: PROVIDERS.slack.base });
  const [busy, setBusy] = useState(false); const [err, setErr] = useState("");
  const p = PROVIDERS[provider];
  const set = (k) => (e) => setForm({ ...form, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  function pick(e) { setProvider(e.target.value); setForm({ ...EMPTY, name: form.name, base_url: PROVIDERS[e.target.value].base }); setErr(""); }
  async function submit(e) {
    e.preventDefault(); setErr("");
    const r = buildConnection(provider, form);
    if (r.error) { setErr(r.error); return; }
    setBusy(true);
    try { await api.createCredential(wsId, r.body); setForm({ ...EMPTY, base_url: p.base }); onDone(); } catch (x) { setErr(x.message); } finally { setBusy(false); }
  }
  return (
    <form className="card" onSubmit={submit} autoComplete="off">
      <h2>Connect a system</h2>
      <p className="hint">Your secret is encrypted on the server and is never shown again.</p>
      <label className="f" htmlFor="prov">System</label>
      <select id="prov" className="auth-input" value={provider} onChange={pick}>
        {PROVIDER_IDS.map((id) => <option key={id} value={id}>{PROVIDERS[id].label} ({PROVIDERS[id].domain})</option>)}
      </select>
      <label className="f" htmlFor="cn">Connection name</label>
      <input id="cn" className="auth-input" value={form.name} onChange={set("name")} maxLength={64} placeholder="e.g. Company Slack" />
      <label className="f" htmlFor="cb">Address (https)</label>
      <input id="cb" className="auth-input" value={form.base_url} onChange={set("base_url")} placeholder="https://" />
      {(p.fields || []).map((f) => (<div key={f.key}>
        <label className="f" htmlFor={`f-${f.key}`}>{f.label}</label>
        <input id={`f-${f.key}`} className="auth-input" value={form[f.key] || ""} onChange={set(f.key)} />
      </div>))}
      <label className="f" htmlFor="cs">{p.secretLabel}</label>
      <PasswordInput inputId="cs" value={form.secret} onChange={set("secret")} autoComplete="new-password" />
      {p.write && (<label className="check"><input type="checkbox" checked={form.allow_write} onChange={set("allow_write")} />
        Allow the AI to make changes in this system (still needs your approval for risky actions)</label>)}
      {err && <div className="msg err" role="alert">{err}</div>}
      <button className="btn" style={{ width: "auto", padding: "10px 18px" }} disabled={busy}>{busy ? "Connecting…" : "Connect"}</button>
    </form>
  );
}

function Row({ c, wsId, can, onChange }) {
  const [busy, setBusy] = useState(false); const [note, setNote] = useState(null); const [rot, setRot] = useState(null);
  const st = statusOf(c);
  const run = async (fn) => { setBusy(true); setNote(null); try { await fn(); } catch (x) { setNote({ ok: false, text: x.message }); } finally { setBusy(false); } };
  const test = () => run(async () => { const r = await api.testCredential(wsId, c.id); setNote({ ok: r.ok, text: r.message }); onChange(); });
  const revoke = () => { if (window.confirm(`Revoke "${c.name}"? The AI will lose access to this system. This cannot be undone.`)) run(async () => { await api.revokeCredential(wsId, c.id); onChange(); }); };
  const rotate = () => run(async () => { await api.rotateCredential(wsId, c.id, rot); setRot(null); setNote({ ok: true, text: "Secret replaced. Run a test to confirm it works." }); onChange(); });
  return (
    <tr>
      <td><strong style={{ color: "var(--text)" }}>{c.name}</strong><div className="hint">{(PROVIDERS[c.provider] || {}).label || c.provider}{c.config && c.config.allow_write ? " · changes allowed" : ""}</div></td>
      <td><span className={`pill ${st.tone}`}>{st.text}</span><div className="hint">Tested: {when(c.last_tested_at)}</div></td>
      <td>
        {c.is_active && (<div className="acts">
          {can("connection:test") && <button className="btn-s" disabled={busy} onClick={test}>Test</button>}
          {can("connection:write") && rot === null && <button className="btn-s" disabled={busy} onClick={() => setRot("")}>Replace secret</button>}
          {can("connection:write") && <button className="btn-s danger" disabled={busy} onClick={revoke}>Revoke</button>}
        </div>)}
        {rot !== null && (<div style={{ marginTop: 8 }}>
          <PasswordInput inputId={`r-${c.id}`} value={rot} onChange={(e) => setRot(e.target.value)} autoComplete="new-password" />
          <div className="acts" style={{ marginTop: 6 }}><button className="btn-s" disabled={busy || !rot.trim()} onClick={rotate}>Save</button><button className="btn-s" onClick={() => setRot(null)}>Cancel</button></div>
        </div>)}
        {note && <div className={`msg ${note.ok ? "ok" : "err"}`} role="status">{note.text}</div>}
      </td>
    </tr>
  );
}

export default function ConnectionsPage() {
  const { current, can } = useWorkspace();
  const [items, setItems] = useState(null); const [err, setErr] = useState("");
  const load = useCallback(() => api.credentials(current.id).then(setItems).catch((e) => setErr(e.message)), [current.id]);
  useEffect(() => { setItems(null); setErr(""); load(); }, [load]);
  const active = (items || []).filter((c) => c.is_active), revoked = (items || []).filter((c) => !c.is_active);
  return (
    <>
      <h1>Connections</h1>
      <p style={{ color: "var(--text-2)" }}>The business systems the AI can see in <strong>{current.name}</strong>.</p>
      {err && <div className="msg err" role="alert">{err}</div>}
      {!items && !err && <p className="hint" style={{ marginTop: 16 }}>Loading…</p>}
      {items && (<div className="card">
        <h2>Connected systems</h2>
        {active.length === 0 ? <p className="hint">Nothing connected yet.{can("connection:write") ? " Add your first system below." : " Ask a workspace admin to connect one."}</p> : (
          <table className="t"><thead><tr><th>System</th><th>Status</th><th>Actions</th></tr></thead>
            <tbody>{active.map((c) => <Row key={c.id} c={c} wsId={current.id} can={can} onChange={load} />)}</tbody></table>)}
        {revoked.length > 0 && <p className="hint" style={{ marginTop: 12 }}>{revoked.length} revoked connection{revoked.length > 1 ? "s" : ""} hidden.</p>}
      </div>)}
      {can("connection:write") && <AddForm wsId={current.id} onDone={load} />}
    </>
  );
}
