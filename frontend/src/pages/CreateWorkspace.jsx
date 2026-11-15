import { useState } from "react";
import { useWorkspace } from "../auth/WorkspaceContext";

export default function CreateWorkspace({ first }) {
  const { create } = useWorkspace();
  const [name, setName] = useState(""); const [busy, setBusy] = useState(false); const [err, setErr] = useState("");
  async function submit(e) {
    e.preventDefault(); setBusy(true); setErr("");
    try { await create(name.trim()); setName(""); } catch (x) { setErr(x.message); } finally { setBusy(false); }
  }
  return (
    <form className="card" onSubmit={submit}>
      <h2>{first ? "Create your first workspace" : "New workspace"}</h2>
      <p className="hint">A workspace is your company's private space. Systems, plans and approvals never cross between workspaces.</p>
      <label className="f" htmlFor="wsname">Workspace name</label>
      <input id="wsname" className="auth-input" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} />
      {err && <div className="msg err" role="alert">{err}</div>}
      <button className="btn" style={{ width: "auto", padding: "10px 18px" }} disabled={busy || !name.trim()}>{busy ? "Creating…" : "Create workspace"}</button>
    </form>
  );
}
