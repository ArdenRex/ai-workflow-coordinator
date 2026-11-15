import { useEffect, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth/AuthContext";
import PasswordInput from "../components/PasswordInput";

const LABELS = { register: "Account created", login: "Signed in", login_failed: "Failed sign-in", logout: "Signed out (all devices)",
  password_changed: "Password changed", password_change_failed: "Failed password change" };

export default function AccountPage() {
  const { user, remember, replaceToken } = useAuth();
  const [cur, setCur] = useState(""); const [next, setNext] = useState("");
  const [busy, setBusy] = useState(false); const [msg, setMsg] = useState(null);
  const [events, setEvents] = useState(null); const [evErr, setEvErr] = useState("");

  const loadActivity = () => api.activity(50).then(setEvents).catch((e) => setEvErr(e.message));
  useEffect(() => { loadActivity(); }, []);

  async function change(e) {
    e.preventDefault(); setBusy(true); setMsg(null);
    try {
      replaceToken(await api.changePassword(cur, next, remember), remember);
      setCur(""); setNext("");
      setMsg({ ok: true, text: "Password changed. You were signed out on every other device." });
      loadActivity();
    } catch (err) { setMsg({ ok: false, text: err.message }); }
    finally { setBusy(false); }
  }

  return (
    <>
      <h1>Account</h1>
      <p style={{ color: "var(--text-2)" }}>{user.email}</p>
      <form className="card" onSubmit={change}>
        <h2>Change password</h2>
        <p className="hint">Changing it signs you out everywhere else. At least 10 characters, and different from the current one.</p>
        <label className="f" htmlFor="cur">Current password</label>
        <PasswordInput inputId="cur" value={cur} onChange={(e) => setCur(e.target.value)} autoComplete="current-password" />
        <label className="f" htmlFor="new">New password</label>
        <PasswordInput inputId="new" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" />
        {msg && <div className={`msg ${msg.ok ? "ok" : "err"}`} role="status">{msg.text}</div>}
        <button className="btn" style={{ width: "auto", padding: "10px 18px" }} disabled={busy || !cur || !next}>{busy ? "Saving…" : "Change password"}</button>
      </form>
      <div className="card">
        <h2>Recent account activity</h2>
        {evErr && <div className="msg err">{evErr}</div>}
        {!events && !evErr && <p className="hint">Loading…</p>}
        {events && (events.length === 0 ? <p className="hint">No activity yet.</p> : (
          <table className="t"><thead><tr><th>Event</th><th>Address</th><th>When</th></tr></thead>
            <tbody>{events.map((ev, i) => (
              <tr key={i}><td>{LABELS[ev.event_type] || ev.event_type}</td><td>{ev.ip || "—"}</td><td>{new Date(/Z|[+-]\d\d:?\d\d$/.test(ev.created_at) ? ev.created_at : `${ev.created_at}Z`).toLocaleString()}</td></tr>))}</tbody></table>))}
      </div>
    </>
  );
}
