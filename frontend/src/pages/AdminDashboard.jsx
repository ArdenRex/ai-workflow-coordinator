import { useState, useEffect, useCallback, useRef } from "react";

const API = process.env.REACT_APP_API_URL || "https://ai-workflow-coordinator-api-production.up.railway.app";

// ── Data Hook ──────────────────────────────────────────────────────────────────
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

// ── Floating Particles Canvas ──────────────────────────────────────────────────
function ParticleField() {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    let W = canvas.width = canvas.offsetWidth;
    let H = canvas.height = canvas.offsetHeight;
    const particles = Array.from({ length: 90 }, () => ({
      x: Math.random() * W, y: Math.random() * H,
      r: Math.random() * 1.5 + 0.3,
      vx: (Math.random() - 0.5) * 0.18,
      vy: (Math.random() - 0.5) * 0.18,
      opacity: Math.random() * 0.6 + 0.1,
      color: Math.random() > 0.6
        ? `rgba(${140 + Math.random() * 60},${80 + Math.random() * 40},${220 + Math.random() * 35},`
        : Math.random() > 0.5
        ? `rgba(${30 + Math.random() * 20},${180 + Math.random() * 60},${200 + Math.random() * 55},`
        : `rgba(${200 + Math.random() * 55},${150 + Math.random() * 50},${80 + Math.random() * 40},`,
    }));
    let raf;
    function draw() {
      ctx.clearRect(0, 0, W, H);
      particles.forEach(p => {
        p.x += p.vx; p.y += p.vy;
        if (p.x < 0) p.x = W; if (p.x > W) p.x = 0;
        if (p.y < 0) p.y = H; if (p.y > H) p.y = 0;
        ctx.beginPath();
        ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2);
        ctx.fillStyle = p.color + p.opacity + ")";
        ctx.fill();
      });
      raf = requestAnimationFrame(draw);
    }
    draw();
    const onResize = () => { W = canvas.width = canvas.offsetWidth; H = canvas.height = canvas.offsetHeight; };
    window.addEventListener("resize", onResize);
    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", onResize); };
  }, []);
  return (
    <canvas ref={canvasRef} style={{
      position: "fixed", inset: 0, width: "100%", height: "100%",
      pointerEvents: "none", zIndex: 0,
    }} />
  );
}

// ── Sparkline ──────────────────────────────────────────────────────────────────
function Sparkline({ values, color = "#a855f7" }) {
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
  const gradId = `sg-${color.replace(/[^a-z0-9]/gi, "")}`;
  return (
    <svg width="100%" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" style={{ height: 32 }}>
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.4" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <polyline points={`0,${h} ${pts.join(" ")} ${w},${h}`} fill={`url(#${gradId})`} stroke="none" />
      <polyline points={pts.join(" ")} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

// ── Metric Card ────────────────────────────────────────────────────────────────
function MetricCard({ label, value, sub, color = "#a855f7", spark, icon, trend }) {
  const [hovered, setHovered] = useState(false);
  return (
    <div
      className="metric-card"
      style={{ "--card-accent": color }}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <div className="metric-card-aurora" style={{ background: `radial-gradient(ellipse at top right, ${color}22 0%, transparent 70%)`, opacity: hovered ? 1 : 0.5 }} />
      <div className="metric-card-border-glow" style={{ boxShadow: hovered ? `0 0 20px ${color}30, inset 0 0 20px ${color}08` : "none" }} />
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12, position: "relative", zIndex: 1 }}>
        <span className="metric-label">{label}</span>
        <span className="metric-icon" style={{ color, filter: `drop-shadow(0 0 6px ${color})` }}>{icon}</span>
      </div>
      <div className="metric-value" style={{ position: "relative", zIndex: 1 }}>{value}</div>
      {sub && <div className="metric-sub" style={{ position: "relative", zIndex: 1 }}>{sub}</div>}
      {trend !== undefined && (
        <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 4, position: "relative", zIndex: 1 }}>
          <span style={{ fontSize: 11, color: trend >= 0 ? "#4ade80" : "#f87171", fontWeight: 600 }}>
            {trend >= 0 ? "↑" : "↓"} {Math.abs(trend)}%
          </span>
          <span style={{ fontSize: 10, color: "rgba(148,163,184,0.4)" }}>vs last month</span>
        </div>
      )}
      {spark && (
        <div style={{ marginTop: 12, position: "relative", zIndex: 1 }}>
          <Sparkline values={spark} color={color} />
        </div>
      )}
      <div className="metric-card-bar" style={{ background: `linear-gradient(90deg, transparent, ${color}, transparent)` }} />
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
                  fontSize: 10, color: "#e2d9f3", background: "rgba(10,8,20,0.95)",
                  border: "1px solid rgba(168,85,247,0.4)", borderRadius: 6,
                  padding: "3px 7px", whiteSpace: "nowrap",
                  boxShadow: "0 4px 20px rgba(168,85,247,0.3)", marginBottom: 2,
                }}>${d.revenue.toFixed(0)}</div>
              )}
              {!isHov && <div style={{ height: 22 }} />}
              <div style={{
                width: "100%", height: h,
                background: d.revenue > 0
                  ? isHov
                    ? "linear-gradient(180deg, #e879f9, #7c3aed)"
                    : "linear-gradient(180deg, rgba(168,85,247,0.9) 0%, rgba(109,40,217,0.6) 100%)"
                  : "rgba(20,15,40,0.5)",
                borderRadius: "5px 5px 0 0",
                transition: "all 0.25s cubic-bezier(0.4,0,0.2,1)",
                opacity: hovered !== null && !isHov ? 0.35 : 1,
                boxShadow: isHov ? "0 0 24px rgba(168,85,247,0.5), 0 -4px 20px rgba(168,85,247,0.3)" : d.revenue > 0 ? "0 0 8px rgba(168,85,247,0.15)" : "none",
              }} />
              <div style={{ fontSize: 9, color: isHov ? "#a855f7" : "rgba(148,163,184,0.35)", textAlign: "center", transition: "color 0.2s", fontWeight: isHov ? 700 : 400 }}>
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
    active:    { bg: "rgba(52,211,153,0.1)", color: "#34d399", border: "rgba(52,211,153,0.3)", glow: "rgba(52,211,153,0.2)" },
    trialing:  { bg: "rgba(251,191,36,0.1)", color: "#fbbf24", border: "rgba(251,191,36,0.3)", glow: "rgba(251,191,36,0.2)" },
    cancelled: { bg: "rgba(248,113,113,0.1)", color: "#f87171", border: "rgba(248,113,113,0.3)", glow: "rgba(248,113,113,0.2)" },
    exempt:    { bg: "rgba(168,85,247,0.1)", color: "#a855f7", border: "rgba(168,85,247,0.3)", glow: "rgba(168,85,247,0.2)" },
    paid:      { bg: "rgba(52,211,153,0.1)", color: "#34d399", border: "rgba(52,211,153,0.3)", glow: "rgba(52,211,153,0.2)" },
    open:      { bg: "rgba(251,191,36,0.1)", color: "#fbbf24", border: "rgba(251,191,36,0.3)", glow: "rgba(251,191,36,0.2)" },
    resolved:  { bg: "rgba(52,211,153,0.1)", color: "#34d399", border: "rgba(52,211,153,0.3)", glow: "rgba(52,211,153,0.2)" },
    admin:     { bg: "rgba(168,85,247,0.1)", color: "#a855f7", border: "rgba(168,85,247,0.3)", glow: "rgba(168,85,247,0.2)" },
    member:    { bg: "rgba(148,163,184,0.08)", color: "#94a3b8", border: "rgba(148,163,184,0.2)", glow: "transparent" },
  };
  const s = map[text?.toLowerCase()] || { bg: "rgba(148,163,184,0.08)", color: "#94a3b8", border: "rgba(148,163,184,0.2)", glow: "transparent" };
  return (
    <span style={{
      background: s.bg, color: s.color,
      border: `1px solid ${s.border}`,
      padding: "2px 10px", borderRadius: 20,
      fontSize: 10.5, fontWeight: 600, letterSpacing: "0.05em",
      textTransform: "uppercase",
      boxShadow: `0 0 8px ${s.glow}`,
    }}>{text}</span>
  );
}

// ── Nav Tab ────────────────────────────────────────────────────────────────────
function NavTab({ label, active, onClick, count, icon }) {
  return (
    <button onClick={onClick} className={`nav-tab ${active ? "nav-tab-active" : ""}`}>
      <span className="nav-icon-wrap">{icon}</span>
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
      <div style={{ display: "flex", gap: 10, marginBottom: 22 }}>
        <div style={{ position: "relative", flex: 1 }}>
          <span style={{ position: "absolute", left: 13, top: "50%", transform: "translateY(-50%)", color: "rgba(168,85,247,0.5)", fontSize: 14 }}>⌕</span>
          <input
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Search by name or email…"
            className="arcane-input"
            style={{ paddingLeft: 34 }}
          />
        </div>
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)} className="arcane-input" style={{ flex: "0 0 180px" }}>
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
                    padding: "10px 14px", textAlign: "left",
                    color: "rgba(168,85,247,0.55)", fontWeight: 600, fontSize: 10,
                    textTransform: "uppercase", letterSpacing: "0.1em",
                    borderBottom: "1px solid rgba(168,85,247,0.1)", whiteSpace: "nowrap",
                    fontFamily: "'JetBrains Mono', monospace",
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data?.users?.map((u, idx) => (
                <tr key={u.id} className="arcane-table-row">
                  <td style={{ ...td, color: "rgba(148,163,184,0.35)", fontSize: 11 }}>{idx + 1}</td>
                  <td style={{ ...td, fontWeight: 600, color: "#e2d9f3" }}>{u.name}</td>
                  <td style={{ ...td, color: "rgba(148,163,184,0.55)", fontFamily: "'JetBrains Mono', monospace", fontSize: 12 }}>{u.email}</td>
                  <td style={td}><Badge text={u.role} /></td>
                  <td style={td}><Badge text={u.subscription_status} /></td>
                  <td style={{ ...td, color: "rgba(148,163,184,0.45)" }}>{u.workspace_id ?? "—"}</td>
                  <td style={{ ...td, color: u.trial_expired ? "#f87171" : "rgba(148,163,184,0.45)" }}>
                    {u.trial_ends_at ? new Date(u.trial_ends_at).toLocaleDateString() : "—"}
                    {u.trial_expired && <span style={{ marginLeft: 4, fontSize: 10, filter: "drop-shadow(0 0 4px #f87171)" }}>⚠</span>}
                  </td>
                  <td style={{ ...td, color: "rgba(148,163,184,0.45)" }}>
                    {u.created_at ? new Date(u.created_at).toLocaleDateString() : "—"}
                  </td>
                  <td style={td}>
                    {u.email === "wahaj@acedengroup.com" ? (
                      <span className="super-admin-badge">⬡ Super Admin</span>
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
          <div style={{ marginTop: 14, color: "rgba(148,163,184,0.4)", fontSize: 12, display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ color: "#a855f7", fontWeight: 700, filter: "drop-shadow(0 0 6px #a855f7)" }}>{data?.total}</span>
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
                padding: "10px 14px", textAlign: "left",
                color: "rgba(168,85,247,0.55)", fontWeight: 600, fontSize: 10,
                textTransform: "uppercase", letterSpacing: "0.1em",
                borderBottom: "1px solid rgba(168,85,247,0.1)", whiteSpace: "nowrap",
                fontFamily: "'JetBrains Mono', monospace",
              }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data?.workspaces?.map((ws, idx) => {
            const isActive = ws.is_active !== false;
            return (
              <tr key={ws.id} className="arcane-table-row">
                <td style={{ ...td, color: "rgba(148,163,184,0.35)", fontSize: 11 }}>{idx + 1}</td>
                <td style={{ ...td, fontWeight: 600, color: "#e2d9f3" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <div style={{
                      width: 30, height: 30, borderRadius: 8,
                      background: isActive
                        ? "linear-gradient(135deg, rgba(109,40,217,0.8), rgba(168,85,247,0.9))"
                        : "rgba(20,15,40,0.7)",
                      border: isActive ? "1px solid rgba(168,85,247,0.4)" : "1px solid rgba(168,85,247,0.1)",
                      display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: 11, fontWeight: 700, color: isActive ? "#fff" : "rgba(148,163,184,0.3)",
                      flexShrink: 0, transition: "all 0.3s",
                      boxShadow: isActive ? "0 0 12px rgba(168,85,247,0.3)" : "none",
                    }}>{ws.name?.[0]?.toUpperCase() || "W"}</div>
                    <span style={{ color: isActive ? "#e2d9f3" : "rgba(148,163,184,0.3)", transition: "color 0.2s" }}>{ws.name}</span>
                  </div>
                </td>
                <td style={{ ...td, color: "rgba(148,163,184,0.55)", fontFamily: "'JetBrains Mono', monospace", fontSize: 12 }}>{ws.owner_email ?? "—"}</td>
                <td style={td}><span style={{ color: "#a855f7", fontWeight: 700, filter: "drop-shadow(0 0 4px #a855f7)" }}>{ws.member_count}</span></td>
                <td style={td}><span style={{ color: "#34d399", fontWeight: 600, filter: "drop-shadow(0 0 4px rgba(52,211,153,0.5))" }}>{ws.task_count}</span></td>
                <td style={{ ...td, color: "rgba(148,163,184,0.45)" }}>{ws.created_at ? new Date(ws.created_at).toLocaleDateString() : "—"}</td>
                <td style={td}>
                  {ws.owner_email === "wahaj@acedengroup.com" ? (
                    <span className="super-admin-badge">⬡ Protected</span>
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
      <div style={{ marginTop: 14, color: "rgba(148,163,184,0.4)", fontSize: 12, display: "flex", alignItems: "center", gap: 6 }}>
        <span style={{ color: "#a855f7", fontWeight: 700, filter: "drop-shadow(0 0 6px #a855f7)" }}>{data?.total}</span>
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
    bug:             { bg: "rgba(248,113,113,0.08)", color: "#f87171", border: "rgba(248,113,113,0.3)", icon: "🐛" },
    feedback:        { bg: "rgba(168,85,247,0.08)", color: "#a855f7", border: "rgba(168,85,247,0.3)", icon: "💬" },
    feature_request: { bg: "rgba(52,211,153,0.08)", color: "#34d399", border: "rgba(52,211,153,0.3)", icon: "✦" },
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {data?.items?.map(f => {
        const ts = typeStyle[f.type] || { bg: "rgba(148,163,184,0.08)", color: "#94a3b8", border: "rgba(148,163,184,0.2)", icon: "•" };
        return (
          <div key={f.id} className="feedback-card">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 10, gap: 12 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                <span style={{
                  background: ts.bg, color: ts.color,
                  border: `1px solid ${ts.border}`,
                  padding: "2px 10px", borderRadius: 20, fontSize: 10, fontWeight: 700,
                  textTransform: "uppercase", letterSpacing: "0.06em",
                  display: "flex", alignItems: "center", gap: 4,
                  boxShadow: `0 0 10px ${ts.border}`,
                }}>
                  {ts.icon} {f.type.replace("_", " ")}
                </span>
                <span style={{ color: "#e2d9f3", fontWeight: 600, fontSize: 13 }}>{f.title}</span>
              </div>
              <Badge text={f.status} />
            </div>
            <p style={{ color: "rgba(148,163,184,0.6)", fontSize: 12.5, margin: "0 0 10px", lineHeight: 1.7 }}>{f.message}</p>
            <div style={{ display: "flex", gap: 16, fontSize: 11, color: "rgba(148,163,184,0.35)", flexWrap: "wrap" }}>
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <span style={{ color: "rgba(168,85,247,0.4)" }}>◎</span>
                <span style={{ color: "rgba(148,163,184,0.55)" }}>{f.user_name ?? "Anonymous"}</span>
                {f.user_email && <span>({f.user_email})</span>}
              </span>
              {f.page_context && (
                <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                  <span style={{ color: "rgba(52,211,153,0.4)" }}>⊕</span> {f.page_context}
                </span>
              )}
              <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
                <span style={{ color: "rgba(168,85,247,0.4)" }}>◷</span>
                {f.created_at ? new Date(f.created_at).toLocaleString() : "—"}
              </span>
            </div>
          </div>
        );
      })}
      {!data?.items?.length && (
        <div style={{ textAlign: "center", padding: 80, color: "rgba(148,163,184,0.25)" }}>
          <div style={{ fontSize: 40, marginBottom: 12, filter: "drop-shadow(0 0 20px rgba(168,85,247,0.4))" }}>✦</div>
          <div style={{ fontSize: 14, letterSpacing: "0.08em" }}>No feedback submissions yet</div>
        </div>
      )}
    </div>
  );
}

// ── Loader ─────────────────────────────────────────────────────────────────────
function Loader() {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: 80, gap: 20 }}>
      <div style={{ position: "relative", width: 48, height: 48 }}>
        <div style={{
          width: 48, height: 48,
          border: "1.5px solid rgba(168,85,247,0.1)",
          borderTop: "1.5px solid #a855f7",
          borderRight: "1.5px solid rgba(168,85,247,0.5)",
          borderRadius: "50%",
          animation: "spin 0.9s linear infinite",
          boxShadow: "0 0 20px rgba(168,85,247,0.2)",
        }} />
        <div style={{
          position: "absolute", top: 8, left: 8,
          width: 32, height: 32,
          border: "1px solid rgba(52,211,153,0.1)",
          borderTop: "1px solid rgba(52,211,153,0.5)",
          borderRadius: "50%",
          animation: "spin 0.6s linear infinite reverse",
        }} />
      </div>
      <span style={{ color: "rgba(168,85,247,0.5)", fontSize: 11, letterSpacing: "0.2em", textTransform: "uppercase", fontFamily: "'JetBrains Mono', monospace" }}>Channeling data…</span>
    </div>
  );
}

const td = {
  padding: "13px 14px",
  color: "rgba(148,163,184,0.6)",
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
    <div style={{ minHeight: "100vh", background: "#06040f", color: "#e2d9f3", position: "relative", overflow: "hidden" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;500;600;700&family=Syne:wght@400;500;600;700;800&family=JetBrains+Mono:wght@300;400;500;600&display=swap');

        * { box-sizing: border-box; margin: 0; padding: 0; }

        /* ── AMBIENT BACKGROUND ── */
        body { background: #06040f; }

        /* ─ Animated nebula bg ─ */
        .nebula-1 {
          position: fixed; width: 900px; height: 900px;
          top: -300px; left: -200px;
          background: radial-gradient(ellipse, rgba(88,28,135,0.18) 0%, rgba(109,40,217,0.06) 40%, transparent 70%);
          pointer-events: none; z-index: 0;
          animation: nebula-drift-1 25s ease-in-out infinite alternate;
        }
        .nebula-2 {
          position: fixed; width: 700px; height: 700px;
          bottom: -200px; right: -150px;
          background: radial-gradient(ellipse, rgba(6,95,70,0.15) 0%, rgba(5,150,105,0.06) 40%, transparent 70%);
          pointer-events: none; z-index: 0;
          animation: nebula-drift-2 30s ease-in-out infinite alternate;
        }
        .nebula-3 {
          position: fixed; width: 500px; height: 500px;
          top: 40%; right: 20%;
          background: radial-gradient(ellipse, rgba(30,10,80,0.12) 0%, transparent 70%);
          pointer-events: none; z-index: 0;
          animation: nebula-drift-1 20s ease-in-out infinite alternate-reverse;
        }
        .aurora-line {
          position: fixed; top: 0; left: 0; right: 0; height: 2px;
          background: linear-gradient(90deg, transparent 0%, rgba(88,28,135,0.4) 20%, rgba(168,85,247,0.8) 40%, rgba(52,211,153,0.6) 60%, rgba(88,28,135,0.4) 80%, transparent 100%);
          pointer-events: none; z-index: 20;
          animation: aurora-shift 8s ease-in-out infinite alternate;
          filter: blur(1px);
        }

        @keyframes nebula-drift-1 { from { transform: translate(0,0) scale(1); } to { transform: translate(40px, 30px) scale(1.08); } }
        @keyframes nebula-drift-2 { from { transform: translate(0,0) scale(1); } to { transform: translate(-30px, -20px) scale(1.05); } }
        @keyframes aurora-shift { from { background-position: 0% 0%; } to { background-position: 100% 0%; } }

        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes fadeUp {
          from { opacity: 0; transform: translateY(20px); }
          to { opacity: 1; transform: translateY(0); }
        }
        @keyframes glow-pulse {
          0%, 100% { opacity: 0.3; }
          50% { opacity: 0.7; }
        }
        @keyframes shimmer-line {
          0% { transform: translateX(-100%); }
          100% { transform: translateX(100%); }
        }

        .dashboard-root {
          font-family: 'Syne', sans-serif;
          display: flex;
          min-height: 100vh;
          position: relative;
          z-index: 1;
        }

        /* ── SIDEBAR ── */
        .sidebar {
          width: 230px;
          min-height: 100vh;
          background: rgba(8,5,20,0.85);
          border-right: 1px solid rgba(168,85,247,0.12);
          display: flex;
          flex-direction: column;
          padding: 0;
          position: fixed;
          top: 0; left: 0; bottom: 0;
          z-index: 10;
          backdrop-filter: blur(20px);
        }

        .sidebar::before {
          content: '';
          position: absolute; top: 0; left: 0; right: 0; bottom: 0;
          background: linear-gradient(180deg, rgba(88,28,135,0.05) 0%, transparent 50%, rgba(6,95,70,0.04) 100%);
          pointer-events: none;
        }

        /* decorative rune line on sidebar right edge */
        .sidebar::after {
          content: '';
          position: absolute; top: 20%; right: -1px; bottom: 20%;
          width: 1px;
          background: linear-gradient(180deg, transparent, rgba(168,85,247,0.4), rgba(52,211,153,0.3), rgba(168,85,247,0.4), transparent);
        }

        .sidebar-logo {
          padding: 28px 22px 24px;
          border-bottom: 1px solid rgba(168,85,247,0.08);
          margin-bottom: 8px;
          position: relative;
        }

        .logo-mark {
          width: 40px; height: 40px;
          background: linear-gradient(135deg, rgba(88,28,135,0.9) 0%, rgba(168,85,247,0.9) 100%);
          border-radius: 12px;
          display: flex; align-items: center; justify-content: center;
          font-family: 'Cinzel', serif;
          font-size: 18px; font-weight: 700; color: #fff;
          margin-bottom: 12px;
          box-shadow: 0 0 30px rgba(168,85,247,0.4), inset 0 1px 0 rgba(255,255,255,0.15);
          border: 1px solid rgba(168,85,247,0.4);
          position: relative;
        }

        .logo-mark::after {
          content: '';
          position: absolute; inset: -4px;
          border-radius: 15px;
          border: 1px solid rgba(168,85,247,0.15);
        }

        .logo-text {
          font-family: 'Cinzel', serif;
          font-size: 13px; font-weight: 600;
          color: #e2d9f3; letter-spacing: 0.05em;
        }

        .logo-sub {
          font-size: 9px; color: rgba(168,85,247,0.5);
          letter-spacing: 0.2em; text-transform: uppercase; margin-top: 3px;
          font-family: 'JetBrains Mono', monospace;
        }

        .nav-section-label {
          padding: 0 22px 6px; font-size: 8px;
          color: rgba(148,163,184,0.25);
          text-transform: uppercase; letter-spacing: 0.2em;
          font-family: 'JetBrains Mono', monospace;
        }

        .nav-tab {
          display: flex; align-items: center; gap: 10px;
          padding: 11px 22px; width: 100%; border: none; background: transparent;
          color: rgba(148,163,184,0.4); font-size: 13px; font-weight: 500; cursor: pointer;
          transition: all 0.2s; font-family: 'Syne', sans-serif;
          position: relative; text-align: left; border-radius: 0;
          letter-spacing: 0.01em;
        }

        .nav-icon-wrap {
          font-size: 14px;
          opacity: 0.6;
          transition: all 0.2s;
        }

        .nav-tab:hover {
          color: rgba(168,85,247,0.8);
          background: rgba(168,85,247,0.04);
        }

        .nav-tab:hover .nav-icon-wrap {
          opacity: 1;
          filter: drop-shadow(0 0 6px rgba(168,85,247,0.6));
        }

        .nav-tab-active {
          color: #e2d9f3 !important;
          background: rgba(168,85,247,0.07) !important;
        }

        .nav-tab-active .nav-icon-wrap {
          opacity: 1 !important;
          filter: drop-shadow(0 0 8px rgba(168,85,247,0.8)) !important;
        }

        .nav-tab-active::before {
          content: '';
          position: absolute; left: 0; top: 0; bottom: 0;
          width: 2px;
          background: linear-gradient(180deg, transparent, #a855f7, #7c3aed, transparent);
          box-shadow: 0 0 8px rgba(168,85,247,0.6), 2px 0 12px rgba(168,85,247,0.2);
        }

        .nav-count {
          margin-left: auto; font-size: 10px;
          background: rgba(15,10,30,0.8);
          color: rgba(148,163,184,0.35);
          border: 1px solid rgba(168,85,247,0.1);
          border-radius: 20px; padding: 1px 8px;
          font-weight: 600; font-family: 'JetBrains Mono', monospace;
        }

        .nav-count-active {
          background: rgba(168,85,247,0.12) !important;
          color: #a855f7 !important;
          border-color: rgba(168,85,247,0.25) !important;
          box-shadow: 0 0 8px rgba(168,85,247,0.2);
        }

        .sidebar-footer {
          margin-top: auto;
          padding: 20px 22px;
          border-top: 1px solid rgba(168,85,247,0.08);
        }

        .admin-pill {
          display: flex; align-items: center; gap: 10px;
        }

        .admin-avatar {
          width: 32px; height: 32px; border-radius: 10px;
          background: linear-gradient(135deg, rgba(88,28,135,0.9), rgba(168,85,247,0.9));
          border: 1px solid rgba(168,85,247,0.35);
          display: flex; align-items: center; justify-content: center;
          font-family: 'Cinzel', serif;
          font-size: 12px; font-weight: 700; color: #fff; flex-shrink: 0;
          box-shadow: 0 0 16px rgba(168,85,247,0.3);
        }

        /* ── MAIN CONTENT ── */
        .main-content {
          margin-left: 230px;
          flex: 1;
          padding: 0;
          min-height: 100vh;
        }

        /* ── TOP BAR ── */
        .topbar {
          padding: 18px 36px;
          display: flex; align-items: center; justify-content: space-between;
          border-bottom: 1px solid rgba(168,85,247,0.08);
          background: rgba(6,4,15,0.7);
          backdrop-filter: blur(20px);
          position: sticky; top: 0; z-index: 5;
        }

        .topbar::after {
          content: '';
          position: absolute; bottom: -1px; left: 0; right: 0; height: 1px;
          background: linear-gradient(90deg, transparent, rgba(168,85,247,0.3), rgba(52,211,153,0.2), rgba(168,85,247,0.3), transparent);
        }

        .topbar-title {
          font-family: 'Cinzel', serif;
          font-size: 16px; font-weight: 600;
          color: #e2d9f3; letter-spacing: 0.04em;
          text-shadow: 0 0 20px rgba(168,85,247,0.3);
        }

        .topbar-date {
          font-size: 10px; color: rgba(148,163,184,0.35); margin-top: 3px;
          font-family: 'JetBrains Mono', monospace; letter-spacing: 0.05em;
        }

        .refresh-btn {
          display: flex; align-items: center; gap: 8px;
          background: rgba(15,10,30,0.8);
          border: 1px solid rgba(168,85,247,0.2);
          border-radius: 10px; padding: 9px 18px;
          color: rgba(148,163,184,0.5); font-size: 12px; cursor: pointer;
          transition: all 0.25s; font-family: 'Syne', sans-serif; font-weight: 500;
          letter-spacing: 0.03em;
        }

        .refresh-btn:hover {
          border-color: rgba(168,85,247,0.5);
          color: #a855f7;
          background: rgba(168,85,247,0.06);
          box-shadow: 0 0 20px rgba(168,85,247,0.15), inset 0 0 20px rgba(168,85,247,0.04);
        }

        /* ── CONTENT AREA ── */
        .content-area {
          padding: 32px 36px;
          animation: fadeUp 0.4s ease both;
        }

        /* ── SECTION HEADING ── */
        .section-heading {
          font-family: 'Cinzel', serif;
          font-size: 9px; color: rgba(168,85,247,0.45);
          text-transform: uppercase; letter-spacing: 0.2em;
          margin-bottom: 18px;
          display: flex; align-items: center; gap: 12px;
        }

        .section-heading::after {
          content: ''; flex: 1; height: 1px;
          background: linear-gradient(90deg, rgba(168,85,247,0.2), transparent);
        }

        /* ── METRIC CARD ── */
        .metric-card {
          background: rgba(10,7,22,0.8);
          border: 1px solid rgba(168,85,247,0.1);
          border-radius: 16px;
          padding: 20px 22px 16px;
          display: flex; flex-direction: column;
          position: relative; overflow: hidden;
          transition: border-color 0.25s, transform 0.25s;
          backdrop-filter: blur(10px);
        }

        .metric-card:hover {
          border-color: rgba(168,85,247,0.3);
          transform: translateY(-3px);
        }

        .metric-card-aurora {
          position: absolute; inset: 0;
          pointer-events: none;
          transition: opacity 0.3s;
          border-radius: 16px;
        }

        .metric-card-border-glow {
          position: absolute; inset: 0;
          border-radius: 16px;
          pointer-events: none;
          transition: box-shadow 0.3s;
        }

        .metric-label {
          font-size: 9px; color: rgba(148,163,184,0.4);
          text-transform: uppercase; letter-spacing: 0.15em;
          font-family: 'JetBrains Mono', monospace;
        }

        .metric-icon { font-size: 15px; }

        .metric-value {
          font-family: 'Cinzel', serif;
          font-size: 28px; font-weight: 700;
          color: #e2d9f3;
          font-variant-numeric: tabular-nums; line-height: 1.2;
          letter-spacing: -0.01em; margin-top: 8px;
          text-shadow: 0 0 20px rgba(168,85,247,0.25);
        }

        .metric-sub {
          font-size: 10px; color: rgba(148,163,184,0.35);
          margin-top: 4px; font-family: 'JetBrains Mono', monospace;
        }

        .metric-card-bar {
          position: absolute; bottom: 0; left: 20%; right: 20%;
          height: 1px; opacity: 0.5;
        }

        /* ── GLASS PANEL ── */
        .glass-panel {
          background: rgba(10,7,22,0.75);
          border: 1px solid rgba(168,85,247,0.1);
          border-radius: 16px;
          padding: 24px 26px;
          position: relative;
          overflow: hidden;
          backdrop-filter: blur(10px);
        }

        .glass-panel::before {
          content: '';
          position: absolute; top: 0; left: 15%; right: 15%; height: 1px;
          background: linear-gradient(90deg, transparent, rgba(168,85,247,0.35), transparent);
        }

        .panel-title {
          font-family: 'Cinzel', serif;
          font-size: 9px; color: rgba(168,85,247,0.5);
          text-transform: uppercase; letter-spacing: 0.18em;
          margin-bottom: 18px;
        }

        /* ── STAT ROW ── */
        .stat-row {
          background: rgba(10,7,22,0.75);
          border: 1px solid rgba(168,85,247,0.1);
          border-radius: 16px;
          padding: 20px 26px; display: flex; flex-wrap: wrap; gap: 0;
          backdrop-filter: blur(10px);
          position: relative; overflow: hidden;
        }

        .stat-row::before {
          content: '';
          position: absolute; top: 0; left: 10%; right: 10%; height: 1px;
          background: linear-gradient(90deg, transparent, rgba(168,85,247,0.25), rgba(52,211,153,0.2), rgba(168,85,247,0.25), transparent);
        }

        .stat-item {
          flex: 1; min-width: 120px; padding: 0 24px;
          border-right: 1px solid rgba(168,85,247,0.07);
        }

        .stat-item:first-child { padding-left: 0; }
        .stat-item:last-child { border-right: none; }

        .stat-label {
          font-size: 8px; color: rgba(148,163,184,0.3);
          text-transform: uppercase; letter-spacing: 0.15em;
          font-family: 'JetBrains Mono', monospace; margin-bottom: 5px;
        }

        .stat-val {
          font-family: 'Cinzel', serif;
          font-size: 18px; font-weight: 700;
          font-variant-numeric: tabular-nums; letter-spacing: -0.01em;
        }

        /* ── TABLE ── */
        .arcane-table-row {
          border-bottom: 1px solid rgba(168,85,247,0.05);
          transition: background 0.15s;
        }
        .arcane-table-row:hover { background: rgba(168,85,247,0.03); }
        .arcane-table-row:last-child { border-bottom: none; }

        /* ── TOGGLE BUTTONS ── */
        .toggle-btn-active {
          background: rgba(52,211,153,0.08);
          color: #34d399;
          border: 1px solid rgba(52,211,153,0.25);
          border-radius: 8px; padding: 5px 12px; font-size: 11px;
          cursor: pointer; font-weight: 600;
          font-family: 'JetBrains Mono', monospace;
          transition: all 0.2s;
          box-shadow: 0 0 10px rgba(52,211,153,0.1);
        }
        .toggle-btn-active:hover {
          background: rgba(248,113,113,0.08); color: #f87171;
          border-color: rgba(248,113,113,0.25);
          box-shadow: 0 0 10px rgba(248,113,113,0.15);
        }
        .toggle-btn-inactive {
          background: rgba(248,113,113,0.08); color: #f87171;
          border: 1px solid rgba(248,113,113,0.25);
          border-radius: 8px; padding: 5px 12px; font-size: 11px;
          cursor: pointer; font-weight: 600;
          font-family: 'JetBrains Mono', monospace;
          transition: all 0.2s;
        }

        /* ── SUPER ADMIN BADGE ── */
        .super-admin-badge {
          font-size: 10px; color: rgba(168,85,247,0.4);
          font-family: 'JetBrains Mono', monospace;
          padding: 4px 10px; border: 1px solid rgba(168,85,247,0.15);
          border-radius: 8px; display: inline-flex; align-items: center; gap: 4px;
          letter-spacing: 0.05em;
        }

        /* ── FEEDBACK CARD ── */
        .feedback-card {
          background: rgba(10,7,22,0.75);
          border: 1px solid rgba(168,85,247,0.09);
          border-radius: 14px; padding: 18px 22px;
          transition: border-color 0.2s, box-shadow 0.2s;
          backdrop-filter: blur(10px);
          position: relative; overflow: hidden;
        }
        .feedback-card::before {
          content: '';
          position: absolute; top: 0; left: 10%; right: 10%; height: 1px;
          background: linear-gradient(90deg, transparent, rgba(168,85,247,0.2), transparent);
        }
        .feedback-card:hover {
          border-color: rgba(168,85,247,0.2);
          box-shadow: 0 4px 30px rgba(168,85,247,0.05);
        }

        /* ── ERROR BOX ── */
        .error-box {
          background: rgba(248,113,113,0.05);
          border: 1px solid rgba(248,113,113,0.2);
          border-radius: 12px; padding: 14px 18px; color: #f87171;
          font-size: 13px; margin-bottom: 24px;
          display: flex; align-items: center; gap: 8px;
          box-shadow: 0 0 20px rgba(248,113,113,0.05);
        }

        /* ── INPUT ── */
        .arcane-input {
          background: rgba(10,7,22,0.8);
          border: 1px solid rgba(168,85,247,0.15);
          border-radius: 10px; padding: 10px 14px;
          color: #e2d9f3; font-size: 13px; outline: none;
          width: 100%; transition: border-color 0.2s, box-shadow 0.2s;
          font-family: 'Syne', sans-serif;
        }
        .arcane-input:focus {
          border-color: rgba(168,85,247,0.4) !important;
          box-shadow: 0 0 20px rgba(168,85,247,0.1);
        }
        .arcane-input option { background: #0a0714; }

        ::-webkit-scrollbar { width: 4px; height: 4px; }
        ::-webkit-scrollbar-track { background: transparent; }
        ::-webkit-scrollbar-thumb { background: rgba(168,85,247,0.2); border-radius: 10px; }
        ::-webkit-scrollbar-thumb:hover { background: rgba(168,85,247,0.35); }
      `}</style>

      {/* ── AMBIENT LAYERS ── */}
      <div className="nebula-1" />
      <div className="nebula-2" />
      <div className="nebula-3" />
      <div className="aurora-line" />
      <ParticleField />

      <div className="dashboard-root">
        {/* ── SIDEBAR ── */}
        <aside className="sidebar">
          <div className="sidebar-logo">
            <div className="logo-mark">⬡</div>
            <div className="logo-text">Control Center</div>
            <div className="logo-sub">Super Admin · Arcane</div>
          </div>

          <div style={{ marginBottom: 8, padding: "8px 0" }}>
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
                <div style={{ fontSize: 12, fontWeight: 600, color: "rgba(226,217,243,0.8)", fontFamily: "'Cinzel', serif" }}>Wahaj</div>
                <div style={{ fontSize: 9, color: "rgba(168,85,247,0.45)", fontFamily: "'JetBrains Mono', monospace", letterSpacing: "0.1em" }}>SUPER ADMIN</div>
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
              <div className="topbar-date">
                {dateStr} · {timeStr}
                {m && <span style={{ marginLeft: 8, color: "rgba(52,211,153,0.3)" }}>· synced {new Date(m.generated_at).toLocaleTimeString()}</span>}
              </div>
            </div>
            <button onClick={refetch} className="refresh-btn">
              <span style={{ fontSize: 14, lineHeight: 1, filter: "drop-shadow(0 0 4px currentColor)" }}>↻</span> Refresh
            </button>
          </div>

          {/* Content */}
          <div className="content-area" key={tab}>
            {error && (
              <div className="error-box">
                <span style={{ filter: "drop-shadow(0 0 6px #f87171)" }}>⚠</span> Failed to load metrics: {error}
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
                        sub={`+${m.users.new_this_week} this week`} color="#a855f7"
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
                        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 10, fontSize: 10, color: "rgba(148,163,184,0.3)", fontFamily: "'JetBrains Mono', monospace" }}>
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
                          { label: "Exempt",    count: m.users.exempt,    color: "#a855f7", total: m.users.total },
                        ].map(({ label, count, color, total }) => {
                          const pct = total ? Math.round((count / total) * 100) : 0;
                          return (
                            <div key={label} style={{ marginBottom: 14 }}>
                              <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                                <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                                  <div style={{ width: 5, height: 5, borderRadius: "50%", background: color, boxShadow: `0 0 8px ${color}` }} />
                                  <span style={{ fontSize: 12, color: "rgba(148,163,184,0.55)" }}>{label}</span>
                                </div>
                                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                  <span style={{ fontSize: 10, color: "rgba(148,163,184,0.3)", fontFamily: "'JetBrains Mono', monospace" }}>{pct}%</span>
                                  <span style={{ fontSize: 13, color, fontWeight: 700, minWidth: 28, textAlign: "right", filter: `drop-shadow(0 0 4px ${color}60)` }}>{count}</span>
                                </div>
                              </div>
                              <div style={{ height: 3, background: "rgba(168,85,247,0.05)", borderRadius: 4, overflow: "hidden" }}>
                                <div style={{
                                  height: "100%", width: `${pct}%`,
                                  background: `linear-gradient(90deg, ${color}40, ${color})`,
                                  borderRadius: 4, transition: "width 0.8s cubic-bezier(0.4,0,0.2,1)",
                                  boxShadow: `0 0 8px ${color}40`,
                                }} />
                              </div>
                            </div>
                          );
                        })}

                        <div style={{ marginTop: 18, paddingTop: 16, borderTop: "1px solid rgba(168,85,247,0.07)" }}>
                          <div className="panel-title" style={{ marginBottom: 12 }}>Users by Role</div>
                          {Object.entries(m.users.by_role).map(([role, count]) => (
                            <div key={role} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                              <span style={{ fontSize: 12, color: "rgba(148,163,184,0.4)", textTransform: "capitalize" }}>{role}</span>
                              <span style={{ fontSize: 13, color: "rgba(168,85,247,0.7)", fontWeight: 700, fontFamily: "'JetBrains Mono', monospace" }}>{count}</span>
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>

                    <div className="stat-row">
                      {[
                        { label: "New This Week",   value: m.users.new_this_week,                color: "#a855f7" },
                        { label: "New This Month",  value: m.users.new_this_month,               color: "#a855f7" },
                        { label: "Tasks Today",     value: m.tasks.created_today,                color: "#34d399" },
                        { label: "Completion Rate", value: `${m.tasks.completion_rate}%`,        color: "#34d399" },
                        { label: "MRR",             value: `$${m.revenue.mrr}`,                  color: "#fbbf24" },
                        { label: "QRR",             value: `$${m.revenue.qrr}`,                  color: "#fbbf24" },
                        { label: "ARR",             value: `$${m.revenue.arr.toLocaleString()}`, color: "#fbbf24" },
                      ].map(({ label, value, color }) => (
                        <div key={label} className="stat-item">
                          <div className="stat-label">{label}</div>
                          <div className="stat-val" style={{ color, filter: `drop-shadow(0 0 6px ${color}60)` }}>{value}</div>
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
                      <MetricCard label="ARR" value={`$${m.revenue.arr.toLocaleString()}`} icon="↑" color="#a855f7" sub="annualized" />
                      <MetricCard label="QRR" value={`$${m.revenue.qrr}`} icon="◈" color="#fbbf24" sub="this quarter" />
                      <MetricCard label="Plan Price" value={`$${m.revenue.plan_price}/mo`} icon="✦" color="#818cf8" sub="per user" />
                    </div>

                    <div className="glass-panel" style={{ marginBottom: 16 }}>
                      <div className="panel-title">Monthly Revenue — Last 12 Months</div>
                      <RevenueChart data={m.revenue.monthly_breakdown} />

                      <div style={{ marginTop: 28 }}>
                        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", padding: "6px 0 10px", borderBottom: "1px solid rgba(168,85,247,0.07)" }}>
                          {["Month", "New Paid", "Revenue"].map(h => (
                            <div key={h} style={{ fontSize: 9, color: "rgba(168,85,247,0.4)", textTransform: "uppercase", letterSpacing: "0.12em", fontFamily: "'JetBrains Mono', monospace" }}>{h}</div>
                          ))}
                        </div>
                        {[...m.revenue.monthly_breakdown].reverse().slice(0, 8).map((d, i) => (
                          <div key={i} style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", padding: "11px 0", borderBottom: "1px solid rgba(168,85,247,0.04)", fontSize: 13 }}>
                            <span style={{ color: "rgba(148,163,184,0.45)" }}>{d.month}</span>
                            <span style={{ color: "rgba(148,163,184,0.35)", fontFamily: "'JetBrains Mono', monospace" }}>{d.new_paid}</span>
                            <span style={{
                              color: d.revenue > 0 ? "#34d399" : "rgba(148,163,184,0.2)",
                              fontWeight: 600, fontFamily: "'JetBrains Mono', monospace",
                              filter: d.revenue > 0 ? "drop-shadow(0 0 4px rgba(52,211,153,0.4))" : "none",
                            }}>${d.revenue.toFixed(2)}</span>
                          </div>
                        ))}
                      </div>

                      <div style={{ marginTop: 16, padding: "12px 14px", background: "rgba(168,85,247,0.04)", borderRadius: 10, border: "1px solid rgba(168,85,247,0.08)", fontSize: 11, color: "rgba(148,163,184,0.3)", fontFamily: "'JetBrains Mono', monospace", lineHeight: 1.7 }}>
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
