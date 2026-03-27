// src/components/TaskCard.jsx
import React, { useState } from "react";

const PRIORITY_CONFIG = {
  critical: { label: "critical", bg: "rgba(248,113,113,0.14)", color: "#f87171", dot: "#ef4444", border: "rgba(239,68,68,0.25)"  },
  high:     { label: "high",     bg: "rgba(251,146,60,0.14)",  color: "#fb923c", dot: "#f97316", border: "rgba(249,115,22,0.25)" },
  medium:   { label: "medium",   bg: "rgba(79,142,247,0.14)",  color: "#4f8ef7", dot: "#3b82f6", border: "rgba(59,130,246,0.25)" },
  low:      { label: "low",      bg: "rgba(34,211,168,0.14)",  color: "#22d3a8", dot: "#10b981", border: "rgba(16,185,129,0.25)" },
};

// Matches actual backend status values from models.py
const STATUS_TRANSITIONS = {
  to_do:       [{ value: "in_progress", label: "→ Start"   }, { value: "cancelled", label: "✕ Cancel" }],
  in_progress: [{ value: "completed",   label: "✓ Done"    }, { value: "to_do",     label: "← Back"   }],
  completed:   [{ value: "in_progress", label: "↩ Reopen"  }],
  cancelled:   [{ value: "to_do",       label: "↩ Restore" }],
};

function getInitials(name) {
  if (!name) return "?";
  return name.trim().split(/\s+/).map(w => w[0]).join("").toUpperCase().slice(0, 2);
}

const AVATAR_COLORS = [
  { bg: "rgba(79,142,247,0.2)",  color: "#4f8ef7"  },
  { bg: "rgba(123,92,240,0.2)",  color: "#7b5cf0"  },
  { bg: "rgba(34,211,168,0.2)",  color: "#22d3a8"  },
  { bg: "rgba(245,158,11,0.2)",  color: "#f59e0b"  },
  { bg: "rgba(248,113,113,0.2)", color: "#f87171"  },
];
function avatarColor(name) {
  if (!name) return AVATAR_COLORS[0];
  const code = name.charCodeAt(0) % AVATAR_COLORS.length;
  return AVATAR_COLORS[code];
}

export default function TaskCard({ task, onMove, onDelete, style }) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const priority    = PRIORITY_CONFIG[task.priority] || PRIORITY_CONFIG.medium;
  const transitions = STATUS_TRANSITIONS[task.status] || [];
  const av          = avatarColor(task.assignee);

  async function handleDelete() {
    if (!confirmDelete) {
      setConfirmDelete(true);
      // Auto-cancel confirm after 3 s
      setTimeout(() => setConfirmDelete(false), 3000);
      return;
    }
    setDeleting(true);
    try {
      await onDelete(task.id);
    } finally {
      setDeleting(false);
      setConfirmDelete(false);
    }
  }

  return (
    <div
      style={{
        background: "#161a35",
        border: "1px solid rgba(255,255,255,0.08)",
        borderRadius: 12,
        padding: "14px 16px",
        display: "flex", flexDirection: "column", gap: 11,
        transition: "border-color 0.15s, transform 0.15s, box-shadow 0.15s",
        cursor: "default",
        opacity: deleting ? 0.5 : 1,
        ...style,
      }}
      onMouseEnter={e => {
        e.currentTarget.style.borderColor = "rgba(255,255,255,0.16)";
        e.currentTarget.style.transform   = "translateY(-1px)";
        e.currentTarget.style.boxShadow   = "0 4px 16px rgba(0,0,0,0.3)";
      }}
      onMouseLeave={e => {
        e.currentTarget.style.borderColor = "rgba(255,255,255,0.08)";
        e.currentTarget.style.transform   = "";
        e.currentTarget.style.boxShadow   = "";
      }}
    >
      {/* Top row: priority badge + task ID + delete */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}>
        <span style={{
          display: "inline-flex", alignItems: "center", gap: 5,
          fontSize: 11, fontWeight: 600, letterSpacing: "0.02em",
          padding: "3px 9px", borderRadius: 999,
          background: priority.bg, color: priority.color,
          border: `1px solid ${priority.border}`,
        }}>
          <span style={{ width: 5, height: 5, borderRadius: "50%", background: priority.dot, flexShrink: 0, boxShadow: `0 0 4px ${priority.dot}` }} />
          {priority.label}
        </span>

        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span style={{
            fontSize: 11, color: "var(--color-text-tertiary)",
            fontFamily: "var(--font-mono, monospace)",
            background: "rgba(255,255,255,0.04)",
            padding: "2px 7px", borderRadius: 6,
            border: "1px solid rgba(255,255,255,0.06)",
          }}>
            #{task.id}
          </span>

          {/* Delete button */}
          <button
            onClick={handleDelete}
            disabled={deleting}
            title={confirmDelete ? "Click again to confirm delete" : "Delete task"}
            style={{
              width: 24, height: 24, borderRadius: 6, flexShrink: 0,
              border: confirmDelete
                ? "1px solid rgba(248,113,113,0.5)"
                : "1px solid rgba(255,255,255,0.08)",
              background: confirmDelete ? "rgba(248,113,113,0.15)" : "transparent",
              color: confirmDelete ? "#f87171" : "var(--color-text-tertiary)",
              cursor: deleting ? "not-allowed" : "pointer",
              fontSize: 12, display: "flex", alignItems: "center", justifyContent: "center",
              transition: "all 0.15s",
            }}
            onMouseEnter={e => {
              if (!confirmDelete) {
                e.currentTarget.style.background  = "rgba(248,113,113,0.12)";
                e.currentTarget.style.borderColor = "rgba(248,113,113,0.35)";
                e.currentTarget.style.color       = "#f87171";
              }
            }}
            onMouseLeave={e => {
              if (!confirmDelete) {
                e.currentTarget.style.background  = "transparent";
                e.currentTarget.style.borderColor = "rgba(255,255,255,0.08)";
                e.currentTarget.style.color       = "var(--color-text-tertiary)";
              }
            }}
          >
            {deleting ? "…" : confirmDelete ? "!" : "✕"}
          </button>
        </div>
      </div>

      {/* Confirm delete hint */}
      {confirmDelete && (
        <p style={{
          margin: 0, fontSize: 11, color: "#f87171",
          background: "rgba(248,113,113,0.08)",
          border: "1px solid rgba(248,113,113,0.2)",
          borderRadius: 6, padding: "4px 8px",
        }}>
          Click ✕ again to confirm deletion
        </p>
      )}

      {/* Task description */}
      <p style={{
        margin: 0, fontSize: 13, fontWeight: 500,
        color: "var(--color-text-primary)", lineHeight: 1.55,
      }}>
        {task.task_description || task.title}
      </p>

      {/* Assignee + deadline row */}
      <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
        <div style={{
          width: 26, height: 26, borderRadius: "50%", flexShrink: 0,
          background: av.bg, color: av.color,
          display: "flex", alignItems: "center", justifyContent: "center",
          fontSize: 10, fontWeight: 700,
          border: `1px solid ${av.color}40`,
        }}>
          {getInitials(task.assignee)}
        </div>
        <span style={{ fontSize: 12, color: "var(--color-text-secondary)", flex: 1, minWidth: 0 }}>
          {task.assignee || "Unassigned"}
        </span>
        {task.deadline && (
          <span style={{
            fontSize: 11, color: "var(--color-text-tertiary)",
            background: "rgba(255,255,255,0.05)",
            border: "1px solid rgba(255,255,255,0.08)",
            padding: "2px 8px", borderRadius: 6, whiteSpace: "nowrap",
          }}>
            {task.deadline}
          </span>
        )}
      </div>

      {/* Divider */}
      {transitions.length > 0 && (
        <div style={{ height: 1, background: "rgba(255,255,255,0.06)", margin: "0 -2px" }} />
      )}

      {/* Action buttons */}
      {transitions.length > 0 && (
        <div style={{ display: "flex", gap: 6 }}>
          {transitions.map(t => (
            <button
              key={t.value}
              onClick={() => onMove(task.id, t.value)}
              style={{
                flex: 1, fontSize: 11, fontWeight: 600, padding: "6px 0",
                border: "1px solid rgba(255,255,255,0.09)",
                borderRadius: 8,
                background: "transparent",
                color: "var(--color-text-secondary)",
                cursor: "pointer",
                fontFamily: "var(--font-sans, sans-serif)",
                transition: "background 0.12s, color 0.12s, border-color 0.12s",
              }}
              onMouseEnter={e => {
                e.currentTarget.style.background    = "rgba(79,142,247,0.12)";
                e.currentTarget.style.color         = "#4f8ef7";
                e.currentTarget.style.borderColor   = "rgba(79,142,247,0.3)";
              }}
              onMouseLeave={e => {
                e.currentTarget.style.background    = "transparent";
                e.currentTarget.style.color         = "var(--color-text-secondary)";
                e.currentTarget.style.borderColor   = "rgba(255,255,255,0.09)";
              }}
            >
              {t.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
