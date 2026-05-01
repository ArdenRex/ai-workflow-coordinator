import { useState, useEffect, useCallback } from "react";

const API = process.env.REACT_APP_API_URL || "https://ai-workflow-coordinator-api-production.up.railway.app";

function useAdminFetch(path) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetch_ = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const token = localStorage.getItem("access_token");
      const res = await fetch(`${API}${path}`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) throw new Error(`${res.status}`);
      const json = await res.json();
      setData(json);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }, [path]);

  useEffect(() => { fetch_(); }, [fetch_]);
  return { data, loading, error, refetch: fetch_ };
}

// ── Sparkline ──────────────────────────────────────────────────────────────────
function Sparkline({ values, color = "#c084fc" }) {
  if (!values || values.length < 2) return null;
  const max = Math.max(...values, 1);
  const min = Math.min(...values);
  const range = max - min || 1;
  const w = 100, h = 32;
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * w;
    const y = h - ((v - min) / range) * (h - 4) - 2;
    return `${x},${y}`;
  });
  const id = `spark-${color.replace('#','')}`;
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ height: 32 }}>
      <defs>
        <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.35" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polyline points={`0,${h} ${pts.join(" ")} ${w},${h}`} fill={`url(#${id})`} stroke="none" />
      <polyline points={pts.join(" ")} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

// ── Metric Card ────────────────────────────────────────────────────────────────
function MetricCard({ label, value, sub, color = "#c084fc", spark, icon, trend }) {
  return (
    <div className="metric-card" style={{ "--card-accent": color }}>
      <div className="metric-card-glow" />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
        <span className="metric-label">{label}</span>
        <span className="metric-icon">{icon}</span>
      </div>
      <div className="metric-value">{value}</div>
      {sub && <div className="metric-sub">{sub}</div>}
      {trend !== undefined && (
        <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 4 }}>
          <span style={{ fontSize: 11, color: trend >= 0 ? "#4ade80" : "#f87171", fontWeight: 600 }}>
            {trend >= 0 ? "↑" : "↓"} {Math.abs(trend)}%
          </span>
          <span style={{ fontSize: 10, color: "#4b5563" }}>vs last month</span>
        </div>
      )}
      {spark && (
        <div style={{ marginTop: 12 }}>
          <Sparkline values={spark} color={color} />
        </div>
      )}
      <div className="metric-card-bar" />
    </div>
  );
}

// ── Revenue Chart ──────────────────────────────────────────────────────────────
function RevenueChart({ data }) {
  const [hovered, setHovered] = useState(null);
  if (!data || !data.length) return null;
  const max = Math.max(...data.map(d => d.revenue), 1);
  return (
    <div style={{ overflowX: "auto", paddingBottom: 4 }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 8, height: 140, minWidth: data.length * 52, padding: "0 4px" }}>
        {data.map((d, i) => {
          const isHov = hovered === i;
          const h = Math.max(4, (d.revenue / max) * 116);
          return (
            <div
              key={i}
              style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 4, cursor: "pointer" }}
              onMouseEnter={() => setHovered(i)}
              onMouseLeave={() => setHovered(null)}
            >
              {isHov && d.revenue > 0 && (
                <div style={{
                  fontSize: 10, color: "#e2e8f0", background: "#1a1b23", border: "1px solid #2d2f3e",
                  borderRadius: 6, padding: "3px 7px", whiteSpace: "nowrap", fontVariantNumeric: "tabular-nums",
                  boxShadow: "0 4px 12px rgba(0,0,0,0.5)", marginBottom: 2,
                }}>${d.revenue.toFixed(0)}</div>
              )}
              {!isHov && <div style={{ height: 22 }} />}
              <div style={{
                width: "100%",
                height: h,
                background: d.revenue > 0
                  ? isHov
                    ? "linear-gradient(180deg, #e879f9, #8b5cf6)"
                    : "linear-gradient(180deg, #c084fc 0%, #7c3aed 100%)"
                  : "#1a1b23",
                borderRadius: "5px 5px 0 0",
                transition: "all 0.25s cubic-bezier(0.4,0,0.2,1)",
                opacity: hovered !== null && !isHov ? 0.45 : 1,
                boxShadow: isHov ? "0 0 20px rgba(192,132,252,0.4)" : "none",
              }} />
              <div style={{ fontSize: 9, color: isHov ? "#c084fc" : "#374151", textAlign: "center", transition: "color 0.2s", fontWeight: isHov ? 600 : 400 }}>
                {d.month.split(" ")[0]}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Signup Area Chart ──────────────────────────────────────────────────────────
function SignupTrend({ data }) {
  if (!data || !data.length) return null;
  const max = Math.max(...data.map(d => d.signups), 1);
  const w = 100, h = 70;
  const pts = data.map((d, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - (d.signups / max) * (h - 6) - 3;
    return `${x},${y}`;
  });
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ height: 70 }}>
      <defs>
        <linearGradient id="signup-grad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#34d399" stopOpacity="0.4" />
          <stop offset="100%" stopColor="#34d399" stopOpacity="0" />
        </linearGradient>
      </defs>
      <polyline points={`0,${h} ${pts.join(" ")} ${w},${h}`} fill="url(#signup-grad)" stroke="none" />
      <polyline points={pts.join(" ")} fill="none" stroke="#34d399" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

// ── Badge ──────────────────────────────────────────────────────────────────────
function Badge({ text }) {
  const map = {
    active:    { bg: "rgba(52,211,153,0.12)", color: "#34d399", border: "rgba(52,211,153,0.25)" },
    trialing:  { bg: "rgba(251,191,36,0.12)", color: "#fbbf24", border: "rgba(251,191,36,0.25)" },
    cancelled: { bg: "rgba(248,113,113,0.12)", color: "#f87171", border: "rgba(248,113,113,0.25)" },
    exempt:    { bg: "rgba(192,132,252,0.12)", color: "#c084fc", border: "rgba(192,132,252,0.25)" },
    paid:      { bg: "rgba(52,211,153,0.12)", color: "#34d399", border: "rgba(52,211,153,0.25)" },
    open:      { bg: "rgba(251,191,36,0.12)", color: "#fbbf24", border: "rgba(251,191,36,0.25)" },
    resolved:  { bg: "rgba(52,211,153,0.12)", color: "#34d399", border: "rgba(52,211,153,0.25)" },
    admin:     { bg: "rgba(192,132,252,0.12)", color: "#c084fc", border: "rgba(192,132,252,0.25)" },
    member:    { bg: "rgba(148,163,184,0.1)", color: "#94a3b8", border: "rgba(148,163,184,0.2)" },
  };
  const s = map[text?.toLowerCase()] || { bg: "rgba(148,163,184,0.1)", color: "#94a3b8", border: "rgba(148,163,184,0.2)" };
  return (
    <span style={{
      background: s.bg,
      color: s.color,
      border: `1px solid ${s.border}`,
      padding: "2px 9px",
      borderRadius: 20,
      fontSize: 10.5,
      fontWeight: 600,
      letterSpacing: "0.04em",
      textTransform: "uppercase",
    }}>{text}</span>
  );
}

// ── Nav Tab ────────────────────────────────────────────────────────────────────
function NavTab({ label, active, onClick, count, icon }) {
  return (
    <button onClick={onClick} className={`nav-tab ${active ? "nav-tab-active" : ""}`}>
      <span>{icon}</span>
      <span>{label}</span>
      {count !== undefined && (
        <span className={`nav-count ${active ? "nav-count-active" : ""}`}>{count}</span>
      )}
    </button>
  );
}

// ── Users Table ────────────────────────────────────────────────────────────────
function UsersTable() {
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(search), 400);
    return () => clearTimeout(t);
  }, [search]);

  const params = new URLSearchParams({ limit: 100 });
  if (debouncedSearch) params.set("search", debouncedSearch);
  if (statusFilter) params.set("status", statusFilter);

  const { data, loading, refetch } = useAdminFetch(`/admin/users?${params}`);

  const handleToggleActive = async (userId, current) => {
    const token = localStorage.getItem("access_token");
    await fetch(`${API}/admin/users/${userId}`, {
      method: "PATCH",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: !current }),
    });
    refetch();
  };

  return (
    <div>
      <div style={{ display: "flex", gap: 10, marginBottom: 20 }}>
        <div style={{ position: "relative", flex: 1 }}>
          <span style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", color: "#4b5563", fontSize: 14 }}>⌕</span>
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search by name or email…"
            style={{ ...inputStyle, paddingLeft: 32 }}
          />
        </div>
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} style={{ ...inputStyle, flex: "0 0 180px" }}>
          <option value="">All statuses</option>
          <option value="trialing">Trialing</option>
          <option value="active">Active (paid)</option>
          <option value="cancelled">Cancelled</option>
          <option value="exempt">Exempt</option>
        </select>
      </div>

      {loading ? <Loader /> : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr>
                {["#", "Name", "Email", "Role", "Status", "Workspace", "Trial Ends", "Joined", "Action"].map(h => (
                  <th key={h} style={{
                    padding: "10px 14px", textAlign: "left", color: "#4b5563",
                    fontWeight: 500, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.07em",
                    borderBottom: "1px solid #1e2130", whiteSpace: "nowrap",
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data?.users?.map((u, idx) => (
                <tr key={u.id} className="table-row">
                  <td style={{ ...td, color: "#374151", fontSize: 11 }}>{idx + 1}</td>
                  <td style={{ ...td, fontWeight: 600, color: "#e2e8f0" }}>{u.name}</td>
                  <td style={{ ...td, color: "#6b7280", fontFamily: "'JetBrains Mono', monospace", fontSize: 12 }}>{u.email}</td>
                  <td style={td}><Badge text={u.role} /></td>
                  <td style={td}><Badge text={u.subscription_status} /></td>
                  <td style={{ ...td, color: "#4b5563" }}>{u.workspace_id ?? "—"}</td>
                  <td style={{ ...td, color: u.trial_expired ? "#f87171" : "#4b5563" }}>
                    {u.trial_ends_at ? new Date(u.trial_ends_at).toLocaleDateString() : "—"}
                    {u.trial_expired && <span style={{ marginLeft: 4, fontSize: 10 }}>⚠</span>}
                  </td>
                  <td style={{ ...td, color: "#4b5563" }}>
                    {u.created_at ? new Date(u.created_at).toLocaleDateString() : "—"}
                  </td>
                  <td style={td}>
                    {u.email === "wahaj@acedengroup.com" ? (
                      <span style={{
                        fontSize: 10, color: "#374151", fontFamily: "'JetBrains Mono', monospace",
                        padding: "4px 10px", border: "1px solid #1e2130", borderRadius: 8,
                        display: "inline-flex", alignItems: "center", gap: 4,
                      }}>⬡ Super Admin</span>
                    ) : (
                      <button
                        onClick={() => handleToggleActive(u.id, u.is_active)}
                        className={u.is_active ? "toggle-btn-active" : "toggle-btn-inactive"}
                      >
                        {u.is_active ? "● Active" : "○ Disabled"}
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ marginTop: 14, color: "#374151", fontSize: 12, display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ color: "#c084fc", fontWeight: 700 }}>{data?.total}</span>
            <span>total users</span>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Workspaces Table ───────────────────────────────────────────────────────────
function WorkspacesTable() {
  const { data, loading, refetch } = useAdminFetch("/admin/workspaces?limit=100");

  const handleToggleWorkspace = async (wsId, current) => {
    const token = localStorage.getItem("access_token");
    await fetch(`${API}/admin/workspaces/${wsId}`, {
      method: "PATCH",
      headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body: JSON.stringify({ is_active: !current }),
    });
    refetch();
  };

  if (loading) return <Loader />;
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr>
            {["#", "Workspace", "Owner", "Members", "Tasks", "Created", "Action"].map(h => (
              <th key={h} style={{
                padding: "10px 14px", textAlign: "left", color: "#4b5563",
                fontWeight: 500, fontSize: 11, textTransform: "uppercase", letterSpacing: "0.07em",
                borderBottom: "1px solid #1e2130", whiteSpace: "nowrap",
              }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data?.workspaces?.map((ws, idx) => {
            const isActive = ws.is_active !== false; // default true if field missing
            return (
              <tr key={ws.id} className="table-row">
                <td style={{ ...td, color: "#374151", fontSize: 11 }}>{idx + 1}</td>
                <td style={{ ...td, fontWeight: 600, color: "#e2e8f0" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <div style={{
                      width: 28, height: 28, borderRadius: 8,
                      background: isActive
                        ? "linear-gradient(135deg, #7c3aed, #c084fc)"
                        : "linear-gradient(135deg, #1e2130, #374151)",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: 11, fontWeight: 700, color: "#fff", flexShrink: 0,
                      transition: "background 0.3s",
                    }}>{ws.name?.[0]?.toUpperCase() || "W"}</div>
                    <span style={{ color: isActive ? "#e2e8f0" : "#4b5563", transition: "color 0.2s" }}>{ws.name}</span>
                  </div>
                </td>
                <td style={{ ...td, color: "#6b7280", fontFamily: "'JetBrains Mono', monospace", fontSize: 12 }}>{ws.owner_email ?? "—"}</td>
                <td style={td}>
                  <span style={{ color: "#c084fc", fontWeight: 600 }}>{ws.member_count}</span>
                </td>
                <td style={td}>
                  <span style={{ color: "#34d399", fontWeight: 600 }}>{ws.task_count}</span>
                </td>
                <td style={{ ...td, color: "#4b5563" }}>{ws.created_at ? new Date(ws.created_at).toLocaleDateString() : "—"}</td>
                <td style={td}>
                  {ws.owner_email === "wahaj@acedengroup.com" ? (
                    <span style={{
                      fontSize: 10, color: "#374151", fontFamily: "'JetBrains Mono', monospace",
                      padding: "4px 10px", border: "1px solid #1e2130", borderRadius: 8,
                      display: "inline-flex", alignItems: "center", gap: 4,
                    }}>⬡ Protected</span>
                  ) : (
                    <button
                      onClick={() => handleToggleWorkspace(ws.id, isActive)}
                      className={isActive ? "toggle-btn-active" : "toggle-btn-inactive"}
                    >
                      {isActive ? "● Active" : "○ Disabled"}
                    </button>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      <div style={{ marginTop: 14, color: "#374151", fontSize: 12, display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ color: "#c084fc", fontWeight: 700 }}>{data?.total}</span>
        <span>total workspaces</span>
      </div>
    </div>
  );
}

// ── Feedback Table ─────────────────────────────────────────────────────────────
function FeedbackTable() {
  const { data, loading } = useAdminFetch("/admin/feedback?limit=100");
  if (loading) return <Loader />;
  const typeStyle = {
    bug:             { bg: "rgba(248,113,113,0.1)", color: "#f87171", border: "rgba(248,113,113,0.25)", icon: "🐛" },
    feedback:        { bg: "rgba(192,132,252,0.1)", color: "#c084fc", border: "rgba(192,132,252,0.25)", icon: "💬" },
    feature_request: { bg: "rgba(52,211,153,0.1)", color: "#34d399", border: "rgba(52,211,153,0.25)", icon: "✦" },
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {data?.items?.map(f => {
        const ts = typeStyle[f.type] || { bg: "rgba(148,163,184,0.1)", color: "#94a3b8", border: "rgba(148,163,184,0.2)", icon: "•" };
        return (
          <div key={f.id} className="feedback-card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 8, gap: 12 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <span style={{
                  background: ts.bg, color: ts.color, border: `1px solid ${ts.border}`,
                  padding: "2px 9px", borderRadius: 20, fontSize: 10, fontWeight: 700,
                  textTransform: "uppercase", letterSpacing: "0.05em",
                  display: "flex", alignItems: "center", gap: 4,
                }}>
                  {ts.icon} {f.type.replace("_", " ")}
                </span>
                <span style={{ color: "#e2e8f0", fontWeight: 600, fontSize: 13 }}>{f.title}</span>
              </div>
              <Badge text={f.status} />
            </div>
            <p style={{ color: "#6b7280", fontSize: 12.5, margin: "0 0 10px", lineHeight: 1.6 }}>{f.message}</p>
            <div style={{ display: "flex", gap: 16, fontSize: 11, color: "#374151", flexWrap: "wrap" }}>
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <span style={{ color: "#4b5563" }}>◎</span>
                <span>{f.user_name ?? "Anonymous"}</span>
                {f.user_email && <span style={{ color: "#374151" }}>({f.user_email})</span>}
              </span>
              {f.page_context && (
                <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                  <span style={{ color: "#4b5563" }}>⊕</span> {f.page_context}
                </span>
              )}
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <span style={{ color: "#4b5563" }}>◷</span>
                {f.created_at ? new Date(f.created_at).toLocaleString() : "—"}
              </span>
            </div>
          </div>
        );
      })}
      {!data?.items?.length && (
        <div style={{ textAlign: "center", padding: 60, color: "#374151" }}>
          <div style={{ fontSize: 32, marginBottom: 10 }}>✦</div>
          <div style={{ fontSize: 14 }}>No feedback submissions yet</div>
        </div>
      )}
    </div>
  );
}

// ── Loader ─────────────────────────────────────────────────────────────────────
function Loader() {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: 60, gap: 16 }}>
      <div style={{
        width: 36, height: 36,
        border: "2px solid #1e2130",
        borderTop: "2px solid #c084fc",
        borderRight: "2px solid #7c3aed",
        borderRadius: "50%",
        animation: "spin 0.8s linear infinite",
      }} />
      <span style={{ color: "#374151", fontSize: 12, letterSpacing: "0.1em", textTransform: "uppercase" }}>Loading data…</span>
    </div>
  );
}

const inputStyle = {
  background: "#0e0f16",
  border: "1px solid #1e2130",
  borderRadius: 10,
  padding: "9px 14px",
  color: "#e2e8f0",
  fontSize: 13,
  outline: "none",
  width: "100%",
  transition: "border-color 0.2s",
  fontFamily: "inherit",
};

const td = {
  padding: "12px 14px",
  color: "#6b7280",
  whiteSpace: "nowrap",
};

// ── Main Dashboard ─────────────────────────────────────────────────────────────
export default function AdminDashboard() {
  const [tab, setTab] = useState("overview");
  const { data: metrics, loading, error, refetch } = useAdminFetch("/admin/metrics");
  const m = metrics;

  const now = new Date();
  const timeStr = now.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit" });
  const dateStr = now.toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" });

  return (
    <div style={{ minHeight: "100vh", background: "#080a10", color: "#e2e8f0" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;500;600;700;800&family=JetBrains+Mono:wght@300;400;500;600&display=swap');

        * { box-sizing: border-box; margin: 0; padding: 0; }

        body { background: #080a10; }

        ::-webkit-scrollbar { width: 5px; height: 5px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: #1e2130; border-radius: 10px; }

        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes fadeUp {
          from { opacity: 0; transform: translateY(16px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes pulse-glow {
          0%, 100% { opacity: 0.4; }
          50% { opacity: 0.7; }
        }

        .dashboard-root {
          font-family: 'Syne', sans-serif;
          display: flex;
          min-height: 100vh;
        }

        /* ── SIDEBAR ── */
        .sidebar {
          width: 220px;
          min-height: 100vh;
          background: #0b0c14;
          border-right: 1px solid #131520;
          display: flex;
          flex-direction: column;
          padding: 28px 0;
          position: fixed;
          top: 0; left: 0; bottom: 0;
          z-index: 10;
        }

        .sidebar-logo {
          padding: 0 24px 32px;
          border-bottom: 1px solid #131520;
          margin-bottom: 24px;
        }

        .logo-mark {
          width: 38px; height: 38px;
          background: linear-gradient(135deg, #7c3aed 0%, #c084fc 100%);
          border-radius: 10px;
          display: flex; align-items: center; justify-content: center;
          font-size: 18px; font-weight: 800; color: #fff;
          margin-bottom: 10px;
          box-shadow: 0 0 20px rgba(124,58,237,0.35);
        }

        .logo-text {
          font-size: 14px; font-weight: 700; color: #e2e8f0; letter-spacing: -0.01em;
        }

        .logo-sub {
          font-size: 10px; color: #374151; letter-spacing: 0.1em; text-transform: uppercase; margin-top: 1px;
          font-family: 'JetBrains Mono', monospace;
        }

        .nav-section-label {
          padding: 0 24px; font-size: 9px; color: #374151;
          text-transform: uppercase; letter-spacing: 0.12em; margin-bottom: 6px;
          font-family: 'JetBrains Mono', monospace;
        }

        .nav-tab {
          display: flex; align-items: center; gap: 10px;
          padding: 10px 24px; width: 100%; border: none; background: transparent;
          color: #4b5563; font-size: 13px; font-weight: 500; cursor: pointer;
          transition: all 0.18s; font-family: 'Syne', sans-serif;
          position: relative; text-align: left; border-radius: 0;
        }

        .nav-tab:hover { color: #9ca3af; background: rgba(255,255,255,0.02); }

        .nav-tab-active {
          color: #e2e8f0 !important;
          background: rgba(192,132,252,0.08) !important;
        }

        .nav-tab-active::before {
          content: '';
          position: absolute; left: 0; top: 0; bottom: 0;
          width: 2px; background: linear-gradient(180deg, #7c3aed, #c084fc);
          border-radius: 0 2px 2px 0;
        }

        .nav-count {
          margin-left: auto; font-size: 10px; background: #1a1b23;
          color: #4b5563; border-radius: 10px; padding: 1px 7px; font-weight: 600;
          font-family: 'JetBrains Mono', monospace;
        }

        .nav-count-active {
          background: rgba(192,132,252,0.15) !important;
          color: #c084fc !important;
        }

        .sidebar-footer {
          margin-top: auto; padding: 20px 24px 0;
          border-top: 1px solid #131520;
        }

        .admin-pill {
          display: flex; align-items: center; gap: 8px;
        }

        .admin-avatar {
          width: 28px; height: 28px; border-radius: 8px;
          background: linear-gradient(135deg, #7c3aed, #c084fc);
          display: flex; align-items: center; justify-content: center;
          font-size: 11px; font-weight: 700; color: #fff; flex-shrink: 0;
        }

        /* ── MAIN CONTENT ── */
        .main-content {
          margin-left: 220px;
          flex: 1;
          padding: 0;
          min-height: 100vh;
        }

        /* ── TOP BAR ── */
        .topbar {
          padding: 20px 36px;
          display: flex; align-items: center; justify-content: space-between;
          border-bottom: 1px solid #0e1018;
          background: rgba(8,10,16,0.8);
          backdrop-filter: blur(10px);
          position: sticky; top: 0; z-index: 5;
        }

        .topbar-title {
          font-size: 18px; font-weight: 700; color: #f1f5f9; letter-spacing: -0.02em;
        }

        .topbar-date {
          font-size: 11px; color: #374151; margin-top: 1px;
          font-family: 'JetBrains Mono', monospace;
        }

        .refresh-btn {
          display: flex; align-items: center; gap: 7px;
          background: #0e0f16; border: 1px solid #1e2130;
          border-radius: 10px; padding: 8px 16px;
          color: #6b7280; font-size: 12px; cursor: pointer;
          transition: all 0.2s; font-family: 'Syne', sans-serif; font-weight: 500;
        }

        .refresh-btn:hover {
          border-color: #7c3aed; color: #c084fc;
          box-shadow: 0 0 16px rgba(124,58,237,0.15);
        }

        /* ── CONTENT AREA ── */
        .content-area {
          padding: 32px 36px;
          animation: fadeUp 0.4s ease both;
        }

        /* ── SECTION HEADING ── */
        .section-heading {
          font-size: 11px; color: #374151; text-transform: uppercase;
          letter-spacing: 0.1em; margin-bottom: 16px;
          font-family: 'JetBrains Mono', monospace;
          display: flex; align-items: center; gap: 8px;
        }

        .section-heading::after {
          content: ''; flex: 1; height: 1px; background: #131520;
        }

        /* ── METRIC CARD ── */
        .metric-card {
          background: #0b0c14;
          border: 1px solid #131520;
          border-radius: 14px;
          padding: 20px 22px 16px;
          display: flex; flex-direction: column;
          position: relative; overflow: hidden;
          transition: border-color 0.2s, transform 0.2s;
        }

        .metric-card:hover {
          border-color: var(--card-accent, #c084fc);
          transform: translateY(-2px);
        }

        .metric-card-glow {
          position: absolute; top: -30px; right: -30px;
          width: 80px; height: 80px; border-radius: 50%;
          background: var(--card-accent, #c084fc);
          opacity: 0.06; filter: blur(20px);
          pointer-events: none;
          animation: pulse-glow 3s ease-in-out infinite;
        }

        .metric-label {
          font-size: 10px; color: #4b5563; text-transform: uppercase;
          letter-spacing: 0.1em; font-family: 'JetBrains Mono', monospace;
        }

        .metric-icon {
          font-size: 16px; opacity: 0.7;
        }

        .metric-value {
          font-size: 30px; font-weight: 800; color: #f1f5f9;
          font-variant-numeric: tabular-nums; line-height: 1.15;
          letter-spacing: -0.02em; margin-top: 6px;
        }

        .metric-sub {
          font-size: 11px; color: #374151; margin-top: 4px;
          font-family: 'JetBrains Mono', monospace;
        }

        .metric-card-bar {
          position: absolute; bottom: 0; left: 0; right: 0;
          height: 1px; background: var(--card-accent, #c084fc); opacity: 0.3;
        }

        /* ── GLASS PANEL ── */
        .glass-panel {
          background: #0b0c14;
          border: 1px solid #131520;
          border-radius: 14px;
          padding: 24px 26px;
        }

        .panel-title {
          font-size: 10px; color: #374151; text-transform: uppercase;
          letter-spacing: 0.1em; font-family: 'JetBrains Mono', monospace;
          margin-bottom: 18px;
        }

        /* ── STAT ROW ── */
        .stat-row {
          background: #0b0c14; border: 1px solid #131520; border-radius: 14px;
          padding: 20px 26px; display: flex; flex-wrap: wrap; gap: 0;
        }

        .stat-item {
          flex: 1; min-width: 120px; padding: 0 24px;
          border-right: 1px solid #131520;
        }

        .stat-item:first-child { padding-left: 0; }
        .stat-item:last-child { border-right: none; }

        .stat-label {
          font-size: 9px; color: #374151; text-transform: uppercase;
          letter-spacing: 0.12em; font-family: 'JetBrains Mono', monospace;
          margin-bottom: 4px;
        }

        .stat-val {
          font-size: 20px; font-weight: 700; color: #f1f5f9;
          font-variant-numeric: tabular-nums; letter-spacing: -0.02em;
        }

        /* ── TABLE ── */
        .table-row { border-bottom: 1px solid #0e0f16; transition: background 0.15s; }
        .table-row:hover { background: rgba(255,255,255,0.015); }
        .table-row:last-child { border-bottom: none; }

        /* ── TOGGLE BUTTONS ── */
        .toggle-btn-active {
          background: rgba(52,211,153,0.1); color: #34d399;
          border: 1px solid rgba(52,211,153,0.25);
          border-radius: 8px; padding: 4px 10px; font-size: 11px;
          cursor: pointer; font-weight: 600; font-family: 'JetBrains Mono', monospace;
          transition: all 0.2s;
        }

        .toggle-btn-active:hover {
          background: rgba(248,113,113,0.1); color: #f87171;
          border-color: rgba(248,113,113,0.25);
        }

        .toggle-btn-inactive {
          background: rgba(248,113,113,0.1); color: #f87171;
          border: 1px solid rgba(248,113,113,0.25);
          border-radius: 8px; padding: 4px 10px; font-size: 11px;
          cursor: pointer; font-weight: 600; font-family: 'JetBrains Mono', monospace;
          transition: all 0.2s;
        }

        /* ── FEEDBACK CARD ── */
        .feedback-card {
          background: #0b0c14; border: 1px solid #131520;
          border-radius: 12px; padding: 16px 20px;
          transition: border-color 0.2s;
        }

        .feedback-card:hover { border-color: #1e2130; }

        /* ── ERROR BOX ── */
        .error-box {
          background: rgba(248,113,113,0.06); border: 1px solid rgba(248,113,113,0.2);
          border-radius: 12px; padding: 14px 18px; color: #f87171;
          font-size: 13px; margin-bottom: 24px;
          display: flex; align-items: center; gap: 8px;
        }

        /* ── INPUT ── */
        input:focus, select:focus { border-color: #7c3aed !important; outline: none; }
      `}</style>

      <div className="dashboard-root">
        {/* ── SIDEBAR ── */}
        <aside className="sidebar">
          <div className="sidebar-logo">
            <div className="logo-mark">⬡</div>
            <div className="logo-text">Control Center</div>
            <div className="logo-sub">Super Admin</div>
          </div>

          <div style={{ marginBottom: 6 }}>
            <div className="nav-section-label">Navigation</div>
            {[
              { id: "overview",   label: "Overview",    icon: "◈" },
              { id: "revenue",    label: "Revenue",     icon: "◎" },
              { id: "users",      label: "Users",       icon: "◉", count: m?.users?.total },
              { id: "workspaces", label: "Workspaces",  icon: "⬡", count: m?.workspaces?.total },
              { id: "feedback",   label: "Feedback",    icon: "◷", count: m?.feedback?.open },
            ].map(t => (
              <NavTab
                key={t.id}
                label={t.label}
                icon={t.icon}
                active={tab === t.id}
                onClick={() => setTab(t.id)}
                count={t.count}
              />
            ))}
          </div>

          <div className="sidebar-footer">
            <div className="admin-pill">
              <div className="admin-avatar">W</div>
              <div>
                <div style={{ fontSize: 12, fontWeight: 600, color: "#9ca3af" }}>Wahaj</div>
                <div style={{ fontSize: 10, color: "#374151", fontFamily: "'JetBrains Mono', monospace" }}>Super Admin</div>
              </div>
            </div>
          </div>
        </aside>

        {/* ── MAIN CONTENT ── */}
        <main className="main-content">
          {/* Topbar */}
          <div className="topbar">
            <div>
              <div className="topbar-title">
                {tab === "overview"   && "Platform Overview"}
                {tab === "revenue"    && "Revenue Analytics"}
                {tab === "users"      && "User Management"}
                {tab === "workspaces" && "Workspace Directory"}
                {tab === "feedback"   && "Feedback & Reports"}
              </div>
              <div className="topbar-date">{dateStr} · {timeStr}
                {m && <span style={{ marginLeft: 8, color: "#1e2130" }}>· synced {new Date(m.generated_at).toLocaleTimeString()}</span>}
              </div>
            </div>
            <button onClick={refetch} className="refresh-btn">
              <span style={{ fontSize: 14, lineHeight: 1 }}>↻</span> Refresh
            </button>
          </div>

          {/* Content */}
          <div className="content-area" key={tab}>
            {error && (
              <div className="error-box">
                <span>⚠</span> Failed to load metrics: {error}
              </div>
            )}

            {/* ── OVERVIEW TAB ── */}
            {tab === "overview" && (
              <div>
                {loading ? <Loader /> : m && (
                  <>
                    <div className="section-heading">Key Metrics</div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(190px, 1fr))", gap: 12, marginBottom: 24 }}>
                      <MetricCard label="Total Users" value={m.users.total} icon="◉"
                        sub={`+${m.users.new_this_week} this week`} color="#c084fc"
                        spark={m.signup_trend.map(d => d.signups)} />
                      <MetricCard label="Paid Users" value={m.users.paid} icon="◎"
                        sub={`MRR $${m.revenue.mrr}`} color="#34d399" />
                      <MetricCard label="Trialing" value={m.users.trialing} icon="◷"
                        sub={`${m.users.trial_expired} expired`} color="#fbbf24" />
                      <MetricCard label="Cancelled" value={m.users.cancelled} icon="⊗"
                        sub="subscriptions" color="#f87171" />
                      <MetricCard label="Workspaces" value={m.workspaces.total} icon="⬡"
                        sub={`${m.workspaces.active} active`} color="#818cf8" />
                      <MetricCard label="Total Tasks" value={m.tasks.total} icon="✦"
                        sub={`${m.tasks.completion_rate}% completed`} color="#34d399" />
                      <MetricCard label="Critical Open" value={m.tasks.critical_open} icon="⚡"
                        sub="high priority tasks" color="#f87171" />
                      <MetricCard label="Open Issues" value={m.feedback.open} icon="◈"
                        sub={`of ${m.feedback.total} total`} color="#fbbf24" />
                    </div>

                    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 24 }}>
                      <div className="glass-panel">
                        <div className="panel-title">Signup Trend — Last 30 Days</div>
                        <SignupTrend data={m.signup_trend} />
                        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 10, fontSize: 10, color: "#374151", fontFamily: "'JetBrains Mono', monospace" }}>
                          <span>{m.signup_trend[0]?.date}</span>
                          <span>Today</span>
                        </div>
                      </div>

                      <div className="glass-panel">
                        <div className="panel-title">Subscription Split</div>
                        {[
                          { label: "Paid",      count: m.users.paid,      color: "#34d399", total: m.users.total },
                          { label: "Trialing",  count: m.users.trialing,  color: "#fbbf24", total: m.users.total },
                          { label: "Cancelled", count: m.users.cancelled, color: "#f87171", total: m.users.total },
                          { label: "Exempt",    count: m.users.exempt,    color: "#c084fc", total: m.users.total },
                        ].map(({ label, count, color, total }) => {
                          const pct = total ? Math.round((count / total) * 100) : 0;
                          return (
                            <div key={label} style={{ marginBottom: 14 }}>
                              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                                <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                                  <div style={{ width: 6, height: 6, borderRadius: "50%", background: color, boxShadow: `0 0 6px ${color}` }} />
                                  <span style={{ fontSize: 12, color: "#6b7280" }}>{label}</span>
                                </div>
                                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                  <span style={{ fontSize: 10, color: "#374151", fontFamily: "'JetBrains Mono', monospace" }}>{pct}%</span>
                                  <span style={{ fontSize: 13, color, fontWeight: 700, minWidth: 28, textAlign: "right" }}>{count}</span>
                                </div>
                              </div>
                              <div style={{ height: 3, background: "#131520", borderRadius: 4, overflow: "hidden" }}>
                                <div style={{
                                  height: "100%", width: `${pct}%`,
                                  background: `linear-gradient(90deg, ${color}80, ${color})`,
                                  borderRadius: 4, transition: "width 0.6s cubic-bezier(0.4,0,0.2,1)",
                                }} />
                              </div>
                            </div>
                          );
                        })}

                        <div style={{ marginTop: 18, paddingTop: 16, borderTop: "1px solid #131520" }}>
                          <div className="panel-title" style={{ marginBottom: 12 }}>Users by Role</div>
                          {Object.entries(m.users.by_role).map(([role, count]) => (
                            <div key={role} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                              <span style={{ fontSize: 12, color: "#4b5563", textTransform: "capitalize" }}>{role}</span>
                              <span style={{ fontSize: 13, color: "#9ca3af", fontWeight: 600, fontFamily: "'JetBrains Mono', monospace" }}>{count}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>

                    <div className="stat-row">
                      {[
                        { label: "New This Week",    value: m.users.new_this_week,                color: "#c084fc" },
                        { label: "New This Month",   value: m.users.new_this_month,               color: "#c084fc" },
                        { label: "Tasks Today",      value: m.tasks.created_today,                color: "#34d399" },
                        { label: "Completion Rate",  value: `${m.tasks.completion_rate}%`,        color: "#34d399" },
                        { label: "MRR",              value: `$${m.revenue.mrr}`,                  color: "#fbbf24" },
                        { label: "QRR",              value: `$${m.revenue.qrr}`,                  color: "#fbbf24" },
                        { label: "ARR",              value: `$${m.revenue.arr.toLocaleString()}`, color: "#fbbf24" },
                      ].map(({ label, value, color }) => (
                        <div key={label} className="stat-item">
                          <div className="stat-label">{label}</div>
                          <div className="stat-val" style={{ color }}>{value}</div>
                        </div>
                      ))}
                    </div>
                  </>
                )}
              </div>
            )}

            {/* ── REVENUE TAB ── */}
            {tab === "revenue" && (
              <div>
                {loading ? <Loader /> : m && (
                  <>
                    <div className="section-heading">Revenue Summary</div>
                    <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, marginBottom: 24 }}>
                      <MetricCard label="MRR" value={`$${m.revenue.mrr}`} icon="◎" color="#34d399" sub={`${m.users.paid} paid users`} />
                      <MetricCard label="ARR" value={`$${m.revenue.arr.toLocaleString()}`} icon="↑" color="#c084fc" sub="annualized" />
                      <MetricCard label="QRR" value={`$${m.revenue.qrr}`} icon="◈" color="#fbbf24" sub="this quarter" />
                      <MetricCard label="Plan Price" value={`$${m.revenue.plan_price}/mo`} icon="✦" color="#818cf8" sub="per user" />
                    </div>

                    <div className="glass-panel" style={{ marginBottom: 16 }}>
                      <div className="panel-title">Monthly Revenue — Last 12 Months</div>
                      <RevenueChart data={m.revenue.monthly_breakdown} />

                      <div style={{ marginTop: 28 }}>
                        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", padding: "6px 0 10px", borderBottom: "1px solid #131520" }}>
                          {["Month", "New Paid", "Revenue"].map(h => (
                            <div key={h} style={{ fontSize: 9, color: "#374151", textTransform: "uppercase", letterSpacing: "0.1em", fontFamily: "'JetBrains Mono', monospace" }}>{h}</div>
                          ))}
                        </div>
                        {[...m.revenue.monthly_breakdown].reverse().slice(0, 8).map((d, i) => (
                          <div key={i} style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", padding: "10px 0", borderBottom: "1px solid #0a0b11", fontSize: 13 }}>
                            <span style={{ color: "#6b7280" }}>{d.month}</span>
                            <span style={{ color: "#4b5563", fontFamily: "'JetBrains Mono', monospace" }}>{d.new_paid}</span>
                            <span style={{
                              color: d.revenue > 0 ? "#34d399" : "#374151",
                              fontWeight: 600, fontFamily: "'JetBrains Mono', monospace",
                            }}>${d.revenue.toFixed(2)}</span>
                          </div>
                        ))}
                      </div>

                      <div style={{ marginTop: 16, padding: "12px 14px", background: "#080a10", borderRadius: 10, fontSize: 11, color: "#374151", fontFamily: "'JetBrains Mono', monospace", lineHeight: 1.6 }}>
                        ℹ Revenue at ${m.revenue.plan_price}/user/month. Set PLAN_PRICE_USD env var. Connect Lemon Squeezy webhook for real payment data.
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}

            {/* ── USERS TAB ── */}
            {tab === "users" && (
              <div>
                <div className="section-heading">User Management</div>
                <div className="glass-panel">
                  <UsersTable />
                </div>
              </div>
            )}

            {/* ── WORKSPACES TAB ── */}
            {tab === "workspaces" && (
              <div>
                <div className="section-heading">Workspace Directory</div>
                <div className="glass-panel">
                  <WorkspacesTable />
                </div>
              </div>
            )}

            {/* ── FEEDBACK TAB ── */}
            {tab === "feedback" && (
              <div>
                <div className="section-heading">Feedback & Bug Reports</div>
                <FeedbackTable />
              </div>
            )}
          </div>
        </main>
      </div>
    </div>
  );
}
