// src/components/AddToSlackButton.jsx
// Drop this anywhere in your dashboard — e.g. in the header area of App.jsx

import { useEffect, useState } from "react";

const BASE = (process.env.REACT_APP_API_URL || "").replace(/\/$/, "");

export default function AddToSlackButton() {
  const [status, setStatus] = useState(null); // null | "success" | "cancelled" | "error"

  // After Slack OAuth redirect, read ?slack=success/cancelled/error from URL
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const slack  = params.get("slack");
    if (slack) {
      setStatus(slack);
      // Remove the query param from the URL without reloading
      window.history.replaceState({}, "", window.location.pathname);
    }
  }, []);

  const handleClick = () => {
    // Sends user to Railway backend → which redirects to Slack OAuth page
    window.location.href = `${BASE}/auth/install`;
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 8 }}>

      <button
        onClick={handleClick}
        style={{
          display:     "flex",
          alignItems:  "center",
          gap:         10,
          padding:     "10px 20px",
          borderRadius: 8,
          border:      "none",
          background:  "#4A154B",
          color:       "#fff",
          fontSize:    14,
          fontWeight:  600,
          cursor:      "pointer",
          boxShadow:   "0 2px 12px rgba(74,21,75,0.4)",
          transition:  "opacity 0.15s, transform 0.15s",
        }}
        onMouseEnter={e => { e.currentTarget.style.opacity = "0.88"; e.currentTarget.style.transform = "translateY(-1px)"; }}
        onMouseLeave={e => { e.currentTarget.style.opacity = "1";    e.currentTarget.style.transform = ""; }}
      >
        {/* Official Slack logo */}
        <svg width="18" height="18" viewBox="0 0 122.8 122.8" xmlns="http://www.w3.org/2000/svg">
          <path d="M25.8 77.6c0 7.1-5.8 12.9-12.9 12.9S0 84.7 0 77.6s5.8-12.9 12.9-12.9h12.9v12.9zm6.5 0c0-7.1 5.8-12.9 12.9-12.9s12.9 5.8 12.9 12.9v32.3c0 7.1-5.8 12.9-12.9 12.9s-12.9-5.8-12.9-12.9V77.6z" fill="#E01E5A"/>
          <path d="M45.2 25.8c-7.1 0-12.9-5.8-12.9-12.9S38.1 0 45.2 0s12.9 5.8 12.9 12.9v12.9H45.2zm0 6.5c7.1 0 12.9 5.8 12.9 12.9s-5.8 12.9-12.9 12.9H12.9C5.8 58.1 0 52.3 0 45.2s5.8-12.9 12.9-12.9h32.3z" fill="#36C5F0"/>
          <path d="M97 45.2c0-7.1 5.8-12.9 12.9-12.9s12.9 5.8 12.9 12.9-5.8 12.9-12.9 12.9H97V45.2zm-6.5 0c0 7.1-5.8 12.9-12.9 12.9s-12.9-5.8-12.9-12.9V12.9C64.7 5.8 70.5 0 77.6 0s12.9 5.8 12.9 12.9v32.3z" fill="#2EB67D"/>
          <path d="M77.6 97c7.1 0 12.9 5.8 12.9 12.9s-5.8 12.9-12.9 12.9-12.9-5.8-12.9-12.9V97h12.9zm0-6.5c-7.1 0-12.9-5.8-12.9-12.9s5.8-12.9 12.9-12.9h32.3c7.1 0 12.9 5.8 12.9 12.9s-5.8 12.9-12.9 12.9H77.6z" fill="#ECB22E"/>
        </svg>
        Add to Slack
      </button>

      {status === "success" && (
        <div style={{ fontSize: 13, color: "#22d3a8", fontWeight: 600 }}>
          ✅ Slack connected! The bot is now installed in your workspace.
        </div>
      )}
      {status === "cancelled" && (
        <div style={{ fontSize: 13, color: "#f87171" }}>
          ❌ Installation cancelled.
        </div>
      )}
      {status === "error" && (
        <div style={{ fontSize: 13, color: "#f87171" }}>
          ⚠️ Something went wrong. Please try again.
        </div>
      )}

    </div>
  );
}
