import { useState, useEffect, useCallback } from "react";

const API = import.meta.env.VITE_API_URL || "";

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

// ── Tiny sparkline ─────────────────────────────────────────────────────────────
function Sparkline({ values, color = "#7c6fff" }) {
  if (!values || values.length < 2) return null;
  const max = Math.max(...values, 1);
  const min = Math.min(...values);
  const range = max - min || 1;
  const w = 120, h = 36;
  const pts = values.map((v, i) => {
    const x = (i / (values.length - 1)) * w;
    const y = h - ((v - min) / range) * (h - 4) - 2;
    return `${x},${y}`;
  });
  return (
    <svg width={w} height={h} style={{ display: "block" }}>
      <polyline
        points={pts.join(" ")}
        fill="none"
        stroke={color}
        strokeWidth="2"
        strokeLinejoin="round"
        strokeLinecap="round"
      />
      <polyline
        points={`0,${h} ${pts.join(" ")} ${w},${h}`}
        fill={color}
        fillOpacity="0.12"
        stroke="none"
      />
    </svg>
  );
}

// ── Metric card ────────────────────────────────────────────────────────────────
function MetricCard({ label, value, sub, color = "#7c6fff", spark, icon }) {
  return (
    <div style={{
      background: "#111318",
      border: "1px solid #1e2028",
      borderRadius: 12,
      padding: "20px 22px 16px",
      display: "flex",
      flexDirection: "column",
      gap: 4,
      position: "relative",
      overflow: "hidden",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <span style={{ fontSize: 12, color: "#6b7280", fontFamily: "monospace", letterSpacing: "0.06em", textTransform: "uppercase" }}>{label}</span>
        {icon && <span style={{ fontSize: 18 }}>{icon}</span>}
      </div>
      <div style={{ fontSize: 32, fontWeight: 700, color: "#f1f5f9", fontVariantNumeric: "tabular-nums", lineHeight: 1.1 }}>{value}</div>
      {sub && <div style={{ fontSize: 12, color: "#6b7280" }}>{sub}</div>}
      {spark && (
        <div style={{ marginTop: 8 }}>
          <Sparkline values={spark} color={color} />
        </div>
      )}
      <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 2, background: color, opacity: 0.4, borderRadius: "0 0 12px 12px" }} />
    </div>
  );
}

// ── Revenue bar chart ──────────────────────────────────────────────────────────
function RevenueChart({ data }) {
  if (!data || !data.length) return null;
  const max = Math.max(...data.map(d => d.revenue), 1);
  return (
    <div style={{ overflowX: "auto" }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 6, height: 120, minWidth: data.length * 48, padding: "0 4px" }}>
        {data.map((d, i) => (
          <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
            <div style={{ fontSize: 9, color: "#6b7280", fontVariantNumeric: "tabular-nums" }}>
              {d.revenue > 0 ? `$${d.revenue}` : ""}
            </div>
            <div style={{
              width: "100%",
              height: Math.max(4, (d.revenue / max) * 88),
              background: d.revenue > 0 ? "linear-gradient(180deg, #7c6fff, #4f46e5)" : "#1e2028",
              borderRadius: "4px 4px 0 0",
              transition: "height 0.4s ease",
            }} />
            <div style={{ fontSize: 8, color: "#4b5563", textAlign: "center", lineHeight: 1.2, maxWidth: 36, overflow: "hidden" }}>
              {d.month.split(" ")[0]}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Signup trend ──────────────────────────────────────────────────────────────
function SignupTrend({ data }) {
  if (!data || !data.length) return null;
  const max = Math.max(...data.map(d => d.signups), 1);
  const w = 100, h = 60;
  const pts = data.map((d, i) => {
    const x = (i / (data.length - 1)) * w;
    const y = h - (d.signups / max) * (h - 4) - 2;
    return `${x},${y}`;
  });
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ height: 60 }}>
      <defs>
        <linearGradient id="sg" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#10b981" stopOpacity="0.3" />
          <stop offset="100%" stopColor="#10b981" stopOpacity="0" />
        </linearGradient>
      </defs>
      <polyline points={`0,${h} ${pts.join(" ")} ${w},${h}`} fill="url(#sg)" stroke="none" />
      <polyline points={pts.join(" ")} fill="none" stroke="#10b981" strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

// ── Status badge ──────────────────────────────────────────────────────────────
function Badge({ text }) {
  const colors = {
    active:    { bg: "#052e16", color: "#4ade80" },
    trialing:  { bg: "#1c1917", color: "#fbbf24" },
    cancelled: { bg: "#1f0000", color: "#f87171" },
    exempt:    { bg: "#1e1b4b", color: "#a5b4fc" },
    paid:      { bg: "#052e16", color: "#4ade80" },
  };
  const style = colors[text?.toLowerCase()] || { bg: "#1e2028", color: "#9ca3af" };
  return (
    <span style={{
      background: style.bg,
      color: style.color,
      padding: "2px 8px",
      borderRadius: 20,
      fontSize: 11,
      fontFamily: "monospace",
      fontWeight: 600,
    }}>{text}</span>
  );
}

// ── Tab button ────────────────────────────────────────────────────────────────
function Tab({ label, active, onClick, count }) {
  return (
    <button onClick={onClick} style={{
      background: active ? "#1e2028" : "transparent",
      border: active ? "1px solid #2d2f3a" : "1px solid transparent",
      borderRadius: 8,
      padding: "6px 14px",
      color: active ? "#f1f5f9" : "#6b7280",
      fontSize: 13,
      fontWeight: active ? 600 : 400,
      cursor: "pointer",
      display: "flex",
      alignItems: "center",
      gap: 6,
      transition: "all 0.15s",
    }}>
      {label}
      {count !== undefined && (
        <span style={{
          background: active ? "#7c6fff" : "#1e2028",
          color: active ? "#fff" : "#6b7280",
          borderRadius: 10,
          padding: "0 6px",
          fontSize: 10,
          fontWeight: 700,
        }}>{count}</span>
      )}
    </button>
  );
}

// ── Users table ───────────────────────────────────────────────────────────────
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
      <div style={{ display: "flex", gap: 10, marginBottom: 16 }}>
        <input
          value={search}
          onChange={e => setSearch(e.target.value)}
          placeholder="Search name or email…"
          style={inputStyle}
        />
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} style={inputStyle}>
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
                {["ID", "Name", "Email", "Role", "Status", "Workspace", "Trial ends", "Joined", ""].map(h => (
                  <th key={h} style={{ padding: "8px 12px", textAlign: "left", color: "#4b5563", fontWeight: 500, borderBottom: "1px solid #1e2028", whiteSpace: "nowrap" }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data?.users?.map(u => (
                <tr key={u.id} style={{ borderBottom: "1px solid #0f1117" }}>
                  <td style={td}>{u.id}</td>
                  <td style={{ ...td, fontWeight: 500, color: "#e2e8f0" }}>{u.name}</td>
                  <td style={{ ...td, fontFamily: "monospace", color: "#9ca3af" }}>{u.email}</td>
                  <td style={td}><Badge text={u.role} /></td>
                  <td style={td}><Badge text={u.subscription_status} /></td>
                  <td style={{ ...td, color: "#6b7280" }}>{u.workspace_id ?? "—"}</td>
                  <td style={{ ...td, color: u.trial_expired ? "#f87171" : "#6b7280" }}>
                    {u.trial_ends_at ? new Date(u.trial_ends_at).toLocaleDateString() : "—"}
                    {u.trial_expired && <span style={{ marginLeft: 4, color: "#f87171" }}>⚠</span>}
                  </td>
                  <td style={{ ...td, color: "#6b7280" }}>
                    {u.created_at ? new Date(u.created_at).toLocaleDateString() : "—"}
                  </td>
                  <td style={td}>
                    <button
                      onClick={() => handleToggleActive(u.id, u.is_active)}
                      style={{
                        background: u.is_active ? "#052e16" : "#1f0000",
                        color: u.is_active ? "#4ade80" : "#f87171",
                        border: "none",
                        borderRadius: 6,
                        padding: "3px 8px",
                        fontSize: 11,
                        cursor: "pointer",
                        fontWeight: 600,
                      }}
                    >
                      {u.is_active ? "Active" : "Disabled"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div style={{ marginTop: 10, color: "#4b5563", fontSize: 12 }}>
            {data?.total} total users
          </div>
        </div>
      )}
    </div>
  );
}

// ── Workspaces table ──────────────────────────────────────────────────────────
function WorkspacesTable() {
  const { data, loading } = useAdminFetch("/admin/workspaces?limit=100");
  if (loading) return <Loader />;
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead>
          <tr>
            {["ID", "Name", "Owner", "Members", "Tasks", "Created"].map(h => (
              <th key={h} style={{ padding: "8px 12px", textAlign: "left", color: "#4b5563", fontWeight: 500, borderBottom: "1px solid #1e2028" }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data?.workspaces?.map(ws => (
            <tr key={ws.id} style={{ borderBottom: "1px solid #0f1117" }}>
              <td style={td}>{ws.id}</td>
              <td style={{ ...td, fontWeight: 500, color: "#e2e8f0" }}>{ws.name}</td>
              <td style={{ ...td, fontFamily: "monospace", color: "#9ca3af" }}>{ws.owner_email ?? "—"}</td>
              <td style={{ ...td, color: "#7c6fff" }}>{ws.member_count}</td>
              <td style={{ ...td, color: "#10b981" }}>{ws.task_count}</td>
              <td style={{ ...td, color: "#6b7280" }}>{ws.created_at ? new Date(ws.created_at).toLocaleDateString() : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ marginTop: 10, color: "#4b5563", fontSize: 12 }}>{data?.total} workspaces</div>
    </div>
  );
}

// ── Feedback table ────────────────────────────────────────────────────────────
function FeedbackTable() {
  const { data, loading } = useAdminFetch("/admin/feedback?limit=100");
  if (loading) return <Loader />;
  const typeColor = { bug: "#f87171", feedback: "#7c6fff", feature_request: "#10b981" };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {data?.items?.map(f => (
        <div key={f.id} style={{ background: "#111318", border: "1px solid #1e2028", borderRadius: 10, padding: "14px 16px" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <span style={{ background: typeColor[f.type] + "22", color: typeColor[f.type], padding: "2px 8px", borderRadius: 10, fontSize: 10, fontWeight: 700, textTransform: "uppercase" }}>{f.type.replace("_", " ")}</span>
              <span style={{ color: "#e2e8f0", fontWeight: 600, fontSize: 13 }}>{f.title}</span>
            </div>
            <Badge text={f.status} />
          </div>
          <div style={{ color: "#6b7280", fontSize: 12, marginBottom: 6 }}>{f.message}</div>
          <div style={{ display: "flex", gap: 12, fontSize: 11, color: "#4b5563" }}>
            <span>👤 {f.user_name ?? "Anonymous"} ({f.user_email ?? "—"})</span>
            {f.page_context && <span>📍 {f.page_context}</span>}
            <span>🕐 {f.created_at ? new Date(f.created_at).toLocaleString() : "—"}</span>
          </div>
        </div>
      ))}
      {!data?.items?.length && <div style={{ color: "#4b5563", textAlign: "center", padding: 40 }}>No feedback yet</div>}
    </div>
  );
}

// ── Loader ────────────────────────────────────────────────────────────────────
function Loader() {
  return (
    <div style={{ display: "flex", justifyContent: "center", padding: 40 }}>
      <div style={{ width: 24, height: 24, border: "2px solid #1e2028", borderTop: "2px solid #7c6fff", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />
    </div>
  );
}

const inputStyle = {
  background: "#111318",
  border: "1px solid #1e2028",
  borderRadius: 8,
  padding: "7px 12px",
  color: "#e2e8f0",
  fontSize: 13,
  outline: "none",
  flex: 1,
};

const td = {
  padding: "10px 12px",
  color: "#9ca3af",
  whiteSpace: "nowrap",
};

// ── Main dashboard ─────────────────────────────────────────────────────────────
export default function AdminDashboard() {
  const [tab, setTab] = useState("overview");
  const { data: metrics, loading, error, refetch } = useAdminFetch("/admin/metrics");

  const m = metrics;

  return (
    <div style={{
      minHeight: "100vh",
      background: "#0a0b0f",
      color: "#f1f5f9",
      fontFamily: "'DM Mono', 'Fira Code', 'Courier New', monospace",
      padding: "32px 40px",
    }}>
      <style>{`
        @keyframes spin { to { transform: rotate(360deg); } }
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: #0a0b0f; }
        ::-webkit-scrollbar-thumb { background: #1e2028; border-radius: 4px; }
      `}</style>

      {/* Header */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 32 }}>
        <div>
          <div style={{ fontSize: 11, color: "#4b5563", letterSpacing: "0.12em", textTransform: "uppercase", marginBottom: 4 }}>
            SUPER ADMIN
          </div>
          <h1 style={{ fontSize: 24, fontWeight: 700, margin: 0, color: "#f1f5f9", letterSpacing: "-0.02em" }}>
            Platform Control Center
          </h1>
          {m && (
            <div style={{ fontSize: 11, color: "#4b5563", marginTop: 4 }}>
              Last updated {new Date(m.generated_at).toLocaleTimeString()}
            </div>
          )}
        </div>
        <button onClick={refetch} style={{
          background: "#111318",
          border: "1px solid #1e2028",
          borderRadius: 8,
          padding: "8px 16px",
          color: "#7c6fff",
          fontSize: 12,
          cursor: "pointer",
          fontFamily: "inherit",
        }}>↻ Refresh</button>
      </div>

      {/* Tabs */}
      <div style={{ display: "flex", gap: 6, marginBottom: 28, flexWrap: "wrap" }}>
        <Tab label="Overview" active={tab === "overview"} onClick={() => setTab("overview")} />
        <Tab label="Revenue" active={tab === "revenue"} onClick={() => setTab("revenue")} />
        <Tab label="Users" active={tab === "users"} onClick={() => setTab("users")} count={m?.users?.total} />
        <Tab label="Workspaces" active={tab === "workspaces"} onClick={() => setTab("workspaces")} count={m?.workspaces?.total} />
        <Tab label="Feedback" active={tab === "feedback"} onClick={() => setTab("feedback")} count={m?.feedback?.open} />
      </div>

      {error && (
        <div style={{ background: "#1f0000", border: "1px solid #7f1d1d", borderRadius: 10, padding: 16, color: "#f87171", marginBottom: 24 }}>
          ⚠ Failed to load metrics: {error}
        </div>
      )}

      {/* ── OVERVIEW TAB ── */}
      {tab === "overview" && (
        <div>
          {loading ? <Loader /> : m && (
            <>
              {/* Top KPI row */}
              <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))", gap: 14, marginBottom: 14 }}>
                <MetricCard label="Total Users" value={m.users.total} icon="👥"
                  sub={`+${m.users.new_this_week} this week`} color="#7c6fff"
                  spark={m.signup_trend.map(d => d.signups)} />
                <MetricCard label="Paid Users" value={m.users.paid} icon="💳"
                  sub={`MRR $${m.revenue.mrr}`} color="#10b981" />
                <MetricCard label="Trialing" value={m.users.trialing} icon="⏳"
                  sub={`${m.users.trial_expired} expired`} color="#fbbf24" />
                <MetricCard label="Cancelled" value={m.users.cancelled} icon="❌"
                  sub="subscriptions" color="#f87171" />
                <MetricCard label="Workspaces" value={m.workspaces.total} icon="🏢"
                  sub={`${m.workspaces.active} active`} color="#7c6fff" />
                <MetricCard label="Total Tasks" value={m.tasks.total} icon="✅"
                  sub={`${m.tasks.completion_rate}% completed`} color="#10b981" />
                <MetricCard label="Critical Open" value={m.tasks.critical_open} icon="🔥"
                  sub="high priority tasks" color="#f87171" />
                <MetricCard label="Open Issues" value={m.feedback.open} icon="🐛"
                  sub={`of ${m.feedback.total} feedback`} color="#fbbf24" />
              </div>

              {/* Signup trend */}
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, marginBottom: 14 }}>
                <div style={{ background: "#111318", border: "1px solid #1e2028", borderRadius: 12, padding: "20px 22px" }}>
                  <div style={{ fontSize: 11, color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 12 }}>Signup trend — last 30 days</div>
                  <SignupTrend data={m.signup_trend} />
                  <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8, fontSize: 11, color: "#4b5563" }}>
                    <span>{m.signup_trend[0]?.date}</span>
                    <span>Today</span>
                  </div>
                </div>

                {/* User breakdown */}
                <div style={{ background: "#111318", border: "1px solid #1e2028", borderRadius: 12, padding: "20px 22px" }}>
                  <div style={{ fontSize: 11, color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 16 }}>Users by role</div>
                  {Object.entries(m.users.by_role).map(([role, count]) => (
                    <div key={role} style={{ display: "flex", justifyContent: "space-between", marginBottom: 10, alignItems: "center" }}>
                      <span style={{ fontSize: 13, color: "#9ca3af", textTransform: "capitalize" }}>{role}</span>
                      <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                        <div style={{ width: 80, height: 4, background: "#1e2028", borderRadius: 4 }}>
                          <div style={{
                            width: `${m.users.total ? (count / m.users.total * 100) : 0}%`,
                            height: "100%",
                            background: "#7c6fff",
                            borderRadius: 4,
                          }} />
                        </div>
                        <span style={{ fontSize: 13, color: "#e2e8f0", fontWeight: 600, minWidth: 24, textAlign: "right" }}>{count}</span>
                      </div>
                    </div>
                  ))}

                  <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px solid #1e2028" }}>
                    <div style={{ fontSize: 11, color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 10 }}>Subscription split</div>
                    {[
                      { label: "Paid", count: m.users.paid, color: "#10b981" },
                      { label: "Trialing", count: m.users.trialing, color: "#fbbf24" },
                      { label: "Cancelled", count: m.users.cancelled, color: "#f87171" },
                      { label: "Exempt", count: m.users.exempt, color: "#7c6fff" },
                    ].map(({ label, count, color }) => (
                      <div key={label} style={{ display: "flex", justifyContent: "space-between", marginBottom: 8, alignItems: "center" }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                          <div style={{ width: 8, height: 8, borderRadius: "50%", background: color }} />
                          <span style={{ fontSize: 12, color: "#9ca3af" }}>{label}</span>
                        </div>
                        <span style={{ fontSize: 12, color, fontWeight: 600 }}>{count}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              {/* New users this month */}
              <div style={{ background: "#111318", border: "1px solid #1e2028", borderRadius: 12, padding: "16px 22px", display: "flex", gap: 32 }}>
                {[
                  { label: "New this week", value: m.users.new_this_week },
                  { label: "New this month", value: m.users.new_this_month },
                  { label: "Tasks today", value: m.tasks.created_today },
                  { label: "Completion rate", value: `${m.tasks.completion_rate}%` },
                  { label: "ARR", value: `$${m.revenue.arr.toLocaleString()}` },
                  { label: "MRR", value: `$${m.revenue.mrr}` },
                  { label: "QRR", value: `$${m.revenue.qrr}` },
                ].map(({ label, value }) => (
                  <div key={label}>
                    <div style={{ fontSize: 10, color: "#4b5563", textTransform: "uppercase", letterSpacing: "0.08em" }}>{label}</div>
                    <div style={{ fontSize: 20, fontWeight: 700, color: "#f1f5f9" }}>{value}</div>
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
              <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14, marginBottom: 24 }}>
                <MetricCard label="MRR" value={`$${m.revenue.mrr}`} icon="💰" color="#10b981" sub={`${m.users.paid} paid users`} />
                <MetricCard label="ARR" value={`$${m.revenue.arr.toLocaleString()}`} icon="📈" color="#7c6fff" sub="annualized" />
                <MetricCard label="QRR" value={`$${m.revenue.qrr}`} icon="📊" color="#fbbf24" sub="this quarter" />
                <MetricCard label="Plan price" value={`$${m.revenue.plan_price}/mo`} icon="🏷️" color="#9ca3af" sub="per user" />
              </div>

              <div style={{ background: "#111318", border: "1px solid #1e2028", borderRadius: 12, padding: "24px" }}>
                <div style={{ fontSize: 11, color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 20 }}>
                  Monthly revenue — last 12 months
                </div>
                <RevenueChart data={m.revenue.monthly_breakdown} />

                <div style={{ marginTop: 24, display: "flex", flexDirection: "column", gap: 8 }}>
                  {[...m.revenue.monthly_breakdown].reverse().slice(0, 6).map((d, i) => (
                    <div key={i} style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: "1px solid #0f1117", fontSize: 13 }}>
                      <span style={{ color: "#9ca3af" }}>{d.month}</span>
                      <span style={{ color: "#4b5563" }}>{d.new_paid} new paid</span>
                      <span style={{ color: d.revenue > 0 ? "#10b981" : "#4b5563", fontWeight: 600, fontVariantNumeric: "tabular-nums" }}>
                        ${d.revenue.toFixed(2)}
                      </span>
                    </div>
                  ))}
                </div>

                <div style={{ marginTop: 16, padding: 12, background: "#0a0b0f", borderRadius: 8, fontSize: 11, color: "#4b5563" }}>
                  ℹ Revenue calculated at ${m.revenue.plan_price}/user/month. Set PLAN_PRICE_USD env var to match your actual price. Connect Lemon Squeezy webhook for real payment data.
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {/* ── USERS TAB ── */}
      {tab === "users" && (
        <div style={{ background: "#111318", border: "1px solid #1e2028", borderRadius: 12, padding: 24 }}>
          <UsersTable />
        </div>
      )}

      {/* ── WORKSPACES TAB ── */}
      {tab === "workspaces" && (
        <div style={{ background: "#111318", border: "1px solid #1e2028", borderRadius: 12, padding: 24 }}>
          <WorkspacesTable />
        </div>
      )}

      {/* ── FEEDBACK TAB ── */}
      {tab === "feedback" && (
        <div>
          <FeedbackTable />
        </div>
      )}
    </div>
  );
}
