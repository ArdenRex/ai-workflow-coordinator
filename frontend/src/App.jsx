// src/App.jsx
import React, { useState, useMemo, useCallback, useEffect } from "react";
import { AuthProvider, useAuth } from "./context/AuthContext";   // ✅ NEW
import AuthPage from "./pages/AuthPage";                          // ✅ NEW
import OnboardingPage from "./pages/OnboardingPage";             // ✅ NEW
import { useTasks } from "./hooks/useTasks";
import KanbanColumn from "./components/KanbanColumn";
import AddTaskModal from "./components/AddTaskModal";
import AddToSlackButton from "./components/AddToSlackButton";

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
  { icon: "⬡", label: "Dashboard",  badge: null },
  { icon: "✦", label: "Tasks",      badge: null },
  { icon: "◈", label: "Compliance", badge: "5"  },
  { icon: "◉", label: "Knowledge",  badge: null },
  { icon: "▲", label: "Reports",    badge: null },
  { icon: "⚙", label: "Settings",   badge: null },
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
