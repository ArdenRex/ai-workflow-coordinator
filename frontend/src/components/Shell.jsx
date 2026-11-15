import { useAuth } from "../auth/AuthContext";
import { useWorkspace } from "../auth/WorkspaceContext";

const ITEMS = [{ id: "home", label: "Home" }, { id: "connections", label: "Connections" }, { id: "goals", label: "Goals & plans" },
  { id: "approvals", label: "Approvals" }, { id: "monitoring", label: "Monitoring" }, { id: "account", label: "Account" }];

export default function Shell({ page, onNavigate, children }) {
  const { user, signOut } = useAuth();
  const { list, current, select } = useWorkspace();
  return (
    <div className="shell">
      <nav className="side" aria-label="Main">
        <div className="brand">ACEDEN AI OS</div>
        {list && list.length > 0 && (<div className="ws-pick"><select aria-label="Workspace" value={current ? current.id : ""} onChange={(e) => select(e.target.value)}>
          {list.map((w) => <option key={w.id} value={w.id}>{w.name}</option>)}</select></div>)}
        {ITEMS.map((it) => (
          <button key={it.id} className="nav" disabled={it.soon || (!current && it.id !== "account" && it.id !== "home")} aria-current={page === it.id ? "page" : undefined} onClick={() => onNavigate(it.id)}>
            {it.label}{it.soon && <span className="soon">Soon</span>}
          </button>))}
        <div className="grow" />
        <div className="who">{user.email}</div>
        <button className="nav" onClick={signOut} title="Ends your session on every device">Sign out</button>
      </nav>
      <main className="main">{children}</main>
    </div>
  );
}
