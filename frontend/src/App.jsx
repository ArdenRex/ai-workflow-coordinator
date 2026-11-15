import { useEffect, useState } from "react";
import { AuthProvider, useAuth } from "./auth/AuthContext";
import { useWorkspace, WorkspaceProvider } from "./auth/WorkspaceContext";
import Shell from "./components/Shell";
import ApprovalsPage from "./pages/ApprovalsPage";
import MonitoringPage from "./pages/MonitoringPage";
import AccountPage from "./pages/AccountPage";
import AuthPage from "./pages/AuthPage";
import ConnectionsPage from "./pages/ConnectionsPage";
import CreateWorkspace from "./pages/CreateWorkspace";
import GoalsPage from "./pages/GoalsPage";
import HomePage from "./pages/HomePage";

const PAGES = { home: HomePage, connections: ConnectionsPage, goals: GoalsPage, approvals: ApprovalsPage, monitoring: MonitoringPage, account: AccountPage };
const pageFromPath = () => (window.location.pathname.replace(/^\/+|\/+$/g, "").split("/")[0] || "home");

function Routes() {
  const { user, booting } = useAuth();
  const { list, current } = useWorkspace() || {};
  const [page, setPage] = useState(pageFromPath);
  useEffect(() => { const f = () => setPage(pageFromPath()); window.addEventListener("popstate", f); return () => window.removeEventListener("popstate", f); }, []);
  const go = (id) => { window.history.pushState({}, "", id === "home" ? "/" : `/${id}`); setPage(id); };

  if (booting) return <div className="auth-wrap"><span className="brand">ACEDEN AI OS</span></div>;
  if (!user) return <AuthPage />;
  if (list === null) return <div className="auth-wrap"><span className="brand">ACEDEN AI OS</span></div>;
  if (!current && list.length === 0) return <div className="auth-wrap"><div style={{ maxWidth: 480, width: "100%" }}><div className="brand">ACEDEN AI OS</div><CreateWorkspace first /></div></div>;
  if (!current) return <div className="auth-wrap"><span className="brand">Loading workspace…</span></div>;
  const Page = PAGES[page] || HomePage;
  return <Shell page={PAGES[page] ? page : "home"} onNavigate={go}><Page onNavigate={go} /></Shell>;
}

function Gate() {
  const { user, booting } = useAuth();
  if (booting || !user) return <Routes />;
  return <WorkspaceProvider><Routes /></WorkspaceProvider>;
}

export default function App() { return <AuthProvider><Gate /></AuthProvider>; }
