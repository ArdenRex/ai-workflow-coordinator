// src/App.jsx
import React, { useState, useMemo, useCallback, useEffect } from "react";
import { AuthProvider, useAuth } from "./context/AuthContext";   // ✅ NEW
import AuthPage from "./pages/AuthPage";                          // ✅ NEW
import OnboardingPage from "./pages/OnboardingPage";             // ✅ NEW
import { useTasks } from "./hooks/useTasks";
import KanbanColumn from "./components/KanbanColumn";
import AddTaskModal from "./components/AddTaskModal";
import AddToSlackButton from "./components/AddToSlackButton";

// ── API base URL — env var with hardcoded fallback ───────────────────────────
const BASE_URL = process.env.REACT_APP_API_URL || "https://ai-workflow-coordinator-api-production.up.railway.app";

// ── CSS variables + animations ────────────────────────────────────────────────
const GLOBAL_STYLES = `
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg-page:            #0d0f1e;
    --bg-sidebar:         #10132a;
    --border-glass:       rgba(255,255,255,0.09);
    --accent-1:           #4f8ef7;
    --color-text-primary:   #e8eaf6;
    --color-text-secondary: #8b90b8;
    --color-text-tertiary:  #555a80;
    --font-sans: 'Inter', 'Plus Jakarta Sans', system-ui, sans-serif;
    --font-mono: 'JetBrains Mono', 'Fira Code', monospace;
  }
  body { background: #0d0f1e; color: #e8eaf6; font-family: var(--font-sans); }
  @keyframes spin  { to { transform: rotate(360deg); } }
  @keyframes pulse { 0%,100% { opacity:1; } 50% { opacity:0.4; } }
  @keyframes fadeUp {
    from { opacity: 0; transform: translateY(12px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  .fade-up         { animation: fadeUp 0.4s ease both; }
  .fade-up.delay-1 { animation-delay: 0.07s; }
  .fade-up.delay-2 { animation-delay: 0.14s; }
`;

// ── Full-screen loading spinner (shown while auth state initialises) ───────────
function AppLoader() {
  return (
    <div style={{
      minHeight: "100vh", background: "#0d0f1e",
      display: "flex", alignItems: "center", justifyContent: "center",
      flexDirection: "column", gap: 16,
    }}>
      <div style={{
        width: 32, height: 32, borderRadius: 8,
        background: "linear-gradient(135deg, #4f8ef7 0%, #7b5cf0 100%)",
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: 14, fontWeight: 700, color: "#fff",
        boxShadow: "0 0 20px rgba(79,142,247,0.4)",
      }}>AI</div>
      <div style={{
        width: 24, height: 24,
        border: "2px solid rgba(79,142,247,0.2)",
        borderTopColor: "#4f8ef7",
        borderRadius: "50%",
        animation: "spin 0.7s linear infinite",
      }} />
    </div>
  );
}

// ── Columns / nav config (unchanged) ─────────────────────────────────────────
const COLUMNS = [
  { status: "to_do",       label: "To Do"       },
  { status: "in_progress", label: "In Progress" },
  { status: "completed",   label: "Done"        },
  { status: "cancelled",   label: "Cancelled"   },
];

const NAV_ITEMS = [
  { icon: "⬡", label: "Dashboard",    badge: null },
  { icon: "✦", label: "Tasks",        badge: null },
  { icon: "◈", label: "Compliance",   badge: "5"  },
  { icon: "◉", label: "Knowledge",    badge: null },
  { icon: "▲", label: "Reports",      badge: null },
  { icon: "⊕", label: "Ownership",    badge: null },
  { icon: "⛓", label: "Integrations", badge: null },
  { icon: "🌐", label: "Locale",       badge: null },
  { icon: "💬", label: "Teams",        badge: null },
  { icon: "🔑", label: "API",          badge: null },
  { icon: "⚙", label: "Settings",     badge: null },
];

const TABS = [
  { label: "All Tasks",   filter: null          },
  { label: "To Do",       filter: "to_do"       },
  { label: "In Progress", filter: "in_progress" },
  { label: "Done",        filter: "completed"   },
];

// ── Sidebar — now shows real user info + logout ───────────────────────────────
function Sidebar({ activeNav, onNavChange }) {
  const { user, logout } = useAuth();                            // ✅ NEW

  const initials = user?.name
    ? user.name.split(" ").map(w => w[0]).join("").toUpperCase().slice(0, 2)
    : "AW";

  const roleLabel = {
    architect: "Architect",
    navigator: "Navigator",
    operator:  "Operator",
    solo:      "Solo",
  }[user?.role] || "Member";

  return (
    <aside style={{
      position: "fixed", left: 0, top: 0, bottom: 0, width: 220,
      background: "var(--bg-sidebar)",
      borderRight: "1px solid var(--border-glass)",
      display: "flex", flexDirection: "column", zIndex: 50, overflow: "hidden",
    }}>
      <div style={{
        position: "absolute", top: -80, left: -80, width: 280, height: 280,
        background: "radial-gradient(circle, rgba(79,142,247,0.09) 0%, transparent 70%)",
        pointerEvents: "none",
      }} />

      {/* Logo */}
      <div style={{
        padding: "22px 20px 18px", display: "flex", alignItems: "center", gap: 10,
        borderBottom: "1px solid var(--border-glass)", position: "relative",
      }}>
        <div style={{
          width: 32, height: 32, borderRadius: 8, flexShrink: 0,
          background: "linear-gradient(135deg, #4f8ef7 0%, #7b5cf0 100%)",
          display: "flex", alignItems: "center", justifyContent: "center",
          boxShadow: "0 0 16px rgba(79,142,247,0.4)",
          fontSize: 14, color: "#fff", fontWeight: 700,
        }}>AI</div>
        <div>
          <div style={{ fontSize: 13, fontWeight: 700, color: "var(--color-text-primary)", letterSpacing: "-0.01em", lineHeight: 1.2 }}>AI Workflow</div>
          <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", marginTop: 1 }}>Coordinator</div>
        </div>
      </div>

      {/* Nav */}
      <nav style={{ flex: 1, padding: "10px", display: "flex", flexDirection: "column", gap: 2, position: "relative" }}>
        <div style={{ fontSize: 10, fontWeight: 600, letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--color-text-tertiary)", padding: "10px 8px 6px" }}>
          Main Menu
        </div>
        {NAV_ITEMS.map((item, idx) => {
          const isActive = activeNav === idx;
          return (
            <div
              key={item.label}
              role="button" tabIndex={0}
              aria-current={isActive ? "page" : undefined}
              onClick={() => onNavChange(idx)}
              onKeyDown={e => e.key === "Enter" && onNavChange(idx)}
              style={{
                display: "flex", alignItems: "center", gap: 10,
                padding: "9px 12px", borderRadius: 10, fontSize: 13, fontWeight: 500,
                color: isActive ? "var(--accent-1)" : "var(--color-text-secondary)",
                background: isActive ? "linear-gradient(135deg, rgba(79,142,247,0.15) 0%, rgba(123,92,240,0.15) 100%)" : "transparent",
                border: isActive ? "1px solid rgba(79,142,247,0.35)" : "1px solid transparent",
                cursor: "pointer", transition: "all 0.15s",
              }}
              onMouseEnter={e => { if (!isActive) { e.currentTarget.style.background = "rgba(255,255,255,0.04)"; e.currentTarget.style.color = "var(--color-text-primary)"; } }}
              onMouseLeave={e => { if (!isActive) { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--color-text-secondary)"; } }}
            >
              <span style={{ fontSize: 13, opacity: isActive ? 1 : 0.6, width: 16, textAlign: "center", flexShrink: 0 }} aria-hidden="true">{item.icon}</span>
              <span style={{ flex: 1 }}>{item.label}</span>
              {item.badge && (
                <span style={{
                  minWidth: 18, height: 18, padding: "0 5px", borderRadius: 999,
                  fontSize: 10, fontWeight: 700, color: "#fff",
                  background: "linear-gradient(135deg, #4f8ef7 0%, #7b5cf0 100%)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  boxShadow: "0 0 8px rgba(79,142,247,0.4)",
                }}>{item.badge}</span>
              )}
            </div>
          );
        })}
      </nav>

      {/* ✅ User footer — now shows real name, role, logout button */}
      <div style={{ padding: "14px", borderTop: "1px solid var(--border-glass)" }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 10, padding: "8px 10px",
          borderRadius: 10, background: "rgba(255,255,255,0.04)",
          border: "1px solid var(--border-glass)",
        }}>
          <div style={{
            width: 30, height: 30, borderRadius: "50%", flexShrink: 0,
            background: "linear-gradient(135deg, #4f8ef7 0%, #7b5cf0 100%)",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 11, fontWeight: 700, color: "#fff",
            boxShadow: "0 0 10px rgba(79,142,247,0.35)",
          }}>{initials}</div>
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text-primary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {user?.name || "User"}
            </div>
            <div style={{ fontSize: 10, color: "var(--color-text-tertiary)" }}>{roleLabel}</div>
          </div>
          {/* Logout button */}
          <button
            onClick={logout}
            title="Log out"
            aria-label="Log out"
            style={{
              background: "transparent", border: "none", cursor: "pointer",
              color: "var(--color-text-tertiary)", fontSize: 14, padding: 2,
              display: "flex", alignItems: "center", justifyContent: "center",
              borderRadius: 6, transition: "color 0.15s",
            }}
            onMouseEnter={e => e.currentTarget.style.color = "#f87171"}
            onMouseLeave={e => e.currentTarget.style.color = "var(--color-text-tertiary)"}
          >⏻</button>
        </div>
      </div>
    </aside>
  );
}

// ── SVG icons (unchanged) ─────────────────────────────────────────────────────
const IconCheckbox = () => (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
    <rect x="2" y="2" width="16" height="16" rx="4" stroke="currentColor" strokeWidth="1.5"/>
    <path d="M6 10l3 3 5-5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);
const IconProgress = () => (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
    <circle cx="10" cy="10" r="7" stroke="currentColor" strokeWidth="1.5" strokeDasharray="3 2"/>
    <circle cx="10" cy="10" r="3" fill="currentColor" opacity="0.6"/>
  </svg>
);
const IconDone = () => (
  <svg width="20" height="20" viewBox="0 0 20 20" fill="none" aria-hidden="true">
    <circle cx="10" cy="10" r="7" stroke="currentColor" strokeWidth="1.5"/>
    <path d="M7 10l2.5 2.5L13 7.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
  </svg>
);

function Sparkline({ color }) {
  return (
    <svg width="64" height="28" viewBox="0 0 64 28" fill="none" aria-hidden="true">
      <polyline points="0,22 10,18 20,20 30,12 40,14 52,6 64,8"
        stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"
        fill="none" opacity="0.8" />
    </svg>
  );
}

// ── Segment 10: Ownership Graph view ─────────────────────────────────────────
function OwnershipGraph() {
  const { user } = useAuth();
  const API = BASE_URL;
  const [data, setData]         = useState(null);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState(null);
  const [selected, setSelected] = useState(null); // selected assignee node
  const [filter, setFilter]     = useState("");

  useEffect(() => {
    const params = new URLSearchParams();
    if (user?.workspace?.id) params.set("workspace_id", user.workspace.id);
    else if (user?.id)       params.set("owner_id", user.id);

    fetch(`${API}/tasks/graph?${params}`)
      .then(r => { if (!r.ok) throw new Error("Failed to load graph"); return r.json(); })
      .then(d => { setData(d); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  }, [API, user]);

  const PRIORITY_COLOR = { critical: "#f87171", high: "#fb923c", medium: "#fbbf24", low: "#34d399" };
  const STATUS_COLOR   = { to_do: "#4f8ef7", in_progress: "#f59e0b", completed: "#22d3a8", cancelled: "#6b7280" };

  const nodes = useMemo(() => {
    if (!data?.nodes) return [];
    return data.nodes.filter(n =>
      !filter || n.assignee.toLowerCase().includes(filter.toLowerCase())
    );
  }, [data, filter]);

  if (loading) return (
    <main style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 40 }}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
        <div style={{ width: 24, height: 24, border: "2px solid rgba(79,142,247,0.2)", borderTopColor: "#4f8ef7", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />
        <span style={{ fontSize: 13, color: "var(--color-text-tertiary)" }}>Loading ownership data…</span>
      </div>
    </main>
  );

  if (error) return (
    <main style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 40 }}>
      <div style={{ textAlign: "center" }}>
        <div style={{ fontSize: 32, marginBottom: 12 }}>⚠</div>
        <p style={{ color: "#f87171", fontSize: 14 }}>{error}</p>
      </div>
    </main>
  );

  const selectedNode = selected ? data?.nodes?.find(n => n.assignee === selected) : null;

  return (
    <main style={{ flex: 1, padding: "28px 28px 40px", display: "flex", flexDirection: "column", gap: 24 }}>

      {/* Header */}
      <header style={{
        position: "sticky", top: 0, zIndex: 40, height: 60,
        background: "rgba(13,15,30,0.88)", backdropFilter: "blur(16px)",
        borderBottom: "1px solid var(--border-glass)",
        padding: "0 28px", display: "flex", alignItems: "center", gap: 16,
        margin: "-28px -28px 0",
      }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: "var(--color-text-primary)", letterSpacing: "-0.02em" }}>Ownership Graph</div>
          <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 1 }}>
            {data?.total_tasks ?? 0} tasks · {data?.total_owners ?? 0} owners
          </div>
        </div>
        <div style={{ flex: 1, maxWidth: 300, position: "relative" }}>
          <svg style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", width: 14, height: 14, color: "var(--color-text-tertiary)", pointerEvents: "none" }} viewBox="0 0 16 16" fill="none">
            <circle cx="6.5" cy="6.5" r="4.5" stroke="currentColor" strokeWidth="1.3"/>
            <path d="M10 10l3.5 3.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
          </svg>
          <input
            value={filter} onChange={e => setFilter(e.target.value)}
            placeholder="Filter by person…"
            style={{
              width: "100%", height: 36, padding: "0 14px 0 32px",
              background: "rgba(255,255,255,0.06)", border: "1px solid var(--border-glass)",
              borderRadius: 999, fontFamily: "var(--font-sans)", fontSize: 13,
              color: "var(--color-text-primary)", outline: "none",
            }}
            onFocus={e => { e.target.style.borderColor = "rgba(79,142,247,0.5)"; e.target.style.boxShadow = "0 0 0 3px rgba(79,142,247,0.12)"; }}
            onBlur={e => { e.target.style.borderColor = "var(--border-glass)"; e.target.style.boxShadow = "none"; }}
          />
        </div>
      </header>

      {/* Summary pills */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap", marginTop: 8 }}>
        {[
          { label: "Total Tasks",   value: data?.total_tasks,  color: "#4f8ef7" },
          { label: "Owners",        value: data?.total_owners, color: "#7b5cf0" },
          { label: "In Progress",   value: nodes.reduce((s, n) => s + n.in_progress, 0), color: "#f59e0b" },
          { label: "Completed",     value: nodes.reduce((s, n) => s + n.completed,   0), color: "#22d3a8" },
          { label: "Critical",      value: nodes.reduce((s, n) => s + n.critical,    0), color: "#f87171" },
        ].map(p => (
          <div key={p.label} style={{
            padding: "6px 14px", borderRadius: 999,
            background: "rgba(255,255,255,0.05)", border: "1px solid var(--border-glass)",
            display: "flex", alignItems: "center", gap: 8,
          }}>
            <span style={{ width: 8, height: 8, borderRadius: "50%", background: p.color, flexShrink: 0 }} />
            <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>{p.label}</span>
            <span style={{ fontSize: 13, fontWeight: 700, color: "var(--color-text-primary)" }}>{p.value ?? 0}</span>
          </div>
        ))}
      </div>

      {/* Main grid: nodes list + detail panel */}
      <div style={{ display: "grid", gridTemplateColumns: selectedNode ? "1fr 360px" : "1fr", gap: 20, alignItems: "start" }}>

        {/* Ownership nodes grid */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(260px, 1fr))", gap: 14 }}>
          {nodes.length === 0 && (
            <div style={{ gridColumn: "1/-1", textAlign: "center", padding: "60px 0", color: "var(--color-text-tertiary)", fontSize: 14 }}>
              No ownership data found.
            </div>
          )}
          {nodes.map(node => {
            const isSelected = selected === node.assignee;
            const completionPct = node.total > 0 ? Math.round((node.completed / node.total) * 100) : 0;
            return (
              <div
                key={node.assignee}
                role="button" tabIndex={0}
                onClick={() => setSelected(isSelected ? null : node.assignee)}
                onKeyDown={e => e.key === "Enter" && setSelected(isSelected ? null : node.assignee)}
                style={{
                  background: isSelected
                    ? "linear-gradient(135deg, rgba(79,142,247,0.15) 0%, rgba(123,92,240,0.15) 100%)"
                    : "rgba(255,255,255,0.04)",
                  backdropFilter: "blur(12px)",
                  border: `1px solid ${isSelected ? "rgba(79,142,247,0.45)" : "var(--border-glass)"}`,
                  borderRadius: 16, padding: "18px 20px", cursor: "pointer",
                  transition: "all 0.15s", position: "relative", overflow: "hidden",
                }}
                onMouseEnter={e => { if (!isSelected) { e.currentTarget.style.borderColor = "rgba(255,255,255,0.16)"; e.currentTarget.style.transform = "translateY(-2px)"; } }}
                onMouseLeave={e => { if (!isSelected) { e.currentTarget.style.borderColor = "var(--border-glass)"; e.currentTarget.style.transform = ""; } }}
              >
                {/* Top accent */}
                {isSelected && <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2, background: "linear-gradient(90deg,#4f8ef7,#7b5cf0)", borderRadius: "16px 16px 0 0" }} />}

                {/* Assignee name + initials */}
                <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 14 }}>
                  <div style={{
                    width: 36, height: 36, borderRadius: "50%", flexShrink: 0,
                    background: "linear-gradient(135deg, #4f8ef7 0%, #7b5cf0 100%)",
                    display: "flex", alignItems: "center", justifyContent: "center",
                    fontSize: 12, fontWeight: 700, color: "#fff",
                    boxShadow: "0 0 12px rgba(79,142,247,0.3)",
                  }}>
                    {node.assignee.split(" ").map(w => w[0]).join("").toUpperCase().slice(0, 2)}
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text-primary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{node.assignee}</div>
                    <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 1 }}>{node.total} task{node.total !== 1 ? "s" : ""}</div>
                  </div>
                </div>

                {/* Status bar */}
                <div style={{ marginBottom: 12 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                    <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>Completion</span>
                    <span style={{ fontSize: 11, fontWeight: 600, color: "#22d3a8" }}>{completionPct}%</span>
                  </div>
                  <div style={{ height: 4, borderRadius: 999, background: "rgba(255,255,255,0.08)", overflow: "hidden" }}>
                    <div style={{ height: "100%", width: `${completionPct}%`, borderRadius: 999, background: "linear-gradient(90deg,#22d3a8,#06b6d4)", transition: "width 0.5s ease" }} />
                  </div>
                </div>

                {/* Status mini-badges */}
                <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                  {[
                    { key: "to_do",       label: "To Do"  },
                    { key: "in_progress", label: "Active" },
                    { key: "completed",   label: "Done"   },
                  ].map(s => node[s.key] > 0 && (
                    <span key={s.key} style={{
                      padding: "2px 8px", borderRadius: 999, fontSize: 11, fontWeight: 500,
                      background: `${STATUS_COLOR[s.key]}18`,
                      color: STATUS_COLOR[s.key],
                      border: `1px solid ${STATUS_COLOR[s.key]}40`,
                    }}>
                      {node[s.key]} {s.label}
                    </span>
                  ))}
                  {node.critical > 0 && (
                    <span style={{
                      padding: "2px 8px", borderRadius: 999, fontSize: 11, fontWeight: 500,
                      background: "rgba(248,113,113,0.1)", color: "#f87171",
                      border: "1px solid rgba(248,113,113,0.3)",
                    }}>🔴 {node.critical} Critical</span>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        {/* Detail panel */}
        {selectedNode && (
          <div style={{
            background: "rgba(255,255,255,0.04)", backdropFilter: "blur(12px)",
            border: "1px solid var(--border-glass)", borderRadius: 16, padding: "20px",
            position: "sticky", top: 80, maxHeight: "calc(100vh - 120px)", overflowY: "auto",
          }}>
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16 }}>
              <div style={{ fontSize: 14, fontWeight: 700, color: "var(--color-text-primary)" }}>{selectedNode.assignee}</div>
              <button onClick={() => setSelected(null)} style={{ background: "transparent", border: "none", cursor: "pointer", color: "var(--color-text-tertiary)", fontSize: 16, lineHeight: 1 }}>✕</button>
            </div>

            {/* Priority breakdown */}
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--color-text-tertiary)", marginBottom: 8 }}>Priority Breakdown</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
                {["critical", "high", "medium", "low"].map(p => (
                  <div key={p} style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span style={{ width: 8, height: 8, borderRadius: "50%", background: PRIORITY_COLOR[p], flexShrink: 0 }} />
                    <span style={{ fontSize: 12, color: "var(--color-text-secondary)", flex: 1, textTransform: "capitalize" }}>{p}</span>
                    <span style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text-primary)" }}>{selectedNode[p]}</span>
                    <div style={{ width: 60, height: 4, borderRadius: 999, background: "rgba(255,255,255,0.08)", overflow: "hidden" }}>
                      <div style={{ height: "100%", width: `${selectedNode.total > 0 ? (selectedNode[p] / selectedNode.total) * 100 : 0}%`, borderRadius: 999, background: PRIORITY_COLOR[p] }} />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            {/* Task list */}
            <div>
              <div style={{ fontSize: 11, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.06em", color: "var(--color-text-tertiary)", marginBottom: 8 }}>All Tasks</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
                {selectedNode.tasks.map(task => (
                  <div key={task.id} style={{
                    padding: "10px 12px", borderRadius: 10,
                    background: "rgba(255,255,255,0.04)", border: "1px solid var(--border-glass)",
                  }}>
                    <div style={{ fontSize: 12, fontWeight: 500, color: "var(--color-text-primary)", marginBottom: 5, lineHeight: 1.4 }}>{task.title}</div>
                    <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                      <span style={{ fontSize: 10, padding: "1px 7px", borderRadius: 999, background: `${STATUS_COLOR[task.status] || "#888"}18`, color: STATUS_COLOR[task.status] || "#888", border: `1px solid ${STATUS_COLOR[task.status] || "#888"}30` }}>
                        {task.status.replace("_", " ")}
                      </span>
                      <span style={{ fontSize: 10, padding: "1px 7px", borderRadius: 999, background: `${PRIORITY_COLOR[task.priority] || "#888"}18`, color: PRIORITY_COLOR[task.priority] || "#888", border: `1px solid ${PRIORITY_COLOR[task.priority] || "#888"}30` }}>
                        {task.priority}
                      </span>
                      {task.deadline && (
                        <span style={{ fontSize: 10, padding: "1px 7px", borderRadius: 999, background: "rgba(255,255,255,0.05)", color: "var(--color-text-tertiary)", border: "1px solid var(--border-glass)" }}>
                          📅 {task.deadline}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </main>
  );
}

// ── Tasks Page ────────────────────────────────────────────────────────────────
function TasksPage() {
  const { token, isArchitect, isNavigator, user } = useAuth();
  const API = BASE_URL;

  // Reuse the same useTasks hook that Dashboard uses — already handles auth
  const taskFilters = user?.role === "operator" ? { assignee_id: user.id }
    : user?.role === "navigator"                ? { team_id: user.team_id }
    : {};
  const { tasks, loading, error: taskError, submitting: hookSub, moveTask, removeTask, addTask, reload } = useTasks(taskFilters);

  const [search, setSearch]       = useState("");
  const [statusFilter, setStatus] = useState("all");
  const [priorityFilter, setPri]  = useState("all");
  const [showForm, setShowForm]   = useState(false);
  const [editTask, setEditTask]   = useState(null);
  const [submitting, setSub]      = useState(false);
  const [error, setError]         = useState(null);
  const [successMsg, setSuccess]  = useState(null);

  // Merge hook error with local error
  const displayError = error || taskError;

  // Form state
  const [form, setForm] = useState({ title: "", assignee: "", priority: "medium", deadline: "", description: "" });

  const hdrs = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };

  const load = reload;

  const flash = (msg) => { setSuccess(msg); setTimeout(() => setSuccess(null), 3000); };

  const openCreate = () => {
    setForm({ title: "", assignee: "", priority: "medium", deadline: "", description: "" });
    setEditTask(null);
    setShowForm(true);
  };

  const openEdit = (t) => {
    setForm({
      title: t.title || t.task_description || "",
      assignee: t.assignee || "",
      priority: t.priority || "medium",
      deadline: t.deadline ? t.deadline.slice(0, 10) : "",
      description: t.task_description || "",
    });
    setEditTask(t);
    setShowForm(true);
  };

  const handleSubmit = async () => {
    if (!form.title.trim()) return;
    setSub(true);
    try {
      if (editTask) {
        const r = await fetch(`${API}/tasks/${editTask.id}`, {
          method: "PUT",
          headers: hdrs,
          body: JSON.stringify({ title: form.title, assignee: form.assignee, priority: form.priority, deadline: form.deadline || null, task_description: form.description }),
        });
        if (!r.ok) throw new Error("Update failed");
        flash("Task updated ✓");
        reload();
      } else {
        const msg = `${form.priority === "high" ? "URGENT " : ""}create task ${form.assignee ? `@${form.assignee}` : ""} ${form.title}${form.deadline ? ` by ${form.deadline}` : ""}`;
        await addTask(msg);
        flash("Task created ✓");
      }
      setShowForm(false);
      load();
    } catch (e) { setError(e.message); }
    finally { setSub(false); }
  };

  const changeStatus = async (taskId, newStatus) => {
    try {
      await moveTask(taskId, newStatus);
    } catch (e) { setError("Status update failed"); }
  };

  const deleteTask = async (taskId) => {
    if (!window.confirm("Delete this task?")) return;
    try {
      await removeTask(taskId);
      flash("Task deleted");
    } catch { setError("Delete failed"); }
  };

  const filtered = useMemo(() => tasks.filter(t => {
    const q = search.toLowerCase();
    const matchQ = !q || (t.title || t.task_description || "").toLowerCase().includes(q) || (t.assignee || "").toLowerCase().includes(q);
    const matchS = statusFilter === "all" || t.status === statusFilter;
    const matchP = priorityFilter === "all" || (t.priority || "medium") === priorityFilter;
    return matchQ && matchS && matchP;
  }), [tasks, search, statusFilter, priorityFilter]);

  const PRIORITY_COLOR = { high: "#f87171", medium: "#f59e0b", low: "#22d3a8" };
  const STATUS_COLOR   = { to_do: "#4f8ef7", in_progress: "#a78bfa", completed: "#22d3a8", cancelled: "#6b7280" };
  const STATUS_LABEL   = { to_do: "To Do", in_progress: "In Progress", completed: "Done", cancelled: "Cancelled" };

  const pill = (color, label) => (
    <span style={{ display:"inline-flex", alignItems:"center", gap:5, padding:"2px 9px", borderRadius:999, fontSize:11, fontWeight:600, background:`${color}18`, color, border:`1px solid ${color}33` }}>
      <span style={{ width:5, height:5, borderRadius:"50%", background:color }} />{label}
    </span>
  );

  const counts = useMemo(() => ({
    all: tasks.length,
    to_do: tasks.filter(t => t.status === "to_do").length,
    in_progress: tasks.filter(t => t.status === "in_progress").length,
    completed: tasks.filter(t => t.status === "completed").length,
  }), [tasks]);

  const inputStyle = {
    width:"100%", height:38, padding:"0 12px",
    background:"rgba(255,255,255,0.06)", border:"1px solid var(--border-glass)",
    borderRadius:8, fontFamily:"var(--font-sans)", fontSize:13,
    color:"var(--color-text-primary)", outline:"none",
    boxSizing:"border-box",
  };
  const labelStyle = { fontSize:11, fontWeight:600, color:"var(--color-text-secondary)", textTransform:"uppercase", letterSpacing:"0.05em", marginBottom:5, display:"block" };

  return (
    <>
      {/* Topbar */}
      <header style={{ position:"sticky", top:0, zIndex:40, height:60, background:"rgba(13,15,30,0.88)", backdropFilter:"blur(16px)", WebkitBackdropFilter:"blur(16px)", borderBottom:"1px solid var(--border-glass)", padding:"0 28px", display:"flex", alignItems:"center", gap:14 }}>
        <div>
          <div style={{ fontSize:15, fontWeight:700, color:"var(--color-text-primary)", letterSpacing:"-0.02em" }}>Tasks</div>
          <div style={{ fontSize:11, color:"var(--color-text-tertiary)" }}>{counts.all} total · {counts.in_progress} in progress</div>
        </div>

        {/* Search */}
        <div style={{ flex:1, maxWidth:320, position:"relative" }}>
          <svg style={{ position:"absolute", left:10, top:"50%", transform:"translateY(-50%)", width:13, height:13, color:"var(--color-text-tertiary)", pointerEvents:"none" }} viewBox="0 0 16 16" fill="none"><circle cx="6.5" cy="6.5" r="4.5" stroke="currentColor" strokeWidth="1.3"/><path d="M10 10l3.5 3.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/></svg>
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search tasks or assignees…" style={{ ...inputStyle, paddingLeft:30, borderRadius:999, height:36 }} />
        </div>

        {/* Status filter */}
        <div style={{ display:"flex", gap:3, background:"rgba(255,255,255,0.04)", border:"1px solid var(--border-glass)", borderRadius:999, padding:3 }}>
          {[["all","All"], ["to_do","To Do"], ["in_progress","In Progress"], ["completed","Done"]].map(([val, lbl]) => (
            <button key={val} onClick={() => setStatus(val)} style={{ padding:"4px 12px", borderRadius:999, fontSize:12, fontWeight:600, cursor:"pointer", border:"none", fontFamily:"var(--font-sans)", background:statusFilter===val?"linear-gradient(135deg,#4f8ef7,#7b5cf0)":"transparent", color:statusFilter===val?"#fff":"var(--color-text-secondary)", transition:"all 0.15s" }}>{lbl}</button>
          ))}
        </div>

        {/* Priority filter */}
        <select value={priorityFilter} onChange={e => setPri(e.target.value)} style={{ height:34, padding:"0 10px", background:"rgba(255,255,255,0.06)", border:"1px solid var(--border-glass)", borderRadius:8, fontFamily:"var(--font-sans)", fontSize:12, color:"var(--color-text-primary)", cursor:"pointer", outline:"none" }}>
          <option value="all" style={{background:"#1e2140",color:"#f0f2ff"}}>All Priorities</option>
          <option value="high" style={{background:"#1e2140",color:"#f0f2ff"}}>🔴 High</option>
          <option value="medium" style={{background:"#1e2140",color:"#f0f2ff"}}>🟡 Medium</option>
          <option value="low" style={{background:"#1e2140",color:"#f0f2ff"}}>🟢 Low</option>
        </select>

        <button onClick={openCreate} style={{ height:36, padding:"0 18px", borderRadius:999, border:"none", background:"linear-gradient(135deg,#4f8ef7,#7b5cf0)", color:"#fff", fontFamily:"var(--font-sans)", fontSize:13, fontWeight:600, cursor:"pointer", whiteSpace:"nowrap", boxShadow:"0 0 20px rgba(79,142,247,0.35)", marginLeft:"auto" }}>
          + New Task
        </button>
      </header>

      <main style={{ flex:1, padding:"24px 28px 40px" }}>
        {/* Flash messages */}
        {successMsg && (
          <div style={{ padding:"10px 16px", borderRadius:8, background:"rgba(34,211,168,0.12)", border:"1px solid rgba(34,211,168,0.3)", color:"#22d3a8", fontSize:13, fontWeight:600, marginBottom:16 }}>✓ {successMsg}</div>
        )}
        {displayError && (
          <div style={{ padding:"10px 16px", borderRadius:8, background:"rgba(248,113,113,0.1)", border:"1px solid rgba(248,113,113,0.25)", color:"#f87171", fontSize:13, marginBottom:16, display:"flex", justifyContent:"space-between" }}>
            <span>⚠ {displayError}</span>
            <button onClick={() => setError(null)} style={{ background:"none", border:"none", color:"#f87171", cursor:"pointer", fontSize:16 }}>×</button>
          </div>
        )}

        {/* Summary cards */}
        <div style={{ display:"grid", gridTemplateColumns:"repeat(4,1fr)", gap:14, marginBottom:24 }}>
          {[
            { label:"Total Tasks", value:counts.all, color:"#4f8ef7" },
            { label:"To Do", value:counts.to_do, color:"#a78bfa" },
            { label:"In Progress", value:counts.in_progress, color:"#f59e0b" },
            { label:"Completed", value:counts.completed, color:"#22d3a8" },
          ].map(m => (
            <div key={m.label} style={{ background:"rgba(255,255,255,0.04)", border:"1px solid var(--border-glass)", borderRadius:14, padding:"16px 18px", position:"relative", overflow:"hidden" }}>
              <div style={{ position:"absolute", top:0, left:0, right:0, height:2, background:m.color, opacity:0.7 }} />
              <div style={{ fontSize:11, fontWeight:600, color:"var(--color-text-secondary)", textTransform:"uppercase", letterSpacing:"0.05em", marginBottom:6 }}>{m.label}</div>
              <div style={{ fontSize:28, fontWeight:700, color:m.color }}>{loading ? "—" : m.value}</div>
            </div>
          ))}
        </div>

        {/* Task table */}
        <div style={{ background:"rgba(255,255,255,0.03)", border:"1px solid var(--border-glass)", borderRadius:16, overflow:"hidden" }}>
          {/* Table header */}
          <div style={{ display:"grid", gridTemplateColumns:"2fr 1fr 100px 110px 130px 120px", gap:0, padding:"10px 18px", borderBottom:"1px solid var(--border-glass)", background:"rgba(255,255,255,0.03)" }}>
            {["Task", "Assignee", "Priority", "Status", "Deadline", "Actions"].map(h => (
              <div key={h} style={{ fontSize:11, fontWeight:700, color:"var(--color-text-tertiary)", textTransform:"uppercase", letterSpacing:"0.06em" }}>{h}</div>
            ))}
          </div>

          {loading ? (
            <div style={{ padding:"48px 0", textAlign:"center" }}>
              <div style={{ width:24, height:24, border:"2px solid rgba(79,142,247,0.2)", borderTopColor:"#4f8ef7", borderRadius:"50%", animation:"spin 0.7s linear infinite", margin:"0 auto 10px" }} />
              <div style={{ fontSize:13, color:"var(--color-text-tertiary)" }}>Loading tasks…</div>
            </div>
          ) : filtered.length === 0 ? (
            <div style={{ padding:"48px 0", textAlign:"center" }}>
              <div style={{ fontSize:36, marginBottom:10, opacity:0.3 }}>✦</div>
              <div style={{ fontSize:14, color:"var(--color-text-tertiary)" }}>No tasks found</div>
              <div style={{ fontSize:12, color:"var(--color-text-tertiary)", marginTop:4 }}>Try changing filters or create a new task</div>
            </div>
          ) : (
            filtered.map((t, i) => {
              const pri   = t.priority || "medium";
              const st    = t.status || "to_do";
              const title = t.title || t.task_description || "Untitled";
              return (
                <div key={t.id} style={{ display:"grid", gridTemplateColumns:"2fr 1fr 100px 110px 130px 120px", gap:0, padding:"13px 18px", borderBottom: i < filtered.length-1 ? "1px solid rgba(255,255,255,0.04)" : "none", alignItems:"center", transition:"background 0.15s" }}
                  onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.03)"}
                  onMouseLeave={e => e.currentTarget.style.background = "transparent"}
                >
                  {/* Title */}
                  <div style={{ fontSize:13, color:"var(--color-text-primary)", fontWeight:500, overflow:"hidden", textOverflow:"ellipsis", whiteSpace:"nowrap", paddingRight:12 }} title={title}>{title}</div>

                  {/* Assignee */}
                  <div style={{ fontSize:12, color:"var(--color-text-secondary)", display:"flex", alignItems:"center", gap:6 }}>
                    {t.assignee ? (
                      <><span style={{ width:22, height:22, borderRadius:"50%", background:"linear-gradient(135deg,#4f8ef7,#7b5cf0)", display:"inline-flex", alignItems:"center", justifyContent:"center", fontSize:10, fontWeight:700, color:"#fff", flexShrink:0 }}>{t.assignee[0]?.toUpperCase()}</span>{t.assignee}</>
                    ) : <span style={{ color:"var(--color-text-tertiary)" }}>Unassigned</span>}
                  </div>

                  {/* Priority */}
                  <div>{pill(PRIORITY_COLOR[pri] || "#f59e0b", pri.charAt(0).toUpperCase()+pri.slice(1))}</div>

                  {/* Status */}
                  <div>
                    <select value={st} onChange={e => changeStatus(t.id, e.target.value)}
                      style={{ fontSize:11, fontWeight:600, background:`${STATUS_COLOR[st] || "#4f8ef7"}18`, color:STATUS_COLOR[st] || "#4f8ef7", border:`1px solid ${STATUS_COLOR[st] || "#4f8ef7"}33`, borderRadius:999, padding:"3px 8px", cursor:"pointer", outline:"none", fontFamily:"var(--font-sans)" }}>
                      {Object.entries(STATUS_LABEL).map(([v,l]) => <option key={v} value={v} style={{background:"#1e2140",color:"#f0f2ff"}}>{l}</option>)}
                    </select>
                  </div>

                  {/* Deadline */}
                  <div style={{ fontSize:12, color: t.deadline && new Date(t.deadline) < new Date() ? "#f87171" : "var(--color-text-secondary)" }}>
                    {t.deadline ? new Date(t.deadline).toLocaleDateString("en-US", { month:"short", day:"numeric", year:"numeric" }) : <span style={{ color:"var(--color-text-tertiary)" }}>—</span>}
                  </div>

                  {/* Actions */}
                  <div style={{ display:"flex", gap:6 }}>
                    {(isArchitect || isNavigator) && (
                      <button onClick={() => openEdit(t)} title="Edit" style={{ width:28, height:28, borderRadius:7, border:"1px solid var(--border-glass)", background:"transparent", color:"var(--color-text-secondary)", cursor:"pointer", fontSize:13, display:"flex", alignItems:"center", justifyContent:"center" }}
                        onMouseEnter={e => { e.currentTarget.style.background="rgba(79,142,247,0.15)"; e.currentTarget.style.color="#4f8ef7"; }}
                        onMouseLeave={e => { e.currentTarget.style.background="transparent"; e.currentTarget.style.color="var(--color-text-secondary)"; }}>✎</button>
                    )}
                    {isArchitect && (
                      <button onClick={() => deleteTask(t.id)} title="Delete" style={{ width:28, height:28, borderRadius:7, border:"1px solid var(--border-glass)", background:"transparent", color:"var(--color-text-secondary)", cursor:"pointer", fontSize:14, display:"flex", alignItems:"center", justifyContent:"center" }}
                        onMouseEnter={e => { e.currentTarget.style.background="rgba(248,113,113,0.12)"; e.currentTarget.style.color="#f87171"; }}
                        onMouseLeave={e => { e.currentTarget.style.background="transparent"; e.currentTarget.style.color="var(--color-text-secondary)"; }}>✕</button>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </main>

      {/* Create / Edit Modal */}
      {showForm && (
        <div style={{ position:"fixed", inset:0, zIndex:200, background:"rgba(0,0,0,0.6)", backdropFilter:"blur(6px)", display:"flex", alignItems:"center", justifyContent:"center" }}
          onClick={e => { if (e.target === e.currentTarget) setShowForm(false); }}>
          <div style={{ width:480, background:"#141628", border:"1px solid var(--border-glass)", borderRadius:20, padding:"28px 28px 24px", boxShadow:"0 24px 80px rgba(0,0,0,0.6)" }}>
            <div style={{ display:"flex", justifyContent:"space-between", alignItems:"center", marginBottom:22 }}>
              <div style={{ fontSize:16, fontWeight:700, color:"var(--color-text-primary)" }}>{editTask ? "Edit Task" : "Create Task"}</div>
              <button onClick={() => setShowForm(false)} style={{ width:28, height:28, borderRadius:"50%", border:"1px solid var(--border-glass)", background:"transparent", color:"var(--color-text-secondary)", cursor:"pointer", fontSize:16 }}>×</button>
            </div>

            <div style={{ display:"flex", flexDirection:"column", gap:14 }}>
              <div>
                <label style={labelStyle}>Task Title *</label>
                <input value={form.title} onChange={e => setForm(f => ({...f, title:e.target.value}))} placeholder="What needs to be done?" style={inputStyle} />
              </div>
              <div>
                <label style={labelStyle}>Assignee</label>
                <input value={form.assignee} onChange={e => setForm(f => ({...f, assignee:e.target.value}))} placeholder="username or name" style={inputStyle} />
              </div>
              <div style={{ display:"grid", gridTemplateColumns:"1fr 1fr", gap:12 }}>
                <div>
                  <label style={labelStyle}>Priority</label>
                  <select value={form.priority} onChange={e => setForm(f => ({...f, priority:e.target.value}))} style={{ ...inputStyle, cursor:"pointer" }}>
                    <option value="high" style={{background:"#1e2140",color:"#f0f2ff"}}>🔴 High</option>
                    <option value="medium" style={{background:"#1e2140",color:"#f0f2ff"}}>🟡 Medium</option>
                    <option value="low" style={{background:"#1e2140",color:"#f0f2ff"}}>🟢 Low</option>
                  </select>
                </div>
                <div>
                  <label style={labelStyle}>Deadline</label>
                  <input type="date" value={form.deadline} onChange={e => setForm(f => ({...f, deadline:e.target.value}))} style={{ ...inputStyle, colorScheme:"dark" }} />
                </div>
              </div>
              {editTask && (
                <div>
                  <label style={labelStyle}>Description</label>
                  <textarea value={form.description} onChange={e => setForm(f => ({...f, description:e.target.value}))} rows={3} placeholder="Additional details…" style={{ ...inputStyle, height:"auto", padding:"10px 12px", resize:"vertical" }} />
                </div>
              )}
            </div>

            <div style={{ display:"flex", justifyContent:"flex-end", gap:10, marginTop:22 }}>
              <button onClick={() => setShowForm(false)} style={{ height:38, padding:"0 18px", borderRadius:8, border:"1px solid var(--border-glass)", background:"transparent", color:"var(--color-text-secondary)", fontFamily:"var(--font-sans)", fontSize:13, cursor:"pointer" }}>Cancel</button>
              <button onClick={handleSubmit} disabled={submitting || !form.title.trim()} style={{ height:38, padding:"0 22px", borderRadius:8, border:"none", background:"linear-gradient(135deg,#4f8ef7,#7b5cf0)", color:"#fff", fontFamily:"var(--font-sans)", fontSize:13, fontWeight:600, cursor:submitting ? "not-allowed" : "pointer", opacity:submitting ? 0.7 : 1 }}>
                {submitting ? "Saving…" : editTask ? "Save Changes" : "Create Task"}
              </button>
            </div>
          </div>
        </div>
      )}
    </>
  );
}


// ── Reports Page ──────────────────────────────────────────────────────────────
function ReportsPage() {
  const { user } = useAuth();
  const taskFilters = user?.role === "operator" ? { assignee_id: user.id }
    : user?.role === "navigator"                ? { team_id: user.team_id }
    : {};
  const { tasks, loading } = useTasks(taskFilters);

  const [range, setRange] = useState(30); // days

  const now = new Date();

  const stats = useMemo(() => {
    if (!tasks.length) return null;
    const cutoff = new Date(now - range * 86400000);
    const inRange = tasks.filter(t => new Date(t.created_at) >= cutoff);

    const byStatus = { to_do: 0, in_progress: 0, completed: 0, cancelled: 0 };
    tasks.forEach(t => { if (byStatus[t.status] !== undefined) byStatus[t.status]++; });

    const byPriority = { high: 0, medium: 0, low: 0, critical: 0 };
    tasks.forEach(t => { const p = t.priority || "medium"; if (byPriority[p] !== undefined) byPriority[p]++; });

    // Assignee leaderboard
    const assigneeCounts = {};
    tasks.forEach(t => {
      if (t.assignee) {
        if (!assigneeCounts[t.assignee]) assigneeCounts[t.assignee] = { total: 0, done: 0 };
        assigneeCounts[t.assignee].total++;
        if (t.status === "completed") assigneeCounts[t.assignee].done++;
      }
    });
    const leaderboard = Object.entries(assigneeCounts)
      .map(([name, d]) => ({ name, total: d.total, done: d.done, rate: d.total ? Math.round(d.done / d.total * 100) : 0 }))
      .sort((a, b) => b.total - a.total)
      .slice(0, 8);

    // Daily creation trend (last 14 days)
    const trend = [];
    for (let i = 13; i >= 0; i--) {
      const day = new Date(now - i * 86400000);
      const label = day.toLocaleDateString("en-US", { month: "short", day: "numeric" });
      const count = tasks.filter(t => {
        const d = new Date(t.created_at);
        return d.toDateString() === day.toDateString();
      }).length;
      trend.push({ label, count });
    }

    // Overdue
    const overdue = tasks.filter(t =>
      t.deadline && new Date(t.deadline) < now && t.status !== "completed" && t.status !== "cancelled"
    );

    const completionRate = tasks.length ? Math.round(byStatus.completed / tasks.length * 100) : 0;
    const avgPerDay = range > 0 ? (inRange.length / range).toFixed(1) : 0;

    return { byStatus, byPriority, leaderboard, trend, overdue, completionRate, avgPerDay, inRange: inRange.length };
  }, [tasks, range]);

  const maxTrend = stats ? Math.max(...stats.trend.map(d => d.count), 1) : 1;

  const Card = ({ children, style }) => (
    <div style={{ background: "rgba(255,255,255,0.04)", border: "1px solid var(--border-glass)", borderRadius: 16, padding: "20px 22px", ...style }}>{children}</div>
  );

  const SectionTitle = ({ children }) => (
    <div style={{ fontSize: 12, fontWeight: 700, color: "var(--color-text-tertiary)", textTransform: "uppercase", letterSpacing: "0.07em", marginBottom: 14 }}>{children}</div>
  );

  const STATUS_C = { to_do: "#4f8ef7", in_progress: "#f59e0b", completed: "#22d3a8", cancelled: "#6b7280" };
  const STATUS_L = { to_do: "To Do", in_progress: "In Progress", completed: "Done", cancelled: "Cancelled" };
  const PRI_C    = { critical: "#f43f5e", high: "#f87171", medium: "#f59e0b", low: "#22d3a8" };

  return (
    <>
      {/* Topbar */}
      <header style={{ position: "sticky", top: 0, zIndex: 40, height: 60, background: "rgba(13,15,30,0.88)", backdropFilter: "blur(16px)", WebkitBackdropFilter: "blur(16px)", borderBottom: "1px solid var(--border-glass)", padding: "0 28px", display: "flex", alignItems: "center", gap: 16 }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: "var(--color-text-primary)", letterSpacing: "-0.02em" }}>Reports</div>
          <div style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>Workspace analytics & performance</div>
        </div>
        <div style={{ marginLeft: "auto", display: "flex", gap: 4, background: "rgba(255,255,255,0.04)", border: "1px solid var(--border-glass)", borderRadius: 999, padding: 3 }}>
          {[7, 14, 30, 90].map(d => (
            <button key={d} onClick={() => setRange(d)} style={{ padding: "4px 14px", borderRadius: 999, fontSize: 12, fontWeight: 600, cursor: "pointer", border: "none", fontFamily: "var(--font-sans)", background: range === d ? "linear-gradient(135deg,#4f8ef7,#7b5cf0)" : "transparent", color: range === d ? "#fff" : "var(--color-text-secondary)", transition: "all 0.15s" }}>
              {d}d
            </button>
          ))}
        </div>
      </header>

      <main style={{ flex: 1, padding: "24px 28px 40px", display: "flex", flexDirection: "column", gap: 20 }}>

        {loading ? (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: "80px 0" }}>
            <div style={{ width: 28, height: 28, border: "2px solid rgba(79,142,247,0.2)", borderTopColor: "#4f8ef7", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />
          </div>
        ) : !stats ? (
          <div style={{ textAlign: "center", padding: "80px 0", color: "var(--color-text-tertiary)" }}>
            <div style={{ fontSize: 40, marginBottom: 12, opacity: 0.3 }}>▲</div>
            <div style={{ fontSize: 14 }}>No data yet — create some tasks to see reports</div>
          </div>
        ) : (
          <>
            {/* KPI row */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(4,1fr)", gap: 14 }}>
              {[
                { label: "Total Tasks", value: tasks.length, sub: `${stats.inRange} in last ${range}d`, color: "#4f8ef7" },
                { label: "Completed", value: stats.byStatus.completed, sub: `${stats.completionRate}% completion rate`, color: "#22d3a8" },
                { label: "Overdue", value: stats.overdue.length, sub: stats.overdue.length ? "Need attention" : "All on track ✓", color: stats.overdue.length ? "#f87171" : "#22d3a8" },
                { label: "Avg / Day", value: stats.avgPerDay, sub: `Tasks created per day`, color: "#a78bfa" },
              ].map(m => (
                <Card key={m.label} style={{ position: "relative", overflow: "hidden" }}>
                  <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2, background: m.color, opacity: 0.8 }} />
                  <div style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>{m.label}</div>
                  <div style={{ fontSize: 32, fontWeight: 700, color: m.color, lineHeight: 1, marginBottom: 4 }}>{m.value}</div>
                  <div style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>{m.sub}</div>
                </Card>
              ))}
            </div>

            {/* Charts row */}
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 18 }}>

              {/* Status breakdown */}
              <Card>
                <SectionTitle>Task Status Breakdown</SectionTitle>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {Object.entries(STATUS_L).map(([key, label]) => {
                    const count = stats.byStatus[key] || 0;
                    const pct = tasks.length ? Math.round(count / tasks.length * 100) : 0;
                    return (
                      <div key={key}>
                        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                          <span style={{ fontSize: 12, color: "var(--color-text-secondary)", display: "flex", alignItems: "center", gap: 6 }}>
                            <span style={{ width: 8, height: 8, borderRadius: "50%", background: STATUS_C[key], display: "inline-block" }} />{label}
                          </span>
                          <span style={{ fontSize: 12, fontWeight: 700, color: STATUS_C[key] }}>{count} <span style={{ fontWeight: 400, color: "var(--color-text-tertiary)" }}>({pct}%)</span></span>
                        </div>
                        <div style={{ height: 6, background: "rgba(255,255,255,0.06)", borderRadius: 999, overflow: "hidden" }}>
                          <div style={{ height: "100%", width: `${pct}%`, background: STATUS_C[key], borderRadius: 999, transition: "width 0.6s cubic-bezier(.4,0,.2,1)" }} />
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Completion ring */}
                <div style={{ marginTop: 18, paddingTop: 16, borderTop: "1px solid var(--border-glass)", display: "flex", alignItems: "center", gap: 16 }}>
                  <div style={{ position: "relative", width: 70, height: 70, flexShrink: 0 }}>
                    <svg viewBox="0 0 36 36" style={{ width: 70, height: 70, transform: "rotate(-90deg)" }}>
                      <circle cx="18" cy="18" r="15" fill="none" stroke="rgba(255,255,255,0.07)" strokeWidth="3" />
                      <circle cx="18" cy="18" r="15" fill="none" stroke="#22d3a8" strokeWidth="3"
                        strokeDasharray={`${stats.completionRate * 0.942} 94.2`}
                        strokeLinecap="round" />
                    </svg>
                    <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 13, fontWeight: 700, color: "#22d3a8" }}>
                      {stats.completionRate}%
                    </div>
                  </div>
                  <div>
                    <div style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text-primary)" }}>Completion Rate</div>
                    <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 3 }}>{stats.byStatus.completed} of {tasks.length} tasks done</div>
                  </div>
                </div>
              </Card>

              {/* Priority breakdown */}
              <Card>
                <SectionTitle>Priority Distribution</SectionTitle>
                <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
                  {Object.entries(PRI_C).map(([key, color]) => {
                    const count = stats.byPriority[key] || 0;
                    if (!count) return null;
                    const pct = tasks.length ? Math.round(count / tasks.length * 100) : 0;
                    return (
                      <div key={key}>
                        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
                          <span style={{ fontSize: 12, color: "var(--color-text-secondary)", display: "flex", alignItems: "center", gap: 6, textTransform: "capitalize" }}>
                            <span style={{ width: 8, height: 8, borderRadius: "50%", background: color, display: "inline-block" }} />{key}
                          </span>
                          <span style={{ fontSize: 12, fontWeight: 700, color }}>{count} <span style={{ fontWeight: 400, color: "var(--color-text-tertiary)" }}>({pct}%)</span></span>
                        </div>
                        <div style={{ height: 6, background: "rgba(255,255,255,0.06)", borderRadius: 999, overflow: "hidden" }}>
                          <div style={{ height: "100%", width: `${pct}%`, background: color, borderRadius: 999, transition: "width 0.6s cubic-bezier(.4,0,.2,1)" }} />
                        </div>
                      </div>
                    );
                  })}
                </div>

                {/* Overdue alert */}
                {stats.overdue.length > 0 && (
                  <div style={{ marginTop: 18, paddingTop: 16, borderTop: "1px solid var(--border-glass)" }}>
                    <div style={{ fontSize: 11, fontWeight: 700, color: "#f87171", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 8 }}>⚠ Overdue Tasks ({stats.overdue.length})</div>
                    <div style={{ display: "flex", flexDirection: "column", gap: 6, maxHeight: 110, overflowY: "auto" }}>
                      {stats.overdue.map(t => (
                        <div key={t.id} style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
                          <span style={{ fontSize: 12, color: "var(--color-text-secondary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", maxWidth: "70%" }}>{t.title || t.task_description}</span>
                          <span style={{ fontSize: 11, color: "#f87171", flexShrink: 0 }}>{new Date(t.deadline).toLocaleDateString("en-US", { month: "short", day: "numeric" })}</span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </Card>
            </div>

            {/* Activity trend */}
            <Card>
              <SectionTitle>Task Creation Trend — Last 14 Days</SectionTitle>
              <div style={{ display: "flex", alignItems: "flex-end", gap: 6, height: 100 }}>
                {stats.trend.map((d, i) => (
                  <div key={i} style={{ flex: 1, display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
                    <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", fontWeight: 600 }}>{d.count || ""}</div>
                    <div style={{ width: "100%", borderRadius: "4px 4px 0 0", background: d.count ? "linear-gradient(180deg,#7b5cf0,#4f8ef7)" : "rgba(255,255,255,0.05)", transition: "height 0.5s cubic-bezier(.4,0,.2,1)", height: `${Math.max(4, (d.count / maxTrend) * 80)}px`, minHeight: 4 }}
                      title={`${d.label}: ${d.count} task${d.count !== 1 ? "s" : ""}`}
                    />
                    <div style={{ fontSize: 9, color: "var(--color-text-tertiary)", textAlign: "center", whiteSpace: "nowrap", overflow: "hidden", width: "100%", textOverflow: "ellipsis" }}>{i % 2 === 0 ? d.label : ""}</div>
                  </div>
                ))}
              </div>
            </Card>

            {/* Leaderboard */}
            <Card>
              <SectionTitle>Team Leaderboard — Tasks by Assignee</SectionTitle>
              {stats.leaderboard.length === 0 ? (
                <div style={{ fontSize: 13, color: "var(--color-text-tertiary)", textAlign: "center", padding: "20px 0" }}>No assignee data yet</div>
              ) : (
                <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
                  {stats.leaderboard.map((person, i) => (
                    <div key={person.name} style={{ display: "grid", gridTemplateColumns: "28px 1fr 80px 80px 100px", alignItems: "center", gap: 12, padding: "11px 0", borderBottom: i < stats.leaderboard.length - 1 ? "1px solid rgba(255,255,255,0.04)" : "none" }}>
                      <div style={{ fontSize: 13, fontWeight: 700, color: i === 0 ? "#f59e0b" : i === 1 ? "#9ca3af" : i === 2 ? "#b45309" : "var(--color-text-tertiary)", textAlign: "center" }}>#{i + 1}</div>
                      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                        <span style={{ width: 28, height: 28, borderRadius: "50%", background: `hsl(${(person.name.charCodeAt(0) * 37) % 360},60%,50%)`, display: "inline-flex", alignItems: "center", justifyContent: "center", fontSize: 11, fontWeight: 700, color: "#fff", flexShrink: 0 }}>{person.name[0]?.toUpperCase()}</span>
                        <span style={{ fontSize: 13, color: "var(--color-text-primary)", fontWeight: 500 }}>{person.name}</span>
                      </div>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "#4f8ef7", textAlign: "center" }}>{person.total} <span style={{ fontSize: 10, fontWeight: 400, color: "var(--color-text-tertiary)" }}>tasks</span></div>
                      <div style={{ fontSize: 13, fontWeight: 600, color: "#22d3a8", textAlign: "center" }}>{person.done} <span style={{ fontSize: 10, fontWeight: 400, color: "var(--color-text-tertiary)" }}>done</span></div>
                      <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                        <div style={{ flex: 1, height: 5, background: "rgba(255,255,255,0.06)", borderRadius: 999, overflow: "hidden" }}>
                          <div style={{ height: "100%", width: `${person.rate}%`, background: person.rate >= 75 ? "#22d3a8" : person.rate >= 40 ? "#f59e0b" : "#f87171", borderRadius: 999 }} />
                        </div>
                        <span style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-secondary)", minWidth: 32 }}>{person.rate}%</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </>
        )}
      </main>
    </>
  );
}


// ── Compliance Page ───────────────────────────────────────────────────────────
function CompliancePage() {
  const { user } = useAuth();
  const taskFilters = user?.role === "operator" ? { assignee_id: user.id }
    : user?.role === "navigator"                ? { team_id: user.team_id }
    : {};
  const { tasks, loading } = useTasks(taskFilters);

  const [activeTab, setActiveTab] = useState("overdue");

  const now = new Date();

  const compliance = useMemo(() => {
    if (!tasks.length) return null;

    // Overdue tasks (past deadline, not done/cancelled)
    const overdue = tasks.filter(t =>
      t.deadline && new Date(t.deadline) < now &&
      t.status !== "completed" && t.status !== "cancelled"
    ).sort((a, b) => new Date(a.deadline) - new Date(b.deadline));

    // Unassigned tasks
    const unassigned = tasks.filter(t =>
      !t.assignee && t.status !== "completed" && t.status !== "cancelled"
    );

    // Stale tasks — in_progress for more than 7 days
    const stale = tasks.filter(t => {
      if (t.status !== "in_progress") return false;
      const updated = new Date(t.updated_at || t.created_at);
      return (now - updated) > 7 * 86400000;
    });

    // No-deadline tasks (active, no deadline set)
    const noDeadline = tasks.filter(t =>
      !t.deadline && t.status !== "completed" && t.status !== "cancelled"
    );

    // High priority not started
    const highNotStarted = tasks.filter(t =>
      (t.priority === "high" || t.priority === "critical") && t.status === "to_do"
    );

    // Compliance score (0-100)
    const issues = overdue.length + unassigned.length + stale.length + highNotStarted.length;
    const score = Math.max(0, Math.round(100 - (issues / Math.max(tasks.length, 1)) * 100));

    // Audit log — recent task activity (simulate from task data)
    const recent = [...tasks]
      .sort((a, b) => new Date(b.updated_at || b.created_at) - new Date(a.updated_at || a.created_at))
      .slice(0, 20);

    return { overdue, unassigned, stale, noDeadline, highNotStarted, score, issues, recent };
  }, [tasks]);

  const TABS = [
    { key: "overdue",        label: "Overdue",          badge: compliance?.overdue.length },
    { key: "unassigned",     label: "Unassigned",        badge: compliance?.unassigned.length },
    { key: "stale",          label: "Stale (7d+)",       badge: compliance?.stale.length },
    { key: "high_priority",  label: "High Not Started",  badge: compliance?.highNotStarted.length },
    { key: "audit",          label: "Audit Log",         badge: null },
  ];

  const currentList =
    activeTab === "overdue"       ? compliance?.overdue :
    activeTab === "unassigned"    ? compliance?.unassigned :
    activeTab === "stale"         ? compliance?.stale :
    activeTab === "high_priority" ? compliance?.highNotStarted :
    compliance?.recent;

  const STATUS_C = { to_do: "#4f8ef7", in_progress: "#f59e0b", completed: "#22d3a8", cancelled: "#6b7280" };
  const STATUS_L = { to_do: "To Do", in_progress: "In Progress", completed: "Done", cancelled: "Cancelled" };
  const PRI_C    = { critical: "#f43f5e", high: "#f87171", medium: "#f59e0b", low: "#22d3a8" };

  const scoreColor = !compliance ? "#4f8ef7"
    : compliance.score >= 80 ? "#22d3a8"
    : compliance.score >= 50 ? "#f59e0b"
    : "#f87171";

  const daysSince = (dateStr) => {
    const d = dateStr ? Math.floor((now - new Date(dateStr)) / 86400000) : null;
    if (d === null) return "—";
    if (d === 0) return "Today";
    if (d === 1) return "Yesterday";
    return `${d}d ago`;
  };

  const daysOverdue = (dateStr) => {
    if (!dateStr) return "";
    const d = Math.floor((now - new Date(dateStr)) / 86400000);
    return d > 0 ? `${d}d overdue` : "Due today";
  };

  return (
    <>
      {/* Topbar */}
      <header style={{ position: "sticky", top: 0, zIndex: 40, height: 60, background: "rgba(13,15,30,0.88)", backdropFilter: "blur(16px)", WebkitBackdropFilter: "blur(16px)", borderBottom: "1px solid var(--border-glass)", padding: "0 28px", display: "flex", alignItems: "center", gap: 16 }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: "var(--color-text-primary)", letterSpacing: "-0.02em" }}>Compliance</div>
          <div style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>Task health monitoring & audit trail</div>
        </div>
        {compliance && (
          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 10 }}>
            <div style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>Compliance Score</div>
            <div style={{ fontSize: 22, fontWeight: 800, color: scoreColor, letterSpacing: "-0.03em" }}>{compliance.score}<span style={{ fontSize: 13, fontWeight: 500 }}>%</span></div>
            <div style={{ width: 80, height: 6, background: "rgba(255,255,255,0.06)", borderRadius: 999, overflow: "hidden" }}>
              <div style={{ height: "100%", width: `${compliance.score}%`, background: scoreColor, borderRadius: 999, transition: "width 0.6s ease" }} />
            </div>
          </div>
        )}
      </header>

      <main style={{ flex: 1, padding: "24px 28px 40px", display: "flex", flexDirection: "column", gap: 20 }}>

        {loading ? (
          <div style={{ display: "flex", alignItems: "center", justifyContent: "center", padding: "80px 0" }}>
            <div style={{ width: 28, height: 28, border: "2px solid rgba(79,142,247,0.2)", borderTopColor: "#4f8ef7", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />
          </div>
        ) : !compliance ? (
          <div style={{ textAlign: "center", padding: "80px 0", color: "var(--color-text-tertiary)" }}>
            <div style={{ fontSize: 40, marginBottom: 12, opacity: 0.3 }}>◈</div>
            <div>No tasks to analyse yet</div>
          </div>
        ) : (
          <>
            {/* Score cards */}
            <div style={{ display: "grid", gridTemplateColumns: "repeat(5,1fr)", gap: 12 }}>
              {[
                { label: "Overdue",          value: compliance.overdue.length,          color: compliance.overdue.length ? "#f87171" : "#22d3a8",  icon: "⏰" },
                { label: "Unassigned",       value: compliance.unassigned.length,       color: compliance.unassigned.length ? "#f59e0b" : "#22d3a8", icon: "👤" },
                { label: "Stale (7d+)",      value: compliance.stale.length,            color: compliance.stale.length ? "#f59e0b" : "#22d3a8",     icon: "💤" },
                { label: "High Not Started", value: compliance.highNotStarted.length,   color: compliance.highNotStarted.length ? "#f87171" : "#22d3a8", icon: "🔴" },
                { label: "No Deadline",      value: compliance.noDeadline.length,       color: compliance.noDeadline.length > 3 ? "#f59e0b" : "#22d3a8", icon: "📅" },
              ].map(m => (
                <div key={m.label} style={{ background: "rgba(255,255,255,0.04)", border: `1px solid ${m.value && m.color !== "#22d3a8" ? m.color + "33" : "var(--border-glass)"}`, borderRadius: 14, padding: "16px 16px 14px", position: "relative", overflow: "hidden" }}>
                  <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2, background: m.color, opacity: 0.7 }} />
                  <div style={{ fontSize: 18, marginBottom: 6 }}>{m.icon}</div>
                  <div style={{ fontSize: 26, fontWeight: 700, color: m.color, lineHeight: 1, marginBottom: 4 }}>{m.value}</div>
                  <div style={{ fontSize: 10, fontWeight: 600, color: "var(--color-text-tertiary)", textTransform: "uppercase", letterSpacing: "0.05em" }}>{m.label}</div>
                </div>
              ))}
            </div>

            {/* Compliance score bar */}
            <div style={{ background: "rgba(255,255,255,0.04)", border: "1px solid var(--border-glass)", borderRadius: 14, padding: "16px 20px", display: "flex", alignItems: "center", gap: 20 }}>
              <div>
                <div style={{ fontSize: 11, fontWeight: 700, color: "var(--color-text-tertiary)", textTransform: "uppercase", letterSpacing: "0.06em", marginBottom: 4 }}>Overall Health</div>
                <div style={{ fontSize: 28, fontWeight: 800, color: scoreColor }}>{compliance.score}%</div>
              </div>
              <div style={{ flex: 1 }}>
                <div style={{ height: 10, background: "rgba(255,255,255,0.06)", borderRadius: 999, overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${compliance.score}%`, background: `linear-gradient(90deg, ${scoreColor}, ${scoreColor}cc)`, borderRadius: 999, transition: "width 0.8s ease" }} />
                </div>
              </div>
              <div style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>
                {compliance.issues === 0 ? "✅ All tasks healthy" : `${compliance.issues} issue${compliance.issues !== 1 ? "s" : ""} need attention`}
              </div>
            </div>

            {/* Tabs */}
            <div style={{ background: "rgba(255,255,255,0.03)", border: "1px solid var(--border-glass)", borderRadius: 16, overflow: "hidden" }}>
              {/* Tab bar */}
              <div style={{ display: "flex", borderBottom: "1px solid var(--border-glass)", background: "rgba(255,255,255,0.02)" }}>
                {TABS.map(tab => (
                  <button key={tab.key} onClick={() => setActiveTab(tab.key)} style={{ flex: 1, padding: "12px 8px", fontSize: 12, fontWeight: 600, cursor: "pointer", border: "none", fontFamily: "var(--font-sans)", background: activeTab === tab.key ? "rgba(79,142,247,0.12)" : "transparent", color: activeTab === tab.key ? "#4f8ef7" : "var(--color-text-secondary)", borderBottom: activeTab === tab.key ? "2px solid #4f8ef7" : "2px solid transparent", transition: "all 0.15s", display: "flex", alignItems: "center", justifyContent: "center", gap: 6 }}>
                    {tab.label}
                    {tab.badge !== null && tab.badge !== undefined && (
                      <span style={{ minWidth: 18, height: 18, borderRadius: 999, background: tab.badge > 0 ? (tab.key === "audit" ? "#4f8ef7" : "#f87171") : "rgba(255,255,255,0.1)", color: "#fff", fontSize: 10, fontWeight: 700, display: "inline-flex", alignItems: "center", justifyContent: "center", padding: "0 5px" }}>{tab.badge}</span>
                    )}
                  </button>
                ))}
              </div>

              {/* Tab content */}
              <div style={{ minHeight: 200 }}>
                {/* Table header */}
                {activeTab !== "audit" && (
                  <div style={{ display: "grid", gridTemplateColumns: activeTab === "overdue" ? "2fr 1fr 100px 110px 120px" : "2fr 1fr 100px 110px", gap: 0, padding: "9px 18px", borderBottom: "1px solid rgba(255,255,255,0.04)", background: "rgba(255,255,255,0.02)" }}>
                    {["Task", "Assignee", "Priority", "Status", activeTab === "overdue" ? "Overdue" : null].filter(Boolean).map(h => (
                      <div key={h} style={{ fontSize: 10, fontWeight: 700, color: "var(--color-text-tertiary)", textTransform: "uppercase", letterSpacing: "0.07em" }}>{h}</div>
                    ))}
                  </div>
                )}

                {!currentList || currentList.length === 0 ? (
                  <div style={{ padding: "40px 0", textAlign: "center" }}>
                    <div style={{ fontSize: 28, marginBottom: 8, opacity: 0.3 }}>✓</div>
                    <div style={{ fontSize: 13, color: "var(--color-text-tertiary)" }}>
                      {activeTab === "audit" ? "No recent activity" : "No issues found — looking good!"}
                    </div>
                  </div>
                ) : activeTab === "audit" ? (
                  <div>
                    {currentList.map((t, i) => (
                      <div key={t.id} style={{ display: "flex", alignItems: "center", gap: 14, padding: "11px 18px", borderBottom: i < currentList.length - 1 ? "1px solid rgba(255,255,255,0.03)" : "none" }}
                        onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.02)"}
                        onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                        <div style={{ width: 8, height: 8, borderRadius: "50%", background: STATUS_C[t.status] || "#4f8ef7", flexShrink: 0 }} />
                        <div style={{ flex: 1, fontSize: 13, color: "var(--color-text-primary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{t.title || t.task_description || "Untitled"}</div>
                        <div style={{ fontSize: 12, color: "var(--color-text-tertiary)", flexShrink: 0 }}>{t.assignee || "Unassigned"}</div>
                        <div style={{ fontSize: 11, fontWeight: 600, color: STATUS_C[t.status], flexShrink: 0, minWidth: 70, textAlign: "right" }}>{STATUS_L[t.status]}</div>
                        <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", flexShrink: 0, minWidth: 70, textAlign: "right" }}>{daysSince(t.updated_at || t.created_at)}</div>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div>
                    {currentList.map((t, i) => {
                      const pri = t.priority || "medium";
                      const st  = t.status || "to_do";
                      const title = t.title || t.task_description || "Untitled";
                      return (
                        <div key={t.id} style={{ display: "grid", gridTemplateColumns: activeTab === "overdue" ? "2fr 1fr 100px 110px 120px" : "2fr 1fr 100px 110px", gap: 0, padding: "12px 18px", borderBottom: i < currentList.length - 1 ? "1px solid rgba(255,255,255,0.03)" : "none", alignItems: "center" }}
                          onMouseEnter={e => e.currentTarget.style.background = "rgba(255,255,255,0.02)"}
                          onMouseLeave={e => e.currentTarget.style.background = "transparent"}>
                          <div style={{ fontSize: 13, color: "var(--color-text-primary)", fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", paddingRight: 12 }} title={title}>{title}</div>
                          <div style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>{t.assignee || <span style={{ color: "var(--color-text-tertiary)" }}>—</span>}</div>
                          <div>
                            <span style={{ display: "inline-flex", alignItems: "center", gap: 4, padding: "2px 8px", borderRadius: 999, fontSize: 11, fontWeight: 600, background: `${PRI_C[pri] || "#f59e0b"}18`, color: PRI_C[pri] || "#f59e0b", border: `1px solid ${PRI_C[pri] || "#f59e0b"}33`, textTransform: "capitalize" }}>{pri}</span>
                          </div>
                          <div>
                            <span style={{ fontSize: 11, fontWeight: 600, color: STATUS_C[st], background: `${STATUS_C[st]}18`, border: `1px solid ${STATUS_C[st]}33`, borderRadius: 999, padding: "2px 8px" }}>{STATUS_L[st]}</span>
                          </div>
                          {activeTab === "overdue" && (
                            <div style={{ fontSize: 12, fontWeight: 600, color: "#f87171" }}>{daysOverdue(t.deadline)}</div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </main>
    </>
  );
}

function PlaceholderPage({ label }) {
  return (
    <main style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 40 }}>
      <div style={{ textAlign: "center" }}>
        <div style={{ fontSize: 40, marginBottom: 16, opacity: 0.3 }}>🚧</div>
        <h2 style={{ fontSize: 20, fontWeight: 700, color: "var(--color-text-primary)", marginBottom: 8 }}>{label}</h2>
        <p style={{ fontSize: 13, color: "var(--color-text-tertiary)" }}>This section is coming soon.</p>
      </div>
    </main>
  );
}

// ── Dashboard — now role-aware ────────────────────────────────────────────────
function Dashboard({ tasks, total, loading, error, submitting, moveTask, removeTask, addTask, reload, clearError }) {
  const { user, isArchitect, isNavigator } = useAuth();          // ✅ NEW
  const [showModal, setShowModal] = useState(false);
  const [filter, setFilter]       = useState("");
  const [activeTab, setActiveTab] = useState(0);

  // ✅ Role-aware welcome message
  const roleGreeting = isArchitect
    ? "Architect View — All workspace tasks"
    : isNavigator
      ? `Navigator View — ${user?.team_name || "Your team"} tasks`
      : user?.role === "solo"
        ? "Solo Dashboard — Your personal tasks"
        : "Operator View — Tasks assigned to you";

  const columns = useMemo(() => {
    const tabFilter = TABS[activeTab]?.filter;
    const filtered = tasks.filter(t => {
      const matchesSearch =
        !filter ||
        (t.assignee || "").toLowerCase().includes(filter.toLowerCase()) ||
        (t.title || t.task_description || "").toLowerCase().includes(filter.toLowerCase());
      const matchesTab = !tabFilter || t.status === tabFilter;
      return matchesSearch && matchesTab;
    });

    const visibleColumns = tabFilter
      ? COLUMNS.filter(col => col.status === tabFilter)
      : COLUMNS;

    return visibleColumns.map(col => ({
      ...col,
      tasks: filtered.filter(t => t.status === col.status),
    }));
  }, [tasks, filter, activeTab]);

  const counts = useMemo(() => ({
    to_do:       tasks.filter(t => t.status === "to_do").length,
    in_progress: tasks.filter(t => t.status === "in_progress").length,
    completed:   tasks.filter(t => t.status === "completed").length,
    cancelled:   tasks.filter(t => t.status === "cancelled").length,
  }), [tasks]);

  const METRICS = useMemo(() => [
    { label: "To Do",       value: counts.to_do,       icon: <IconCheckbox />, color: "#4f8ef7", variant: "blue"  },
    { label: "In Progress", value: counts.in_progress, icon: <IconProgress />, color: "#f59e0b", variant: "amber" },
    { label: "Completed",   value: counts.completed,   icon: <IconDone />,     color: "#22d3a8", variant: "teal"  },
  ], [counts]);

  const handleModalAdd = useCallback(async (msg) => {
    const result = await addTask(msg);
    setShowModal(false);
    return result;
  }, [addTask]);

  const gridCols = TABS[activeTab]?.filter ? 1 : `repeat(${COLUMNS.length}, minmax(0,1fr))`;

  return (
    <>
      {/* Topbar */}
      <header style={{
        position: "sticky", top: 0, zIndex: 40, height: 60,
        background: "rgba(13,15,30,0.88)",
        backdropFilter: "blur(16px)", WebkitBackdropFilter: "blur(16px)",
        borderBottom: "1px solid var(--border-glass)",
        padding: "0 28px", display: "flex", alignItems: "center", gap: 16,
      }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: "var(--color-text-primary)", letterSpacing: "-0.02em", lineHeight: 1.2 }}>Dashboard</div>
          <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 1 }}>Your AI assistant team is ready</div>
        </div>

        {/* Search */}
        <div style={{ flex: 1, maxWidth: 340, position: "relative" }}>
          <svg style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", width: 14, height: 14, color: "var(--color-text-tertiary)", pointerEvents: "none" }} viewBox="0 0 16 16" fill="none" aria-hidden="true">
            <circle cx="6.5" cy="6.5" r="4.5" stroke="currentColor" strokeWidth="1.3"/>
            <path d="M10 10l3.5 3.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/>
          </svg>
          <input
            value={filter}
            onChange={e => setFilter(e.target.value)}
            placeholder="Search tasks or assignees…"
            aria-label="Search tasks or assignees"
            style={{
              width: "100%", height: 36, padding: "0 14px 0 32px",
              background: "rgba(255,255,255,0.06)", border: "1px solid var(--border-glass)",
              borderRadius: 999, fontFamily: "var(--font-sans)", fontSize: 13,
              color: "var(--color-text-primary)", outline: "none",
              transition: "border-color 0.15s, background 0.15s, box-shadow 0.15s",
            }}
            onFocus={e => { e.target.style.borderColor = "rgba(79,142,247,0.5)"; e.target.style.background = "rgba(79,142,247,0.08)"; e.target.style.boxShadow = "0 0 0 3px rgba(79,142,247,0.12)"; }}
            onBlur={e => { e.target.style.borderColor = "var(--border-glass)"; e.target.style.background = "rgba(255,255,255,0.06)"; e.target.style.boxShadow = "none"; }}
          />
        </div>

        {/* Status badges + actions */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginLeft: "auto" }}>
          {[
            { label: "to do",       count: counts.to_do,       color: "#f59e0b" },
            { label: "in progress", count: counts.in_progress, color: "#4f8ef7" },
            { label: "done",        count: counts.completed,   color: "#22d3a8" },
            { label: "cancelled",   count: counts.cancelled,   color: "#6b7280" },
          ].map(s => (
            <span key={s.label} style={{
              display: "inline-flex", alignItems: "center", gap: 5,
              padding: "4px 10px", borderRadius: 999, fontSize: 12, fontWeight: 500,
              color: "var(--color-text-secondary)", background: "rgba(255,255,255,0.05)",
              border: "1px solid var(--border-glass)",
            }}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: s.color, flexShrink: 0 }} aria-hidden="true" />
              {s.count} {s.label}
            </span>
          ))}

          <button onClick={() => reload()} title="Refresh" aria-label="Refresh tasks" disabled={loading}
            style={{
              width: 36, height: 36, borderRadius: 10, border: "1px solid var(--border-glass)",
              background: "transparent", cursor: loading ? "not-allowed" : "pointer",
              color: "var(--color-text-secondary)", fontSize: 15,
              display: "flex", alignItems: "center", justifyContent: "center",
              transition: "all 0.15s", opacity: loading ? 0.5 : 1,
            }}
            onMouseEnter={e => { if (!loading) { e.currentTarget.style.background = "rgba(255,255,255,0.07)"; e.currentTarget.style.color = "var(--color-text-primary)"; } }}
            onMouseLeave={e => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--color-text-secondary)"; }}
          >↻</button>

          <button onClick={() => setShowModal(true)} disabled={submitting} aria-label="Create new task"
            style={{
              height: 36, padding: "0 18px", borderRadius: 999, border: "none",
              background: "linear-gradient(135deg, #4f8ef7 0%, #7b5cf0 100%)",
              color: "#fff", fontFamily: "var(--font-sans)", fontSize: 13, fontWeight: 600,
              cursor: submitting ? "not-allowed" : "pointer",
              display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap",
              boxShadow: "0 0 20px rgba(79,142,247,0.35)",
              transition: "opacity 0.15s, transform 0.1s",
              opacity: submitting ? 0.6 : 1,
            }}
            onMouseEnter={e => { if (!submitting) { e.currentTarget.style.opacity = "0.9"; e.currentTarget.style.transform = "translateY(-1px)"; } }}
            onMouseLeave={e => { e.currentTarget.style.opacity = submitting ? "0.6" : "1"; e.currentTarget.style.transform = ""; }}
          >{submitting ? "Adding…" : "+ New task"}</button>
        </div>
      </header>

      {/* Page body */}
      <main style={{ flex: 1, padding: "28px 28px 40px", display: "flex", flexDirection: "column", gap: 24 }}>

        {/* Hero row */}
        <div className="fade-up" style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 20, flexWrap: "wrap" }}>
          <div>
            {/* ✅ Personalised greeting */}
            <h1 style={{
              fontSize: 26, fontWeight: 700, letterSpacing: "-0.03em", lineHeight: 1.15,
              background: "linear-gradient(135deg, #f0f2ff 0%, #a5b4fc 100%)",
              WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text",
            }}>
              Welcome, {user?.name?.split(" ")[0] || "there"} 👋
            </h1>
            <p style={{ fontSize: 13, color: "var(--color-text-secondary)", marginTop: 5 }}>
              {roleGreeting} · {new Date().toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric" })}
            </p>
          </div>

          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            <AddToSlackButton />
            <div style={{
              padding: "6px 14px", borderRadius: 999,
              background: "rgba(34,211,168,0.12)", border: "1px solid rgba(34,211,168,0.25)",
              fontSize: 12, fontWeight: 600, color: "#22d3a8",
              display: "flex", alignItems: "center", gap: 6,
            }}>
              <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#22d3a8", boxShadow: "0 0 6px #22d3a8", animation: "pulse 2s ease-in-out infinite" }} aria-hidden="true" />
              System Online
            </div>
          </div>
        </div>

        {/* Error banner */}
        {error && (
          <div role="alert" style={{
            padding: "12px 18px", borderRadius: 10, fontSize: 13,
            background: "rgba(248,113,113,0.1)", border: "1px solid rgba(248,113,113,0.25)",
            color: "#f87171", display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12,
          }}>
            <span>⚠ {error}</span>
            <div style={{ display: "flex", gap: 8 }}>
              <button onClick={clearError} style={{ border: "1px solid rgba(248,113,113,0.3)", borderRadius: 6, background: "transparent", color: "#f87171", cursor: "pointer", fontSize: 12, fontWeight: 600, padding: "3px 10px" }}>Dismiss</button>
              <button onClick={reload} style={{ border: "1px solid rgba(248,113,113,0.3)", borderRadius: 6, background: "transparent", color: "#f87171", cursor: "pointer", fontSize: 12, fontWeight: 600, padding: "3px 10px" }}>Retry</button>
            </div>
          </div>
        )}

        {/* Metrics */}
        <div className="fade-up delay-1" style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0,1fr))", gap: 16 }}>
          {METRICS.map((m, i) => (
            <div key={m.label} style={{
              background: "rgba(255,255,255,0.04)", backdropFilter: "blur(12px)", WebkitBackdropFilter: "blur(12px)",
              border: "1px solid var(--border-glass)", borderRadius: 16, padding: "20px 22px",
              boxShadow: "0 4px 24px rgba(0,0,0,0.3)",
              transition: "transform 0.2s, box-shadow 0.2s, border-color 0.2s",
              position: "relative", overflow: "hidden", cursor: "default",
              animationDelay: `${0.05 + i * 0.05}s`,
            }}
              onMouseEnter={e => { e.currentTarget.style.transform = "translateY(-2px)"; e.currentTarget.style.boxShadow = "0 8px 32px rgba(0,0,0,0.4)"; e.currentTarget.style.borderColor = "rgba(255,255,255,0.16)"; }}
              onMouseLeave={e => { e.currentTarget.style.transform = ""; e.currentTarget.style.boxShadow = "0 4px 24px rgba(0,0,0,0.3)"; e.currentTarget.style.borderColor = ""; }}
            >
              <div aria-hidden="true" style={{
                position: "absolute", top: 0, left: 0, right: 0, height: 2, borderRadius: "16px 16px 0 0",
                background: m.variant === "blue" ? "linear-gradient(90deg,#4f8ef7,#7b5cf0)" : m.variant === "amber" ? "linear-gradient(90deg,#f59e0b,#fb923c)" : "linear-gradient(90deg,#22d3a8,#06b6d4)",
              }} />
              <div style={{ width: 40, height: 40, borderRadius: 10, marginBottom: 14, display: "flex", alignItems: "center", justifyContent: "center", color: m.color, background: m.variant === "blue" ? "rgba(79,142,247,0.14)" : m.variant === "amber" ? "rgba(245,158,11,0.14)" : "rgba(34,211,168,0.14)" }}>{m.icon}</div>
              <div style={{ fontSize: 11, fontWeight: 600, color: "var(--color-text-secondary)", textTransform: "uppercase", letterSpacing: "0.05em", marginBottom: 6 }}>{m.label}</div>
              <div style={{ fontSize: 32, fontWeight: 700, letterSpacing: "-0.03em", color: "var(--color-text-primary)", lineHeight: 1 }}>
                {loading ? "—" : m.value}
              </div>
              <div style={{ position: "absolute", right: 16, bottom: 16, opacity: 0.3 }}><Sparkline color={m.color} /></div>
            </div>
          ))}
        </div>

        {/* Kanban */}
        <div className="fade-up delay-2">
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 16, gap: 12 }}>
            <h2 style={{ fontSize: 16, fontWeight: 700, color: "var(--color-text-primary)", letterSpacing: "-0.02em" }}>Task Board</h2>
            <div role="tablist" aria-label="Filter tasks" style={{ display: "flex", gap: 3, background: "rgba(255,255,255,0.04)", border: "1px solid var(--border-glass)", borderRadius: 999, padding: 3 }}>
              {TABS.map((tab, i) => (
                <button key={tab.label} role="tab" aria-selected={activeTab === i} onClick={() => setActiveTab(i)}
                  style={{
                    padding: "5px 14px", borderRadius: 999, fontSize: 12, fontWeight: 600,
                    cursor: "pointer", border: "none", fontFamily: "var(--font-sans)",
                    background: activeTab === i ? "linear-gradient(135deg,#4f8ef7,#7b5cf0)" : "transparent",
                    color: activeTab === i ? "#fff" : "var(--color-text-secondary)",
                    boxShadow: activeTab === i ? "0 0 12px rgba(79,142,247,0.35)" : "none",
                    transition: "all 0.15s",
                  }}
                  onMouseEnter={e => { if (activeTab !== i) { e.currentTarget.style.background = "rgba(255,255,255,0.06)"; e.currentTarget.style.color = "var(--color-text-primary)"; } }}
                  onMouseLeave={e => { if (activeTab !== i) { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--color-text-secondary)"; } }}
                >{tab.label}</button>
              ))}
            </div>
          </div>

          {loading && tasks.length === 0 ? (
            <div role="status" aria-label="Loading tasks" style={{ textAlign: "center", padding: "60px 0", display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
              <div style={{ width: 24, height: 24, border: "2px solid rgba(79,142,247,0.2)", borderTopColor: "#4f8ef7", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />
              <span style={{ fontSize: 13, color: "var(--color-text-tertiary)" }}>Loading tasks…</span>
            </div>
          ) : (
            <div style={{
              display: "grid",
              gridTemplateColumns: typeof gridCols === "number" ? `repeat(${gridCols}, minmax(0,1fr))` : gridCols,
              gap: 20, alignItems: "start",
            }}>
              {columns.map(col => (
                <KanbanColumn
                  key={col.status} status={col.status} label={col.label}
                  tasks={col.tasks} onMove={moveTask} onDelete={removeTask}
                />
              ))}
            </div>
          )}
        </div>
      </main>

      {showModal && (
        <div role="dialog" aria-modal="true" aria-label="Add new task" style={{ position: "fixed", inset: 0, zIndex: 100 }}>
          <AddTaskModal onClose={() => setShowModal(false)} onAdd={handleModalAdd} />
        </div>
      )}
    </>
  );
}

// ── Segment 11: Integrations Page ────────────────────────────────────────────
function IntegrationsPage() {
  const { token } = useAuth();
  const API = BASE_URL;

  // Status of which integrations are configured
  const [status, setStatus]   = useState(null);
  const [loading, setLoading] = useState(true);

  // Per-service form state
  const [notion, setNotion]   = useState({ notion_token: "", notion_database_id: "" });
  const [jira, setJira]       = useState({ jira_base_url: "", jira_email: "", jira_api_token: "", jira_project_key: "" });
  const [trello, setTrello]   = useState({ trello_api_key: "", trello_token: "", trello_list_id: "" });

  // Sync / save state
  const [saving, setSaving]   = useState(null);   // "notion" | "jira" | "trello"
  const [syncing, setSyncing] = useState(null);
  const [result, setResult]   = useState(null);   // last sync result
  const [saveMsg, setSaveMsg] = useState(null);

  const authHeaders = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };

  useEffect(() => {
    fetch(`${API}/integrations/status`, { headers: authHeaders })
      .then(r => r.json())
      .then(d => { setStatus(d); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  async function handleSave(service, payload) {
    setSaving(service);
    setSaveMsg(null);
    try {
      const r = await fetch(`${API}/integrations/config`, {
        method: "PUT", headers: authHeaders, body: JSON.stringify(payload),
      });
      const d = await r.json();
      if (r.ok) {
        setSaveMsg({ service, type: "success", text: "Credentials saved!" });
        // Refresh status
        const sr = await fetch(`${API}/integrations/status`, { headers: authHeaders });
        setStatus(await sr.json());
      } else {
        setSaveMsg({ service, type: "error", text: d.detail || "Save failed." });
      }
    } catch {
      setSaveMsg({ service, type: "error", text: "Network error." });
    } finally {
      setSaving(null);
    }
  }

  async function handleSync(service) {
    setSyncing(service);
    setResult(null);
    try {
      const r = await fetch(`${API}/integrations/${service}/sync`, {
        method: "POST", headers: authHeaders, body: JSON.stringify({ task_ids: null }),
      });
      const d = await r.json();
      setResult({ service, ...d, error: r.ok ? null : (d.detail || "Sync failed.") });
    } catch {
      setResult({ service, error: "Network error." });
    } finally {
      setSyncing(null);
    }
  }

  const card = (children, extra = {}) => (
    <div style={{
      background: "rgba(255,255,255,0.04)", backdropFilter: "blur(12px)",
      border: "1px solid var(--border-glass)", borderRadius: 16,
      padding: "22px 24px", ...extra,
    }}>{children}</div>
  );

  const field = (label, value, onChange, placeholder, type = "text") => (
    <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
      <label style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text-secondary)", letterSpacing: "0.04em" }}>{label}</label>
      <input
        type={type} value={value} onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        style={{
          width: "100%", height: 38, padding: "0 12px",
          background: "rgba(255,255,255,0.06)", border: "1px solid var(--border-glass)",
          borderRadius: 8, fontFamily: "var(--font-sans)", fontSize: 13,
          color: "var(--color-text-primary)", outline: "none",
        }}
        onFocus={e => { e.target.style.borderColor = "rgba(79,142,247,0.5)"; e.target.style.boxShadow = "0 0 0 3px rgba(79,142,247,0.12)"; }}
        onBlur={e => { e.target.style.borderColor = "var(--border-glass)"; e.target.style.boxShadow = "none"; }}
      />
    </div>
  );

  const saveBtn = (service, onClick) => (
    <button
      onClick={onClick}
      disabled={saving === service}
      style={{
        height: 36, padding: "0 20px", borderRadius: 8, border: "none",
        background: "linear-gradient(135deg,#4f8ef7,#7b5cf0)",
        color: "#fff", fontFamily: "var(--font-sans)", fontSize: 13, fontWeight: 600,
        cursor: saving === service ? "not-allowed" : "pointer",
        opacity: saving === service ? 0.6 : 1, alignSelf: "flex-end",
      }}
    >{saving === service ? "Saving…" : "Save credentials"}</button>
  );

  const syncBtn = (service, configured) => (
    <button
      onClick={() => handleSync(service)}
      disabled={!configured || syncing === service}
      title={!configured ? "Configure credentials first" : `Sync all tasks to ${service}`}
      style={{
        height: 36, padding: "0 18px", borderRadius: 8,
        border: "1px solid var(--border-glass)", background: "rgba(255,255,255,0.05)",
        color: configured ? "var(--color-text-primary)" : "var(--color-text-tertiary)",
        fontFamily: "var(--font-sans)", fontSize: 13, fontWeight: 600,
        cursor: !configured || syncing === service ? "not-allowed" : "pointer",
        opacity: !configured || syncing === service ? 0.5 : 1,
      }}
    >{syncing === service ? "Syncing…" : "↑ Sync all tasks"}</button>
  );

  const statusDot = (configured) => (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: 6,
      padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 600,
      background: configured ? "rgba(34,211,168,0.12)" : "rgba(255,255,255,0.05)",
      border: `1px solid ${configured ? "rgba(34,211,168,0.3)" : "var(--border-glass)"}`,
      color: configured ? "#22d3a8" : "var(--color-text-tertiary)",
    }}>
      <span style={{ width: 6, height: 6, borderRadius: "50%", background: configured ? "#22d3a8" : "#555a80" }} />
      {configured ? "Configured" : "Not configured"}
    </span>
  );

  const msgBanner = (service) => saveMsg?.service === service ? (
    <div style={{
      padding: "8px 12px", borderRadius: 8, fontSize: 12, fontWeight: 500,
      background: saveMsg.type === "success" ? "rgba(34,211,168,0.1)" : "rgba(248,113,113,0.1)",
      border: `1px solid ${saveMsg.type === "success" ? "rgba(34,211,168,0.3)" : "rgba(248,113,113,0.3)"}`,
      color: saveMsg.type === "success" ? "#22d3a8" : "#f87171",
    }}>{saveMsg.text}</div>
  ) : null;

  if (loading) return (
    <main style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ width: 24, height: 24, border: "2px solid rgba(79,142,247,0.2)", borderTopColor: "#4f8ef7", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />
    </main>
  );

  return (
    <main style={{ flex: 1, padding: "28px 28px 40px", display: "flex", flexDirection: "column", gap: 24, maxWidth: 860 }}>

      {/* Header */}
      <div>
        <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-0.02em", color: "var(--color-text-primary)", marginBottom: 6 }}>Integrations</h1>
        <p style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>
          Push your workspace tasks to Notion, Jira, or Trello with one click. Credentials are stored securely in your workspace settings.
        </p>
      </div>

      {/* Last sync result */}
      {result && (
        <div style={{
          padding: "14px 18px", borderRadius: 12,
          background: result.error ? "rgba(248,113,113,0.1)" : "rgba(34,211,168,0.08)",
          border: `1px solid ${result.error ? "rgba(248,113,113,0.3)" : "rgba(34,211,168,0.25)"}`,
          color: result.error ? "#f87171" : "var(--color-text-primary)",
          fontSize: 13,
        }}>
          {result.error ? (
            <span>⚠ {result.error}</span>
          ) : (
            <span>
              ✅ <strong>{result.integration}</strong> sync complete —{" "}
              <span style={{ color: "#22d3a8" }}>{result.succeeded} succeeded</span>
              {result.failed > 0 && <span style={{ color: "#f87171" }}>, {result.failed} failed</span>}
              {" "}out of {result.total} tasks
            </span>
          )}
          <button onClick={() => setResult(null)} style={{ float: "right", background: "transparent", border: "none", color: "inherit", cursor: "pointer", fontSize: 14, opacity: 0.6 }}>✕</button>
        </div>
      )}

      {/* ── Notion ── */}
      {card(
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div style={{ width: 36, height: 36, borderRadius: 10, background: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 20 }}>𝓝</div>
              <div>
                <div style={{ fontSize: 15, fontWeight: 700, color: "var(--color-text-primary)" }}>Notion</div>
                <div style={{ fontSize: 12, color: "var(--color-text-tertiary)", marginTop: 2 }}>Push tasks as pages into a Notion database</div>
              </div>
            </div>
            {statusDot(status?.notion_configured)}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            {field("Integration Token", notion.notion_token, v => setNotion(p => ({ ...p, notion_token: v })), "secret_...", "password")}
            {field("Database ID", notion.notion_database_id, v => setNotion(p => ({ ...p, notion_database_id: v })), "xxxxxxxx-xxxx-...")}
          </div>
          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", alignItems: "center" }}>
            {msgBanner("notion")}
            {saveBtn("notion", () => handleSave("notion", notion))}
            {syncBtn("notion", status?.notion_configured)}
          </div>
        </div>
      )}

      {/* ── Jira ── */}
      {card(
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div style={{ width: 36, height: 36, borderRadius: 10, background: "#0052cc", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, color: "#fff", fontWeight: 800 }}>J</div>
              <div>
                <div style={{ fontSize: 15, fontWeight: 700, color: "var(--color-text-primary)" }}>Jira</div>
                <div style={{ fontSize: 12, color: "var(--color-text-tertiary)", marginTop: 2 }}>Create issues in an Atlassian Jira project</div>
              </div>
            </div>
            {statusDot(status?.jira_configured)}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            {field("Base URL", jira.jira_base_url, v => setJira(p => ({ ...p, jira_base_url: v })), "https://yourorg.atlassian.net")}
            {field("Project Key", jira.jira_project_key, v => setJira(p => ({ ...p, jira_project_key: v })), "PROJ")}
            {field("Email", jira.jira_email, v => setJira(p => ({ ...p, jira_email: v })), "you@company.com")}
            {field("API Token", jira.jira_api_token, v => setJira(p => ({ ...p, jira_api_token: v })), "Your Atlassian API token", "password")}
          </div>
          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", alignItems: "center" }}>
            {msgBanner("jira")}
            {saveBtn("jira", () => handleSave("jira", jira))}
            {syncBtn("jira", status?.jira_configured)}
          </div>
        </div>
      )}

      {/* ── Trello ── */}
      {card(
        <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div style={{ width: 36, height: 36, borderRadius: 10, background: "#0079bf", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18, color: "#fff", fontWeight: 800 }}>T</div>
              <div>
                <div style={{ fontSize: 15, fontWeight: 700, color: "var(--color-text-primary)" }}>Trello</div>
                <div style={{ fontSize: 12, color: "var(--color-text-tertiary)", marginTop: 2 }}>Add cards to a Trello board list with priority labels</div>
              </div>
            </div>
            {statusDot(status?.trello_configured)}
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 12 }}>
            {field("API Key", trello.trello_api_key, v => setTrello(p => ({ ...p, trello_api_key: v })), "From trello.com/app-key", "password")}
            {field("Token", trello.trello_token, v => setTrello(p => ({ ...p, trello_token: v })), "OAuth token", "password")}
            {field("List ID", trello.trello_list_id, v => setTrello(p => ({ ...p, trello_list_id: v })), "Target list ID")}
          </div>
          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", alignItems: "center" }}>
            {msgBanner("trello")}
            {saveBtn("trello", () => handleSave("trello", trello))}
            {syncBtn("trello", status?.trello_configured)}
          </div>
        </div>
      )}

    </main>
  );
}

// ── Segment 12: Locale Page ───────────────────────────────────────────────────
function LocalePage() {
  const { user, token } = useAuth();
  const API = BASE_URL;
  const isArchitect = user?.role === "architect";

  const [options, setOptions]           = useState(null);
  const [userLocale, setUserLocale]     = useState(null);
  const [wsLocale, setWsLocale]         = useState(null);
  const [loading, setLoading]           = useState(true);
  const [saving, setSaving]             = useState(null); // "user" | "workspace"
  const [saveMsg, setSaveMsg]           = useState(null);

  // Form state — user prefs
  const [lang, setLang]     = useState("en");
  const [tz, setTz]         = useState("UTC");
  const [curr, setCurr]     = useState("USD");

  // Form state — workspace defaults
  const [wsLang, setWsLang] = useState("en");
  const [wsTz, setWsTz]     = useState("UTC");
  const [wsCurr, setWsCurr] = useState("USD");

  const authHeaders = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };

  useEffect(() => {
    const safe = (p) => p.catch(() => null);
    Promise.all([
      safe(fetch(`${API}/locale/options`).then(r => r.ok ? r.json() : null)),
      safe(fetch(`${API}/locale/settings`, { headers: authHeaders }).then(r => r.ok ? r.json() : null)),
      isArchitect ? safe(fetch(`${API}/locale/workspace`, { headers: authHeaders }).then(r => r.ok ? r.json() : null)) : Promise.resolve(null),
    ]).then(([opts, ul, wl]) => {
      setOptions(opts);
      setUserLocale(ul);
      setLang(ul?.language || "en");
      setTz(ul?.timezone || "UTC");
      setCurr(ul?.currency || "USD");
      if (wl) {
        setWsLocale(wl);
        setWsLang(wl?.default_language || "en");
        setWsTz(wl?.default_timezone || "UTC");
        setWsCurr(wl?.default_currency || "USD");
      }
      setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  async function handleSaveUser() {
    setSaving("user"); setSaveMsg(null);
    try {
      const r = await fetch(`${API}/locale/settings`, {
        method: "PUT", headers: authHeaders,
        body: JSON.stringify({ language: lang, timezone: tz, currency: curr }),
      });
      const d = await r.json();
      if (r.ok) { setUserLocale(d); setSaveMsg({ scope: "user", type: "success", text: "Your locale preferences saved!" }); }
      else setSaveMsg({ scope: "user", type: "error", text: d.detail || "Save failed." });
    } catch { setSaveMsg({ scope: "user", type: "error", text: "Network error." }); }
    finally { setSaving(null); }
  }

  async function handleSaveWorkspace() {
    setSaving("workspace"); setSaveMsg(null);
    try {
      const r = await fetch(`${API}/locale/workspace`, {
        method: "PUT", headers: authHeaders,
        body: JSON.stringify({ default_language: wsLang, default_timezone: wsTz, default_currency: wsCurr }),
      });
      const d = await r.json();
      if (r.ok) { setWsLocale(d); setSaveMsg({ scope: "workspace", type: "success", text: "Workspace locale defaults saved!" }); }
      else setSaveMsg({ scope: "workspace", type: "error", text: d.detail || "Save failed." });
    } catch { setSaveMsg({ scope: "workspace", type: "error", text: "Network error." }); }
    finally { setSaving(null); }
  }

  const selectStyle = {
    width: "100%", height: 38, padding: "0 12px",
    background: "#1e2140", border: "1px solid var(--border-glass)",
    borderRadius: 8, fontFamily: "var(--font-sans)", fontSize: 13,
    color: "#f0f2ff", outline: "none", cursor: "pointer",
    appearance: "none", WebkitAppearance: "none",
  };
  const optStyle = { background: "#1e2140", color: "#f0f2ff" };

  const labelStyle = { fontSize: 12, fontWeight: 600, color: "var(--color-text-secondary)", letterSpacing: "0.04em", marginBottom: 6, display: "block" };

  const card = (children) => (
    <div style={{
      background: "rgba(255,255,255,0.04)", backdropFilter: "blur(12px)",
      border: "1px solid var(--border-glass)", borderRadius: 16, padding: "22px 24px",
    }}>{children}</div>
  );

  const msgBanner = (scope) => saveMsg?.scope === scope ? (
    <div style={{
      padding: "8px 14px", borderRadius: 8, fontSize: 12, fontWeight: 500,
      background: saveMsg.type === "success" ? "rgba(34,211,168,0.1)" : "rgba(248,113,113,0.1)",
      border: `1px solid ${saveMsg.type === "success" ? "rgba(34,211,168,0.3)" : "rgba(248,113,113,0.3)"}`,
      color: saveMsg.type === "success" ? "#22d3a8" : "#f87171",
    }}>{saveMsg.text}</div>
  ) : null;

  const saveBtn = (scope, onClick) => (
    <button onClick={onClick} disabled={saving === scope} style={{
      height: 36, padding: "0 20px", borderRadius: 8, border: "none",
      background: "linear-gradient(135deg,#4f8ef7,#7b5cf0)",
      color: "#fff", fontFamily: "var(--font-sans)", fontSize: 13, fontWeight: 600,
      cursor: saving === scope ? "not-allowed" : "pointer",
      opacity: saving === scope ? 0.6 : 1,
    }}>{saving === scope ? "Saving…" : "Save"}</button>
  );

  // Current display values for the summary pills
  const langLabel = options?.languages?.[lang] || lang;
  const currLabel = options?.currencies?.[curr] || curr;

  if (loading) return (
    <main style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}>
      <div style={{ width: 24, height: 24, border: "2px solid rgba(79,142,247,0.2)", borderTopColor: "#4f8ef7", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />
    </main>
  );

  return (
    <main style={{ flex: 1, padding: "28px 28px 40px", display: "flex", flexDirection: "column", gap: 24, maxWidth: 780 }}>

      {/* Header */}
      <div>
        <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-0.02em", color: "var(--color-text-primary)", marginBottom: 6 }}>Locale &amp; Preferences</h1>
        <p style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>
          Set your language, timezone, and currency. Changes apply immediately to your account.
        </p>
      </div>

      {/* Current summary pills */}
      <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
        {[
          { label: "Language", value: langLabel, icon: "🌐" },
          { label: "Timezone", value: tz, icon: "🕐" },
          { label: "Currency", value: currLabel, icon: "💱" },
        ].map(p => (
          <div key={p.label} style={{
            padding: "6px 14px", borderRadius: 999,
            background: "rgba(79,142,247,0.1)", border: "1px solid rgba(79,142,247,0.25)",
            display: "flex", alignItems: "center", gap: 8,
          }}>
            <span style={{ fontSize: 14 }}>{p.icon}</span>
            <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>{p.label}:</span>
            <span style={{ fontSize: 12, fontWeight: 600, color: "#4f8ef7" }}>{p.value}</span>
          </div>
        ))}
      </div>

      {/* ── User Locale Card ── */}
      {card(
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
            <div style={{ width: 36, height: 36, borderRadius: 10, background: "rgba(79,142,247,0.15)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18 }}>👤</div>
            <div>
              <div style={{ fontSize: 15, fontWeight: 700, color: "var(--color-text-primary)" }}>My Preferences</div>
              <div style={{ fontSize: 12, color: "var(--color-text-tertiary)", marginTop: 2 }}>Applied to your account only</div>
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
            {/* Language */}
            <div>
              <label style={labelStyle}>Language</label>
              <div style={{ position: "relative" }}>
                <select value={lang} onChange={e => setLang(e.target.value)} style={selectStyle}
                  onFocus={e => { e.target.style.borderColor = "rgba(79,142,247,0.5)"; e.target.style.boxShadow = "0 0 0 3px rgba(79,142,247,0.12)"; }}
                  onBlur={e => { e.target.style.borderColor = "var(--border-glass)"; e.target.style.boxShadow = "none"; }}
                >
                  {options && Object.entries(options.languages).map(([code, name]) => (
                    <option style={optStyle} key={code} value={code}>{name}</option>
                  ))}
                </select>
                <span style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", pointerEvents: "none", color: "var(--color-text-tertiary)", fontSize: 11 }}>▾</span>
              </div>
            </div>

            {/* Timezone */}
            <div>
              <label style={labelStyle}>Timezone</label>
              <div style={{ position: "relative" }}>
                <select value={tz} onChange={e => setTz(e.target.value)} style={selectStyle}
                  onFocus={e => { e.target.style.borderColor = "rgba(79,142,247,0.5)"; e.target.style.boxShadow = "0 0 0 3px rgba(79,142,247,0.12)"; }}
                  onBlur={e => { e.target.style.borderColor = "var(--border-glass)"; e.target.style.boxShadow = "none"; }}
                >
                  {options?.timezones?.map(t => (
                    <option style={optStyle} key={t} value={t}>{t}</option>
                  ))}
                </select>
                <span style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", pointerEvents: "none", color: "var(--color-text-tertiary)", fontSize: 11 }}>▾</span>
              </div>
            </div>

            {/* Currency */}
            <div>
              <label style={labelStyle}>Currency</label>
              <div style={{ position: "relative" }}>
                <select value={curr} onChange={e => setCurr(e.target.value)} style={selectStyle}
                  onFocus={e => { e.target.style.borderColor = "rgba(79,142,247,0.5)"; e.target.style.boxShadow = "0 0 0 3px rgba(79,142,247,0.12)"; }}
                  onBlur={e => { e.target.style.borderColor = "var(--border-glass)"; e.target.style.boxShadow = "none"; }}
                >
                  {options && Object.entries(options.currencies).map(([code, label]) => (
                    <option style={optStyle} key={code} value={code}>{label}</option>
                  ))}
                </select>
                <span style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", pointerEvents: "none", color: "var(--color-text-tertiary)", fontSize: 11 }}>▾</span>
              </div>
            </div>
          </div>

          <div style={{ display: "flex", gap: 10, alignItems: "center", justifyContent: "flex-end" }}>
            {msgBanner("user")}
            {saveBtn("user", handleSaveUser)}
          </div>
        </div>
      )}

      {/* ── Workspace Locale Card (Architect only) ── */}
      {isArchitect && card(
        <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
            <div style={{ width: 36, height: 36, borderRadius: 10, background: "rgba(123,92,240,0.15)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 18 }}>🏢</div>
            <div>
              <div style={{ fontSize: 15, fontWeight: 700, color: "var(--color-text-primary)" }}>Workspace Defaults</div>
              <div style={{ fontSize: 12, color: "var(--color-text-tertiary)", marginTop: 2 }}>Applied to new members who haven't set their own preferences</div>
            </div>
            <span style={{
              marginLeft: "auto", padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 600,
              background: "rgba(123,92,240,0.15)", border: "1px solid rgba(123,92,240,0.3)", color: "#7b5cf0",
            }}>Architect only</span>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 16 }}>
            <div>
              <label style={labelStyle}>Default Language</label>
              <div style={{ position: "relative" }}>
                <select value={wsLang} onChange={e => setWsLang(e.target.value)} style={selectStyle}>
                  {options && Object.entries(options.languages).map(([code, name]) => (
                    <option style={optStyle} key={code} value={code}>{name}</option>
                  ))}
                </select>
                <span style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", pointerEvents: "none", color: "var(--color-text-tertiary)", fontSize: 11 }}>▾</span>
              </div>
            </div>
            <div>
              <label style={labelStyle}>Default Timezone</label>
              <div style={{ position: "relative" }}>
                <select value={wsTz} onChange={e => setWsTz(e.target.value)} style={selectStyle}>
                  {options?.timezones?.map(t => (
                    <option style={optStyle} key={t} value={t}>{t}</option>
                  ))}
                </select>
                <span style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", pointerEvents: "none", color: "var(--color-text-tertiary)", fontSize: 11 }}>▾</span>
              </div>
            </div>
            <div>
              <label style={labelStyle}>Default Currency</label>
              <div style={{ position: "relative" }}>
                <select value={wsCurr} onChange={e => setWsCurr(e.target.value)} style={selectStyle}>
                  {options && Object.entries(options.currencies).map(([code, label]) => (
                    <option style={optStyle} key={code} value={code}>{label}</option>
                  ))}
                </select>
                <span style={{ position: "absolute", right: 10, top: "50%", transform: "translateY(-50%)", pointerEvents: "none", color: "var(--color-text-tertiary)", fontSize: 11 }}>▾</span>
              </div>
            </div>
          </div>

          <div style={{ display: "flex", gap: 10, alignItems: "center", justifyContent: "flex-end" }}>
            {msgBanner("workspace")}
            {saveBtn("workspace", handleSaveWorkspace)}
          </div>
        </div>
      )}

      {/* Info box */}
      <div style={{
        padding: "14px 18px", borderRadius: 12,
        background: "rgba(255,255,255,0.03)", border: "1px solid var(--border-glass)",
        fontSize: 12, color: "var(--color-text-tertiary)", lineHeight: 1.7,
      }}>
        <strong style={{ color: "var(--color-text-secondary)" }}>ℹ How locale settings work</strong><br />
        Your personal settings override workspace defaults. Timezone affects how deadlines and timestamps are displayed throughout the app.
        Currency is used for any budget or cost fields. Language preference is stored and will power UI translations in a future release.
      </div>

    </main>
  );
}

// ── TeamsPage — Segment 9: Microsoft Teams Integration ───────────────────────
function TeamsPage() {
  const { token, user } = useAuth();
  const API = BASE_URL;
  const authHeaders = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };
  const isArchitect = user?.role === "architect";

  const [status, setStatus]     = useState(null);
  const [channels, setChannels] = useState([]);
  const [loading, setLoading]   = useState(true);
  const [saving, setSaving]     = useState(false);
  const [msg, setMsg]           = useState(null);
  const [tenantId, setTenantId] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [chForm, setChForm]     = useState({ channel_id: "", channel_name: "", service_url: "", conversation_id: "" });

  useEffect(() => {
    Promise.all([
      fetch(`${API}/teams/status`,   { headers: authHeaders }).then(r => r.json()),
      fetch(`${API}/teams/channels`, { headers: authHeaders }).then(r => r.json()),
    ]).then(([s, ch]) => {
      setStatus(s); setTenantId(s?.tenant_id || "");
      setChannels(Array.isArray(ch) ? ch : []); setLoading(false);
    }).catch(() => setLoading(false));
  }, []);

  async function handleSaveConfig() {
    setSaving(true); setMsg(null);
    try {
      const r = await fetch(`${API}/teams/config`, { method: "PUT", headers: authHeaders, body: JSON.stringify({ tenant_id: tenantId }) });
      const d = await r.json();
      if (r.ok) { setStatus(s => ({ ...s, connected: true, tenant_id: tenantId })); setMsg({ type: "success", text: "Teams tenant ID saved!" }); }
      else setMsg({ type: "error", text: d.detail || "Save failed." });
    } catch { setMsg({ type: "error", text: "Network error." }); }
    finally { setSaving(false); }
  }

  async function handleDisconnect() {
    if (!window.confirm("Disconnect Teams from this workspace?")) return;
    setSaving(true);
    try {
      await fetch(`${API}/teams/config`, { method: "DELETE", headers: authHeaders });
      setStatus(s => ({ ...s, connected: false, tenant_id: null })); setTenantId(""); setMsg({ type: "success", text: "Teams disconnected." });
    } catch { setMsg({ type: "error", text: "Network error." }); }
    finally { setSaving(false); }
  }

  async function handleRegisterChannel(e) {
    e.preventDefault(); setSaving(true); setMsg(null);
    try {
      const r = await fetch(`${API}/teams/channels`, { method: "POST", headers: authHeaders, body: JSON.stringify(chForm) });
      const d = await r.json();
      if (r.ok) { setChannels(ch => [...ch, d]); setChForm({ channel_id: "", channel_name: "", service_url: "", conversation_id: "" }); setShowForm(false); setMsg({ type: "success", text: `Channel "${d.channel_name}" registered!` }); }
      else setMsg({ type: "error", text: d.detail || "Registration failed." });
    } catch { setMsg({ type: "error", text: "Network error." }); }
    finally { setSaving(false); }
  }

  async function handleRemoveChannel(id, name) {
    if (!window.confirm(`Remove channel "${name}"?`)) return;
    try {
      await fetch(`${API}/teams/channels/${id}`, { method: "DELETE", headers: authHeaders });
      setChannels(ch => ch.filter(c => c.id !== id)); setMsg({ type: "success", text: `Channel "${name}" removed.` });
    } catch { setMsg({ type: "error", text: "Network error." }); }
  }

  const inp = { width: "100%", height: 38, padding: "0 12px", background: "rgba(255,255,255,0.06)", border: "1px solid var(--border-glass)", borderRadius: 8, fontFamily: "var(--font-sans)", fontSize: 13, color: "var(--color-text-primary)", outline: "none" };
  const lbl = { fontSize: 12, fontWeight: 600, color: "var(--color-text-secondary)", letterSpacing: "0.04em", marginBottom: 6, display: "block" };
  const card = (ch) => <div style={{ background: "rgba(255,255,255,0.04)", backdropFilter: "blur(12px)", border: "1px solid var(--border-glass)", borderRadius: 16, padding: "22px 24px" }}>{ch}</div>;

  if (loading) return <main style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}><div style={{ width: 24, height: 24, border: "2px solid rgba(79,142,247,0.2)", borderTopColor: "#4f8ef7", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} /></main>;

  return (
    <main style={{ flex: 1, padding: "28px 28px 40px", display: "flex", flexDirection: "column", gap: 24, maxWidth: 820 }}>
      <div>
        <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-0.02em", color: "var(--color-text-primary)", marginBottom: 6 }}>Microsoft Teams</h1>
        <p style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>Connect your workspace to Microsoft Teams. Create tasks directly from Teams channels by mentioning the bot.</p>
      </div>
      {msg && <div style={{ padding: "10px 16px", borderRadius: 10, fontSize: 13, fontWeight: 500, background: msg.type === "success" ? "rgba(34,211,168,0.1)" : "rgba(248,113,113,0.1)", border: `1px solid ${msg.type === "success" ? "rgba(34,211,168,0.3)" : "rgba(248,113,113,0.3)"}`, color: msg.type === "success" ? "#22d3a8" : "#f87171" }}>{msg.text}</div>}
      {card(<div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <div style={{ width: 44, height: 44, borderRadius: 12, background: status?.connected ? "rgba(34,211,168,0.12)" : "rgba(255,255,255,0.06)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22 }}>💬</div>
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 15, fontWeight: 700, color: "var(--color-text-primary)" }}>Teams Connection</div>
            <div style={{ fontSize: 12, marginTop: 2, display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ width: 7, height: 7, borderRadius: "50%", background: status?.connected ? "#22d3a8" : "#6b7280", display: "inline-block" }} />
              <span style={{ color: status?.connected ? "#22d3a8" : "var(--color-text-tertiary)" }}>{status?.connected ? `Connected — Tenant: ${status.tenant_id}` : "Not connected"}</span>
            </div>
          </div>
          {status?.connected && isArchitect && <button onClick={handleDisconnect} disabled={saving} style={{ height: 32, padding: "0 14px", borderRadius: 8, border: "1px solid rgba(248,113,113,0.3)", background: "rgba(248,113,113,0.08)", color: "#f87171", fontFamily: "var(--font-sans)", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>Disconnect</button>}
        </div>
        <div style={{ padding: "14px 16px", borderRadius: 10, background: "rgba(79,142,247,0.06)", border: "1px solid rgba(79,142,247,0.15)", fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.8 }}>
          <strong style={{ color: "#4f8ef7", display: "block", marginBottom: 6 }}>⚙ Setup Instructions</strong>
          1. Azure Portal → create a Bot resource → enable Teams channel.<br />
          2. Set <code style={{ background: "rgba(255,255,255,0.08)", padding: "1px 5px", borderRadius: 4 }}>TEAMS_APP_ID</code> and <code style={{ background: "rgba(255,255,255,0.08)", padding: "1px 5px", borderRadius: 4 }}>TEAMS_APP_SECRET</code> in Railway.<br />
          3. Set messaging endpoint: <code style={{ background: "rgba(255,255,255,0.08)", padding: "1px 5px", borderRadius: 4 }}>{status?.webhook_url || `${API}/teams/webhook`}</code><br />
          4. Paste your Azure AD Tenant ID below and save.
        </div>
        {isArchitect && <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <label style={lbl}>Azure AD Tenant ID</label>
          <div style={{ display: "flex", gap: 10 }}>
            <input value={tenantId} onChange={e => setTenantId(e.target.value)} placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx" style={{ ...inp, flex: 1 }} />
            <button onClick={handleSaveConfig} disabled={saving || !tenantId.trim()} style={{ height: 38, padding: "0 20px", borderRadius: 8, border: "none", background: "linear-gradient(135deg,#4f8ef7,#7b5cf0)", color: "#fff", fontFamily: "var(--font-sans)", fontSize: 13, fontWeight: 600, cursor: "pointer", opacity: (saving || !tenantId.trim()) ? 0.6 : 1 }}>{saving ? "Saving…" : "Save"}</button>
          </div>
        </div>}
      </div>)}
      {card(<div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div><div style={{ fontSize: 15, fontWeight: 700, color: "var(--color-text-primary)" }}>Registered Channels</div><div style={{ fontSize: 12, color: "var(--color-text-tertiary)", marginTop: 2 }}>Channels that receive proactive task notifications</div></div>
          {isArchitect && <button onClick={() => setShowForm(f => !f)} style={{ height: 34, padding: "0 16px", borderRadius: 8, border: "1px solid rgba(79,142,247,0.3)", background: "rgba(79,142,247,0.08)", color: "#4f8ef7", fontFamily: "var(--font-sans)", fontSize: 12, fontWeight: 600, cursor: "pointer" }}>{showForm ? "Cancel" : "+ Add Channel"}</button>}
        </div>
        {showForm && isArchitect && <div style={{ padding: 18, borderRadius: 12, background: "rgba(79,142,247,0.05)", border: "1px solid rgba(79,142,247,0.15)" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            {[["channel_name","Channel Name","#general"],["channel_id","Channel ID","19:abc@thread.tacv2"],["service_url","Service URL","https://smba.trafficmanager.net/…"],["conversation_id","Conversation ID","19:abc@thread.tacv2"]].map(([k, label, ph]) => (
              <div key={k}><label style={lbl}>{label}</label><input value={chForm[k]} onChange={e => setChForm(f => ({ ...f, [k]: e.target.value }))} placeholder={ph} style={inp} /></div>
            ))}
          </div>
          <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 14 }}>
            <button onClick={handleRegisterChannel} disabled={saving || !chForm.channel_id || !chForm.channel_name} style={{ height: 36, padding: "0 20px", borderRadius: 8, border: "none", background: "linear-gradient(135deg,#4f8ef7,#7b5cf0)", color: "#fff", fontFamily: "var(--font-sans)", fontSize: 13, fontWeight: 600, cursor: "pointer" }}>{saving ? "Registering…" : "Register Channel"}</button>
          </div>
        </div>}
        {channels.length === 0 ? <div style={{ padding: 28, textAlign: "center", color: "var(--color-text-tertiary)", fontSize: 13, border: "1px dashed var(--border-glass)", borderRadius: 10 }}>No channels registered yet.{isArchitect && " Click \"+ Add Channel\" to register."}</div>
        : channels.map(ch => (
          <div key={ch.id} style={{ display: "flex", alignItems: "center", gap: 14, padding: "12px 16px", borderRadius: 10, background: "rgba(255,255,255,0.03)", border: "1px solid var(--border-glass)" }}>
            <div style={{ width: 34, height: 34, borderRadius: 8, background: "rgba(79,142,247,0.12)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>💬</div>
            <div style={{ flex: 1 }}><div style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text-primary)" }}>{ch.channel_name}</div><div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 2, fontFamily: "var(--font-mono)" }}>{ch.channel_id}</div></div>
            <div style={{ padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 600, background: "rgba(34,211,168,0.1)", border: "1px solid rgba(34,211,168,0.25)", color: "#22d3a8" }}>Active</div>
            {isArchitect && <button onClick={() => handleRemoveChannel(ch.id, ch.channel_name)} style={{ height: 28, padding: "0 12px", borderRadius: 6, border: "1px solid rgba(248,113,113,0.25)", background: "rgba(248,113,113,0.06)", color: "#f87171", fontFamily: "var(--font-sans)", fontSize: 11, fontWeight: 600, cursor: "pointer" }}>Remove</button>}
          </div>
        ))}
      </div>)}
    </main>
  );
}

// ── ApiPage — Segment 13: Public REST API & Key Management ────────────────────
function ApiPage() {
  const { token, user } = useAuth();
  const API = BASE_URL;
  const authHeaders = { "Content-Type": "application/json", Authorization: `Bearer ${token}` };
  const isArchitect = user?.role === "architect";
  const BACKEND = API || "https://your-backend.railway.app";

  const [keys, setKeys]           = useState([]);
  const [loading, setLoading]     = useState(true);
  const [creating, setCreating]   = useState(false);
  const [msg, setMsg]             = useState(null);
  const [newKeyName, setNewKeyName] = useState("");
  const [revealedKey, setRevealedKey] = useState(null); // { id, key }
  const [copied, setCopied]       = useState(false);

  useEffect(() => {
    fetch(`${API}/api/v1/keys`, { headers: authHeaders })
      .then(r => r.json()).then(d => { setKeys(Array.isArray(d) ? d : []); setLoading(false); })
      .catch(() => setLoading(false));
  }, []);

  async function handleCreateKey() {
    if (!newKeyName.trim()) return;
    setCreating(true); setMsg(null); setRevealedKey(null);
    try {
      const r = await fetch(`${API}/api/v1/keys`, {
        method: "POST", headers: authHeaders,
        body: JSON.stringify({ name: newKeyName.trim() }),
      });
      const d = await r.json();
      if (r.ok) {
        setRevealedKey({ id: d.id, key: d.key, name: d.name });
        setKeys(k => [{ id: d.id, name: d.name, key_prefix: d.key_prefix, workspace_id: d.workspace_id, is_active: true, created_at: d.created_at }, ...k]);
        setNewKeyName("");
        setMsg({ type: "success", text: "API key created! Copy it now — it won't be shown again." });
      } else {
        setMsg({ type: "error", text: d.detail || "Failed to create key." });
      }
    } catch { setMsg({ type: "error", text: "Network error." }); }
    finally { setCreating(false); }
  }

  async function handleRevoke(id, name) {
    if (!window.confirm(`Revoke key "${name}"? Any integrations using it will stop working.`)) return;
    try {
      await fetch(`${API}/api/v1/keys/${id}`, { method: "DELETE", headers: authHeaders });
      setKeys(k => k.filter(key => key.id !== id));
      if (revealedKey?.id === id) setRevealedKey(null);
      setMsg({ type: "success", text: `Key "${name}" revoked.` });
    } catch { setMsg({ type: "error", text: "Network error." }); }
  }

  function copyKey(key) {
    navigator.clipboard.writeText(key).then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000); });
  }

  const inp = { width: "100%", height: 38, padding: "0 12px", background: "rgba(255,255,255,0.06)", border: "1px solid var(--border-glass)", borderRadius: 8, fontFamily: "var(--font-sans)", fontSize: 13, color: "var(--color-text-primary)", outline: "none" };
  const card = (ch, extra = {}) => <div style={{ background: "rgba(255,255,255,0.04)", backdropFilter: "blur(12px)", border: "1px solid var(--border-glass)", borderRadius: 16, padding: "22px 24px", ...extra }}>{ch}</div>;

  const ENDPOINTS = [
    { method: "POST",   path: "/api/v1/tasks",       desc: "Create a task from Notion, Jira, Zapier, etc." },
    { method: "GET",    path: "/api/v1/tasks",        desc: "List tasks (supports ?status=, ?assignee=, ?priority=, ?skip=, ?limit=)" },
    { method: "GET",    path: "/api/v1/tasks/{id}",   desc: "Get a single task by ID" },
    { method: "PUT",    path: "/api/v1/tasks/{id}",   desc: "Update status, priority, assignee, or deadline" },
    { method: "DELETE", path: "/api/v1/tasks/{id}",   desc: "Cancel a task (sets status to cancelled)" },
  ];

  const METHOD_COLORS = { POST: "#22d3a8", GET: "#4f8ef7", PUT: "#f59e0b", DELETE: "#f87171" };

  if (loading) return <main style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center" }}><div style={{ width: 24, height: 24, border: "2px solid rgba(79,142,247,0.2)", borderTopColor: "#4f8ef7", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} /></main>;

  return (
    <main style={{ flex: 1, padding: "28px 28px 40px", display: "flex", flexDirection: "column", gap: 24, maxWidth: 860 }}>
      <div>
        <h1 style={{ fontSize: 22, fontWeight: 700, letterSpacing: "-0.02em", color: "var(--color-text-primary)", marginBottom: 6 }}>Public API</h1>
        <p style={{ fontSize: 13, color: "var(--color-text-secondary)" }}>
          Connect Notion, Jira, Trello, Zapier, or any tool to your workspace using API keys. All endpoints use <code style={{ background: "rgba(255,255,255,0.08)", padding: "1px 6px", borderRadius: 4, fontSize: 12 }}>X-API-Key</code> header authentication.
        </p>
      </div>

      {msg && <div style={{ padding: "10px 16px", borderRadius: 10, fontSize: 13, fontWeight: 500, background: msg.type === "success" ? "rgba(34,211,168,0.1)" : "rgba(248,113,113,0.1)", border: `1px solid ${msg.type === "success" ? "rgba(34,211,168,0.3)" : "rgba(248,113,113,0.3)"}`, color: msg.type === "success" ? "#22d3a8" : "#f87171" }}>{msg.text}</div>}

      {/* Revealed key banner */}
      {revealedKey && (
        <div style={{ padding: "16px 20px", borderRadius: 12, background: "rgba(245,158,11,0.08)", border: "1px solid rgba(245,158,11,0.3)", display: "flex", flexDirection: "column", gap: 10 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: "#f59e0b" }}>⚠ Copy your API key now — it won't be shown again</div>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <code style={{ flex: 1, fontFamily: "var(--font-mono)", fontSize: 12, background: "rgba(0,0,0,0.3)", padding: "8px 12px", borderRadius: 8, color: "#e8eaf6", wordBreak: "break-all" }}>{revealedKey.key}</code>
            <button onClick={() => copyKey(revealedKey.key)} style={{ height: 36, padding: "0 16px", borderRadius: 8, border: "none", background: copied ? "rgba(34,211,168,0.2)" : "rgba(245,158,11,0.2)", color: copied ? "#22d3a8" : "#f59e0b", fontFamily: "var(--font-sans)", fontSize: 12, fontWeight: 600, cursor: "pointer", whiteSpace: "nowrap" }}>
              {copied ? "✓ Copied!" : "Copy"}
            </button>
          </div>
        </div>
      )}

      {/* Key management */}
      {card(<div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: "var(--color-text-primary)" }}>API Keys</div>

        {isArchitect && (
          <div style={{ display: "flex", gap: 10 }}>
            <input value={newKeyName} onChange={e => setNewKeyName(e.target.value)} placeholder="Key name, e.g. Notion Integration" style={{ ...inp, flex: 1 }}
              onKeyDown={e => e.key === "Enter" && handleCreateKey()}
              onFocus={e => { e.target.style.borderColor = "rgba(79,142,247,0.5)"; e.target.style.boxShadow = "0 0 0 3px rgba(79,142,247,0.12)"; }}
              onBlur={e => { e.target.style.borderColor = "var(--border-glass)"; e.target.style.boxShadow = "none"; }}
            />
            <button onClick={handleCreateKey} disabled={creating || !newKeyName.trim()} style={{ height: 38, padding: "0 20px", borderRadius: 8, border: "none", background: "linear-gradient(135deg,#4f8ef7,#7b5cf0)", color: "#fff", fontFamily: "var(--font-sans)", fontSize: 13, fontWeight: 600, cursor: "pointer", opacity: (creating || !newKeyName.trim()) ? 0.6 : 1 }}>
              {creating ? "Creating…" : "Generate Key"}
            </button>
          </div>
        )}

        {keys.length === 0 ? (
          <div style={{ padding: 28, textAlign: "center", color: "var(--color-text-tertiary)", fontSize: 13, border: "1px dashed var(--border-glass)", borderRadius: 10 }}>
            No API keys yet.{isArchitect && " Generate your first key above to start integrating."}
          </div>
        ) : (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            {keys.map(k => (
              <div key={k.id} style={{ display: "flex", alignItems: "center", gap: 14, padding: "12px 16px", borderRadius: 10, background: "rgba(255,255,255,0.03)", border: "1px solid var(--border-glass)" }}>
                <div style={{ width: 34, height: 34, borderRadius: 8, background: "rgba(79,142,247,0.12)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 16 }}>🔑</div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text-primary)" }}>{k.name}</div>
                  <div style={{ fontSize: 11, color: "var(--color-text-tertiary)", marginTop: 2, fontFamily: "var(--font-mono)" }}>
                    {k.key_prefix}•••••••••••••••••••••••
                    {k.last_used_at && <span style={{ marginLeft: 10 }}>Last used: {new Date(k.last_used_at).toLocaleDateString()}</span>}
                  </div>
                </div>
                <div style={{ padding: "3px 10px", borderRadius: 999, fontSize: 11, fontWeight: 600, background: "rgba(34,211,168,0.1)", border: "1px solid rgba(34,211,168,0.25)", color: "#22d3a8" }}>Active</div>
                {isArchitect && <button onClick={() => handleRevoke(k.id, k.name)} style={{ height: 28, padding: "0 12px", borderRadius: 6, border: "1px solid rgba(248,113,113,0.25)", background: "rgba(248,113,113,0.06)", color: "#f87171", fontFamily: "var(--font-sans)", fontSize: 11, fontWeight: 600, cursor: "pointer" }}>Revoke</button>}
              </div>
            ))}
          </div>
        )}
      </div>)}

      {/* Endpoint reference */}
      {card(<div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={{ fontSize: 15, fontWeight: 700, color: "var(--color-text-primary)" }}>📖 Endpoint Reference</div>
        <div style={{ fontSize: 12, color: "var(--color-text-tertiary)", fontFamily: "var(--font-mono)", marginBottom: 4 }}>Base URL: {BACKEND}</div>
        {ENDPOINTS.map(e => (
          <div key={e.path} style={{ display: "flex", gap: 14, alignItems: "flex-start", padding: "10px 14px", borderRadius: 8, background: "rgba(255,255,255,0.03)", border: "1px solid var(--border-glass)" }}>
            <span style={{ flex: "0 0 60px", fontFamily: "var(--font-mono)", fontSize: 11, fontWeight: 700, color: METHOD_COLORS[e.method] }}>{e.method}</span>
            <code style={{ flex: "0 0 220px", fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--color-text-primary)" }}>{e.path}</code>
            <span style={{ fontSize: 12, color: "var(--color-text-secondary)" }}>{e.desc}</span>
          </div>
        ))}
        <div style={{ marginTop: 4, padding: "14px 16px", borderRadius: 10, background: "rgba(79,142,247,0.05)", border: "1px solid rgba(79,142,247,0.12)", fontSize: 12, color: "var(--color-text-secondary)", lineHeight: 1.8 }}>
          <strong style={{ color: "#4f8ef7" }}>Example request:</strong><br />
          <code style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "#e8eaf6" }}>
            curl -X POST {BACKEND}/api/v1/tasks \<br />
            &nbsp;&nbsp;-H "X-API-Key: sk_live_..." \<br />
            &nbsp;&nbsp;-H "Content-Type: application/json" \<br />
            &nbsp;&nbsp;-d {'\'{"title":"Fix payment bug","assignee":"ali","priority":"high"}\''}
          </code>
        </div>
      </div>)}

      {/* Full docs link */}
      <div style={{ padding: "14px 18px", borderRadius: 12, background: "rgba(255,255,255,0.03)", border: "1px solid var(--border-glass)", fontSize: 12, color: "var(--color-text-tertiary)" }}>
        📄 Full interactive API docs available at <code style={{ color: "#4f8ef7", fontFamily: "var(--font-mono)" }}>{BACKEND}/docs</code> (FastAPI Swagger UI — no auth needed).
      </div>
    </main>
  );
}

// ── Authenticated shell — wraps Dashboard with Sidebar ────────────────────────
function AuthenticatedApp() {
  const { user, isOnboarded, token } = useAuth();
  const [activeNav, setActiveNav]   = useState(0);
  const [showOnboarding, setShowOnboarding] = useState(false);

  // ✅ Role-based task filters passed to useTasks
  const taskFilters = useMemo(() => {
    if (!user) return {};
    if (user.role === "architect") return { workspace_id: user.workspace?.id };
    if (user.role === "navigator") return { workspace_id: user.workspace?.id, team_name: user.team_name };
    if (user.role === "operator") return { owner_id: user.id };
    if (user.role === "solo")     return { owner_id: user.id };
    return {};
  }, [user]);

  const { tasks, total, loading, error, submitting, moveTask, removeTask, addTask, reload, clearError } = useTasks(taskFilters);

  const handleKeyDown = useCallback((e) => {
    if (e.key === "Escape") document.activeElement?.blur();
  }, []);

  // Check if Slack OAuth returned a token in the URL (after Slack login)
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const urlToken = params.get("token");
    if (urlToken) {
      // Clean URL
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, []);

  // If user hasn't completed onboarding
  if (!isOnboarded || showOnboarding) {
    return <OnboardingPage onComplete={() => setShowOnboarding(false)} />;
  }

  const currentNavLabel = NAV_ITEMS[activeNav]?.label;

  return (
    <div style={{ minHeight: "100vh", background: "var(--bg-page)", fontFamily: "var(--font-sans)" }} onKeyDown={handleKeyDown}>
      <Sidebar activeNav={activeNav} onNavChange={setActiveNav} />
      <div style={{ paddingLeft: 220, display: "flex", flexDirection: "column", minHeight: "100vh" }}>
        {activeNav === 0 ? (
          <Dashboard
            tasks={tasks} total={total} loading={loading} error={error}
            submitting={submitting} moveTask={moveTask} removeTask={removeTask}
            addTask={addTask} reload={reload} clearError={clearError}
          />
        ) : activeNav === 1 ? (
          <TasksPage />
        ) : activeNav === 2 ? (
          <CompliancePage />
        ) : activeNav === 4 ? (
          <ReportsPage />
        ) : activeNav === 5 ? (
          <OwnershipGraph />
        ) : activeNav === 6 ? (
          <IntegrationsPage />
        ) : activeNav === 7 ? (
          <LocalePage />
        ) : activeNav === 8 ? (
          <TeamsPage />
        ) : activeNav === 9 ? (
          <ApiPage />
        ) : (
          <PlaceholderPage label={currentNavLabel} />
        )}
      </div>
    </div>
  );
}

// ── Router — decides which page to show ──────────────────────────────────────
function AppRouter() {
  const { isAuthenticated, loading } = useAuth();
  const [goToOnboarding, setGoToOnboarding] = useState(false);

  // Show spinner while auth state is being restored from storage
  if (loading) return <AppLoader />;

  // Not logged in → show auth page
  if (!isAuthenticated) {
    return (
      <AuthPage
        onAuthSuccess={(user, isNew) => {
          if (isNew) setGoToOnboarding(true);
        }}
      />
    );
  }

  // Logged in → show dashboard (with onboarding check inside)
  return <AuthenticatedApp />;
}

// ── Root App — wraps everything in AuthProvider ───────────────────────────────
export default function App() {
  return (
    <>
      <style>{GLOBAL_STYLES}</style>
      <AuthProvider>
        <AppRouter />
      </AuthProvider>
    </>
  );
}
