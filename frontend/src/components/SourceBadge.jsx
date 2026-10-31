// src/components/SourceBadge.jsx
// Small pill showing where a task came from (`compact` = the smaller size used in
// dense lists/tables). The backend sends
// task.source = "slack" | "gmail" | "whatsapp" | null (see Task.source in
// app/models.py). Renders nothing for tasks with no source (manual, forwarded
// email, Teams, public API), so unknown values are safely ignored too.

const SOURCES = {
  slack: {
    label: "Slack", color: "#e8478b", bg: "rgba(224,30,90,0.14)", border: "rgba(224,30,90,0.30)",
    // hash sign
    icon: (
      <path d="M9 3 7.5 21M16.5 3 15 21M4 9h17M3 15h17" fill="none" stroke="currentColor"
            strokeWidth="2.2" strokeLinecap="round" />
    ),
  },
  gmail: {
    label: "Gmail", color: "#f2766b", bg: "rgba(234,67,53,0.14)", border: "rgba(234,67,53,0.30)",
    // envelope
    icon: (
      <>
        <rect x="3" y="5" width="18" height="14" rx="2.5" fill="none" stroke="currentColor" strokeWidth="2.1" />
        <path d="m4 7.5 8 6 8-6" fill="none" stroke="currentColor" strokeWidth="2.1"
              strokeLinecap="round" strokeLinejoin="round" />
      </>
    ),
  },
  whatsapp: {
    label: "WhatsApp", color: "#25D366", bg: "rgba(37,211,102,0.14)", border: "rgba(37,211,102,0.30)",
    // chat bubble
    icon: (
      <path d="M12 3a9 9 0 0 0-7.7 13.6L3 21l4.5-1.2A9 9 0 1 0 12 3z" fill="none" stroke="currentColor"
            strokeWidth="2.1" strokeLinejoin="round" />
    ),
  },
};

export default function SourceBadge({ source, compact = false }) {
  // Own-property check so inherited keys ("constructor", "__proto__"…) never match
  const cfg = Object.prototype.hasOwnProperty.call(SOURCES, source) ? SOURCES[source] : null;
  if (!cfg) return null;
  return (
    <span
      data-testid="source-badge"
      title={`Created from ${cfg.label}`}
      style={{
        display: "inline-flex", alignItems: "center", gap: 5,
        fontSize: compact ? 10 : 11, fontWeight: 600, letterSpacing: "0.02em",
        padding: compact ? "1px 7px" : "3px 9px", borderRadius: 999, whiteSpace: "nowrap",
        background: cfg.bg, color: cfg.color, border: `1px solid ${cfg.border}`,
      }}
    >
      <svg width={compact ? 10 : 11} height={compact ? 10 : 11} viewBox="0 0 24 24" aria-hidden="true" style={{ flexShrink: 0 }}>
        {cfg.icon}
      </svg>
      {cfg.label}
    </span>
  );
}
