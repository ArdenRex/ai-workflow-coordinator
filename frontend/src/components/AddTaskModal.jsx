// src/components/AddTaskModal.jsx — redesigned dark theme (all logic preserved)
import React, { useState, useRef, useEffect } from "react";

const EXAMPLES = [
  "Hey Sarah, can you finish the API docs by Thursday? It's high priority.",
  "Marcus — please review and merge the auth PR before EOD.",
  "URGENT: production DB is throwing errors, needs immediate attention from the devops team.",
];

export default function AddTaskModal({ onClose, onAdd }) {
  const [message, setMessage]   = useState("");
  const [loading, setLoading]   = useState(false);
  const [error, setError]       = useState(null);
  const [result, setResult]     = useState(null);
  const textareaRef = useRef(null);

  useEffect(() => { textareaRef.current?.focus(); }, []);

  async function handleSubmit() {
    if (!message.trim() || loading) return;
    setLoading(true);
    setError(null);
    try {
      const res = await onAdd(message.trim());
      setResult(res);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  function handleKeyDown(e) {
    if (e.key === "Escape") onClose();
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleSubmit();
  }

  const PRIORITY_COLORS = {
    critical: "#f87171", high: "#fb923c", medium: "#4f8ef7", low: "#22d3a8"
  };

  return (
    <div
      style={{
        position: "fixed", inset: 0,
        background: "rgba(5,6,20,0.78)",
        backdropFilter: "blur(6px)", WebkitBackdropFilter: "blur(6px)",
        display: "flex", alignItems: "center", justifyContent: "center",
        padding: 24, zIndex: 100,
      }}
      onClick={e => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div style={{
        width: "100%", maxWidth: 540,
        background: "#14183a",
        border: "1px solid rgba(255,255,255,0.14)",
        borderRadius: 20, padding: "28px",
        boxShadow: "0 24px 80px rgba(0,0,0,0.65), 0 0 0 1px rgba(79,142,247,0.12)",
        display: "flex", flexDirection: "column", gap: 18,
      }}>
        {/* Header */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 16, fontWeight: 700, color: "var(--color-text-primary)", letterSpacing: "-0.02em" }}>
              Extract Task from Message
            </h2>
            <p style={{ margin: "4px 0 0", fontSize: 12, color: "var(--color-text-secondary)" }}>
              Paste a Slack message — AI will extract the task details
            </p>
          </div>
          <button onClick={onClose} style={{
            width: 30, height: 30, borderRadius: 8,
            border: "1px solid rgba(255,255,255,0.1)",
            background: "transparent", cursor: "pointer",
            color: "var(--color-text-tertiary)", fontSize: 16, lineHeight: 1,
            display: "flex", alignItems: "center", justifyContent: "center",
            transition: "all 0.15s",
          }}
            onMouseEnter={e => { e.currentTarget.style.background = "rgba(255,255,255,0.07)"; e.currentTarget.style.color = "var(--color-text-primary)"; }}
            onMouseLeave={e => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--color-text-tertiary)"; }}
          >×</button>
        </div>

        {!result ? (
          <>
            {/* Example pills */}
            <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
              <p style={{ margin: 0, fontSize: 10, fontWeight: 600, color: "var(--color-text-tertiary)", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                Try an example
              </p>
              {EXAMPLES.map((ex, i) => (
                <button key={i} onClick={() => setMessage(ex)} style={{
                  textAlign: "left", fontSize: 12, lineHeight: 1.5,
                  color: "var(--color-text-secondary)",
                  background: "rgba(255,255,255,0.03)",
                  border: "1px solid rgba(255,255,255,0.08)",
                  borderRadius: 8, padding: "8px 12px", cursor: "pointer",
                  fontFamily: "var(--font-sans, sans-serif)",
                  transition: "all 0.15s",
                }}
                  onMouseEnter={e => { e.currentTarget.style.background = "rgba(79,142,247,0.08)"; e.currentTarget.style.borderColor = "rgba(79,142,247,0.3)"; e.currentTarget.style.color = "var(--color-text-primary)"; }}
                  onMouseLeave={e => { e.currentTarget.style.background = "rgba(255,255,255,0.03)"; e.currentTarget.style.borderColor = "rgba(255,255,255,0.08)"; e.currentTarget.style.color = "var(--color-text-secondary)"; }}
                >{ex}</button>
              ))}
            </div>

            {/* Divider */}
            <div style={{ height: 1, background: "rgba(255,255,255,0.07)" }} />

            {/* Textarea */}
            <textarea
              ref={textareaRef}
              value={message}
              onChange={e => setMessage(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Paste a Slack message or write a task description…"
              rows={4}
              style={{
                width: "100%", resize: "vertical",
                fontSize: 13, padding: "12px 14px", lineHeight: 1.6,
                border: "1px solid rgba(255,255,255,0.1)",
                borderRadius: 10,
                background: "rgba(255,255,255,0.04)",
                color: "var(--color-text-primary)",
                fontFamily: "var(--font-sans, sans-serif)",
                outline: "none", boxSizing: "border-box",
                transition: "border-color 0.15s, box-shadow 0.15s",
              }}
              onFocus={e => { e.target.style.borderColor = "rgba(79,142,247,0.5)"; e.target.style.boxShadow = "0 0 0 3px rgba(79,142,247,0.1)"; }}
              onBlur={e => { e.target.style.borderColor = "rgba(255,255,255,0.1)"; e.target.style.boxShadow = "none"; }}
            />

            {error && (
              <p style={{ margin: 0, fontSize: 12, color: "#f87171", padding: "8px 12px", background: "rgba(248,113,113,0.08)", borderRadius: 8, border: "1px solid rgba(248,113,113,0.2)" }}>
                ⚠ {error}
              </p>
            )}

            {/* Actions */}
            <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
              <button onClick={onClose} style={{
                padding: "9px 18px", fontSize: 13, fontWeight: 600, cursor: "pointer",
                border: "1px solid rgba(255,255,255,0.1)",
                borderRadius: 999, background: "transparent",
                color: "var(--color-text-secondary)",
                fontFamily: "var(--font-sans, sans-serif)",
                transition: "all 0.15s",
              }}
                onMouseEnter={e => { e.currentTarget.style.background = "rgba(255,255,255,0.06)"; e.currentTarget.style.color = "var(--color-text-primary)"; }}
                onMouseLeave={e => { e.currentTarget.style.background = "transparent"; e.currentTarget.style.color = "var(--color-text-secondary)"; }}
              >Cancel</button>
              <button onClick={handleSubmit} disabled={!message.trim() || loading} style={{
                padding: "9px 22px", fontSize: 13, fontWeight: 600, cursor: message.trim() && !loading ? "pointer" : "not-allowed",
                border: "none", borderRadius: 999,
                background: message.trim() && !loading ? "linear-gradient(135deg,#4f8ef7,#7b5cf0)" : "rgba(255,255,255,0.07)",
                color: message.trim() && !loading ? "#fff" : "var(--color-text-tertiary)",
                fontFamily: "var(--font-sans, sans-serif)",
                boxShadow: message.trim() && !loading ? "0 0 20px rgba(79,142,247,0.35)" : "none",
                transition: "all 0.15s",
                display: "flex", alignItems: "center", gap: 8,
              }}>
                {loading ? (
                  <>
                    <span style={{ width: 14, height: 14, border: "2px solid rgba(255,255,255,0.25)", borderTopColor: "#fff", borderRadius: "50%", animation: "spin 0.7s linear infinite" }} />
                    Extracting…
                  </>
                ) : "Extract & Save"}
              </button>
            </div>
          </>
        ) : (
          /* Success state */
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div style={{
              padding: "12px 16px", borderRadius: 10, fontSize: 13, fontWeight: 600,
              background: "rgba(34,211,168,0.1)", border: "1px solid rgba(34,211,168,0.25)",
              color: "#22d3a8", display: "flex", alignItems: "center", gap: 8,
            }}>
              <span>✓</span> Task #{result.task.id} created successfully
            </div>

            <div style={{ background: "rgba(255,255,255,0.03)", border: "1px solid rgba(255,255,255,0.07)", borderRadius: 12, padding: "16px 18px", display: "flex", flexDirection: "column", gap: 12 }}>
              {[
                ["Task",     result.extracted.task],
                ["Assignee", result.extracted.assignee || "Unassigned"],
                ["Deadline", result.extracted.deadline || "—"],
                ["Priority", result.extracted.priority],
              ].map(([label, val]) => (
                <div key={label} style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, fontSize: 13 }}>
                  <span style={{ color: "var(--color-text-tertiary)", flexShrink: 0, fontSize: 12, fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.04em", paddingTop: 1 }}>{label}</span>
                  <span style={{
                    fontWeight: 600, textAlign: "right", maxWidth: "70%",
                    color: label === "Priority" ? (PRIORITY_COLORS[val] || "#4f8ef7") : "var(--color-text-primary)",
                  }}>{val}</span>
                </div>
              ))}
            </div>

            <button onClick={onClose} style={{
              padding: "10px", fontSize: 13, fontWeight: 600, cursor: "pointer",
              border: "none", borderRadius: 999,
              background: "linear-gradient(135deg,#4f8ef7,#7b5cf0)",
              color: "#fff", fontFamily: "var(--font-sans, sans-serif)",
              boxShadow: "0 0 16px rgba(79,142,247,0.35)",
            }}>Done</button>
          </div>
        )}
      </div>
    </div>
  );
}
