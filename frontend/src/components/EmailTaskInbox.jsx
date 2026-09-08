// src/components/EmailTaskInbox.jsx
// Drop next to <AddToSlackButton /> in the header area of App.jsx.
//
// Unlike Slack, email integration has no OAuth "connect" step — any email
// forwarded/sent from the user's own registered account email to this
// address is picked up automatically (see app/email_bot.py on the backend).
// This component is purely informational: it shows the address and lets
// the user copy it.

import { useState } from "react";
import { useAuth } from "../context/AuthContext";

// Set this in your frontend .env / Vercel project settings, e.g.:
//   REACT_APP_TASK_EMAIL=tasks@tasks.yourdomain.com
const TASK_EMAIL = process.env.REACT_APP_TASK_EMAIL || "";

export default function EmailTaskInbox() {
  const [copied, setCopied] = useState(false);
  const { isArchitect } = useAuth();

  // Not configured yet. Regular team members can't act on this, so they see
  // nothing — same as before. Architects are the ones who'd actually set the
  // env vars / SendGrid domain, so they get a short "how to turn this on"
  // card instead of the feature just silently not existing.
  if (!TASK_EMAIL) {
    if (!isArchitect) return null;
    return (
      <div style={{
        display: "flex", flexDirection: "column", gap: 6,
        padding: "10px 14px", borderRadius: 10,
        background: "rgba(255,255,255,0.03)",
        border: "1px dashed rgba(255,255,255,0.14)",
        maxWidth: 340,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 13, fontWeight: 600, color: "var(--color-text-secondary)" }}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
            <path d="M3 5h18a1 1 0 011 1v12a1 1 0 01-1 1H3a1 1 0 01-1-1V6a1 1 0 011-1z" stroke="currentColor" strokeWidth="1.6"/>
            <path d="M2.5 6.5l9.5 7 9.5-7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
          </svg>
          Email — Not Configured
        </div>
        <div style={{ fontSize: 11.5, color: "var(--color-text-tertiary)", lineHeight: 1.5 }}>
          Let your team create tasks by emailing a shared address, the same way Slack messages do. Needs a domain you control:
        </div>
        <ol style={{ margin: 0, paddingLeft: 16, fontSize: 11.5, color: "var(--color-text-tertiary)", lineHeight: 1.6 }}>
          <li>Point a subdomain's MX record at SendGrid Inbound Parse</li>
          <li>Set <code style={{ fontSize: 10.5 }}>EMAIL_INBOUND_SECRET</code> on the backend</li>
          <li>Set <code style={{ fontSize: 10.5 }}>REACT_APP_TASK_EMAIL</code> on the frontend</li>
        </ol>
      </div>
    );
  }

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(TASK_EMAIL);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard API unavailable — fail silently, address is still visible
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 8 }}>

      <button
        onClick={handleCopy}
        title="Click to copy"
        style={{
          display:     "flex",
          alignItems:  "center",
          gap:         10,
          padding:     "10px 20px",
          borderRadius: 8,
          border:      "none",
          background:  "#c81f30",
          color:       "#f5f0eb",
          fontSize:    14,
          fontWeight:  600,
          cursor:      "pointer",
          boxShadow:   "0 2px 12px rgba(37,99,235,0.4)",
          transition:  "opacity 0.15s, transform 0.15s",
        }}
        onMouseEnter={e => { e.currentTarget.style.opacity = "0.88"; e.currentTarget.style.transform = "translateY(-1px)"; }}
        onMouseLeave={e => { e.currentTarget.style.opacity = "1";    e.currentTarget.style.transform = ""; }}
      >
        {/* Simple envelope icon */}
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">
          <path d="M3 5h18a1 1 0 011 1v12a1 1 0 01-1 1H3a1 1 0 01-1-1V6a1 1 0 011-1z" stroke="#f5f0eb" strokeWidth="1.6"/>
          <path d="M2.5 6.5l9.5 7 9.5-7" stroke="#f5f0eb" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
        </svg>
        {copied ? "Copied!" : TASK_EMAIL}
      </button>

      <div style={{ fontSize: 12, color: "var(--color-text-tertiary)", maxWidth: 320 }}>
        Email or forward anything to this address from your account email to create a task automatically.
      </div>

    </div>
  );
}
