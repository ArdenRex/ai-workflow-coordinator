// src/components/KanbanColumn.jsx
import React from "react";
import TaskCard from "./TaskCard";

const COLUMN_CONFIG = {
  to_do:       { accent: "#f59e0b", dotShadow: "0 0 6px rgba(245,158,11,0.6)"  },
  in_progress: { accent: "#4f8ef7", dotShadow: "0 0 6px rgba(79,142,247,0.6)" },
  completed:   { accent: "#22d3a8", dotShadow: "0 0 6px rgba(34,211,168,0.6)" },
  cancelled:   { accent: "#6b7280", dotShadow: "0 0 6px rgba(107,114,128,0.6)" },
};

export default function KanbanColumn({ status, label, tasks, onMove, onDelete, timezone }) {
  const config = COLUMN_CONFIG[status] || { accent: "#4f8ef7", dotShadow: "none" };

  return (
    <div style={{ display: "flex", flexDirection: "column", minWidth: 0 }}>
      {/* Column header */}
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "0 4px 14px" }}>
        <span style={{
          width: 8, height: 8, borderRadius: "50%", flexShrink: 0,
          background: config.accent, boxShadow: config.dotShadow,
        }} aria-hidden="true" />
        <span style={{ fontSize: 13, fontWeight: 600, color: "var(--color-text-primary)" }}>
          {label || status}
        </span>
        <span style={{
          marginLeft: "auto",
          minWidth: 22, height: 22, padding: "0 6px", borderRadius: 999,
          background: "rgba(255,255,255,0.07)",
          border: "1px solid rgba(255,255,255,0.09)",
          fontSize: 11, fontWeight: 600, color: "var(--color-text-secondary)",
          display: "flex", alignItems: "center", justifyContent: "center",
        }} aria-label={`${tasks.length} tasks`}>
          {tasks.length}
        </span>
      </div>

      {/* Cards container */}
      <div style={{
        display: "flex", flexDirection: "column", gap: 10,
        background: "rgba(255,255,255,0.025)",
        border: "1px solid rgba(255,255,255,0.07)",
        borderRadius: 16,
        padding: tasks.length ? 10 : "32px 10px",
        minHeight: 140,
        borderTop: `2px solid ${config.accent}33`,
      }}>
        {tasks.length === 0 ? (
          <p style={{
            margin: 0, textAlign: "center",
            fontSize: 12, color: "var(--color-text-tertiary)",
          }}>
            No tasks
          </p>
        ) : (
          tasks.map(task => (
            <TaskCard
              key={task.id}
              task={task}
              onMove={onMove}
              onDelete={onDelete}
              timezone={timezone}
            />
          ))
        )}
      </div>
    </div>
  );
}
