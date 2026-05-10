// src/App.jsx
import React, { useState, useMemo, useCallback, useEffect } from "react";
import { AuthProvider, useAuth } from "./context/AuthContext";   // ✅ NEW
import AuthPage from "./pages/AuthPage";                          // ✅ NEW
import OnboardingPage from "./pages/OnboardingPage";             // ✅ NEW
import AdminDashboard from "./pages/AdminDashboard";             // ✅ Super-admin
import { useTasks } from "./hooks/useTasks";
import KanbanColumn from "./components/KanbanColumn";
import AddTaskModal from "./components/AddTaskModal";
import AddToSlackButton from "./components/AddToSlackButton";

// -- API base URL — env var with hardcoded fallback ---------------------------
const BASE_URL = process.env.REACT_APP_API_URL || "https://ai-workflow-coordinator-api-production.up.railway.app";

// -- Responsive window width hook ---------------------------------------------
function useWindowWidth() {
  const [w, setW] = React.useState(window.innerWidth);
  React.useEffect(() => {
    const handler = () => setW(window.innerWidth);
    window.addEventListener("resize", handler);
    return () => window.removeEventListener("resize", handler);
  }, []);
  return w;
}



// -- Date formatting utility ---------------------------------------------------
// Normalises "2026-04-30" and "2026-04-30T00:00:00[Z]" → local Date object.
// When a timezone string (IANA, e.g. "Asia/Karachi") is supplied the date is
// displayed in that zone; otherwise it falls back to the browser's local time.
function formatDeadline(raw, timezone, opts = {}) {
  if (!raw) return null;
  // Force local-time parsing for bare date strings (avoids UTC-midnight shift)
  const normalised = /T/.test(raw) ? raw : raw + "T00:00:00";
  const date = new Date(normalised);
  if (isNaN(date.getTime())) return raw; // unparseable — return raw as fallback
  const baseOpts = { day: "numeric", month: "short", year: "numeric", ...opts };
  try {
    return date.toLocaleDateString(undefined, timezone ? { ...baseOpts, timeZone: timezone } : baseOpts);
  } catch {
    return date.toLocaleDateString(undefined, baseOpts);
  }
}

// Same normalisation used for overdue comparisons (returns a Date)
function parseDeadline(raw) {
  if (!raw) return null;
  const normalised = /T/.test(raw) ? raw : raw + "T00:00:00";
  const d = new Date(normalised);
  return isNaN(d.getTime()) ? null : d;
}

// -- CSS variables + animations ------------------------------------------------
const GLOBAL_STYLES = `
  @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;500;600;700;800&family=DM+Sans:ital,opsz,wght@0,9..40,300;0,9..40,400;0,9..40,500;0,9..40,600;1,9..40,300&family=JetBrains+Mono:wght@400;500&display=swap');

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    /* Core palette */
    --bg-base:            #07080f;
    --bg-page:            #090d18;
    --bg-sidebar:         #07080f;
    --bg-card:            rgba(255,255,255,0.032);
    --bg-card-hover:      rgba(255,255,255,0.058);
    --bg-elevated:        rgba(255,255,255,0.06);

    /* Borders */
    --border-glass:       rgba(255,255,255,0.072);
    --border-strong:      rgba(255,255,255,0.14);

    /* Accent colors */
    --accent-blue:        #3b82f6;
    --accent-violet:      #8b5cf6;
    --accent-cyan:        #06b6d4;
    --accent-emerald:     #10b981;
    --accent-amber:       #f59e0b;
    --accent-rose:        #f43f5e;
    --accent-1:           #3b82f6;

    /* Gradients */
    --grad-primary:       linear-gradient(135deg, #3b82f6 0%, #8b5cf6 100%);
    --grad-success:       linear-gradient(135deg, #10b981 0%, #06b6d4 100%);
    --grad-danger:        linear-gradient(135deg, #f43f5e 0%, #fb923c 100%);
    --grad-amber:         linear-gradient(135deg, #f59e0b 0%, #f97316 100%);
    --grad-sidebar:       linear-gradient(180deg, #07080f 0%, #060810 100%);

    /* Text */
    --color-text-primary:   #f1f3fc;
    --color-text-secondary: #8892b0;
    --color-text-tertiary:  #4a5378;
    --color-text-muted:     #2d3450;

    /* Typography */
    --font-display: 'Syne', sans-serif;
    --font-sans:    'DM Sans', sans-serif;
    --font-mono:    'JetBrains Mono', monospace;

    /* Shadows */
    --shadow-sm:   0 1px 3px rgba(0,0,0,0.4);
    --shadow-md:   0 4px 16px rgba(0,0,0,0.5);
    --shadow-lg:   0 12px 40px rgba(0,0,0,0.6);
    --shadow-glow: 0 0 24px rgba(59,130,246,0.3);

    /* Radius */
    --radius-sm:  6px;
    --radius-md:  10px;
    --radius-lg:  16px;
    --radius-xl:  22px;
  }

  html { scroll-behavior: smooth; }

  body {
    background: var(--bg-page);
    color: var(--color-text-primary);
    font-family: var(--font-sans);
    font-size: 14px;
    line-height: 1.5;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    overflow-x: auto;
  }

  /* Scrollbar */
  ::-webkit-scrollbar { width: 4px; height: 4px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 999px; }
  ::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.2); }

  /* Animations */
  @keyframes spin    { to { transform: rotate(360deg); } }
  @keyframes pulse   { 0%,100% { opacity:1; } 50% { opacity:0.4; } }
  @keyframes shimmer { 0% { background-position: -200% 0; } 100% { background-position: 200% 0; } }
  @keyframes fadeUp  { from { opacity:0; transform:translateY(16px); } to { opacity:1; transform:translateY(0); } }
  @keyframes slideIn { from { opacity:0; transform:translateX(-8px); } to { opacity:1; transform:translateX(0); } }
  @keyframes scaleIn { from { opacity:0; transform:scale(0.96); } to { opacity:1; transform:scale(1); } }
  @keyframes glow-pulse { 0%,100% { box-shadow: 0 0 20px rgba(59,130,246,0.3); } 50% { box-shadow: 0 0 40px rgba(59,130,246,0.6); } }

  .fade-up         { animation: fadeUp 0.45s cubic-bezier(0.16,1,0.3,1) both; }
  .fade-up.delay-1 { animation-delay: 0.08s; }
  .fade-up.delay-2 { animation-delay: 0.16s; }
  .fade-up.delay-3 { animation-delay: 0.24s; }
  .scale-in        { animation: scaleIn 0.3s cubic-bezier(0.16,1,0.3,1) both; }
  .slide-in        { animation: slideIn 0.35s cubic-bezier(0.16,1,0.3,1) both; }

  /* Noise texture overlay on sidebar */
  .noise-bg::before {
    content: '';
    position: absolute;
    inset: 0;
    background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='0.04'/%3E%3C/svg%3E");
    pointer-events: none;
    border-radius: inherit;
    z-index: 0;
  }

  /* Focus ring */
  :focus-visible { outline: 2px solid rgba(59,130,246,0.6); outline-offset: 2px; border-radius: 4px; }

  /* Selection */
  ::selection { background: rgba(59,130,246,0.25); color: #f1f3fc; }

  /* -- Premium card hover --------------- */
  .pcard {
    background: rgba(255,255,255,0.032);
    border: 1px solid var(--border-glass);
    border-radius: var(--radius-lg);
    transition: transform 0.2s cubic-bezier(0.34,1.56,0.64,1), box-shadow 0.2s, border-color 0.2s;
  }
  .pcard:hover {
    transform: translateY(-2px);
    box-shadow: 0 12px 40px rgba(0,0,0,0.5), 0 0 0 1px rgba(255,255,255,0.07);
    border-color: rgba(255,255,255,0.1);
  }

  /* -- Table rows ----------------------- */
  .trow {
    transition: background 0.12s;
    border-radius: 8px;
  }
  .trow:hover { background: rgba(255,255,255,0.04) !important; }

  /* -- Btn primary ---------------------- */
  .btn-primary {
    height: 38px; padding: 0 20px; border-radius: 10px; border: none;
    background: var(--grad-primary); color: #fff;
    font-family: var(--font-sans); font-size: 13px; font-weight: 600;
    cursor: pointer; display: inline-flex; align-items: center; gap: 7px;
    box-shadow: 0 0 24px rgba(59,130,246,0.35), inset 0 1px 0 rgba(255,255,255,0.18);
    transition: transform 0.12s, box-shadow 0.12s, opacity 0.12s;
    white-space: nowrap;
  }
  .btn-primary:hover { transform: translateY(-1px); box-shadow: 0 0 36px rgba(59,130,246,0.5), inset 0 1px 0 rgba(255,255,255,0.22); }
  .btn-primary:active { transform: translateY(0); }
  .btn-primary:disabled { opacity: 0.5; cursor: not-allowed; transform: none; }

  /* -- Btn ghost ------------------------ */
  .btn-ghost {
    height: 38px; padding: 0 16px; border-radius: 10px;
    border: 1px solid var(--border-glass);
    background: rgba(255,255,255,0.03); color: var(--color-text-secondary);
    font-family: var(--font-sans); font-size: 13px; font-weight: 500;
    cursor: pointer; display: inline-flex; align-items: center; gap: 7px;
    transition: all 0.12s;
  }
  .btn-ghost:hover { background: rgba(255,255,255,0.07); color: var(--color-text-primary); border-color: rgba(255,255,255,0.12); }

  /* -- Input field ---------------------- */
  .field-input {
    width: 100%; height: 40px; padding: 0 13px;
    background: rgba(255,255,255,0.04);
    border: 1px solid var(--border-glass);
    border-radius: 9px; font-family: var(--font-sans); font-size: 13px;
    color: var(--color-text-primary); outline: none;
    transition: border-color 0.15s, box-shadow 0.15s, background 0.15s;
    box-sizing: border-box;
  }
  .field-input:focus {
    border-color: rgba(59,130,246,0.55);
    background: rgba(59,130,246,0.06);
    box-shadow: 0 0 0 3px rgba(59,130,246,0.14);
  }
  .field-input::placeholder { color: var(--color-text-muted); }

  /* -- Page header ---------------------- */
  .page-header {
    position: sticky; top: 0; z-index: 40; min-height: 56px;
    background: rgba(7,8,15,0.88);
    backdrop-filter: blur(28px); -webkit-backdrop-filter: blur(28px);
    border-bottom: 1px solid rgba(255,255,255,0.055);
    box-shadow: 0 1px 0 rgba(59,130,246,0.07), 0 4px 20px rgba(0,0,0,0.25);
    padding: 10px clamp(12px, 2.5vw, 28px); display: flex; align-items: center; gap: 10; flex-wrap: wrap;
  }

  /* -- Section card --------------------- */
  .section-card {
    background: rgba(255,255,255,0.03);
    border: 1px solid var(--border-glass);
    border-radius: var(--radius-lg);
    padding: 22px 24px;
  }

  /* -- Badge ---------------------------- */
  .badge {
    display: inline-flex; align-items: center; gap: 4px;
    padding: 3px 9px; border-radius: 999px;
    font-size: 11px; font-weight: 600; letter-spacing: 0.01em;
    border: 1px solid transparent;
  }

  /* -- Animated counter ----------------- */
  @keyframes countUp { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: translateY(0); } }
  .count-up { animation: countUp 0.4s cubic-bezier(0.16,1,0.3,1) both; }

  /* -- Skeleton shimmer ----------------- */
  .skeleton {
    background: linear-gradient(90deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0.09) 50%, rgba(255,255,255,0.04) 100%);
    background-size: 200% 100%;
    animation: shimmer 1.4s ease-in-out infinite;
    border-radius: 6px;
  }

  /* -- Modal backdrop ------------------- */
  .modal-backdrop {
    position: fixed; inset: 0; z-index: 200;
    background: rgba(0,0,0,0.65);
    backdrop-filter: blur(8px);
    display: flex; align-items: center; justify-content: center;
    animation: scaleIn 0.18s ease both;
  }
  .modal-box {
    background: linear-gradient(160deg, #13172b 0%, #0e1122 100%);
    border: 1px solid rgba(255,255,255,0.1);
    border-radius: var(--radius-xl);
    box-shadow: 0 32px 100px rgba(0,0,0,0.7), 0 0 0 1px rgba(59,130,246,0.1);
    animation: scaleIn 0.22s cubic-bezier(0.34,1.56,0.64,1) both;
    max-width: calc(100vw - 32px);
    width: 100%;
  }

  /* -- Status pill ---------------------- */
  .status-pill {
    display: inline-flex; align-items: center; gap: 5px;
    padding: 3px 10px; border-radius: 999px; font-size: 11px; font-weight: 600;
    border: 1px solid transparent;
  }
  .status-pill::before {
    content: ''; width: 5px; height: 5px; border-radius: 50%;
    background: currentColor; opacity: 0.8; flex-shrink: 0;
  }

  /* -- Progress bar --------------------- */
  .progress-track {
    height: 5px; border-radius: 999px;
    background: rgba(255,255,255,0.07); overflow: hidden;
  }
  .progress-fill {
    height: 100%; border-radius: 999px;
    transition: width 0.7s cubic-bezier(0.16,1,0.3,1);
  }

  /* -- Glow orb ------------------------- */
  .glow-orb {
    position: absolute; border-radius: 50%;
    pointer-events: none; filter: blur(32px);
  }

  /* -- Icon bubble ---------------------- */
  .icon-bubble {
    display: flex; align-items: center; justify-content: center;
    border-radius: var(--radius-md); flex-shrink: 0;
  }

  /* -- Page transition ------------------ */
  @keyframes pageIn {
    from { opacity: 0; transform: translateY(10px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  .page-enter { animation: pageIn 0.32s cubic-bezier(0.16,1,0.3,1) both; }

  /* -- Ripple on click ------------------ */
  @keyframes ripple {
    from { transform: scale(0); opacity: 0.4; }
    to   { transform: scale(2.5); opacity: 0; }
  }

  /* -- Task row ------------------------- */
  .task-row {
    display: grid; align-items: center;
    border-radius: 10px; padding: 10px 14px;
    transition: background 0.12s, box-shadow 0.12s;
    position: relative; overflow: hidden;
  }
  .task-row:hover {
    background: rgba(255,255,255,0.045) !important;
    box-shadow: inset 0 0 0 1px rgba(255,255,255,0.06);
  }

  /* -- Ownership node card -------------- */
  .owner-card {
    background: rgba(255,255,255,0.04);
    border: 1px solid var(--border-glass);
    border-radius: var(--radius-lg);
    padding: 18px 20px; cursor: pointer;
    transition: transform 0.2s cubic-bezier(0.34,1.56,0.64,1), box-shadow 0.2s, border-color 0.15s;
    position: relative; overflow: hidden;
  }
  .owner-card:hover {
    transform: translateY(-3px) scale(1.01);
    box-shadow: 0 12px 36px rgba(0,0,0,0.45);
    border-color: rgba(255,255,255,0.12);
  }
  .owner-card.selected {
    background: linear-gradient(135deg, rgba(59,130,246,0.14) 0%, rgba(139,92,246,0.14) 100%);
    border-color: rgba(59,130,246,0.45);
  }

  /* -- Integration card ----------------- */
  .integ-card {
    background: rgba(255,255,255,0.035);
    border: 1px solid var(--border-glass);
    border-radius: var(--radius-lg);
    padding: 24px 26px; overflow: hidden; position: relative;
    transition: border-color 0.2s, box-shadow 0.2s;
  }
  .integ-card:hover {
    border-color: rgba(255,255,255,0.1);
    box-shadow: 0 8px 32px rgba(0,0,0,0.35);
  }

  /* -- Pulse dot for live status -------- */
  @keyframes pulseDot {
    0%, 100% { box-shadow: 0 0 0 0 rgba(34,211,168,0.4); }
    50%       { box-shadow: 0 0 0 5px rgba(34,211,168,0); }
  }
  .pulse-dot {
    width: 7px; height: 7px; border-radius: 50%;
    background: #22d3a8; animation: pulseDot 2s ease-in-out infinite;
  }

  /* -- Tooltip -------------------------- */
  .has-tooltip { position: relative; }
  .has-tooltip:hover::after {
    content: attr(data-tip);
    position: absolute; bottom: 110%; left: 50%; transform: translateX(-50%);
    background: #1e2340; border: 1px solid var(--border-glass);
    color: var(--color-text-secondary); font-size: 11px; font-weight: 500;
    padding: 4px 9px; border-radius: 6px; white-space: nowrap;
    pointer-events: none; animation: fadeUp 0.15s ease both;
    font-family: var(--font-sans); z-index: 100;
  }

  /* -- Stagger fade for list items ------ */
  .stagger > * { animation: fadeUp 0.4s cubic-bezier(0.16,1,0.3,1) both; }
  .stagger > *:nth-child(1) { animation-delay: 0.04s; }
  .stagger > *:nth-child(2) { animation-delay: 0.08s; }
  .stagger > *:nth-child(3) { animation-delay: 0.12s; }
  .stagger > *:nth-child(4) { animation-delay: 0.16s; }
  .stagger > *:nth-child(5) { animation-delay: 0.20s; }
  .stagger > *:nth-child(6) { animation-delay: 0.24s; }

  /* -- Tour overlay --------------------- */
  @keyframes tourIn {
    from { opacity: 0; transform: scale(0.92) translateY(16px); }
    to   { opacity: 1; transform: scale(1) translateY(0); }
  }
  @keyframes tourSlide {
    from { opacity: 0; transform: translateX(24px); }
    to   { opacity: 1; transform: translateX(0); }
  }
  @keyframes spotlightPulse {
    0%,100% { box-shadow: 0 0 0 4px rgba(59,130,246,0.4), 0 0 0 8px rgba(59,130,246,0.15); }
    50%      { box-shadow: 0 0 0 6px rgba(59,130,246,0.55), 0 0 0 14px rgba(59,130,246,0.08); }
  }
  @keyframes spin {
    from { transform: rotate(0deg); }
    to   { transform: rotate(360deg); }
  }

  @keyframes slideUpIn {
    from { opacity: 0; transform: translateY(24px) scale(0.96); }
    to   { opacity: 1; transform: translateY(0)    scale(1); }
  }

  @keyframes confettiFall {
    0%   { opacity: 1; transform: translateY(0) rotate(0deg) scale(1); }
    100% { opacity: 0; transform: translateY(320px) rotate(var(--rot,360deg)) scale(0.4); }
  }

  @keyframes particleFloat {
    0%   { transform: translateY(0px) rotate(0deg); opacity: 0.8; }
    50%  { transform: translateY(-18px) rotate(180deg); opacity: 0.4; }
    100% { transform: translateY(-36px) rotate(360deg); opacity: 0; }
  }
  .tour-card { animation: tourIn 0.38s cubic-bezier(0.34,1.56,0.64,1) both; }
  .tour-step-slide { animation: tourSlide 0.3s cubic-bezier(0.16,1,0.3,1) both; }

`;

// -- Tour step definitions -----------------------------------------------------
const TOUR_STEPS = [
  {
    id: "welcome", emoji: "👋", title: "Welcome to AI Workflow Coordinator",
    subtitle: "Your intelligent command center",
    description: "You're about to master the most powerful workflow tool your team has ever used. This quick tour will show you everything — it only takes 2 minutes.",
    color: "#3b82f6", gradient: "linear-gradient(135deg,#3b82f6 0%,#8b5cf6 100%)", tip: null, xp: 0,
  },
  {
    id: "dashboard", emoji: "⬡", title: "Dashboard — Your Mission Control",
    subtitle: "Everything at a glance",
    description: "The Dashboard shows your live task counts, Kanban board, team status, and a real-time system health indicator. It's the first page you'll see every morning.",
    color: "#3b82f6", gradient: "linear-gradient(135deg,#3b82f6 0%,#06b6d4 100%)",
    tip: "💡 Pro tip: The Kanban board lets you drag tasks between columns — or click a card to see full details.", xp: 10,
  },
  {
    id: "nav_badges", emoji: "🔴", title: "Live Sidebar Badges — Always in the Know",
    subtitle: "Real-time counts on every nav item",
    description: "Every section of the sidebar shows a live number badge that updates automatically as your data changes. No need to click into a page to know what's waiting for you.",
    color: "#f59e0b", gradient: "linear-gradient(135deg,#f59e0b 0%,#f97316 100%)",
    tip: "💡 What each badge means:\n🟠 Dashboard = active (in-progress) tasks\n🔵 Tasks = total task count\n🔴 Compliance = issues needing attention\n🟢 Reports = completed tasks\n🟣 Ownership = number of owners",
    xp: 18,
    isBadgeStep: true,
  },
  {
    id: "tasks", emoji: "✦", title: "Tasks — Full Task Management",
    subtitle: "Create, assign, track, complete",
    description: "The Tasks page gives you a filterable table of every task. Create new tasks, assign them to teammates, set priorities (Critical → Low), and add deadlines.",
    color: "#8b5cf6", gradient: "linear-gradient(135deg,#8b5cf6 0%,#ec4899 100%)",
    tip: "💡 Pro tip: Use the search bar + status/priority filters to instantly zero in on what matters.", xp: 27,
  },
  {
    id: "compliance", emoji: "◈", title: "Compliance — Task Health Monitor",
    subtitle: "Catch problems before they explode",
    description: "Compliance automatically flags overdue tasks, unassigned work, stale tasks (7+ days inactive), and high-priority items that haven't started yet. Your score shows overall team health.",
    color: "#f43f5e", gradient: "linear-gradient(135deg,#f43f5e 0%,#fb923c 100%)",
    tip: "💡 Pro tip: Keep your Compliance Score above 80% — that means your team is running clean.", xp: 36,
  },
  {
    id: "knowledge", emoji: "◉", title: "Knowledge — Team Brain",
    subtitle: "Document everything, forget nothing",
    description: "Store SOPs, runbooks, decision logs, and team notes in the Knowledge base. Pin critical docs so they're always visible, and search across everything instantly.",
    color: "#10b981", gradient: "linear-gradient(135deg,#10b981 0%,#06b6d4 100%)",
    tip: "💡 Pro tip: Tag your notes with categories to keep things organised as your library grows.", xp: 45,
  },
  {
    id: "ownership", emoji: "⊕", title: "Ownership — Who Owns What",
    subtitle: "Visualise workload distribution",
    description: "The Ownership Graph shows every team member's task load — how many tasks they own, their completion rate, and priority breakdown. Spot overloaded teammates instantly.",
    color: "#f59e0b", gradient: "linear-gradient(135deg,#f59e0b 0%,#f97316 100%)",
    tip: "💡 Pro tip: Click any person card to expand their full task list with status and deadlines.", xp: 54,
  },
  {
    id: "reports", emoji: "▲", title: "Reports — Performance Analytics",
    subtitle: "Data-driven decisions",
    description: "Reports gives you completion rates, velocity trends, priority distribution, and KPIs over time. Share these with stakeholders to show team progress.",
    color: "#06b6d4", gradient: "linear-gradient(135deg,#06b6d4 0%,#3b82f6 100%)",
    tip: "💡 Pro tip: Check Reports weekly to spot trends before they become problems.", xp: 63,
  },
  {
    id: "integrations", emoji: "⛓", title: "Integrations — Connect Your Stack",
    subtitle: "Slack, GitHub, Zapier and more",
    description: "Connect AI Workflow to your existing tools. Get Slack notifications when tasks are assigned or overdue, trigger automations via Zapier, or post updates to GitHub.",
    color: "#8b5cf6", gradient: "linear-gradient(135deg,#8b5cf6 0%,#3b82f6 100%)",
    tip: "💡 Pro tip: Enable the Slack integration first — your team will get nudged about deadlines automatically.", xp: 72,
  },
  {
    id: "api", emoji: "🔑", title: "API — Build On Top",
    subtitle: "Full REST API access",
    description: "Every feature in this app is available via API. Generate API keys, browse the endpoint reference, and build your own automations or integrations on top of your workflow data.",
    color: "#10b981", gradient: "linear-gradient(135deg,#10b981 0%,#8b5cf6 100%)",
    tip: "💡 Pro tip: The API docs are available at /docs — fully interactive with Swagger UI.", xp: 81,
  },
  {
    id: "finish", emoji: "🏆", title: "You're Ready to Command!",
    subtitle: "Tour complete — 100 XP earned",
    description: "You now know everything about AI Workflow Coordinator. Your dashboard is live, your team is waiting, and your first task is to create something worth doing.",
    color: "#f59e0b", gradient: "linear-gradient(135deg,#f59e0b 0%,#f43f5e 100%)",
    tip: null, xp: 100,
  },
];

// -- Confetti burst on tour finish ---------------------------------------------
function ConfettiBurst() {
  const pieces = [...Array(60)].map((_, i) => ({
    id: i,
    x: 40 + Math.random() * 20,
    color: ["#3b82f6","#8b5cf6","#f59e0b","#10b981","#f43f5e","#06b6d4","#ec4899"][i % 7],
    size: 6 + Math.random() * 8,
    delay: Math.random() * 0.6,
    dur: 1.2 + Math.random() * 1,
    rot: Math.random() * 720 - 360,
    shape: i % 3,
  }));
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden", pointerEvents: "none", zIndex: 10 }}>
      {pieces.map(p => (
        <div key={p.id} style={{
          position: "absolute",
          left: `${p.x}%`, top: "30%",
          width: p.size, height: p.shape === 2 ? p.size * 0.4 : p.size,
          background: p.color,
          borderRadius: p.shape === 0 ? "50%" : p.shape === 1 ? "2px" : "1px",
          opacity: 0,
          animation: `confettiFall ${p.dur}s ${p.delay}s ease-out forwards`,
          transform: `rotate(${p.rot}deg)`,
        }} />
      ))}
    </div>
  );
}

// -- Floating particles --------------------------------------------------------
function TourParticles({ color }) {
  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden", pointerEvents: "none", borderRadius: "inherit" }}>
      {[...Array(10)].map((_, i) => (
        <div key={i} style={{
          position: "absolute", borderRadius: i % 2 === 0 ? "50%" : "2px",
          background: color, opacity: 0.5,
          width: 3 + (i % 4) * 2, height: 3 + (i % 4) * 2,
          left: `${5 + i * 10}%`, bottom: "8%",
          animation: `particleFloat ${1.6 + i * 0.25}s ease-in-out ${i * 0.15}s infinite`,
        }} />
      ))}
    </div>
  );
}

// -- Feature preview illustrations per step ---------------------------------
function StepVisual({ stepId, color }) {
  const s = { borderRadius: 8, overflow: "hidden", position: "relative" };
  if (stepId === "welcome") return (
    <div style={{ ...s, background: "rgba(59,130,246,0.07)", border: "1px solid rgba(59,130,246,0.18)", padding: "18px 20px", display: "flex", gap: 14, alignItems: "center" }}>
      {[["⬡","Dashboard","#3b82f6"],["✦","Tasks","#8b5cf6"],["◈","Compliance","#f43f5e"],["⊕","Ownership","#f59e0b"],["▲","Reports","#06b6d4"],["🔑","API","#10b981"]].map(([icon, label, c]) => (
        <div key={label} style={{ display:"flex",flexDirection:"column",alignItems:"center",gap:5,flex:1 }}>
          <div style={{ width:36,height:36,borderRadius:10,background:`${c}20`,border:`1px solid ${c}35`,display:"flex",alignItems:"center",justifyContent:"center",fontSize:16 }}>{icon}</div>
          <div style={{ fontSize:9,color:"var(--color-text-tertiary)",fontWeight:600,letterSpacing:"0.04em",textTransform:"uppercase" }}>{label}</div>
        </div>
      ))}
    </div>
  );
  if (stepId === "dashboard") return (
    <div style={{ ...s, background:"rgba(255,255,255,0.03)",border:"1px solid var(--border-glass)",padding:"14px 16px" }}>
      <div style={{ display:"flex",gap:8,marginBottom:10 }}>
        {[["24","Tasks","#3b82f6"],["8","In Progress","#f59e0b"],["3","Overdue","#f43f5e"]].map(([n,l,c])=>(
          <div key={l} style={{ flex:1,background:`${c}12`,border:`1px solid ${c}28`,borderRadius:8,padding:"8px 10px" }}>
            <div style={{ fontSize:18,fontWeight:800,color:c,fontFamily:"var(--font-display)" }}>{n}</div>
            <div style={{ fontSize:10,color:"var(--color-text-tertiary)",marginTop:1 }}>{l}</div>
          </div>
        ))}
      </div>
      <div style={{ display:"flex",gap:6 }}>
        {[["To Do","#8b5cf6",3],["In Progress","#f59e0b",2],["Done","#10b981",4]].map(([l,c,cnt])=>(
          <div key={l} style={{ flex:1,background:"rgba(255,255,255,0.02)",border:`1px solid ${c}22`,borderRadius:6,padding:"8px 8px" }}>
            <div style={{ fontSize:9,fontWeight:700,color:c,marginBottom:6,textTransform:"uppercase",letterSpacing:"0.05em" }}>{l}</div>
            {[...Array(cnt)].map((_,i)=><div key={i} style={{ height:5,borderRadius:3,background:c,opacity:0.15+i*0.12,marginBottom:3 }}/>)}
          </div>
        ))}
      </div>
    </div>
  );
  if (stepId === "nav_badges") return (
    <div style={{ ...s, background:"rgba(255,255,255,0.03)",border:"1px solid var(--border-glass)",padding:"12px 14px",display:"flex",flexDirection:"column",gap:7 }}>
      {[["⬡","Dashboard","#f59e0b","8"],["✦","Tasks","#3b82f6","24"],["◈","Compliance","#f43f5e","3"],["▲","Reports","#10b981","12"],["⊕","Ownership","#8b5cf6","5"]].map(([icon,label,c,badge])=>(
        <div key={label} style={{ display:"flex",alignItems:"center",gap:9,padding:"5px 8px",borderRadius:7,background:"rgba(255,255,255,0.025)" }}>
          <span style={{ fontSize:13 }}>{icon}</span>
          <span style={{ flex:1,fontSize:12,color:"var(--color-text-secondary)",fontWeight:500 }}>{label}</span>
          <div style={{ minWidth:20,height:18,borderRadius:999,background:`${c}25`,border:`1px solid ${c}45`,display:"flex",alignItems:"center",justifyContent:"center",padding:"0 6px" }}>
            <span style={{ fontSize:10,fontWeight:700,color:c }}>{badge}</span>
          </div>
        </div>
      ))}
    </div>
  );
  if (stepId === "tasks") return (
    <div style={{ ...s, background:"rgba(255,255,255,0.03)",border:"1px solid var(--border-glass)",padding:"12px 14px" }}>
      <div style={{ display:"flex",gap:6,marginBottom:10 }}>
        {["All","To Do","In Progress","Done"].map((t,i)=>(
          <div key={t} style={{ padding:"3px 10px",borderRadius:999,fontSize:10,fontWeight:600,background:i===0?"rgba(139,92,246,0.2)":"rgba(255,255,255,0.04)",border:i===0?"1px solid rgba(139,92,246,0.4)":"1px solid var(--border-glass)",color:i===0?"#8b5cf6":"var(--color-text-tertiary)" }}>{t}</div>
        ))}
      </div>
      {[["Fix auth bug","critical","#f43f5e","Alex"],["Write docs","high","#f59e0b","Sam"],["Deploy v2","medium","#8b5cf6","Kim"],["Add tests","low","#10b981","—"]].map(([task,pri,c,ass])=>(
        <div key={task} style={{ display:"flex",alignItems:"center",gap:8,padding:"6px 0",borderBottom:"1px solid rgba(255,255,255,0.04)" }}>
          <div style={{ width:6,height:6,borderRadius:"50%",background:c,flexShrink:0 }}/>
          <span style={{ flex:1,fontSize:11,color:"var(--color-text-secondary)" }}>{task}</span>
          <span style={{ fontSize:9,padding:"2px 7px",borderRadius:999,background:`${c}18`,color:c,fontWeight:600,textTransform:"uppercase",letterSpacing:"0.04em" }}>{pri}</span>
          <span style={{ fontSize:10,color:"var(--color-text-tertiary)",minWidth:28,textAlign:"right" }}>{ass}</span>
        </div>
      ))}
    </div>
  );
  if (stepId === "compliance") return (
    <div style={{ ...s, background:"rgba(255,255,255,0.03)",border:"1px solid var(--border-glass)",padding:"14px 16px" }}>
      <div style={{ display:"flex",justifyContent:"space-between",alignItems:"center",marginBottom:12 }}>
        <span style={{ fontSize:11,color:"var(--color-text-secondary)",fontWeight:600 }}>Compliance Score</span>
        <span style={{ fontSize:22,fontWeight:800,color:"#10b981",fontFamily:"var(--font-display)" }}>84%</span>
      </div>
      <div style={{ height:5,borderRadius:999,background:"rgba(255,255,255,0.06)",marginBottom:12,overflow:"hidden" }}>
        <div style={{ height:"100%",width:"84%",borderRadius:999,background:"linear-gradient(90deg,#10b981,#06b6d4)",transition:"width 0.6s" }}/>
      </div>
      {[["Overdue tasks","2","#f43f5e"],["Unassigned","1","#f59e0b"],["Stale (7d+)","0","#10b981"],["High priority idle","1","#8b5cf6"]].map(([l,n,c])=>(
        <div key={l} style={{ display:"flex",justifyContent:"space-between",alignItems:"center",padding:"4px 0",borderBottom:"1px solid rgba(255,255,255,0.03)" }}>
          <span style={{ fontSize:11,color:"var(--color-text-tertiary)" }}>{l}</span>
          <span style={{ fontSize:12,fontWeight:700,color:c }}>{n}</span>
        </div>
      ))}
    </div>
  );
  if (stepId === "knowledge") return (
    <div style={{ ...s, background:"rgba(255,255,255,0.03)",border:"1px solid var(--border-glass)",padding:"12px 14px" }}>
      <div style={{ display:"flex",gap:6,marginBottom:9 }}>
        {[["📌","Pinned","#f59e0b"],["📄","SOP","#3b82f6"],["📋","Runbook","#8b5cf6"]].map(([e,l,c])=>(
          <div key={l} style={{ flex:1,padding:"6px 8px",borderRadius:8,background:`${c}12`,border:`1px solid ${c}28` }}>
            <div style={{ fontSize:14,marginBottom:4 }}>{e}</div>
            <div style={{ fontSize:9,color:c,fontWeight:600,textTransform:"uppercase",letterSpacing:"0.04em" }}>{l}</div>
          </div>
        ))}
      </div>
      {[["Deploy Runbook","📋","#8b5cf6"],["Auth SOP","📄","#3b82f6"],["Q3 Decisions","📝","#10b981"],["On-call Guide","⚡","#f43f5e"]].map(([title,e,c])=>(
        <div key={title} style={{ display:"flex",alignItems:"center",gap:8,padding:"5px 0",borderBottom:"1px solid rgba(255,255,255,0.04)" }}>
          <span style={{ fontSize:12 }}>{e}</span>
          <span style={{ flex:1,fontSize:11,color:"var(--color-text-secondary)" }}>{title}</span>
          <div style={{ width:6,height:6,borderRadius:"50%",background:c }}/>
        </div>
      ))}
    </div>
  );
  if (stepId === "ownership") return (
    <div style={{ ...s, background:"rgba(255,255,255,0.03)",border:"1px solid var(--border-glass)",padding:"12px 14px",display:"flex",flexDirection:"column",gap:7 }}>
      {[["Alex Chen","#3b82f6",8,75],["Sam Park","#8b5cf6",5,60],["Kim Lee","#10b981",3,90],["Jordan","#f59e0b",11,45]].map(([name,c,tasks,pct])=>(
        <div key={name} style={{ display:"flex",alignItems:"center",gap:9 }}>
          <div style={{ width:28,height:28,borderRadius:"50%",background:`${c}25`,border:`1.5px solid ${c}50`,display:"flex",alignItems:"center",justifyContent:"center",fontSize:11,fontWeight:700,color:c,flexShrink:0 }}>{name[0]}</div>
          <div style={{ flex:1 }}>
            <div style={{ display:"flex",justifyContent:"space-between",marginBottom:3 }}>
              <span style={{ fontSize:11,color:"var(--color-text-secondary)",fontWeight:500 }}>{name}</span>
              <span style={{ fontSize:10,color:"var(--color-text-tertiary)" }}>{tasks} tasks · {pct}%</span>
            </div>
            <div style={{ height:3,borderRadius:999,background:"rgba(255,255,255,0.06)",overflow:"hidden" }}>
              <div style={{ height:"100%",width:`${pct}%`,borderRadius:999,background:c,opacity:0.7 }}/>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
  if (stepId === "reports") return (
    <div style={{ ...s, background:"rgba(255,255,255,0.03)",border:"1px solid var(--border-glass)",padding:"14px 16px" }}>
      <div style={{ display:"flex",gap:8,marginBottom:12 }}>
        {[["Velocity","↑12%","#10b981"],["Done Rate","78%","#3b82f6"],["Avg Time","2.4d","#8b5cf6"]].map(([l,v,c])=>(
          <div key={l} style={{ flex:1,padding:"8px",borderRadius:8,background:`${c}10`,border:`1px solid ${c}25`,textAlign:"center" }}>
            <div style={{ fontSize:14,fontWeight:800,color:c,fontFamily:"var(--font-display)" }}>{v}</div>
            <div style={{ fontSize:9,color:"var(--color-text-tertiary)",marginTop:2,fontWeight:600 }}>{l}</div>
          </div>
        ))}
      </div>
      <div style={{ display:"flex",alignItems:"flex-end",gap:4,height:52 }}>
        {[35,55,42,68,50,75,90,62,80,95].map((h,i)=>(
          <div key={i} style={{ flex:1,height:`${h}%`,borderRadius:"3px 3px 0 0",background:i===9?"#3b82f6":i===8?"rgba(59,130,246,0.6)":"rgba(59,130,246,0.25)",transition:"height 0.3s" }}/>
        ))}
      </div>
      <div style={{ height:1,background:"rgba(255,255,255,0.05)",marginTop:2 }}/>
    </div>
  );
  if (stepId === "integrations") return (
    <div style={{ ...s, background:"rgba(255,255,255,0.03)",border:"1px solid var(--border-glass)",padding:"12px 14px",display:"grid",gridTemplateColumns:"1fr 1fr",gap:7 }}>
      {[["Slack","#4A154B","💬","Connected"],["GitHub","#24292e","⚡","Connect"],["Zapier","#FF4A00","⚙","Connect"],["Notion","#fff","📝","Connect"]].map(([name,c,e,status])=>(
        <div key={name} style={{ padding:"10px",borderRadius:8,background:"rgba(255,255,255,0.025)",border:`1px solid ${status==="Connected"?"rgba(16,185,129,0.35)":"var(--border-glass)"}` }}>
          <div style={{ display:"flex",justifyContent:"space-between",alignItems:"flex-start",marginBottom:5 }}>
            <span style={{ fontSize:16 }}>{e}</span>
            <div style={{ fontSize:9,padding:"2px 6px",borderRadius:999,background:status==="Connected"?"rgba(16,185,129,0.2)":"rgba(255,255,255,0.07)",color:status==="Connected"?"#10b981":"var(--color-text-tertiary)",fontWeight:600 }}>{status}</div>
          </div>
          <div style={{ fontSize:11,color:"var(--color-text-secondary)",fontWeight:600 }}>{name}</div>
        </div>
      ))}
    </div>
  );
  if (stepId === "api") return (
    <div style={{ ...s, background:"#0a0c14",border:"1px solid rgba(16,185,129,0.2)",padding:"12px 16px",fontFamily:"var(--font-mono)" }}>
      <div style={{ display:"flex",gap:6,marginBottom:8 }}>
        {["GET","POST","PUT","DELETE"].map((m,i)=>(<div key={m} style={{ padding:"2px 8px",borderRadius:4,fontSize:9,fontWeight:700,background:["rgba(16,185,129,0.2)","rgba(59,130,246,0.2)","rgba(245,158,11,0.2)","rgba(244,63,94,0.2)"][i],color:["#10b981","#3b82f6","#f59e0b","#f43f5e"][i] }}>{m}</div>))}
      </div>
      {["/tasks","  → list + filter","/tasks/:id","  → task details","/tasks (POST)","  → create task"].map((line,i)=>(
        <div key={i} style={{ fontSize:10,color:i%2===0?"#06b6d4":"var(--color-text-tertiary)",marginBottom:1,lineHeight:1.7 }}>{line}</div>
      ))}
      <div style={{ marginTop:8,padding:"6px 10px",borderRadius:6,background:"rgba(16,185,129,0.08)",border:"1px solid rgba(16,185,129,0.15)",fontSize:10,color:"#10b981" }}>✓ Authorization: Bearer ••••••••</div>
    </div>
  );
  if (stepId === "finish") return (
    <div style={{ ...s, background:`${color}0d`,border:`1px solid ${color}30`,padding:"16px 18px",textAlign:"center" }}>
      <div style={{ fontSize:42,marginBottom:8,animation:"pulse 1.5s ease-in-out infinite" }}>🏆</div>
      <div style={{ fontSize:13,fontWeight:700,color:"var(--color-text-primary)",marginBottom:6 }}>You earned 100 XP!</div>
      <div style={{ display:"flex",gap:6,flexWrap:"wrap",justifyContent:"center" }}>
        {["Dashboard","Tasks","Compliance","Knowledge","Ownership","Reports","API"].map((l,i)=>(
          <div key={l} style={{ padding:"3px 10px",borderRadius:999,fontSize:10,fontWeight:600,background:"rgba(255,255,255,0.06)",border:"1px solid rgba(255,255,255,0.12)",color:"var(--color-text-secondary)",animation:`fadeUp 0.3s ${i*0.06}s ease both` }}>✓ {l}</div>
        ))}
      </div>
    </div>
  );
  return null;
}

// -- Main Tour Overlay — with optional skip -----------------------------------
function TourOverlay({ onComplete, onSkip }) {
  const [step, setStep]             = useState(0);
  const [xp, setXp]                 = useState(0);
  const [exiting, setExiting]       = useState(false);
  const [typing, setTyping]         = useState(true);
  const [shownChars, setShownChars] = useState(0);
  const [showConfetti, setShowConfetti] = useState(false);
  const [btnHover, setBtnHover]     = useState(false);
  const [showSkipNotice, setShowSkipNotice] = useState(false);

  const skipIntro = () => {
    localStorage.setItem("aw_tour_done", "1");
    setShowSkipNotice(true);
  };

  const dismissSkipNotice = () => {
    setExiting(true);
    setTimeout(() => onSkip(), 450);
  };

  const current = TOUR_STEPS[step];
  const isFirst = step === 0;
  const isLast  = step === TOUR_STEPS.length - 1;
  const progress = ((step) / (TOUR_STEPS.length - 1)) * 100;

  // Typewriter effect — faster on later steps so users don't get impatient
  useEffect(() => {
    setTyping(true);
    setShownChars(0);
    const text = current.description;
    let i = 0;
    const speed = isFirst ? 22 : 14;
    const interval = setInterval(() => {
      i++;
      setShownChars(i);
      if (i >= text.length) { clearInterval(interval); setTyping(false); }
    }, speed);
    return () => clearInterval(interval);
  }, [step]);

  const advance = () => {
    if (typing) { setShownChars(current.description.length); setTyping(false); return; }
    if (isLast) { finish(); return; }
    setXp(current.xp);
    setStep(s => s + 1);
  };

  const finish = () => {
    setShowConfetti(true);
    setTimeout(() => {
      setExiting(true);
      localStorage.setItem("aw_tour_done", "1");
      setTimeout(() => onComplete(), 500);
    }, 900);
  };

  // Keyboard shortcut: Space / Enter to advance
  useEffect(() => {
    const handler = (e) => {
      if (e.code === "Space" || e.code === "Enter") { e.preventDefault(); advance(); }
      if (e.code === "ArrowLeft" && !isFirst && !isLast && step > 1) setStep(s => s - 1);
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [step, typing, isFirst, isLast]);

  return (
    <div style={{
      position: "fixed", inset: 0, zIndex: 9999,
      background: "rgba(4,5,12,0.96)", backdropFilter: "blur(16px)",
      display: "flex", alignItems: "center", justifyContent: "center", padding: "20px",
      opacity: exiting ? 0 : 1, transition: "opacity 0.45s ease",
    }}>
      {showConfetti && <ConfettiBurst />}

      {/* ── Skip Intro Notice Modal ── */}
      {showSkipNotice && (
        <div style={{
          position: "absolute", inset: 0, zIndex: 10001,
          background: "rgba(4,5,12,0.92)", backdropFilter: "blur(12px)",
          display: "flex", alignItems: "center", justifyContent: "center", padding: "20px",
        }}>
          <div style={{
            width: "100%", maxWidth: 500,
            background: "linear-gradient(160deg,#111526 0%,#0c0f1e 60%,#080a16 100%)",
            border: "1px solid rgba(79,142,247,0.35)", borderRadius: 24,
            padding: "36px 32px", boxShadow: "0 40px 100px rgba(0,0,0,0.8), 0 0 60px rgba(79,142,247,0.08)",
            textAlign: "center", animation: "fadeUp 0.4s cubic-bezier(0.16,1,0.3,1) both",
          }}>
            {/* Icon */}
            <div style={{
              width: 72, height: 72, borderRadius: 20, margin: "0 auto 20px",
              background: "rgba(79,142,247,0.12)", border: "1.5px solid rgba(79,142,247,0.35)",
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 32, boxShadow: "0 0 32px rgba(79,142,247,0.2)",
            }}>📚</div>

            {/* Heading */}
            <div style={{
              fontSize: 22, fontWeight: 800, letterSpacing: "-0.03em", marginBottom: 10,
              fontFamily: "var(--font-display)",
              background: "linear-gradient(135deg, #f0f2ff 0%, #a5b4fc 100%)",
              WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent", backgroundClip: "text",
            }}>Intro skipped — you're all set!</div>

            {/* Body */}
            <div style={{
              fontSize: 14, color: "var(--color-text-secondary)", lineHeight: 1.75, marginBottom: 24,
            }}>
              No worries — everything you need is in the{" "}
              <span style={{ color: "#a5b4fc", fontWeight: 700 }}>Knowledge Panel</span>.{" "}
              You can find it in the sidebar anytime. It contains all the info about how the software works, and you can also{" "}
              <span style={{ color: "#a5b4fc", fontWeight: 600 }}>add notes for your team</span>{" "}
              so everyone stays on the same page.
            </div>

            {/* Feature bullets */}
            <div style={{
              background: "rgba(79,142,247,0.06)", border: "1px solid rgba(79,142,247,0.18)",
              borderRadius: 14, padding: "16px 20px", marginBottom: 28, textAlign: "left",
            }}>
              {[
                ["📖", "Full software documentation & feature guides"],
                ["📝", "Add & manage notes for your team"],
                ["🔍", "Searchable — find any info instantly"],
              ].map(([icon, text]) => (
                <div key={text} style={{
                  display: "flex", alignItems: "center", gap: 12,
                  fontSize: 13, color: "var(--color-text-secondary)", padding: "6px 0",
                }}>
                  <span style={{ fontSize: 16, flexShrink: 0 }}>{icon}</span>
                  <span>{text}</span>
                </div>
              ))}
            </div>

            {/* CTA */}
            <button
              onClick={dismissSkipNotice}
              style={{
                width: "100%", height: 50, borderRadius: 13, border: "none",
                background: "linear-gradient(135deg, #4f8ef7 0%, #7b5cf0 100%)",
                color: "#fff", fontFamily: "var(--font-sans)", fontSize: 15, fontWeight: 700,
                cursor: "pointer", letterSpacing: "-0.01em",
                boxShadow: "0 0 28px rgba(79,142,247,0.4), 0 8px 20px rgba(0,0,0,0.3)",
                transition: "opacity 0.15s",
              }}
              onMouseEnter={e => e.currentTarget.style.opacity = "0.88"}
              onMouseLeave={e => e.currentTarget.style.opacity = "1"}
            >
              Go to Dashboard →
            </button>
          </div>
        </div>
      )}

      {/* Dynamic ambient glow — large, shifts color with step */}
      <div style={{
        position: "absolute", width: 900, height: 900, borderRadius: "50%",
        background: `radial-gradient(circle,${current.color}14 0%,transparent 65%)`,
        top: "50%", left: "50%", transform: "translate(-50%,-50%)",
        pointerEvents: "none", transition: "background 0.6s ease",
      }} />
      {/* Secondary smaller orb — offset for depth */}
      <div style={{
        position: "absolute", width: 400, height: 400, borderRadius: "50%",
        background: `radial-gradient(circle,${current.color}0e 0%,transparent 70%)`,
        top: "20%", left: "65%", pointerEvents: "none", transition: "background 0.6s ease",
      }} />

      {/* -- Keyboard hint + Skip Intro (top right) -- */}
      <div style={{
        position: "absolute", top: 20, right: 24,
        display: "flex", alignItems: "center", gap: 14,
      }}>
        <div style={{
          fontSize: 11, color: "var(--color-text-muted)",
          display: "flex", alignItems: "center", gap: 6, fontFamily: "var(--font-mono)",
        }}>
          <kbd style={{ padding:"2px 7px",borderRadius:5,background:"rgba(255,255,255,0.06)",border:"1px solid rgba(255,255,255,0.1)",fontSize:10 }}>Space</kbd>
          <span>to advance</span>
        </div>
        <button
          onClick={skipIntro}
          style={{
            height: 30, padding: "0 14px", borderRadius: 8,
            border: "1px solid rgba(255,255,255,0.12)",
            background: "rgba(255,255,255,0.04)",
            color: "var(--color-text-muted)",
            fontFamily: "var(--font-sans)", fontSize: 12, fontWeight: 500,
            cursor: "pointer", transition: "all 0.14s",
            display: "flex", alignItems: "center", gap: 5,
          }}
          onMouseEnter={e => { e.currentTarget.style.background = "rgba(255,255,255,0.09)"; e.currentTarget.style.color = "var(--color-text-secondary)"; }}
          onMouseLeave={e => { e.currentTarget.style.background = "rgba(255,255,255,0.04)"; e.currentTarget.style.color = "var(--color-text-muted)"; }}
        >
          <span style={{ fontSize: 13 }}>⏭</span> Skip Intro
        </button>
      </div>

      {/* -- Step counter (top left) -- */}
      <div style={{
        position: "absolute", top: 20, left: 24,
        fontSize: 11, color: "var(--color-text-muted)", fontFamily: "var(--font-mono)",
        display: "flex", alignItems: "center", gap: 8,
      }}>
        <div style={{ width: 8, height: 8, borderRadius: "50%", background: current.color, boxShadow: `0 0 10px ${current.color}` }} />
        Step {step + 1} of {TOUR_STEPS.length}
      </div>

      {/* -- Main card -- */}
      <div className="tour-card" style={{
        width: "100%", maxWidth: 620,
        background: "linear-gradient(160deg,#111526 0%,#0c0f1e 50%,#080a16 100%)",
        border: `1px solid ${current.color}30`, borderRadius: 26,
        boxShadow: `0 50px 140px rgba(0,0,0,0.85),0 0 0 1px ${current.color}18,0 0 80px ${current.color}08`,
        overflow: "hidden", position: "relative",
        transition: "border-color 0.5s ease,box-shadow 0.5s ease",
      }}>
        <TourParticles color={current.color} />

        {/* Top progress bar — continuous fill */}
        <div style={{ height: 3, background: "rgba(255,255,255,0.05)", position: "relative" }}>
          <div style={{
            height: "100%", background: current.gradient,
            width: `${progress}%`, transition: "width 0.5s cubic-bezier(0.34,1.56,0.64,1),background 0.4s",
            borderRadius: "0 999px 999px 0",
            boxShadow: `0 0 10px ${current.color}60`,
          }} />
        </div>

        {/* Header row */}
        <div style={{ padding: "16px 26px 0", display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          {/* XP pill */}
          <div style={{
            padding: "4px 12px", borderRadius: 999, fontSize: 12, fontWeight: 700,
            background: `${current.color}18`, color: current.color,
            border: `1px solid ${current.color}38`, fontFamily: "var(--font-display)",
            transition: "all 0.35s", display: "flex", alignItems: "center", gap: 5,
          }}>
            <span>⚡</span>
            <span style={{ fontVariantNumeric: "tabular-nums" }}>{xp} XP</span>
          </div>
          {/* Step dots */}
          <div style={{ display: "flex", gap: 5, alignItems: "center" }}>
            {TOUR_STEPS.map((s2, i) => (
              <div key={i} style={{
                width: i === step ? 22 : 6, height: 6, borderRadius: 999,
                background: i < step ? current.color : i === step ? current.color : "rgba(255,255,255,0.1)",
                opacity: i > step ? 0.35 : 1,
                transition: "width 0.4s cubic-bezier(0.34,1.56,0.64,1),background 0.3s,opacity 0.3s",
                boxShadow: i === step ? `0 0 8px ${current.color}80` : "none",
              }} />
            ))}
          </div>
        </div>

        {/* Step content */}
        <div className="tour-step-slide" key={step} style={{ padding: "22px 26px 26px" }}>
          {/* Icon + subtitle row */}
          <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 18 }}>
            <div style={{
              width: 64, height: 64, borderRadius: 18, flexShrink: 0,
              background: `${current.color}15`, border: `1.5px solid ${current.color}38`,
              display: "flex", alignItems: "center", justifyContent: "center", fontSize: 28,
              boxShadow: `0 0 28px ${current.color}22,inset 0 1px 0 rgba(255,255,255,0.08)`,
              transition: "all 0.35s ease",
            }}>{current.emoji}</div>
            <div>
              <div style={{
                display: "inline-flex", alignItems: "center", padding: "3px 11px",
                borderRadius: 999, marginBottom: 6,
                background: `${current.color}12`, border: `1px solid ${current.color}28`,
                fontSize: 10, fontWeight: 700, color: current.color,
                letterSpacing: "0.06em", textTransform: "uppercase",
              }}>{current.subtitle}</div>
              <div style={{
                fontSize: 22, fontWeight: 800, color: "var(--color-text-primary)",
                fontFamily: "var(--font-display)", letterSpacing: "-0.03em", lineHeight: 1.2,
              }}>{current.title}</div>
            </div>
          </div>

          {/* Typewriter description */}
          <div style={{
            fontSize: 14, color: "var(--color-text-secondary)", lineHeight: 1.75,
            minHeight: 56, marginBottom: 16,
          }}>
            {current.description.slice(0, shownChars)}
            {typing && <span style={{ opacity: 0.7, animation: "pulse 0.55s ease-in-out infinite" }}>|</span>}
          </div>

          {/* Feature visual — mini preview of the section */}
          {!typing && (
            <div style={{ marginBottom: 18, animation: "fadeUp 0.35s 0.05s ease both" }}>
              <StepVisual stepId={current.id} color={current.color} />
            </div>
          )}

          {/* Tip box — shown after typing */}
          {current.tip && !typing && !current.isBadgeStep && (
            <div style={{
              padding: "11px 15px", borderRadius: 11, marginBottom: 18,
              background: `${current.color}0a`, border: `1px solid ${current.color}22`,
              fontSize: 12.5, color: "var(--color-text-secondary)", lineHeight: 1.65,
              animation: "fadeUp 0.3s 0.12s ease both", display: "flex", gap: 9, alignItems: "flex-start",
            }}>
              <span style={{ fontSize: 14, flexShrink: 0, marginTop: 1 }}>💡</span>
              <span>{current.tip.replace("💡 Pro tip: ","").replace("💡 ","")}</span>
            </div>
          )}

          {/* CTA button */}
          <button
            onClick={advance}
            onMouseEnter={() => setBtnHover(true)}
            onMouseLeave={() => setBtnHover(false)}
            style={{
              width: "100%", height: 52, borderRadius: 14, border: "none",
              background: current.gradient, color: "#fff",
              fontFamily: "var(--font-sans)", fontSize: 15, fontWeight: 700,
              cursor: "pointer", display: "flex", alignItems: "center", justifyContent: "center", gap: 9,
              boxShadow: `0 0 32px ${current.color}40,0 8px 24px rgba(0,0,0,0.3),inset 0 1px 0 rgba(255,255,255,0.22)`,
              transform: btnHover ? "translateY(-2px) scale(1.01)" : "translateY(0) scale(1)",
              transition: "transform 0.18s cubic-bezier(0.34,1.56,0.64,1),box-shadow 0.18s",
              letterSpacing: "-0.01em",
            }}
          >
            {typing
              ? <><span style={{ fontSize: 17 }}>⏭</span> Skip typing</>
              : isLast
                ? <><span style={{ fontSize: 19 }}>🚀</span> Launch Dashboard &mdash; Let's Go!</>
                : isFirst
                  ? <><span style={{ fontSize: 17 }}>▶</span> Start Tour &nbsp;<span style={{ opacity: 0.75, fontSize: 13 }}>+{TOUR_STEPS[1].xp} XP</span></>
                  : <><span style={{ fontSize: 14, opacity: 0.85 }}>Continue</span> &nbsp;→&nbsp; <span style={{ opacity: 0.7, fontSize: 13 }}>+{Math.max(0,(TOUR_STEPS[step + 1]?.xp ?? current.xp) - current.xp)} XP</span></>
            }
          </button>

          {/* Back + "why no skip" row */}
          {!isFirst && !isLast && (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 12 }}>
              <button onClick={() => setStep(s => s - 1)} style={{
                height: 34, padding: "0 14px", borderRadius: 9,
                border: "1px solid var(--border-glass)", background: "rgba(255,255,255,0.03)",
                color: "var(--color-text-tertiary)", fontFamily: "var(--font-sans)",
                fontSize: 12, fontWeight: 500, cursor: "pointer", transition: "all 0.12s",
              }}
                onMouseEnter={e => { e.currentTarget.style.background = "rgba(255,255,255,0.07)"; e.currentTarget.style.color = "var(--color-text-secondary)"; }}
                onMouseLeave={e => { e.currentTarget.style.background = "rgba(255,255,255,0.03)"; e.currentTarget.style.color = "var(--color-text-tertiary)"; }}
              >← Back</button>
              <div style={{ fontSize: 11, color: "var(--color-text-muted)", display: "flex", alignItems: "center", gap: 5 }}>
                <span style={{ fontSize: 12 }}>🔒</span>
                <span>Complete the tour to unlock the dashboard</span>
              </div>
            </div>
          )}
          {isFirst && !typing && (
            <div style={{ marginTop: 10, textAlign: "center", fontSize: 11, color: "var(--color-text-muted)" }}>
              ✦ Takes ~2 minutes &nbsp;·&nbsp; Earn 100 XP &nbsp;·&nbsp; Learn every feature
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// -- Full-screen loading spinner (shown while auth state initialises) -----------
function AppLoader() {
  return (
    <div style={{
      minHeight: "100vh", background: "var(--bg-base)",
      display: "flex", alignItems: "center", justifyContent: "center",
      flexDirection: "column", gap: 24, position: "relative", overflow: "hidden",
    }}>
      {/* Ambient glow */}
      <div style={{ position: "absolute", width: 500, height: 500, borderRadius: "50%", background: "radial-gradient(circle, rgba(59,130,246,0.08) 0%, transparent 70%)", top: "50%", left: "50%", transform: "translate(-50%,-50%)", pointerEvents: "none" }} />

      {/* Logo mark */}
      <div style={{ position: "relative" }}>
        <div style={{
          width: 56, height: 56, borderRadius: 16,
          background: "var(--grad-primary)",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 22, fontWeight: 800, color: "#fff",
          fontFamily: "var(--font-display)",
          boxShadow: "0 0 40px rgba(59,130,246,0.45), 0 0 80px rgba(139,92,246,0.2)",
          animation: "glow-pulse 2s ease-in-out infinite",
          letterSpacing: "-0.02em",
        }}>Ω</div>
      </div>

      {/* Brand name */}
      <div style={{ textAlign: "center" }}>
        <div style={{ fontFamily: "var(--font-display)", fontSize: 20, fontWeight: 700, color: "var(--color-text-primary)", letterSpacing: "-0.03em" }}>AI Workflow</div>
        <div style={{ fontSize: 12, color: "var(--color-text-tertiary)", marginTop: 3, letterSpacing: "0.1em", textTransform: "uppercase" }}>Coordinator</div>
      </div>

      {/* Loading bar */}
      <div style={{ width: 180, height: 2, background: "rgba(255,255,255,0.06)", borderRadius: 999, overflow: "hidden" }}>
        <div style={{ height: "100%", background: "var(--grad-primary)", borderRadius: 999, animation: "shimmer 1.5s ease-in-out infinite", backgroundSize: "200% 100%" }} />
      </div>
    </div>
  );
}

// -- Columns / nav config (unchanged) -----------------------------------------
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

// -- Sidebar -------------------------------------------------------------------
const NAV_GROUPS = [
  {
    label: "Core",
    items: [
      { icon: "dashboard", label: "Dashboard",    idx: 0 },
      { icon: "tasks",     label: "Tasks",        idx: 1 },
      { icon: "reports",   label: "Reports",      idx: 4 },
    ]
  },
  {
    label: "Manage",
    items: [
      { icon: "comply",    label: "Compliance",   idx: 2, badge: true },
      { icon: "know",      label: "Knowledge",    idx: 3 },
      { icon: "owner",     label: "Ownership",    idx: 5 },
    ]
  },
  {
    label: "Connect",
    items: [
      { icon: "integrate", label: "Integrations", idx: 6 },
      { icon: "locale",    label: "Locale",       idx: 7 },
      { icon: "teams",     label: "Teams",        idx: 8 },
      { icon: "api",       label: "API",          idx: 9 },
    ]
  },
  {
    label: "Account",
    items: [
      { icon: "settings",  label: "Settings",     idx: 10 },
    ]
  },
];

const NAV_ICONS = {
  dashboard: (
    <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><rect x="1" y="1" width="5.5" height="5.5" rx="1.5" fill="currentColor" opacity="0.9"/><rect x="8.5" y="1" width="5.5" height="5.5" rx="1.5" fill="currentColor" opacity="0.5"/><rect x="1" y="8.5" width="5.5" height="5.5" rx="1.5" fill="currentColor" opacity="0.5"/><rect x="8.5" y="8.5" width="5.5" height="5.5" rx="1.5" fill="currentColor" opacity="0.9"/></svg>
  ),
  tasks: (
    <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M2 3.5h11M2 7.5h8M2 11.5h5" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/><circle cx="12.5" cy="11.5" r="1.5" fill="currentColor" opacity="0.7"/></svg>
  ),
  reports: (
    <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M1.5 13.5V9M5.5 13.5V5.5M9.5 13.5V7.5M13.5 13.5V2" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round"/></svg>
  ),
  comply: (
    <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M7.5 1.5L13 4v4c0 2.8-2.5 5-5.5 5.5C4.5 13 2 10.8 2 8V4L7.5 1.5z" stroke="currentColor" strokeWidth="1.4" strokeLinejoin="round"/><path d="M5 7.5l1.5 1.5L10 6" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/></svg>
  ),
  know: (
    <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M3 2.5h9a1 1 0 011 1v9a1 1 0 01-1 1H3a1 1 0 01-1-1v-9a1 1 0 011-1z" stroke="currentColor" strokeWidth="1.4"/><path d="M5 6h5M5 8.5h3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/></svg>
  ),
  owner: (
    <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><circle cx="7.5" cy="5" r="2.5" stroke="currentColor" strokeWidth="1.4"/><circle cx="2.5" cy="11" r="1.5" stroke="currentColor" strokeWidth="1.3" opacity="0.7"/><circle cx="12.5" cy="11" r="1.5" stroke="currentColor" strokeWidth="1.3" opacity="0.7"/><path d="M4 11C4 9.5 5.5 8 7.5 8s3.5 1.5 3.5 3" stroke="currentColor" strokeWidth="1.3" opacity="0.7" strokeLinecap="round"/><path d="M1 13c0-1 .7-2 1.5-2M14 13c0-1-.7-2-1.5-2" stroke="currentColor" strokeWidth="1.3" opacity="0.5" strokeLinecap="round"/></svg>
  ),
  integrate: (
    <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><path d="M5.5 4L2 7.5l3.5 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/><path d="M9.5 4L13 7.5l-3.5 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/><path d="M6.5 11.5l2-8" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" opacity="0.6"/></svg>
  ),
  locale: (
    <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><circle cx="7.5" cy="7.5" r="5.5" stroke="currentColor" strokeWidth="1.4"/><path d="M7.5 2c-1.5 1.5-2.5 3.5-2.5 5.5s1 4 2.5 5.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/><path d="M7.5 2c1.5 1.5 2.5 3.5 2.5 5.5s-1 4-2.5 5.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round"/><path d="M2 7.5h11" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" opacity="0.7"/></svg>
  ),
  teams: (
    <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><circle cx="5" cy="5.5" r="2" stroke="currentColor" strokeWidth="1.4"/><circle cx="10.5" cy="5.5" r="2" stroke="currentColor" strokeWidth="1.4" opacity="0.7"/><path d="M1.5 13c0-1.7 1.6-3 3.5-3s3.5 1.3 3.5 3" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round"/><path d="M10.5 10.5c1.6.3 3 1.5 3 2.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" opacity="0.6"/></svg>
  ),
  api: (
    <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><rect x="1.5" y="3.5" width="12" height="8" rx="1.5" stroke="currentColor" strokeWidth="1.4"/><path d="M4.5 7.5l1.5-1.5L4.5 4.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" strokeLinejoin="round" opacity="0.8"/><path d="M8 8h2.5" stroke="currentColor" strokeWidth="1.3" strokeLinecap="round" opacity="0.8"/></svg>
  ),
  settings: (
    <svg width="15" height="15" viewBox="0 0 15 15" fill="none"><circle cx="7.5" cy="7.5" r="2" stroke="currentColor" strokeWidth="1.4"/><path d="M7.5 1.5v1M7.5 12.5v1M1.5 7.5h1M12.5 7.5h1M3.4 3.4l.7.7M10.9 10.9l.7.7M3.4 11.6l.7-.7M10.9 4.1l.7-.7" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" opacity="0.7"/></svg>
  ),
};

function Sidebar({ activeNav, onNavChange, navBadges = {} }) {
  const { user, logout } = useAuth();
  const [collapsed, setCollapsed] = useState(false);

  const initials = user?.name
    ? user.name.split(" ").map(w => w[0]).join("").toUpperCase().slice(0, 2)
    : "AW";

  const roleLabel = { architect: "Architect", navigator: "Navigator", operator: "Operator", solo: "Solo" }[user?.role] || "Member";
  const roleColor = { architect: "#f59e0b", navigator: "#3b82f6", operator: "#10b981", solo: "#8b5cf6" }[user?.role] || "#8892b0";

  const winW = useWindowWidth();
  // Auto-collapse sidebar on narrow screens
  const effectiveCollapsed = collapsed || winW < 900;
  const sidebarW = effectiveCollapsed ? 64 : 228;

  return (
    <aside style={{
      position: "fixed", left: 0, top: 0, bottom: 0,
      width: sidebarW,
      background: "var(--bg-sidebar)",
      borderRight: "1px solid var(--border-glass)",
      display: "flex", flexDirection: "column", zIndex: 50,
      overflow: "hidden", transition: "width 0.25s cubic-bezier(0.4,0,0.2,1)",
    }}>
      {/* Subtle ambient gradient */}
      <div style={{ position: "absolute", inset: 0, background: "linear-gradient(160deg, rgba(59,130,246,0.04) 0%, transparent 40%, rgba(139,92,246,0.03) 100%)", pointerEvents: "none" }} />

      {/* Top accent line */}
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: "var(--grad-primary)", opacity: 0.5 }} />

      {/* Logo */}
      <div style={{ padding: effectiveCollapsed ? "20px 14px" : "20px 18px", display: "flex", alignItems: "center", gap: 10, borderBottom: "1px solid var(--border-glass)", position: "relative", flexShrink: 0 }}>
        <div style={{
          width: 34, height: 34, borderRadius: 10, flexShrink: 0,
          background: "var(--grad-primary)",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontFamily: "var(--font-display)", fontSize: 16, fontWeight: 800, color: "#fff",
          boxShadow: "0 0 20px rgba(59,130,246,0.4)",
          letterSpacing: "-0.02em",
        }}>Ω</div>

        {!effectiveCollapsed && (
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontFamily: "var(--font-display)", fontSize: 14, fontWeight: 700, color: "var(--color-text-primary)", letterSpacing: "-0.02em", lineHeight: 1.2 }}>AI Workflow</div>
            <div style={{ fontSize: 10, color: "var(--color-text-tertiary)", marginTop: 1, letterSpacing: "0.08em", textTransform: "uppercase" }}>Coordinator</div>
          </div>
        )}

        {/* Collapse toggle */}
        <button onClick={() => setCollapsed(c => !c)} style={{
          width: 22, height: 22, borderRadius: 6, border: "1px solid var(--border-glass)",
          background: "rgba(255,255,255,0.04)", cursor: "pointer", color: "var(--color-text-tertiary)",
          display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0,
          transition: "all 0.15s",
        }}
          onMouseEnter={e => { e.currentTarget.style.background = "rgba(255,255,255,0.09)"; e.currentTarget.style.color = "var(--color-text-primary)"; }}
          onMouseLeave={e => { e.currentTarget.style.background = "rgba(255,255,255,0.04)"; e.currentTarget.style.color = "var(--color-text-tertiary)"; }}
          title={effectiveCollapsed ? "Expand sidebar" : "Collapse sidebar"}
        >
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
            <path d={collapsed ? "M3 2l4 3-4 3" : "M7 2L3 5l4 3"} stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
        </button>
      </div>

      {/* Nav groups */}
      <nav style={{ flex: 1, overflowY: "auto", overflowX: "hidden", padding: effectiveCollapsed ? "10px 8px" : "10px 10px", display: "flex", flexDirection: "column", gap: 0 }}>
        {NAV_GROUPS.map(group => (
          <div key={group.label} style={{ marginBottom: 4 }}>
            {!effectiveCollapsed && (
              <div style={{ fontSize: 9.5, fontWeight: 600, letterSpacing: "0.1em", textTransform: "uppercase", color: "var(--color-text-muted)", padding: "10px 8px 5px", fontFamily: "var(--font-display)" }}>
                {group.label}
              </div>
            )}
            {collapsed && <div style={{ height: 8 }} />}

            {group.items.map(item => {
              const isActive = activeNav === item.idx;
              // Dynamic badge: live count from navBadges, fallback to static NAV_ITEMS badge
              const dynamicBadge = navBadges[item.idx];
              const staticBadge  = item.badge ? NAV_ITEMS[item.idx]?.badge : null;
              const badgeValue   = dynamicBadge ?? staticBadge ?? null;
              // Badge color: compliance/issues = red, tasks/dashboard = blue, others = purple
              const badgeColor   =
                item.idx === 2 ? "var(--grad-danger)"   :  // Compliance — red (issues)
                item.idx === 1 ? "linear-gradient(135deg,#3b82f6,#06b6d4)" :  // Tasks — blue
                item.idx === 0 ? "linear-gradient(135deg,#f59e0b,#f97316)" :  // Dashboard — amber (active)
                item.idx === 4 ? "linear-gradient(135deg,#10b981,#06b6d4)" :  // Reports — green (completed)
                item.idx === 5 ? "linear-gradient(135deg,#8b5cf6,#3b82f6)" :  // Ownership — violet
                "var(--grad-danger)";
              return (
                <div key={item.label}
                  role="button" tabIndex={0} title={collapsed ? item.label : undefined}
                  aria-current={isActive ? "page" : undefined}
                  onClick={() => onNavChange(item.idx)}
                  onKeyDown={e => e.key === "Enter" && onNavChange(item.idx)}
                  style={{
                    display: "flex", alignItems: "center", gap: effectiveCollapsed ? 0 : 10,
                    padding: collapsed ? "9px" : "8px 10px",
                    borderRadius: 10, cursor: "pointer",
                    justifyContent: collapsed ? "center" : "flex-start",
                    position: "relative", marginBottom: 1,
                    color: isActive ? "#fff" : "var(--color-text-secondary)",
                    background: isActive
                      ? "linear-gradient(135deg, rgba(59,130,246,0.22) 0%, rgba(139,92,246,0.18) 100%)"
                      : "transparent",
                    border: isActive ? "1px solid rgba(59,130,246,0.3)" : "1px solid transparent",
                    transition: "all 0.15s cubic-bezier(0.4,0,0.2,1)",
                  }}
                  onMouseEnter={e => {
                    if (!isActive) {
                      e.currentTarget.style.background = "rgba(255,255,255,0.05)";
                      e.currentTarget.style.color = "var(--color-text-primary)";
                      e.currentTarget.style.borderColor = "rgba(255,255,255,0.06)";
                    }
                  }}
                  onMouseLeave={e => {
                    if (!isActive) {
                      e.currentTarget.style.background = "transparent";
                      e.currentTarget.style.color = "var(--color-text-secondary)";
                      e.currentTarget.style.borderColor = "transparent";
                    }
                  }}
                >
                  {/* Active left bar */}
                  {isActive && <div style={{ position: "absolute", left: -10, top: "50%", transform: "translateY(-50%)", width: 3, height: "60%", borderRadius: "0 3px 3px 0", background: "var(--grad-primary)", boxShadow: "0 0 8px rgba(59,130,246,0.6)" }} />}

                  <span style={{ color: isActive ? "#3b82f6" : "inherit", transition: "color 0.15s", flexShrink: 0 }}>
                    {NAV_ICONS[item.icon]}
                  </span>

                  {!effectiveCollapsed && (
                    <span style={{ flex: 1, fontSize: 13, fontWeight: isActive ? 600 : 400, letterSpacing: "-0.01em", whiteSpace: "nowrap" }}>
                      {item.label}
                    </span>
                  )}

                  {!effectiveCollapsed && badgeValue !== null && (
                    <span style={{
                      minWidth: 20, height: 18, padding: "0 5px", borderRadius: 999,
                      fontSize: 10, fontWeight: 700, color: "#fff",
                      background: badgeColor,
                      display: "flex", alignItems: "center", justifyContent: "center",
                      transition: "all 0.2s cubic-bezier(0.34,1.56,0.64,1)",
                      boxShadow: "0 2px 6px rgba(0,0,0,0.3)",
                    }}>{badgeValue}</span>
                  )}
                  {collapsed && badgeValue !== null && (
                    <div style={{ position: "absolute", top: 4, right: 4, minWidth: 14, height: 14, borderRadius: 999, background: badgeColor, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 8, fontWeight: 700, color: "#fff", padding: "0 3px" }}>
                      {badgeValue > 99 ? "99+" : badgeValue}
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        ))}
      </nav>

      {/* User footer */}
      <div style={{ padding: collapsed ? "12px 8px" : "12px 10px", borderTop: "1px solid var(--border-glass)", flexShrink: 0 }}>
        <div style={{
          display: "flex", alignItems: "center", gap: effectiveCollapsed ? 0 : 10,
          padding: collapsed ? "8px" : "8px 10px",
          borderRadius: 10, background: "rgba(255,255,255,0.04)",
          border: "1px solid var(--border-glass)",
          justifyContent: collapsed ? "center" : "flex-start",
          position: "relative", overflow: "hidden",
        }}>
          {/* Avatar */}
          <div style={{
            width: 30, height: 30, borderRadius: 9, flexShrink: 0,
            background: `linear-gradient(135deg, ${roleColor}90, ${roleColor}50)`,
            border: `1px solid ${roleColor}40`,
            display: "flex", alignItems: "center", justifyContent: "center",
            fontFamily: "var(--font-display)", fontSize: 11, fontWeight: 700, color: "#fff",
          }}>{initials}</div>

          {!effectiveCollapsed && (
            <>
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 12, fontWeight: 600, color: "var(--color-text-primary)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", letterSpacing: "-0.01em" }}>
                  {user?.name || "User"}
                </div>
                <div style={{ fontSize: 10, color: roleColor, fontWeight: 500, letterSpacing: "0.02em" }}>{roleLabel}</div>
              </div>

              <button onClick={logout} title="Sign out" style={{
                background: "transparent", border: "none", cursor: "pointer",
                color: "var(--color-text-tertiary)", padding: "4px", borderRadius: 6,
                display: "flex", alignItems: "center", transition: "color 0.15s",
                flexShrink: 0,
              }}
                onMouseEnter={e => e.currentTarget.style.color = "var(--accent-rose)"}
                onMouseLeave={e => e.currentTarget.style.color = "var(--color-text-tertiary)"}
              >
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none"><path d="M9.5 4.5L12 7l-2.5 2.5M12 7H5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/><path d="M5 2H3a1 1 0 00-1 1v8a1 1 0 001 1h2" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/></svg>
              </button>
            </>
          )}
        </div>
      </div>
    </aside>
  );
}

// -- SVG icons (unchanged) -----------------------------------------------------
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

// -- Segment 10: Ownership Graph view -----------------------------------------
function OwnershipGraph() {
  const { user, token } = useAuth();
  const API = BASE_URL;
  const [data, setData]         = useState(null);
  const [loading, setLoading]   = useState(true);
  const [error, setError]       = useState(null);
  const [selected, setSelected] = useState(null); // selected assignee node
  const [filter, setFilter]     = useState("");

  useEffect(() => {
    if (!token) return;
    const params = new URLSearchParams();
    if (user?.workspace?.id) params.set("workspace_id", user.workspace.id);
    else if (user?.id)       params.set("owner_id", user.id);

    fetch(`${API}/tasks/graph?${params}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => { if (!r.ok) throw new Error("Failed to load graph"); return r.json(); })
      .then(d => { setData(d); setLoading(false); })
      .catch(e => { setError(e.message); setLoading(false); });
  }, [API, user, token]);

  const PRIORITY_COLOR = { critical: "#f87171", high: "#fb923c", medium: "#fbbf24", low: "#34d399" };
  const STATUS_COLOR   = { to_do: "#3b82f6", in_progress: "#f59e0b", completed: "#22d3a8", cancelled: "#6b7280" };

  const nodes = useMemo(() => {
    if (!data?.nodes) return [];
    return data.nodes.filter(n =>
      !filter || n.assignee.toLowerCase().includes(filter.toLowerCase())
    );
  }, [data, filter]);

  if (loading) return (
    <main style={{ flex: 1, display: "flex", alignItems: "center", justifyContent: "center", padding: 40 }}>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 12 }}>
        <div style={{ width: 24, height: 24, border: "2px solid rgba(79,142,247,0.2)", borderTopColor: "#3b82f6", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />
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
    <main className="page-enter" style={{ flex: 1, padding: "clamp(14px, 2.5vw, 28px) clamp(12px, 2.5vw, 28px) 40px", display: "flex", flexDirection: "column", gap: 24 }}>

      {/* Header */}
      <header style={{
        position: "sticky", top: 0, zIndex: 40, minHeight: 56,
        background: "rgba(13,15,30,0.88)", backdropFilter: "blur(16px)",
        borderBottom: "1px solid var(--border-glass)",
        padding: "10px clamp(12px, 2.5vw, 28px)", display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap",
        margin: "0 calc(-1 * clamp(12px, 2.5vw, 28px))",
      }}>
        <div>
          <div style={{ fontSize: 15, fontWeight: 700, color: "var(--color-text-primary)", letterSpacing: "-0.02em", fontFamily: "var(--font-display)" }}>Ownership Graph</div>
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
              background: "rgba(255,255,255,0.05)", border: "1px solid var(--border-glass)",
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
          { label: "Total Tasks",   value: data?.total_tasks,  color: "#3b82f6" },
          { label: "Owners",        value: data?.total_owners, color: "#8b5cf6" },
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
                className={`owner-card${isSelected ? " selected" : ""}`}
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
                  <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 6 }}>
                    <span style={{ fontSize: 11, color: "var(--color-text-tertiary)" }}>Completion</span>
                    <span style={{ fontSize: 11, fontWeight: 700, color: "#22d3a8" }}>{completionPct}%</span>
                  </div>
                  <div className="progress-track">
                    <div className="progress-fill" style={{ width: `${completionPct}%`, background: "linear-gradient(90deg,#22d3a8,#06b6d4)", boxShadow: "0 0 8px rgba(34,211,168,0.4)" }} />
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
                          📅 {formatDeadline(task.deadline, user?.timezone)}
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

// -- Tasks Page ----------------------------------------------------------------
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
  const STATUS_COLOR   = { to_do: "#3b82f6", in_progress: "#a78bfa", completed: "#22d3a8", cancelled: "#6b7280" };
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
      <header style={{ position:"sticky", top:0, zIndex:40, minHeight:56, background:"rgba(13,15,30,0.88)", backdropFilter:"blur(16px)", WebkitBackdropFilter:"blur(16px)", borderBottom:"1px solid var(--border-glass)", padding:"10px clamp(12px,2.5vw,28px)", display:"flex", alignItems:"center", gap:10, flexWrap:"wrap" }}>
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

        <button onClick={openCreate} style={{ height:36, padding:"0 18px", borderRadius:999, border:"none", background:"var(--grad-primary)", color:"#fff", fontFamily:"var(--font-sans)", fontSize:13, fontWeight:600, cursor:"pointer", whiteSpace:"nowrap", boxShadow:"0 0 20px rgba(79,142,247,0.35)", marginLeft:"auto" }}>
          + New Task
        </button>
      </header>

      <main style={{ flex:1, padding:"clamp(14px, 2vw, 24px) clamp(12px, 2.5vw, 28px) 40px" }}>
        {/* Flash messages */}
        {successMsg && (
          <div styl