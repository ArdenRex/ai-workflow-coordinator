// src/components/ConnectGmailButton.jsx
// Drop next to <AddToSlackButton /> in the header area of App.jsx.
//
// Unlike EmailTaskInbox (forward-to-a-shared-address), this connects the
// user's OWN Gmail account via OAuth — the backend then polls that inbox
// and turns matching messages into tasks automatically, the same way
// Slack messages do. See app/gmail_bot.py + app/routers/gmail_router.py.

import { useEffect, useState } from "react";
import { useAuth } from "../context/AuthContext";

const BASE = (process.env.REACT_APP_API_URL || "").replace(/\/$/, "");

export default function ConnectGmailButton() {
  const { token } = useAuth();
  const [status, setStatus]     = useState(null);   // null | "success" | "cancelled" | "error"
  const [connected, setConnected] = useState(null);  // null = unknown/loading, then bool
  const [gmailAddress, setGmailAddress] = useState(null);
  const [disconnecting, setDisconnecting] = useState(false);

  // After Google OAuth redirect, read ?gmail=success/cancelled/error from URL
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const gmail  = params.get("gmail");
    if (gmail) {
      setStatus(gmail);
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, []);

  const loadStatus = async () => {
    if (!token) return;
    try {
      const res = await fetch(`${BASE}/auth/gmail/status`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (!res.ok) return;
      const data = await res.json();
      setConnected(!!data.connected);
      setGmailAddress(data.email || null);
    } catch {
      // Leave connected as null (unknown) — button still works either way
    }
  };

  useEffect(() => { loadStatus(); }, [token, status]);

  const handleConnect = () => {
    if (!token) return;
    // Full-page redirect to Google's consent screen — the JWT has to travel
    // as a query param since a plain navigation can't carry an Authorization
    // header; the backend decodes it the same way as normal requests.
    window.location.href = `${BASE}/auth/gmail/install?token=${encodeURIComponent(token)}`;
  };

  const handleDisconnect = async () => {
    setDisconnecting(true);
    try {
      await fetch(`${BASE}/auth/gmail/disconnect`, {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
      });
      setConnected(false);
      setGmailAddress(null);
    } finally {
      setDisconnecting(false);
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 8 }}>

      {connected ? (
        <div style={{
          display: "flex", alignItems: "center", gap: 10,
          padding: "9px 16px", borderRadius: 8,
          background: "rgba(63,174,125,0.1)", border: "1px solid rgba(63,174,125,0.25)",
        }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: "#3fae7d" }}>
            ✅ Gmail connected{gmailAddress ? ` — ${gmailAddress}` : ""}
          </span>
          <button
            onClick={handleDisconnect}
            disabled={disconnecting}
            style={{
              border: "none", background: "transparent", color: "#ff4d5e",
              fontSize: 12, fontWeight: 600, cursor: disconnecting ? "default" : "pointer",
              opacity: disconnecting ? 0.5 : 1, padding: 0,
            }}
          >
            {disconnecting ? "…" : "Disconnect"}
          </button>
        </div>
      ) : (
        <button
          onClick={handleConnect}
          style={{
            display:     "flex",
            alignItems:  "center",
            gap:         10,
            padding:     "10px 20px",
            borderRadius: 8,
            border:      "none",
            background:  "#4285F4",
            color:       "#f5f0eb",
            fontSize:    14,
            fontWeight:  600,
            cursor:      "pointer",
            boxShadow:   "0 2px 12px rgba(66,133,244,0.4)",
            transition:  "opacity 0.15s, transform 0.15s",
          }}
          onMouseEnter={e => { e.currentTarget.style.opacity = "0.88"; e.currentTarget.style.transform = "translateY(-1px)"; }}
          onMouseLeave={e => { e.currentTarget.style.opacity = "1";    e.currentTarget.style.transform = ""; }}
        >
          {/* Simple Google "G" mark */}
          <svg width="16" height="16" viewBox="0 0 48 48" xmlns="http://www.w3.org/2000/svg">
            <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3c-1.6 4.7-6.1 8-11.3 8-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.1 8 3l5.7-5.7C34.6 6 29.6 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.7-.4-3.5z"/>
            <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.4 19 12.5 24 12.5c3.1 0 5.8 1.1 8 3l5.7-5.7C34.6 6 29.6 4 24 4 16.3 4 9.7 8.3 6.3 14.7z"/>
            <path fill="#4CAF50" d="M24 44c5.5 0 10.4-1.9 14.3-5.1l-6.6-5.6C29.7 34.8 27 35.5 24 35.5c-5.2 0-9.6-3.3-11.2-7.9l-6.6 5.1C9.6 39.7 16.2 44 24 44z"/>
            <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.3-2.2 4.2-4.1 5.6l6.6 5.6C39.9 37.4 44 31.5 44 24c0-1.3-.1-2.7-.4-3.5z"/>
          </svg>
          Connect Gmail
        </button>
      )}

      {status === "success" && !connected && (
        <div style={{ fontSize: 13, color: "#3fae7d", fontWeight: 600 }}>
          ✅ Gmail connected! New task-like emails will show up here automatically.
        </div>
      )}
      {status === "cancelled" && (
        <div style={{ fontSize: 13, color: "#ff4d5e" }}>
          ❌ Connection cancelled.
        </div>
      )}
      {status === "error" && (
        <div style={{ fontSize: 13, color: "#ff4d5e" }}>
          ⚠️ Something went wrong. Please try again.
        </div>
      )}

    </div>
  );
}
