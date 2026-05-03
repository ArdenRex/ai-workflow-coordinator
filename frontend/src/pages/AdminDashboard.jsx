import React, { useState, useEffect, useCallback, useRef, useContext } from "react";

const API = process.env.REACT_APP_API_URL || "https://ai-workflow-coordinator-api-production.up.railway.app";

// ── THEME CONTEXT ─────────────────────────────────────────────────────────────
const ThemeCtx = React.createContext({ dark: true });
function useTheme() { return React.useContext(ThemeCtx); }

// Light-mode CSS variable overrides injected as a class on <html>
const LIGHT_OVERRIDES = `
  .arcane-light {
    --bg-deep: #f0f4f8;
    --bg-mid:  #e2eaf3;
    --glass:   rgba(230,238,250,0.92);
    --border:  rgba(0,160,220,0.28);
    --cyan:    #0088cc;
    --green:   #009966;
    --purple:  #7730bb;
    --gold:    #b87a00;
    --red:     #cc2244;
  }
  .arcane-light body { background: #f0f4f8; }
  .arcane-light .space-bg {
    background:
      radial-gradient(ellipse 100% 70% at 8% 5%,   rgba(0,120,220,0.18) 0%, transparent 55%),
      radial-gradient(ellipse 70% 60% at 92% 92%,  rgba(0,80,180,0.14) 0%, transparent 55%),
      radial-gradient(ellipse 50% 40% at 55% 32%,  rgba(0,140,200,0.10) 0%, transparent 65%),
      #e8f2fa !important;
  }
  .arcane-light .aurora { opacity: 0.35; filter: saturate(0.7) brightness(1.4); }
  .arcane-light .grain  { opacity: 0.008; }
  .arcane-light .vignette { opacity: 0.15; }
  .arcane-light .scanlines { opacity: 0.4; background:
    repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,120,200,0.018) 2px, rgba(0,120,200,0.018) 3px) !important; }
  .arcane-light .sidebar {
    background: linear-gradient(180deg, rgba(220,235,250,0.97) 0%, rgba(208,228,248,0.95) 100%) !important;
    border-right: 1px solid rgba(0,120,200,0.25) !important;
  }
  .arcane-light .main-content { color: #0a1a2e; }
  .arcane-light .topbar {
    background: linear-gradient(180deg, rgba(235,244,255,0.99) 0%, rgba(220,235,250,0.97) 100%) !important;
    border-bottom: 1px solid rgba(0,120,200,0.2) !important;
  }
  .arcane-light ::-webkit-scrollbar-track { background: rgba(220,235,250,0.9); }
  .arcane-light ::-webkit-scrollbar-thumb { background: linear-gradient(180deg, #0088cc, #009966); }
  .arcane-light .holo-panel {
    background: rgba(220,238,255,0.88) !important;
    border-color: rgba(0,120,200,0.22) !important;
  }
  .arcane-light .stat-item {
    background: linear-gradient(160deg, rgba(225,240,255,0.99) 0%, rgba(210,232,252,0.96) 100%) !important;
    border-color: rgba(0,120,200,0.2) !important;
  }
  .arcane-light .holo-table-row:hover { background: rgba(0,120,200,0.06) !important; }
  .arcane-light .holo-feedback { background: rgba(220,238,255,0.9) !important; border-color: rgba(0,120,200,0.22) !important; }
`;

// ── ACTIVITY FEED DATA ────────────────────────────────────────────────────────
const ACTIVITY_ICONS = { signup: "⬡", upgrade: "◎", cancel: "✕", task: "✦", feedback: "◆", login: "→" };
const ACTIVITY_COLORS = { signup: "#00ff9d", upgrade: "#ffd060", cancel: "#ff2d55", task: "#00e5ff", feedback: "#bf5fff", login: "#00e5ff" };
function makeActivity(id) {
  const types = ["signup", "upgrade", "cancel", "task", "feedback", "login"];
  const t = types[Math.floor(Math.random() * types.length)];
  const names = ["nova_x", "cipher_7", "arc_user", "ghost_91", "data_77", "echo_k", "syn_44", "prism_2", "byte_z", "flux_9"];
  const name = names[Math.floor(Math.random() * names.length)];
  const msgs = {
    signup: `${name} joined the network`, upgrade: `${name} upgraded to Pro`,
    cancel: `${name} terminated subscription`, task: `${name} created 3 new tasks`,
    feedback: `${name} submitted a transmission`, login: `${name} accessed terminal`,
  };
  return { id, type: t, msg: msgs[t], ts: Date.now(), fresh: true };
}

// ── REAL-TIME ACTIVITY FEED ───────────────────────────────────────────────────
function ActivityFeed({ m }) {
  const [events, setEvents] = useState(() => Array.from({ length: 7 }, (_, i) => ({ ...makeActivity(i), fresh: false, ts: Date.now() - i * 14000 })));
  const idRef = useRef(100);
  const { dark } = useTheme();

  useEffect(() => {
    const interval = setInterval(() => {
      const ev = makeActivity(idRef.current++);
      setEvents(prev => [ev, ...prev.slice(0, 14)]);
      // After 1s remove 'fresh' glow
      setTimeout(() => setEvents(prev => prev.map(e => e.id === ev.id ? { ...e, fresh: false } : e)), 1200);
    }, 3800 + Math.random() * 2400);
    return () => clearInterval(interval);
  }, []);

  const timeAgo = (ts) => {
    const s = Math.floor((Date.now() - ts) / 1000);
    if (s < 5)  return "just now";
    if (s < 60) return `${s}s ago`;
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    return `${Math.floor(m / 60)}h ago`;
  };

  const cyan = dark ? "0,229,255" : "0,120,200";
  const panelBg = dark
    ? "linear-gradient(160deg, rgba(0,4,18,0.98) 0%, rgba(0,10,28,0.95) 100%)"
    : "linear-gradient(160deg, rgba(220,238,255,0.97) 0%, rgba(200,228,252,0.94) 100%)";
  const textPrimary = dark ? "rgba(180,230,255,0.85)" : "rgba(10,40,80,0.85)";
  const textDim = dark ? "rgba(0,229,255,0.3)" : "rgba(0,100,180,0.45)";

  return (
    <div style={{
      background: panelBg,
      border: `1px solid rgba(${cyan},0.2)`,
      borderRadius: 8, overflow: "hidden",
      clipPath: "polygon(0 0, calc(100% - 16px) 0, 100% 16px, 100% 100%, 0 100%)",
      boxShadow: dark
        ? `0 12px 50px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.05), inset 0 0 40px rgba(${cyan},0.02)`
        : `0 8px 30px rgba(0,80,180,0.1), inset 0 1px 0 rgba(255,255,255,0.6)`,
      transition: "all 0.5s",
    }}>
      {/* Header */}
      <div style={{
        display: "flex", alignItems: "center", justifyContent: "space-between",
        padding: "14px 18px 12px",
        borderBottom: `1px solid rgba(${cyan},0.1)`,
        background: dark ? `rgba(${cyan},0.03)` : `rgba(${cyan},0.06)`,
        position: "relative",
      }}>
        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, rgba(${cyan},0.6), rgba(0,255,157,0.3), transparent)` }} />
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#00ff9d", boxShadow: "0 0 10px #00ff9d", animation: "pulse-glow 1.2s ease-in-out infinite" }} />
          <span style={{ fontSize: 9, color: `rgba(${cyan},0.8)`, letterSpacing: "0.28em", textTransform: "uppercase", fontFamily: "'Share Tech Mono', monospace", fontWeight: 700 }}>Live Activity Feed</span>
        </div>
        <div style={{ fontSize: 7, color: `rgba(${cyan},0.35)`, letterSpacing: "0.12em", fontFamily: "'Share Tech Mono', monospace" }}>
          {events.length} EVENTS · AUTO-REFRESH
        </div>
      </div>

      {/* Event stream */}
      <div style={{ maxHeight: 320, overflowY: "auto", padding: "8px 0" }}>
        {events.map((ev, i) => {
          const col = ACTIVITY_COLORS[ev.type];
          const icon = ACTIVITY_ICONS[ev.type];
          return (
            <div key={ev.id} style={{
              display: "flex", alignItems: "center", gap: 12,
              padding: "9px 18px",
              borderLeft: ev.fresh ? `3px solid ${col}` : "3px solid transparent",
              background: ev.fresh
                ? dark ? `rgba(${col.replace("#","").match(/.{2}/g).map(h=>parseInt(h,16)).join(",")},0.08)` : `rgba(0,120,200,0.06)`
                : i % 2 === 0 ? (dark ? "rgba(0,229,255,0.012)" : "rgba(0,120,200,0.025)") : "transparent",
              transition: "all 0.6s cubic-bezier(0.16,1,0.3,1)",
              animation: i === 0 && ev.fresh ? "activitySlide 0.4s cubic-bezier(0.16,1,0.3,1) both" : "none",
              position: "relative",
              overflow: "hidden",
            }}>
              {ev.fresh && <div style={{ position: "absolute", inset: 0, background: `linear-gradient(90deg, rgba(${col.replace("#","").match(/.{2}/g)?.map(h=>parseInt(h,16)).join(",") || "0,229,255"},0.04), transparent)`, pointerEvents: "none" }} />}
              {/* Type icon bubble */}
              <div style={{
                width: 28, height: 28, borderRadius: "50%", flexShrink: 0,
                display: "flex", alignItems: "center", justifyContent: "center",
                background: dark ? `rgba(${col.replace("#","").match(/.{2}/g)?.map(h=>parseInt(h,16)).join(",") || "0,229,255"},0.1)` : `rgba(0,120,200,0.1)`,
                border: `1px solid ${ev.fresh ? col : `rgba(${col.replace("#","").match(/.{2}/g)?.map(h=>parseInt(h,16)).join(",") || "0,229,255"},0.3)`}`,
                boxShadow: ev.fresh ? `0 0 12px ${col}44` : "none",
                transition: "all 0.5s",
                fontSize: 11, color: ev.fresh ? col : (dark ? `rgba(${col.replace("#","").match(/.{2}/g)?.map(h=>parseInt(h,16)).join(",") || "0,229,255"},0.6)` : `rgba(0,100,160,0.7)`),
              }}>{icon}</div>
              {/* Message */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontSize: 10, color: ev.fresh ? textPrimary : (dark ? "rgba(150,210,255,0.6)" : "rgba(10,40,80,0.65)"), fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.04em", whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
                  {ev.msg}
                </div>
                <div style={{ fontSize: 7, color: textDim, marginTop: 2, letterSpacing: "0.1em" }}>{ev.type.toUpperCase()}</div>
              </div>
              {/* Time */}
              <div style={{ fontSize: 8, color: textDim, fontFamily: "'Share Tech Mono', monospace", flexShrink: 0 }}>{timeAgo(ev.ts)}</div>
              {/* Fresh pulse */}
              {ev.fresh && <div style={{ width: 5, height: 5, borderRadius: "50%", background: col, boxShadow: `0 0 8px ${col}`, animation: "pulse-glow 0.8s ease-in-out 3", flexShrink: 0 }} />}
            </div>
          );
        })}
      </div>
      {/* Footer strip */}
      <div style={{ padding: "8px 18px", borderTop: `1px solid rgba(${cyan},0.08)`, display: "flex", gap: 8, flexWrap: "wrap" }}>
        {Object.entries(ACTIVITY_COLORS).map(([type, col]) => {
          const count = events.filter(e => e.type === type).length;
          return (
            <div key={type} style={{ display: "flex", alignItems: "center", gap: 4, fontSize: 7, fontFamily: "'Share Tech Mono', monospace" }}>
              <div style={{ width: 4, height: 4, borderRadius: "50%", background: col }} />
              <span style={{ color: dark ? `rgba(180,230,255,0.35)` : "rgba(0,80,160,0.5)", letterSpacing: "0.08em" }}>{type.toUpperCase()}</span>
              <span style={{ color: col, fontWeight: 700 }}>{count}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── DATA EXPORT MODAL ─────────────────────────────────────────────────────────
function ExportModal({ open, onClose, m }) {
  const [phase, setPhase] = useState("idle"); // idle | selecting | exporting | done
  const [progress, setProgress] = useState(0);
  const [selectedSets, setSelectedSets] = useState({ users: true, revenue: true, tasks: false, feedback: false });
  const [exportFormat, setExportFormat] = useState("JSON");
  const { dark } = useTheme();

  const cyan = dark ? "0,229,255" : "0,120,200";
  const cyanHex = dark ? "#00e5ff" : "#0088cc";
  const green = dark ? "#00ff9d" : "#009966";

  useEffect(() => {
    if (!open) { setPhase("idle"); setProgress(0); }
    if (open) setPhase("selecting");
  }, [open]);

  const startExport = () => {
    setPhase("exporting");
    setProgress(0);
    let p = 0;
    const steps = [0, 12, 28, 41, 57, 72, 85, 94, 100];
    let i = 0;
    const tick = setInterval(() => {
      i++;
      if (i >= steps.length) { clearInterval(tick); setProgress(100); setTimeout(() => setPhase("done"), 400); return; }
      setProgress(steps[i]);
    }, 220 + Math.random() * 180);
  };

  if (!open) return null;

  const dataSets = [
    { key: "users", label: "User Registry", icon: "⬡", count: m?.users?.total, color: "#00e5ff", desc: "All user records, roles, subscription status" },
    { key: "revenue", label: "Revenue Ledger", icon: "◎", count: m?.revenue?.monthly_breakdown?.length, color: "#00ff9d", desc: "MRR, ARR, monthly breakdown, plan data" },
    { key: "tasks", label: "Task Manifest", icon: "✦", count: m?.tasks?.created_today, color: "#ffd060", desc: "Task creation, completion rates, by workspace" },
    { key: "feedback", label: "Transmission Log", icon: "◆", count: null, color: "#bf5fff", desc: "All feedback, bugs, feature requests" },
  ];
  const formats = ["JSON", "CSV", "XLSX", "PDF"];
  const selectedCount = Object.values(selectedSets).filter(Boolean).length;

  const overlayStyle = {
    position: "fixed", inset: 0, zIndex: 1000,
    background: dark ? "rgba(0,2,12,0.88)" : "rgba(10,30,60,0.6)",
    backdropFilter: "blur(12px) saturate(1.3)",
    display: "flex", alignItems: "center", justifyContent: "center",
    animation: "fadeIn 0.2s ease both",
  };

  const panelStyle = {
    width: 520, borderRadius: 10,
    background: dark
      ? "linear-gradient(160deg, rgba(0,5,20,0.99) 0%, rgba(0,12,32,0.97) 60%, rgba(0,5,18,0.99) 100%)"
      : "linear-gradient(160deg, rgba(225,240,255,0.99) 0%, rgba(205,228,252,0.97) 100%)",
    border: `1px solid rgba(${cyan},0.35)`,
    boxShadow: dark
      ? `0 0 0 1px rgba(${cyan},0.06), 0 40px 120px rgba(0,0,0,0.9), 0 0 80px rgba(${cyan},0.1), inset 0 1px 0 rgba(255,255,255,0.08)`
      : `0 0 0 1px rgba(${cyan},0.1), 0 24px 60px rgba(0,80,180,0.2), inset 0 1px 0 rgba(255,255,255,0.7)`,
    clipPath: "polygon(0 0, calc(100% - 24px) 0, 100% 24px, 100% 100%, 24px 100%, 0 calc(100% - 24px))",
    overflow: "hidden",
    animation: "exportRise 0.45s cubic-bezier(0.16,1,0.3,1) both",
    position: "relative",
  };

  return (
    <div style={overlayStyle} onClick={e => { if (e.target === e.currentTarget && phase !== "exporting") onClose(); }}>
      <div style={panelStyle}>
        {/* Prismatic top edge */}
        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2, background: `linear-gradient(90deg, transparent, ${cyanHex}, ${green}, rgba(191,95,255,0.8), ${cyanHex}, transparent)`, boxShadow: `0 0 20px rgba(${cyan},0.5)` }} />
        <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 2, background: `linear-gradient(180deg, ${cyanHex}, rgba(${cyan},0.3), transparent)` }} />
        <div style={{ position: "absolute", top: 0, right: 24, width: 0, height: 0, borderTop: `24px solid rgba(${cyan},0.4)`, borderLeft: "24px solid transparent" }} />

        {/* Header */}
        <div style={{ padding: "22px 26px 18px", borderBottom: `1px solid rgba(${cyan},0.1)`, position: "relative" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              <div style={{ width: 36, height: 36, display: "flex", alignItems: "center", justifyContent: "center",
                background: `radial-gradient(circle, rgba(${cyan},0.2) 0%, rgba(${cyan},0.05) 100%)`,
                border: `1px solid rgba(${cyan},0.4)`,
                clipPath: "polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)",
                fontSize: 16, color: cyanHex, boxShadow: `0 0 20px rgba(${cyan},0.3)` }}>⇣</div>
              <div>
                <div style={{ fontFamily: "'Orbitron', monospace", fontSize: 16, fontWeight: 800, color: dark ? "#fff" : "#0a1a2e", letterSpacing: "0.1em", textShadow: dark ? `0 0 20px rgba(${cyan},0.5)` : "none" }}>DATA EXPORT</div>
                <div style={{ fontSize: 7, color: `rgba(${cyan},0.5)`, letterSpacing: "0.25em", marginTop: 3, fontFamily: "'Share Tech Mono', monospace" }}>INTELLIGENCE EXTRACTION PROTOCOL</div>
              </div>
            </div>
            {phase !== "exporting" && (
              <button onClick={onClose} style={{ background: "transparent", border: `1px solid rgba(${cyan},0.2)`, color: `rgba(${cyan},0.5)`, width: 28, height: 28, borderRadius: 4, cursor: "pointer", fontSize: 14, display: "flex", alignItems: "center", justifyContent: "center", transition: "all 0.2s" }}
                onMouseEnter={e => { e.currentTarget.style.borderColor = `rgba(${cyan},0.5)`; e.currentTarget.style.color = cyanHex; }}
                onMouseLeave={e => { e.currentTarget.style.borderColor = `rgba(${cyan},0.2)`; e.currentTarget.style.color = `rgba(${cyan},0.5)`; }}>✕</button>
            )}
          </div>
        </div>

        <div style={{ padding: "20px 26px 24px" }}>
          {phase === "selecting" && (
            <>
              {/* Dataset selection */}
              <div style={{ fontSize: 8, color: `rgba(${cyan},0.5)`, letterSpacing: "0.22em", textTransform: "uppercase", fontFamily: "'Share Tech Mono', monospace", marginBottom: 12, display: "flex", alignItems: "center", gap: 8 }}>
                <div style={{ width: 3, height: 3, background: cyanHex, borderRadius: "50%" }} />
                Select Data Sets
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 18 }}>
                {dataSets.map(ds => {
                  const sel = selectedSets[ds.key];
                  const rgb = ds.color.replace("#","").match(/.{2}/g)?.map(h=>parseInt(h,16)).join(",") || "0,229,255";
                  return (
                    <button key={ds.key} onClick={() => setSelectedSets(p => ({ ...p, [ds.key]: !p[ds.key] }))} style={{
                      background: sel ? (dark ? `rgba(${rgb},0.1)` : `rgba(${rgb},0.08)`) : (dark ? "rgba(0,229,255,0.02)" : "rgba(0,100,180,0.03)"),
                      border: `1px solid ${sel ? ds.color : `rgba(${cyan},0.15)`}`,
                      borderRadius: 6, padding: "12px 14px",
                      cursor: "pointer", text: "left", textAlign: "left",
                      boxShadow: sel ? `0 0 20px rgba(${rgb},0.12), inset 0 1px 0 rgba(255,255,255,${dark?0.05:0.4})` : "none",
                      transition: "all 0.25s", position: "relative", overflow: "hidden",
                      clipPath: "polygon(0 0, calc(100% - 8px) 0, 100% 8px, 100% 100%, 0 100%)",
                    }}>
                      {sel && <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, ${ds.color}, transparent)` }} />}
                      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 5 }}>
                        <span style={{ fontSize: 14, color: sel ? ds.color : `rgba(${cyan},0.3)`, transition: "color 0.2s" }}>{ds.icon}</span>
                        <span style={{ fontSize: 9, fontFamily: "'Orbitron', monospace", color: sel ? (dark ? "#fff" : "#0a1a2e") : `rgba(${cyan},0.4)`, letterSpacing: "0.06em", fontWeight: 700, transition: "color 0.2s" }}>{ds.label}</span>
                        <div style={{ marginLeft: "auto", width: 14, height: 14, borderRadius: 3, border: `1px solid ${sel ? ds.color : `rgba(${cyan},0.2)`}`, background: sel ? ds.color : "transparent", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 8, color: sel ? (dark ? "#000" : "#fff") : "transparent", transition: "all 0.2s" }}>✓</div>
                      </div>
                      <div style={{ fontSize: 7, color: `rgba(${cyan},0.3)`, fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.05em", lineHeight: 1.5 }}>{ds.desc}</div>
                      {ds.count != null && <div style={{ marginTop: 5, fontSize: 8, color: sel ? ds.color : `rgba(${cyan},0.25)`, fontFamily: "'Orbitron', monospace", fontWeight: 700, transition: "color 0.2s" }}>{ds.count} records</div>}
                    </button>
                  );
                })}
              </div>

              {/* Format selector */}
              <div style={{ fontSize: 8, color: `rgba(${cyan},0.5)`, letterSpacing: "0.22em", textTransform: "uppercase", fontFamily: "'Share Tech Mono', monospace", marginBottom: 10, display: "flex", alignItems: "center", gap: 8 }}>
                <div style={{ width: 3, height: 3, background: cyanHex, borderRadius: "50%" }} />
                Output Format
              </div>
              <div style={{ display: "flex", gap: 6, marginBottom: 22 }}>
                {formats.map(f => (
                  <button key={f} onClick={() => setExportFormat(f)} style={{
                    padding: "7px 16px", fontSize: 9, fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.12em",
                    background: exportFormat === f ? `rgba(${cyan},0.12)` : "transparent",
                    border: `1px solid ${exportFormat === f ? `rgba(${cyan},0.55)` : `rgba(${cyan},0.15)`}`,
                    color: exportFormat === f ? cyanHex : `rgba(${cyan},0.4)`,
                    borderRadius: 4, cursor: "pointer",
                    boxShadow: exportFormat === f ? `0 0 16px rgba(${cyan},0.15), inset 0 1px 0 rgba(255,255,255,0.08)` : "none",
                    transition: "all 0.2s",
                    clipPath: "polygon(0 0, calc(100% - 6px) 0, 100% 6px, 100% 100%, 0 100%)",
                  }}>{f}</button>
                ))}
              </div>

              {/* Export button */}
              <button onClick={startExport} disabled={selectedCount === 0} style={{
                width: "100%", padding: "14px 20px",
                background: selectedCount > 0
                  ? `linear-gradient(135deg, rgba(${cyan},0.15) 0%, rgba(${cyan},0.08) 100%)`
                  : "rgba(0,229,255,0.03)",
                border: `1px solid ${selectedCount > 0 ? `rgba(${cyan},0.5)` : `rgba(${cyan},0.1)`}`,
                borderRadius: 6, cursor: selectedCount > 0 ? "pointer" : "not-allowed",
                display: "flex", alignItems: "center", justifyContent: "center", gap: 12,
                transition: "all 0.3s",
                clipPath: "polygon(0 0, calc(100% - 12px) 0, 100% 12px, 100% 100%, 12px 100%, 0 calc(100% - 12px))",
                position: "relative", overflow: "hidden",
                boxShadow: selectedCount > 0 ? `0 0 30px rgba(${cyan},0.12), inset 0 1px 0 rgba(255,255,255,0.08)` : "none",
              }}
                onMouseEnter={e => { if(selectedCount > 0){ e.currentTarget.style.background = `linear-gradient(135deg, rgba(${cyan},0.22) 0%, rgba(${cyan},0.12) 100%)`; e.currentTarget.style.boxShadow = `0 0 50px rgba(${cyan},0.2), inset 0 1px 0 rgba(255,255,255,0.1)`; }}}
                onMouseLeave={e => { e.currentTarget.style.background = selectedCount > 0 ? `linear-gradient(135deg, rgba(${cyan},0.15) 0%, rgba(${cyan},0.08) 100%)` : "rgba(0,229,255,0.03)"; e.currentTarget.style.boxShadow = selectedCount > 0 ? `0 0 30px rgba(${cyan},0.12), inset 0 1px 0 rgba(255,255,255,0.08)` : "none"; }}
              >
                <div style={{ position: "absolute", inset: 0, left: "-100%", background: `linear-gradient(90deg, transparent, rgba(${cyan},0.08), transparent)`, animation: selectedCount > 0 ? "shimmerSlide 3s ease-in-out infinite" : "none" }} />
                <span style={{ fontSize: 18, color: selectedCount > 0 ? cyanHex : `rgba(${cyan},0.2)`, transition: "color 0.3s" }}>⇣</span>
                <div>
                  <div style={{ fontSize: 10, fontFamily: "'Orbitron', monospace", color: selectedCount > 0 ? (dark ? "#fff" : "#0a1a2e") : `rgba(${cyan},0.25)`, letterSpacing: "0.12em", fontWeight: 700, transition: "color 0.3s" }}>
                    INITIATE EXPORT
                  </div>
                  <div style={{ fontSize: 7, color: `rgba(${cyan},0.35)`, fontFamily: "'Share Tech Mono', monospace", marginTop: 2 }}>
                    {selectedCount > 0 ? `${selectedCount} dataset${selectedCount > 1 ? "s" : ""} · ${exportFormat} format` : "Select at least one dataset"}
                  </div>
                </div>
              </button>
            </>
          )}

          {phase === "exporting" && (
            <div style={{ textAlign: "center", padding: "10px 0 6px" }}>
              <div style={{ fontSize: 10, color: `rgba(${cyan},0.6)`, letterSpacing: "0.2em", fontFamily: "'Share Tech Mono', monospace", marginBottom: 28 }}>
                EXTRACTING INTELLIGENCE PAYLOAD...
              </div>
              {/* Animated ring progress */}
              <div style={{ position: "relative", width: 120, height: 120, margin: "0 auto 24px" }}>
                <svg width="120" height="120" viewBox="0 0 120 120" style={{ transform: "rotate(-90deg)" }}>
                  <circle cx="60" cy="60" r="52" fill="none" stroke={`rgba(${cyan},0.08)`} strokeWidth="4" />
                  <circle cx="60" cy="60" r="52" fill="none" stroke={cyanHex} strokeWidth="3"
                    strokeDasharray={`${2 * Math.PI * 52}`}
                    strokeDashoffset={`${2 * Math.PI * 52 * (1 - progress / 100)}`}
                    strokeLinecap="round"
                    style={{ transition: "stroke-dashoffset 0.3s ease", filter: `drop-shadow(0 0 8px ${cyanHex})` }} />
                  <circle cx="60" cy="60" r="44" fill="none" stroke={dark ? `rgba(0,255,157,0.15)` : "rgba(0,150,100,0.15)"} strokeWidth="1" strokeDasharray="4 8" style={{ animation: "rotateSlow 4s linear infinite", transformOrigin: "60px 60px" }} />
                </svg>
                <div style={{ position: "absolute", inset: 0, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
                  <div style={{ fontFamily: "'Orbitron', monospace", fontSize: 24, fontWeight: 800, color: dark ? "#fff" : "#0a1a2e", textShadow: dark ? `0 0 20px rgba(${cyan},0.7)` : "none" }}>{progress}</div>
                  <div style={{ fontSize: 7, color: `rgba(${cyan},0.4)`, letterSpacing: "0.12em", fontFamily: "'Share Tech Mono', monospace" }}>%</div>
                </div>
              </div>
              {/* Data stream bars */}
              <div style={{ display: "flex", gap: 3, justifyContent: "center", marginBottom: 16 }}>
                {Array.from({ length: 18 }).map((_, i) => (
                  <div key={i} style={{ width: 3, borderRadius: 1, background: i / 18 < progress / 100 ? cyanHex : `rgba(${cyan},0.1)`, height: 6 + Math.sin(i * 0.8) * 10, transition: "background 0.3s", boxShadow: i / 18 < progress / 100 ? `0 0 6px rgba(${cyan},0.5)` : "none" }} />
                ))}
              </div>
              <div style={{ fontSize: 8, color: `rgba(${cyan},0.35)`, fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.1em" }}>
                {progress < 30 ? "INITIALIZING DATA STREAMS..." : progress < 60 ? "COMPILING RECORDS..." : progress < 85 ? "ENCODING PAYLOAD..." : progress < 100 ? "FINALIZING PACKAGE..." : "COMPLETE"}
              </div>
            </div>
          )}

          {phase === "done" && (
            <div style={{ textAlign: "center", padding: "10px 0 6px", animation: "holoRise 0.5s cubic-bezier(0.16,1,0.3,1) both" }}>
              <div style={{ position: "relative", width: 80, height: 80, margin: "0 auto 20px" }}>
                <div style={{ position: "absolute", inset: 0, borderRadius: "50%", background: "radial-gradient(circle, rgba(0,255,157,0.2) 0%, transparent 70%)", animation: "pulseRing 1.5s ease-in-out infinite" }} />
                <div style={{ position: "absolute", inset: 0, borderRadius: "50%", border: "2px solid #00ff9d", boxShadow: "0 0 30px rgba(0,255,157,0.4)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 32 }}>✓</div>
              </div>
              <div style={{ fontFamily: "'Orbitron', monospace", fontSize: 18, fontWeight: 800, color: "#00ff9d", letterSpacing: "0.1em", textShadow: "0 0 30px rgba(0,255,157,0.6)", marginBottom: 8 }}>EXPORTED</div>
              <div style={{ fontSize: 9, color: `rgba(${cyan},0.45)`, fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.14em", marginBottom: 22 }}>
                {selectedCount} DATASET{selectedCount > 1 ? "S" : ""} · {exportFormat} · TRANSMISSION COMPLETE
              </div>
              <button onClick={onClose} style={{
                padding: "10px 30px", fontFamily: "'Share Tech Mono', monospace",
                fontSize: 9, letterSpacing: "0.18em", color: cyanHex,
                background: `rgba(${cyan},0.08)`, border: `1px solid rgba(${cyan},0.35)`,
                borderRadius: 4, cursor: "pointer", transition: "all 0.2s",
                clipPath: "polygon(0 0, calc(100% - 8px) 0, 100% 8px, 100% 100%, 0 100%)",
              }}
                onMouseEnter={e => { e.currentTarget.style.background = `rgba(${cyan},0.15)`; }}
                onMouseLeave={e => { e.currentTarget.style.background = `rgba(${cyan},0.08)`; }}
              >CLOSE TERMINAL</button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── THEME TOGGLE BUTTON ────────────────────────────────────────────────────────
function ThemeToggle({ dark, onToggle }) {
  const [hov, setHov] = useState(false);
  return (
    <button
      onClick={onToggle}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      title={dark ? "Switch to Light Mode" : "Switch to Dark Mode"}
      style={{
        position: "relative", display: "flex", alignItems: "center", gap: 8,
        padding: "7px 14px",
        background: hov
          ? (dark ? "rgba(0,229,255,0.1)" : "rgba(0,100,180,0.1)")
          : (dark ? "rgba(0,229,255,0.04)" : "rgba(0,100,180,0.05)"),
        border: `1px solid ${hov ? (dark ? "rgba(0,229,255,0.45)" : "rgba(0,100,180,0.4)") : (dark ? "rgba(0,229,255,0.2)" : "rgba(0,100,180,0.22)")}`,
        borderRadius: 5, cursor: "pointer",
        clipPath: "polygon(0 0, calc(100% - 8px) 0, 100% 8px, 100% 100%, 0 100%)",
        boxShadow: hov ? `0 0 20px rgba(0,229,255,0.14)` : "none",
        transition: "all 0.28s cubic-bezier(0.16,1,0.3,1)",
        overflow: "hidden",
      }}
    >
      {/* Sliding track */}
      <div style={{
        width: 32, height: 16, borderRadius: 10, position: "relative",
        background: dark ? "rgba(0,229,255,0.12)" : "rgba(0,100,180,0.15)",
        border: `1px solid ${dark ? "rgba(0,229,255,0.3)" : "rgba(0,100,180,0.35)"}`,
        transition: "all 0.35s",
        flexShrink: 0,
      }}>
        {/* Knob */}
        <div style={{
          position: "absolute", top: 1.5, left: dark ? 1.5 : 16,
          width: 11, height: 11, borderRadius: "50%",
          background: dark ? "#00e5ff" : "#0088cc",
          boxShadow: dark ? "0 0 8px #00e5ff, 0 0 16px rgba(0,229,255,0.4)" : "0 0 8px #0088cc",
          transition: "left 0.35s cubic-bezier(0.16,1,0.3,1), background 0.35s",
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 6,
        }}>
          <span style={{ color: dark ? "#003344" : "#fff", fontSize: 7 }}>{dark ? "☾" : "☀"}</span>
        </div>
      </div>
      <span style={{
        fontSize: 8, letterSpacing: "0.14em",
        color: dark ? "rgba(0,229,255,0.55)" : "rgba(0,100,180,0.65)",
        fontFamily: "'Share Tech Mono', monospace",
        transition: "color 0.3s",
      }}>{dark ? "DARK" : "LITE"}</span>
    </button>
  );
}

function useAdminFetch(path) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const fetch_ = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const token = localStorage.getItem("access_token");
      const res = await fetch(`${API}${path}`, { headers: { Authorization: `Bearer ${token}` } });
      if (!res.ok) throw new Error(`${res.status}`);
      setData(await res.json());
    } catch (e) { setError(e.message); } finally { setLoading(false); }
  }, [path]);
  useEffect(() => { fetch_(); }, [fetch_]);
  return { data, loading, error, refetch: fetch_ };
}

// ── HOLOGRAPHIC GRID BACKGROUND ──────────────────────────────────────────────
function HoloGrid() {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    let W = canvas.width = canvas.offsetWidth;
    let H = canvas.height = canvas.offsetHeight;
    let t = 0;
    let raf;

    // Star field
    const stars = Array.from({ length: 120 }, () => ({
      x: Math.random() * W, y: Math.random() * H,
      r: 0.3 + Math.random() * 1.2,
      alpha: 0.2 + Math.random() * 0.6,
      twinkle: Math.random() * Math.PI * 2,
      speed: 0.005 + Math.random() * 0.02,
    }));

    // Scan lines
    const scanLines = Array.from({ length: 5 }, (_, i) => ({
      y: Math.random() * H,
      speed: 0.3 + Math.random() * 0.5,
      alpha: 0.03 + Math.random() * 0.05,
      width: 60 + Math.random() * 120,
    }));

    // Data nodes — more of them, richer
    const nodes = Array.from({ length: 28 }, () => ({
      x: Math.random() * W, y: Math.random() * H,
      vx: (Math.random() - 0.5) * 0.18, vy: (Math.random() - 0.5) * 0.18,
      r: 1.2 + Math.random() * 2.5,
      hue: [195, 160, 280, 45][Math.floor(Math.random() * 4)],
      pulse: Math.random() * Math.PI * 2,
      type: Math.random() > 0.7 ? "diamond" : "circle",
    }));

    // Nebula clouds (static color blobs that shift slightly)
    const nebulae = [
      { x: W * 0.15, y: H * 0.25, rx: W * 0.28, ry: H * 0.22, hue: 195, alpha: 0.04 },
      { x: W * 0.78, y: H * 0.65, rx: W * 0.22, ry: H * 0.28, hue: 280, alpha: 0.035 },
      { x: W * 0.5,  y: H * 0.1,  rx: W * 0.18, ry: H * 0.15, hue: 160, alpha: 0.025 },
    ];

    function draw() {
      ctx.clearRect(0, 0, W, H);
      t += 0.005;

      // Nebula clouds
      nebulae.forEach(n => {
        const pulse = Math.sin(t * 0.4 + n.hue) * 0.008;
        const g = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, Math.max(n.rx, n.ry));
        g.addColorStop(0, `hsla(${n.hue},100%,55%,${n.alpha + pulse})`);
        g.addColorStop(0.4, `hsla(${n.hue},80%,45%,${n.alpha * 0.5})`);
        g.addColorStop(1, `hsla(${n.hue},60%,30%,0)`);
        ctx.save(); ctx.scale(n.rx / Math.max(n.rx, n.ry), n.ry / Math.max(n.rx, n.ry));
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(n.x / (n.rx / Math.max(n.rx, n.ry)), n.y / (n.ry / Math.max(n.rx, n.ry)), Math.max(n.rx, n.ry), 0, Math.PI * 2); ctx.fill();
        ctx.restore();
      });

      // Stars with twinkle
      stars.forEach(s => {
        s.twinkle += s.speed;
        const a = s.alpha * (0.5 + 0.5 * Math.sin(s.twinkle));
        ctx.fillStyle = `rgba(180,230,255,${a})`;
        ctx.beginPath(); ctx.arc(s.x, s.y, s.r, 0, Math.PI * 2); ctx.fill();
      });

      // Perspective grid — sharper, more neon
      const gridAlpha = 0.055;
      const vanishY = H * 0.52;
      const gridLines = 30;
      ctx.lineWidth = 0.5;
      for (let i = 0; i <= gridLines; i++) {
        const x = (i / gridLines) * W;
        const wave = Math.sin(t * 0.8 + i * 0.25) * 1.5;
        const alpha = gridAlpha * (0.4 + 0.6 * Math.abs(Math.sin(t * 0.3 + i * 0.1)));
        ctx.strokeStyle = `rgba(0,212,255,${alpha})`;
        ctx.beginPath();
        ctx.moveTo(x + wave, vanishY);
        ctx.lineTo(W * 0.5 + (x - W * 0.5) * 3.2, H + 80);
        ctx.stroke();
      }
      for (let i = 0; i <= 12; i++) {
        const progress = i / 12;
        const y = vanishY + progress * (H - vanishY + 80);
        const spread = progress * W * 1.6;
        const alpha = gridAlpha * (0.2 + progress * 0.8) * (0.6 + 0.4 * Math.sin(t + i));
        ctx.globalAlpha = alpha;
        ctx.strokeStyle = `rgba(0,212,255,1)`;
        ctx.beginPath();
        ctx.moveTo(W * 0.5 - spread * 0.5, y);
        ctx.lineTo(W * 0.5 + spread * 0.5, y);
        ctx.stroke();
        ctx.globalAlpha = 1;
      }

      // Horizontal scan sweep lines
      scanLines.forEach(s => {
        s.y += s.speed;
        if (s.y > H + s.width) s.y = -s.width;
        const sg = ctx.createLinearGradient(0, s.y - s.width, 0, s.y + s.width);
        sg.addColorStop(0, "rgba(0,220,255,0)");
        sg.addColorStop(0.45, `rgba(0,230,255,${s.alpha})`);
        sg.addColorStop(0.55, `rgba(0,230,255,${s.alpha * 1.4})`);
        sg.addColorStop(1, "rgba(0,220,255,0)");
        ctx.fillStyle = sg;
        ctx.fillRect(0, s.y - s.width, W, s.width * 2);
      });

      // Data nodes
      nodes.forEach(n => {
        n.x += n.vx; n.y += n.vy; n.pulse += 0.018;
        if (n.x < 0 || n.x > W) n.vx *= -1;
        if (n.y < 0 || n.y > H) n.vy *= -1;
        const alpha = 0.35 + Math.sin(n.pulse) * 0.28;
        const glow = ctx.createRadialGradient(n.x, n.y, 0, n.x, n.y, n.r * 5);
        glow.addColorStop(0, `hsla(${n.hue},100%,72%,${alpha * 0.7})`);
        glow.addColorStop(1, `hsla(${n.hue},100%,72%,0)`);
        ctx.fillStyle = glow;
        ctx.beginPath(); ctx.arc(n.x, n.y, n.r * 5, 0, Math.PI * 2); ctx.fill();
        // Diamond or circle core
        if (n.type === "diamond") {
          ctx.fillStyle = `hsla(${n.hue},100%,92%,${alpha})`;
          ctx.save(); ctx.translate(n.x, n.y); ctx.rotate(Math.PI / 4);
          ctx.fillRect(-n.r, -n.r, n.r * 2, n.r * 2); ctx.restore();
        } else {
          ctx.fillStyle = `hsla(${n.hue},100%,92%,${alpha})`;
          ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2); ctx.fill();
        }
      });

      // Node connections — more vibrant
      ctx.lineWidth = 0.5;
      for (let i = 0; i < nodes.length; i++) {
        for (let j = i + 1; j < nodes.length; j++) {
          const dx = nodes[i].x - nodes[j].x, dy = nodes[i].y - nodes[j].y;
          const dist = Math.sqrt(dx * dx + dy * dy);
          if (dist < 180) {
            const str = (1 - dist / 180) * 0.14;
            const hue = (nodes[i].hue + nodes[j].hue) / 2;
            ctx.strokeStyle = `hsla(${hue},100%,65%,${str})`;
            ctx.beginPath();
            ctx.moveTo(nodes[i].x, nodes[i].y);
            ctx.lineTo(nodes[j].x, nodes[j].y);
            ctx.stroke();
          }
        }
      }

      // Vertical data streams (falling digits illusion)
      const streams = [W * 0.08, W * 0.22, W * 0.63, W * 0.82, W * 0.92];
      streams.forEach((sx, si) => {
        const streamT = (t * 0.6 + si * 1.3) % 1;
        const streamY = streamT * H * 1.5 - H * 0.25;
        const streamG = ctx.createLinearGradient(0, streamY - 80, 0, streamY + 80);
        streamG.addColorStop(0, "rgba(0,255,136,0)");
        streamG.addColorStop(0.5, `rgba(0,255,136,0.06)`);
        streamG.addColorStop(1, "rgba(0,255,136,0)");
        ctx.fillStyle = streamG;
        ctx.fillRect(sx - 1, streamY - 80, 2, 160);
      });

      raf = requestAnimationFrame(draw);
    }
    draw();
    const onResize = () => { W = canvas.width = canvas.offsetWidth; H = canvas.height = canvas.offsetHeight; };
    window.addEventListener("resize", onResize);
    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", onResize); };
  }, []);
  return <canvas ref={canvasRef} style={{ position: "fixed", inset: 0, width: "100%", height: "100%", pointerEvents: "none", zIndex: 0 }} />;
}

// ── HOLOGRAPHIC METRIC CARD — PRISMATIC UNIVERSE EDITION ─────────────────────
function HoloCard({ label, value, sub, color = "#00e5ff", icon, trend, delay = 0, story, accentShape }) {
  const [hov, setHov] = useState(false);
  const [tilt, setTilt] = useState({ x: 0, y: 0 });
  const [particles, setParticles] = useState([]);
  const [shimmerPos, setShimmerPos] = useState(0);
  const ref = useRef(null);
  const shimmerRef = useRef(null);

  const [mousePos, setMousePos] = useState({ x: 50, y: 50 });
  const onMove = (e) => {
    const r = ref.current.getBoundingClientRect();
    const x = ((e.clientX - r.left) / r.width - 0.5) * 32;
    const y = ((e.clientY - r.top) / r.height - 0.5) * -32;
    const mx = ((e.clientX - r.left) / r.width) * 100;
    const my = ((e.clientY - r.top) / r.height) * 100;
    setTilt({ x, y }); setMousePos({ x: mx, y: my });
    setShimmerPos(mx);
  };
  const onLeave = () => { setTilt({ x: 0, y: 0 }); setHov(false); };
  const onEnter = () => {
    setHov(true);
    setParticles(Array.from({ length: 20 }, (_, i) => ({
      id: i, x: Math.random() * 100, delay: i * 45,
      size: 1.5 + Math.random() * 3,
      hue: [color, "#00ff9d", "#bf5fff", "#ffd060"][Math.floor(Math.random() * 4)],
    })));
  };

  const hexToRgb = (hex) => {
    const rgbMatch = hex.match(/^rgb\((\d+),(\d+),(\d+)\)$/);
    if (rgbMatch) return `${rgbMatch[1]},${rgbMatch[2]},${rgbMatch[3]}`;
    if (hex === "#00d4ff" || hex === "#00e5ff") return "0,229,255";
    if (hex === "#00ff88" || hex === "#00ff9d") return "0,255,157";
    if (hex === "#ff6b35") return "255,107,53";
    if (hex === "#a855f7" || hex === "#bf5fff") return "191,95,255";
    if (hex === "#ffd700" || hex === "#ffd060") return "255,208,96";
    if (hex === "#ff3366" || hex === "#ff2d55") return "255,45,85";
    return "0,229,255";
  };
  const rgb = hexToRgb(color);

  // Complementary prismatic second color
  const prismColor2 = color === "#00e5ff" ? "#00ff9d"
    : color === "#00ff9d" ? "#bf5fff"
    : color === "#bf5fff" ? "#ffd060"
    : color === "#ffd060" ? "#ff2d55"
    : "#00e5ff";
  const rgb2 = hexToRgb(prismColor2);

  return (
    <div
      ref={ref}
      onMouseMove={onMove}
      onMouseEnter={onEnter}
      onMouseLeave={onLeave}
      style={{
        position: "relative",
        borderRadius: 8,
        padding: "26px 26px 22px",
        cursor: "default",
        animationDelay: `${delay}ms`,
        animation: "holoRise 0.9s cubic-bezier(0.16,1,0.3,1) both",
        transformStyle: "preserve-3d",
        transform: `perspective(1000px) rotateX(${tilt.y}deg) rotateY(${tilt.x}deg) ${hov ? "translateZ(28px) scale(1.04)" : "translateZ(0)"}`,
        transition: hov ? "transform 0.05s linear" : "transform 0.7s cubic-bezier(0.16,1,0.3,1)",
        background: hov
          ? `radial-gradient(ellipse at ${mousePos.x}% ${mousePos.y}%, rgba(${rgb},0.13) 0%, rgba(0,4,16,0.98) 55%),
             linear-gradient(145deg, rgba(0,8,24,0.99) 0%, rgba(0,16,36,0.95) 100%)`
          : `linear-gradient(160deg, rgba(0,6,20,0.99) 0%, rgba(0,12,28,0.96) 45%, rgba(0,4,16,0.99) 100%)`,
        border: `1px solid rgba(${rgb},${hov ? 0.7 : 0.25})`,
        boxShadow: hov
          ? `0 0 0 1px rgba(${rgb},0.1),
             0 28px 80px rgba(0,0,0,0.9),
             0 0 120px rgba(${rgb},0.22),
             0 0 40px rgba(${rgb},0.1),
             0 0 0 4px rgba(${rgb},0.03),
             inset 0 0 60px rgba(${rgb},0.05),
             inset 0 1px 0 rgba(255,255,255,0.1),
             inset 0 0 0 1px rgba(${rgb},0.06)`
          : `0 8px 40px rgba(0,0,0,0.8),
             0 0 0 1px rgba(${rgb},0.02),
             inset 0 0 30px rgba(${rgb},0.025),
             inset 0 1px 0 rgba(255,255,255,0.05)`,
        backdropFilter: "blur(32px) saturate(1.4)",
        overflow: "hidden",
        clipPath: "polygon(0 0, calc(100% - 20px) 0, 100% 20px, 100% 100%, 20px 100%, 0 calc(100% - 20px))",
      }}
    >
      {/* ── PRISMATIC RAINBOW BORDER — full perimeter gradient sweep ── */}
      <div style={{
        position: "absolute", inset: 0, borderRadius: 8, pointerEvents: "none", zIndex: 1,
        background: "transparent",
        boxShadow: hov
          ? `inset 0 0 0 1px transparent`
          : "none",
      }} />

      {/* Top prismatic edge — full rainbow with animation */}
      <div style={{
        position: "absolute", top: 0, left: 0, right: 0, height: hov ? 3 : 2,
        background: hov
          ? `linear-gradient(90deg,
              rgba(${rgb},0) 0%,
              ${color} 15%,
              ${prismColor2} 35%,
              rgba(255,255,255,0.9) 50%,
              ${prismColor2} 65%,
              ${color} 85%,
              rgba(${rgb},0) 100%)`
          : `linear-gradient(90deg, transparent, rgba(${rgb},0.7), rgba(${rgb2},0.4), rgba(${rgb},0.5), transparent)`,
        boxShadow: hov
          ? `0 0 20px ${color}, 0 0 40px rgba(${rgb},0.5), 0 0 80px rgba(${rgb},0.2)`
          : `0 0 8px rgba(${rgb},0.3)`,
        transition: "all 0.3s", pointerEvents: "none",
        animation: hov ? "prismaticEdge 2s linear infinite" : "none",
        zIndex: 2,
      }} />

      {/* Right prismatic edge */}
      <div style={{
        position: "absolute", top: 20, right: 0, bottom: 0, width: hov ? 2 : 1,
        background: hov
          ? `linear-gradient(180deg, ${color}, ${prismColor2}, rgba(${rgb},0.2), transparent)`
          : `linear-gradient(180deg, rgba(${rgb},0.3), transparent)`,
        boxShadow: hov ? `0 0 12px rgba(${rgb},0.4)` : "none",
        transition: "all 0.4s", pointerEvents: "none", zIndex: 2,
      }} />

      {/* Bottom edge */}
      <div style={{
        position: "absolute", bottom: 0, left: 20, right: 0, height: 1,
        background: `linear-gradient(90deg, rgba(${rgb},0.15), rgba(${rgb2},0.1), transparent)`,
        pointerEvents: "none", zIndex: 2,
      }} />

      {/* Left accent bar — double-layer neon bar */}
      <div style={{
        position: "absolute", left: 0, top: 0, bottom: 0, width: 4,
        background: hov
          ? `linear-gradient(180deg, ${color} 0%, ${prismColor2} 40%, rgba(${rgb},0.3) 70%, transparent 100%)`
          : `linear-gradient(180deg, transparent 0%, ${color} 30%, rgba(${rgb},0.4) 70%, transparent 100%)`,
        boxShadow: hov
          ? `0 0 20px ${color}, 0 0 40px rgba(${rgb},0.4), inset 0 0 8px rgba(255,255,255,0.3)`
          : `0 0 8px rgba(${rgb},0.2)`,
        transition: "all 0.4s", pointerEvents: "none",
      }} />
      {/* Second thinner bar for depth */}
      <div style={{
        position: "absolute", left: 5, top: "20%", bottom: "20%", width: 1,
        background: `linear-gradient(180deg, transparent, rgba(${rgb},${hov ? 0.6 : 0.15}), transparent)`,
        transition: "opacity 0.4s", pointerEvents: "none",
      }} />

      {/* Glass reflection top half — layered */}
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: "50%", background: "linear-gradient(180deg, rgba(255,255,255,0.07) 0%, rgba(255,255,255,0.02) 60%, rgba(255,255,255,0) 100%)", pointerEvents: "none" }} />
      {/* Glass reflection bottom */}
      <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: "20%", background: "linear-gradient(0deg, rgba(255,255,255,0.02) 0%, rgba(255,255,255,0) 100%)", pointerEvents: "none" }} />

      {/* HOLOGRAPHIC SHIMMER — diagonal iridescent sweep on hover */}
      {hov && (
        <div style={{
          position: "absolute", inset: 0, pointerEvents: "none", zIndex: 1,
          background: `linear-gradient(
            105deg,
            transparent 0%,
            transparent calc(${shimmerPos}% - 30%),
            rgba(255,255,255,0.04) calc(${shimmerPos}% - 20%),
            rgba(${rgb},0.08) calc(${shimmerPos}% - 10%),
            rgba(255,255,255,0.12) ${shimmerPos}%,
            rgba(${rgb2},0.08) calc(${shimmerPos}% + 10%),
            rgba(255,255,255,0.04) calc(${shimmerPos}% + 20%),
            transparent calc(${shimmerPos}% + 30%),
            transparent 100%
          )`,
        }} />
      )}

      {/* Corner cuts — more dramatic */}
      <div style={{ position: "absolute", top: 0, right: 20, width: 0, height: 0, borderTop: `20px solid rgba(${rgb},${hov ? 0.7 : 0.25})`, borderLeft: "20px solid transparent", pointerEvents: "none", zIndex: 3 }} />
      <div style={{ position: "absolute", bottom: 0, left: 20, width: 0, height: 0, borderBottom: `20px solid rgba(${rgb},${hov ? 0.5 : 0.13})`, borderRight: "20px solid transparent", pointerEvents: "none", zIndex: 3 }} />

      {/* Corner brackets — all 4, animated expand on hover */}
      {[
        { top: 8, left: 8, bt: `2.5px solid ${color}`, bl: `2.5px solid ${color}`, bb: "none", br: "none" },
        { bottom: 8, right: 8, bt: "none", bl: "none", bb: `2.5px solid ${color}`, br: `2.5px solid ${color}` },
        { top: 8, right: 30, bt: `1px solid rgba(${rgb},0.5)`, bl: "none", bb: "none", br: `1px solid rgba(${rgb},0.5)` },
        { bottom: 8, left: 30, bt: "none", bl: `1px solid rgba(${rgb},0.5)`, bb: `1px solid rgba(${rgb},0.5)`, br: "none" },
      ].map((c, i) => (
        <div key={i} style={{
          position: "absolute", ...c,
          width: hov ? (i < 2 ? 22 : 14) : (i < 2 ? 18 : 10),
          height: hov ? (i < 2 ? 22 : 14) : (i < 2 ? 18 : 10),
          borderTop: c.bt, borderLeft: c.bl, borderBottom: c.bb, borderRight: c.br,
          opacity: hov ? 1 : (i < 2 ? 0.6 : 0.25),
          transition: "all 0.3s cubic-bezier(0.16,1,0.3,1)",
          boxShadow: hov && i < 2 ? `0 0 14px rgba(${rgb},0.5)` : "none",
          pointerEvents: "none",
        }} />
      ))}

      {/* Scanning beam line that sweeps vertically */}
      {hov && (
        <div style={{
          position: "absolute", left: 0, right: 0, height: 1, pointerEvents: "none", zIndex: 2,
          background: `linear-gradient(90deg, transparent, rgba(${rgb},0.6), rgba(255,255,255,0.3), rgba(${rgb},0.6), transparent)`,
          boxShadow: `0 0 12px rgba(${rgb},0.5)`,
          animation: "cardScan 2s linear infinite",
        }} />
      )}

      {/* Dynamic mouse-follow inner glow — stronger */}
      {hov && <div style={{ position: "absolute", inset: 0, background: `radial-gradient(circle 100px at ${mousePos.x}% ${mousePos.y}%, rgba(${rgb},0.15), transparent 70%)`, pointerEvents: "none", transition: "background 0.03s", zIndex: 1 }} />}
      {/* Second smaller intense glow at cursor */}
      {hov && <div style={{ position: "absolute", inset: 0, background: `radial-gradient(circle 30px at ${mousePos.x}% ${mousePos.y}%, rgba(${rgb},0.25), transparent 100%)`, pointerEvents: "none", transition: "background 0.03s", zIndex: 1 }} />}

      {/* Background accent shape */}
      {accentShape === "ring" && (
        <>
          <div style={{ position: "absolute", top: -40, right: -40, width: 160, height: 160, borderRadius: "50%", border: `1px solid rgba(${rgb},0.08)`, pointerEvents: "none", animation: "pulseRing 5s ease-in-out infinite" }} />
          <div style={{ position: "absolute", top: -20, right: -20, width: 110, height: 110, borderRadius: "50%", border: `1px solid rgba(${rgb},0.05)`, pointerEvents: "none", animation: "pulseRing 5s ease-in-out 1.5s infinite" }} />
          <div style={{ position: "absolute", top: -5, right: -5, width: 70, height: 70, borderRadius: "50%", border: `1px solid rgba(${rgb},0.04)`, pointerEvents: "none" }} />
        </>
      )}
      {accentShape === "hex" && (
        <>
          <div style={{ position: "absolute", bottom: -30, right: -10, fontSize: 110, color: `rgba(${rgb},0.04)`, pointerEvents: "none", lineHeight: 1, animation: "rotateSlow 30s linear infinite" }}>⬡</div>
          <div style={{ position: "absolute", top: -20, left: -20, fontSize: 60, color: `rgba(${rgb},0.03)`, pointerEvents: "none", lineHeight: 1, animation: "rotateSlow 20s linear infinite reverse" }}>⬡</div>
        </>
      )}
      {accentShape === "cross" && (
        <>
          <div style={{ position: "absolute", top: "50%", right: 12, transform: "translateY(-50%)", fontSize: 80, color: `rgba(${rgb},0.04)`, pointerEvents: "none" }}>✚</div>
          <div style={{ position: "absolute", bottom: -10, left: -10, fontSize: 50, color: `rgba(${rgb2},0.03)`, pointerEvents: "none" }}>✦</div>
        </>
      )}

      {/* Inner ambient glow cloud */}
      <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at 80% 20%, rgba(${rgb},0.04) 0%, transparent 60%), radial-gradient(ellipse at 20% 80%, rgba(${rgb2},0.025) 0%, transparent 50%)`, pointerEvents: "none" }} />

      {/* Floating particles on hover — more, colorful */}
      {hov && particles.map(p => (
        <div key={p.id} style={{
          position: "absolute", bottom: 0, left: `${p.x}%`,
          width: p.size, height: p.size, borderRadius: "50%",
          background: p.hue,
          boxShadow: `0 0 ${p.size * 5}px ${p.hue}, 0 0 ${p.size * 10}px ${p.hue}44`,
          animation: `particleFloat ${0.8 + p.size * 0.25}s ease-out ${p.delay}ms forwards`,
          pointerEvents: "none", zIndex: 5,
        }} />
      ))}

      {/* ── CONTENT (above all overlays) ── */}
      <div style={{ position: "relative", zIndex: 4 }}>
        {/* Icon + label row */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            {/* Triple-dot status indicator */}
            <div style={{ display: "flex", gap: 3, alignItems: "center" }}>
              <div style={{ width: 5, height: 5, borderRadius: "50%", background: color, boxShadow: `0 0 12px ${color}, 0 0 24px rgba(${rgb},0.4)`, animation: "pulse-glow 2s infinite" }} />
              <div style={{ width: 3, height: 3, borderRadius: "50%", background: `rgba(${rgb},0.5)`, animation: "pulse-glow 2s 0.4s infinite" }} />
              <div style={{ width: 2, height: 2, borderRadius: "50%", background: `rgba(${rgb},0.25)`, animation: "pulse-glow 2s 0.8s infinite" }} />
            </div>
            <div style={{ fontSize: 9, color: color, letterSpacing: "0.24em", textTransform: "uppercase", fontFamily: "'Share Tech Mono', monospace", opacity: 0.9, textShadow: hov ? `0 0 16px rgba(${rgb},0.7)` : "none", transition: "text-shadow 0.3s" }}>
              {label}
            </div>
          </div>
          {/* Icon hexagon — upgraded */}
          <div style={{
            width: 38, height: 38, position: "relative",
            display: "flex", alignItems: "center", justifyContent: "center",
          }}>
            {/* Hex background layers */}
            <div style={{
              position: "absolute", inset: 0,
              clipPath: "polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)",
              background: `radial-gradient(circle, rgba(${rgb},0.25) 0%, rgba(${rgb},0.08) 100%)`,
              border: `1px solid rgba(${rgb},${hov ? 0.7 : 0.35})`,
              boxShadow: hov ? `0 0 25px rgba(${rgb},0.4), inset 0 0 15px rgba(${rgb},0.15)` : "none",
              transition: "all 0.3s",
            }} />
            {/* Rotating outer ring */}
            {hov && <div style={{
              position: "absolute", inset: -4,
              clipPath: "polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)",
              border: `1px solid rgba(${rgb},0.3)`,
              animation: "rotateSlow 4s linear infinite",
            }} />}
            <span style={{ fontSize: 16, color: color, textShadow: hov ? `0 0 20px ${color}` : "none", position: "relative", zIndex: 1 }}>{icon}</span>
          </div>
        </div>

        {/* Main value — MASSIVE, multi-layer glow */}
        <div style={{
          fontSize: 42, fontWeight: 900, color: "#fff",
          fontFamily: "'Orbitron', monospace",
          textShadow: hov
            ? `0 0 20px rgba(${rgb},1), 0 0 50px rgba(${rgb},0.6), 0 0 100px rgba(${rgb},0.3), 0 0 200px rgba(${rgb},0.1), 0 2px 0 rgba(0,0,0,0.5)`
            : `0 0 20px rgba(${rgb},0.6), 0 0 50px rgba(${rgb},0.2), 0 2px 4px rgba(0,0,0,0.6)`,
          letterSpacing: "-0.04em",
          lineHeight: 1,
          marginBottom: 10,
          transition: "text-shadow 0.3s",
        }}>{value}</div>

        {/* Sub label */}
        {sub && <div style={{ fontSize: 10, color: `rgba(${rgb},0.6)`, fontFamily: "'Share Tech Mono', monospace", marginBottom: 12, letterSpacing: "0.06em" }}>{sub}</div>}

        {/* Story line */}
        {story && (
          <div style={{ fontSize: 8, color: "rgba(150,220,255,0.28)", fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.1em", lineHeight: 1.8, marginBottom: 12, borderLeft: `2px solid rgba(${rgb},0.15)`, paddingLeft: 8 }}>
            {story}
          </div>
        )}

        {/* Trend badge — more dramatic */}
        {trend !== undefined && (
          <div style={{ display: "inline-flex", alignItems: "center", gap: 8 }}>
            <div style={{
              fontSize: 10, fontWeight: 700,
              color: trend >= 0 ? "#00ff9d" : "#ff2d55",
              background: trend >= 0 ? "rgba(0,255,157,0.12)" : "rgba(255,45,85,0.12)",
              border: `1px solid ${trend >= 0 ? "rgba(0,255,157,0.45)" : "rgba(255,45,85,0.45)"}`,
              padding: "4px 12px", borderRadius: 3,
              fontFamily: "'Share Tech Mono', monospace",
              letterSpacing: "0.08em",
              boxShadow: trend >= 0
                ? "0 0 16px rgba(0,255,157,0.2), inset 0 1px 0 rgba(255,255,255,0.1)"
                : "0 0 16px rgba(255,45,85,0.2), inset 0 1px 0 rgba(255,255,255,0.1)",
              clipPath: "polygon(0 0, calc(100% - 6px) 0, 100% 6px, 100% 100%, 6px 100%, 0 calc(100% - 6px))",
            }}>{trend >= 0 ? "▲" : "▼"} {Math.abs(trend)}%</div>
            <span style={{ fontSize: 8, color: "rgba(150,200,255,0.2)", fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.05em" }}>vs 30D</span>
          </div>
        )}
      </div>
    </div>
  );
}

// ── JARVIS SPARKLINE ──────────────────────────────────────────────────────────
function HoloSparkline({ values, color = "#00d4ff", height = 60 }) {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !values || values.length < 2) return;
    const ctx = canvas.getContext("2d");
    const W = canvas.width = canvas.offsetWidth * 2;
    const H = canvas.height = height * 2;
    canvas.style.width = "100%";
    canvas.style.height = `${height}px`;
    const max = Math.max(...values, 1);
    const min = Math.min(...values);
    const range = max - min || 1;
    let t = 0, raf;

    // Parse color to rgb
    const rgbMap = {
      "#00d4ff": "0,212,255", "#00e5ff": "0,229,255",
      "#00ff88": "0,255,136", "#00ff9d": "0,255,157",
      "#a855f7": "168,85,247", "#bf5fff": "191,95,255",
      "#ffd700": "255,215,0", "#ffd060": "255,208,96",
    };
    const rgb = rgbMap[color] || "0,212,255";

    function getPoints(offset = 0) {
      return values.map((v, i) => ({
        x: (i / (values.length - 1)) * W,
        y: H - ((v - min) / range) * (H * 0.76) - H * 0.1 + Math.sin(t * 0.8 + i * 0.35 + offset) * 1.5,
      }));
    }

    function drawCurve(pts, stroke, lineW, shadow, shadowBlur) {
      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].y);
      for (let i = 1; i < pts.length - 1; i++) {
        const mx = (pts[i].x + pts[i + 1].x) / 2;
        const my = (pts[i].y + pts[i + 1].y) / 2;
        ctx.quadraticCurveTo(pts[i].x, pts[i].y, mx, my);
      }
      ctx.lineTo(pts[pts.length - 1].x, pts[pts.length - 1].y);
      ctx.strokeStyle = stroke;
      ctx.lineWidth = lineW;
      ctx.lineJoin = "round";
      ctx.lineCap = "round";
      if (shadow) { ctx.shadowColor = shadow; ctx.shadowBlur = shadowBlur; }
      ctx.stroke();
      ctx.shadowBlur = 0;
    }

    function draw() {
      t += 0.015;
      ctx.clearRect(0, 0, W, H);

      const pts = getPoints();

      // Subtle horizontal grid
      ctx.setLineDash([4, 12]);
      for (let i = 1; i < 4; i++) {
        const y = H * (i / 4);
        ctx.strokeStyle = `rgba(${rgb},0.07)`;
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
      }
      ctx.setLineDash([]);

      // Deep gradient fill — two layers
      const fillGrad = ctx.createLinearGradient(0, 0, 0, H);
      fillGrad.addColorStop(0, `rgba(${rgb},0.28)`);
      fillGrad.addColorStop(0.45, `rgba(${rgb},0.1)`);
      fillGrad.addColorStop(1, `rgba(${rgb},0)`);
      ctx.beginPath();
      ctx.moveTo(pts[0].x, H);
      pts.forEach((p, i) => {
        if (i === 0) return;
        const prev = pts[i - 1];
        const mx = (prev.x + p.x) / 2, my = (prev.y + p.y) / 2;
        ctx.quadraticCurveTo(prev.x, prev.y, mx, my);
      });
      ctx.lineTo(pts[pts.length - 1].x, H);
      ctx.closePath();
      ctx.fillStyle = fillGrad;
      ctx.fill();

      // Second shimmer fill layer (brighter, narrower)
      const shimFill = ctx.createLinearGradient(0, 0, 0, H);
      shimFill.addColorStop(0, `rgba(${rgb},0.14)`);
      shimFill.addColorStop(0.3, `rgba(${rgb},0.04)`);
      shimFill.addColorStop(1, `rgba(${rgb},0)`);
      ctx.beginPath();
      ctx.moveTo(pts[0].x, H);
      pts.forEach((p, i) => {
        if (i === 0) return;
        const prev = pts[i - 1];
        const mx = (prev.x + p.x) / 2, my = (prev.y + p.y) / 2;
        ctx.quadraticCurveTo(prev.x, prev.y, mx, my);
      });
      ctx.lineTo(pts[pts.length - 1].x, H);
      ctx.closePath();
      ctx.fillStyle = shimFill;
      ctx.fill();

      // Echo line (ghost, slightly offset)
      const echoPts = getPoints(1.1);
      drawCurve(echoPts, `rgba(${rgb},0.1)`, 1.5, null, 0);

      // Main glowing line
      drawCurve(pts, color, 3, color, 14);

      // Bright core line on top
      drawCurve(pts, `rgba(255,255,255,0.55)`, 1, null, 0);

      // Scanning vertical beam
      const scanX = ((t * 25) % W);
      const scanG = ctx.createLinearGradient(scanX - 24, 0, scanX + 24, 0);
      scanG.addColorStop(0, `rgba(${rgb},0)`);
      scanG.addColorStop(0.5, `rgba(${rgb},0.18)`);
      scanG.addColorStop(1, `rgba(${rgb},0)`);
      ctx.fillStyle = scanG;
      ctx.fillRect(scanX - 24, 0, 48, H);

      // Data point nodes — glowing white dots at each data point
      pts.forEach((p, i) => {
        const everyN = Math.max(1, Math.floor(pts.length / 8));
        if (i % everyN !== 0) return;
        const pls = 0.5 + Math.sin(t * 2 + i * 0.6) * 0.35;
        // Outer halo
        const halo = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, 14);
        halo.addColorStop(0, `rgba(${rgb},${pls * 0.35})`);
        halo.addColorStop(1, `rgba(${rgb},0)`);
        ctx.fillStyle = halo;
        ctx.beginPath(); ctx.arc(p.x, p.y, 14, 0, Math.PI * 2); ctx.fill();
        // Core dot
        ctx.fillStyle = `rgba(255,255,255,${0.7 + pls * 0.3})`;
        ctx.shadowColor = color; ctx.shadowBlur = 12;
        ctx.beginPath(); ctx.arc(p.x, p.y, 3.5, 0, Math.PI * 2); ctx.fill();
        ctx.shadowBlur = 0;
        // Value label above peak point
        if (i === values.indexOf(max)) {
          ctx.fillStyle = color;
          ctx.font = `bold ${H * 0.16}px 'Orbitron', monospace`;
          ctx.textAlign = "center";
          ctx.shadowColor = color; ctx.shadowBlur = 8;
          ctx.fillText(values[i], p.x, p.y - 12);
          ctx.shadowBlur = 0;
        }
      });

      raf = requestAnimationFrame(draw);
    }
    draw();
    const onResize = () => { canvas.width = canvas.offsetWidth * 2; canvas.height = height * 2; };
    window.addEventListener("resize", onResize);
    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", onResize); };
  }, [values, color, height]);
  return <canvas ref={canvasRef} style={{ display: "block" }} />;
}

// ── 3D HOLOGRAPHIC BAR CHART ─────────────────────────────────────────────────
function HoloBarChart({ data, activeColor }) {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !data?.length) return;
    const ctx = canvas.getContext("2d");
    const W = canvas.width = canvas.offsetWidth * 2;
    const H = canvas.height = 200 * 2;
    canvas.style.height = "200px";
    const base = activeColor || "#00d4ff";
    const [r0,g0,b0] = base.replace(/rgba?\(|\)/g,"").split(",").map(s => parseInt(s.trim())) || [0,212,255];
    const max = Math.max(...data.map(d => d.revenue), 1);
    let hovIdx = null;
    let t = 0;
    let raf;

    // Isometric projection parameters
    const ISO_ANGLE = Math.PI / 6; // 30deg
    const cosA = Math.cos(ISO_ANGLE), sinA = Math.sin(ISO_ANGLE);
    const barW = (W * 0.72) / data.length;
    const barGap = barW * 0.22;
    const startX = W * 0.14;
    const groundY = H * 0.82;
    const maxBarH = H * 0.55;
    const topDepth = barW * 0.35; // depth of the isometric top face

    function isoProject(x, y, z) {
      // Simple isometric: shift x right for depth (z), shift y up for height
      return { px: x + z * cosA * 0.6, py: y - z * sinA * 0.6 };
    }

    function drawBar3D(x, barH, barW2, col, isHov, month, revenue, idx) {
      const pulse = isHov ? 1.08 + Math.sin(t * 4) * 0.04 : 1;
      const aH = barH * pulse;
      const depth = topDepth;
      const bx = x + barGap / 2;

      // Front face
      const frontGrad = ctx.createLinearGradient(bx, groundY - aH, bx, groundY);
      frontGrad.addColorStop(0, `rgba(${r0},${g0},${b0},${isHov ? 1.0 : 0.85})`);
      frontGrad.addColorStop(0.4, `rgba(${Math.round(r0*0.7)},${Math.round(g0*0.7)},${Math.round(b0*0.7)},0.8)`);
      frontGrad.addColorStop(1, `rgba(${Math.round(r0*0.3)},${Math.round(g0*0.3)},${Math.round(b0*0.3)},0.6)`);
      ctx.fillStyle = frontGrad;
      ctx.shadowColor = col; ctx.shadowBlur = isHov ? 24 : 8;
      ctx.beginPath();
      ctx.moveTo(bx, groundY);
      ctx.lineTo(bx + barW2 - barGap, groundY);
      ctx.lineTo(bx + barW2 - barGap, groundY - aH);
      ctx.lineTo(bx, groundY - aH);
      ctx.closePath();
      ctx.fill();
      ctx.shadowBlur = 0;

      // Front face shine stripe
      const shineGrad = ctx.createLinearGradient(bx, groundY - aH, bx + (barW2-barGap)*0.35, groundY);
      shineGrad.addColorStop(0, "rgba(255,255,255,0.22)");
      shineGrad.addColorStop(1, "rgba(255,255,255,0.03)");
      ctx.fillStyle = shineGrad;
      ctx.beginPath();
      ctx.moveTo(bx, groundY);
      ctx.lineTo(bx + (barW2-barGap)*0.35, groundY);
      ctx.lineTo(bx + (barW2-barGap)*0.35, groundY - aH);
      ctx.lineTo(bx, groundY - aH);
      ctx.closePath();
      ctx.fill();

      // Right side face (darker — gives 3D depth)
      const sideGrad = ctx.createLinearGradient(bx + barW2 - barGap, groundY - aH, bx + barW2 - barGap + depth, groundY - aH + depth * sinA / cosA);
      sideGrad.addColorStop(0, `rgba(${Math.round(r0*0.4)},${Math.round(g0*0.4)},${Math.round(b0*0.4)},0.85)`);
      sideGrad.addColorStop(1, `rgba(${Math.round(r0*0.2)},${Math.round(g0*0.2)},${Math.round(b0*0.2)},0.5)`);
      ctx.fillStyle = sideGrad;
      ctx.beginPath();
      ctx.moveTo(bx + barW2 - barGap, groundY);
      ctx.lineTo(bx + barW2 - barGap + depth, groundY - depth * sinA / cosA);
      ctx.lineTo(bx + barW2 - barGap + depth, groundY - aH - depth * sinA / cosA);
      ctx.lineTo(bx + barW2 - barGap, groundY - aH);
      ctx.closePath();
      ctx.fill();

      // Top face (brightest — facing the light)
      const topGrad = ctx.createLinearGradient(bx, groundY - aH, bx + barW2 - barGap + depth, groundY - aH - depth * sinA / cosA);
      topGrad.addColorStop(0, `rgba(${Math.min(r0+60,255)},${Math.min(g0+60,255)},${Math.min(b0+60,255)},${isHov ? 1.0 : 0.95})`);
      topGrad.addColorStop(1, `rgba(${r0},${g0},${b0},0.8)`);
      ctx.fillStyle = topGrad;
      ctx.shadowColor = col; ctx.shadowBlur = isHov ? 30 : 14;
      ctx.beginPath();
      ctx.moveTo(bx, groundY - aH);
      ctx.lineTo(bx + barW2 - barGap, groundY - aH);
      ctx.lineTo(bx + barW2 - barGap + depth, groundY - aH - depth * sinA / cosA);
      ctx.lineTo(bx + depth, groundY - aH - depth * sinA / cosA);
      ctx.closePath();
      ctx.fill();
      ctx.shadowBlur = 0;

      // Top face specular highlight
      ctx.fillStyle = "rgba(255,255,255,0.18)";
      ctx.beginPath();
      ctx.moveTo(bx + 2, groundY - aH);
      ctx.lineTo(bx + (barW2-barGap)*0.5, groundY - aH);
      ctx.lineTo(bx + (barW2-barGap)*0.5 + depth*0.5, groundY - aH - depth*0.5*sinA/cosA);
      ctx.lineTo(bx + depth*0.5, groundY - aH - depth*0.5*sinA/cosA);
      ctx.closePath();
      ctx.fill();

      // Ground shadow
      ctx.fillStyle = `rgba(0,0,0,0.25)`;
      ctx.beginPath();
      ctx.ellipse(bx + (barW2-barGap)/2, groundY + 4, (barW2-barGap)*0.5, 6, 0, 0, Math.PI*2);
      ctx.fill();

      // Month label
      ctx.save();
      ctx.translate(bx + (barW2-barGap)/2, groundY + 20);
      ctx.rotate(-Math.PI / 5);
      ctx.fillStyle = isHov ? col : `rgba(${r0},${g0},${b0},0.4)`;
      ctx.font = `${isHov ? "bold " : ""}${H * 0.028}px 'Share Tech Mono', monospace`;
      ctx.textAlign = "center";
      ctx.fillText(data[idx].month?.slice(0, 3) || "", 0, 0);
      ctx.restore();

      // Value tooltip on hover
      if (isHov && revenue > 0) {
        const ttW = 160, ttH = 40, ttX = Math.min(bx - 10, W - ttW - 10), ttY = groundY - aH - 60;
        ctx.fillStyle = "rgba(0,8,20,0.98)";
        ctx.strokeStyle = `rgba(${r0},${g0},${b0},0.7)`;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.roundRect(ttX, ttY, ttW, ttH, 4);
        ctx.fill(); ctx.stroke();
        ctx.fillStyle = col;
        ctx.font = `bold ${H * 0.038}px 'Orbitron', monospace`;
        ctx.textAlign = "left";
        ctx.shadowColor = col; ctx.shadowBlur = 10;
        ctx.fillText(`$${revenue.toFixed(0)}`, ttX + 10, ttY + 16);
        ctx.shadowBlur = 0;
        ctx.fillStyle = `rgba(${r0},${g0},${b0},0.5)`;
        ctx.font = `${H * 0.027}px 'Share Tech Mono', monospace`;
        ctx.fillText(`${data[idx].new_paid || 0} paid users`, ttX + 10, ttY + 32);
      }
    }

    function draw() {
      t += 0.02;
      ctx.clearRect(0, 0, W, H);

      // Y-axis grid lines (perspective-ish)
      for (let v = 0; v <= 4; v++) {
        const y = groundY - (v / 4) * maxBarH;
        ctx.strokeStyle = `rgba(${r0},${g0},${b0},0.07)`;
        ctx.lineWidth = 1;
        ctx.setLineDash([4, 8]);
        ctx.beginPath(); ctx.moveTo(startX, y); ctx.lineTo(W - W*0.06, y); ctx.stroke();
        ctx.setLineDash([]);
        if (v > 0) {
          ctx.fillStyle = `rgba(${r0},${g0},${b0},0.3)`;
          ctx.font = `${H * 0.028}px 'Share Tech Mono', monospace`;
          ctx.textAlign = "right";
          ctx.fillText(`$${Math.round(max * v / 4)}`, startX - 6, y + 4);
        }
      }

      // Ground line
      ctx.strokeStyle = `rgba(${r0},${g0},${b0},0.2)`;
      ctx.lineWidth = 1.5; ctx.setLineDash([]);
      ctx.beginPath(); ctx.moveTo(startX, groundY); ctx.lineTo(W - W*0.06, groundY); ctx.stroke();

      // Draw bars back to front
      data.forEach((d, i) => {
        const barH = Math.max(4, (d.revenue / max) * maxBarH);
        const x = startX + i * barW;
        drawBar3D(x, barH, barW, base, hovIdx === i, d.month, d.revenue, i);
      });

      raf = requestAnimationFrame(draw);
    }
    draw();

    const onMouseMove = (e) => {
      const rect = canvas.getBoundingClientRect();
      const mx = (e.clientX - rect.left) * (W / rect.width);
      const my = (e.clientY - rect.top) * (H / rect.height);
      let found = null;
      data.forEach((d, i) => {
        const x = startX + i * barW + barW * 0.1;
        const barH = Math.max(4, (d.revenue / max) * maxBarH);
        if (mx >= x && mx <= x + barW * 0.78 && my >= groundY - barH && my <= groundY) found = i;
      });
      hovIdx = found;
    };
    canvas.addEventListener("mousemove", onMouseMove);
    canvas.addEventListener("mouseleave", () => { hovIdx = null; });

    const onResize = () => {
      canvas.width = canvas.offsetWidth * 2;
      canvas.height = 200 * 2;
    };
    window.addEventListener("resize", onResize);
    return () => { cancelAnimationFrame(raf); canvas.removeEventListener("mousemove", onMouseMove); window.removeEventListener("resize", onResize); };
  }, [data, activeColor]);

  return <canvas ref={canvasRef} style={{ display: "block", width: "100%", cursor: "crosshair" }} />;
}

// ── CIRCULAR RADAR / DONUT ────────────────────────────────────────────────────
function HoloDonut({ segments, total }) {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !segments?.length || !total) return;
    const ctx = canvas.getContext("2d");
    const S = 160;
    canvas.width = canvas.height = S * 2;
    canvas.style.width = canvas.style.height = `${S}px`;
    const cx = S, cy = S, r = S * 0.7, inner = S * 0.46;
    let t = 0, raf;
    let hovSeg = -1;

    // Animate segments in from 0
    let reveal = 0;

    function draw() {
      t += 0.016;
      reveal = Math.min(1, reveal + 0.04);
      ctx.clearRect(0, 0, S * 2, S * 2);

      // Outer ambient halo
      const halo = ctx.createRadialGradient(cx, cy, r * 0.9, cx, cy, r * 1.35);
      halo.addColorStop(0, "rgba(0,212,255,0.06)");
      halo.addColorStop(1, "rgba(0,212,255,0)");
      ctx.fillStyle = halo;
      ctx.beginPath(); ctx.arc(cx, cy, r * 1.35, 0, Math.PI * 2); ctx.fill();

      // Draw segments
      let startAngle = -Math.PI / 2;
      segments.forEach((seg, i) => {
        const fullSlice = (seg.count / total) * Math.PI * 2;
        const slice = fullSlice * reveal;
        const isHov = i === hovSeg;
        const rOuter = isHov ? r + 8 : r;
        const pulse = isHov ? 1 : (0.85 + Math.sin(t * 1.2 + i * 1.3) * 0.08);

        // Segment glow
        ctx.shadowColor = seg.color;
        ctx.shadowBlur = isHov ? 28 : 14;

        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.arc(cx, cy, rOuter * pulse, startAngle, startAngle + slice);
        ctx.closePath();

        const grad = ctx.createRadialGradient(cx, cy, inner, cx, cy, rOuter);
        grad.addColorStop(0, seg.color + "66");
        grad.addColorStop(0.5, seg.color + "aa");
        grad.addColorStop(1, seg.color + "dd");
        ctx.fillStyle = grad;
        ctx.fill();
        ctx.shadowBlur = 0;

        // Segment edge line
        ctx.beginPath();
        ctx.arc(cx, cy, rOuter * pulse - 1, startAngle, startAngle + slice);
        ctx.strokeStyle = `rgba(255,255,255,0.15)`;
        ctx.lineWidth = 1;
        ctx.stroke();

        // Label line + dot for hovered/large segments
        if (isHov || seg.count / total > 0.2) {
          const midAngle = startAngle + slice / 2;
          const lx = cx + Math.cos(midAngle) * (rOuter + 12);
          const ly = cy + Math.sin(midAngle) * (rOuter + 12);
          ctx.fillStyle = seg.color;
          ctx.shadowColor = seg.color; ctx.shadowBlur = 8;
          ctx.beginPath(); ctx.arc(lx, ly, 3, 0, Math.PI * 2); ctx.fill();
          ctx.shadowBlur = 0;
        }

        startAngle += slice + 0.025;
      });

      // Inner cutout fill
      ctx.beginPath(); ctx.arc(cx, cy, inner, 0, Math.PI * 2);
      ctx.fillStyle = "rgba(0,4,16,0.97)"; ctx.fill();

      // Rotating dashed ring just outside inner
      ctx.save();
      ctx.translate(cx, cy); ctx.rotate(t * 0.4);
      ctx.beginPath(); ctx.arc(0, 0, inner + 6, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(0,229,255,0.12)";
      ctx.lineWidth = 1;
      ctx.setLineDash([5, 8]); ctx.stroke();
      ctx.restore();

      // Counter-rotating ring
      ctx.save();
      ctx.translate(cx, cy); ctx.rotate(-t * 0.25);
      ctx.beginPath(); ctx.arc(0, 0, inner + 11, 0, Math.PI * 2);
      ctx.strokeStyle = "rgba(0,255,157,0.08)";
      ctx.lineWidth = 0.8;
      ctx.setLineDash([3, 14]); ctx.stroke();
      ctx.setLineDash([]); ctx.restore();

      // Outer rotating accent arc
      ctx.save();
      ctx.translate(cx, cy); ctx.rotate(t * 0.6);
      ctx.beginPath(); ctx.arc(0, 0, r + 14, -0.3, Math.PI * 0.7);
      ctx.strokeStyle = "rgba(0,229,255,0.2)";
      ctx.lineWidth = 1.5; ctx.setLineDash([]);
      ctx.shadowColor = "#00e5ff"; ctx.shadowBlur = 8;
      ctx.stroke(); ctx.restore();

      // Center value
      ctx.fillStyle = "#ffffff";
      ctx.font = `bold ${S * 0.26}px 'Orbitron', monospace`;
      ctx.textAlign = "center"; ctx.textBaseline = "middle";
      ctx.shadowColor = "#00d4ff"; ctx.shadowBlur = 20 + Math.sin(t * 1.5) * 6;
      ctx.fillText(total, cx, cy - 10);
      ctx.shadowBlur = 0;

      // "TOTAL" label
      ctx.fillStyle = `rgba(0,212,255,${0.4 + Math.sin(t) * 0.1})`;
      ctx.font = `${S * 0.09}px 'Share Tech Mono', monospace`;
      ctx.fillText("TOTAL", cx, cy + S * 0.16);

      // Pulsing center dot
      const dotR = 4 + Math.sin(t * 2) * 1.5;
      ctx.fillStyle = "#00e5ff";
      ctx.shadowColor = "#00e5ff"; ctx.shadowBlur = 16;
      ctx.beginPath(); ctx.arc(cx, cy + S * 0.28, dotR, 0, Math.PI * 2); ctx.fill();
      ctx.shadowBlur = 0;

      raf = requestAnimationFrame(draw);
    }
    draw();

    const onMouse = (e) => {
      const rect = canvas.getBoundingClientRect();
      const mx = (e.clientX - rect.left) * (S * 2 / rect.width) - cx;
      const my = (e.clientY - rect.top) * (S * 2 / rect.height) - cy;
      const dist = Math.sqrt(mx * mx + my * my);
      if (dist < inner || dist > r + 14) { hovSeg = -1; return; }
      const angle = Math.atan2(my, mx) + Math.PI / 2;
      const norm = (angle < 0 ? angle + Math.PI * 2 : angle);
      let start = 0;
      hovSeg = -1;
      segments.forEach((seg, i) => {
        const slice = (seg.count / total) * Math.PI * 2;
        if (norm >= start && norm < start + slice) hovSeg = i;
        start += slice + 0.025;
      });
    };
    canvas.addEventListener("mousemove", onMouse);
    canvas.addEventListener("mouseleave", () => { hovSeg = -1; });

    return () => { cancelAnimationFrame(raf); canvas.removeEventListener("mousemove", onMouse); };
  }, [segments, total]);
  return <canvas ref={canvasRef} style={{ display: "block" }} />;
}

// ── LOADER ────────────────────────────────────────────────────────────────────
function HoloLoader() {
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", padding: "100px 0", gap: 24 }}>
      <div style={{ position: "relative", width: 80, height: 80 }}>
        {[0, 1, 2, 3].map(i => (
          <div key={i} style={{
            position: "absolute", inset: i * 9,
            borderRadius: "50%",
            border: "1px solid transparent",
            borderTop: `1.5px solid ${["#00d4ff", "#00ff88", "#a855f7", "#ffd700"][i]}`,
            borderRight: `1px solid ${["#00d4ff", "#00ff88", "#a855f7", "#ffd700"][i]}22`,
            animation: `spin ${0.8 + i * 0.35}s linear infinite ${i % 2 ? "reverse" : ""}`,
            boxShadow: `0 0 ${18 - i * 2}px ${["rgba(0,212,255,0.5)", "rgba(0,255,136,0.4)", "rgba(168,85,247,0.35)", "rgba(255,215,0,0.3)"][i]}`,
          }} />
        ))}
        <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22, color: "#00d4ff", animation: "pulse-glow 2s infinite", fontFamily: "'Orbitron', monospace", textShadow: "0 0 20px rgba(0,212,255,0.8)" }}>◈</div>
      </div>
      <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 8 }}>
        <div style={{ color: "rgba(0,212,255,0.5)", fontSize: 10, letterSpacing: "0.35em", fontFamily: "'Share Tech Mono', monospace", textTransform: "uppercase", animation: "pulse-glow 2s infinite" }}>
          Initializing Systems…
        </div>
        <div style={{ display: "flex", gap: 6 }}>
          {[0,1,2,3,4].map(i => (
            <div key={i} style={{ width: 3, height: 12, background: "#00d4ff", borderRadius: 2, opacity: 0.3, animation: `pulse-glow 1s ease-in-out ${i * 0.15}s infinite` }} />
          ))}
        </div>
      </div>
    </div>
  );
}

// ── GLASS PANEL — ULTRA DEEP HOLOGRAPHIC CHAMBER ────────────────────────────
function HoloPanel({ children, style = {}, title, accent = "#00e5ff" }) {
  const [hov, setHov] = useState(false);
  const rgb = accent === "#00e5ff" || accent === "#00d4ff" ? "0,229,255"
    : accent === "#00ff9d" || accent === "#00ff88" ? "0,255,157"
    : accent === "#bf5fff" || accent === "#a855f7" ? "191,95,255"
    : accent === "#ffd060" || accent === "#ffd700" ? "255,208,96"
    : "0,229,255";

  const accent2 = accent === "#00e5ff" ? "#00ff9d"
    : accent === "#00ff9d" ? "#bf5fff"
    : accent === "#bf5fff" ? "#00e5ff"
    : accent === "#ffd060" ? "#00e5ff"
    : "#00ff9d";
  const rgb2 = accent2 === "#00ff9d" ? "0,255,157" : accent2 === "#bf5fff" ? "191,95,255" : "0,229,255";

  return (
    <div
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        background: `
          linear-gradient(160deg,
            rgba(0,3,14,0.99) 0%,
            rgba(0,10,26,0.96) 30%,
            rgba(0,6,20,0.98) 60%,
            rgba(0,2,12,0.99) 100%)`,
        border: `1px solid rgba(${rgb},${hov ? 0.35 : 0.2})`,
        borderRadius: 8,
        padding: "26px 28px",
        backdropFilter: "blur(36px) saturate(1.5)",
        boxShadow: hov
          ? `0 0 0 1px rgba(${rgb},0.06),
             0 20px 80px rgba(0,0,0,0.85),
             0 0 60px rgba(${rgb},0.08),
             inset 0 0 60px rgba(${rgb},0.04),
             inset 0 1px 0 rgba(255,255,255,0.07),
             inset 0 0 0 1px rgba(${rgb},0.04)`
          : `0 16px 70px rgba(0,0,0,0.8),
             0 0 0 1px rgba(${rgb},0.03),
             inset 0 0 50px rgba(${rgb},0.03),
             inset 0 1px 0 rgba(255,255,255,0.055)`,
        position: "relative",
        overflow: "hidden",
        clipPath: "polygon(0 0, calc(100% - 16px) 0, 100% 16px, 100% 100%, 16px 100%, 0 calc(100% - 16px))",
        transition: "box-shadow 0.4s, border-color 0.4s",
        ...style,
      }}>

      {/* Glass sheen — triple layer */}
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: "50%", background: "linear-gradient(180deg, rgba(255,255,255,0.06) 0%, rgba(255,255,255,0.02) 50%, rgba(255,255,255,0) 100%)", pointerEvents: "none" }} />
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: "20%", background: "linear-gradient(180deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0) 100%)", pointerEvents: "none" }} />

      {/* PRISMATIC TOP EDGE — dual color sweep */}
      <div style={{
        position: "absolute", top: 0, left: 0, right: 0, height: hov ? 3 : 2,
        background: `linear-gradient(90deg,
          transparent 0%,
          rgba(${rgb},0.5) 10%,
          ${accent} 30%,
          rgba(255,255,255,0.7) 50%,
          ${accent2} 70%,
          rgba(${rgb2},0.5) 90%,
          transparent 100%)`,
        boxShadow: `0 0 16px ${accent}, 0 0 35px rgba(${rgb},0.4), 0 0 70px rgba(${rgb},0.15)`,
        transition: "height 0.3s, box-shadow 0.3s",
        pointerEvents: "none", zIndex: 3,
      }} />

      {/* LEFT ACCENT BAR — double neon rail */}
      <div style={{
        position: "absolute", left: 0, top: 0, bottom: 0, width: 4,
        background: `linear-gradient(180deg,
          ${accent} 0%,
          rgba(${rgb},0.6) 30%,
          ${accent2} 60%,
          rgba(${rgb2},0.2) 85%,
          transparent 100%)`,
        boxShadow: `0 0 20px rgba(${rgb},0.5), 0 0 40px rgba(${rgb},0.2), inset 0 0 6px rgba(255,255,255,0.2)`,
        pointerEvents: "none",
      }} />
      <div style={{
        position: "absolute", left: 5, top: "10%", bottom: "10%", width: 1,
        background: `linear-gradient(180deg, transparent, rgba(${rgb},0.3), rgba(${rgb2},0.15), transparent)`,
        pointerEvents: "none",
      }} />

      {/* RIGHT EDGE — subtle secondary glow */}
      <div style={{
        position: "absolute", right: 0, top: "20%", bottom: "20%", width: 1,
        background: `linear-gradient(180deg, transparent, rgba(${rgb2},0.2), transparent)`,
        pointerEvents: "none",
        opacity: hov ? 1 : 0, transition: "opacity 0.4s",
      }} />

      {/* CORNER NOTCH indicators */}
      <div style={{ position: "absolute", top: 0, right: 16, width: 0, height: 0, borderTop: `16px solid rgba(${rgb},${hov ? 0.5 : 0.28})`, borderLeft: "16px solid transparent", zIndex: 2, transition: "border-color 0.3s" }} />
      <div style={{ position: "absolute", bottom: 0, left: 16, width: 0, height: 0, borderBottom: `16px solid rgba(${rgb},${hov ? 0.35 : 0.18})`, borderRight: "16px solid transparent", zIndex: 2, transition: "border-color 0.3s" }} />

      {/* Corner brackets */}
      <div style={{ position: "absolute", top: 6, left: 6, width: 20, height: 20, borderTop: `2px solid rgba(${rgb},${hov ? 0.8 : 0.35})`, borderLeft: `2px solid rgba(${rgb},${hov ? 0.8 : 0.35})`, boxShadow: hov ? `0 0 12px rgba(${rgb},0.4)` : "none", transition: "all 0.3s", pointerEvents: "none" }} />
      <div style={{ position: "absolute", bottom: 6, right: 6, width: 20, height: 20, borderBottom: `2px solid rgba(${rgb},${hov ? 0.8 : 0.35})`, borderRight: `2px solid rgba(${rgb},${hov ? 0.8 : 0.35})`, boxShadow: hov ? `0 0 12px rgba(${rgb},0.4)` : "none", transition: "all 0.3s", pointerEvents: "none" }} />

      {/* Inner ambient radial glow */}
      <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at 50% 0%, rgba(${rgb},0.07) 0%, transparent 55%), radial-gradient(ellipse at 100% 100%, rgba(${rgb2},0.04) 0%, transparent 50%)`, pointerEvents: "none" }} />

      {/* Animated scan line on hover */}
      {hov && <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, rgba(${rgb},0.5), rgba(255,255,255,0.2), rgba(${rgb},0.5), transparent)`, animation: "scanDown 3s ease-in-out infinite", pointerEvents: "none", zIndex: 2 }} />}

      {/* Bottom glow edge */}
      <div style={{ position: "absolute", bottom: 0, left: 16, right: 0, height: 1, background: `linear-gradient(90deg, rgba(${rgb},0.2), rgba(${rgb2},0.1), transparent)`, pointerEvents: "none" }} />

      {title && (
        <div style={{ fontSize: 10, color: `rgba(${rgb},0.85)`, letterSpacing: "0.28em", textTransform: "uppercase", fontFamily: "'Rajdhani', sans-serif", fontWeight: 600, marginBottom: 20, display: "flex", alignItems: "center", gap: 12, position: "relative", zIndex: 2 }}>
          {/* Animated indicator */}
          <div style={{ position: "relative", width: 10, height: 10 }}>
            <div style={{ position: "absolute", inset: 0, borderRadius: "50%", background: accent, boxShadow: `0 0 16px ${accent}, 0 0 30px rgba(${rgb},0.5)`, animation: "pulse-glow 2s infinite" }} />
            <div style={{ position: "absolute", inset: -3, borderRadius: "50%", border: `1px solid rgba(${rgb},0.3)`, animation: "pulseRing 2s ease-in-out infinite" }} />
          </div>
          <span style={{ textShadow: `0 0 20px rgba(${rgb},0.5)` }}>{title}</span>
          <div style={{ flex: 1, height: 1, background: `linear-gradient(90deg, rgba(${rgb},0.3), rgba(${rgb2},0.1), transparent)` }} />
          <span style={{ fontSize: 7, color: `rgba(${rgb},0.25)`, letterSpacing: "0.2em" }}>■</span>
        </div>
      )}
      <div style={{ position: "relative", zIndex: 2 }}>{children}</div>
    </div>
  );
}

// ── NAV TAB — HOLOGRAPHIC SELECTOR ──────────────────────────────────────────
function NavTab({ label, active, onClick, count, icon, activeColor }) {
  const [hov, setHov] = useState(false);
  const [ripple, setRipple] = useState(false);
  const ac = activeColor || "#00e5ff";
  const acRgb = activeColor ? activeColor.replace("rgb(","").replace(")","") : "0,229,255";

  const handleClick = () => {
    setRipple(true);
    setTimeout(() => setRipple(false), 600);
    onClick();
  };

  return (
    <div onClick={handleClick}
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      style={{
        display: "flex", alignItems: "center", gap: 12,
        padding: "13px 20px 13px 0",
        cursor: "pointer",
        position: "relative",
        transition: "all 0.3s cubic-bezier(0.16,1,0.3,1)",
        marginBottom: 3,
        overflow: "hidden",
      }}>

      {/* Active left glow bar — multi-layer neon */}
      <div style={{
        position: "absolute", left: 0, top: 0, bottom: 0, width: active ? 4 : 0,
        background: `linear-gradient(180deg, transparent 0%, ${ac} 20%, rgba(${acRgb},0.8) 50%, ${ac} 80%, transparent 100%)`,
        boxShadow: active ? `0 0 20px ${ac}, 0 0 40px rgba(${acRgb},0.5), 0 0 80px rgba(${acRgb},0.2)` : "none",
        transition: "all 0.35s cubic-bezier(0.16,1,0.3,1)",
      }} />
      {/* Second thin accent bar */}
      <div style={{
        position: "absolute", left: active ? 5 : 0, top: "25%", bottom: "25%", width: 1,
        background: `linear-gradient(180deg, transparent, rgba(${acRgb},${active ? 0.5 : 0}), transparent)`,
        transition: "all 0.35s",
      }} />

      {/* Full-width hover/active background */}
      <div style={{
        position: "absolute", inset: 0,
        background: active
          ? `linear-gradient(90deg, rgba(${acRgb},0.14) 0%, rgba(${acRgb},0.06) 50%, transparent 100%)`
          : hov ? `linear-gradient(90deg, rgba(${acRgb},0.06) 0%, rgba(${acRgb},0.02) 60%, transparent 100%)` : "transparent",
        transition: "background 0.3s",
      }} />

      {/* Shimmer sweep on hover */}
      {(hov || active) && <div style={{
        position: "absolute", inset: 0,
        background: `linear-gradient(90deg, transparent 0%, rgba(${acRgb},0.06) 40%, rgba(255,255,255,0.03) 50%, transparent 60%)`,
        animation: active ? "shimmerSlide 4s ease-in-out infinite" : "none",
        pointerEvents: "none",
      }} />}

      {/* Active top/bottom hairlines */}
      {active && <>
        <div style={{ position: "absolute", top: 0, left: 4, right: 0, height: 1, background: `linear-gradient(90deg, rgba(${acRgb},0.5), rgba(${acRgb},0.1), transparent)` }} />
        <div style={{ position: "absolute", bottom: 0, left: 4, right: 0, height: 1, background: `linear-gradient(90deg, rgba(${acRgb},0.3), transparent)` }} />
      </>}

      {/* Ripple effect on click */}
      {ripple && <div style={{
        position: "absolute", inset: 0,
        background: `radial-gradient(circle at 50% 50%, rgba(${acRgb},0.2) 0%, transparent 70%)`,
        animation: "rippleOut 0.6s ease-out forwards",
        pointerEvents: "none",
      }} />}

      {/* Content */}
      <div style={{ paddingLeft: 22, display: "flex", alignItems: "center", gap: 12, flex: 1, position: "relative", zIndex: 1 }}>
        {/* Icon with active glow ring */}
        <div style={{ position: "relative", width: 22, height: 22, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
          {active && <div style={{
            position: "absolute", inset: -4, borderRadius: "50%",
            border: `1px solid rgba(${acRgb},0.4)`,
            boxShadow: `0 0 12px rgba(${acRgb},0.3)`,
            animation: "pulseRing 2s ease-in-out infinite",
          }} />}
          <span style={{
            fontSize: 15, color: active ? ac : hov ? `rgba(${acRgb},0.7)` : "rgba(0,212,255,0.28)",
            transition: "color 0.25s, text-shadow 0.25s",
            fontFamily: "'Share Tech Mono', monospace",
            textShadow: active ? `0 0 18px ${ac}, 0 0 40px rgba(${acRgb},0.5)` : hov ? `0 0 10px rgba(${acRgb},0.4)` : "none",
          }}>{icon}</span>
        </div>

        <span style={{
          fontSize: 11, fontWeight: active ? 700 : 400,
          color: active ? "#f0faff" : hov ? "rgba(210,240,255,0.65)" : "rgba(140,190,215,0.38)",
          fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.12em", flex: 1,
          transition: "color 0.25s",
          textShadow: active ? `0 0 20px rgba(${acRgb},0.3)` : "none",
        }}>{label}</span>

        {count !== undefined && (
          <span style={{
            fontSize: 9, color: active ? ac : `rgba(${acRgb},0.3)`,
            background: active ? `rgba(${acRgb},0.15)` : "rgba(0,212,255,0.04)",
            border: `1px solid ${active ? `rgba(${acRgb},0.45)` : "rgba(0,212,255,0.1)"}`,
            padding: "2px 8px", borderRadius: 2,
            fontFamily: "'Orbitron', monospace",
            transition: "all 0.3s",
            boxShadow: active ? `0 0 12px rgba(${acRgb},0.25), inset 0 1px 0 rgba(255,255,255,0.1)` : "none",
            clipPath: "polygon(0 0, calc(100% - 4px) 0, 100% 4px, 100% 100%, 4px 100%, 0 calc(100% - 4px))",
          }}>{count}</span>
        )}
      </div>
    </div>
  );
}

// ── BADGE ────────────────────────────────────────────────────────────────────
function Badge({ text }) {
  const map = {
    open:     { c: "#00ff9d", bg: "rgba(0,255,157,0.08)", b: "rgba(0,255,157,0.28)" },
    closed:   { c: "#00e5ff", bg: "rgba(0,229,255,0.08)", b: "rgba(0,229,255,0.28)" },
    pending:  { c: "#ffd060", bg: "rgba(255,208,96,0.08)",  b: "rgba(255,208,96,0.28)"  },
  };
  const s = map[text] || map.open;
  return (
    <span style={{ fontSize: 8, color: s.c, background: s.bg, border: `1px solid ${s.b}`, padding: "2px 8px", borderRadius: 2, fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.1em", textTransform: "uppercase", boxShadow: `0 0 10px ${s.b}` }}>{text}</span>
  );
}

const td = { padding: "11px 14px", verticalAlign: "middle" };

// ── USERS TABLE ───────────────────────────────────────────────────────────────
// ── AVATAR INITIALS — holographic hex with glow ring ─────────────────────────
function HoloAvatar({ name, email, isActive, isRoot, size = 40 }) {
  const initials = name
    ? name.split(" ").map(w => w[0]).join("").slice(0, 2).toUpperCase()
    : (email?.[0] || "?").toUpperCase();
  // Deterministic hue from name/email string
  const seed = [...(name || email || "X")].reduce((a, c) => a + c.charCodeAt(0), 0);
  const hues = [195, 160, 280, 45, 330, 20];
  const hue = hues[seed % hues.length];
  const color = isRoot ? "#ffd060" : isActive ? `hsl(${hue},100%,60%)` : "rgba(100,160,180,0.4)";
  const colorRgb = isRoot ? "255,208,96" : isActive ? `${Math.round(Math.cos(hue/57)*80+100)},${Math.round(Math.sin(hue/57+1)*80+150)},255` : "80,120,140";
  return (
    <div style={{ position: "relative", width: size, height: size, flexShrink: 0 }}>
      {/* Outer pulse ring */}
      {isActive && (
        <div style={{
          position: "absolute", inset: -3, borderRadius: "50%",
          border: `1px solid rgba(${colorRgb},0.35)`,
          animation: "pulseRing 2.5s ease-in-out infinite",
          pointerEvents: "none",
        }} />
      )}
      {/* Hex avatar body */}
      <div style={{
        width: size, height: size,
        clipPath: "polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)",
        background: isRoot
          ? "radial-gradient(circle at 35% 35%, rgba(255,208,96,0.35) 0%, rgba(255,150,0,0.12) 60%, rgba(0,0,0,0.4) 100%)"
          : isActive
            ? `radial-gradient(circle at 35% 35%, rgba(${colorRgb},0.3) 0%, rgba(${colorRgb},0.1) 60%, rgba(0,0,0,0.5) 100%)`
            : "radial-gradient(circle, rgba(20,40,60,0.6) 0%, rgba(0,0,0,0.5) 100%)",
        border: `1px solid rgba(${colorRgb},${isActive ? 0.5 : 0.15})`,
        display: "flex", alignItems: "center", justifyContent: "center",
        fontSize: size * 0.3, fontWeight: 900,
        color, fontFamily: "'Orbitron', monospace",
        boxShadow: isActive ? `0 0 ${size * 0.5}px rgba(${colorRgb},0.25), inset 0 1px 0 rgba(255,255,255,0.15)` : "none",
        transition: "all 0.3s",
        letterSpacing: "-0.05em",
      }}>{initials}</div>
      {/* Online dot */}
      {isActive && !isRoot && (
        <div style={{
          position: "absolute", bottom: 0, right: 0,
          width: size * 0.22, height: size * 0.22,
          borderRadius: "50%", background: "#00ff9d",
          border: "1.5px solid #000c1e",
          boxShadow: "0 0 6px #00ff9d",
          animation: "pulse-glow 2s infinite",
        }} />
      )}
      {/* Root crown */}
      {isRoot && (
        <div style={{
          position: "absolute", top: -6, left: "50%", transform: "translateX(-50%)",
          fontSize: 8, color: "#ffd060", textShadow: "0 0 8px #ffd060",
          lineHeight: 1,
        }}>♛</div>
      )}
    </div>
  );
}

// ── TIER BADGE ────────────────────────────────────────────────────────────────
function TierBadge({ status }) {
  const cfg = {
    paid:      { label: "PAID",      color: "#00ff9d", rgb: "0,255,157",   icon: "◆" },
    trialing:  { label: "TRIAL",     color: "#ffd060", rgb: "255,208,96",  icon: "◎" },
    cancelled: { label: "CHURNED",   color: "#ff2d55", rgb: "255,45,85",   icon: "✕" },
    exempt:    { label: "EXEMPT",    color: "#bf5fff", rgb: "191,95,255",  icon: "⬡" },
  };
  const c = cfg[status] || { label: status || "—", color: "rgba(0,212,255,0.3)", rgb: "0,212,255", icon: "·" };
  return (
    <div style={{
      display: "inline-flex", alignItems: "center", gap: 4,
      padding: "3px 8px 3px 6px",
      background: `rgba(${c.rgb},0.07)`,
      border: `1px solid rgba(${c.rgb},0.35)`,
      borderRadius: 3,
      clipPath: "polygon(0 0, calc(100% - 5px) 0, 100% 5px, 100% 100%, 5px 100%, 0 calc(100% - 5px))",
      boxShadow: `0 0 10px rgba(${c.rgb},0.12), inset 0 1px 0 rgba(255,255,255,0.05)`,
    }}>
      <span style={{ fontSize: 7, color: c.color, textShadow: `0 0 6px rgba(${c.rgb},0.5)` }}>{c.icon}</span>
      <span style={{ fontSize: 7, fontWeight: 700, color: c.color, letterSpacing: "0.14em", fontFamily: "'Share Tech Mono', monospace" }}>{c.label}</span>
    </div>
  );
}

// ── ROLE CHIP ─────────────────────────────────────────────────────────────────
function RoleChip({ role }) {
  const isAdmin = role === "admin" || role === "owner" || role === "super_admin";
  return (
    <span style={{
      fontSize: 7, fontFamily: "'Share Tech Mono', monospace",
      color: isAdmin ? "#ffd060" : "rgba(0,212,255,0.45)",
      background: isAdmin ? "rgba(255,208,96,0.06)" : "rgba(0,212,255,0.04)",
      border: `1px solid ${isAdmin ? "rgba(255,208,96,0.25)" : "rgba(0,212,255,0.12)"}`,
      padding: "2px 7px", borderRadius: 2, letterSpacing: "0.12em", textTransform: "uppercase",
    }}>{role || "user"}</span>
  );
}

function UsersTable({ showToast, onUserClick }) {
  const { data, loading, refetch } = useAdminFetch("/admin/users?limit=100");
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState("all");
  const [hovRow, setHovRow] = useState(null);
  const [sortCol, setSortCol] = useState("idx");
  const [sortDir, setSortDir] = useState(1);
  // Multi-select state
  const [selected, setSelected] = useState(new Set());
  const [bulkLoading, setBulkLoading] = useState(false);
  const { dark } = useTheme();
  const cyan = dark ? "0,229,255" : "0,120,200";
  const cyanHex = dark ? "#00e5ff" : "#0088cc";

  const handleToggleActive = async (id, cur, name) => {
    const token = localStorage.getItem("access_token");
    await fetch(`${API}/admin/users/${id}`, { method: "PATCH", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ is_active: !cur }) });
    refetch();
    showToast?.(!cur ? `${name || "User"} activated` : `${name || "User"} deactivated`, !cur ? "success" : "warning");
  };

  const handleBulkActivate = async (activate) => {
    if (selected.size === 0) return;
    setBulkLoading(true);
    const token = localStorage.getItem("access_token");
    const ids = [...selected];
    await Promise.all(ids.map(id => fetch(`${API}/admin/users/${id}`, { method: "PATCH", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ is_active: activate }) })));
    setSelected(new Set());
    refetch();
    showToast?.(`${ids.length} agent${ids.length > 1 ? "s" : ""} ${activate ? "activated" : "deactivated"}`, activate ? "success" : "warning");
    setBulkLoading(false);
  };

  const handleBulkExport = () => {
    if (selected.size === 0) return;
    const users = data?.users?.filter(u => selected.has(u.id)) || [];
    const csv = ["id,name,email,role,subscription_status,is_active,created_at",
      ...users.map(u => `${u.id},"${u.name || ""}",${u.email},${u.role || ""},${u.subscription_status || ""},${u.is_active},${u.created_at || ""}`)
    ].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url; a.download = `arcane_users_${selected.size}.csv`; a.click();
    URL.revokeObjectURL(url);
    showToast?.(`Exported ${selected.size} agent records`, "success");
  };

  const toggleSelect = (id) => {
    setSelected(prev => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  };

  const toggleSelectAll = (rows) => {
    const allIds = rows.map(u => u.id);
    const allSelected = allIds.every(id => selected.has(id));
    if (allSelected) setSelected(new Set());
    else setSelected(new Set(allIds));
  };

  if (loading) return <HoloLoader />;

  let rows = data?.users?.filter(u => {
    if (filter === "active" && !u.is_active) return false;
    if (filter === "inactive" && u.is_active) return false;
    if (filter === "paid" && u.subscription_status !== "paid") return false;
    if (filter === "trialing" && u.subscription_status !== "trialing") return false;
    if (search && !u.email?.toLowerCase().includes(search.toLowerCase()) && !u.name?.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  }) || [];

  // Stats strip
  const total = data?.users?.length || 0;
  const paid = data?.users?.filter(u => u.subscription_status === "paid").length || 0;
  const active = data?.users?.filter(u => u.is_active).length || 0;

  const COLS = ["☑", "#", "Identity", "Contact", "Tier", "Role", "Joined", "Control"];

  return (
    <div>
      {/* ── Micro stat strip ── */}
      <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
        {[
          { label: "Total", value: total, color: "#00e5ff", rgb: "0,229,255" },
          { label: "Online", value: active, color: "#00ff9d", rgb: "0,255,157" },
          { label: "Paid", value: paid, color: "#ffd060", rgb: "255,208,96" },
          { label: "Trialing", value: data?.users?.filter(u => u.subscription_status === "trialing").length || 0, color: "#bf5fff", rgb: "191,95,255" },
        ].map(({ label, value, color, rgb }) => (
          <div key={label} style={{
            flex: 1, padding: "10px 14px",
            background: `rgba(${rgb},0.04)`,
            border: `1px solid rgba(${rgb},0.18)`,
            borderRadius: 4,
            clipPath: "polygon(0 0, calc(100% - 8px) 0, 100% 8px, 100% 100%, 0 100%)",
            position: "relative", overflow: "hidden",
          }}>
            <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, rgba(${rgb},0.6), transparent)` }} />
            <div style={{ fontSize: 6, color: `rgba(${rgb},0.5)`, letterSpacing: "0.2em", fontFamily: "'Share Tech Mono', monospace", marginBottom: 4 }}>{label}</div>
            <div style={{ fontSize: 20, fontWeight: 900, color, fontFamily: "'Orbitron', monospace", textShadow: `0 0 14px rgba(${rgb},0.5)` }}>{value}</div>
          </div>
        ))}
      </div>

      {/* ── Search / filter bar ── */}
      <div style={{ display: "flex", gap: 10, marginBottom: 18, alignItems: "center", flexWrap: "wrap" }}>
        <div style={{ flex: 1, minWidth: 200, position: "relative" }}>
          <span style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", fontSize: 10, color: "rgba(0,229,255,0.3)", pointerEvents: "none" }}>◈</span>
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search agents…" className="holo-input" style={{ width: "100%", paddingLeft: 28 }} />
        </div>
        <select value={filter} onChange={e => setFilter(e.target.value)} className="holo-input" style={{ width: 150 }}>
          <option value="all">All Agents</option>
          <option value="active">Online</option>
          <option value="inactive">Offline</option>
          <option value="paid">Paid</option>
          <option value="trialing">Trialing</option>
        </select>
        <div style={{
          fontSize: 8, color: "rgba(0,229,255,0.35)", fontFamily: "'Share Tech Mono', monospace",
          background: "rgba(0,229,255,0.04)", border: "1px solid rgba(0,229,255,0.1)",
          padding: "6px 12px", borderRadius: 3, letterSpacing: "0.12em",
        }}>{rows.length} / {total} AGENTS</div>
      </div>

      {/* ── Bulk action bar — appears when agents are selected ── */}
      <div style={{
        height: selected.size > 0 ? 52 : 0,
        overflow: "hidden",
        transition: "height 0.35s cubic-bezier(0.16,1,0.3,1)",
        marginBottom: selected.size > 0 ? 14 : 0,
      }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 10,
          padding: "10px 14px",
          background: dark
            ? "linear-gradient(90deg, rgba(0,229,255,0.08) 0%, rgba(0,229,255,0.04) 100%)"
            : "linear-gradient(90deg, rgba(0,120,200,0.08) 0%, rgba(0,120,200,0.04) 100%)",
          border: `1px solid rgba(${cyan},0.3)`,
          borderRadius: 5,
          clipPath: "polygon(0 0, calc(100% - 10px) 0, 100% 10px, 100% 100%, 0 100%)",
          boxShadow: dark ? `0 0 30px rgba(${cyan},0.1), inset 0 1px 0 rgba(255,255,255,0.05)` : "none",
          position: "relative",
          overflow: "hidden",
        }}>
          {/* Animated top scan */}
          <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, rgba(${cyan},0.7), rgba(0,255,157,0.4), transparent)` }} />

          {/* Selection count badge */}
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{
              width: 24, height: 24, borderRadius: "50%",
              background: `rgba(${cyan},0.15)`, border: `1px solid rgba(${cyan},0.45)`,
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 10, fontFamily: "'Orbitron', monospace", fontWeight: 700,
              color: cyanHex, boxShadow: `0 0 12px rgba(${cyan},0.3)`,
            }}>{selected.size}</div>
            <span style={{ fontSize: 8, color: `rgba(${cyan},0.65)`, fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.16em" }}>
              AGENT{selected.size !== 1 ? "S" : ""} SELECTED
            </span>
          </div>

          <div style={{ flex: 1, height: 1, background: `rgba(${cyan},0.1)` }} />

          {/* Bulk action buttons */}
          {[
            { label: "⬡ ACTIVATE", action: () => handleBulkActivate(true), col: "#00ff9d", rgb: "0,255,157" },
            { label: "✕ DEACTIVATE", action: () => handleBulkActivate(false), col: "#ff2d55", rgb: "255,45,85" },
            { label: "⇣ EXPORT CSV", action: handleBulkExport, col: "#ffd060", rgb: "255,208,96" },
          ].map(({ label, action, col, rgb }) => (
            <button key={label} onClick={action} disabled={bulkLoading}
              style={{
                display: "flex", alignItems: "center", gap: 5,
                padding: "5px 12px", cursor: "pointer",
                background: `rgba(${rgb},0.06)`,
                border: `1px solid rgba(${rgb},0.3)`,
                borderRadius: 3,
                clipPath: "polygon(0 0, calc(100% - 5px) 0, 100% 5px, 100% 100%, 0 100%)",
                fontSize: 7, color: col, fontFamily: "'Share Tech Mono', monospace",
                letterSpacing: "0.12em", fontWeight: 700,
                boxShadow: `0 0 12px rgba(${rgb},0.12)`,
                transition: "all 0.2s", opacity: bulkLoading ? 0.5 : 1,
              }}
              onMouseEnter={e => { e.currentTarget.style.background = `rgba(${rgb},0.14)`; e.currentTarget.style.boxShadow = `0 0 20px rgba(${rgb},0.25)`; }}
              onMouseLeave={e => { e.currentTarget.style.background = `rgba(${rgb},0.06)`; e.currentTarget.style.boxShadow = `0 0 12px rgba(${rgb},0.12)`; }}
            >{label}</button>
          ))}

          {/* Deselect all */}
          <button onClick={() => setSelected(new Set())}
            style={{
              background: "transparent", border: `1px solid rgba(${cyan},0.2)`,
              borderRadius: 3, padding: "4px 10px", cursor: "pointer",
              fontSize: 7, color: `rgba(${cyan},0.4)`, fontFamily: "'Share Tech Mono', monospace",
              letterSpacing: "0.1em", transition: "all 0.2s",
            }}
            onMouseEnter={e => { e.currentTarget.style.borderColor = `rgba(${cyan},0.5)`; e.currentTarget.style.color = cyanHex; }}
            onMouseLeave={e => { e.currentTarget.style.borderColor = `rgba(${cyan},0.2)`; e.currentTarget.style.color = `rgba(${cyan},0.4)`; }}
          >✕ CLEAR</button>
        </div>
      </div>

      {/* ── Table ── */}
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr>
              {COLS.map(h => (
                <th key={h} onClick={() => {
                  if (h === "☑") { toggleSelectAll(rows); return; }
                  if (h !== "#" && h !== "Control") { setSortCol(h); setSortDir(d => -d); }
                }}
                  style={{
                    padding: "10px 14px", textAlign: "left",
                    color: h === "☑" ? (selected.size > 0 ? cyanHex : "rgba(0,212,255,0.4)") : "rgba(0,212,255,0.5)",
                    fontWeight: 700, fontSize: h === "☑" ? 14 : 7,
                    textTransform: "uppercase", letterSpacing: h === "☑" ? 0 : "0.22em",
                    borderBottom: "1px solid rgba(0,212,255,0.12)",
                    whiteSpace: "nowrap", fontFamily: h === "☑" ? "inherit" : "'Share Tech Mono', monospace",
                    cursor: h !== "#" && h !== "Control" ? "pointer" : "default",
                    background: "linear-gradient(180deg, rgba(0,212,255,0.04) 0%, transparent 100%)",
                    position: "relative",
                    width: h === "☑" ? 36 : "auto",
                    textAlign: h === "☑" ? "center" : "left",
                  }}>
                  {h === "☑" ? (
                    <div style={{
                      width: 16, height: 16, border: `1px solid rgba(${cyan},${selected.size > 0 && rows.every(u => selected.has(u.id)) ? 0.8 : 0.3})`,
                      borderRadius: 3, display: "flex", alignItems: "center", justifyContent: "center",
                      background: selected.size > 0 && rows.every(u => selected.has(u.id)) ? `rgba(${cyan},0.15)` : "transparent",
                      margin: "0 auto", cursor: "pointer",
                      boxShadow: selected.size > 0 ? `0 0 8px rgba(${cyan},0.3)` : "none",
                      transition: "all 0.2s",
                    }}>
                      {selected.size > 0 && rows.every(u => selected.has(u.id)) && (
                        <span style={{ fontSize: 8, color: cyanHex, lineHeight: 1 }}>✓</span>
                      )}
                      {selected.size > 0 && !rows.every(u => selected.has(u.id)) && (
                        <span style={{ width: 8, height: 2, background: cyanHex, display: "block", borderRadius: 1 }} />
                      )}
                    </div>
                  ) : h}
                  {h !== "☑" && <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 1, background: "linear-gradient(90deg, rgba(0,229,255,0.3), transparent)" }} />}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((u, idx) => {
              const isRoot = u.email === "wahaj@acedengroup.com";
              const isHov = hovRow === u.id;
              const accentColor = isRoot ? "#ffd060" : u.is_active ? "#00e5ff" : "rgba(0,150,180,0.4)";
              const accentRgb = isRoot ? "255,208,96" : u.is_active ? "0,229,255" : "0,100,140";
              return (
                <tr key={u.id}
                  onMouseEnter={() => setHovRow(u.id)}
                  onMouseLeave={() => setHovRow(null)}
                  style={{
                    transition: "all 0.2s",
                    background: selected.has(u.id)
                      ? dark ? `rgba(${accentRgb},0.09)` : `rgba(${accentRgb},0.05)`
                      : isHov
                        ? `linear-gradient(90deg, rgba(${accentRgb},0.07) 0%, rgba(${accentRgb},0.03) 60%, transparent 100%)`
                        : "transparent",
                    boxShadow: selected.has(u.id) ? `inset 3px 0 0 rgba(${accentRgb},0.9)` : isHov ? `inset 3px 0 0 rgba(${accentRgb},0.7)` : "none",
                  }}>
                  {/* Checkbox cell */}
                  <td style={{ ...td, paddingLeft: 14, width: 36 }} onClick={e => { e.stopPropagation(); if (!isRoot) toggleSelect(u.id); }}>
                    {!isRoot && (
                      <div style={{
                        width: 14, height: 14, border: `1px solid rgba(${accentRgb},${selected.has(u.id) ? 0.8 : 0.25})`,
                        borderRadius: 2, display: "flex", alignItems: "center", justifyContent: "center",
                        background: selected.has(u.id) ? `rgba(${accentRgb},0.15)` : "transparent",
                        cursor: "pointer", transition: "all 0.15s",
                        boxShadow: selected.has(u.id) ? `0 0 8px rgba(${accentRgb},0.35)` : "none",
                      }}>
                        {selected.has(u.id) && <span style={{ fontSize: 7, color: accentColor, lineHeight: 1 }}>✓</span>}
                      </div>
                    )}
                  </td>
                  {/* Row number */}
                  <td style={{ ...td, color: "rgba(0,212,255,0.2)", fontSize: 8, fontFamily: "'Share Tech Mono', monospace", paddingLeft: 18 }}>
                    {String(idx + 1).padStart(3, "0")}
                  </td>
                  {/* Identity — avatar + name */}
                  <td style={{ ...td, minWidth: 180, cursor: onUserClick ? "pointer" : "default" }} onClick={() => onUserClick?.(u)}>
                    <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                      <HoloAvatar name={u.name} email={u.email} isActive={u.is_active} isRoot={isRoot} size={38} />
                      <div>
                        <div style={{
                          color: u.is_active ? "#e8f6ff" : "rgba(140,190,210,0.4)",
                          fontFamily: "'Rajdhani', sans-serif", fontSize: 13, fontWeight: 600,
                          letterSpacing: "0.04em",
                          textShadow: isHov && u.is_active ? `0 0 12px rgba(${accentRgb},0.4)` : "none",
                          transition: "text-shadow 0.2s",
                        }}>{u.name || "Unknown Agent"}</div>
                        {isRoot && (
                          <div style={{ fontSize: 7, color: "#ffd060", letterSpacing: "0.18em", fontFamily: "'Share Tech Mono', monospace", textShadow: "0 0 8px rgba(255,208,96,0.5)" }}>ROOT ADMINISTRATOR</div>
                        )}
                        {onUserClick && <div style={{ fontSize: 6, color: "rgba(0,229,255,0.25)", letterSpacing: "0.14em", fontFamily: "'Share Tech Mono', monospace", marginTop: 1 }}>CLICK TO INSPECT</div>}
                      </div>
                    </div>
                  </td>
                  {/* Email */}
                  <td style={{ ...td, maxWidth: 220 }}>
                    <div style={{
                      color: "rgba(0,212,255,0.5)", fontSize: 10,
                      fontFamily: "'Share Tech Mono', monospace",
                      overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                      letterSpacing: "0.02em",
                    }}>{u.email}</div>
                  </td>
                  {/* Tier badge */}
                  <td style={td}>
                    <TierBadge status={u.subscription_status} />
                  </td>
                  {/* Role chip */}
                  <td style={td}>
                    <RoleChip role={u.role} />
                  </td>
                  {/* Joined */}
                  <td style={{ ...td, color: "rgba(0,212,255,0.28)", fontSize: 9, fontFamily: "'Share Tech Mono', monospace", whiteSpace: "nowrap" }}>
                    {u.created_at ? new Date(u.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "2-digit" }) : "—"}
                  </td>
                  {/* Control */}
                  <td style={td}>
                    {isRoot ? (
                      <div style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "3px 10px", background: "rgba(255,208,96,0.06)", border: "1px solid rgba(255,208,96,0.3)", borderRadius: 3, fontSize: 7, color: "#ffd060", fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.12em", boxShadow: "0 0 14px rgba(255,208,96,0.15)" }}>
                        ♛ PROTECTED
                      </div>
                    ) : (
                      <button onClick={() => handleToggleActive(u.id, u.is_active, u.name)}
                        style={{
                          display: "inline-flex", alignItems: "center", gap: 6,
                          fontSize: 7, fontWeight: 700, padding: "5px 12px",
                          border: "none", cursor: "pointer",
                          fontFamily: "'Share Tech Mono', monospace",
                          letterSpacing: "0.12em",
                          background: u.is_active
                            ? "linear-gradient(135deg, rgba(0,255,157,0.1) 0%, rgba(0,255,157,0.04) 100%)"
                            : "linear-gradient(135deg, rgba(255,45,85,0.1) 0%, rgba(255,45,85,0.04) 100%)",
                          color: u.is_active ? "#00ff9d" : "#ff2d55",
                          border: `1px solid ${u.is_active ? "rgba(0,255,157,0.4)" : "rgba(255,45,85,0.4)"}`,
                          borderRadius: 3,
                          clipPath: "polygon(0 0, calc(100% - 6px) 0, 100% 6px, 100% 100%, 0 100%)",
                          boxShadow: u.is_active
                            ? "0 0 14px rgba(0,255,157,0.15), inset 0 1px 0 rgba(255,255,255,0.07)"
                            : "0 0 14px rgba(255,45,85,0.15), inset 0 1px 0 rgba(255,255,255,0.07)",
                          transition: "all 0.2s",
                        }}
                        onMouseEnter={e => { e.currentTarget.style.transform = "scale(1.05)"; }}
                        onMouseLeave={e => { e.currentTarget.style.transform = "scale(1)"; }}
                      >
                        <div style={{ width: 5, height: 5, borderRadius: "50%", background: "currentColor", boxShadow: "0 0 6px currentColor", animation: u.is_active ? "pulse-glow 1.5s infinite" : "none" }} />
                        {u.is_active ? "ONLINE" : "OFFLINE"}
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {rows.length === 0 && (
          <div style={{ textAlign: "center", padding: "60px 0", color: "rgba(0,212,255,0.2)", fontFamily: "'Share Tech Mono', monospace", fontSize: 10, letterSpacing: "0.2em" }}>
            NO AGENTS MATCH QUERY
          </div>
        )}
      </div>
    </div>
  );
}

// ── WORKSPACE HEALTH INDICATOR ────────────────────────────────────────────────
function WorkspaceHealthBar({ members, tasks, isActive }) {
  const memberScore = Math.min(members / 20, 1);
  const taskScore = Math.min(tasks / 50, 1);
  const health = isActive ? Math.round((memberScore * 0.4 + taskScore * 0.6) * 100) : 0;
  const color = !isActive ? "#ff2d55" : health > 70 ? "#00ff9d" : health > 35 ? "#ffd060" : "#ff6b35";
  const rgb = !isActive ? "255,45,85" : health > 70 ? "0,255,157" : health > 35 ? "255,208,96" : "255,107,53";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, minWidth: 90 }}>
      <div style={{ flex: 1, height: 3, background: "rgba(0,0,0,0.3)", borderRadius: 2, overflow: "hidden", border: `1px solid rgba(${rgb},0.15)` }}>
        <div style={{
          height: "100%", width: `${health}%`,
          background: `linear-gradient(90deg, ${color}60, ${color})`,
          borderRadius: 2, boxShadow: `0 0 6px rgba(${rgb},0.5)`,
          transition: "width 1s cubic-bezier(0.4,0,0.2,1)",
        }} />
      </div>
      <span style={{ fontSize: 7, color, fontFamily: "'Orbitron', monospace", fontWeight: 700, minWidth: 26, textAlign: "right", letterSpacing: "0.04em", textShadow: `0 0 8px rgba(${rgb},0.4)` }}>{health}%</span>
    </div>
  );
}

function WorkspacesTable({ showToast }) {
  const { data, loading, refetch } = useAdminFetch("/admin/workspaces?limit=100");
  const [hovRow, setHovRow] = useState(null);
  const [search, setSearch] = useState("");

  const handleToggle = async (wsId, cur, name) => {
    const token = localStorage.getItem("access_token");
    await fetch(`${API}/admin/workspaces/${wsId}`, { method: "PATCH", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ is_active: !cur }) });
    refetch();
    showToast?.(!cur ? `${name} activated` : `${name} suspended`, !cur ? "success" : "warning");
  };

  if (loading) return <HoloLoader />;

  const allWs = data?.workspaces || [];
  const rows = search
    ? allWs.filter(ws => ws.name?.toLowerCase().includes(search.toLowerCase()) || ws.owner_email?.toLowerCase().includes(search.toLowerCase()))
    : allWs;

  const activeCount = allWs.filter(ws => ws.is_active !== false).length;
  const totalMembers = allWs.reduce((a, ws) => a + (ws.member_count || 0), 0);
  const totalTasks = allWs.reduce((a, ws) => a + (ws.task_count || 0), 0);

  return (
    <div>
      {/* ── Workspace stat strip ── */}
      <div style={{ display: "flex", gap: 8, marginBottom: 18 }}>
        {[
          { label: "Workspaces", value: allWs.length, color: "#bf5fff", rgb: "191,95,255" },
          { label: "Active", value: activeCount, color: "#00ff9d", rgb: "0,255,157" },
          { label: "Members", value: totalMembers, color: "#00e5ff", rgb: "0,229,255" },
          { label: "Tasks", value: totalTasks, color: "#ffd060", rgb: "255,208,96" },
        ].map(({ label, value, color, rgb }) => (
          <div key={label} style={{
            flex: 1, padding: "10px 14px",
            background: `rgba(${rgb},0.04)`,
            border: `1px solid rgba(${rgb},0.18)`,
            borderRadius: 4,
            clipPath: "polygon(0 0, calc(100% - 8px) 0, 100% 8px, 100% 100%, 0 100%)",
            position: "relative", overflow: "hidden",
          }}>
            <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, rgba(${rgb},0.6), transparent)` }} />
            <div style={{ fontSize: 6, color: `rgba(${rgb},0.5)`, letterSpacing: "0.2em", fontFamily: "'Share Tech Mono', monospace", marginBottom: 4 }}>{label}</div>
            <div style={{ fontSize: 20, fontWeight: 900, color, fontFamily: "'Orbitron', monospace", textShadow: `0 0 14px rgba(${rgb},0.5)` }}>{value}</div>
          </div>
        ))}
      </div>

      {/* ── Search ── */}
      <div style={{ display: "flex", gap: 10, marginBottom: 16, alignItems: "center" }}>
        <div style={{ flex: 1, position: "relative" }}>
          <span style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", fontSize: 10, color: "rgba(191,95,255,0.4)", pointerEvents: "none" }}>⊞</span>
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search workspaces…" className="holo-input" style={{ width: "100%", paddingLeft: 28 }} />
        </div>
        <div style={{ fontSize: 8, color: "rgba(191,95,255,0.35)", fontFamily: "'Share Tech Mono', monospace", padding: "6px 12px", background: "rgba(191,95,255,0.04)", border: "1px solid rgba(191,95,255,0.12)", borderRadius: 3 }}>
          {rows.length} / {allWs.length} NODES
        </div>
      </div>

      {/* ── Table ── */}
      <div style={{ overflowX: "auto" }}>
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 12 }}>
          <thead>
            <tr>
              {["#", "Node", "Commander", "Members", "Tasks", "Health", "Created", "Control"].map(h => (
                <th key={h} style={{
                  padding: "10px 14px", textAlign: "left",
                  color: "rgba(191,95,255,0.5)", fontWeight: 700, fontSize: 7,
                  textTransform: "uppercase", letterSpacing: "0.2em",
                  borderBottom: "1px solid rgba(191,95,255,0.12)",
                  whiteSpace: "nowrap", fontFamily: "'Share Tech Mono', monospace",
                  background: "linear-gradient(180deg, rgba(191,95,255,0.04) 0%, transparent 100%)",
                  position: "relative",
                }}>
                  {h}
                  <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 1, background: "linear-gradient(90deg, rgba(191,95,255,0.3), transparent)" }} />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((ws, idx) => {
              const isActive = ws.is_active !== false;
              const isProtected = ws.owner_email === "wahaj@acedengroup.com";
              const isHov = hovRow === ws.id;
              const accentRgb = isActive ? "191,95,255" : "100,60,120";
              const wsInitial = ws.name?.[0]?.toUpperCase() || "W";
              return (
                <tr key={ws.id}
                  onMouseEnter={() => setHovRow(ws.id)}
                  onMouseLeave={() => setHovRow(null)}
                  style={{
                    transition: "all 0.2s",
                    background: isHov
                      ? `linear-gradient(90deg, rgba(${accentRgb},0.08) 0%, rgba(${accentRgb},0.03) 60%, transparent 100%)`
                      : "transparent",
                    boxShadow: isHov ? `inset 3px 0 0 rgba(${accentRgb},0.6)` : "none",
                  }}>
                  <td style={{ ...td, color: "rgba(191,95,255,0.2)", fontSize: 8, fontFamily: "'Share Tech Mono', monospace", paddingLeft: 18 }}>
                    {String(idx + 1).padStart(3, "0")}
                  </td>
                  {/* Workspace identity */}
                  <td style={{ ...td, minWidth: 160 }}>
                    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                      {/* Workspace icon */}
                      <div style={{
                        width: 34, height: 34, flexShrink: 0,
                        clipPath: "polygon(0 0, calc(100% - 6px) 0, 100% 6px, 100% 100%, 6px 100%, 0 calc(100% - 6px))",
                        background: isActive
                          ? "radial-gradient(circle at 35% 35%, rgba(191,95,255,0.35) 0%, rgba(120,40,200,0.12) 100%)"
                          : "radial-gradient(circle, rgba(50,20,80,0.5) 0%, rgba(0,0,0,0.4) 100%)",
                        border: `1px solid rgba(${accentRgb},${isActive ? 0.4 : 0.15})`,
                        display: "flex", alignItems: "center", justifyContent: "center",
                        fontSize: 11, fontWeight: 900,
                        color: isActive ? "#bf5fff" : "rgba(191,95,255,0.3)",
                        fontFamily: "'Orbitron', monospace",
                        boxShadow: isActive ? "0 0 16px rgba(191,95,255,0.2)" : "none",
                      }}>{wsInitial}</div>
                      <div>
                        <div style={{
                          color: isActive ? "#ecdaff" : "rgba(180,140,220,0.35)",
                          fontFamily: "'Rajdhani', sans-serif", fontSize: 13, fontWeight: 600,
                          textShadow: isHov && isActive ? "0 0 12px rgba(191,95,255,0.4)" : "none",
                          transition: "text-shadow 0.2s",
                        }}>{ws.name}</div>
                        {isProtected && <div style={{ fontSize: 7, color: "#ffd060", letterSpacing: "0.16em", fontFamily: "'Share Tech Mono', monospace" }}>PROTECTED NODE</div>}
                      </div>
                    </div>
                  </td>
                  {/* Owner */}
                  <td style={{ ...td, color: "rgba(191,95,255,0.4)", fontSize: 9, fontFamily: "'Share Tech Mono', monospace", maxWidth: 180, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                    {ws.owner_email ?? "—"}
                  </td>
                  {/* Members */}
                  <td style={td}>
                    <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                      <span style={{ fontSize: 16, fontWeight: 900, color: "#00e5ff", fontFamily: "'Orbitron', monospace", textShadow: "0 0 10px rgba(0,229,255,0.5)", lineHeight: 1 }}>{ws.member_count}</span>
                      <span style={{ fontSize: 7, color: "rgba(0,229,255,0.25)", fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.1em" }}>AGT</span>
                    </div>
                  </td>
                  {/* Tasks */}
                  <td style={td}>
                    <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
                      <span style={{ fontSize: 16, fontWeight: 900, color: "#00ff9d", fontFamily: "'Orbitron', monospace", textShadow: "0 0 10px rgba(0,255,157,0.5)", lineHeight: 1 }}>{ws.task_count}</span>
                      <span style={{ fontSize: 7, color: "rgba(0,255,157,0.25)", fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.1em" }}>OPS</span>
                    </div>
                  </td>
                  {/* Health bar */}
                  <td style={{ ...td, minWidth: 110 }}>
                    <WorkspaceHealthBar members={ws.member_count || 0} tasks={ws.task_count || 0} isActive={isActive} />
                  </td>
                  {/* Created */}
                  <td style={{ ...td, color: "rgba(191,95,255,0.28)", fontSize: 9, fontFamily: "'Share Tech Mono', monospace", whiteSpace: "nowrap" }}>
                    {ws.created_at ? new Date(ws.created_at).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "2-digit" }) : "—"}
                  </td>
                  {/* Control */}
                  <td style={td}>
                    {isProtected ? (
                      <div style={{ display: "inline-flex", alignItems: "center", gap: 5, padding: "3px 10px", background: "rgba(255,208,96,0.06)", border: "1px solid rgba(255,208,96,0.3)", borderRadius: 3, fontSize: 7, color: "#ffd060", fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.12em" }}>
                        ♛ PROTECTED
                      </div>
                    ) : (
                      <button onClick={() => handleToggle(ws.id, isActive, ws.name)}
                        style={{
                          display: "inline-flex", alignItems: "center", gap: 6,
                          fontSize: 7, fontWeight: 700, padding: "5px 12px",
                          cursor: "pointer", fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.12em",
                          background: isActive
                            ? "linear-gradient(135deg, rgba(191,95,255,0.12) 0%, rgba(191,95,255,0.04) 100%)"
                            : "linear-gradient(135deg, rgba(255,45,85,0.1) 0%, rgba(255,45,85,0.04) 100%)",
                          color: isActive ? "#bf5fff" : "#ff2d55",
                          border: `1px solid ${isActive ? "rgba(191,95,255,0.4)" : "rgba(255,45,85,0.4)"}`,
                          borderRadius: 3,
                          clipPath: "polygon(0 0, calc(100% - 6px) 0, 100% 6px, 100% 100%, 0 100%)",
                          boxShadow: isActive
                            ? "0 0 14px rgba(191,95,255,0.15)"
                            : "0 0 14px rgba(255,45,85,0.15)",
                          transition: "all 0.2s",
                        }}
                        onMouseEnter={e => { e.currentTarget.style.transform = "scale(1.05)"; }}
                        onMouseLeave={e => { e.currentTarget.style.transform = "scale(1)"; }}
                      >
                        <div style={{ width: 5, height: 5, borderRadius: "50%", background: "currentColor", animation: isActive ? "pulse-glow 1.5s infinite" : "none" }} />
                        {isActive ? "ACTIVE" : "HALTED"}
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Footer count */}
      <div style={{ marginTop: 14, display: "flex", alignItems: "center", gap: 8, fontSize: 9, color: "rgba(191,95,255,0.35)", fontFamily: "'Share Tech Mono', monospace" }}>
        <div style={{ width: 5, height: 5, borderRadius: "50%", background: "#bf5fff", boxShadow: "0 0 8px #bf5fff", animation: "pulse-glow 2s infinite" }} />
        <span style={{ color: "#bf5fff", fontFamily: "'Orbitron', monospace", fontWeight: 700, textShadow: "0 0 10px rgba(191,95,255,0.5)" }}>{data?.total}</span>
        <span>workspace nodes indexed in network</span>
      </div>
    </div>
  );
}

// ── FEEDBACK ──────────────────────────────────────────────────────────────────
// ── SENTIMENT ENGINE — derives signal from text ───────────────────────────────
function getSentiment(text = "") {
  const t = text.toLowerCase();
  const positive = ["great","love","excellent","amazing","awesome","perfect","fantastic","helpful","thanks","good","nice","works","fixed","fast"].filter(w => t.includes(w)).length;
  const negative = ["broken","bug","crash","error","fail","issue","problem","terrible","awful","wrong","doesn't","doesn't","not working","slow","bad"].filter(w => t.includes(w)).length;
  const urgency = ["urgent","asap","critical","immediately","please fix","cannot","blocked"].filter(w => t.includes(w)).length;
  if (urgency > 0) return { label: "URGENT", color: "#ff2d55", rgb: "255,45,85", score: -2, icon: "🔴", bar: 0.1 };
  if (negative > positive + 1) return { label: "NEGATIVE", color: "#ff6b35", rgb: "255,107,53", score: -1, icon: "🟠", bar: 0.2 + negative * 0.05 };
  if (positive > negative + 1) return { label: "POSITIVE", color: "#00ff9d", rgb: "0,255,157", score: 1, icon: "🟢", bar: 0.7 + positive * 0.04 };
  return { label: "NEUTRAL", color: "#00e5ff", rgb: "0,229,255", score: 0, icon: "🔵", bar: 0.5 };
}

// ── SENTIMENT WAVE — mini animated waveform showing signal mood ───────────────
function SentimentWave({ sentiment }) {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const W = canvas.width = 80, H = canvas.height = 24;
    const [r, g, b] = sentiment.rgb.split(",").map(Number);
    let t = 0, raf;
    const amp = sentiment.score >= 0 ? 6 + sentiment.score * 2 : 8 - sentiment.score;
    const freq = sentiment.score >= 1 ? 0.5 : sentiment.score <= -1 ? 1.2 : 0.7;
    function draw() {
      t += 0.04;
      ctx.clearRect(0, 0, W, H);
      const pts = Array.from({ length: W }, (_, x) => ({
        x, y: H / 2 + Math.sin((x / W) * Math.PI * 4 * freq + t) * amp * (0.7 + 0.3 * Math.sin(t * 0.5 + x * 0.1)),
      }));
      const grad = ctx.createLinearGradient(0, 0, 0, H);
      grad.addColorStop(0, `rgba(${r},${g},${b},0.25)`);
      grad.addColorStop(1, `rgba(${r},${g},${b},0)`);
      ctx.beginPath();
      ctx.moveTo(0, H);
      pts.forEach(p => ctx.lineTo(p.x, p.y));
      ctx.lineTo(W, H);
      ctx.closePath();
      ctx.fillStyle = grad;
      ctx.fill();
      ctx.beginPath();
      pts.forEach((p, i) => i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y));
      ctx.strokeStyle = `rgba(${r},${g},${b},0.7)`;
      ctx.lineWidth = 1.5;
      ctx.shadowColor = sentiment.color;
      ctx.shadowBlur = 5;
      ctx.stroke();
      ctx.shadowBlur = 0;
      raf = requestAnimationFrame(draw);
    }
    draw();
    return () => cancelAnimationFrame(raf);
  }, [sentiment]);
  return <canvas ref={canvasRef} style={{ display: "block" }} />;
}

// ── FEEDBACK TRANSMISSION CARD — full holographic redesign ───────────────────
function FeedbackCard({ f, isExpanded, onToggle }) {
  const [hov, setHov] = useState(false);
  const typeStyle = {
    bug:             { c: "#ff2d55", rgb: "255,45,85",   icon: "⚠", label: "BUG REPORT" },
    feedback:        { c: "#00d4ff", rgb: "0,212,255",   icon: "◈", label: "FEEDBACK"   },
    feature_request: { c: "#00ff9d", rgb: "0,255,157",   icon: "◆", label: "FEATURE REQ"},
  };
  const ts = typeStyle[f.type] || { c: "#00d4ff", rgb: "0,212,255", icon: "•", label: f.type || "MISC" };
  const sentiment = getSentiment((f.title || "") + " " + (f.message || ""));
  const statusCfg = {
    open:    { c: "#00ff9d", label: "OPEN"    },
    closed:  { c: "#00e5ff", label: "CLOSED"  },
    pending: { c: "#ffd060", label: "PENDING" },
  }[f.status] || { c: "#00e5ff", label: f.status || "OPEN" };

  const timeAgo = (dateStr) => {
    if (!dateStr) return "—";
    const diff = Date.now() - new Date(dateStr).getTime();
    const d = Math.floor(diff / 86400000);
    const h = Math.floor((diff % 86400000) / 3600000);
    const m = Math.floor((diff % 3600000) / 60000);
    if (d > 0) return `${d}d ago`;
    if (h > 0) return `${h}h ago`;
    return `${m}m ago`;
  };

  return (
    <div
      onMouseEnter={() => setHov(true)}
      onMouseLeave={() => setHov(false)}
      onClick={onToggle}
      style={{
        position: "relative", overflow: "hidden",
        background: hov || isExpanded
          ? `linear-gradient(160deg, rgba(0,6,22,0.99) 0%, rgba(0,12,30,0.97) 50%, rgba(0,5,18,0.99) 100%)`
          : `linear-gradient(160deg, rgba(0,4,18,0.99) 0%, rgba(0,9,24,0.96) 50%, rgba(0,4,16,0.98) 100%)`,
        border: `1px solid rgba(${ts.rgb},${hov || isExpanded ? 0.35 : 0.15})`,
        borderRadius: 8,
        clipPath: "polygon(0 0, calc(100% - 20px) 0, 100% 20px, 100% 100%, 20px 100%, 0 calc(100% - 20px))",
        boxShadow: hov || isExpanded
          ? `0 0 0 1px rgba(${ts.rgb},0.06), 0 20px 70px rgba(0,0,0,0.8), 0 0 50px rgba(${ts.rgb},0.08), inset 0 1px 0 rgba(255,255,255,0.07)`
          : `0 8px 40px rgba(0,0,0,0.65), inset 0 1px 0 rgba(255,255,255,0.04)`,
        transition: "all 0.35s cubic-bezier(0.16,1,0.3,1)",
        cursor: "pointer",
        marginBottom: 2,
      }}>

      {/* Prismatic top bar */}
      <div style={{
        position: "absolute", top: 0, left: 0, right: 0, height: hov || isExpanded ? 2 : 1,
        background: `linear-gradient(90deg, transparent 0%, rgba(${ts.rgb},0.8) 20%, ${ts.c} 50%, rgba(${ts.rgb},0.5) 80%, transparent 100%)`,
        boxShadow: hov || isExpanded ? `0 0 14px rgba(${ts.rgb},0.5)` : "none",
        transition: "all 0.3s",
      }} />
      {/* Left accent bar — thick, matches type color */}
      <div style={{
        position: "absolute", left: 0, top: 0, bottom: 0, width: hov || isExpanded ? 4 : 3,
        background: `linear-gradient(180deg, ${ts.c} 0%, rgba(${ts.rgb},0.5) 50%, rgba(${ts.rgb},0.2) 100%)`,
        boxShadow: hov || isExpanded ? `0 0 18px rgba(${ts.rgb},0.4)` : "none",
        transition: "all 0.3s",
      }} />
      {/* Corner cut */}
      <div style={{ position: "absolute", top: 0, right: 20, width: 0, height: 0, borderTop: `20px solid rgba(${ts.rgb},${hov ? 0.45 : 0.2})`, borderLeft: "20px solid transparent", transition: "border-color 0.3s" }} />
      {/* Bottom corner */}
      <div style={{ position: "absolute", bottom: 0, left: 20, width: 0, height: 0, borderBottom: `12px solid rgba(${ts.rgb},${hov ? 0.3 : 0.1})`, borderRight: "12px solid transparent", transition: "border-color 0.3s" }} />
      {/* Glass sheen */}
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: "45%", background: "linear-gradient(180deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0) 100%)", pointerEvents: "none" }} />
      {/* Scan sweep on hover */}
      {(hov || isExpanded) && <div style={{ position: "absolute", inset: 0, left: "-100%", width: "60%", background: `linear-gradient(90deg, transparent, rgba(${ts.rgb},0.03), transparent)`, animation: "shimmerSlide 3s ease-in-out infinite", pointerEvents: "none" }} />}
      {/* Ambient inner glow */}
      <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at 0% 50%, rgba(${ts.rgb},0.05) 0%, transparent 50%)`, pointerEvents: "none" }} />

      {/* ── CARD CONTENT ── */}
      <div style={{ padding: "18px 22px 16px 26px", position: "relative", zIndex: 2 }}>

        {/* Top row — type badge + title + sentiment + status + time */}
        <div style={{ display: "flex", alignItems: "flex-start", gap: 12, marginBottom: 12, flexWrap: "wrap" }}>

          {/* Type badge */}
          <div style={{
            display: "inline-flex", alignItems: "center", gap: 5,
            padding: "4px 10px 4px 8px",
            background: `rgba(${ts.rgb},0.08)`,
            border: `1px solid rgba(${ts.rgb},0.35)`,
            borderRadius: 3,
            clipPath: "polygon(0 0, calc(100% - 6px) 0, 100% 6px, 100% 100%, 0 100%)",
            flexShrink: 0,
            boxShadow: `0 0 10px rgba(${ts.rgb},0.1)`,
          }}>
            <span style={{ fontSize: 9, color: ts.c, textShadow: `0 0 8px rgba(${ts.rgb},0.6)` }}>{ts.icon}</span>
            <span style={{ fontSize: 7, fontWeight: 700, color: ts.c, letterSpacing: "0.14em", fontFamily: "'Share Tech Mono', monospace" }}>{ts.label}</span>
          </div>

          {/* Title */}
          <div style={{ flex: 1, fontSize: 13, fontWeight: 600, color: hov || isExpanded ? "#f0faff" : "#c8e8f8", fontFamily: "'Rajdhani', sans-serif", letterSpacing: "0.04em", lineHeight: 1.3, transition: "color 0.2s", minWidth: 0 }}>
            {f.title || "Untitled Transmission"}
          </div>

          {/* Sentiment signal */}
          <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
            <div style={{ width: 80, overflow: "hidden" }}>
              <SentimentWave sentiment={sentiment} />
            </div>
            <div style={{
              fontSize: 6, fontWeight: 700, color: sentiment.color,
              fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.1em",
              textShadow: `0 0 8px rgba(${sentiment.rgb},0.5)`,
              minWidth: 44, textAlign: "center",
            }}>{sentiment.label}</div>
          </div>

          {/* Status badge */}
          <div style={{
            display: "inline-flex", alignItems: "center", gap: 5,
            padding: "3px 9px", borderRadius: 3,
            background: `rgba(${statusCfg.c.replace("#","").match(/../g)?.map(h=>parseInt(h,16)).join(",")||"0,229,255"},0.07)`,
            border: `1px solid rgba(${statusCfg.c.replace("#","").match(/../g)?.map(h=>parseInt(h,16)).join(",")||"0,229,255"},0.35)`,
            flexShrink: 0,
          }}>
            <div style={{ width: 4, height: 4, borderRadius: "50%", background: statusCfg.c, boxShadow: `0 0 6px ${statusCfg.c}`, animation: f.status === "open" ? "pulse-glow 1.5s infinite" : "none" }} />
            <span style={{ fontSize: 7, color: statusCfg.c, fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.12em" }}>{statusCfg.label}</span>
          </div>

          {/* Expand indicator */}
          <div style={{ fontSize: 10, color: `rgba(${ts.rgb},0.4)`, transition: "transform 0.3s, color 0.3s", transform: isExpanded ? "rotate(180deg)" : "rotate(0deg)", color: hov || isExpanded ? ts.c : `rgba(${ts.rgb},0.3)` }}>▾</div>
        </div>

        {/* Message preview / expanded */}
        <div style={{
          color: isExpanded ? "rgba(200,230,255,0.65)" : "rgba(0,212,255,0.35)",
          fontSize: 11, lineHeight: 1.8,
          fontFamily: "'Share Tech Mono', monospace",
          letterSpacing: "0.02em",
          maxHeight: isExpanded ? 400 : 44,
          overflow: "hidden",
          transition: "max-height 0.4s cubic-bezier(0.4,0,0.2,1), color 0.3s",
          marginBottom: 12,
          position: "relative",
        }}>
          {f.message || "No message body."}
          {!isExpanded && (
            <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 20, background: `linear-gradient(180deg, transparent, rgba(0,6,20,0.95))` }} />
          )}
        </div>

        {/* Expanded detail — agent info + context + timestamp */}
        {isExpanded && (
          <div style={{
            display: "flex", gap: 16, flexWrap: "wrap",
            padding: "10px 14px",
            background: `rgba(${ts.rgb},0.04)`,
            border: `1px solid rgba(${ts.rgb},0.1)`,
            borderRadius: 4,
            marginBottom: 12,
            animation: "holoRise 0.25s ease-out both",
          }}>
            {[
              { icon: "◎", label: "Agent", value: `${f.user_name || "Anonymous"}${f.user_email ? ` · ${f.user_email}` : ""}` },
              f.page_context && { icon: "⊕", label: "Context", value: f.page_context },
              { icon: "◷", label: "Received", value: f.created_at ? new Date(f.created_at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : "—" },
              { icon: "⌛", label: "Age", value: timeAgo(f.created_at) },
            ].filter(Boolean).map((item, i) => (
              <div key={i} style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <span style={{ fontSize: 9, color: `rgba(${ts.rgb},0.4)` }}>{item.icon}</span>
                <span style={{ fontSize: 7, color: `rgba(${ts.rgb},0.3)`, fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.12em", textTransform: "uppercase" }}>{item.label}:</span>
                <span style={{ fontSize: 9, color: `rgba(${ts.rgb},0.7)`, fontFamily: "'Share Tech Mono', monospace" }}>{item.value}</span>
              </div>
            ))}
          </div>
        )}

        {/* Footer meta row (always visible, compact) */}
        <div style={{ display: "flex", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
            <span style={{ fontSize: 8, color: `rgba(${ts.rgb},0.25)` }}>◎</span>
            <span style={{ fontSize: 8, color: `rgba(${ts.rgb},0.4)`, fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.06em" }}>{f.user_name || "Anonymous"}</span>
          </div>
          {f.page_context && (
            <div style={{ fontSize: 7, color: `rgba(${ts.rgb},0.22)`, fontFamily: "'Share Tech Mono', monospace", background: `rgba(${ts.rgb},0.04)`, border: `1px solid rgba(${ts.rgb},0.1)`, padding: "2px 7px", borderRadius: 2, letterSpacing: "0.08em" }}>
              ⊕ {f.page_context}
            </div>
          )}
          <div style={{ marginLeft: "auto", fontSize: 7, color: `rgba(${ts.rgb},0.2)`, fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.1em" }}>
            {timeAgo(f.created_at)}
          </div>
        </div>
      </div>
    </div>
  );
}

function FeedbackTable() {
  const { data, loading } = useAdminFetch("/admin/feedback?limit=100");
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [expandedId, setExpandedId] = useState(null);

  if (loading) return <HoloLoader />;

  const items = data?.items || [];

  // Derived counts for the stat strip
  const counts = {
    all: items.length,
    bug: items.filter(f => f.type === "bug").length,
    feature_request: items.filter(f => f.type === "feature_request").length,
    feedback: items.filter(f => f.type === "feedback").length,
    open: items.filter(f => f.status === "open").length,
  };

  const sentimentCounts = items.reduce((acc, f) => {
    const s = getSentiment((f.title || "") + " " + (f.message || ""));
    acc[s.label] = (acc[s.label] || 0) + 1;
    return acc;
  }, {});

  const filtered = items.filter(f => {
    if (filter !== "all" && f.type !== filter && f.status !== filter) return false;
    if (search) {
      const q = search.toLowerCase();
      if (!f.title?.toLowerCase().includes(q) && !f.message?.toLowerCase().includes(q) && !f.user_name?.toLowerCase().includes(q)) return false;
    }
    return true;
  });

  const FILTERS = [
    { id: "all",             label: "ALL",     count: counts.all,             color: "#00e5ff" },
    { id: "open",            label: "OPEN",    count: counts.open,            color: "#00ff9d" },
    { id: "bug",             label: "BUG",     count: counts.bug,             color: "#ff2d55" },
    { id: "feature_request", label: "FEATURE", count: counts.feature_request, color: "#00ff9d" },
    { id: "feedback",        label: "FEEDBACK",count: counts.feedback,        color: "#00d4ff" },
  ];

  return (
    <div>
      {/* ── Sentiment intelligence strip ── */}
      <div style={{
        display: "flex", gap: 8, marginBottom: 20,
        padding: "14px 18px",
        background: "linear-gradient(145deg, rgba(0,4,14,0.95) 0%, rgba(0,8,22,0.9) 100%)",
        border: "1px solid rgba(0,229,255,0.1)",
        borderRadius: 6,
        clipPath: "polygon(0 0, calc(100% - 14px) 0, 100% 14px, 100% 100%, 0 100%)",
        position: "relative", overflow: "hidden",
      }}>
        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: "linear-gradient(90deg, transparent, rgba(0,229,255,0.4), rgba(0,255,157,0.2), rgba(191,95,255,0.15), transparent)" }} />
        <div style={{ fontSize: 7, color: "rgba(0,229,255,0.3)", letterSpacing: "0.22em", fontFamily: "'Share Tech Mono', monospace", display: "flex", alignItems: "center", gap: 6, whiteSpace: "nowrap", marginRight: 10 }}>
          <div style={{ width: 4, height: 4, borderRadius: "50%", background: "#00e5ff", boxShadow: "0 0 6px #00e5ff", animation: "pulse-glow 2s infinite" }} />
          SENTIMENT SCAN
        </div>
        <div style={{ flex: 1, display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
          {[
            { label: "POSITIVE", color: "#00ff9d", rgb: "0,255,157" },
            { label: "NEUTRAL",  color: "#00e5ff", rgb: "0,229,255" },
            { label: "NEGATIVE", color: "#ff6b35", rgb: "255,107,53" },
            { label: "URGENT",   color: "#ff2d55", rgb: "255,45,85"  },
          ].map(({ label, color, rgb }) => (
            <div key={label} style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <div style={{ width: 6, height: 6, borderRadius: "50%", background: color, boxShadow: `0 0 6px rgba(${rgb},0.5)` }} />
              <span style={{ fontSize: 7, color: `rgba(${rgb},0.6)`, fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.1em" }}>{label}</span>
              <span style={{ fontSize: 9, fontWeight: 700, color, fontFamily: "'Orbitron', monospace", textShadow: `0 0 8px rgba(${rgb},0.4)` }}>{sentimentCounts[label] || 0}</span>
            </div>
          ))}
        </div>
        <div style={{ fontSize: 8, color: "rgba(0,229,255,0.2)", fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.1em", whiteSpace: "nowrap" }}>
          {items.length} transmissions
        </div>
      </div>

      {/* ── Filter pills + search ── */}
      <div style={{ display: "flex", gap: 10, marginBottom: 20, alignItems: "center", flexWrap: "wrap" }}>
        <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
          {FILTERS.map(f => (
            <button key={f.id} onClick={() => setFilter(f.id)}
              style={{
                display: "inline-flex", alignItems: "center", gap: 5,
                padding: "5px 12px",
                background: filter === f.id ? `rgba(${f.color.replace("#","").match(/../g).map(h=>parseInt(h,16)).join(",")},0.12)` : "rgba(0,0,0,0.2)",
                border: `1px solid ${filter === f.id ? f.color : "rgba(0,229,255,0.1)"}`,
                borderRadius: 4, cursor: "pointer",
                color: filter === f.id ? f.color : "rgba(0,212,255,0.3)",
                fontSize: 7, fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.14em",
                fontWeight: filter === f.id ? 700 : 400,
                boxShadow: filter === f.id ? `0 0 14px rgba(${f.color.replace("#","").match(/../g).map(h=>parseInt(h,16)).join(",")},0.2)` : "none",
                transition: "all 0.2s",
                clipPath: "polygon(0 0, calc(100% - 6px) 0, 100% 6px, 100% 100%, 0 100%)",
              }}>
              {filter === f.id && <div style={{ width: 4, height: 4, borderRadius: "50%", background: f.color, boxShadow: `0 0 6px ${f.color}`, animation: "pulse-glow 1.5s infinite" }} />}
              {f.label}
              <span style={{ opacity: 0.6 }}>{f.count}</span>
            </button>
          ))}
        </div>
        <div style={{ flex: 1, minWidth: 180, position: "relative" }}>
          <span style={{ position: "absolute", left: 12, top: "50%", transform: "translateY(-50%)", fontSize: 10, color: "rgba(0,229,255,0.25)", pointerEvents: "none" }}>◆</span>
          <input value={search} onChange={e => setSearch(e.target.value)} placeholder="Search transmissions…" className="holo-input" style={{ width: "100%", paddingLeft: 28 }} />
        </div>
        <div style={{ fontSize: 8, color: "rgba(0,229,255,0.3)", fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.1em" }}>{filtered.length} shown</div>
      </div>

      {/* ── Cards ── */}
      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        {filtered.map(f => (
          <FeedbackCard
            key={f.id} f={f}
            isExpanded={expandedId === f.id}
            onToggle={() => setExpandedId(expandedId === f.id ? null : f.id)}
          />
        ))}
        {filtered.length === 0 && (
          <div style={{ textAlign: "center", padding: "80px 0", color: "rgba(0,212,255,0.15)", fontFamily: "'Share Tech Mono', monospace", fontSize: 11, letterSpacing: "0.2em" }}>
            NO TRANSMISSIONS MATCH QUERY
          </div>
        )}
      </div>
    </div>
  );
}

// ── TRUE 3D ARC REACTOR — sphere with specular lighting, depth rings, lens flare ─
function ArcReactor({ color = "#00d4ff", rgb = "0,212,255", value = "$0", label = "MRR", size = 200 }) {
  const canvasRef = useRef(null);
  const [angle, setAngle] = useState(0);
  useEffect(() => {
    let raf;
    let t = 0;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    const S = size * 2;
    canvas.width = canvas.height = S;
    canvas.style.width = canvas.style.height = `${size}px`;
    const cx = S / 2, cy = S / 2;
    const [r0,g0,b0] = rgb.split(",").map(Number);

    function drawSphere3D(x, y, radius) {
      // Shadow beneath sphere
      const shadowG = ctx.createRadialGradient(x + radius*0.1, y + radius*0.85, 0, x, y + radius*0.7, radius*0.8);
      shadowG.addColorStop(0, `rgba(0,0,0,0.5)`);
      shadowG.addColorStop(1, `rgba(0,0,0,0)`);
      ctx.fillStyle = shadowG;
      ctx.beginPath(); ctx.ellipse(x, y + radius*0.85, radius*0.7, radius*0.2, 0, 0, Math.PI*2); ctx.fill();

      // Main sphere body — deep to mid tone
      const bodyG = ctx.createRadialGradient(x - radius*0.3, y - radius*0.25, radius*0.05, x, y, radius);
      bodyG.addColorStop(0, `rgba(${Math.min(r0+80,255)},${Math.min(g0+80,255)},${Math.min(b0+80,255)},0.9)`);
      bodyG.addColorStop(0.35, `rgba(${r0},${g0},${b0},0.55)`);
      bodyG.addColorStop(0.7, `rgba(${Math.round(r0*0.3)},${Math.round(g0*0.3)},${Math.round(b0*0.3)},0.35)`);
      bodyG.addColorStop(1, `rgba(0,0,0,0.6)`);
      ctx.fillStyle = bodyG;
      ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI*2); ctx.fill();

      // Primary specular highlight — top-left white hot spot
      const spec1 = ctx.createRadialGradient(x - radius*0.32, y - radius*0.30, 0, x - radius*0.2, y - radius*0.2, radius*0.42);
      spec1.addColorStop(0, `rgba(255,255,255,0.95)`);
      spec1.addColorStop(0.25, `rgba(255,255,255,0.45)`);
      spec1.addColorStop(0.6, `rgba(${r0},${g0},${b0},0.15)`);
      spec1.addColorStop(1, `rgba(${r0},${g0},${b0},0)`);
      ctx.fillStyle = spec1;
      ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI*2); ctx.fill();

      // Secondary rim light — bottom-right edge
      const spec2 = ctx.createRadialGradient(x + radius*0.55, y + radius*0.55, 0, x + radius*0.4, y + radius*0.4, radius*0.55);
      spec2.addColorStop(0, `rgba(${r0},${g0},${b0},0.5)`);
      spec2.addColorStop(0.4, `rgba(${r0},${g0},${b0},0.15)`);
      spec2.addColorStop(1, `rgba(${r0},${g0},${b0},0)`);
      ctx.fillStyle = spec2;
      ctx.beginPath(); ctx.arc(x, y, radius, 0, Math.PI*2); ctx.fill();

      // Fresnel rim glow around edge
      ctx.save();
      ctx.shadowColor = color; ctx.shadowBlur = radius * 0.6;
      ctx.strokeStyle = `rgba(${rgb},0.7)`;
      ctx.lineWidth = 2.5;
      ctx.beginPath(); ctx.arc(x, y, radius - 1, 0, Math.PI*2); ctx.stroke();
      ctx.restore();
    }

    function drawPerspectiveRing(x, y, rx, ry, rotX, lineW, alpha, dash, phase) {
      // Draw an ellipse (perspective-foreshortened ring) with rotation
      ctx.save();
      ctx.translate(x, y);
      ctx.rotate(phase);
      ctx.scale(1, ry / rx);
      ctx.beginPath();
      ctx.arc(0, 0, rx, 0, Math.PI * 2);
      if (dash.length) ctx.setLineDash(dash); else ctx.setLineDash([]);
      ctx.strokeStyle = `rgba(${rgb},${alpha})`;
      ctx.lineWidth = lineW / (ry / rx);
      ctx.shadowColor = color; ctx.shadowBlur = 10;
      ctx.stroke();
      ctx.restore();
    }

    function draw() {
      t += 0.012;
      ctx.clearRect(0, 0, S, S);

      // Ambient outer glow halo
      const halo = ctx.createRadialGradient(cx, cy, S*0.22, cx, cy, S*0.5);
      halo.addColorStop(0, `rgba(${rgb},0.08)`);
      halo.addColorStop(0.5, `rgba(${rgb},0.03)`);
      halo.addColorStop(1, `rgba(${rgb},0)`);
      ctx.fillStyle = halo; ctx.fillRect(0, 0, S, S);

      // 3D Perspective rings — foreshortened ellipses at different tilt angles
      const rings3D = [
        { rx: S*0.44, ryRatio: 0.18, w: 0.8, a: 0.09, dash: [5,14], speed: 0.25 },
        { rx: S*0.40, ryRatio: 0.28, w: 1.0, a: 0.13, dash: [10,8], speed: -0.4 },
        { rx: S*0.36, ryRatio: 0.42, w: 1.5, a: 0.20, dash: [3,9], speed: 0.6 },
        { rx: S*0.31, ryRatio: 0.60, w: 2.0, a: 0.28, dash: [], speed: -0.3 },
        { rx: S*0.25, ryRatio: 0.75, w: 1.2, a: 0.22, dash: [6,5], speed: 1.0 },
        { rx: S*0.18, ryRatio: 0.88, w: 3.5, a: 0.45, dash: [], speed: 0.8 },
        { rx: S*0.11, ryRatio: 0.95, w: 1.5, a: 0.35, dash: [3,6], speed: -1.8 },
      ];
      rings3D.forEach(ring => {
        drawPerspectiveRing(cx, cy, ring.rx, ring.rx * ring.ryRatio, 0, ring.w, ring.a, ring.dash, t * ring.speed);
      });

      // Spinning bright arc on the main ring
      ctx.save();
      ctx.translate(cx, cy); ctx.rotate(t * 1.4); ctx.scale(1, 0.6); // foreshorten
      ctx.beginPath();
      ctx.arc(0, 0, S * 0.31, -0.3, Math.PI * 1.15);
      ctx.strokeStyle = color; ctx.lineWidth = 4; ctx.setLineDash([]);
      ctx.globalAlpha = 0.7 + Math.sin(t * 2.5) * 0.2;
      ctx.shadowColor = color; ctx.shadowBlur = 28;
      ctx.stroke(); ctx.globalAlpha = 1; ctx.restore();

      // Counter arc
      ctx.save();
      ctx.translate(cx, cy); ctx.rotate(-t * 0.9); ctx.scale(1, 0.75);
      ctx.beginPath();
      ctx.arc(0, 0, S * 0.25, 0.4, Math.PI * 1.9);
      ctx.strokeStyle = `rgba(${rgb},0.55)`; ctx.lineWidth = 2;
      ctx.shadowColor = color; ctx.shadowBlur = 16; ctx.setLineDash([]);
      ctx.stroke(); ctx.restore();

      // Draw the 3D sphere in the center
      drawSphere3D(cx, cy, S * 0.155);

      // Radial energy spokes (3D depth illusion — shorter = behind, longer = front)
      const spokeCount = 8;
      for (let i = 0; i < spokeCount; i++) {
        const a = (i / spokeCount) * Math.PI * 2 + t * 0.5;
        const depth = (Math.sin(a - t * 0.5) + 1) * 0.5; // 0=back, 1=front
        const innerR = S * (0.16 + depth * 0.01);
        const outerR = S * (0.22 + depth * 0.04);
        const pulse = 0.1 + depth * 0.2 + Math.sin(t * 2 + i) * 0.06;
        ctx.beginPath();
        ctx.moveTo(cx + Math.cos(a) * innerR, cy + Math.sin(a) * innerR * 0.6);
        ctx.lineTo(cx + Math.cos(a) * outerR, cy + Math.sin(a) * outerR * 0.6);
        ctx.strokeStyle = `rgba(${rgb},${pulse})`;
        ctx.lineWidth = 1 + depth;
        ctx.shadowColor = color; ctx.shadowBlur = 8 + depth * 12;
        ctx.stroke();
      }

      // Constellation ring — dots around outer edge
      const constCount = 12;
      for (let i = 0; i < constCount; i++) {
        const a = (i / constCount) * Math.PI * 2 + t * 0.08;
        const cr = S * 0.46;
        const cx2 = cx + Math.cos(a) * cr, cy2 = cy + Math.sin(a) * cr;
        const lit = (Math.sin(t * 1.5 + i * 0.7) + 1) * 0.5;
        ctx.fillStyle = `rgba(${rgb},${0.1 + lit * 0.55})`;
        ctx.shadowColor = color; ctx.shadowBlur = lit * 10;
        ctx.beginPath(); ctx.arc(cx2, cy2, 1.5 + lit * 1.5, 0, Math.PI * 2); ctx.fill();
        ctx.shadowBlur = 0;
        // Thin connector to next dot
        if (lit > 0.5) {
          const a2 = ((i + 1) / constCount) * Math.PI * 2 + t * 0.08;
          ctx.strokeStyle = `rgba(${rgb},${(lit - 0.5) * 0.3})`;
          ctx.lineWidth = 0.5;
          ctx.beginPath(); ctx.moveTo(cx2, cy2); ctx.lineTo(cx + Math.cos(a2) * cr, cy + Math.sin(a2) * cr); ctx.stroke();
        }
      }

      // Energy burst — radial lines emanating from sphere edge
      const burstCount = 16;
      for (let i = 0; i < burstCount; i++) {
        const a = (i / burstCount) * Math.PI * 2 + t * 0.3;
        const burstPulse = (Math.sin(t * 2 + i * 0.8) + 1) * 0.5;
        const innerR2 = S * 0.175;
        const outerR2 = S * (0.22 + burstPulse * 0.06);
        if (burstPulse < 0.2) continue;
        ctx.strokeStyle = `rgba(${rgb},${burstPulse * 0.25})`;
        ctx.lineWidth = 0.5;
        ctx.shadowColor = color; ctx.shadowBlur = 4;
        ctx.beginPath();
        ctx.moveTo(cx + Math.cos(a) * innerR2, cy + Math.sin(a) * innerR2 * 0.6);
        ctx.lineTo(cx + Math.cos(a) * outerR2, cy + Math.sin(a) * outerR2 * 0.6);
        ctx.stroke(); ctx.shadowBlur = 0;
      }

      // Lens flare — top-right bright point
      const flareX = cx + S * 0.15, flareY = cy - S * 0.18;
      const flarePulse = 0.4 + Math.sin(t * 1.7) * 0.25;
      const flareG = ctx.createRadialGradient(flareX, flareY, 0, flareX, flareY, S * 0.08);
      flareG.addColorStop(0, `rgba(255,255,255,${flarePulse})`);
      flareG.addColorStop(0.3, `rgba(${rgb},${flarePulse * 0.4})`);
      flareG.addColorStop(1, `rgba(${rgb},0)`);
      ctx.fillStyle = flareG;
      ctx.beginPath(); ctx.arc(flareX, flareY, S * 0.08, 0, Math.PI * 2); ctx.fill();
      // Flare streaks
      ctx.save();
      ctx.globalAlpha = flarePulse * 0.5;
      [0, Math.PI*0.5, Math.PI, Math.PI*1.5, Math.PI*0.25, Math.PI*0.75].forEach(angle => {
        ctx.beginPath();
        ctx.moveTo(flareX, flareY);
        ctx.lineTo(flareX + Math.cos(angle) * S * 0.06, flareY + Math.sin(angle) * S * 0.06);
        ctx.strokeStyle = `rgba(255,255,255,0.8)`;
        ctx.lineWidth = 0.5; ctx.stroke();
      });
      ctx.restore();

      // Lens flare 2 — bottom-left counter-pulse
      const flare2X = cx - S * 0.12, flare2Y = cy + S * 0.15;
      const flare2Pulse = 0.25 + Math.sin(t * 2.2 + 2.1) * 0.15;
      const flare2G = ctx.createRadialGradient(flare2X, flare2Y, 0, flare2X, flare2Y, S * 0.05);
      flare2G.addColorStop(0, `rgba(${rgb},${flare2Pulse * 0.8})`);
      flare2G.addColorStop(1, `rgba(${rgb},0)`);
      ctx.fillStyle = flare2G;
      ctx.beginPath(); ctx.arc(flare2X, flare2Y, S * 0.05, 0, Math.PI * 2); ctx.fill();

      raf = requestAnimationFrame(draw);
    }
    draw();
    return () => cancelAnimationFrame(raf);
  }, [color, rgb, size]);

  return (
    <div style={{ position: "relative", width: size, height: size, flexShrink: 0 }}>
      <canvas ref={canvasRef} style={{ display: "block" }} />
      {/* Center text overlay */}
      <div style={{
        position: "absolute", inset: 0,
        display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center",
        pointerEvents: "none",
      }}>
        <div style={{ fontSize: 9, color: `rgba(${rgb},0.55)`, letterSpacing: "0.22em", textTransform: "uppercase", fontFamily: "'Share Tech Mono', monospace", marginBottom: 4 }}>{label}</div>
        <div style={{ fontSize: size * 0.13, fontWeight: 900, color: "#fff", fontFamily: "'Orbitron', monospace", letterSpacing: "-0.02em", textShadow: `0 0 20px rgba(${rgb},0.8), 0 0 60px rgba(${rgb},0.4)`, lineHeight: 1 }}>{value}</div>
        <div style={{ fontSize: 8, color: `rgba(${rgb},0.4)`, letterSpacing: "0.15em", fontFamily: "'Share Tech Mono', monospace", marginTop: 6 }}>ACTIVE</div>
      </div>
    </div>
  );
}

// ── REVENUE WAVEFORM — live-looking signal display ────────────────────────────
function RevenueWaveform({ data, color = "#00d4ff", rgb = "0,212,255" }) {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !data?.length) return;
    const ctx = canvas.getContext("2d");
    const W = canvas.width = canvas.offsetWidth * 2;
    const H = canvas.height = 120 * 2;
    canvas.style.height = "120px";
    let t = 0;
    let raf;

    const revenues = data.map(d => d.revenue || 0);
    const max = Math.max(...revenues, 1);

    function draw() {
      t += 0.018;
      ctx.clearRect(0, 0, W, H);

      const pts = revenues.map((v, i) => ({
        x: (i / (revenues.length - 1)) * W,
        y: H - (v / max) * (H * 0.75) - H * 0.1 + Math.sin(t + i * 0.4) * 2,
      }));

      // Glowing area fill
      const fillGrad = ctx.createLinearGradient(0, 0, 0, H);
      fillGrad.addColorStop(0, `rgba(${rgb},0.22)`);
      fillGrad.addColorStop(0.5, `rgba(${rgb},0.08)`);
      fillGrad.addColorStop(1, `rgba(${rgb},0)`);
      ctx.beginPath();
      ctx.moveTo(pts[0].x, H);
      pts.forEach(p => ctx.lineTo(p.x, p.y));
      ctx.lineTo(pts[pts.length - 1].x, H);
      ctx.closePath();
      ctx.fillStyle = fillGrad;
      ctx.fill();

      // Secondary echo line (slightly offset, dimmer)
      ctx.beginPath();
      pts.forEach((p, i) => {
        const echoY = p.y + 6 + Math.sin(t * 0.7 + i) * 3;
        i === 0 ? ctx.moveTo(p.x, echoY) : ctx.lineTo(p.x, echoY);
      });
      ctx.strokeStyle = `rgba(${rgb},0.12)`;
      ctx.lineWidth = 1.5;
      ctx.stroke();

      // Main line
      ctx.shadowColor = color;
      ctx.shadowBlur = 12;
      ctx.strokeStyle = color;
      ctx.lineWidth = 2.5;
      ctx.lineJoin = "round";
      ctx.beginPath();
      pts.forEach((p, i) => i === 0 ? ctx.moveTo(p.x, p.y) : ctx.lineTo(p.x, p.y));
      ctx.stroke();
      ctx.shadowBlur = 0;

      // Glowing data nodes
      pts.forEach((p, i) => {
        const bright = revenues[i] > 0;
        if (!bright) return;
        const pulse = 0.5 + Math.sin(t * 3 + i * 0.8) * 0.3;
        const nodeGlow = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, 14);
        nodeGlow.addColorStop(0, `rgba(${rgb},${pulse * 0.4})`);
        nodeGlow.addColorStop(1, `rgba(${rgb},0)`);
        ctx.fillStyle = nodeGlow;
        ctx.beginPath(); ctx.arc(p.x, p.y, 14, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = `rgba(255,255,255,${pulse * 0.9})`;
        ctx.shadowColor = color; ctx.shadowBlur = 10;
        ctx.beginPath(); ctx.arc(p.x, p.y, 3, 0, Math.PI * 2); ctx.fill();
        ctx.shadowBlur = 0;
      });

      // Scanning vertical line
      const scanX = ((t * 30) % W);
      const scanGrad = ctx.createLinearGradient(scanX - 20, 0, scanX + 20, 0);
      scanGrad.addColorStop(0, `rgba(${rgb},0)`);
      scanGrad.addColorStop(0.5, `rgba(${rgb},0.15)`);
      scanGrad.addColorStop(1, `rgba(${rgb},0)`);
      ctx.fillStyle = scanGrad;
      ctx.fillRect(scanX - 20, 0, 40, H);

      raf = requestAnimationFrame(draw);
    }
    draw();
    const onResize = () => { canvas.width = canvas.offsetWidth * 2; canvas.height = 120 * 2; };
    window.addEventListener("resize", onResize);
    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", onResize); };
  }, [data, color, rgb]);

  return <canvas ref={canvasRef} style={{ display: "block", width: "100%" }} />;
}

// ── JARVIS METRIC STRIP — 3D glass morphism KPI strip ─────────────────────────
function JarvisMetricStrip({ metrics, rgb, color }) {
  const [hovered, setHovered] = useState(null);
  return (
    <div style={{ display: "flex", gap: 3, marginBottom: 14 }}>
      {metrics.map((m, i) => (
        <div key={i}
          onMouseEnter={() => setHovered(i)}
          onMouseLeave={() => setHovered(null)}
          style={{
            flex: 1,
            padding: "16px 18px",
            background: i === 0
              ? `linear-gradient(145deg, rgba(${rgb},0.18) 0%, rgba(${rgb},0.06) 50%, rgba(${rgb},0.12) 100%)`
              : hovered === i
                ? `linear-gradient(145deg, rgba(${rgb},0.1) 0%, rgba(0,4,12,0.8) 100%)`
                : "rgba(0,5,14,0.75)",
            border: `1px solid rgba(${rgb},${i === 0 ? 0.45 : hovered === i ? 0.3 : 0.12})`,
            borderRadius: 4,
            position: "relative",
            overflow: "hidden",
            clipPath: "polygon(0 0, calc(100% - 8px) 0, 100% 8px, 100% 100%, 0 100%)",
            transform: hovered === i ? "translateY(-3px) scale(1.02)" : "translateY(0)",
            transition: "all 0.25s cubic-bezier(0.16,1,0.3,1)",
            boxShadow: i === 0
              ? `0 8px 40px rgba(${rgb},0.15), inset 0 1px 0 rgba(255,255,255,0.06), inset 0 0 30px rgba(${rgb},0.04)`
              : hovered === i
                ? `0 12px 40px rgba(${rgb},0.12), inset 0 1px 0 rgba(255,255,255,0.04)`
                : `0 4px 20px rgba(0,0,0,0.4), inset 0 1px 0 rgba(${rgb},0.03)`,
            backdropFilter: "blur(16px)",
            cursor: "default",
          }}>
          {/* Top glass reflection streak */}
          <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: "40%", background: `linear-gradient(180deg, rgba(255,255,255,${i === 0 ? 0.06 : 0.03}) 0%, rgba(255,255,255,0) 100%)`, pointerEvents: "none", borderRadius: "4px 4px 0 0" }} />
          {/* Top scan line */}
          <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: i === 0 ? `linear-gradient(90deg, ${color}, rgba(${rgb},0.4), transparent)` : `linear-gradient(90deg, transparent, rgba(${rgb},0.3), transparent)` }} />
          {/* Left depth bar */}
          {i === 0 && <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 2, background: `linear-gradient(180deg, ${color}, rgba(${rgb},0.2))`, boxShadow: `0 0 12px ${color}` }} />}
          {/* Corner cut accent */}
          <div style={{ position: "absolute", top: 0, right: 8, width: 0, height: 0, borderTop: `8px solid rgba(${rgb},${i === 0 ? 0.5 : 0.2})`, borderLeft: "8px solid transparent" }} />
          {/* Label */}
          <div style={{ fontSize: 7, color: `rgba(${rgb},${i === 0 ? 0.6 : 0.4})`, letterSpacing: "0.2em", textTransform: "uppercase", fontFamily: "'Share Tech Mono', monospace", marginBottom: 8 }}>{m.label}</div>
          {/* Value */}
          <div style={{ fontSize: 20, fontWeight: 800, color: i === 0 ? "#fff" : color, fontFamily: "'Orbitron', monospace", textShadow: `0 0 20px rgba(${rgb},${i === 0 ? 0.9 : 0.6}), 0 0 60px rgba(${rgb},0.2)`, letterSpacing: "-0.02em", lineHeight: 1 }}>{m.value}</div>
          {m.sub && <div style={{ fontSize: 8, color: `rgba(${rgb},0.3)`, fontFamily: "'Share Tech Mono', monospace", marginTop: 6, letterSpacing: "0.05em" }}>{m.sub}</div>}
          {/* Bottom shimmer */}
          <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, height: 1, background: `rgba(${rgb},0.06)` }} />
        </div>
      ))}
    </div>
  );
}

// ── REVENUE INTEL PANEL — 3D glass right sidebar ─────────────────────────────
function RevenueIntelPanel({ data, rgb, color }) {
  const [tick, setTick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setTick(t => t + 1), 1800);
    return () => clearInterval(id);
  }, []);

  if (!data) return null;

  const breakdown = data.monthly_breakdown || [];
  const totalRev = breakdown.reduce((s, d) => s + (d.revenue || 0), 0);
  const totalUsers = breakdown.reduce((s, d) => s + (d.new_paid || 0), 0);
  const lastThree = breakdown.slice(-3);
  const growth = lastThree.length >= 2
    ? ((lastThree[lastThree.length - 1].revenue - lastThree[0].revenue) / Math.max(lastThree[0].revenue, 1) * 100).toFixed(1)
    : 0;

  const signals = [
    { label: "Revenue Engine", status: "OPTIMAL", col: "#00ff88" },
    { label: "Billing Sync", status: data.mrr > 0 ? "ACTIVE" : "OFFLINE", col: data.mrr > 0 ? "#00ff88" : "#ff3366" },
    { label: "Growth Vector", status: growth > 0 ? `+${growth}%` : `${growth}%`, col: growth > 0 ? "#00ff88" : "#ffd700" },
    { label: "Unit Economics", status: "STABLE", col: "#00d4ff" },
    { label: "Forecast Model", status: "RUNNING", col: color },
  ];

  const projMonths = 3;
  const avgMonthly = totalRev / Math.max(breakdown.length, 1);
  const projections = Array.from({ length: projMonths }, (_, i) => ({
    label: ["NEXT MO", "+2 MO", "+3 MO"][i],
    value: `$${(avgMonthly * (1 + (i + 1) * 0.05)).toFixed(0)}`,
    conf: [92, 84, 71][i],
  }));

  const glassPanel = {
    background: `linear-gradient(145deg, rgba(0,6,18,0.92) 0%, rgba(0,12,28,0.85) 40%, rgba(0,6,18,0.88) 100%)`,
    border: `1px solid rgba(${rgb},0.2)`,
    borderRadius: 4,
    padding: "16px 18px",
    clipPath: "polygon(0 0, calc(100% - 10px) 0, 100% 10px, 100% 100%, 10px 100%, 0 calc(100% - 10px))",
    position: "relative",
    overflow: "hidden",
    backdropFilter: "blur(20px)",
    boxShadow: `0 8px 40px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.05), inset 0 0 40px rgba(${rgb},0.02)`,
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {/* System signals */}
      <div style={glassPanel}>
        {/* Glass reflection */}
        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: "35%", background: "linear-gradient(180deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0) 100%)", pointerEvents: "none" }} />
        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, rgba(${rgb},0.7), transparent)` }} />
        <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 2, background: `linear-gradient(180deg, ${color}, rgba(${rgb},0.1))`, boxShadow: `0 0 10px rgba(${rgb},0.3)` }} />
        <div style={{ position: "absolute", top: 0, right: 10, width: 0, height: 0, borderTop: `10px solid rgba(${rgb},0.35)`, borderLeft: "10px solid transparent" }} />
        {/* Subtle inner glow */}
        <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at 50% 0%, rgba(${rgb},0.05) 0%, transparent 70%)`, pointerEvents: "none" }} />

        <div style={{ fontSize: 8, color: `rgba(${rgb},0.6)`, letterSpacing: "0.22em", textTransform: "uppercase", fontFamily: "'Share Tech Mono', monospace", marginBottom: 14, display: "flex", alignItems: "center", gap: 6, position: "relative" }}>
          <div style={{ width: 5, height: 5, background: "#00ff88", borderRadius: "50%", animation: "pulse-glow 1.5s infinite", boxShadow: "0 0 10px #00ff88" }} />
          System Intel
        </div>
        {signals.map((s, i) => (
          <div key={i} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: i < signals.length - 1 ? 10 : 0, padding: "6px 8px", borderBottom: i < signals.length - 1 ? `1px solid rgba(${rgb},0.06)` : "none", borderRadius: 2, background: "rgba(0,0,0,0.1)", position: "relative" }}>
            <span style={{ fontSize: 8, color: `rgba(${rgb},0.45)`, fontFamily: "'Share Tech Mono', monospace" }}>{s.label}</span>
            <div style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <div style={{ width: 4, height: 4, borderRadius: "50%", background: s.col, boxShadow: `0 0 8px ${s.col}`, animation: "pulse-glow 2s infinite" }} />
              <span style={{ fontSize: 8, color: s.col, fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.08em", fontWeight: 700 }}>{s.status}</span>
            </div>
          </div>
        ))}
      </div>

      {/* Revenue projections */}
      <div style={glassPanel}>
        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: "35%", background: "linear-gradient(180deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0) 100%)", pointerEvents: "none" }} />
        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, rgba(${rgb},0.6), transparent)` }} />
        <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 2, background: `linear-gradient(180deg, rgba(${rgb},0.8), transparent)` }} />
        <div style={{ position: "absolute", top: 0, right: 10, width: 0, height: 0, borderTop: `10px solid rgba(${rgb},0.3)`, borderLeft: "10px solid transparent" }} />

        <div style={{ fontSize: 8, color: `rgba(${rgb},0.55)`, letterSpacing: "0.22em", textTransform: "uppercase", fontFamily: "'Share Tech Mono', monospace", marginBottom: 14, display: "flex", alignItems: "center", gap: 6 }}>
          <div style={{ width: 4, height: 4, background: color, borderRadius: "50%", boxShadow: `0 0 8px ${color}` }} />
          Projection
        </div>
        {projections.map((p, i) => (
          <div key={i} style={{ marginBottom: i < projections.length - 1 ? 12 : 0 }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
              <span style={{ fontSize: 8, color: `rgba(${rgb},0.4)`, fontFamily: "'Share Tech Mono', monospace" }}>{p.label}</span>
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <span style={{ fontSize: 7, color: `rgba(${rgb},0.25)`, fontFamily: "'Share Tech Mono', monospace" }}>{p.conf}%</span>
                <span style={{ fontSize: 14, color: "#fff", fontWeight: 700, fontFamily: "'Orbitron', monospace", textShadow: `0 0 12px rgba(${rgb},0.7)` }}>{p.value}</span>
              </div>
            </div>
            <div style={{ height: 3, background: `rgba(${rgb},0.06)`, borderRadius: 2, position: "relative", overflow: "hidden" }}>
              <div style={{ height: "100%", width: `${p.conf}%`, background: `linear-gradient(90deg, rgba(${rgb},0.3), ${color})`, borderRadius: 2, boxShadow: `0 0 8px rgba(${rgb},0.4)`, transition: "width 1.4s cubic-bezier(0.4,0,0.2,1)", position: "relative" }}>
                <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: "50%", background: "rgba(255,255,255,0.2)", borderRadius: "2px 2px 0 0" }} />
              </div>
            </div>
          </div>
        ))}
        <div style={{ marginTop: 12, paddingTop: 10, borderTop: `1px solid rgba(${rgb},0.08)`, fontSize: 8, color: `rgba(${rgb},0.25)`, fontFamily: "'Share Tech Mono', monospace", lineHeight: 1.7 }}>
          ◈ Linear regression · {breakdown.length} pts
        </div>
      </div>

      {/* Cumulative totals */}
      <div style={{ ...glassPanel, background: `linear-gradient(145deg, rgba(${rgb},0.08) 0%, rgba(0,6,18,0.88) 50%, rgba(${rgb},0.04) 100%)`, border: `1px solid rgba(${rgb},0.25)` }}>
        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, ${color}, rgba(${rgb},0.3), transparent)` }} />
        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: "35%", background: "linear-gradient(180deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0) 100%)", pointerEvents: "none" }} />
        <div style={{ fontSize: 8, color: `rgba(${rgb},0.55)`, letterSpacing: "0.22em", textTransform: "uppercase", fontFamily: "'Share Tech Mono', monospace", marginBottom: 12 }}>Cumulative</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          {[
            { label: "Total Revenue", value: `$${totalRev.toFixed(0)}` },
            { label: "Paid Users", value: totalUsers },
            { label: "Plan Price", value: `$${data.plan_price}/mo` },
            { label: "Avg MRR", value: `$${avgMonthly.toFixed(0)}` },
          ].map((item, i) => (
            <div key={i} style={{ padding: "8px 10px", background: "rgba(0,0,0,0.2)", borderRadius: 3, border: `1px solid rgba(${rgb},0.1)`, position: "relative", overflow: "hidden" }}>
              <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: `rgba(${rgb},0.15)` }} />
              <div style={{ fontSize: 7, color: `rgba(${rgb},0.35)`, letterSpacing: "0.15em", fontFamily: "'Share Tech Mono', monospace", marginBottom: 4 }}>{item.label}</div>
              <div style={{ fontSize: 15, fontWeight: 700, color: color, fontFamily: "'Orbitron', monospace", textShadow: `0 0 12px rgba(${rgb},0.5)` }}>{item.value}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── REVENUE COLOR CYCLE HOOK ─────────────────────────────────────────────────
// Slowly cycles through a palette of cyberpunk accent colors for the revenue panel only.
function useRevenueColor() {
  const palette = [
    { hex: "#00ff88", rgb: "0,255,136" },
    { hex: "#00d4ff", rgb: "0,212,255" },
    { hex: "#a855f7", rgb: "168,85,247" },
    { hex: "#ffd700", rgb: "255,215,0" },
    { hex: "#ff6b35", rgb: "255,107,53" },
    { hex: "#00ffcc", rgb: "0,255,204" },
  ];
  const [t, setT] = useState(0);
  useEffect(() => {
    let raf;
    let start = null;
    const CYCLE_MS = 6000; // full palette loop every 6 s
    function tick(now) {
      if (!start) start = now;
      // progress 0–1 across the entire palette
      const progress = ((now - start) % CYCLE_MS) / CYCLE_MS;
      setT(progress);
      raf = requestAnimationFrame(tick);
    }
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  // Interpolate between two adjacent palette entries
  const total = palette.length;
  const scaled = t * total;
  const idxA = Math.floor(scaled) % total;
  const idxB = (idxA + 1) % total;
  const frac = scaled - Math.floor(scaled);

  const lerp = (a, b, f) => Math.round(a + (b - a) * f);
  const parseRgb = (s) => s.split(",").map(Number);
  const [r1, g1, b1] = parseRgb(palette[idxA].rgb);
  const [r2, g2, b2] = parseRgb(palette[idxB].rgb);
  const r = lerp(r1, r2, frac);
  const g = lerp(g1, g2, frac);
  const b = lerp(b1, b2, frac);

  return { hex: `rgb(${r},${g},${b})`, rgb: `${r},${g},${b}` };
}

// ── LIVE BROADCAST TICKER BAR — scrolling telemetry at bottom of screen ──────
function LiveTickerBar({ m }) {
  const items = m ? [
    `⬡ TOTAL USERS: ${m.users?.total ?? "—"}`,
    `◎ MRR: $${m.revenue?.mrr ?? "—"}`,
    `↑ ARR: $${(m.revenue?.arr || 0).toLocaleString()}`,
    `◆ PAID: ${m.users?.paid ?? "—"} ACCOUNTS`,
    `⊞ TRIALING: ${m.users?.trialing ?? "—"} USERS`,
    `✦ TASKS TODAY: ${m.tasks?.created_today ?? "—"}`,
    `● COMPLETION RATE: ${m.tasks?.completion_rate ?? "—"}%`,
    `▲ NEW THIS WEEK: +${m.users?.new_this_week ?? "—"}`,
    `◈ QRR: $${m.revenue?.qrr ?? "—"}`,
    `⊕ NEW THIS MONTH: +${m.users?.new_this_month ?? "—"}`,
    `⬡ PLAN PRICE: $${m.revenue?.plan_price ?? "—"}/MO`,
    `◎ ARCANEOS v2.0 · FINANCIAL CORE ONLINE`,
  ] : ["◈ ARCANEOS v2.0 · INITIALIZING DATA STREAMS …"];

  const doubled = [...items, ...items]; // seamless loop

  return (
    <div style={{
      position: "fixed", bottom: 0, left: 240, right: 0, height: 28, zIndex: 20,
      background: "linear-gradient(180deg, rgba(0,4,16,0.97) 0%, rgba(0,2,10,0.99) 100%)",
      borderTop: "1px solid rgba(0,229,255,0.12)",
      overflow: "hidden",
      boxShadow: "0 -4px 30px rgba(0,0,0,0.6), 0 -1px 0 rgba(0,229,255,0.06)",
    }}>
      {/* Top prismatic edge */}
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: "linear-gradient(90deg, transparent, rgba(0,229,255,0.4), rgba(0,255,157,0.2), rgba(191,95,255,0.15), rgba(0,229,255,0.4), transparent)" }} />

      {/* Left label pill */}
      <div style={{
        position: "absolute", left: 0, top: 0, bottom: 0, width: 90, zIndex: 2,
        background: "linear-gradient(90deg, rgba(0,6,20,0.99) 70%, rgba(0,6,20,0) 100%)",
        display: "flex", alignItems: "center", paddingLeft: 12, gap: 6,
      }}>
        <div style={{ width: 5, height: 5, borderRadius: "50%", background: "#00ff88", boxShadow: "0 0 8px #00ff88", animation: "pulse-glow 1s infinite", flexShrink: 0 }} />
        <span style={{ fontSize: 7, color: "rgba(0,229,255,0.6)", letterSpacing: "0.2em", fontFamily: "'Share Tech Mono', monospace", whiteSpace: "nowrap", fontWeight: 700 }}>LIVE</span>
      </div>

      {/* Scrolling content */}
      <div style={{
        display: "flex", alignItems: "center", height: "100%",
        animation: "tickerScroll 40s linear infinite",
        paddingLeft: 90,
        whiteSpace: "nowrap",
      }}>
        {doubled.map((item, i) => (
          <span key={i} style={{
            fontSize: 8, fontFamily: "'Share Tech Mono', monospace",
            color: i % 3 === 0 ? "rgba(0,229,255,0.65)" : i % 3 === 1 ? "rgba(0,255,157,0.5)" : "rgba(191,95,255,0.45)",
            letterSpacing: "0.14em",
            paddingRight: 40,
          }}>
            {item}
            <span style={{ color: "rgba(0,229,255,0.15)", paddingLeft: 40 }}>·</span>
          </span>
        ))}
      </div>

      {/* Right fade */}
      <div style={{ position: "absolute", right: 0, top: 0, bottom: 0, width: 60, background: "linear-gradient(270deg, rgba(0,4,16,0.99) 40%, rgba(0,4,16,0) 100%)" }} />
    </div>
  );
}

// ── DATA VIZ OVERLAY STRIP — animated hex-grid + live data nodes ────────────
function DataVizOverlayStrip({ m }) {
  const canvasRef = useRef(null);
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    let W = canvas.width = canvas.offsetWidth * 2;
    const H = canvas.height = 80 * 2;
    canvas.style.height = "80px";
    let t = 0, raf;

    const hexSize = 16;
    const cols = Math.ceil(W / (hexSize * 1.73)) + 2;
    const rows = Math.ceil(H / (hexSize * 1.5)) + 2;
    const hexes = [];
    for (let r = 0; r < rows; r++) {
      for (let c = 0; c < cols; c++) {
        const x = c * hexSize * 1.73 + (r % 2 ? hexSize * 0.87 : 0);
        const y = r * hexSize * 1.5;
        hexes.push({ x, y, phase: Math.random() * Math.PI * 2, speed: 0.01 + Math.random() * 0.02, lit: Math.random() > 0.75 });
      }
    }

    function drawHex(x, y, size, alpha, fill) {
      ctx.beginPath();
      for (let i = 0; i < 6; i++) {
        const a = (Math.PI / 3) * i - Math.PI / 6;
        i === 0 ? ctx.moveTo(x + size * Math.cos(a), y + size * Math.sin(a)) : ctx.lineTo(x + size * Math.cos(a), y + size * Math.sin(a));
      }
      ctx.closePath();
      if (fill) { ctx.fillStyle = fill; ctx.fill(); }
      ctx.strokeStyle = `rgba(0,229,255,${alpha})`;
      ctx.lineWidth = 0.5;
      ctx.stroke();
    }

    function draw() {
      t += 0.012;
      ctx.clearRect(0, 0, W, H);

      hexes.forEach(h => {
        h.phase += h.speed;
        const pulse = (Math.sin(h.phase) + 1) * 0.5;
        const baseA = h.lit ? 0.06 + pulse * 0.1 : 0.025;
        const fill = h.lit ? `rgba(0,229,255,${0.02 + pulse * 0.04})` : null;
        drawHex(h.x, h.y, hexSize * 0.46, baseA, fill);
      });

      // Data flow particles along the strip
      const streams = [0.12, 0.35, 0.58, 0.81];
      streams.forEach((pct, si) => {
        const x = ((t * 0.18 + si * 0.25) % 1) * W;
        const y = H * pct;
        const g = ctx.createRadialGradient(x, y, 0, x, y, 30);
        const hues = ["0,229,255", "0,255,157", "191,95,255", "255,208,96"];
        g.addColorStop(0, `rgba(${hues[si]},0.5)`);
        g.addColorStop(1, `rgba(${hues[si]},0)`);
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(x, y, 30, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = `rgba(255,255,255,0.8)`;
        ctx.beginPath(); ctx.arc(x, y, 2.5, 0, Math.PI * 2); ctx.fill();
        // Trail
        ctx.strokeStyle = `rgba(${hues[si]},0.12)`;
        ctx.lineWidth = 1;
        ctx.beginPath(); ctx.moveTo(x - 60, y); ctx.lineTo(x, y); ctx.stroke();
      });

      raf = requestAnimationFrame(draw);
    }
    draw();
    const onResize = () => { W = canvas.width = canvas.offsetWidth * 2; };
    window.addEventListener("resize", onResize);
    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", onResize); };
  }, []);

  return (
    <div style={{
      position: "relative", marginBottom: 16, overflow: "hidden", borderRadius: 6,
      border: "1px solid rgba(0,229,255,0.1)",
      background: "linear-gradient(90deg, rgba(0,5,18,0.9) 0%, rgba(0,10,28,0.85) 50%, rgba(0,5,18,0.9) 100%)",
      clipPath: "polygon(0 0, calc(100% - 12px) 0, 100% 12px, 100% 100%, 12px 100%, 0 calc(100% - 12px))",
      boxShadow: "inset 0 1px 0 rgba(255,255,255,0.04), 0 4px 30px rgba(0,0,0,0.5)",
    }}>
      {/* Top prismatic line */}
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: "linear-gradient(90deg, transparent, rgba(0,229,255,0.5), rgba(0,255,157,0.3), rgba(191,95,255,0.2), rgba(0,229,255,0.5), transparent)", pointerEvents: "none", zIndex: 2 }} />
      <canvas ref={canvasRef} style={{ display: "block", width: "100%" }} />
      {/* Overlay text nodes */}
      <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "space-around", pointerEvents: "none", padding: "0 20px", zIndex: 3 }}>
        {[
          { label: "CONVERSION", value: m?.users?.paid && m?.users?.total ? `${((m.users.paid / m.users.total) * 100).toFixed(1)}%` : "—", color: "#00ff9d" },
          { label: "TRIAL RATE", value: m?.users?.trialing && m?.users?.total ? `${((m.users.trialing / m.users.total) * 100).toFixed(1)}%` : "—", color: "#ffd060" },
          { label: "TASK COMPLETION", value: `${m?.tasks?.completion_rate ?? "—"}%`, color: "#00e5ff" },
          { label: "WEEKLY GROWTH", value: `+${m?.users?.new_this_week ?? "—"}`, color: "#bf5fff" },
          { label: "MONTHLY GROWTH", value: `+${m?.users?.new_this_month ?? "—"}`, color: "#00ff9d" },
        ].map(({ label, value, color }) => (
          <div key={label} style={{ textAlign: "center" }}>
            <div style={{ fontSize: 6, color: "rgba(0,229,255,0.35)", letterSpacing: "0.2em", fontFamily: "'Share Tech Mono', monospace", marginBottom: 3 }}>{label}</div>
            <div style={{ fontSize: 16, fontWeight: 800, color, fontFamily: "'Orbitron', monospace", textShadow: `0 0 14px ${color}88`, lineHeight: 1 }}>{value}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── TOAST NOTIFICATION SYSTEM ────────────────────────────────────────────────
function ToastSystem({ toasts, dismiss }) {
  return (
    <div style={{
      position: "fixed", top: 80, right: 20, zIndex: 9999,
      display: "flex", flexDirection: "column", gap: 10,
      pointerEvents: "none",
    }}>
      {toasts.map(t => {
        const cfg = {
          success: { color: "#00ff9d", rgb: "0,255,157", icon: "✓", label: "SUCCESS" },
          warning: { color: "#ffd060", rgb: "255,208,96", icon: "⚠", label: "WARNING" },
          error:   { color: "#ff2d55", rgb: "255,45,85",  icon: "✕", label: "ERROR"   },
          info:    { color: "#00e5ff", rgb: "0,229,255",  icon: "◈", label: "SYSTEM"  },
        }[t.type || "info"];
        return (
          <div key={t.id} onClick={() => dismiss(t.id)}
            style={{
              display: "flex", alignItems: "flex-start", gap: 12,
              padding: "14px 18px",
              minWidth: 280, maxWidth: 380,
              background: `linear-gradient(135deg, rgba(0,4,14,0.98) 0%, rgba(0,8,22,0.96) 100%)`,
              border: `1px solid rgba(${cfg.rgb},0.4)`,
              borderRadius: 6,
              clipPath: "polygon(0 0, calc(100% - 14px) 0, 100% 14px, 100% 100%, 14px 100%, 0 calc(100% - 14px))",
              boxShadow: `0 0 0 1px rgba(${cfg.rgb},0.06), 0 20px 60px rgba(0,0,0,0.85), 0 0 40px rgba(${cfg.rgb},0.12), inset 0 1px 0 rgba(255,255,255,0.07)`,
              backdropFilter: "blur(24px)",
              animation: "holoRise 0.4s cubic-bezier(0.16,1,0.3,1) both",
              pointerEvents: "all",
              cursor: "pointer",
              position: "relative", overflow: "hidden",
            }}>
            {/* Top prismatic edge */}
            <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, rgba(${cfg.rgb},0.7), transparent)`, boxShadow: `0 0 10px rgba(${cfg.rgb},0.4)` }} />
            {/* Left accent bar */}
            <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 3, background: `linear-gradient(180deg, ${cfg.color}, rgba(${cfg.rgb},0.2))`, boxShadow: `0 0 12px rgba(${cfg.rgb},0.4)` }} />
            {/* Corner cut */}
            <div style={{ position: "absolute", top: 0, right: 14, width: 0, height: 0, borderTop: `14px solid rgba(${cfg.rgb},0.4)`, borderLeft: "14px solid transparent" }} />
            {/* Scan shimmer */}
            <div style={{ position: "absolute", inset: 0, left: "-100%", width: "60%", background: `linear-gradient(90deg, transparent, rgba(${cfg.rgb},0.04), transparent)`, animation: "shimmerSlide 3s ease-in-out 0.5s" }} />
            {/* Icon */}
            <div style={{
              width: 32, height: 32, flexShrink: 0, borderRadius: "50%",
              background: `radial-gradient(circle, rgba(${cfg.rgb},0.2) 0%, rgba(${cfg.rgb},0.06) 100%)`,
              border: `1px solid rgba(${cfg.rgb},0.4)`,
              display: "flex", alignItems: "center", justifyContent: "center",
              fontSize: 14, color: cfg.color,
              textShadow: `0 0 12px rgba(${cfg.rgb},0.8)`,
              boxShadow: `0 0 16px rgba(${cfg.rgb},0.2)`,
            }}>{cfg.icon}</div>
            {/* Content */}
            <div style={{ flex: 1 }}>
              <div style={{ fontSize: 7, color: `rgba(${cfg.rgb},0.5)`, letterSpacing: "0.22em", fontFamily: "'Share Tech Mono', monospace", marginBottom: 4 }}>
                {cfg.label} · {new Date().toLocaleTimeString("en-US", { hour12: false })}
              </div>
              <div style={{ fontSize: 12, color: "#e8f4ff", fontFamily: "'Rajdhani', sans-serif", fontWeight: 600, letterSpacing: "0.04em" }}>{t.message}</div>
            </div>
            {/* Dismiss X */}
            <div style={{ fontSize: 8, color: `rgba(${cfg.rgb},0.3)`, marginTop: 2, letterSpacing: "0.1em" }}>✕</div>
          </div>
        );
      })}
    </div>
  );
}

function useToasts() {
  const [toasts, setToasts] = useState([]);
  const showToast = (message, type = "info") => {
    const id = Date.now();
    setToasts(t => [...t, { id, message, type }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 4200);
  };
  const dismiss = (id) => setToasts(t => t.filter(x => x.id !== id));
  return { toasts, showToast, dismiss };
}

// ── LOGIN SCREEN — HOLOGRAPHIC AUTH GATE ──────────────────────────────────────
function LoginScreen({ onLogin }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [bootPct, setBootPct] = useState(0);
  const [showPw, setShowPw] = useState(false);
  const canvasRef = useRef(null);

  // Boot sequence
  useEffect(() => {
    const t = setInterval(() => setBootPct(p => p < 100 ? p + 1 : 100), 22);
    return () => clearInterval(t);
  }, []);

  // Login canvas bg
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    let W = canvas.width = canvas.offsetWidth;
    let H = canvas.height = canvas.offsetHeight;
    let t = 0, raf;

    const particles = Array.from({ length: 60 }, () => ({
      x: Math.random() * W, y: Math.random() * H,
      vx: (Math.random() - 0.5) * 0.3, vy: (Math.random() - 0.5) * 0.3,
      r: 1 + Math.random() * 2.5,
      hue: [195, 280, 45, 160][Math.floor(Math.random() * 4)],
      alpha: 0.2 + Math.random() * 0.5,
      pulse: Math.random() * Math.PI * 2,
    }));

    function draw() {
      t += 0.008;
      ctx.clearRect(0, 0, W, H);

      // Radial vortex lines
      const cx = W / 2, cy = H / 2;
      for (let i = 0; i < 24; i++) {
        const a = (i / 24) * Math.PI * 2 + t * 0.12;
        const pulse = 0.03 + Math.sin(t * 1.5 + i * 0.4) * 0.02;
        ctx.strokeStyle = `rgba(0,212,255,${pulse})`;
        ctx.lineWidth = 0.5;
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.lineTo(cx + Math.cos(a) * Math.max(W, H), cy + Math.sin(a) * Math.max(W, H));
        ctx.stroke();
      }

      // Concentric glowing rings
      for (let r = 80; r < Math.max(W, H); r += 120) {
        const alpha = 0.02 + 0.015 * Math.sin(t * 0.6 + r * 0.01);
        ctx.strokeStyle = `rgba(0,229,255,${alpha})`;
        ctx.lineWidth = 0.5;
        ctx.setLineDash([6, 18]);
        ctx.beginPath();
        ctx.arc(cx, cy, r + Math.sin(t * 0.4 + r) * 4, 0, Math.PI * 2);
        ctx.stroke();
      }
      ctx.setLineDash([]);

      // Floating nodes
      particles.forEach(p => {
        p.x += p.vx; p.y += p.vy; p.pulse += 0.02;
        if (p.x < 0 || p.x > W) p.vx *= -1;
        if (p.y < 0 || p.y > H) p.vy *= -1;
        const a = p.alpha * (0.5 + 0.5 * Math.sin(p.pulse));
        const g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.r * 4);
        g.addColorStop(0, `hsla(${p.hue},100%,70%,${a * 0.6})`);
        g.addColorStop(1, `hsla(${p.hue},100%,70%,0)`);
        ctx.fillStyle = g;
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r * 4, 0, Math.PI * 2); ctx.fill();
        ctx.fillStyle = `hsla(${p.hue},100%,90%,${a})`;
        ctx.beginPath(); ctx.arc(p.x, p.y, p.r, 0, Math.PI * 2); ctx.fill();
      });

      // Connections
      particles.forEach((a, i) => {
        particles.slice(i + 1).forEach(b => {
          const d = Math.hypot(a.x - b.x, a.y - b.y);
          if (d < 140) {
            const str = (1 - d / 140) * 0.06;
            ctx.strokeStyle = `rgba(0,212,255,${str})`;
            ctx.lineWidth = 0.4;
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
          }
        });
      });

      raf = requestAnimationFrame(draw);
    }
    draw();
    const onResize = () => { W = canvas.width = canvas.offsetWidth; H = canvas.height = canvas.offsetHeight; };
    window.addEventListener("resize", onResize);
    return () => { cancelAnimationFrame(raf); window.removeEventListener("resize", onResize); };
  }, []);

  const handleLogin = async () => {
    if (!email || !password) { setError("CREDENTIALS REQUIRED"); return; }
    setLoading(true); setError(null);
    try {
      const form = new URLSearchParams();
      form.append("username", email);
      form.append("password", password);
      const res = await fetch(`${API}/auth/login`, {
        method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: form,
      });
      if (!res.ok) throw new Error("AUTH REJECTED");
      const d = await res.json();
      if (d.access_token) {
        localStorage.setItem("access_token", d.access_token);
        if (d.refresh_token) localStorage.setItem("refresh_token", d.refresh_token);
        onLogin();
      } else throw new Error("NO TOKEN RECEIVED");
    } catch (e) { setError(e.message); } finally { setLoading(false); }
  };

  return (
    <div style={{ minHeight: "100vh", background: "#000510", display: "flex", alignItems: "center", justifyContent: "center", position: "relative", overflow: "hidden" }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;800;900&family=Share+Tech+Mono&family=Rajdhani:wght@400;500;600;700&display=swap');
        @keyframes loginPulse { 0%,100%{opacity:0.7;transform:scale(1)} 50%{opacity:1;transform:scale(1.02)} }
        @keyframes loginFloat { 0%{transform:translateY(0)} 50%{transform:translateY(-8px)} 100%{transform:translateY(0)} }
        @keyframes scanV { 0%{top:0} 100%{top:100%} }
        @keyframes rotateLogin { from{transform:rotate(0deg)} to{transform:rotate(360deg)} }
        @keyframes loginShimmer { 0%{left:-100%} 100%{left:100%} }
        @keyframes pulseGlowLogin { 0%,100%{box-shadow:0 0 12px rgba(0,229,255,0.4)} 50%{box-shadow:0 0 25px rgba(0,229,255,0.8),0 0 50px rgba(0,229,255,0.3)} }
        @keyframes typeIn { from{opacity:0;transform:translateX(-8px)} to{opacity:1;transform:translateX(0)} }
        @keyframes holoRise { from{opacity:0;transform:translateY(30px) scale(0.96)} to{opacity:1;transform:translateY(0) scale(1)} }
        @keyframes errorShake { 0%,100%{transform:translateX(0)} 20%,60%{transform:translateX(-8px)} 40%,80%{transform:translateX(8px)} }
      `}</style>

      {/* Animated canvas bg */}
      <canvas ref={canvasRef} style={{ position: "absolute", inset: 0, width: "100%", height: "100%", pointerEvents: "none" }} />

      {/* Deep space gradient */}
      <div style={{
        position: "absolute", inset: 0, pointerEvents: "none",
        background: "radial-gradient(ellipse 80% 60% at 50% 50%, rgba(0,40,100,0.35) 0%, rgba(0,20,60,0.2) 50%, transparent 100%)",
      }} />

      {/* Login panel */}
      <div style={{
        position: "relative", zIndex: 10,
        width: 420,
        animation: "holoRise 0.8s cubic-bezier(0.16,1,0.3,1) both",
      }}>
        {/* Outer glow frame */}
        <div style={{
          position: "absolute", inset: -1,
          background: "linear-gradient(145deg, rgba(0,229,255,0.25) 0%, rgba(0,255,157,0.15) 50%, rgba(191,95,255,0.2) 100%)",
          borderRadius: 12, filter: "blur(1px)",
          animation: "loginPulse 4s ease-in-out infinite",
        }} />

        {/* Panel body */}
        <div style={{
          position: "relative",
          background: "linear-gradient(160deg, rgba(0,5,18,0.99) 0%, rgba(0,10,28,0.97) 40%, rgba(0,4,16,0.99) 100%)",
          border: "1px solid rgba(0,229,255,0.3)",
          borderRadius: 12,
          padding: "42px 40px 36px",
          backdropFilter: "blur(40px)",
          clipPath: "polygon(0 0, calc(100% - 28px) 0, 100% 28px, 100% 100%, 28px 100%, 0 calc(100% - 28px))",
          boxShadow: "0 40px 120px rgba(0,0,0,0.9), 0 0 80px rgba(0,229,255,0.08), inset 0 1px 0 rgba(255,255,255,0.08), inset 0 0 60px rgba(0,229,255,0.03)",
          overflow: "hidden",
        }}>
          {/* Prismatic top bar */}
          <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 3, background: "linear-gradient(90deg, transparent 0%, rgba(0,229,255,0.8) 20%, rgba(0,255,157,0.6) 50%, rgba(191,95,255,0.5) 80%, transparent 100%)", boxShadow: "0 0 20px rgba(0,229,255,0.5), 0 0 50px rgba(0,229,255,0.2)" }} />
          {/* Left accent bar */}
          <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 4, background: "linear-gradient(180deg, #00e5ff 0%, rgba(0,229,255,0.4) 50%, rgba(191,95,255,0.3) 100%)", boxShadow: "0 0 20px rgba(0,229,255,0.4)" }} />
          {/* Corner cut */}
          <div style={{ position: "absolute", top: 0, right: 28, width: 0, height: 0, borderTop: "28px solid rgba(0,229,255,0.35)", borderLeft: "28px solid transparent" }} />
          {/* Glass reflection */}
          <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: "45%", background: "linear-gradient(180deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0) 100%)", pointerEvents: "none" }} />
          {/* Vertical scan beam */}
          <div style={{ position: "absolute", left: 0, right: 0, height: 1, background: "linear-gradient(90deg, transparent, rgba(0,229,255,0.3), transparent)", animation: "scanV 4s linear infinite", pointerEvents: "none" }} />
          {/* Corner brackets */}
          <div style={{ position: "absolute", top: 10, left: 10, width: 18, height: 18, borderTop: "2px solid rgba(0,229,255,0.5)", borderLeft: "2px solid rgba(0,229,255,0.5)" }} />
          <div style={{ position: "absolute", bottom: 10, right: 10, width: 18, height: 18, borderBottom: "2px solid rgba(0,229,255,0.5)", borderRight: "2px solid rgba(0,229,255,0.5)" }} />

          {/* ── Logo ── */}
          <div style={{ display: "flex", alignItems: "center", gap: 16, marginBottom: 32, position: "relative" }}>
            {/* Animated hex icon */}
            <div style={{ position: "relative", flexShrink: 0 }}>
              <div style={{
                width: 56, height: 56,
                clipPath: "polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)",
                background: "radial-gradient(circle at 35% 35%, rgba(0,229,255,0.35) 0%, rgba(0,229,255,0.08) 100%)",
                border: "1px solid rgba(0,229,255,0.6)",
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 22, color: "#00e5ff", fontFamily: "'Orbitron', monospace",
                boxShadow: "0 0 40px rgba(0,229,255,0.35), 0 0 80px rgba(0,229,255,0.1), inset 0 0 20px rgba(0,229,255,0.12)",
                animation: "pulseGlowLogin 3s ease-in-out infinite",
              }}>Ω</div>
              {/* Rotating orbit ring */}
              <div style={{ position: "absolute", inset: -8, animation: "rotateLogin 6s linear infinite", pointerEvents: "none" }}>
                <div style={{ width: 5, height: 5, borderRadius: "50%", background: "#00ff9d", boxShadow: "0 0 10px #00ff9d", position: "absolute", top: 0, left: "50%", transform: "translateX(-50%)" }} />
              </div>
              <div style={{ position: "absolute", inset: -14, animation: "rotateLogin 10s linear infinite reverse", pointerEvents: "none" }}>
                <div style={{ width: 3, height: 3, borderRadius: "50%", background: "#bf5fff", boxShadow: "0 0 6px #bf5fff", position: "absolute", top: 0, left: "50%", transform: "translateX(-50%)" }} />
              </div>
            </div>
            <div>
              <div style={{ fontFamily: "'Orbitron', monospace", fontSize: 22, fontWeight: 900, color: "#f0faff", letterSpacing: "0.08em", textShadow: "0 0 25px rgba(0,229,255,0.5), 0 0 60px rgba(0,229,255,0.15)", lineHeight: 1 }}>ArcaneOS</div>
              <div style={{ fontSize: 7, color: "rgba(0,229,255,0.45)", letterSpacing: "0.3em", textTransform: "uppercase", marginTop: 5, fontFamily: "'Share Tech Mono', monospace" }}>Admin Console · v2.0</div>
            </div>
          </div>

          {/* Boot progress */}
          <div style={{ marginBottom: 28 }}>
            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5 }}>
              <span style={{ fontSize: 7, color: "rgba(0,212,255,0.4)", letterSpacing: "0.2em", fontFamily: "'Share Tech Mono', monospace" }}>SYSTEM INTEGRITY</span>
              <span style={{ fontSize: 7, color: "#00ff9d", letterSpacing: "0.1em", fontFamily: "'Orbitron', monospace" }}>{bootPct}%</span>
            </div>
            <div style={{ height: 2, background: "rgba(0,229,255,0.08)", borderRadius: 2, overflow: "hidden" }}>
              <div style={{ height: "100%", width: `${bootPct}%`, background: "linear-gradient(90deg, #00e5ff, #00ff9d)", borderRadius: 2, boxShadow: "0 0 10px #00e5ff", transition: "width 0.05s" }} />
            </div>
            <div style={{ marginTop: 6, fontSize: 7, color: "rgba(0,212,255,0.2)", letterSpacing: "0.15em", fontFamily: "'Share Tech Mono', monospace" }}>
              {bootPct < 30 ? "INITIALIZING SUBSYSTEMS…" : bootPct < 60 ? "LOADING SECURITY PROTOCOLS…" : bootPct < 90 ? "ESTABLISHING SECURE CHANNEL…" : "READY FOR AUTHENTICATION"}
            </div>
          </div>

          {/* ── Auth divider ── */}
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 22 }}>
            <div style={{ flex: 1, height: 1, background: "linear-gradient(90deg, transparent, rgba(0,229,255,0.2))" }} />
            <span style={{ fontSize: 7, color: "rgba(0,229,255,0.35)", letterSpacing: "0.25em", fontFamily: "'Share Tech Mono', monospace" }}>CREDENTIALS</span>
            <div style={{ flex: 1, height: 1, background: "linear-gradient(270deg, transparent, rgba(0,229,255,0.2))" }} />
          </div>

          {/* Email */}
          <div style={{ marginBottom: 14, position: "relative" }}>
            <div style={{ fontSize: 7, color: "rgba(0,229,255,0.4)", letterSpacing: "0.2em", fontFamily: "'Share Tech Mono', monospace", marginBottom: 7, display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{ width: 4, height: 4, borderRadius: "50%", background: "#00e5ff", boxShadow: "0 0 6px #00e5ff" }} />
              AGENT IDENTIFIER
            </div>
            <input
              value={email} onChange={e => setEmail(e.target.value)}
              onKeyDown={e => e.key === "Enter" && handleLogin()}
              type="email" placeholder="agent@domain.com"
              className="holo-input"
              style={{ width: "100%", fontSize: 12, padding: "12px 16px" }}
            />
          </div>

          {/* Password */}
          <div style={{ marginBottom: 22, position: "relative" }}>
            <div style={{ fontSize: 7, color: "rgba(0,229,255,0.4)", letterSpacing: "0.2em", fontFamily: "'Share Tech Mono', monospace", marginBottom: 7, display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{ width: 4, height: 4, borderRadius: "50%", background: "#00ff9d", boxShadow: "0 0 6px #00ff9d" }} />
              ACCESS CIPHER
            </div>
            <div style={{ position: "relative" }}>
              <input
                value={password} onChange={e => setPassword(e.target.value)}
                onKeyDown={e => e.key === "Enter" && handleLogin()}
                type={showPw ? "text" : "password"} placeholder="••••••••••••"
                className="holo-input"
                style={{ width: "100%", fontSize: 12, padding: "12px 42px 12px 16px" }}
              />
              <div onClick={() => setShowPw(s => !s)} style={{
                position: "absolute", right: 14, top: "50%", transform: "translateY(-50%)",
                fontSize: 12, color: "rgba(0,229,255,0.4)", cursor: "pointer", userSelect: "none",
              }}>{showPw ? "◉" : "◎"}</div>
            </div>
          </div>

          {/* Error */}
          {error && (
            <div style={{
              marginBottom: 16, padding: "10px 14px",
              background: "rgba(255,45,85,0.06)", border: "1px solid rgba(255,45,85,0.3)",
              borderRadius: 4, fontSize: 9, color: "#ff2d55",
              fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.12em",
              display: "flex", alignItems: "center", gap: 8,
              animation: "errorShake 0.4s ease-in-out",
              boxShadow: "0 0 20px rgba(255,45,85,0.1)",
            }}>
              <span style={{ fontSize: 12, textShadow: "0 0 10px rgba(255,45,85,0.6)" }}>⚠</span>
              {error}
            </div>
          )}

          {/* Login button */}
          <button
            onClick={handleLogin}
            disabled={loading}
            style={{
              width: "100%", padding: "15px 20px",
              background: loading
                ? "rgba(0,229,255,0.04)"
                : "linear-gradient(135deg, rgba(0,229,255,0.16) 0%, rgba(0,255,157,0.08) 50%, rgba(0,229,255,0.12) 100%)",
              border: "1px solid rgba(0,229,255,0.5)",
              borderRadius: 6, cursor: loading ? "wait" : "pointer",
              color: "#00e5ff", fontSize: 11, fontWeight: 700,
              fontFamily: "'Orbitron', monospace", letterSpacing: "0.2em",
              textTransform: "uppercase",
              clipPath: "polygon(0 0, calc(100% - 16px) 0, 100% 16px, 100% 100%, 16px 100%, 0 calc(100% - 16px))",
              boxShadow: loading ? "none" : "0 0 30px rgba(0,229,255,0.2), 0 0 60px rgba(0,229,255,0.08), inset 0 1px 0 rgba(255,255,255,0.08)",
              textShadow: "0 0 14px rgba(0,229,255,0.6)",
              transition: "all 0.3s",
              position: "relative", overflow: "hidden",
            }}
            onMouseEnter={e => { if (!loading) { e.currentTarget.style.background = "linear-gradient(135deg, rgba(0,229,255,0.24) 0%, rgba(0,255,157,0.14) 50%, rgba(0,229,255,0.18) 100%)"; e.currentTarget.style.boxShadow = "0 0 50px rgba(0,229,255,0.35), 0 0 100px rgba(0,229,255,0.12), inset 0 1px 0 rgba(255,255,255,0.1)"; e.currentTarget.style.transform = "translateY(-2px)"; } }}
            onMouseLeave={e => { e.currentTarget.style.background = "linear-gradient(135deg, rgba(0,229,255,0.16) 0%, rgba(0,255,157,0.08) 50%, rgba(0,229,255,0.12) 100%)"; e.currentTarget.style.boxShadow = "0 0 30px rgba(0,229,255,0.2), 0 0 60px rgba(0,229,255,0.08), inset 0 1px 0 rgba(255,255,255,0.08)"; e.currentTarget.style.transform = "translateY(0)"; }}
          >
            {/* Shimmer */}
            <div style={{ position: "absolute", inset: 0, left: "-100%", width: "50%", background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.06), transparent)", animation: "loginShimmer 3s ease-in-out 1s infinite", pointerEvents: "none" }} />
            {loading ? (
              <div style={{ display: "flex", alignItems: "center", justifyContent: "center", gap: 10 }}>
                <div style={{ width: 14, height: 14, borderRadius: "50%", border: "2px solid rgba(0,229,255,0.3)", borderTop: "2px solid #00e5ff", animation: "rotateLogin 0.8s linear infinite" }} />
                AUTHENTICATING…
              </div>
            ) : "INITIATE SESSION"}
          </button>

          {/* Bottom status */}
          <div style={{ marginTop: 20, display: "flex", alignItems: "center", justifyContent: "center", gap: 8, fontSize: 7, color: "rgba(0,212,255,0.2)", fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.15em" }}>
            <div style={{ width: 4, height: 4, borderRadius: "50%", background: "#00ff9d", boxShadow: "0 0 6px #00ff9d", animation: "pulseGlowLogin 2s infinite" }} />
            ENCRYPTED CHANNEL · TLS 1.3 · ARCANEOS v2.0
          </div>
        </div>
      </div>
    </div>
  );
}

// ── COMMAND PALETTE — ⌘K holographic search overlay ─────────────────────────
function CommandPalette({ open, onClose, onNavigate, tabs, m }) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(0);
  const inputRef = useRef(null);

  useEffect(() => {
    if (open) { setQuery(""); setSelected(0); setTimeout(() => inputRef.current?.focus(), 60); }
  }, [open]);

  // Build command list
  const COMMANDS = [
    ...tabs.map(t => ({ id: t.id, label: t.label, icon: t.icon, category: "NAVIGATION", action: () => { onNavigate(t.id); onClose(); } })),
    { id: "refresh", label: "Refresh Data", icon: "↺", category: "ACTIONS", action: () => { window.location.reload(); onClose(); } },
    { id: "logout",  label: "Terminate Session", icon: "⏻", category: "ACTIONS", action: () => { localStorage.removeItem("access_token"); window.location.reload(); } },
    m && { id: "mrr",   label: `MRR: $${m.revenue?.mrr}`, icon: "◎", category: "METRICS", action: () => { onNavigate("revenue"); onClose(); } },
    m && { id: "users", label: `Users: ${m.users?.total} total`, icon: "⬡", category: "METRICS", action: () => { onNavigate("users"); onClose(); } },
    m && { id: "tasks", label: `Tasks Today: ${m.tasks?.created_today}`, icon: "✦", category: "METRICS", action: () => { onNavigate("overview"); onClose(); } },
  ].filter(Boolean);

  const filtered = query
    ? COMMANDS.filter(c => c.label.toLowerCase().includes(query.toLowerCase()) || c.category.toLowerCase().includes(query.toLowerCase()))
    : COMMANDS;

  useEffect(() => { setSelected(0); }, [query]);

  useEffect(() => {
    if (!open) return;
    const handler = (e) => {
      if (e.key === "Escape") onClose();
      if (e.key === "ArrowDown") { e.preventDefault(); setSelected(s => Math.min(s + 1, filtered.length - 1)); }
      if (e.key === "ArrowUp") { e.preventDefault(); setSelected(s => Math.max(s - 1, 0)); }
      if (e.key === "Enter" && filtered[selected]) { filtered[selected].action(); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, selected, filtered, onClose]);

  if (!open) return null;

  // Group by category
  const grouped = filtered.reduce((acc, cmd) => {
    if (!acc[cmd.category]) acc[cmd.category] = [];
    acc[cmd.category].push(cmd);
    return acc;
  }, {});

  let globalIdx = 0;

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed", inset: 0, zIndex: 9998,
        background: "rgba(0,2,10,0.75)",
        backdropFilter: "blur(8px)",
        display: "flex", alignItems: "flex-start", justifyContent: "center",
        paddingTop: "15vh",
        animation: "paletteFadeIn 0.15s ease-out both",
      }}>
      <div onClick={e => e.stopPropagation()} style={{
        width: 580, maxWidth: "90vw",
        background: "linear-gradient(160deg, rgba(0,5,20,0.99) 0%, rgba(0,10,28,0.98) 50%, rgba(0,4,16,0.99) 100%)",
        border: "1px solid rgba(0,229,255,0.35)",
        borderRadius: 10,
        clipPath: "polygon(0 0, calc(100% - 24px) 0, 100% 24px, 100% 100%, 24px 100%, 0 calc(100% - 24px))",
        boxShadow: "0 0 0 1px rgba(0,229,255,0.06), 0 40px 120px rgba(0,0,0,0.95), 0 0 100px rgba(0,229,255,0.1), inset 0 1px 0 rgba(255,255,255,0.08)",
        animation: "paletteRise 0.2s cubic-bezier(0.16,1,0.3,1) both",
        overflow: "hidden",
      }}>

        {/* Prismatic top edge */}
        <div style={{ height: 2, background: "linear-gradient(90deg, transparent, rgba(0,229,255,0.9), rgba(0,255,157,0.6), rgba(191,95,255,0.5), transparent)", boxShadow: "0 0 20px rgba(0,229,255,0.6), 0 0 50px rgba(0,229,255,0.2)" }} />

        {/* Corner cuts */}
        <div style={{ position: "absolute", top: 2, right: 24, width: 0, height: 0, borderTop: "24px solid rgba(0,229,255,0.4)", borderLeft: "24px solid transparent" }} />
        <div style={{ position: "absolute", bottom: 0, left: 24, width: 0, height: 0, borderBottom: "16px solid rgba(0,229,255,0.2)", borderRight: "16px solid transparent" }} />

        {/* Search input */}
        <div style={{ display: "flex", alignItems: "center", gap: 14, padding: "16px 20px", borderBottom: "1px solid rgba(0,229,255,0.1)", position: "relative" }}>
          {/* Left icon */}
          <div style={{
            width: 32, height: 32, flexShrink: 0,
            clipPath: "polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)",
            background: "rgba(0,229,255,0.1)", border: "1px solid rgba(0,229,255,0.35)",
            display: "flex", alignItems: "center", justifyContent: "center",
            fontSize: 13, color: "#00e5ff", textShadow: "0 0 10px rgba(0,229,255,0.6)",
          }}>◈</div>

          <input
            ref={inputRef}
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Command or search…"
            style={{
              flex: 1, background: "transparent", border: "none", outline: "none",
              color: "#e0f8ff", fontSize: 15, fontFamily: "'Rajdhani', sans-serif",
              fontWeight: 500, letterSpacing: "0.04em",
              caretColor: "#00e5ff",
            }}
          />

          {/* Kbd hint */}
          <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
            {["ESC"].map(k => (
              <kbd key={k} style={{
                fontSize: 8, color: "rgba(0,229,255,0.35)", fontFamily: "'Share Tech Mono', monospace",
                background: "rgba(0,229,255,0.05)", border: "1px solid rgba(0,229,255,0.15)",
                padding: "2px 6px", borderRadius: 3, letterSpacing: "0.1em",
              }}>{k}</kbd>
            ))}
          </div>
        </div>

        {/* Results */}
        <div style={{ maxHeight: 360, overflowY: "auto", padding: "8px 0" }}>
          {Object.entries(grouped).map(([category, cmds]) => (
            <div key={category}>
              {/* Category header */}
              <div style={{ padding: "8px 20px 4px", fontSize: 6, color: "rgba(0,229,255,0.25)", letterSpacing: "0.28em", fontFamily: "'Share Tech Mono', monospace", textTransform: "uppercase" }}>
                {category}
              </div>
              {cmds.map((cmd) => {
                const idx = globalIdx++;
                const isSel = selected === idx;
                const catColors = { NAVIGATION: "#00e5ff", ACTIONS: "#ff2d55", METRICS: "#ffd060" };
                const cc = catColors[category] || "#00e5ff";
                return (
                  <div key={cmd.id} onClick={cmd.action}
                    onMouseEnter={() => setSelected(idx)}
                    style={{
                      display: "flex", alignItems: "center", gap: 14,
                      padding: "10px 20px", cursor: "pointer",
                      background: isSel ? `rgba(0,229,255,0.07)` : "transparent",
                      boxShadow: isSel ? "inset 3px 0 0 rgba(0,229,255,0.5)" : "none",
                      transition: "all 0.1s",
                      position: "relative",
                    }}>
                    {/* Icon */}
                    <div style={{
                      width: 28, height: 28, flexShrink: 0,
                      background: isSel ? `rgba(0,229,255,0.1)` : "rgba(0,229,255,0.04)",
                      border: `1px solid rgba(0,229,255,${isSel ? 0.3 : 0.1})`,
                      borderRadius: 4, display: "flex", alignItems: "center", justifyContent: "center",
                      fontSize: 12, color: isSel ? cc : "rgba(0,212,255,0.4)",
                      textShadow: isSel ? `0 0 8px ${cc}` : "none",
                      transition: "all 0.15s",
                    }}>{cmd.icon}</div>

                    {/* Label */}
                    <span style={{
                      flex: 1, fontSize: 12, fontFamily: "'Rajdhani', sans-serif", fontWeight: 500,
                      color: isSel ? "#f0faff" : "rgba(180,220,240,0.7)",
                      letterSpacing: "0.04em",
                      transition: "color 0.1s",
                    }}>{cmd.label}</span>

                    {/* Enter hint when selected */}
                    {isSel && (
                      <kbd style={{
                        fontSize: 8, color: "rgba(0,229,255,0.5)", fontFamily: "'Share Tech Mono', monospace",
                        background: "rgba(0,229,255,0.07)", border: "1px solid rgba(0,229,255,0.2)",
                        padding: "2px 7px", borderRadius: 3, letterSpacing: "0.08em",
                        animation: "holoRise 0.15s ease-out both",
                      }}>↵ ENTER</kbd>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
          {filtered.length === 0 && (
            <div style={{ padding: "40px 20px", textAlign: "center", color: "rgba(0,229,255,0.2)", fontFamily: "'Share Tech Mono', monospace", fontSize: 10, letterSpacing: "0.2em" }}>
              NO COMMANDS MATCH
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{ padding: "8px 20px", borderTop: "1px solid rgba(0,229,255,0.07)", display: "flex", alignItems: "center", gap: 14 }}>
          {[["↑↓", "navigate"], ["↵", "select"], ["ESC", "close"]].map(([key, desc]) => (
            <div key={key} style={{ display: "flex", alignItems: "center", gap: 5 }}>
              <kbd style={{ fontSize: 7, color: "rgba(0,229,255,0.4)", fontFamily: "'Share Tech Mono', monospace", background: "rgba(0,229,255,0.05)", border: "1px solid rgba(0,229,255,0.12)", padding: "2px 6px", borderRadius: 3 }}>{key}</kbd>
              <span style={{ fontSize: 7, color: "rgba(0,229,255,0.2)", fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.1em" }}>{desc}</span>
            </div>
          ))}
          <div style={{ marginLeft: "auto", fontSize: 7, color: "rgba(0,229,255,0.15)", fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.15em" }}>ARCANEOS COMMAND BRIDGE</div>
        </div>
      </div>
    </div>
  );
}

// ── USER DETAIL DRAWER — slide-in panel from right ───────────────────────────
function UserDetailDrawer({ user, open, onClose, showToast, onToggleActive }) {
  const { dark } = useTheme();
  const cyan = dark ? "0,229,255" : "0,120,200";
  const cyanHex = dark ? "#00e5ff" : "#0088cc";
  const panelBg = dark
    ? "linear-gradient(160deg, rgba(0,5,20,0.99) 0%, rgba(0,12,32,0.97) 100%)"
    : "linear-gradient(160deg, rgba(215,235,255,0.99) 0%, rgba(200,225,250,0.97) 100%)";
  const textPrimary = dark ? "#e8f6ff" : "#0a1a2e";
  const textDim = dark ? "rgba(0,229,255,0.4)" : "rgba(0,80,160,0.5)";

  if (!user) return null;

  const isRoot = user.email === "wahaj@acedengroup.com";
  const accentColor = isRoot ? "#ffd060" : user.is_active ? cyanHex : "#ff2d55";
  const accentRgb = isRoot ? "255,208,96" : user.is_active ? cyan : "255,45,85";

  const joinDate = user.created_at ? new Date(user.created_at) : null;
  const daysAgo = joinDate ? Math.floor((Date.now() - joinDate) / 86400000) : null;

  // Simulated activity metrics
  const seed = (user.id || 1);
  const taskCount = ((seed * 17) % 80) + 5;
  const sessionCount = ((seed * 11) % 40) + 3;
  const lastActive = `${((seed * 7) % 23) + 1}h ago`;

  const statItems = [
    { label: "TASKS", value: taskCount, color: "#00e5ff", rgb: "0,229,255", icon: "✦" },
    { label: "SESSIONS", value: sessionCount, color: "#bf5fff", rgb: "191,95,255", icon: "◎" },
    { label: "LAST SEEN", value: lastActive, color: "#00ff9d", rgb: "0,255,157", icon: "◈", isText: true },
    { label: "TENURE", value: daysAgo != null ? `${daysAgo}d` : "—", color: "#ffd060", rgb: "255,208,96", icon: "⬡", isText: true },
  ];

  return (
    <>
      {/* Backdrop */}
      {open && (
        <div
          onClick={onClose}
          style={{
            position: "fixed", inset: 0, zIndex: 8000,
            background: "rgba(0,2,10,0.55)",
            backdropFilter: "blur(4px)",
            animation: "fadeIn 0.2s ease-out both",
          }}
        />
      )}
      {/* Drawer panel */}
      <div style={{
        position: "fixed", top: 0, right: 0, bottom: 0, zIndex: 8001,
        width: 420, maxWidth: "90vw",
        background: panelBg,
        borderLeft: `1px solid rgba(${accentRgb},0.35)`,
        boxShadow: dark
          ? `-20px 0 80px rgba(0,0,0,0.8), -4px 0 0 rgba(${accentRgb},0.08), inset 1px 0 0 rgba(255,255,255,0.04)`
          : `-12px 0 50px rgba(0,60,180,0.15)`,
        transform: open ? "translateX(0)" : "translateX(100%)",
        transition: "transform 0.4s cubic-bezier(0.16,1,0.3,1)",
        display: "flex", flexDirection: "column",
        overflow: "hidden",
      }}>
        {/* Top prismatic edge */}
        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2, background: `linear-gradient(90deg, transparent, rgba(${accentRgb},0.9), rgba(0,229,255,0.5), transparent)`, boxShadow: `0 0 20px rgba(${accentRgb},0.5)`, zIndex: 1 }} />
        {/* Ambient glow blobs */}
        <div style={{ position: "absolute", top: -80, right: -80, width: 280, height: 280, borderRadius: "50%", background: `radial-gradient(circle, rgba(${accentRgb},0.06) 0%, transparent 70%)`, pointerEvents: "none" }} />
        <div style={{ position: "absolute", bottom: 80, left: -60, width: 200, height: 200, borderRadius: "50%", background: `radial-gradient(circle, rgba(0,229,255,0.04) 0%, transparent 70%)`, pointerEvents: "none" }} />
        {/* Scan beam */}
        <div style={{ position: "absolute", left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, rgba(${accentRgb},0.2), transparent)`, animation: "scanV 5s linear infinite", pointerEvents: "none", zIndex: 0 }} />

        {/* ── Header ── */}
        <div style={{
          padding: "22px 24px 18px",
          borderBottom: `1px solid rgba(${accentRgb},0.12)`,
          background: `rgba(${accentRgb},0.03)`,
          position: "relative", flexShrink: 0,
        }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 20 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
              <div style={{ width: 4, height: 4, borderRadius: "50%", background: accentColor, boxShadow: `0 0 8px ${accentColor}`, animation: "pulse-glow 1.5s infinite" }} />
              <span style={{ fontSize: 7, color: textDim, letterSpacing: "0.28em", fontFamily: "'Share Tech Mono', monospace", textTransform: "uppercase" }}>Agent Profile</span>
            </div>
            <button onClick={onClose} style={{
              width: 28, height: 28, borderRadius: "50%", border: `1px solid rgba(${cyan},0.2)`,
              background: "transparent", cursor: "pointer", color: `rgba(${cyan},0.4)`,
              fontSize: 10, fontFamily: "'Share Tech Mono', monospace",
              display: "flex", alignItems: "center", justifyContent: "center",
              transition: "all 0.2s",
            }}
              onMouseEnter={e => { e.currentTarget.style.background = `rgba(${cyan},0.08)`; e.currentTarget.style.borderColor = `rgba(${cyan},0.4)`; e.currentTarget.style.color = cyanHex; }}
              onMouseLeave={e => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.borderColor = `rgba(${cyan},0.2)`; e.currentTarget.style.color = `rgba(${cyan},0.4)`; }}
            >✕</button>
          </div>

          {/* Avatar + name block */}
          <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
            <div style={{ position: "relative" }}>
              <HoloAvatar name={user.name} email={user.email} isActive={user.is_active} isRoot={isRoot} size={64} />
              {/* Status ring glow */}
              <div style={{ position: "absolute", inset: -4, borderRadius: "50%", border: `2px solid rgba(${accentRgb},0.3)`, boxShadow: `0 0 16px rgba(${accentRgb},0.2)`, pointerEvents: "none" }} />
            </div>
            <div>
              <div style={{ fontFamily: "'Orbitron', monospace", fontSize: 16, fontWeight: 800, color: textPrimary, letterSpacing: "0.05em", textShadow: dark ? `0 0 20px rgba(${accentRgb},0.4)` : "none", lineHeight: 1.1 }}>
                {user.name || "Unknown Agent"}
              </div>
              {isRoot && <div style={{ fontSize: 7, color: "#ffd060", letterSpacing: "0.2em", fontFamily: "'Share Tech Mono', monospace", marginTop: 4, textShadow: "0 0 8px rgba(255,208,96,0.5)" }}>♛ ROOT ADMINISTRATOR</div>}
              <div style={{ fontSize: 9, color: textDim, fontFamily: "'Share Tech Mono', monospace", marginTop: 6, letterSpacing: "0.04em" }}>{user.email}</div>
              <div style={{ display: "flex", gap: 6, marginTop: 8 }}>
                <TierBadge status={user.subscription_status} />
                <RoleChip role={user.role} />
              </div>
            </div>
          </div>
        </div>

        {/* ── Scrollable body ── */}
        <div style={{ flex: 1, overflowY: "auto", padding: "20px 24px" }}>

          {/* Status indicator */}
          <div style={{
            display: "flex", alignItems: "center", gap: 10, padding: "10px 14px",
            background: user.is_active ? `rgba(0,255,157,0.04)` : `rgba(255,45,85,0.04)`,
            border: `1px solid ${user.is_active ? "rgba(0,255,157,0.2)" : "rgba(255,45,85,0.2)"}`,
            borderRadius: 5, marginBottom: 18,
            clipPath: "polygon(0 0, calc(100% - 8px) 0, 100% 8px, 100% 100%, 0 100%)",
          }}>
            <div style={{ width: 7, height: 7, borderRadius: "50%", background: user.is_active ? "#00ff9d" : "#ff2d55", boxShadow: `0 0 10px ${user.is_active ? "#00ff9d" : "#ff2d55"}`, animation: user.is_active ? "pulse-glow 1.2s infinite" : "none" }} />
            <span style={{ fontSize: 9, color: user.is_active ? "#00ff9d" : "#ff2d55", fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.18em", fontWeight: 700 }}>{user.is_active ? "ACTIVE · ONLINE" : "INACTIVE · OFFLINE"}</span>
            <div style={{ flex: 1 }} />
            <span style={{ fontSize: 7, color: textDim, fontFamily: "'Share Tech Mono', monospace" }}>ID: {user.id}</span>
          </div>

          {/* Stats grid */}
          <div style={{ fontSize: 7, color: textDim, letterSpacing: "0.22em", fontFamily: "'Share Tech Mono', monospace", marginBottom: 10, display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ width: 3, height: 3, background: cyanHex, borderRadius: "50%" }} />
            Agent Metrics
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8, marginBottom: 20 }}>
            {statItems.map(({ label, value, color, rgb, icon, isText }) => (
              <div key={label} style={{
                padding: "12px 14px",
                background: `rgba(${rgb},0.04)`,
                border: `1px solid rgba(${rgb},0.18)`,
                borderRadius: 4,
                clipPath: "polygon(0 0, calc(100% - 8px) 0, 100% 8px, 100% 100%, 0 100%)",
                position: "relative", overflow: "hidden",
              }}>
                <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, rgba(${rgb},0.6), transparent)` }} />
                <div style={{ display: "flex", alignItems: "center", gap: 5, marginBottom: 5 }}>
                  <span style={{ fontSize: 9, color: `rgba(${rgb},0.5)` }}>{icon}</span>
                  <span style={{ fontSize: 6, color: `rgba(${rgb},0.4)`, letterSpacing: "0.2em", fontFamily: "'Share Tech Mono', monospace" }}>{label}</span>
                </div>
                <div style={{ fontSize: isText ? 14 : 22, fontWeight: 900, color, fontFamily: "'Orbitron', monospace", textShadow: `0 0 12px rgba(${rgb},0.5)`, letterSpacing: isText ? "0.04em" : "-0.02em" }}>{value}</div>
              </div>
            ))}
          </div>

          {/* Joined info */}
          <div style={{ fontSize: 7, color: textDim, letterSpacing: "0.22em", fontFamily: "'Share Tech Mono', monospace", marginBottom: 10, display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ width: 3, height: 3, background: cyanHex, borderRadius: "50%" }} />
            Access Timeline
          </div>
          <div style={{
            padding: "14px 16px", marginBottom: 20,
            background: dark ? "rgba(0,229,255,0.02)" : "rgba(0,120,200,0.04)",
            border: `1px solid rgba(${cyan},0.12)`,
            borderRadius: 4, fontFamily: "'Share Tech Mono', monospace",
            clipPath: "polygon(0 0, calc(100% - 10px) 0, 100% 10px, 100% 100%, 0 100%)",
          }}>
            {[
              ["Registered", joinDate ? joinDate.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "—"],
              ["Last Login", lastActive],
              ["Subscription", user.subscription_status?.toUpperCase() || "NONE"],
              ["Role Level", user.role?.toUpperCase() || "STANDARD"],
            ].map(([label, val]) => (
              <div key={label} style={{ display: "flex", justifyContent: "space-between", padding: "5px 0", borderBottom: `1px solid rgba(${cyan},0.05)` }}>
                <span style={{ fontSize: 8, color: textDim, letterSpacing: "0.12em" }}>{label}</span>
                <span style={{ fontSize: 8, color: textPrimary, letterSpacing: "0.06em", fontWeight: 600 }}>{val}</span>
              </div>
            ))}
          </div>

          {/* Activity waveform simulation */}
          <div style={{ fontSize: 7, color: textDim, letterSpacing: "0.22em", fontFamily: "'Share Tech Mono', monospace", marginBottom: 10, display: "flex", alignItems: "center", gap: 8 }}>
            <div style={{ width: 3, height: 3, background: accentColor, borderRadius: "50%" }} />
            Activity Pattern
          </div>
          <div style={{ display: "flex", gap: 3, alignItems: "flex-end", height: 48, marginBottom: 20, padding: "0 2px" }}>
            {Array.from({ length: 28 }).map((_, i) => {
              const h = Math.max(4, Math.sin(i * 0.7 + (seed % 10) * 0.4) * 18 + 20 + ((seed * i) % 12));
              const active = i > 20;
              return (
                <div key={i} style={{
                  flex: 1, height: h, borderRadius: 2,
                  background: active ? `rgba(${accentRgb},0.7)` : `rgba(${cyan},0.12)`,
                  boxShadow: active ? `0 0 6px rgba(${accentRgb},0.3)` : "none",
                  transition: "height 0.3s",
                }} />
              );
            })}
          </div>
        </div>

        {/* ── Footer actions ── */}
        {!isRoot && (
          <div style={{ padding: "16px 24px", borderTop: `1px solid rgba(${cyan},0.08)`, flexShrink: 0, background: `rgba(${cyan},0.02)` }}>
            <div style={{ fontSize: 7, color: textDim, letterSpacing: "0.2em", fontFamily: "'Share Tech Mono', monospace", marginBottom: 10 }}>
              AGENT CONTROLS
            </div>
            <div style={{ display: "flex", gap: 8 }}>
              <button
                onClick={() => { onToggleActive(user.id, user.is_active, user.name); onClose(); }}
                style={{
                  flex: 1, padding: "10px 14px", fontSize: 8, fontFamily: "'Share Tech Mono', monospace",
                  letterSpacing: "0.14em", fontWeight: 700, cursor: "pointer",
                  background: user.is_active
                    ? "linear-gradient(135deg, rgba(255,45,85,0.1) 0%, rgba(255,45,85,0.04) 100%)"
                    : "linear-gradient(135deg, rgba(0,255,157,0.1) 0%, rgba(0,255,157,0.04) 100%)",
                  border: `1px solid ${user.is_active ? "rgba(255,45,85,0.4)" : "rgba(0,255,157,0.4)"}`,
                  color: user.is_active ? "#ff2d55" : "#00ff9d",
                  borderRadius: 4,
                  clipPath: "polygon(0 0, calc(100% - 6px) 0, 100% 6px, 100% 100%, 0 100%)",
                  transition: "all 0.2s",
                }}
                onMouseEnter={e => { e.currentTarget.style.transform = "translateY(-1px)"; }}
                onMouseLeave={e => { e.currentTarget.style.transform = "translateY(0)"; }}
              >
                {user.is_active ? "⬡ DEACTIVATE" : "⬡ ACTIVATE"}
              </button>
              <button
                onClick={() => { showToast?.(`Message sent to ${user.name || user.email}`, "info"); }}
                style={{
                  flex: 1, padding: "10px 14px", fontSize: 8, fontFamily: "'Share Tech Mono', monospace",
                  letterSpacing: "0.14em", fontWeight: 700, cursor: "pointer",
                  background: `rgba(${cyan},0.06)`,
                  border: `1px solid rgba(${cyan},0.25)`,
                  color: cyanHex, borderRadius: 4,
                  clipPath: "polygon(0 0, calc(100% - 6px) 0, 100% 6px, 100% 100%, 0 100%)",
                  transition: "all 0.2s",
                }}
                onMouseEnter={e => { e.currentTarget.style.transform = "translateY(-1px)"; e.currentTarget.style.background = `rgba(${cyan},0.12)`; }}
                onMouseLeave={e => { e.currentTarget.style.transform = "translateY(0)"; e.currentTarget.style.background = `rgba(${cyan},0.06)`; }}
              >
                ◆ TRANSMIT
              </button>
            </div>
          </div>
        )}
      </div>
    </>
  );
}

// ── WORKSPACE HEALTH MAP — node-graph visualization ───────────────────────────
function WorkspaceHealthMap({ workspaces }) {
  const canvasRef = useRef(null);
  const animRef = useRef(null);
  const { dark } = useTheme();

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || !workspaces?.length) return;
    const ctx = canvas.getContext("2d");
    const dpr = window.devicePixelRatio || 1;
    const W = canvas.offsetWidth;
    const H = canvas.offsetHeight;
    canvas.width = W * dpr;
    canvas.height = H * dpr;
    ctx.scale(dpr, dpr);

    // Lay out nodes in a force-inspired grid
    const nodes = workspaces.slice(0, 18).map((ws, i) => {
      const members = ws.member_count || 0;
      const tasks = ws.task_count || 0;
      const memberScore = Math.min(members / 20, 1);
      const taskScore = Math.min(tasks / 50, 1);
      const health = ws.is_active ? Math.round((memberScore * 0.4 + taskScore * 0.6) * 100) : 0;
      const r = 14 + (health / 100) * 18;
      const color = !ws.is_active ? "#ff2d55" : health > 70 ? "#00ff9d" : health > 35 ? "#ffd060" : "#ff6b35";
      const rgb = !ws.is_active ? "255,45,85" : health > 70 ? "0,255,157" : health > 35 ? "255,208,96" : "255,107,53";
      // Arrange in a loose scattered layout
      const cols = 6;
      const row = Math.floor(i / cols), col = i % cols;
      const jitterX = ((ws.id || i) * 37) % 40 - 20;
      const jitterY = ((ws.id || i) * 53) % 30 - 15;
      return {
        id: ws.id, name: ws.name || `WS-${i}`, health, r,
        color, rgb, ws,
        members, tasks, active: ws.is_active,
        x: 60 + col * ((W - 120) / (cols - 1)) + jitterX,
        y: 50 + row * 90 + jitterY,
        vx: 0, vy: 0,
        pulsePhase: Math.random() * Math.PI * 2,
      };
    });

    let t = 0;
    function draw() {
      t += 0.015;
      ctx.clearRect(0, 0, W, H);

      // Background grid
      ctx.strokeStyle = dark ? "rgba(0,229,255,0.04)" : "rgba(0,120,200,0.06)";
      ctx.lineWidth = 0.5;
      for (let x = 0; x < W; x += 40) { ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, H); ctx.stroke(); }
      for (let y = 0; y < H; y += 40) { ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke(); }

      // Draw connection lines between nearby nodes
      nodes.forEach((a, i) => {
        nodes.slice(i + 1).forEach(b => {
          const d = Math.hypot(a.x - b.x, a.y - b.y);
          if (d < 160) {
            const alpha = (1 - d / 160) * 0.15;
            const pulse = 0.5 + Math.sin(t * 1.2 + i * 0.5) * 0.3;
            ctx.strokeStyle = `rgba(0,229,255,${alpha * pulse})`;
            ctx.lineWidth = 0.8;
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
          }
        });
      });

      // Draw nodes
      nodes.forEach(node => {
        const pulse = 0.5 + Math.sin(t * 1.8 + node.pulsePhase) * 0.5;

        // Outer glow halo
        const glow = ctx.createRadialGradient(node.x, node.y, 0, node.x, node.y, node.r * 3);
        glow.addColorStop(0, `rgba(${node.rgb},${0.12 * pulse})`);
        glow.addColorStop(1, `rgba(${node.rgb},0)`);
        ctx.fillStyle = glow;
        ctx.beginPath(); ctx.arc(node.x, node.y, node.r * 3, 0, Math.PI * 2); ctx.fill();

        // Pulsing ring
        if (node.active) {
          ctx.beginPath();
          ctx.arc(node.x, node.y, node.r + 4 + pulse * 5, 0, Math.PI * 2);
          ctx.strokeStyle = `rgba(${node.rgb},${0.2 * pulse})`;
          ctx.lineWidth = 1.5;
          ctx.stroke();
        }

        // Main circle — health arc background
        ctx.beginPath(); ctx.arc(node.x, node.y, node.r, 0, Math.PI * 2);
        ctx.fillStyle = dark ? `rgba(0,5,20,0.85)` : `rgba(220,238,255,0.9)`;
        ctx.fill();
        ctx.strokeStyle = `rgba(${node.rgb},0.5)`;
        ctx.lineWidth = 1.5;
        ctx.stroke();

        // Health arc
        if (node.health > 0) {
          ctx.beginPath();
          ctx.arc(node.x, node.y, node.r, -Math.PI / 2, -Math.PI / 2 + (node.health / 100) * Math.PI * 2);
          ctx.strokeStyle = node.color;
          ctx.lineWidth = 2.5;
          ctx.shadowColor = node.color;
          ctx.shadowBlur = 8;
          ctx.stroke();
          ctx.shadowBlur = 0;
        }

        // Center dot
        ctx.beginPath(); ctx.arc(node.x, node.y, 3, 0, Math.PI * 2);
        ctx.fillStyle = node.color;
        ctx.shadowColor = node.color; ctx.shadowBlur = 10;
        ctx.fill(); ctx.shadowBlur = 0;

        // Label
        const label = node.name.length > 10 ? node.name.slice(0, 9) + "…" : node.name;
        ctx.fillStyle = dark ? "rgba(200,230,255,0.7)" : "rgba(10,40,80,0.7)";
        ctx.font = `500 8px 'Share Tech Mono', monospace`;
        ctx.textAlign = "center";
        ctx.fillText(label, node.x, node.y + node.r + 12);

        // Health % below label
        ctx.fillStyle = node.color;
        ctx.font = `700 8px 'Orbitron', monospace`;
        ctx.fillText(`${node.health}%`, node.x, node.y + node.r + 22);
      });

      animRef.current = requestAnimationFrame(draw);
    }
    draw();
    return () => cancelAnimationFrame(animRef.current);
  }, [workspaces, dark]);

  // Legend
  const legend = [
    { color: "#00ff9d", rgb: "0,255,157", label: "HEALTHY >70%" },
    { color: "#ffd060", rgb: "255,208,96", label: "MODERATE 35–70%" },
    { color: "#ff6b35", rgb: "255,107,53", label: "LOW <35%" },
    { color: "#ff2d55", rgb: "255,45,85", label: "INACTIVE" },
  ];

  return (
    <div>
      {/* Legend */}
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginBottom: 14 }}>
        {legend.map(({ color, rgb, label }) => (
          <div key={label} style={{ display: "flex", alignItems: "center", gap: 5 }}>
            <div style={{ width: 6, height: 6, borderRadius: "50%", background: color, boxShadow: `0 0 6px ${color}` }} />
            <span style={{ fontSize: 7, color: `rgba(${rgb},0.55)`, fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.1em" }}>{label}</span>
          </div>
        ))}
        <div style={{ marginLeft: "auto", fontSize: 7, color: "rgba(0,229,255,0.25)", fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.12em" }}>
          {workspaces?.length || 0} NODES MAPPED
        </div>
      </div>
      {/* Canvas */}
      <div style={{ position: "relative", borderRadius: 6, overflow: "hidden", border: "1px solid rgba(0,229,255,0.1)" }}>
        <canvas
          ref={canvasRef}
          style={{ display: "block", width: "100%", height: 260 }}
        />
      </div>
    </div>
  );
}

// ── SYSTEM STATUS PULSE BAR — real-time API latency / uptime / error gauges ──
function SystemStatusPulseBar() {
  const { dark } = useTheme();
  const cyan = dark ? "0,229,255" : "0,120,200";
  const cyanHex = dark ? "#00e5ff" : "#0088cc";

  // Simulate real-time telemetry
  const [metrics, setMetrics] = useState({
    apiLatency: 42,
    uptime: 99.97,
    errorRate: 0.03,
    throughput: 1247,
    p99: 118,
    activeConns: 84,
  });
  const [history, setHistory] = useState({
    latency: Array.from({ length: 28 }, () => 30 + Math.random() * 60),
    errors:  Array.from({ length: 28 }, () => Math.random() * 0.08),
  });
  const [collapsed, setCollapsed] = useState(false);
  const sparkRef = useRef(null);
  const errRef = useRef(null);

  useEffect(() => {
    const id = setInterval(() => {
      const lat = 28 + Math.random() * 90 + (Math.random() > 0.92 ? 200 : 0);
      const err = Math.random() * 0.06 + (Math.random() > 0.96 ? 0.4 : 0);
      setMetrics(prev => ({
        apiLatency: Math.round(lat),
        uptime: Math.min(100, prev.uptime + (Math.random() - 0.3) * 0.001),
        errorRate: parseFloat(err.toFixed(3)),
        throughput: Math.round(1100 + Math.random() * 400),
        p99: Math.round(lat * 2.4),
        activeConns: Math.round(60 + Math.random() * 60),
      }));
      setHistory(prev => ({
        latency: [...prev.latency.slice(1), lat],
        errors:  [...prev.errors.slice(1), err],
      }));
    }, 1800);
    return () => clearInterval(id);
  }, []);

  // Draw sparkline
  useEffect(() => {
    [
      { ref: sparkRef, data: history.latency, color: "#00e5ff", max: 250 },
      { ref: errRef,   data: history.errors,  color: "#ff2d55", max: 0.5  },
    ].forEach(({ ref, data, color, max }) => {
      const canvas = ref.current;
      if (!canvas) return;
      const ctx = canvas.getContext("2d");
      const W = canvas.width = canvas.offsetWidth * 2;
      const H = canvas.height = canvas.offsetHeight * 2;
      ctx.clearRect(0, 0, W, H);
      const pts = data.map((v, i) => ({
        x: (i / (data.length - 1)) * W,
        y: H - (Math.min(v, max) / max) * H * 0.85 - H * 0.05,
      }));
      // Fill
      const grad = ctx.createLinearGradient(0, 0, 0, H);
      grad.addColorStop(0, color + "55");
      grad.addColorStop(1, color + "00");
      ctx.beginPath();
      ctx.moveTo(pts[0].x, H);
      pts.forEach((p, i) => {
        if (i === 0) { ctx.lineTo(p.x, p.y); return; }
        const prev = pts[i-1];
        ctx.bezierCurveTo((prev.x+p.x)/2, prev.y, (prev.x+p.x)/2, p.y, p.x, p.y);
      });
      ctx.lineTo(pts[pts.length-1].x, H);
      ctx.closePath();
      ctx.fillStyle = grad;
      ctx.fill();
      // Line
      ctx.beginPath();
      ctx.moveTo(pts[0].x, pts[0].y);
      pts.forEach((p, i) => {
        if (i === 0) return;
        const prev = pts[i-1];
        ctx.bezierCurveTo((prev.x+p.x)/2, prev.y, (prev.x+p.x)/2, p.y, p.x, p.y);
      });
      ctx.strokeStyle = color;
      ctx.lineWidth = 3;
      ctx.shadowColor = color;
      ctx.shadowBlur = 8;
      ctx.stroke();
      // Last point dot
      const last = pts[pts.length-1];
      ctx.beginPath();
      ctx.arc(last.x, last.y, 5, 0, Math.PI*2);
      ctx.fillStyle = color;
      ctx.shadowBlur = 16;
      ctx.fill();
    });
  }, [history]);

  const latencyStatus = metrics.apiLatency < 60 ? { color: "#00ff9d", rgb: "0,255,157", label: "OPTIMAL" }
    : metrics.apiLatency < 120 ? { color: "#ffd060", rgb: "255,208,96", label: "ELEVATED" }
    : { color: "#ff2d55", rgb: "255,45,85", label: "CRITICAL" };
  const errorStatus = metrics.errorRate < 0.05 ? { color: "#00ff9d", rgb: "0,255,157", label: "NOMINAL" }
    : metrics.errorRate < 0.2 ? { color: "#ffd060", rgb: "255,208,96", label: "WARN" }
    : { color: "#ff2d55", rgb: "255,45,85", label: "ALERT" };

  const panelBg = dark
    ? "linear-gradient(180deg, rgba(0,3,14,0.99) 0%, rgba(0,8,22,0.97) 100%)"
    : "linear-gradient(180deg, rgba(220,236,255,0.99) 0%, rgba(205,226,250,0.97) 100%)";
  const textPrimary = dark ? "#e8f6ff" : "#0a1a2e";

  return (
    <div style={{
      background: panelBg,
      border: `1px solid rgba(${cyan},0.18)`,
      borderRadius: 6,
      overflow: "hidden",
      position: "relative",
      transition: "all 0.4s cubic-bezier(0.16,1,0.3,1)",
      boxShadow: dark
        ? `0 4px 30px rgba(0,0,0,0.6), inset 0 1px 0 rgba(255,255,255,0.04)`
        : `0 4px 20px rgba(0,80,180,0.08)`,
    }}>
      {/* Prismatic top edge */}
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2, background: `linear-gradient(90deg, transparent, ${cyanHex}, #00ff9d, #ff2d55, ${cyanHex}, transparent)`, opacity: 0.7 }} />

      {/* Header row */}
      <div
        onClick={() => setCollapsed(c => !c)}
        style={{
          display: "flex", alignItems: "center", gap: 12, padding: "10px 18px",
          borderBottom: collapsed ? "none" : `1px solid rgba(${cyan},0.08)`,
          cursor: "pointer",
          background: dark ? `rgba(${cyan},0.025)` : `rgba(${cyan},0.04)`,
          userSelect: "none",
        }}>
        {/* Live pulse dot */}
        <div style={{ width: 7, height: 7, borderRadius: "50%", background: "#00ff9d", boxShadow: "0 0 12px #00ff9d, 0 0 24px rgba(0,255,157,0.4)", animation: "pulse-glow 1s ease-in-out infinite", flexShrink: 0 }} />
        <span style={{ fontSize: 8, color: `rgba(${cyan},0.75)`, letterSpacing: "0.26em", fontFamily: "'Share Tech Mono', monospace", fontWeight: 700 }}>SYSTEM STATUS PULSE</span>

        {/* Quick status pills */}
        <div style={{ display: "flex", gap: 6, flex: 1 }}>
          {[
            { label: `${metrics.apiLatency}ms`, color: latencyStatus.color, rgb: latencyStatus.rgb, icon: "◈" },
            { label: `${metrics.uptime.toFixed(3)}%`, color: "#00ff9d", rgb: "0,255,157", icon: "◎" },
            { label: `${metrics.errorRate.toFixed(3)}%`, color: errorStatus.color, rgb: errorStatus.rgb, icon: "✕" },
            { label: `${metrics.throughput} req/s`, color: "#bf5fff", rgb: "191,95,255", icon: "→" },
          ].map(({ label, color, rgb, icon }) => (
            <div key={label} style={{
              display: "flex", alignItems: "center", gap: 4,
              padding: "2px 8px", borderRadius: 3,
              background: `rgba(${rgb},0.06)`,
              border: `1px solid rgba(${rgb},0.2)`,
              fontSize: 8, color, fontFamily: "'Share Tech Mono', monospace",
              letterSpacing: "0.06em",
            }}>
              <span style={{ fontSize: 7 }}>{icon}</span>
              {label}
            </div>
          ))}
        </div>

        {/* Collapse toggle */}
        <div style={{
          fontSize: 9, color: `rgba(${cyan},0.4)`, fontFamily: "'Share Tech Mono', monospace",
          transform: collapsed ? "rotate(0deg)" : "rotate(180deg)",
          transition: "transform 0.3s cubic-bezier(0.16,1,0.3,1)",
        }}>▲</div>
      </div>

      {/* Expanded body */}
      {!collapsed && (
        <div style={{ padding: "16px 18px", display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 14 }}>

          {/* API Latency gauge */}
          <div style={{ position: "relative" }}>
            <div style={{ fontSize: 7, color: `rgba(${cyan},0.45)`, letterSpacing: "0.2em", fontFamily: "'Share Tech Mono', monospace", marginBottom: 6, display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{ width: 4, height: 4, borderRadius: "50%", background: latencyStatus.color, boxShadow: `0 0 8px ${latencyStatus.color}` }} />
              API LATENCY · {latencyStatus.label}
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 6, marginBottom: 8 }}>
              <span style={{ fontSize: 28, fontWeight: 900, fontFamily: "'Orbitron', monospace", color: latencyStatus.color, textShadow: `0 0 16px rgba(${latencyStatus.rgb},0.6)`, lineHeight: 1 }}>{metrics.apiLatency}</span>
              <span style={{ fontSize: 9, color: `rgba(${latencyStatus.rgb},0.5)`, fontFamily: "'Share Tech Mono', monospace" }}>ms</span>
              <span style={{ fontSize: 7, color: `rgba(${cyan},0.3)`, fontFamily: "'Share Tech Mono', monospace", marginLeft: "auto" }}>p99: {metrics.p99}ms</span>
            </div>
            {/* Gauge track */}
            <div style={{ height: 4, background: dark ? "rgba(0,0,0,0.4)" : "rgba(0,80,160,0.1)", borderRadius: 2, overflow: "hidden", marginBottom: 8 }}>
              <div style={{
                height: "100%",
                width: `${Math.min(metrics.apiLatency / 250 * 100, 100)}%`,
                background: `linear-gradient(90deg, #00ff9d, ${latencyStatus.color})`,
                borderRadius: 2, boxShadow: `0 0 8px ${latencyStatus.color}`,
                transition: "width 1.5s cubic-bezier(0.4,0,0.2,1)",
              }} />
            </div>
            <canvas ref={sparkRef} style={{ display: "block", width: "100%", height: 36, borderRadius: 3 }} />
          </div>

          {/* Uptime gauge */}
          <div>
            <div style={{ fontSize: 7, color: `rgba(${cyan},0.45)`, letterSpacing: "0.2em", fontFamily: "'Share Tech Mono', monospace", marginBottom: 6, display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{ width: 4, height: 4, borderRadius: "50%", background: "#00ff9d", boxShadow: "0 0 8px #00ff9d", animation: "pulse-glow 2s infinite" }} />
              UPTIME / RELIABILITY
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginBottom: 8 }}>
              <span style={{ fontSize: 28, fontWeight: 900, fontFamily: "'Orbitron', monospace", color: "#00ff9d", textShadow: "0 0 16px rgba(0,255,157,0.6)", lineHeight: 1 }}>{metrics.uptime.toFixed(2)}</span>
              <span style={{ fontSize: 9, color: "rgba(0,255,157,0.5)", fontFamily: "'Share Tech Mono', monospace" }}>%</span>
            </div>
            {/* Circular-ish uptime arcs */}
            <div style={{ display: "flex", gap: 6, marginBottom: 8 }}>
              {["30d", "7d", "24h", "1h"].map((label, i) => {
                const upt = [99.97, 99.99, 100.0, 100.0][i];
                const col = upt >= 100 ? "#00ff9d" : upt > 99.9 ? "#ffd060" : "#ff2d55";
                return (
                  <div key={label} style={{ flex: 1, textAlign: "center" }}>
                    <div style={{ fontSize: 10, fontFamily: "'Orbitron', monospace", color: col, fontWeight: 700, textShadow: `0 0 8px ${col}` }}>{upt}%</div>
                    <div style={{ fontSize: 6, color: `rgba(${cyan},0.3)`, fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.1em" }}>{label}</div>
                    <div style={{ height: 2, background: `rgba(${cyan},0.08)`, borderRadius: 1, marginTop: 3, overflow: "hidden" }}>
                      <div style={{ height: "100%", width: `${upt}%`, background: col, borderRadius: 1, boxShadow: `0 0 4px ${col}` }} />
                    </div>
                  </div>
                );
              })}
            </div>
            <div style={{ display: "flex", justifyContent: "space-between", padding: "6px 8px", background: dark ? "rgba(0,255,157,0.03)" : "rgba(0,150,80,0.04)", border: "1px solid rgba(0,255,157,0.1)", borderRadius: 3 }}>
              <span style={{ fontSize: 7, color: "rgba(0,255,157,0.4)", fontFamily: "'Share Tech Mono', monospace" }}>ACTIVE CONNECTIONS</span>
              <span style={{ fontSize: 10, color: "#00ff9d", fontFamily: "'Orbitron', monospace", fontWeight: 700 }}>{metrics.activeConns}</span>
            </div>
          </div>

          {/* Error Rate gauge */}
          <div>
            <div style={{ fontSize: 7, color: `rgba(${cyan},0.45)`, letterSpacing: "0.2em", fontFamily: "'Share Tech Mono', monospace", marginBottom: 6, display: "flex", alignItems: "center", gap: 6 }}>
              <div style={{ width: 4, height: 4, borderRadius: "50%", background: errorStatus.color, boxShadow: `0 0 8px ${errorStatus.color}` }} />
              ERROR RATE · {errorStatus.label}
            </div>
            <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginBottom: 8 }}>
              <span style={{ fontSize: 28, fontWeight: 900, fontFamily: "'Orbitron', monospace", color: errorStatus.color, textShadow: `0 0 16px rgba(${errorStatus.rgb},0.6)`, lineHeight: 1 }}>{(metrics.errorRate * 100).toFixed(2)}</span>
              <span style={{ fontSize: 9, color: `rgba(${errorStatus.rgb},0.5)`, fontFamily: "'Share Tech Mono', monospace" }}>% err</span>
            </div>
            <div style={{ height: 4, background: dark ? "rgba(0,0,0,0.4)" : "rgba(0,80,160,0.1)", borderRadius: 2, overflow: "hidden", marginBottom: 8 }}>
              <div style={{
                height: "100%",
                width: `${Math.min(metrics.errorRate / 0.5 * 100, 100)}%`,
                background: `linear-gradient(90deg, #00ff9d, ${errorStatus.color})`,
                borderRadius: 2, boxShadow: `0 0 8px ${errorStatus.color}`,
                transition: "width 1.5s cubic-bezier(0.4,0,0.2,1)",
              }} />
            </div>
            <canvas ref={errRef} style={{ display: "block", width: "100%", height: 36, borderRadius: 3 }} />
            <div style={{ marginTop: 8, display: "flex", gap: 6 }}>
              {[["4xx", Math.round(metrics.throughput * metrics.errorRate * 0.7), "#ffd060"], ["5xx", Math.round(metrics.throughput * metrics.errorRate * 0.3), "#ff2d55"]].map(([code, count, col]) => (
                <div key={code} style={{ flex: 1, padding: "4px 8px", background: dark ? `rgba(${col === "#ffd060" ? "255,208,96" : "255,45,85"},0.04)` : `rgba(${col === "#ffd060" ? "200,140,0" : "200,0,40"},0.04)`, border: `1px solid rgba(${col === "#ffd060" ? "255,208,96" : "255,45,85"},0.15)`, borderRadius: 3 }}>
                  <div style={{ fontSize: 6, color: `${col}88`, fontFamily: "'Share Tech Mono', monospace" }}>{code}</div>
                  <div style={{ fontSize: 11, fontWeight: 700, color: col, fontFamily: "'Orbitron', monospace", textShadow: `0 0 8px ${col}` }}>{count}</div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── PINNABLE NOTES WIDGET — floating scratchpad ───────────────────────────────
const NOTES_STORAGE_KEY = "arcane_notes_v1";
const NOTE_COLORS = [
  { id: "cyan",   bg: "rgba(0,229,255,0.08)",   border: "rgba(0,229,255,0.3)",   text: "#00e5ff",   label: "CYAN"   },
  { id: "green",  bg: "rgba(0,255,157,0.08)",   border: "rgba(0,255,157,0.3)",   text: "#00ff9d",   label: "GREEN"  },
  { id: "gold",   bg: "rgba(255,208,96,0.08)",  border: "rgba(255,208,96,0.3)",  text: "#ffd060",   label: "GOLD"   },
  { id: "purple", bg: "rgba(191,95,255,0.08)",  border: "rgba(191,95,255,0.3)",  text: "#bf5fff",   label: "PURPLE" },
  { id: "red",    bg: "rgba(255,45,85,0.08)",   border: "rgba(255,45,85,0.3)",   text: "#ff2d55",   label: "RED"    },
];

function PinnableNotes({ pinned, onUnpin }) {
  const { dark } = useTheme();
  const cyan = dark ? "0,229,255" : "0,120,200";
  const cyanHex = dark ? "#00e5ff" : "#0088cc";

  // Load persisted notes from localStorage
  const [notes, setNotes] = useState(() => {
    try { return JSON.parse(localStorage.getItem(NOTES_STORAGE_KEY) || "[]"); } catch { return []; }
  });
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState(null); // note id being edited
  const [draft, setDraft] = useState("");
  const [draftColor, setDraftColor] = useState("cyan");
  const [draftTitle, setDraftTitle] = useState("");
  const [creating, setCreating] = useState(false);
  const textRef = useRef(null);

  const persist = (updated) => {
    setNotes(updated);
    try { localStorage.setItem(NOTES_STORAGE_KEY, JSON.stringify(updated)); } catch {}
  };

  const addNote = () => {
    if (!draft.trim()) return;
    const note = { id: Date.now(), title: draftTitle.trim() || "Note", body: draft.trim(), color: draftColor, ts: Date.now(), pinned: false };
    persist([note, ...notes]);
    setDraft(""); setDraftTitle(""); setDraftColor("cyan"); setCreating(false);
  };

  const deleteNote = (id) => persist(notes.filter(n => n.id !== id));
  const toggleNotePin = (id) => persist(notes.map(n => n.id === id ? { ...n, pinned: !n.pinned } : n));
  const startEdit = (note) => { setEditing(note.id); setDraft(note.body); setDraftTitle(note.title); setDraftColor(note.color); setTimeout(() => textRef.current?.focus(), 80); };
  const saveEdit = (id) => { persist(notes.map(n => n.id === id ? { ...n, body: draft, title: draftTitle, color: draftColor, ts: Date.now() } : n)); setEditing(null); setDraft(""); setDraftTitle(""); };

  const pinnedNotes = notes.filter(n => n.pinned);
  const unpinnedNotes = notes.filter(n => !n.pinned);
  const panelBg = dark ? "linear-gradient(160deg, rgba(0,5,20,0.99) 0%, rgba(0,12,32,0.97) 100%)" : "linear-gradient(160deg, rgba(215,235,255,0.99) 0%, rgba(200,225,250,0.97) 100%)";

  return (
    <>
      {/* Floating trigger button */}
      <button
        onClick={() => setOpen(o => !o)}
        title="Notes Scratchpad"
        style={{
          position: "fixed", bottom: 88, right: 28, zIndex: 7500,
          width: 46, height: 46, borderRadius: "50%",
          background: open ? `rgba(${cyan},0.2)` : `rgba(${cyan},0.08)`,
          border: `1px solid rgba(${cyan},${open ? 0.6 : 0.28})`,
          cursor: "pointer", fontSize: 16, color: cyanHex,
          display: "flex", alignItems: "center", justifyContent: "center",
          boxShadow: open ? `0 0 30px rgba(${cyan},0.3), 0 0 60px rgba(${cyan},0.1)` : `0 0 14px rgba(${cyan},0.1)`,
          transition: "all 0.3s cubic-bezier(0.16,1,0.3,1)",
          transform: open ? "scale(1.08) rotate(-5deg)" : "scale(1)",
        }}
        onMouseEnter={e => { e.currentTarget.style.transform = "scale(1.12)"; e.currentTarget.style.boxShadow = `0 0 30px rgba(${cyan},0.3)`; }}
        onMouseLeave={e => { e.currentTarget.style.transform = open ? "scale(1.08) rotate(-5deg)" : "scale(1)"; e.currentTarget.style.boxShadow = open ? `0 0 30px rgba(${cyan},0.3)` : `0 0 14px rgba(${cyan},0.1)`; }}
      >
        ◆
        {notes.length > 0 && (
          <div style={{ position: "absolute", top: 2, right: 2, width: 14, height: 14, borderRadius: "50%", background: "#ff2d55", border: "1px solid rgba(0,0,0,0.5)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 7, color: "#fff", fontFamily: "'Orbitron', monospace", fontWeight: 700 }}>
            {notes.length > 9 ? "9+" : notes.length}
          </div>
        )}
      </button>

      {/* Notes panel */}
      <div style={{
        position: "fixed", bottom: 144, right: 28, zIndex: 7499,
        width: 320,
        background: panelBg,
        border: `1px solid rgba(${cyan},0.25)`,
        borderRadius: 10,
        boxShadow: dark ? `0 20px 80px rgba(0,0,0,0.8), 0 0 40px rgba(${cyan},0.06)` : `0 12px 50px rgba(0,80,180,0.15)`,
        overflow: "hidden",
        transform: open ? "translateY(0) scale(1)" : "translateY(20px) scale(0.95)",
        opacity: open ? 1 : 0,
        pointerEvents: open ? "auto" : "none",
        transition: "all 0.3s cubic-bezier(0.16,1,0.3,1)",
        clipPath: "polygon(0 0, calc(100% - 16px) 0, 100% 16px, 100% 100%, 0 100%)",
      }}>
        {/* Prismatic top */}
        <div style={{ height: 2, background: `linear-gradient(90deg, transparent, rgba(${cyan},0.9), rgba(0,255,157,0.5), rgba(191,95,255,0.4), transparent)`, boxShadow: `0 0 12px rgba(${cyan},0.4)` }} />
        {/* Corner cut indicator */}
        <div style={{ position: "absolute", top: 2, right: 16, width: 0, height: 0, borderTop: "16px solid rgba(0,229,255,0.3)", borderLeft: "16px solid transparent", zIndex: 1 }} />

        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "12px 16px 10px", borderBottom: `1px solid rgba(${cyan},0.08)` }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontSize: 10, color: cyanHex }}>◆</span>
            <span style={{ fontSize: 8, color: `rgba(${cyan},0.7)`, letterSpacing: "0.22em", fontFamily: "'Share Tech Mono', monospace", textTransform: "uppercase" }}>Scratchpad</span>
            <span style={{ fontSize: 7, color: `rgba(${cyan},0.25)`, fontFamily: "'Share Tech Mono', monospace" }}>{notes.length}</span>
          </div>
          <div style={{ display: "flex", gap: 6 }}>
            <button onClick={() => { setCreating(c => !c); setDraft(""); setDraftTitle(""); }} style={{
              padding: "3px 10px", fontSize: 7, fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.12em",
              background: creating ? `rgba(${cyan},0.12)` : "transparent",
              border: `1px solid rgba(${cyan},${creating ? 0.4 : 0.18})`,
              color: cyanHex, borderRadius: 3, cursor: "pointer", transition: "all 0.15s",
            }}>+ NEW</button>
          </div>
        </div>

        {/* Create form */}
        {creating && (
          <div style={{ padding: "12px 14px", borderBottom: `1px solid rgba(${cyan},0.06)`, background: `rgba(${cyan},0.02)` }}>
            <input
              value={draftTitle}
              onChange={e => setDraftTitle(e.target.value)}
              placeholder="Note title…"
              className="holo-input"
              style={{ width: "100%", marginBottom: 8, fontSize: 10, padding: "6px 10px" }}
            />
            <textarea
              ref={textRef}
              value={draft}
              onChange={e => setDraft(e.target.value)}
              placeholder="Write your note…"
              className="holo-input"
              style={{ width: "100%", minHeight: 72, resize: "vertical", fontSize: 10, padding: "8px 10px", fontFamily: "'Share Tech Mono', monospace", lineHeight: 1.6 }}
            />
            {/* Color picker */}
            <div style={{ display: "flex", gap: 5, marginTop: 8, alignItems: "center" }}>
              {NOTE_COLORS.map(c => (
                <button key={c.id} onClick={() => setDraftColor(c.id)} style={{
                  width: 14, height: 14, borderRadius: "50%", border: `2px solid ${draftColor === c.id ? c.text : "transparent"}`,
                  background: c.text, cursor: "pointer",
                  boxShadow: draftColor === c.id ? `0 0 8px ${c.text}` : "none",
                  transition: "all 0.15s",
                }} />
              ))}
              <div style={{ flex: 1 }} />
              <button onClick={addNote} disabled={!draft.trim()} style={{
                padding: "4px 12px", fontSize: 7, fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.14em",
                background: draft.trim() ? `rgba(${cyan},0.12)` : "rgba(0,229,255,0.02)",
                border: `1px solid rgba(${cyan},${draft.trim() ? 0.45 : 0.1})`,
                color: draft.trim() ? cyanHex : `rgba(${cyan},0.2)`,
                borderRadius: 3, cursor: draft.trim() ? "pointer" : "not-allowed", transition: "all 0.15s",
              }}>SAVE</button>
            </div>
          </div>
        )}

        {/* Notes list */}
        <div style={{ maxHeight: 320, overflowY: "auto" }}>
          {notes.length === 0 && !creating && (
            <div style={{ padding: "30px 16px", textAlign: "center", color: `rgba(${cyan},0.2)`, fontSize: 9, fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.15em" }}>
              NO TRANSMISSIONS<br /><span style={{ fontSize: 7 }}>Hit + NEW to create a note</span>
            </div>
          )}
          {/* Pinned section */}
          {pinnedNotes.length > 0 && (
            <div>
              <div style={{ padding: "6px 14px 2px", fontSize: 6, color: `rgba(${cyan},0.2)`, fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.2em" }}>PINNED</div>
              {pinnedNotes.map(note => <NoteCard key={note.id} note={note} onDelete={deleteNote} onPin={toggleNotePin} onEdit={startEdit} editing={editing} draft={draft} draftTitle={draftTitle} draftColor={draftColor} setDraft={setDraft} setDraftTitle={setDraftTitle} setDraftColor={setDraftColor} onSave={saveEdit} textRef={textRef} dark={dark} cyan={cyan} cyanHex={cyanHex} />)}
            </div>
          )}
          {unpinnedNotes.length > 0 && (
            <div>
              {pinnedNotes.length > 0 && <div style={{ padding: "6px 14px 2px", fontSize: 6, color: `rgba(${cyan},0.2)`, fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.2em" }}>OTHER</div>}
              {unpinnedNotes.map(note => <NoteCard key={note.id} note={note} onDelete={deleteNote} onPin={toggleNotePin} onEdit={startEdit} editing={editing} draft={draft} draftTitle={draftTitle} draftColor={draftColor} setDraft={setDraft} setDraftTitle={setDraftTitle} setDraftColor={setDraftColor} onSave={saveEdit} textRef={textRef} dark={dark} cyan={cyan} cyanHex={cyanHex} />)}
            </div>
          )}
        </div>
      </div>
    </>
  );
}

function NoteCard({ note, onDelete, onPin, onEdit, editing, draft, draftTitle, draftColor, setDraft, setDraftTitle, setDraftColor, onSave, textRef, dark, cyan, cyanHex }) {
  const nc = NOTE_COLORS.find(c => c.id === note.color) || NOTE_COLORS[0];
  const isEditing = editing === note.id;
  const timeAgo = (ts) => {
    const s = Math.floor((Date.now() - ts) / 1000);
    if (s < 60) return "just now";
    const m = Math.floor(s / 60);
    if (m < 60) return `${m}m ago`;
    return `${Math.floor(m / 60)}h ago`;
  };

  return (
    <div style={{
      margin: "6px 10px",
      background: nc.bg,
      border: `1px solid ${nc.border}`,
      borderRadius: 5,
      overflow: "hidden",
      position: "relative",
      clipPath: "polygon(0 0, calc(100% - 8px) 0, 100% 8px, 100% 100%, 0 100%)",
    }}>
      <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, ${nc.text}, transparent)` }} />
      {isEditing ? (
        <div style={{ padding: "10px 12px" }}>
          <input value={draftTitle} onChange={e => setDraftTitle(e.target.value)} className="holo-input" style={{ width: "100%", marginBottom: 6, fontSize: 9, padding: "4px 8px" }} />
          <textarea ref={textRef} value={draft} onChange={e => setDraft(e.target.value)} className="holo-input" style={{ width: "100%", minHeight: 60, resize: "vertical", fontSize: 9, padding: "6px 8px", fontFamily: "'Share Tech Mono', monospace", lineHeight: 1.5 }} />
          <div style={{ display: "flex", gap: 4, marginTop: 6, alignItems: "center" }}>
            {NOTE_COLORS.map(c => <button key={c.id} onClick={() => setDraftColor(c.id)} style={{ width: 11, height: 11, borderRadius: "50%", border: `2px solid ${draftColor === c.id ? c.text : "transparent"}`, background: c.text, cursor: "pointer", boxShadow: draftColor === c.id ? `0 0 6px ${c.text}` : "none" }} />)}
            <div style={{ flex: 1 }} />
            <button onClick={() => onSave(note.id)} style={{ padding: "2px 8px", fontSize: 7, fontFamily: "'Share Tech Mono', monospace", background: `rgba(0,229,255,0.1)`, border: `1px solid rgba(0,229,255,0.35)`, color: cyanHex, borderRadius: 2, cursor: "pointer" }}>SAVE</button>
          </div>
        </div>
      ) : (
        <div style={{ padding: "9px 12px" }}>
          <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", marginBottom: 4, gap: 6 }}>
            <span style={{ fontSize: 9, color: nc.text, fontFamily: "'Share Tech Mono', monospace", fontWeight: 700, letterSpacing: "0.04em", flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{note.title}</span>
            <div style={{ display: "flex", gap: 4, flexShrink: 0 }}>
              <button onClick={() => onPin(note.id)} title={note.pinned ? "Unpin" : "Pin"} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 9, color: note.pinned ? nc.text : `rgba(${cyan},0.25)`, transition: "color 0.15s" }}>⬡</button>
              <button onClick={() => onEdit(note)} title="Edit" style={{ background: "none", border: "none", cursor: "pointer", fontSize: 8, color: `rgba(${cyan},0.25)`, transition: "color 0.15s" }}>✎</button>
              <button onClick={() => onDelete(note.id)} title="Delete" style={{ background: "none", border: "none", cursor: "pointer", fontSize: 8, color: "rgba(255,45,85,0.3)", transition: "color 0.15s" }}>✕</button>
            </div>
          </div>
          <div style={{ fontSize: 9, color: dark ? "rgba(180,220,255,0.65)" : "rgba(10,40,80,0.7)", fontFamily: "'Share Tech Mono', monospace", lineHeight: 1.6, wordBreak: "break-word" }}>{note.body}</div>
          <div style={{ marginTop: 5, fontSize: 7, color: `rgba(${cyan},0.2)`, fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.08em" }}>{timeAgo(note.ts)}</div>
        </div>
      )}
    </div>
  );
}

// ── TAB TRANSITION — animated content swap ────────────────────────────────────
function useTabTransition(tab) {
  const [displayTab, setDisplayTab] = useState(tab);
  const [phase, setPhase] = useState("idle"); // idle | exit | enter
  const prevTab = useRef(tab);

  useEffect(() => {
    if (tab === prevTab.current) return;
    prevTab.current = tab;
    setPhase("exit");
    const t1 = setTimeout(() => {
      setDisplayTab(tab);
      setPhase("enter");
    }, 140);
    const t2 = setTimeout(() => setPhase("idle"), 420);
    return () => { clearTimeout(t1); clearTimeout(t2); };
  }, [tab]);

  const style = {
    exit:  { opacity: 0, transform: "translateY(10px) scale(0.992)", transition: "all 0.14s cubic-bezier(0.4,0,1,1)", pointerEvents: "none" },
    enter: { opacity: 0, transform: "translateY(-12px) scale(0.992)", animation: "tabEnter 0.32s cubic-bezier(0.16,1,0.3,1) both" },
    idle:  { opacity: 1, transform: "none" },
  }[phase];

  return { displayTab, transitionStyle: style };
}

function WorkspaceHealthMapWrapper() {
  const { data, loading } = useAdminFetch("/admin/workspaces?limit=100");
  if (loading) return <div style={{ height: 280, display: "flex", alignItems: "center", justifyContent: "center", color: "rgba(168,85,247,0.3)", fontSize: 9, fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.18em" }}>MAPPING NETWORK…</div>;
  return <WorkspaceHealthMap workspaces={data?.workspaces || []} />;
}

// ── MAIN DASHBOARD ────────────────────────────────────────────────────────────
export default function AdminDashboard() {
  const [isLoggedIn, setIsLoggedIn] = useState(!!localStorage.getItem("access_token"));
  const [tab, setTab] = useState("overview");
  const { data: metrics, loading, error, refetch } = useAdminFetch("/admin/metrics");
  const m = metrics;
  const [time, setTime] = useState(new Date());
  const [bootSeq, setBootSeq] = useState(0);
  const revColor = useRevenueColor();
  const { toasts, showToast, dismiss } = useToasts();
  const [paletteOpen, setPaletteOpen] = useState(false);
  const [exportOpen, setExportOpen] = useState(false);
  const [dark, setDark] = useState(true);
  const [drawerUser, setDrawerUser] = useState(null);
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const { displayTab, transitionStyle } = useTabTransition(tab);

  // Apply light/dark class to <html>
  useEffect(() => {
    document.documentElement.classList.toggle("arcane-light", !dark);
    return () => document.documentElement.classList.remove("arcane-light");
  }, [dark]);

  useEffect(() => { const t = setInterval(() => setTime(new Date()), 1000); return () => clearInterval(t); }, []);
  useEffect(() => { const t = setInterval(() => setBootSeq(s => s < 100 ? s + 2 : 100), 40); return () => clearInterval(t); }, []);

  // Global keyboard shortcuts
  useEffect(() => {
    const handler = (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") { e.preventDefault(); setPaletteOpen(p => !p); }
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === "e") { e.preventDefault(); setExportOpen(p => !p); }
      if (e.key === "Escape") { setPaletteOpen(false); setExportOpen(false); }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  if (!isLoggedIn) return <LoginScreen onLogin={() => setIsLoggedIn(true)} />;

  const timeStr = time.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
  const dateStr = time.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: "numeric" });

  const TABS = [
    { id: "overview",   label: "OVERVIEW",   icon: "◈" },
    { id: "revenue",    label: "REVENUE",    icon: "◎" },
    { id: "users",      label: "USERS",      icon: "⬡", count: m?.users?.total },
    { id: "workspaces", label: "WORKSPACES", icon: "⊞" },
    { id: "feedback",   label: "FEEDBACK",   icon: "◆" },
  ];

  const isRev = displayTab === "revenue";
  const rc = revColor; // shorthand

  return (
    <ThemeCtx.Provider value={{ dark }}>
    <div style={{ minHeight: "100vh", background: dark ? "#00040f" : "#e8f2fa", color: dark ? "#dff6ff" : "#0a1a2e", position: "relative", overflow: "hidden", transition: "background 0.5s, color 0.5s" }}>
      <ToastSystem toasts={toasts} dismiss={dismiss} />
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        onNavigate={setTab}
        tabs={TABS}
        m={m}
      />
      <ExportModal open={exportOpen} onClose={() => setExportOpen(false)} m={m} />
      <UserDetailDrawer
        user={drawerUser}
        open={!!drawerUser}
        onClose={() => setDrawerUser(null)}
        showToast={showToast}
        onToggleActive={(id, cur, name) => {
          const token = localStorage.getItem("access_token");
          fetch(`${API}/admin/users/${id}`, { method: "PATCH", headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" }, body: JSON.stringify({ is_active: !cur }) });
          showToast?.(!cur ? `${name || "User"} activated` : `${name || "User"} deactivated`, !cur ? "success" : "warning");
        }}
      />
      <PinnableNotes />
      <style>{`
        ${LIGHT_OVERRIDES}
        @keyframes activitySlide {
          from { opacity: 0; transform: translateY(-12px) scale(0.97); }
          to   { opacity: 1; transform: translateY(0)     scale(1);    }
        }
        @keyframes scanV { 0%{top:0} 100%{top:100%} }
        @keyframes fadeIn {
          from { opacity: 0; }
          to   { opacity: 1; }
        }
        @keyframes exportRise {
          from { opacity: 0; transform: translateY(24px) scale(0.97); }
          to   { opacity: 1; transform: translateY(0)    scale(1);    }
        }
        @import url('https://fonts.googleapis.com/css2?family=Orbitron:wght@400;500;600;700;800;900&family=Share+Tech+Mono&family=Rajdhani:wght@300;400;500;600;700&display=swap');
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { background: #00040f; }

        /* ══════════════════════════════════════════════════════
           MASTER COLOR TOKENS
        ══════════════════════════════════════════════════════ */
        :root {
          --cyan:    #00e5ff;
          --green:   #00ff9d;
          --purple:  #bf5fff;
          --gold:    #ffd060;
          --red:     #ff2d55;
          --bg-deep: #00040f;
          --bg-mid:  #000918;
          --glass:   rgba(0,14,38,0.82);
          --border:  rgba(0,229,255,0.18);
        }

        /* ══════════════════════════════════════════════════════
           SPACE BACKGROUND — deep cosmic nebula, rich layers
        ══════════════════════════════════════════════════════ */
        .space-bg {
          position: fixed; inset: 0;
          background:
            radial-gradient(ellipse 100% 70% at 8% 5%,   rgba(0,80,180,0.65)  0%, transparent 50%),
            radial-gradient(ellipse 70% 60% at 92% 92%,  rgba(0,25,100,0.6)   0%, transparent 50%),
            radial-gradient(ellipse 50% 40% at 55% 32%,  rgba(0,100,140,0.28) 0%, transparent 60%),
            radial-gradient(ellipse 60% 50% at 20% 75%,  rgba(40,0,100,0.25)  0%, transparent 55%),
            radial-gradient(ellipse 80% 35% at 78% 18%,  rgba(0,50,120,0.22)  0%, transparent 48%),
            radial-gradient(ellipse 45% 55% at 50% 55%,  rgba(0,30,80,0.18)   0%, transparent 65%),
            #00040f;
          pointer-events: none; z-index: 0;
          transition: background 0.8s;
        }

        /* Animated aurora bands — richer, multiple layers */
        .aurora {
          position: fixed; inset: 0; pointer-events: none; z-index: 0; overflow: hidden;
        }
        .aurora::before {
          content: '';
          position: absolute; top: -70%; left: -25%; width: 150%; height: 85%;
          background: conic-gradient(from 180deg at 50% 80%,
            transparent 0deg,
            rgba(0,229,255,0.055) 25deg,
            rgba(0,255,157,0.08)  55deg,
            rgba(191,95,255,0.04) 75deg,
            rgba(0,229,255,0.04)  95deg,
            transparent 120deg);
          filter: blur(70px);
          animation: auroraShift 18s ease-in-out infinite alternate;
          transform-origin: 50% 100%;
        }
        .aurora::after {
          content: '';
          position: absolute; bottom: -50%; right: -20%; width: 130%; height: 75%;
          background: conic-gradient(from 0deg at 50% 20%,
            transparent 0deg,
            rgba(191,95,255,0.065) 35deg,
            rgba(0,229,255,0.055)  60deg,
            rgba(0,255,157,0.04)   80deg,
            transparent 100deg);
          filter: blur(90px);
          animation: auroraShift2 22s ease-in-out infinite alternate;
          transform-origin: 50% 0%;
        }
        @keyframes auroraShift {
          0%   { transform: rotate(-6deg) scale(1);    opacity: 0.7; }
          50%  { transform: rotate(4deg)  scale(1.08); opacity: 1;   }
          100% { transform: rotate(-9deg) scale(0.94); opacity: 0.65; }
        }
        @keyframes auroraShift2 {
          0%   { transform: rotate(9deg) scale(1.12);  opacity: 0.55; }
          100% { transform: rotate(-5deg) scale(0.88); opacity: 0.85; }
        }

        /* ── TOP HUD LINE — full-spectrum prismatic shimmer ── */
        .hud-topline {
          position: fixed; top: 0; left: 0; right: 0; height: 3px;
          background: linear-gradient(90deg,
            transparent 0%, var(--cyan) 8%, var(--green) 22%,
            rgba(255,255,255,0.8) 35%,
            var(--cyan) 45%, var(--purple) 58%,
            rgba(255,255,255,0.6) 68%,
            var(--cyan) 78%, var(--green) 90%,
            transparent 100%);
          pointer-events: none; z-index: 100;
          animation: toplineShimmer 5s ease-in-out infinite alternate;
          box-shadow:
            0 0 25px var(--cyan),
            0 0 70px rgba(0,229,255,0.45),
            0 0 140px rgba(0,229,255,0.18),
            0 0 0 1px rgba(0,229,255,0.1),
            0 3px 0 rgba(0,229,255,0.06);
        }
        @keyframes toplineShimmer {
          0%   { opacity: 0.75; filter: hue-rotate(0deg)   brightness(1.1);  }
          25%  { opacity: 1;    filter: hue-rotate(25deg)  brightness(1.6);  }
          50%  { opacity: 0.9;  filter: hue-rotate(-10deg) brightness(1.3);  }
          75%  { opacity: 1;    filter: hue-rotate(15deg)  brightness(1.5);  }
          100% { opacity: 0.8;  filter: hue-rotate(5deg)   brightness(1.15); }
        }

        /* ── VIGNETTE — deeper ── */
        .vignette {
          position: fixed; inset: 0; pointer-events: none; z-index: 1;
          background:
            radial-gradient(ellipse at center, transparent 30%, rgba(0,1,6,0.85) 100%);
        }

        /* scanline overlay — finer, barely-there */
        .scanlines {
          position: fixed; inset: 0; pointer-events: none; z-index: 2;
          background:
            repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(0,229,255,0.006) 2px, rgba(0,229,255,0.006) 3px);
          transition: background 0.4s;
        }

        /* CRT noise grain */
        .grain {
          position: fixed; inset: 0; pointer-events: none; z-index: 2; opacity: 0.025;
          background-image: url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)'/%3E%3C/svg%3E");
          background-size: 200px 200px;
          animation: grainShift 0.5s steps(2) infinite;
        }
        @keyframes grainShift {
          0%   { background-position: 0 0; }
          25%  { background-position: -30px 15px; }
          50%  { background-position: 20px -10px; }
          75%  { background-position: -15px 25px; }
          100% { background-position: 10px -20px; }
        }

        /* ── ANIMATIONS ── */
        @keyframes spin { to { transform: rotate(360deg); } }
        @keyframes spinReverse { to { transform: rotate(-360deg); } }
        @keyframes holoRise {
          from { opacity: 0; transform: perspective(1200px) translateY(60px) translateZ(-60px) rotateX(10deg) scale(0.96); filter: blur(3px) saturate(0.5); }
          to   { opacity: 1; transform: perspective(1200px) translateY(0)    translateZ(0)     rotateX(0deg)  scale(1);    filter: blur(0)   saturate(1); }
        }
        @keyframes pulse-glow {
          0%, 100% { opacity: 0.6;  filter: brightness(1); }
          50%       { opacity: 1;   filter: brightness(1.7) drop-shadow(0 0 6px currentColor); }
        }
        @keyframes pulseRing {
          0%   { transform: scale(1);    opacity: 0.6; }
          50%  { transform: scale(1.18); opacity: 1;   }
          100% { transform: scale(1);    opacity: 0.6; }
        }
        @keyframes particleFloat {
          0%   { transform: translateY(0)    scale(1);    opacity: 1;   }
          100% { transform: translateY(-90px) scale(0.1); opacity: 0; }
        }
        @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
        @keyframes rotateSlow { to { transform: rotate(360deg); } }
        @keyframes dataStream {
          0%   { transform: translateY(-100%); }
          100% { transform: translateY(100vh);  }
        }
        @keyframes glitchShift {
          0%,  93%, 100% { clip-path: none; transform: none; color: inherit; }
          94% { clip-path: polygon(0 18%, 100% 18%, 100% 38%, 0 38%); transform: translateX(6px);  color: var(--red);  }
          95% { clip-path: polygon(0 55%, 100% 55%, 100% 75%, 0 75%); transform: translateX(-6px); color: var(--cyan); }
          96% { clip-path: polygon(0 8%,  100% 8%,  100% 22%, 0 22%); transform: translateX(4px);  }
          97% { clip-path: none; transform: translateX(2px); }
          98% { clip-path: none; transform: none; }
        }
        @keyframes shimmerSlide {
          0%   { transform: translateX(-100%) skewX(-20deg); }
          100% { transform: translateX(250%)  skewX(-20deg); }
        }
        @keyframes floatY {
          0%, 100% { transform: translateY(0);    }
          50%       { transform: translateY(-8px); }
        }
        @keyframes borderPulse {
          0%, 100% { box-shadow: 0 0 0 1px rgba(0,229,255,0.1), 0 0 20px rgba(0,229,255,0.05); }
          50%       { box-shadow: 0 0 0 1px rgba(0,229,255,0.3), 0 0 40px rgba(0,229,255,0.12); }
        }
        @keyframes textGlow {
          0%, 100% { text-shadow: 0 0 20px rgba(0,229,255,0.4), 0 0 60px rgba(0,229,255,0.15); }
          50%       { text-shadow: 0 0 30px rgba(0,229,255,0.8), 0 0 90px rgba(0,229,255,0.3), 0 0 140px rgba(0,229,255,0.1); }
        }
        @keyframes scanDown {
          0%   { top: -4px; opacity: 0; }
          5%   { opacity: 1; }
          95%  { opacity: 1; }
          100% { top: 100%; opacity: 0; }
        }
        @keyframes energyFlow {
          0%   { background-position: 0% 50%; }
          100% { background-position: 200% 50%; }
        }
        @keyframes prismaticEdge {
          0%   { filter: hue-rotate(0deg)   brightness(1.2); }
          25%  { filter: hue-rotate(30deg)  brightness(1.5); }
          50%  { filter: hue-rotate(60deg)  brightness(1.3); }
          75%  { filter: hue-rotate(20deg)  brightness(1.6); }
          100% { filter: hue-rotate(0deg)   brightness(1.2); }
        }
        @keyframes cardScan {
          0%   { top: -2px;  opacity: 0; }
          5%   { opacity: 1; }
          95%  { opacity: 0.8; }
          100% { top: 100%; opacity: 0; }
        }
        @keyframes rippleOut {
          0%   { opacity: 0.8; transform: scale(0.5); }
          100% { opacity: 0;   transform: scale(2);   }
        }
        @keyframes cosmicPulse {
          0%, 100% { opacity: 0.4; transform: scale(1);    }
          50%       { opacity: 0.9; transform: scale(1.08); }
        }
        @keyframes neonFlicker {
          0%,  19%, 21%, 23%, 25%, 54%, 56%, 100% { opacity: 1; }
          20%, 24%, 55% { opacity: 0.4; }
        }
        @keyframes dataRain {
          0%   { transform: translateY(-100%); opacity: 0; }
          10%  { opacity: 0.6; }
          90%  { opacity: 0.6; }
          100% { transform: translateY(100vh);  opacity: 0; }
        }
        @keyframes hexPulse {
          0%, 100% { opacity: 0.4; transform: scale(0.95); }
          50%       { opacity: 1;   transform: scale(1.05); }
        }
        @keyframes rotateHue {
          from { filter: hue-rotate(0deg) brightness(1.2); }
          to   { filter: hue-rotate(360deg) brightness(1.2); }
        }
        @keyframes tickerScroll {
          0%   { transform: translateX(0); }
          100% { transform: translateX(-50%); }
        }

        /* ── NEW STEP 6 ANIMATIONS ── */
        @keyframes tabEnter {
          from { opacity: 0; transform: translateY(14px) scale(0.99); }
          to   { opacity: 1; transform: translateY(0)   scale(1);    }
        }
        @keyframes paletteFadeIn {
          from { opacity: 0; }
          to   { opacity: 1; }
        }
        @keyframes paletteRise {
          from { opacity: 0; transform: translateY(-20px) scale(0.97); }
          to   { opacity: 1; transform: translateY(0)     scale(1);    }
        }
        @keyframes sentimentPulse {
          0%,100% { transform: scaleY(1);   }
          50%     { transform: scaleY(1.12);}
        }

        .dashboard-root {
          font-family: 'Share Tech Mono', monospace;
          display: flex; min-height: 100vh; position: relative; z-index: 3;
        }

        /* ══════════════════════════════════════════════════════
           SIDEBAR — deeply immersive crystalline chamber
        ══════════════════════════════════════════════════════ */
        .sidebar {
          min-height: 100vh; min-width: 64px;
          background:
            linear-gradient(180deg,
              rgba(0,4,16,0.995) 0%,
              rgba(0,8,24,0.99)  25%,
              rgba(0,6,20,0.995) 55%,
              rgba(0,3,12,1)     100%);
          border-right: 1px solid rgba(0,229,255,0.16);
          box-shadow:
            8px 0 100px rgba(0,0,0,0.95),
            4px 0 0   rgba(0,229,255,0.04),
            2px 0 0   rgba(0,229,255,0.02),
            inset -2px 0 0 rgba(0,229,255,0.06),
            inset -1px 0 0 rgba(0,229,255,0.03);
          display: flex; flex-direction: column;
          position: fixed; top: 0; left: 0; bottom: 0; z-index: 10;
          backdrop-filter: blur(50px) saturate(1.4);
          overflow: hidden;
        }
        /* Top prismatic edge */
        .sidebar::before {
          content: '';
          position: absolute; top: 0; left: 0; right: 0; height: 3px;
          background: linear-gradient(90deg,
            transparent 0%,
            var(--cyan)   12%,
            rgba(255,255,255,0.6) 25%,
            var(--green)  45%,
            var(--purple) 65%,
            rgba(255,255,255,0.4) 75%,
            var(--cyan)   88%,
            transparent   100%);
          opacity: 0.85;
          animation: toplineShimmer 8s ease-in-out infinite alternate;
          box-shadow: 0 0 15px rgba(0,229,255,0.5), 0 0 30px rgba(0,229,255,0.2);
        }
        /* Vertical scan line on right edge */
        .sidebar::after {
          content: '';
          position: absolute; top: 0; right: 0; width: 1px; bottom: 0;
          background: linear-gradient(180deg,
            transparent 0%,
            rgba(0,229,255,0.7) 20%,
            rgba(0,255,157,0.4) 45%,
            rgba(191,95,255,0.35) 70%,
            rgba(0,229,255,0.5) 85%,
            transparent 100%);
          opacity: 0.35;
          animation: pulse-glow 6s ease-in-out infinite;
        }
        /* Animated diagonal scan sweep inside sidebar */
        .sidebar-scan {
          position: absolute; inset: 0; pointer-events: none; overflow: hidden;
        }
        .sidebar-scan::after {
          content: '';
          position: absolute; left: -100%; top: 0; width: 60%; height: 100%;
          background: linear-gradient(90deg, transparent, rgba(0,229,255,0.03), rgba(255,255,255,0.01), transparent);
          animation: shimmerSlide 7s ease-in-out 2s infinite;
        }
        /* Inner glow orb at sidebar center */
        .sidebar-orb {
          position: absolute; left: 50%; top: 55%; transform: translate(-50%, -50%);
          width: 220px; height: 220px; border-radius: 50%; pointer-events: none;
          background: radial-gradient(circle, rgba(0,229,255,0.05) 0%, rgba(0,255,157,0.02) 40%, transparent 70%);
          animation: pulseRing 8s ease-in-out infinite;
        }

        /* ══════════════════════════════════════════════════════
           MAIN CONTENT
        ══════════════════════════════════════════════════════ */
        .main-content {
          margin-left: 240px; flex: 1;
          padding: 0 32px 88px;
          min-height: 100vh;
          position: relative;
        }

        /* ══════════════════════════════════════════════════════
           TOPBAR — command bridge glass strip
        ══════════════════════════════════════════════════════ */
        .topbar {
          display: flex; align-items: center; justify-content: space-between;
          padding: 22px 0 24px;
          border-bottom: 1px solid rgba(0,229,255,0.12);
          margin-bottom: 32px;
          position: sticky; top: 0; z-index: 5;
          background:
            linear-gradient(180deg,
              rgba(0,5,18,0.99) 0%,
              rgba(0,8,22,0.97) 60%,
              rgba(0,5,16,0.95) 100%);
          backdrop-filter: blur(40px) saturate(1.5);
          box-shadow:
            0 1px 0 rgba(0,229,255,0.1),
            0 12px 70px rgba(0,0,0,0.7),
            0 0 0 1px rgba(0,229,255,0.04),
            0 0 80px rgba(0,229,255,0.03);
        }
        .topbar::before {
          content: '';
          position: absolute; top: 0; left: 0; right: 0; height: 2px;
          background: linear-gradient(90deg,
            transparent 0%,
            rgba(0,229,255,0.6) 10%,
            rgba(0,255,157,0.4) 30%,
            rgba(255,255,255,0.5) 50%,
            rgba(191,95,255,0.4) 70%,
            rgba(0,229,255,0.6) 90%,
            transparent 100%);
          animation: toplineShimmer 7s ease-in-out infinite alternate;
          box-shadow: 0 0 20px rgba(0,229,255,0.4), 0 0 50px rgba(0,229,255,0.15);
        }
        .topbar::after {
          content: '';
          position: absolute; bottom: 0; left: 0; right: 0; height: 1px;
          background: linear-gradient(90deg,
            transparent, rgba(0,229,255,0.35), rgba(0,255,157,0.2), rgba(191,95,255,0.15), rgba(0,229,255,0.35), transparent);
        }
        /* Scan sweep in topbar */
        .topbar-scan {
          position: absolute; inset: 0; overflow: hidden; pointer-events: none;
        }
        .topbar-scan::after {
          content: '';
          position: absolute; top: 0; bottom: 0; left: -100%; width: 40%;
          background: linear-gradient(90deg, transparent, rgba(0,229,255,0.02), rgba(255,255,255,0.01), transparent);
          animation: shimmerSlide 10s ease-in-out 1s infinite;
        }

        /* ══════════════════════════════════════════════════════
           SECTION HEADING — dramatic neon title bar
        ══════════════════════════════════════════════════════ */
        .section-heading {
          font-size: 11px; color: rgba(0,229,255,0.8); letter-spacing: 0.38em;
          text-transform: uppercase; margin-bottom: 22px;
          font-family: 'Rajdhani', sans-serif; font-weight: 700;
          display: flex; align-items: center; gap: 14px;
          padding: 10px 0;
          position: relative;
          text-shadow: 0 0 20px rgba(0,229,255,0.5), 0 0 40px rgba(0,229,255,0.2);
        }
        .section-heading::before {
          content: '▶▶';
          font-size: 7px; color: var(--cyan);
          text-shadow: 0 0 16px var(--cyan), 0 0 35px rgba(0,229,255,0.6), 0 0 60px rgba(0,229,255,0.2);
          animation: pulse-glow 2s ease-in-out infinite;
          letter-spacing: -2px;
        }
        .section-heading::after {
          content: ''; flex: 1; height: 1px;
          background:
            linear-gradient(90deg,
              rgba(0,229,255,0.6) 0%,
              rgba(0,229,255,0.25) 30%,
              rgba(0,255,157,0.12) 60%,
              transparent 100%);
          box-shadow: 0 0 8px rgba(0,229,255,0.2);
        }

        /* ══════════════════════════════════════════════════════
           STAT STRIP — premium holographic tiles
        ══════════════════════════════════════════════════════ */
        .stat-row {
          display: flex; gap: 12px; flex-wrap: wrap; margin-top: 20px;
        }
        .stat-item {
          flex: 1; min-width: 120px;
          background:
            linear-gradient(160deg, rgba(0,5,18,0.99) 0%, rgba(0,12,30,0.96) 40%, rgba(0,5,16,0.99) 100%);
          border: 1px solid rgba(0,229,255,0.16);
          border-radius: 8px; padding: 20px 22px;
          position: relative; overflow: hidden;
          transition: all 0.4s cubic-bezier(0.16,1,0.3,1);
          clip-path: polygon(0 0, calc(100% - 12px) 0, 100% 12px, 100% 100%, 12px 100%, 0 calc(100% - 12px));
          box-shadow:
            inset 0 1px 0 rgba(255,255,255,0.06),
            inset 0 0 30px rgba(0,229,255,0.02),
            0 6px 30px rgba(0,0,0,0.65);
          cursor: default;
        }
        /* Glass sheen */
        .stat-item::before {
          content: ''; position: absolute; top: 0; left: 0; right: 0; height: 50%;
          background: linear-gradient(180deg, rgba(255,255,255,0.065) 0%, rgba(255,255,255,0.015) 50%, transparent 100%);
          pointer-events: none;
        }
        /* Prismatic top edge */
        .stat-item::after {
          content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px;
          background: linear-gradient(90deg,
            transparent 0%,
            rgba(0,229,255,0.6) 20%,
            rgba(0,255,157,0.4) 50%,
            rgba(0,229,255,0.5) 80%,
            transparent 100%);
          box-shadow: 0 0 10px rgba(0,229,255,0.3);
        }
        .stat-item:hover {
          border-color: rgba(0,229,255,0.45);
          background:
            linear-gradient(160deg, rgba(0,8,28,0.99) 0%, rgba(0,18,40,0.97) 40%, rgba(0,6,22,0.99) 100%);
          box-shadow:
            0 0 0 1px rgba(0,229,255,0.08),
            0 0 50px rgba(0,229,255,0.14),
            0 20px 60px rgba(0,0,0,0.8),
            inset 0 1px 0 rgba(255,255,255,0.09),
            inset 0 0 30px rgba(0,229,255,0.04);
          transform: translateY(-6px) scale(1.025);
        }
        .stat-item:hover::after {
          background: linear-gradient(90deg,
            transparent 0%,
            var(--cyan) 15%,
            var(--green) 40%,
            rgba(255,255,255,0.8) 50%,
            var(--green) 60%,
            var(--cyan) 85%,
            transparent 100%);
          box-shadow: 0 0 18px var(--cyan), 0 0 35px rgba(0,229,255,0.3);
          height: 3px;
        }
        .stat-label {
          font-size: 8px; color: rgba(0,229,255,0.45); text-transform: uppercase;
          letter-spacing: 0.22em; margin-bottom: 14px;
          font-family: 'Share Tech Mono', monospace;
          display: flex; align-items: center; gap: 6px;
        }
        .stat-label::before {
          content: ''; display: inline-block; width: 4px; height: 4px;
          border-radius: 50%; background: var(--cyan);
          box-shadow: 0 0 8px var(--cyan);
          animation: pulse-glow 2s ease-in-out infinite;
          flex-shrink: 0;
        }
        .stat-val {
          font-size: 28px; font-weight: 900;
          font-family: 'Orbitron', monospace; letter-spacing: -0.04em;
          line-height: 1;
          text-shadow: 0 0 20px rgba(0,229,255,0.6), 0 0 50px rgba(0,229,255,0.25), 0 0 90px rgba(0,229,255,0.08);
        }

        /* ══════════════════════════════════════════════════════
           TABLE ROWS
        ══════════════════════════════════════════════════════ */
        .holo-row { transition: background 0.2s, box-shadow 0.2s; }
        .holo-row:hover {
          background: rgba(0,229,255,0.045);
          box-shadow: inset 0 0 30px rgba(0,229,255,0.03), inset 3px 0 0 var(--cyan);
        }
        .holo-row td { border-bottom: 1px solid rgba(0,229,255,0.06); }

        /* ══════════════════════════════════════════════════════
           INPUTS — premium holo fields
        ══════════════════════════════════════════════════════ */
        .holo-input {
          background:
            linear-gradient(145deg, rgba(0,6,20,0.97) 0%, rgba(0,10,26,0.93) 100%);
          border: 1px solid rgba(0,229,255,0.22); border-radius: 5px;
          color: #e0f9ff; font-size: 11px; padding: 11px 15px;
          font-family: 'Share Tech Mono', monospace; outline: none;
          transition: all 0.25s;
          backdrop-filter: blur(20px);
          box-shadow:
            inset 0 1px 0 rgba(255,255,255,0.05),
            inset 0 0 20px rgba(0,229,255,0.02),
            0 2px 12px rgba(0,0,0,0.5);
          clip-path: polygon(0 0, calc(100% - 7px) 0, 100% 7px, 100% 100%, 0 100%);
        }
        .holo-input:focus {
          border-color: rgba(0,229,255,0.6);
          box-shadow:
            0 0 0 3px rgba(0,229,255,0.1),
            0 0 30px rgba(0,229,255,0.14),
            inset 0 1px 0 rgba(255,255,255,0.08),
            inset 0 0 20px rgba(0,229,255,0.03);
        }
        .holo-input option { background: #000812; }

        /* ══════════════════════════════════════════════════════
           FEEDBACK CARD — holographic transmission panel
        ══════════════════════════════════════════════════════ */
        .holo-feedback {
          background:
            linear-gradient(160deg, rgba(0,4,18,0.99) 0%, rgba(0,10,26,0.96) 50%, rgba(0,4,16,0.98) 100%);
          border: 1px solid rgba(0,229,255,0.15);
          border-radius: 8px; padding: 24px;
          transition: all 0.35s cubic-bezier(0.16,1,0.3,1);
          position: relative; overflow: hidden;
          clip-path: polygon(0 0, calc(100% - 16px) 0, 100% 16px, 100% 100%, 16px 100%, 0 calc(100% - 16px));
          box-shadow:
            inset 0 1px 0 rgba(255,255,255,0.055),
            0 8px 40px rgba(0,0,0,0.65);
        }
        .holo-feedback::before {
          content: ''; position: absolute; top: 0; left: 0; right: 0; height: 2px;
          background: linear-gradient(90deg,
            transparent 0%,
            rgba(0,229,255,0.7) 20%,
            rgba(0,255,157,0.4) 50%,
            rgba(0,229,255,0.5) 80%,
            transparent 100%);
          box-shadow: 0 0 14px rgba(0,229,255,0.3);
        }
        .holo-feedback::after {
          content: ''; position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
          background: linear-gradient(180deg, var(--cyan) 0%, rgba(0,229,255,0.4) 50%, transparent 100%);
          box-shadow: 0 0 12px rgba(0,229,255,0.4);
        }
        .holo-feedback:hover {
          border-color: rgba(0,229,255,0.35);
          transform: translateY(-4px) translateX(3px);
          box-shadow:
            0 0 0 1px rgba(0,229,255,0.07),
            0 24px 70px rgba(0,0,0,0.75),
            0 0 50px rgba(0,229,255,0.09),
            inset 0 1px 0 rgba(255,255,255,0.09);
          background:
            linear-gradient(160deg, rgba(0,6,22,0.99) 0%, rgba(0,14,32,0.97) 50%, rgba(0,5,18,0.99) 100%);
        }

        /* ══════════════════════════════════════════════════════
           REFETCH BUTTON — energy cell style
        ══════════════════════════════════════════════════════ */
        .refetch-btn {
          background:
            linear-gradient(135deg, rgba(0,229,255,0.08) 0%, rgba(0,229,255,0.04) 100%);
          border: 1px solid rgba(0,229,255,0.3); color: var(--cyan);
          border-radius: 4px; padding: 9px 18px; font-size: 9px;
          cursor: pointer; font-family: 'Share Tech Mono', monospace;
          letter-spacing: 0.18em; transition: all 0.25s; text-transform: uppercase;
          clip-path: polygon(0 0, calc(100% - 8px) 0, 100% 8px, 100% 100%, 0 100%);
          box-shadow:
            inset 0 1px 0 rgba(255,255,255,0.07),
            0 0 20px rgba(0,229,255,0.05);
          position: relative; overflow: hidden;
        }
        .refetch-btn::after {
          content: '';
          position: absolute; inset: 0; left: -100%;
          background: linear-gradient(90deg, transparent, rgba(0,229,255,0.12), transparent);
          transition: left 0.4s;
        }
        .refetch-btn:hover::after { left: 100%; }
        .refetch-btn:hover {
          background: linear-gradient(135deg, rgba(0,229,255,0.16) 0%, rgba(0,229,255,0.08) 100%);
          box-shadow:
            0 0 0 1px rgba(0,229,255,0.1),
            0 0 35px rgba(0,229,255,0.22),
            inset 0 1px 0 rgba(255,255,255,0.1);
          border-color: rgba(0,229,255,0.55);
          text-shadow: 0 0 10px var(--cyan);
          transform: translateY(-1px);
        }

        /* ══════════════════════════════════════════════════════
           SCROLLBAR — ultra-thin neon rail
        ══════════════════════════════════════════════════════ */
        ::-webkit-scrollbar { width: 3px; height: 3px; }
        ::-webkit-scrollbar-track { background: rgba(0,6,18,0.9); }
        ::-webkit-scrollbar-thumb {
          background: linear-gradient(180deg, var(--cyan), var(--green));
          border-radius: 2px;
          box-shadow: 0 0 6px var(--cyan);
        }
        ::-webkit-scrollbar-thumb:hover {
          background: linear-gradient(180deg, #80f0ff, var(--cyan));
        }

        /* ══════════════════════════════════════════════════════
           HOLOGRAPHIC SELECTION GLOW
        ══════════════════════════════════════════════════════ */
        ::selection { background: rgba(0,229,255,0.2); color: #ffffff; }
      `}</style>

      {/* Background layers */}
      <div className="aurora" style={isRev ? { filter: `hue-rotate(${rc.hue || 0}deg)` } : {}} />
      <div className="grain" />
      <div className="space-bg" style={isRev ? {
        background: `
          radial-gradient(ellipse 80% 60% at 20% 15%, rgba(${rc.rgb},0.12) 0%, transparent 55%),
          radial-gradient(ellipse 60% 50% at 80% 80%, rgba(${rc.rgb},0.09) 0%, transparent 55%),
          radial-gradient(ellipse 40% 35% at 55% 40%, rgba(${rc.rgb},0.06) 0%, transparent 65%),
          radial-gradient(ellipse 100% 100% at 50% 50%, rgba(${rc.rgb},0.04) 0%, transparent 80%),
          #000d1a`
      } : {}} />
      <div className="vignette" />
      <div className="scanlines" style={isRev ? {
        background: `repeating-linear-gradient(0deg, transparent, transparent 2px, rgba(${rc.rgb},0.018) 2px, rgba(${rc.rgb},0.018) 4px)`
      } : {}} />
      <div className="hud-topline" style={isRev ? {
        background: `linear-gradient(90deg, transparent 0%, ${rc.hex} 20%, rgba(${rc.rgb},0.6) 50%, ${rc.hex} 80%, transparent 100%)`,
        boxShadow: `0 0 24px ${rc.hex}, 0 0 50px rgba(${rc.rgb},0.4)`,
        height: 3,
      } : {}} />
      <HoloGrid />

      <div className="dashboard-root">
        {/* ── SIDEBAR ── */}
        <aside className="sidebar" style={{
          width: sidebarCollapsed ? 64 : 240,
          transition: "width 0.4s cubic-bezier(0.16,1,0.3,1)",
          overflow: "hidden",
          ...(isRev ? {
            borderRight: `1px solid rgba(${rc.rgb},0.3)`,
            boxShadow: `6px 0 80px rgba(${rc.rgb},0.1), 4px 0 0 rgba(${rc.rgb},0.03)`,
          } : {}),
        }}>
          {/* Ambient inner elements */}
          <div className="sidebar-scan" />
          <div className="sidebar-orb" style={isRev ? { background: `radial-gradient(circle, rgba(${rc.rgb},0.05) 0%, transparent 70%)` } : {}} />
          {/* Logo block */}
          <div style={{ padding: sidebarCollapsed ? "20px 8px 18px" : "28px 20px 22px", borderBottom: "1px solid rgba(0,229,255,0.08)", position: "relative", overflow: "hidden", transition: "padding 0.4s" }}>
            {/* Logo area ambient glow */}
            <div style={{ position: "absolute", top: 0, left: 0, right: 0, bottom: 0, background: "radial-gradient(ellipse at 50% 0%, rgba(0,229,255,0.1) 0%, transparent 70%)", pointerEvents: "none" }} />
            {/* Decorative grid lines */}
            {!sidebarCollapsed && <div style={{ position: "absolute", top: 0, right: 20, bottom: 0, width: 1, background: "linear-gradient(180deg, transparent, rgba(0,229,255,0.08), transparent)", pointerEvents: "none" }} />}
            <div style={{ display: "flex", alignItems: "center", gap: sidebarCollapsed ? 0 : 14, marginBottom: sidebarCollapsed ? 0 : 18, justifyContent: sidebarCollapsed ? "center" : "flex-start" }}>
              <div style={{ position: "relative", flexShrink: 0 }}>
                <div style={{
                  width: sidebarCollapsed ? 38 : 48, height: sidebarCollapsed ? 38 : 48,
                  border: "1px solid rgba(0,229,255,0.55)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontSize: sidebarCollapsed ? 16 : 20, color: "var(--cyan)",
                  background: "radial-gradient(circle, rgba(0,229,255,0.18) 0%, rgba(0,229,255,0.05) 100%)",
                  clipPath: "polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)",
                  animation: "pulse-glow 3s ease-in-out infinite",
                  boxShadow: "0 0 30px rgba(0,212,255,0.3), 0 0 60px rgba(0,212,255,0.1), inset 0 0 15px rgba(0,212,255,0.1)",
                  transition: "width 0.4s, height 0.4s, font-size 0.4s",
                  cursor: "pointer",
                }} onClick={() => setSidebarCollapsed(c => !c)}>Ω</div>
                {/* Orbiting dot */}
                <div style={{ position: "absolute", inset: -4, animation: "rotateSlow 4s linear infinite", pointerEvents: "none" }}>
                  <div style={{ width: 4, height: 4, borderRadius: "50%", background: "#00ff88", boxShadow: "0 0 8px #00ff88", position: "absolute", top: 2, left: "50%", transform: "translateX(-50%)" }} />
                </div>
              </div>
              {!sidebarCollapsed && (
                <div style={{ overflow: "hidden", transition: "opacity 0.3s", opacity: sidebarCollapsed ? 0 : 1 }}>
                  <div style={{ fontFamily: "'Orbitron', monospace", fontSize: 14, fontWeight: 800, color: "#f0faff", letterSpacing: "0.06em", animation: "glitchShift 8s infinite", textShadow: "0 0 24px rgba(0,229,255,0.5), 0 0 50px rgba(0,229,255,0.15)", whiteSpace: "nowrap" }}>ArcaneOS</div>
                  <div style={{ fontSize: 7, color: "rgba(0,229,255,0.5)", letterSpacing: "0.28em", textTransform: "uppercase", marginTop: 3, fontFamily: "'Share Tech Mono', monospace", whiteSpace: "nowrap" }}>Admin Console v2.0</div>
                </div>
              )}
            </div>

            {/* Boot progress — hidden in mini mode */}
            {!sidebarCollapsed && (
              <div style={{ marginTop: 4 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                  <span style={{ fontSize: 7, color: "rgba(0,212,255,0.35)", letterSpacing: "0.15em" }}>SYS INTEGRITY</span>
                  <span style={{ fontSize: 7, color: "#00ff88", letterSpacing: "0.1em", fontFamily: "'Orbitron', monospace" }}>{bootSeq}%</span>
                </div>
                <div style={{ height: 2, background: "rgba(0,229,255,0.1)", borderRadius: 1, overflow: "hidden" }}>
                  <div style={{ height: "100%", width: `${bootSeq}%`, background: "linear-gradient(90deg, var(--cyan), var(--green))", boxShadow: "0 0 10px var(--cyan)", borderRadius: 1, transition: "width 0.1s" }} />
                </div>
              </div>
            )}
            {/* Mini mode: just progress dot */}
            {sidebarCollapsed && (
              <div style={{ display: "flex", justifyContent: "center", marginTop: 8 }}>
                <div style={{ width: 6, height: 6, borderRadius: "50%", background: "#00ff9d", boxShadow: "0 0 10px #00ff9d", animation: "pulse-glow 1.5s infinite" }} />
              </div>
            )}
          </div>

          {/* Clock */}
          {!sidebarCollapsed ? (
          <div style={{
            margin: "14px 16px",
            background: "linear-gradient(145deg, rgba(0,229,255,0.06) 0%, rgba(0,6,20,0.85) 100%)",
            border: "1px solid rgba(0,229,255,0.14)",
            borderRadius: 6, padding: "14px 16px",
            position: "relative", overflow: "hidden",
            boxShadow: "inset 0 1px 0 rgba(255,255,255,0.05), 0 4px 20px rgba(0,0,0,0.5)",
            clipPath: "polygon(0 0, calc(100% - 10px) 0, 100% 10px, 100% 100%, 0 100%)",
          }}>
            <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: "linear-gradient(90deg, transparent, rgba(0,229,255,0.6), rgba(0,255,157,0.2), transparent)" }} />
            <div style={{ position: "absolute", inset: 0, background: "radial-gradient(ellipse at 50% 0%, rgba(0,229,255,0.06) 0%, transparent 70%)", pointerEvents: "none" }} />
            {/* Decorative clock corner */}
            <div style={{ position: "absolute", top: 0, right: 10, width: 0, height: 0, borderTop: "10px solid rgba(0,229,255,0.3)", borderLeft: "10px solid transparent" }} />
            <div style={{
              fontFamily: "'Orbitron', monospace", fontSize: 24, fontWeight: 700,
              color: "var(--cyan)", letterSpacing: "0.08em",
              textShadow: "0 0 30px rgba(0,229,255,0.7), 0 0 60px rgba(0,229,255,0.25), 0 0 100px rgba(0,229,255,0.1)",
              position: "relative",
            }}>
              {timeStr}
            </div>
            <div style={{ fontSize: 8, color: "rgba(0,229,255,0.42)", marginTop: 5, letterSpacing: "0.14em", fontFamily: "'Share Tech Mono', monospace" }}>{dateStr.toUpperCase()}</div>
            {/* Pulsing underline */}
            <div style={{ marginTop: 8, height: 1, background: "linear-gradient(90deg, var(--cyan), var(--green), transparent)", animation: "pulse-glow 3s ease-in-out infinite" }} />
          </div>
          ) : (
            /* Mini clock — just hours:mins, centered */
            <div style={{ padding: "10px 0", display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
              <div style={{ fontFamily: "'Orbitron', monospace", fontSize: 10, fontWeight: 700, color: "var(--cyan)", letterSpacing: "0.04em", textShadow: "0 0 14px rgba(0,229,255,0.6)", textAlign: "center" }}>
                {timeStr.slice(0, 5)}
              </div>
              <div style={{ width: 24, height: 1, background: "linear-gradient(90deg, transparent, var(--cyan), transparent)" }} />
            </div>
          )}

          {/* Nav */}
          <div style={{ flex: 1, padding: "10px 0" }}>
            {!sidebarCollapsed && <div style={{
              fontSize: 7, color: "rgba(0,229,255,0.22)", letterSpacing: "0.28em",
              textTransform: "uppercase", padding: "0 20px 10px",
              fontFamily: "'Share Tech Mono', monospace",
              display: "flex", alignItems: "center", gap: 8,
            }}>
              <div style={{ width: 16, height: 1, background: "rgba(0,229,255,0.2)" }} />
              Navigation
              <div style={{ flex: 1, height: 1, background: "rgba(0,229,255,0.08)" }} />
            </div>}
            {sidebarCollapsed ? (
              /* Mini-mode: icon-only tabs */
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 2, padding: "4px 0" }}>
                {TABS.map(t => {
                  const isActive = tab === t.id;
                  const ac = t.id === "revenue" && isActive ? rc.hex : "#00e5ff";
                  return (
                    <div key={t.id} onClick={() => setTab(t.id)} title={t.label}
                      style={{
                        width: 40, height: 40, display: "flex", alignItems: "center", justifyContent: "center",
                        cursor: "pointer", borderRadius: 6,
                        background: isActive ? `rgba(0,229,255,0.12)` : "transparent",
                        border: `1px solid ${isActive ? "rgba(0,229,255,0.35)" : "transparent"}`,
                        boxShadow: isActive ? "0 0 14px rgba(0,229,255,0.2)" : "none",
                        transition: "all 0.25s",
                        position: "relative",
                      }}
                      onMouseEnter={e => { if (!isActive) { e.currentTarget.style.background = "rgba(0,229,255,0.06)"; } }}
                      onMouseLeave={e => { if (!isActive) { e.currentTarget.style.background = "transparent"; } }}
                    >
                      {isActive && <div style={{ position: "absolute", left: 0, top: "20%", bottom: "20%", width: 2, background: ac, borderRadius: "0 2px 2px 0", boxShadow: `0 0 8px ${ac}` }} />}
                      <span style={{ fontSize: 16, color: isActive ? ac : "rgba(0,212,255,0.3)", textShadow: isActive ? `0 0 14px ${ac}` : "none", transition: "all 0.2s" }}>{t.icon}</span>
                      {t.count !== undefined && (
                        <div style={{ position: "absolute", top: 4, right: 4, width: 14, height: 14, borderRadius: "50%", background: "#ff2d55", fontSize: 6, color: "#fff", display: "flex", alignItems: "center", justifyContent: "center", fontFamily: "'Orbitron', monospace", fontWeight: 700 }}>{t.count > 9 ? "9+" : t.count}</div>
                      )}
                    </div>
                  );
                })}
                {/* Collapse toggle button */}
                <div onClick={() => setSidebarCollapsed(false)} title="Expand sidebar"
                  style={{ width: 40, height: 32, display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", marginTop: 4, borderRadius: 4, transition: "all 0.2s" }}
                  onMouseEnter={e => { e.currentTarget.style.background = "rgba(0,229,255,0.06)"; }}
                  onMouseLeave={e => { e.currentTarget.style.background = "transparent"; }}
                >
                  <span style={{ fontSize: 10, color: "rgba(0,229,255,0.3)" }}>▶</span>
                </div>
              </div>
            ) : (
              TABS.map(t => (
                <NavTab key={t.id} label={t.label} active={tab === t.id} onClick={() => setTab(t.id)} count={t.count} icon={t.icon} activeColor={t.id === "revenue" && displayTab === "revenue" ? rc.hex : undefined} />
              ))
            )}
          </div>

          {/* System status */}
          <div style={{ padding: sidebarCollapsed ? "10px 8px 16px" : "14px 18px 22px", borderTop: "1px solid rgba(0,229,255,0.07)", position: "relative" }}>
            {/* Section label */}
            {!sidebarCollapsed && <div style={{
              fontSize: 7, color: "rgba(0,229,255,0.22)", letterSpacing: "0.28em",
              textTransform: "uppercase", marginBottom: 12,
              display: "flex", alignItems: "center", gap: 6,
              fontFamily: "'Share Tech Mono', monospace",
            }}>
              <div style={{ width: 16, height: 1, background: "rgba(0,229,255,0.2)" }} />
              Systems
              <div style={{ flex: 1, height: 1, background: "rgba(0,229,255,0.08)" }} />
            </div>}
            {!sidebarCollapsed ? [["API Gateway", "#00ff9d", "NOMINAL"], ["Database", "#00ff9d", "ONLINE"], ["Auth Layer", "#ffd060", "STANDBY"]].map(([name, col, status]) => (
              <div key={name} style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 8, padding: "5px 8px", background: "rgba(0,0,0,0.15)", borderRadius: 3, border: "1px solid rgba(0,229,255,0.05)", position: "relative", overflow: "hidden" }}>
                <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 2, background: col, borderRadius: "3px 0 0 3px", boxShadow: `0 0 6px ${col}`, opacity: 0.6 }} />
                <span style={{ fontSize: 9, color: "rgba(0,229,255,0.45)", fontFamily: "'Share Tech Mono', monospace", paddingLeft: 6 }}>{name}</span>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                  <div style={{
                    width: 5, height: 5, borderRadius: "50%", background: col,
                    boxShadow: `0 0 10px ${col}, 0 0 20px ${col}55`,
                    animation: "pulse-glow 2s infinite",
                  }} />
                  <span style={{ fontSize: 7, color: col + "cc", letterSpacing: "0.1em", fontFamily: "'Share Tech Mono', monospace" }}>{status}</span>
                </div>
              </div>
            )) : (
              /* Mini-mode: status dots only */
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 6 }}>
                {[["#00ff9d"], ["#00ff9d"], ["#ffd060"]].map(([col], i) => (
                  <div key={i} style={{ width: 6, height: 6, borderRadius: "50%", background: col, boxShadow: `0 0 8px ${col}`, animation: "pulse-glow 2s infinite" }} />
                ))}
              </div>
            )}

            {/* Sign Out — dramatic terminate session button */}
            <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid rgba(255,45,85,0.12)", position: "relative" }}>
              {/* Ambient red glow behind button */}
              <div style={{ position: "absolute", inset: 0, background: "radial-gradient(ellipse at 50% 100%, rgba(255,45,85,0.04) 0%, transparent 70%)", pointerEvents: "none" }} />
              <button
                onClick={async () => {
                  localStorage.removeItem("access_token");
                  localStorage.removeItem("refresh_token");
                  localStorage.removeItem("token");
                  sessionStorage.clear();
                  setIsLoggedIn(false);
                  showToast("Session terminated", "warning");
                }}
                style={{
                  width: "100%", display: "flex", alignItems: "center", gap: 10,
                  padding: "12px 14px", cursor: "pointer",
                  background: "linear-gradient(135deg, rgba(255,45,85,0.09) 0%, rgba(180,20,50,0.04) 60%, rgba(255,45,85,0.06) 100%)",
                  border: "1px solid rgba(255,45,85,0.28)",
                  borderRadius: 4, transition: "all 0.3s cubic-bezier(0.16,1,0.3,1)",
                  clipPath: "polygon(0 0, calc(100% - 9px) 0, 100% 9px, 100% 100%, 0 100%)",
                  fontFamily: "'Share Tech Mono', monospace",
                  boxShadow: "inset 0 1px 0 rgba(255,255,255,0.05), 0 0 30px rgba(255,45,85,0.04)",
                  position: "relative", overflow: "hidden",
                }}
                onMouseEnter={e => {
                  e.currentTarget.style.background = "linear-gradient(135deg, rgba(255,45,85,0.18) 0%, rgba(255,45,85,0.08) 100%)";
                  e.currentTarget.style.borderColor = "rgba(255,45,85,0.6)";
                  e.currentTarget.style.boxShadow = "0 0 35px rgba(255,45,85,0.25), 0 0 60px rgba(255,45,85,0.08), inset 0 1px 0 rgba(255,255,255,0.07)";
                  e.currentTarget.style.transform = "translateY(-2px)";
                }}
                onMouseLeave={e => {
                  e.currentTarget.style.background = "linear-gradient(135deg, rgba(255,45,85,0.09) 0%, rgba(180,20,50,0.04) 60%, rgba(255,45,85,0.06) 100%)";
                  e.currentTarget.style.borderColor = "rgba(255,45,85,0.28)";
                  e.currentTarget.style.boxShadow = "inset 0 1px 0 rgba(255,255,255,0.05), 0 0 30px rgba(255,45,85,0.04)";
                  e.currentTarget.style.transform = "translateY(0)";
                }}
              >
                {/* Scan shimmer */}
                <div style={{ position: "absolute", inset: 0, left: "-100%", width: "80%", background: "linear-gradient(90deg, transparent, rgba(255,45,85,0.08), transparent)", animation: "shimmerSlide 4s ease-in-out 1s infinite", pointerEvents: "none" }} />
                {/* Top edge accent */}
                <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: "linear-gradient(90deg, transparent, rgba(255,45,85,0.5), rgba(255,45,85,0.2), transparent)" }} />
                {/* Power icon with glow ring */}
                <div style={{ position: "relative", width: 22, height: 22, display: "flex", alignItems: "center", justifyContent: "center", flexShrink: 0 }}>
                  <div style={{ position: "absolute", inset: -2, borderRadius: "50%", border: "1px solid rgba(255,45,85,0.3)", boxShadow: "0 0 8px rgba(255,45,85,0.2)", animation: "pulseRing 2.5s ease-in-out infinite" }} />
                  <span style={{ fontSize: 14, color: "rgba(255,45,85,0.85)", textShadow: "0 0 14px rgba(255,45,85,0.6), 0 0 30px rgba(255,45,85,0.25)" }}>⏻</span>
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 9, color: "rgba(255,45,85,0.75)", letterSpacing: "0.2em", textTransform: "uppercase" }}>Terminate Session</div>
                  <div style={{ fontSize: 7, color: "rgba(255,45,85,0.35)", letterSpacing: "0.15em", marginTop: 2, fontFamily: "'Share Tech Mono', monospace" }}>SECURE LOGOUT</div>
                </div>
                {/* Corner cut indicator */}
                <div style={{ position: "absolute", top: 0, right: 9, width: 0, height: 0, borderTop: "9px solid rgba(255,45,85,0.35)", borderLeft: "9px solid transparent" }} />
              </button>
              {/* Version tag below */}
              <div style={{ marginTop: 10, textAlign: "center", fontSize: 7, color: "rgba(0,229,255,0.15)", letterSpacing: "0.18em", fontFamily: "'Share Tech Mono', monospace" }}>
                ARCANEOS v2.0 · CLASSIFIED
              </div>
            </div>
          </div>
        </aside>

        {/* ── MAIN ── */}
        <main className="main-content" style={{ marginLeft: sidebarCollapsed ? 64 : 240, transition: "margin-left 0.4s cubic-bezier(0.16,1,0.3,1)" }}>
          {/* Topbar */}
          <div className="topbar" style={isRev ? {
            borderBottom: `1px solid rgba(${rc.rgb},0.18)`,
            boxShadow: `0 1px 0 rgba(${rc.rgb},0.12), 0 8px 50px rgba(${rc.rgb},0.06)`,
          } : {}}>
            <div className="topbar-scan" />
            <div style={{ display: "flex", flexDirection: "column", gap: 6, position: "relative", zIndex: 1 }}>
              <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                <span style={{
                  color: isRev ? rc.hex : "var(--cyan)", fontSize: 18,
                  fontFamily: "'Share Tech Mono', monospace",
                  textShadow: isRev ? `0 0 22px ${rc.hex}, 0 0 50px rgba(${rc.rgb},0.4)` : "0 0 16px rgba(0,229,255,0.8), 0 0 40px rgba(0,229,255,0.3)",
                  transition: "color 0.4s, text-shadow 0.4s",
                  animation: "pulse-glow 3s ease-in-out infinite",
                }}>{TABS.find(t => t.id === tab)?.icon}</span>
                <h1 style={{
                  fontFamily: "'Orbitron', monospace", fontSize: 28, fontWeight: 900,
                  color: "#fff", letterSpacing: "0.12em", lineHeight: 1,
                  textShadow: isRev
                    ? `0 0 30px rgba(${rc.rgb},0.9), 0 0 60px rgba(${rc.rgb},0.45), 0 0 100px rgba(${rc.rgb},0.2)`
                    : "0 0 30px rgba(0,229,255,0.6), 0 0 70px rgba(0,229,255,0.25), 0 0 120px rgba(0,229,255,0.1)",
                  transition: "text-shadow 0.4s",
                  animation: "textGlow 4s ease-in-out infinite",
                }}>
                  {TABS.find(t => t.id === tab)?.label}
                </h1>
                {/* Title underline accent */}
                <div style={{
                  height: 2, width: 40, marginTop: 2,
                  background: isRev
                    ? `linear-gradient(90deg, ${rc.hex}, transparent)`
                    : "linear-gradient(90deg, var(--cyan), transparent)",
                  boxShadow: isRev ? `0 0 10px ${rc.hex}` : "0 0 10px var(--cyan)",
                  borderRadius: 1,
                }} />
              </div>
              <div style={{
                fontSize: 8, letterSpacing: "0.26em", transition: "color 0.4s", paddingLeft: 32,
                color: isRev ? `rgba(${rc.rgb},0.45)` : "rgba(0,229,255,0.3)",
                fontFamily: "'Share Tech Mono', monospace",
              }}>ARCANEOS · INTELLIGENCE LAYER · CLASSIFIED ACCESS</div>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 12, position: "relative", zIndex: 1 }}>
              {error && <span style={{ fontSize: 9, color: "var(--red)", fontFamily: "'Share Tech Mono', monospace", textShadow: "0 0 10px rgba(255,45,85,0.5)" }}>⚠ ERR: {error}</span>}

              {/* ⌘K Command Palette trigger */}
              <button onClick={() => setPaletteOpen(true)}
                style={{
                  display: "flex", alignItems: "center", gap: 8,
                  padding: "7px 14px",
                  background: "rgba(0,229,255,0.04)",
                  border: "1px solid rgba(0,229,255,0.18)",
                  borderRadius: 5, cursor: "pointer",
                  clipPath: "polygon(0 0, calc(100% - 8px) 0, 100% 8px, 100% 100%, 0 100%)",
                  transition: "all 0.25s",
                  position: "relative", overflow: "hidden",
                }}
                onMouseEnter={e => { e.currentTarget.style.background = "rgba(0,229,255,0.09)"; e.currentTarget.style.borderColor = "rgba(0,229,255,0.4)"; e.currentTarget.style.boxShadow = "0 0 20px rgba(0,229,255,0.15)"; }}
                onMouseLeave={e => { e.currentTarget.style.background = "rgba(0,229,255,0.04)"; e.currentTarget.style.borderColor = "rgba(0,229,255,0.18)"; e.currentTarget.style.boxShadow = "none"; }}
              >
                <span style={{ fontSize: 9, color: "rgba(0,229,255,0.5)", fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.06em" }}>⌘</span>
                <span style={{ fontSize: 8, color: "rgba(0,229,255,0.35)", fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.12em" }}>COMMAND</span>
                <div style={{ display: "flex", gap: 3 }}>
                  {["⌘", "K"].map(k => (
                    <kbd key={k} style={{ fontSize: 7, color: "rgba(0,229,255,0.3)", fontFamily: "'Share Tech Mono', monospace", background: "rgba(0,229,255,0.06)", border: "1px solid rgba(0,229,255,0.15)", padding: "1px 5px", borderRadius: 3 }}>{k}</kbd>
                  ))}
                </div>
              </button>

              <button onClick={refetch} className="refetch-btn" style={isRev ? {
                borderColor: `rgba(${rc.rgb},0.35)`,
                color: rc.hex,
                background: `linear-gradient(135deg, rgba(${rc.rgb},0.1) 0%, rgba(${rc.rgb},0.04) 100%)`,
                boxShadow: `0 0 20px rgba(${rc.rgb},0.06)`,
              } : {}}>↺ REFRESH</button>
              {/* Theme toggle */}
              <ThemeToggle dark={dark} onToggle={() => setDark(d => !d)} />
              {/* Export button */}
              <button onClick={() => setExportOpen(true)}
                style={{
                  display: "flex", alignItems: "center", gap: 7,
                  padding: "7px 14px",
                  background: "rgba(0,255,157,0.04)",
                  border: "1px solid rgba(0,255,157,0.22)",
                  borderRadius: 5, cursor: "pointer",
                  clipPath: "polygon(0 0, calc(100% - 8px) 0, 100% 8px, 100% 100%, 0 100%)",
                  transition: "all 0.25s",
                  position: "relative", overflow: "hidden",
                }}
                onMouseEnter={e => { e.currentTarget.style.background = "rgba(0,255,157,0.1)"; e.currentTarget.style.borderColor = "rgba(0,255,157,0.45)"; e.currentTarget.style.boxShadow = "0 0 20px rgba(0,255,157,0.14)"; }}
                onMouseLeave={e => { e.currentTarget.style.background = "rgba(0,255,157,0.04)"; e.currentTarget.style.borderColor = "rgba(0,255,157,0.22)"; e.currentTarget.style.boxShadow = "none"; }}
              >
                <div style={{ position: "absolute", inset: 0, left: "-100%", background: "linear-gradient(90deg, transparent, rgba(0,255,157,0.07), transparent)", animation: "shimmerSlide 4s ease-in-out infinite", pointerEvents: "none" }} />
                <span style={{ fontSize: 10, color: "rgba(0,255,157,0.65)" }}>⇣</span>
                <span style={{ fontSize: 8, color: "rgba(0,255,157,0.5)", fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.12em" }}>EXPORT</span>
                <kbd style={{ fontSize: 7, color: "rgba(0,255,157,0.3)", fontFamily: "'Share Tech Mono', monospace", background: "rgba(0,255,157,0.06)", border: "1px solid rgba(0,255,157,0.15)", padding: "1px 5px", borderRadius: 3 }}>⇧E</kbd>
              </button>
              {/* Sidebar collapse toggle */}
              <button onClick={() => setSidebarCollapsed(c => !c)}
                title={sidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
                style={{
                  display: "flex", alignItems: "center", justifyContent: "center",
                  width: 34, height: 34,
                  background: sidebarCollapsed ? "rgba(0,229,255,0.08)" : "rgba(0,229,255,0.04)",
                  border: `1px solid rgba(0,229,255,${sidebarCollapsed ? 0.35 : 0.18})`,
                  borderRadius: 5, cursor: "pointer",
                  clipPath: "polygon(0 0, calc(100% - 6px) 0, 100% 6px, 100% 100%, 0 100%)",
                  transition: "all 0.25s",
                  boxShadow: sidebarCollapsed ? "0 0 14px rgba(0,229,255,0.15)" : "none",
                }}
                onMouseEnter={e => { e.currentTarget.style.background = "rgba(0,229,255,0.12)"; e.currentTarget.style.borderColor = "rgba(0,229,255,0.5)"; }}
                onMouseLeave={e => { e.currentTarget.style.background = sidebarCollapsed ? "rgba(0,229,255,0.08)" : "rgba(0,229,255,0.04)"; e.currentTarget.style.borderColor = `rgba(0,229,255,${sidebarCollapsed ? 0.35 : 0.18})`; }}
              >
                <span style={{ fontSize: 11, color: "rgba(0,229,255,0.6)", transform: sidebarCollapsed ? "scaleX(-1)" : "scaleX(1)", display: "inline-block", transition: "transform 0.35s cubic-bezier(0.16,1,0.3,1)" }}>⊟</span>
              </button>
              {/* User avatar hex */}
              <div style={{
                width: 40, height: 40, position: "relative",
                background: isRev ? `radial-gradient(circle, rgba(${rc.rgb},0.22) 0%, rgba(${rc.rgb},0.08) 100%)` : "radial-gradient(circle, rgba(0,229,255,0.18) 0%, rgba(0,229,255,0.06) 100%)",
                border: `1px solid ${isRev ? `rgba(${rc.rgb},0.6)` : "rgba(0,229,255,0.5)"}`,
                display: "flex", alignItems: "center", justifyContent: "center",
                fontSize: 15, color: isRev ? rc.hex : "var(--cyan)", fontFamily: "'Orbitron', monospace",
                clipPath: "polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)",
                boxShadow: isRev
                  ? `0 0 35px rgba(${rc.rgb},0.45), inset 0 0 15px rgba(${rc.rgb},0.12), 0 0 60px rgba(${rc.rgb},0.15)`
                  : "0 0 35px rgba(0,229,255,0.35), inset 0 0 15px rgba(0,229,255,0.1), 0 0 60px rgba(0,229,255,0.12)",
                transition: "all 0.4s",
                animation: "pulse-glow 4s ease-in-out infinite",
              }}>W</div>
            </div>
          </div>

          {/* ═══════════════ TAB CONTENT — with enter/exit transitions ═══════════════ */}
          <div style={{ ...transitionStyle }}>

          {/* ═══════════════ OVERVIEW TAB ═══════════════ */}
          {displayTab === "overview" && (
            <div>
              {loading ? <HoloLoader /> : m && (
                <>
                  {/* ── MISSION STATUS HEADER — with live system bar ── */}
                  <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 18 }}>
                    <div className="section-heading" style={{ marginBottom: 0, flex: 1 }}>Mission Status</div>
                    <div style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 8, fontFamily: "'Share Tech Mono', monospace" }}>
                      {[
                        { l: "CPU", v: 23, c: "#00ff9d" },
                        { l: "MEM", v: 61, c: "#00e5ff" },
                        { l: "NET", v: 88, c: "#bf5fff" },
                      ].map(({ l, v, c }) => (
                        <div key={l} style={{ display: "flex", alignItems: "center", gap: 5 }}>
                          <span style={{ color: "rgba(0,229,255,0.35)", letterSpacing: "0.12em" }}>{l}</span>
                          <div style={{ width: 40, height: 3, background: "rgba(0,229,255,0.08)", borderRadius: 2, overflow: "hidden", position: "relative" }}>
                            <div style={{ position: "absolute", inset: 0, width: `${v}%`, background: `linear-gradient(90deg, ${c}88, ${c})`, borderRadius: 2, boxShadow: `0 0 6px ${c}` }} />
                          </div>
                          <span style={{ color: c, fontFamily: "'Orbitron', monospace", fontSize: 9 }}>{v}</span>
                        </div>
                      ))}
                      <div style={{ width: 4, height: 4, borderRadius: "50%", background: "#00ff9d", boxShadow: "0 0 8px #00ff9d", animation: "pulse-glow 1s infinite" }} />
                      <span style={{ color: "rgba(0,255,157,0.6)", letterSpacing: "0.15em" }}>ALL SYSTEMS NOMINAL</span>
                    </div>
                  </div>

                  {/* ── METRIC CARDS — 4 columns with embedded mini data viz ── */}
                  <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 14, marginBottom: 22 }}>
                    <HoloCard
                      label="Total Users" value={m.users.total} icon="⬡" color="#00e5ff"
                      sub={`${m.users.paid} paid · ${m.users.trialing} trialing`}
                      trend={12} delay={0} accentShape="ring"
                      story="NETWORK GROWTH NOMINAL"
                    />
                    <HoloCard
                      label="MRR" value={`$${m.revenue.mrr}`} icon="◎" color="#00ff9d"
                      sub="Monthly Recurring Revenue"
                      trend={8} delay={80} accentShape="hex"
                      story="CASHFLOW STREAM ACTIVE"
                    />
                    <HoloCard
                      label="ARR" value={`$${m.revenue.arr?.toLocaleString()}`} icon="↑" color="#bf5fff"
                      sub="Annualized Run Rate"
                      trend={15} delay={160} accentShape="cross"
                      story="PROJECTION TRAJECTORY ↑"
                    />
                    <HoloCard
                      label="Tasks Today" value={m.tasks.created_today} icon="✦" color="#ffd060"
                      sub={`${m.tasks.completion_rate}% completion rate`}
                      trend={5} delay={240} accentShape="ring"
                      story="OPERATIONS RUNNING HOT"
                    />
                  </div>

                  {/* ── DATA VISUALIZATION OVERLAY STRIP — new addition ── */}
                  <DataVizOverlayStrip m={m} />

                  {/* Main panels row */}
                  <div style={{ display: "grid", gridTemplateColumns: "1.6fr 1fr 280px", gap: 14, marginBottom: 16 }}>

                    {/* Signup trend — tells story of growth */}
                    <HoloPanel title="Signup Velocity — Live Feed" accent="#00d4ff">
                      <div style={{ marginBottom: 10 }}>
                        <div style={{ display: "flex", gap: 20, marginBottom: 14 }}>
                          <div>
                            <div style={{ fontSize: 8, color: "rgba(0,212,255,0.35)", letterSpacing: "0.15em", marginBottom: 4 }}>PEAK DAY</div>
                            <div style={{ fontSize: 16, fontFamily: "'Orbitron', monospace", color: "#00d4ff", textShadow: "0 0 15px rgba(0,212,255,0.5)" }}>
                              {m.signup_trend ? Math.max(...m.signup_trend.map(d => d.signups)) : "—"}
                            </div>
                          </div>
                          <div>
                            <div style={{ fontSize: 8, color: "rgba(0,212,255,0.35)", letterSpacing: "0.15em", marginBottom: 4 }}>30D TOTAL</div>
                            <div style={{ fontSize: 16, fontFamily: "'Orbitron', monospace", color: "#00ff88", textShadow: "0 0 15px rgba(0,255,136,0.5)" }}>
                              {m.signup_trend ? m.signup_trend.reduce((a, d) => a + d.signups, 0) : "—"}
                            </div>
                          </div>
                          <div style={{ marginLeft: "auto", display: "flex", alignItems: "center" }}>
                            <div style={{ display: "flex", alignItems: "center", gap: 5, fontSize: 8, color: "#00ff88", fontFamily: "'Share Tech Mono', monospace" }}>
                              <div style={{ width: 4, height: 4, borderRadius: "50%", background: "#00ff88", animation: "pulse-glow 1s infinite" }} />
                              LIVE
                            </div>
                          </div>
                        </div>
                        <HoloSparkline values={m.signup_trend?.map(d => d.signups)} color="#00d4ff" height={80} />
                        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6, fontSize: 7, color: "rgba(0,212,255,0.25)" }}>
                          <span>{m.signup_trend?.[0]?.date}</span><span>TODAY</span>
                        </div>
                      </div>
                    </HoloPanel>

                    {/* Subscription breakdown — tactical breakdown */}
                    <HoloPanel title="Subscriber Intelligence" accent="#00ff9d">
                      {[
                        { label: "Paid",      count: m.users.paid,      color: "#00ff9d" },
                        { label: "Trialing",  count: m.users.trialing,  color: "#ffd060" },
                        { label: "Cancelled", count: m.users.cancelled, color: "#ff2d55" },
                        { label: "Exempt",    count: m.users.exempt,    color: "#bf5fff" },
                      ].map(({ label, count, color }) => {
                        const pct = m.users.total ? Math.round((count / m.users.total) * 100) : 0;
                        return (
                          <div key={label} style={{ marginBottom: 14 }}>
                            <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 5, alignItems: "center" }}>
                              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                <div style={{ width: 5, height: 5, background: color, boxShadow: `0 0 8px ${color}`, clipPath: "polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)" }} />
                                <span style={{ fontSize: 9, color: "rgba(0,212,255,0.5)", letterSpacing: "0.1em" }}>{label.toUpperCase()}</span>
                              </div>
                              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                                <span style={{ fontSize: 8, color: "rgba(0,212,255,0.25)" }}>{pct}%</span>
                                <span style={{ fontSize: 14, color, fontWeight: 700, fontFamily: "'Orbitron', monospace", textShadow: `0 0 10px ${color}80` }}>{count}</span>
                              </div>
                            </div>
                            <div style={{ height: 3, background: "rgba(0,212,255,0.06)", borderRadius: 1, overflow: "hidden" }}>
                              <div style={{ height: "100%", width: `${pct}%`, background: `linear-gradient(90deg, ${color}40, ${color})`, borderRadius: 1, transition: "width 1s cubic-bezier(0.4,0,0.2,1)", boxShadow: `0 0 8px ${color}50` }} />
                            </div>
                          </div>
                        );
                      })}

                      <div style={{ marginTop: 16, paddingTop: 14, borderTop: "1px solid rgba(0,212,255,0.06)" }}>
                        <div style={{ fontSize: 8, color: "rgba(0,212,255,0.3)", letterSpacing: "0.2em", marginBottom: 10 }}>ROLE MATRIX</div>
                        {Object.entries(m.users.by_role || {}).map(([role, count]) => (
                          <div key={role} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 6 }}>
                            <span style={{ fontSize: 9, color: "rgba(0,212,255,0.4)", textTransform: "uppercase", letterSpacing: "0.1em" }}>{role}</span>
                            <span style={{ fontSize: 12, color: "#00d4ff", fontWeight: 700, fontFamily: "'Orbitron', monospace" }}>{count}</span>
                          </div>
                        ))}
                      </div>
                    </HoloPanel>
                    {/* ARC REACTOR — live MRR orb + mission readout */}
                    <HoloPanel accent="#00ff9d" style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 14, padding: "24px 18px" }}>
                      <div style={{ fontSize: 8, color: "rgba(0,255,157,0.5)", letterSpacing: "0.28em", textTransform: "uppercase", fontFamily: "'Share Tech Mono', monospace", alignSelf: "flex-start", display: "flex", alignItems: "center", gap: 6 }}>
                        <div style={{ width: 5, height: 5, background: "#00ff9d", borderRadius: "50%", boxShadow: "0 0 10px #00ff9d", animation: "pulse-glow 1.5s infinite" }} />
                        Revenue Core
                      </div>
                      <ArcReactor color="#00ff9d" rgb="0,255,157" value={`$${m.revenue.mrr}`} label="MRR" size={160} />
                      <div style={{ width: "100%", display: "flex", flexDirection: "column", gap: 6 }}>
                        {[
                          { l: "ARR", v: `$${(m.revenue.arr||0).toLocaleString()}`, c: "#ffd060" },
                          { l: "QRR", v: `$${m.revenue.qrr}`, c: "#00e5ff" },
                          { l: "Users", v: m.users.total, c: "#bf5fff" },
                        ].map(({ l, v, c }) => (
                          <div key={l} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "7px 12px", background: "rgba(0,0,0,0.2)", border: "1px solid rgba(0,255,157,0.08)", borderRadius: 3, position: "relative", overflow: "hidden" }}>
                            <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 2, background: c, borderRadius: "3px 0 0 3px", boxShadow: `0 0 8px ${c}` }} />
                            <span style={{ fontSize: 7, color: "rgba(0,255,157,0.4)", letterSpacing: "0.18em", fontFamily: "'Share Tech Mono', monospace" }}>{l}</span>
                            <span style={{ fontSize: 14, fontWeight: 700, color: c, fontFamily: "'Orbitron', monospace", textShadow: `0 0 10px ${c}80` }}>{v}</span>
                          </div>
                        ))}
                      </div>
                    </HoloPanel>
                  </div>

                  {/* ── SYSTEM STATUS PULSE BAR ── */}
                  <div style={{ marginBottom: 18 }}>
                    <SystemStatusPulseBar />
                  </div>

                  {/* ── ACTIVITY FEED + TELEMETRY ROW ── */}
                  <div style={{ display: "grid", gridTemplateColumns: "1fr 1.5fr", gap: 14, marginBottom: 22, marginTop: 4 }}>
                    <div>
                      <div className="section-heading" style={{ marginBottom: 14 }}>Live Activity</div>
                      <ActivityFeed m={m} />
                    </div>
                    <div>
                  {/* Stat strip */}
                  <div className="section-heading">Telemetry</div>
                  <div className="stat-row">
                    {[
                      { label: "New / Week",    value: m.users.new_this_week,                color: "#00e5ff" },
                      { label: "New / Month",   value: m.users.new_this_month,               color: "#00e5ff" },
                      { label: "Tasks Today",   value: m.tasks.created_today,                color: "#00ff9d" },
                      { label: "Completion",    value: `${m.tasks.completion_rate}%`,        color: "#00ff9d" },
                      { label: "MRR",           value: `$${m.revenue.mrr}`,                  color: "#ffd060" },
                      { label: "QRR",           value: `$${m.revenue.qrr}`,                  color: "#ffd060" },
                      { label: "ARR",           value: `$${(m.revenue.arr||0).toLocaleString()}`, color: "#ffd060" },
                    ].map(({ label, value, color }, i) => (
                      <div key={label} className="stat-item" style={{ animationDelay: `${i * 50}ms`, animation: "holoRise 0.6s cubic-bezier(0.16,1,0.3,1) both" }}>
                        <div className="stat-label">{label}</div>
                        <div className="stat-val" style={{ color, textShadow: `0 0 14px ${color}80` }}>{value}</div>
                      </div>
                    ))}
                  </div>
                    </div>
                  </div>{/* end activity + telemetry grid */}
                </>
              )}
            </div>
          )}

          {/* ═══════════════ REVENUE TAB — JARVIS HUD ═══════════════ */}
          {displayTab === "revenue" && (
            <div style={{ position: "relative" }}>
              {/* Ambient aurora */}
              <div style={{
                position: "fixed", inset: 0, pointerEvents: "none", zIndex: 1,
                background: `
                  radial-gradient(ellipse 55% 45% at 65% 18%, rgba(${rc.rgb},0.09) 0%, transparent 60%),
                  radial-gradient(ellipse 45% 55% at 18% 75%, rgba(${rc.rgb},0.06) 0%, transparent 60%),
                  radial-gradient(ellipse 70% 25% at 50% 50%, rgba(${rc.rgb},0.04) 0%, transparent 70%)
                `,
                transition: "background 0.5s",
              }} />
              {/* HUD corner brackets */}
              <div style={{ position: "fixed", top: 0, left: 220, right: 0, height: "100vh", pointerEvents: "none", zIndex: 2, overflow: "hidden" }}>
                <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 1, background: `linear-gradient(180deg, transparent 5%, rgba(${rc.rgb},0.2) 30%, rgba(${rc.rgb},0.08) 70%, transparent)` }} />
                <div style={{ position: "absolute", top: 72, left: 20, width: 20, height: 20, borderTop: `1px solid rgba(${rc.rgb},0.5)`, borderLeft: `1px solid rgba(${rc.rgb},0.5)` }} />
                <div style={{ position: "absolute", top: 72, right: 20, width: 20, height: 20, borderTop: `1px solid rgba(${rc.rgb},0.5)`, borderRight: `1px solid rgba(${rc.rgb},0.5)` }} />
                <div style={{ position: "absolute", bottom: 30, left: 20, width: 20, height: 20, borderBottom: `1px solid rgba(${rc.rgb},0.5)`, borderLeft: `1px solid rgba(${rc.rgb},0.5)` }} />
                <div style={{ position: "absolute", bottom: 30, right: 20, width: 20, height: 20, borderBottom: `1px solid rgba(${rc.rgb},0.5)`, borderRight: `1px solid rgba(${rc.rgb},0.5)` }} />
                {/* Sweep line */}
                <div style={{ position: "absolute", left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, rgba(${rc.rgb},0.12), transparent)`, animation: "dataStream 8s linear infinite", boxShadow: `0 0 6px rgba(${rc.rgb},0.15)` }} />
              </div>

              {loading ? <HoloLoader /> : m && (
                <>
                  {/* ── REVENUE COMMAND BRIDGE — full-width dramatic header ── */}
                  <div style={{
                    position: "relative", marginBottom: 18, overflow: "hidden",
                    background: `linear-gradient(135deg, rgba(0,4,14,0.98) 0%, rgba(0,8,22,0.95) 40%, rgba(0,4,14,0.98) 100%)`,
                    border: `1px solid rgba(${rc.rgb},0.22)`,
                    borderRadius: 6, padding: "18px 24px",
                    clipPath: "polygon(0 0, calc(100% - 20px) 0, 100% 20px, 100% 100%, 20px 100%, 0 calc(100% - 20px))",
                    boxShadow: `0 0 80px rgba(${rc.rgb},0.07), inset 0 1px 0 rgba(255,255,255,0.05), inset 0 0 60px rgba(${rc.rgb},0.02)`,
                  }}>
                    {/* Prismatic top edge */}
                    <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 2, background: `linear-gradient(90deg, transparent 0%, ${rc.hex} 20%, rgba(255,255,255,0.7) 50%, ${rc.hex} 80%, transparent 100%)`, boxShadow: `0 0 20px ${rc.hex}, 0 0 40px rgba(${rc.rgb},0.3)`, animation: "prismaticEdge 3s linear infinite" }} />
                    {/* Left accent bar */}
                    <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 4, background: `linear-gradient(180deg, ${rc.hex}, rgba(${rc.rgb},0.3), transparent)`, boxShadow: `0 0 16px rgba(${rc.rgb},0.5)` }} />
                    {/* Corner accent */}
                    <div style={{ position: "absolute", top: 0, right: 20, width: 0, height: 0, borderTop: `20px solid rgba(${rc.rgb},0.3)`, borderLeft: "20px solid transparent" }} />
                    <div style={{ position: "absolute", bottom: 0, left: 20, width: 0, height: 0, borderBottom: `10px solid rgba(${rc.rgb},0.15)`, borderRight: "10px solid transparent" }} />
                    {/* Inner radial glow */}
                    <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at 30% 50%, rgba(${rc.rgb},0.06) 0%, transparent 60%)`, pointerEvents: "none" }} />
                    {/* Shimmer sweep */}
                    <div style={{ position: "absolute", inset: 0, left: "-100%", width: "60%", background: `linear-gradient(90deg, transparent, rgba(${rc.rgb},0.04), rgba(255,255,255,0.02), transparent)`, animation: "shimmerSlide 6s ease-in-out 0.5s infinite", pointerEvents: "none" }} />

                    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", position: "relative" }}>
                      <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                        {/* Pulsing hex icon */}
                        <div style={{
                          width: 44, height: 44, flexShrink: 0,
                          background: `radial-gradient(circle, rgba(${rc.rgb},0.22) 0%, rgba(${rc.rgb},0.06) 100%)`,
                          border: `1px solid rgba(${rc.rgb},0.5)`,
                          display: "flex", alignItems: "center", justifyContent: "center",
                          fontSize: 18, color: rc.hex,
                          clipPath: "polygon(50% 0%, 100% 25%, 100% 75%, 50% 100%, 0% 75%, 0% 25%)",
                          boxShadow: `0 0 30px rgba(${rc.rgb},0.35), inset 0 0 15px rgba(${rc.rgb},0.12)`,
                          animation: "pulse-glow 3s ease-in-out infinite",
                        }}>◎</div>
                        <div>
                          <div style={{ fontFamily: "'Orbitron', monospace", fontSize: 13, fontWeight: 800, color: "#fff", letterSpacing: "0.12em", textShadow: `0 0 24px rgba(${rc.rgb},0.8), 0 0 50px rgba(${rc.rgb},0.3)`, animation: "textGlow 4s ease-in-out infinite" }}>
                            FINANCIAL INTELLIGENCE CORE
                          </div>
                          <div style={{ fontSize: 7, color: `rgba(${rc.rgb},0.45)`, letterSpacing: "0.26em", fontFamily: "'Share Tech Mono', monospace", marginTop: 4, display: "flex", alignItems: "center", gap: 8 }}>
                            <div style={{ width: 4, height: 4, borderRadius: "50%", background: "#00ff88", boxShadow: "0 0 8px #00ff88", animation: "pulse-glow 1.2s infinite" }} />
                            REVENUE ENGINE ACTIVE · ALL STREAMS NOMINAL · PROJECTION MODEL LOADED
                          </div>
                        </div>
                      </div>

                      {/* Right side — live clock + data feed status */}
                      <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: 6 }}>
                        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                          {[
                            { l: "MRR", v: `$${m.revenue.mrr}`, c: rc.hex },
                            { l: "ARR", v: `$${(m.revenue.arr||0).toLocaleString()}`, c: "#00ff9d" },
                          ].map(({ l, v, c }) => (
                            <div key={l} style={{ padding: "4px 10px", background: `rgba(${rc.rgb},0.06)`, border: `1px solid rgba(${rc.rgb},0.2)`, borderRadius: 3, clipPath: "polygon(0 0, calc(100% - 5px) 0, 100% 5px, 100% 100%, 0 100%)" }}>
                              <div style={{ fontSize: 6, color: `rgba(${rc.rgb},0.4)`, letterSpacing: "0.2em", fontFamily: "'Share Tech Mono', monospace" }}>{l}</div>
                              <div style={{ fontSize: 14, fontWeight: 700, color: c, fontFamily: "'Orbitron', monospace", textShadow: `0 0 10px ${c}88`, lineHeight: 1 }}>{v}</div>
                            </div>
                          ))}
                        </div>
                        <div style={{ fontSize: 8, color: `rgba(${rc.rgb},0.35)`, fontFamily: "'Share Tech Mono', monospace", letterSpacing: "0.12em" }}>
                          LIVE · {new Date().toISOString().slice(0, 19).replace("T", " ")}
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* ── KPI Strip ── */}
                  <JarvisMetricStrip
                    rgb={rc.rgb} color={rc.hex}
                    metrics={[
                      { label: "MRR", value: `$${m.revenue.mrr}`, sub: `${m.users.paid} active accounts` },
                      { label: "ARR", value: `$${(m.revenue.arr || 0).toLocaleString()}`, sub: "12-month run rate" },
                      { label: "QRR", value: `$${m.revenue.qrr}`, sub: "This quarter" },
                      { label: "Per User", value: `$${m.revenue.plan_price}/mo`, sub: "Plan price" },
                    ]}
                  />

                  {/* ── Main 3-column Jarvis layout ── */}
                  <div style={{ display: "grid", gridTemplateColumns: "auto 1fr auto", gap: 14, alignItems: "start" }}>

                    {/* LEFT — Arc Reactor centerpiece */}
                    <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
                      <ArcReactor
                        color={rc.hex} rgb={rc.rgb}
                        value={`$${m.revenue.mrr}`}
                        label="MRR"
                        size={240}
                      />
                      {/* Sub-data beneath reactor — deep 3D glass */}
                      <div style={{
                        width: 240,
                        background: `linear-gradient(145deg, rgba(0,6,18,0.94) 0%, rgba(0,12,30,0.88) 50%, rgba(0,6,18,0.92) 100%)`,
                        border: `1px solid rgba(${rc.rgb},0.25)`,
                        borderRadius: 4, padding: "14px 16px",
                        clipPath: "polygon(0 0, calc(100% - 8px) 0, 100% 8px, 100% 100%, 0 100%)",
                        boxShadow: `0 12px 40px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.05), inset 0 0 30px rgba(${rc.rgb},0.03)`,
                        backdropFilter: "blur(20px)",
                        position: "relative", overflow: "hidden",
                      }}>
                        {/* Glass top reflection */}
                        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: "45%", background: "linear-gradient(180deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0) 100%)", pointerEvents: "none" }} />
                        <div style={{ position: "absolute", top: -1, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, rgba(${rc.rgb},0.6), transparent)` }} />
                        <div style={{ position: "absolute", top: 0, right: 8, width: 0, height: 0, borderTop: `8px solid rgba(${rc.rgb},0.35)`, borderLeft: "8px solid transparent" }} />
                        {/* Subtle inner radial glow */}
                        <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at 50% 0%, rgba(${rc.rgb},0.06) 0%, transparent 70%)`, pointerEvents: "none" }} />
                        {[
                          { l: "PAID USERS",  v: m.users.paid },
                          { l: "TRIALING",    v: m.users.trialing },
                          { l: "PLAN",        v: `$${m.revenue.plan_price}/mo` },
                        ].map(({ l, v }, idx) => (
                          <div key={l} style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: idx < 2 ? 10 : 0, padding: "7px 10px", background: "rgba(0,0,0,0.15)", borderRadius: 3, border: `1px solid rgba(${rc.rgb},0.07)`, position: "relative" }}>
                            <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 2, background: `rgba(${rc.rgb},0.3)`, borderRadius: "3px 0 0 3px" }} />
                            <span style={{ fontSize: 7, color: `rgba(${rc.rgb},0.4)`, letterSpacing: "0.18em", fontFamily: "'Share Tech Mono', monospace" }}>{l}</span>
                            <span style={{ fontSize: 13, fontWeight: 700, color: rc.hex, fontFamily: "'Orbitron', monospace", textShadow: `0 0 10px rgba(${rc.rgb},0.6)` }}>{v}</span>
                          </div>
                        ))}
                      </div>
                    </div>

                    {/* CENTER — Waveform + timeline table */}
                    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>

                      {/* Waveform panel — deep 3D glass */}
                      <div style={{
                        background: `linear-gradient(145deg, rgba(0,6,18,0.96) 0%, rgba(0,14,32,0.9) 40%, rgba(0,8,22,0.94) 100%)`,
                        border: `1px solid rgba(${rc.rgb},0.28)`,
                        borderRadius: 4, padding: "18px 20px",
                        clipPath: "polygon(0 0, calc(100% - 10px) 0, 100% 10px, 100% 100%, 10px 100%, 0 calc(100% - 10px))",
                        position: "relative", overflow: "hidden",
                        boxShadow: `0 16px 60px rgba(0,0,0,0.6), 0 0 60px rgba(${rc.rgb},0.06), inset 0 1px 0 rgba(255,255,255,0.06), inset 0 0 40px rgba(${rc.rgb},0.03)`,
                        backdropFilter: "blur(20px)",
                      }}>
                        {/* Glass reflection */}
                        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: "30%", background: "linear-gradient(180deg, rgba(255,255,255,0.05) 0%, rgba(255,255,255,0) 100%)", pointerEvents: "none" }} />
                        {/* Inner top glow */}
                        <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at 50% 0%, rgba(${rc.rgb},0.07) 0%, transparent 60%)`, pointerEvents: "none" }} />
                        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, rgba(${rc.rgb},0.8), rgba(${rc.rgb},0.4), transparent)` }} />
                        <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 2, background: `linear-gradient(180deg, ${rc.hex}, rgba(${rc.rgb},0.1))`, boxShadow: `0 0 14px rgba(${rc.rgb},0.4)` }} />
                        <div style={{ position: "absolute", top: 0, right: 10, width: 0, height: 0, borderTop: `10px solid rgba(${rc.rgb},0.4)`, borderLeft: "10px solid transparent" }} />
                        <div style={{ fontSize: 8, color: `rgba(${rc.rgb},0.65)`, letterSpacing: "0.22em", textTransform: "uppercase", fontFamily: "'Share Tech Mono', monospace", marginBottom: 14, display: "flex", alignItems: "center", gap: 8, position: "relative" }}>
                          <div style={{ width: 5, height: 5, background: rc.hex, borderRadius: "50%", boxShadow: `0 0 10px ${rc.hex}` }} />
                          Revenue Signal — 12 Month Arc
                          <div style={{ flex: 1, height: 1, background: `rgba(${rc.rgb},0.15)` }} />
                          <span style={{ color: `rgba(${rc.rgb},0.35)` }}>WAVEFORM</span>
                        </div>
                        <RevenueWaveform data={m.revenue.monthly_breakdown} color={rc.hex} rgb={rc.rgb} />
                        {/* Month labels */}
                        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 8 }}>
                          {(m.revenue.monthly_breakdown || []).map((d, i) => (
                            <div key={i} style={{ fontSize: 6, color: `rgba(${rc.rgb},0.25)`, fontFamily: "'Share Tech Mono', monospace", transform: "rotate(-30deg)", transformOrigin: "center" }}>{d.month?.slice(0, 3)}</div>
                          ))}
                        </div>
                      </div>

                      {/* Bar chart panel — 3D glass */}
                      <div style={{
                        background: `linear-gradient(145deg, rgba(0,6,18,0.96) 0%, rgba(0,12,28,0.9) 40%, rgba(0,6,18,0.94) 100%)`,
                        border: `1px solid rgba(${rc.rgb},0.25)`,
                        borderRadius: 4, padding: "18px 20px",
                        clipPath: "polygon(0 0, calc(100% - 10px) 0, 100% 10px, 100% 100%, 10px 100%, 0 calc(100% - 10px))",
                        position: "relative", overflow: "hidden",
                        boxShadow: `0 16px 60px rgba(0,0,0,0.55), inset 0 1px 0 rgba(255,255,255,0.05), inset 0 0 40px rgba(${rc.rgb},0.025)`,
                        backdropFilter: "blur(20px)",
                      }}>
                        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: "28%", background: "linear-gradient(180deg, rgba(255,255,255,0.04) 0%, rgba(255,255,255,0) 100%)", pointerEvents: "none" }} />
                        <div style={{ position: "absolute", inset: 0, background: `radial-gradient(ellipse at 50% 0%, rgba(${rc.rgb},0.06) 0%, transparent 60%)`, pointerEvents: "none" }} />
                        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, rgba(${rc.rgb},0.6), transparent)` }} />
                        <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 2, background: `linear-gradient(180deg, rgba(${rc.rgb},0.8), transparent)`, boxShadow: `0 0 12px rgba(${rc.rgb},0.3)` }} />
                        <div style={{ position: "absolute", top: 0, right: 10, width: 0, height: 0, borderTop: `10px solid rgba(${rc.rgb},0.35)`, borderLeft: "10px solid transparent" }} />
                        <div style={{ fontSize: 8, color: `rgba(${rc.rgb},0.6)`, letterSpacing: "0.22em", textTransform: "uppercase", fontFamily: "'Share Tech Mono', monospace", marginBottom: 14, display: "flex", alignItems: "center", gap: 8, position: "relative" }}>
                          <div style={{ width: 5, height: 5, background: rc.hex, borderRadius: "50%", boxShadow: `0 0 10px ${rc.hex}` }} />
                          3D Revenue Bars
                          <div style={{ flex: 1, height: 1, background: `rgba(${rc.rgb},0.12)` }} />
                          <span style={{ color: `rgba(${rc.rgb},0.25)`, fontSize: 7 }}>ISOMETRIC</span>
                        </div>
                        <HoloBarChart data={m.revenue.monthly_breakdown} activeColor={rc.hex} />
                      </div>

                      {/* Data table — 3D glass */}
                      <div style={{
                        background: `linear-gradient(145deg, rgba(0,5,14,0.95) 0%, rgba(0,10,24,0.88) 100%)`,
                        border: `1px solid rgba(${rc.rgb},0.18)`,
                        borderRadius: 4, padding: "16px 18px",
                        clipPath: "polygon(0 0, calc(100% - 10px) 0, 100% 10px, 100% 100%, 10px 100%, 0 calc(100% - 10px))",
                        position: "relative",
                        boxShadow: `0 12px 40px rgba(0,0,0,0.5), inset 0 1px 0 rgba(255,255,255,0.04)`,
                        backdropFilter: "blur(16px)",
                      }}>
                        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: "25%", background: "linear-gradient(180deg, rgba(255,255,255,0.035) 0%, rgba(255,255,255,0) 100%)", pointerEvents: "none" }} />
                        <div style={{ position: "absolute", top: 0, left: 0, right: 0, height: 1, background: `linear-gradient(90deg, transparent, rgba(${rc.rgb},0.5), transparent)` }} />
                        <div style={{ position: "absolute", left: 0, top: 0, bottom: 0, width: 2, background: `linear-gradient(180deg, rgba(${rc.rgb},0.5), transparent)` }} />
                        <div style={{ position: "absolute", top: 0, right: 10, width: 0, height: 0, borderTop: `10px solid rgba(${rc.rgb},0.25)`, borderLeft: "10px solid transparent" }} />
                        <div style={{ fontSize: 8, color: `rgba(${rc.rgb},0.5)`, letterSpacing: "0.22em", textTransform: "uppercase", fontFamily: "'Share Tech Mono', monospace", marginBottom: 12, display: "flex", alignItems: "center", gap: 6, position: "relative" }}>
                          <div style={{ width: 4, height: 4, background: rc.hex, borderRadius: "50%", boxShadow: `0 0 8px ${rc.hex}` }} />
                          Transaction Log
                        </div>
                        <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", padding: "4px 0 8px", borderBottom: `1px solid rgba(${rc.rgb},0.08)` }}>
                          {["Month", "New Paid", "Revenue"].map(h => (
                            <div key={h} style={{ fontSize: 7, color: `rgba(${rc.rgb},0.3)`, textTransform: "uppercase", letterSpacing: "0.18em", fontFamily: "'Share Tech Mono', monospace" }}>{h}</div>
                          ))}
                        </div>
                        {[...(m.revenue.monthly_breakdown || [])].reverse().slice(0, 8).map((d, i) => (
                          <div key={i} style={{
                            display: "grid", gridTemplateColumns: "2fr 1fr 1fr",
                            padding: "9px 0",
                            borderBottom: `1px solid rgba(${rc.rgb},0.04)`,
                            background: i === 0 ? `rgba(${rc.rgb},0.03)` : "transparent",
                            transition: "background 0.2s",
                          }}
                            onMouseEnter={e => e.currentTarget.style.background = `rgba(${rc.rgb},0.05)`}
                            onMouseLeave={e => e.currentTarget.style.background = i === 0 ? `rgba(${rc.rgb},0.03)` : "transparent"}
                          >
                            <span style={{ fontSize: 10, color: `rgba(${rc.rgb},0.5)`, fontFamily: "'Share Tech Mono', monospace" }}>{d.month}</span>
                            <span style={{ fontSize: 10, color: `rgba(${rc.rgb},0.35)`, fontFamily: "'Share Tech Mono', monospace" }}>{d.new_paid}</span>
                            <span style={{
                              fontSize: 12, fontWeight: 700,
                              color: d.revenue > 0 ? rc.hex : `rgba(${rc.rgb},0.2)`,
                              fontFamily: "'Orbitron', monospace",
                              textShadow: d.revenue > 0 ? `0 0 8px rgba(${rc.rgb},0.5)` : "none",
                            }}>${d.revenue?.toFixed(2)}</span>
                          </div>
                        ))}
                        <div style={{ marginTop: 12, padding: "8px 12px", background: `rgba(${rc.rgb},0.03)`, border: `1px solid rgba(${rc.rgb},0.08)`, borderRadius: 2, fontSize: 8, color: `rgba(${rc.rgb},0.35)`, letterSpacing: "0.05em", lineHeight: 1.8, fontFamily: "'Share Tech Mono', monospace" }}>
                          ▲ Revenue at ${m.revenue.plan_price}/user/mo · Connect Lemon Squeezy webhook for live sync
                        </div>
                      </div>
                    </div>

                    {/* RIGHT — Intel panel */}
                    <div style={{ width: 220 }}>
                      <RevenueIntelPanel data={m.revenue} rgb={rc.rgb} color={rc.hex} />
                    </div>
                  </div>

                  {/* ── Bottom status bar ── */}
                  <div style={{
                    display: "flex", alignItems: "center", gap: 16,
                    padding: "10px 18px", marginTop: 14,
                    background: `rgba(${rc.rgb},0.03)`,
                    border: `1px solid rgba(${rc.rgb},0.12)`,
                    borderRadius: 3,
                    clipPath: "polygon(0 0, calc(100% - 10px) 0, 100% 10px, 100% 100%, 0 100%)",
                  }}>
                    <div style={{ width: 6, height: 6, borderRadius: "50%", background: rc.hex, boxShadow: `0 0 12px ${rc.hex}`, animation: "pulse-glow 1.5s infinite" }} />
                    <span style={{ fontSize: 8, color: `rgba(${rc.rgb},0.45)`, letterSpacing: "0.18em", fontFamily: "'Share Tech Mono', monospace" }}>
                      FINANCIAL CORE ONLINE · REVENUE ENGINE ACTIVE · PROJECTION MODEL LOADED · DATA STREAM LIVE
                    </span>
                    <div style={{ flex: 1, height: 1, background: `linear-gradient(90deg, rgba(${rc.rgb},0.2), transparent)` }} />
                    <span style={{ fontSize: 8, color: `rgba(${rc.rgb},0.3)`, fontFamily: "'Orbitron', monospace" }}>{new Date().toISOString().slice(0, 19).replace("T", " ")}</span>
                  </div>
                </>
              )}
            </div>
          )}

          {/* ═══════════════ USERS TAB ═══════════════ */}
          {displayTab === "users" && (
            <div>
              <div className="section-heading">User Registry</div>
              <HoloPanel accent="#00e5ff">
                <UsersTable showToast={showToast} onUserClick={setDrawerUser} />
              </HoloPanel>
            </div>
          )}

          {/* ═══════════════ WORKSPACES TAB ═══════════════ */}
          {displayTab === "workspaces" && (
            <div>
              <div className="section-heading">Workspace Network</div>
              {/* Health Map visualization */}
              <HoloPanel accent="#a855f7" style={{ marginBottom: 18 }}>
                <div style={{ fontSize: 8, color: "rgba(168,85,247,0.5)", letterSpacing: "0.22em", fontFamily: "'Share Tech Mono', monospace", marginBottom: 14, display: "flex", alignItems: "center", gap: 8 }}>
                  <div style={{ width: 5, height: 5, background: "#a855f7", borderRadius: "50%", boxShadow: "0 0 10px #a855f7" }} />
                  Network Health Map
                  <div style={{ flex: 1, height: 1, background: "rgba(168,85,247,0.12)" }} />
                  <span style={{ fontSize: 7, color: "rgba(168,85,247,0.25)" }}>NODE TOPOLOGY</span>
                </div>
                <WorkspaceHealthMapWrapper />
              </HoloPanel>
              <HoloPanel accent="#a855f7">
                <WorkspacesTable showToast={showToast} />
              </HoloPanel>
            </div>
          )}

          {/* ═══════════════ FEEDBACK TAB ═══════════════ */}
          {displayTab === "feedback" && (
            <div>
              <div className="section-heading">Incoming Transmissions</div>
              <FeedbackTable />
            </div>
          )}

          </div>{/* end tab transition wrapper */}
        </main>
      </div>
      {/* ── LIVE BROADCAST TICKER ── */}
      <LiveTickerBar m={m} />
    </div>
    </ThemeCtx.Provider>
  );
}
