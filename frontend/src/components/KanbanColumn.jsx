// src/components/KanbanColumn.jsx
//
// Step 2 (dashboard 3D/motion pass): columns now enter as part of the
// shared stagger sequence (variants={fadeUpItem}, driven by the parent's
// staggerContainer) instead of popping in statically, and pick up a
// gentle tilt-lite hover — same useTilt3D hook as TaskCard/TiltPCard but
// tuned down (lower max angle, no glare) so the *column* reads as a
// shallow tray sitting behind its cards rather than competing with them.
import React from "react";
import { motion, AnimatePresence } from "framer-motion";
import TaskCard from "./TaskCard";
import useTilt3D from "../motion/useTilt3D";
import { fadeUpItem } from "../motion/variants";

const COLUMN_CONFIG = {
  to_do:       { accent: "#d99a3f", dotShadow: "0 0 6px rgba(217,154,63,0.6)"  },
  in_progress: { accent: "#ff6a52", dotShadow: "0 0 6px rgba(255,106,82,0.6)" },
  completed:   { accent: "#3fae7d", dotShadow: "0 0 6px rgba(63,174,125,0.6)" },
  cancelled:   { accent: "#9a908a", dotShadow: "0 0 6px rgba(107,114,128,0.6)" },
};

export default function KanbanColumn({ status, label, tasks, onMove, onDelete, timezone }) {
  const config = COLUMN_CONFIG[status] || { accent: "#ff6a52", dotShadow: "none" };
  const { ref, style: tiltStyle, onPointerMove, onPointerLeave } =
    useTilt3D({ max: 2.5, scale: 1.006, glare: false });

  return (
    <motion.div
      variants={fadeUpItem}
      ref={ref}
      onPointerMove={onPointerMove}
      onPointerLeave={onPointerLeave}
      style={{ display: "flex", flexDirection: "column", minWidth: 0, ...tiltStyle }}
    >
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
        boxShadow: `0 12px 30px -18px ${config.accent}55`,
        transition: "box-shadow 0.25s cubic-bezier(0.16,1,0.3,1)",
      }}>
        {tasks.length === 0 ? (
          <p style={{
            margin: 0, textAlign: "center",
            fontSize: 12, color: "var(--color-text-tertiary)",
          }}>
            No tasks
          </p>
        ) : (
          <AnimatePresence mode="popLayout">
            {tasks.map(task => (
              <TaskCard
                key={task.id}
                task={task}
                onMove={onMove}
                onDelete={onDelete}
                timezone={timezone}
              />
            ))}
          </AnimatePresence>
        )}
      </div>
    </motion.div>
  );
}
