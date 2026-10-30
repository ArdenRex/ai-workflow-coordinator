// src/components/ConnectWhatsAppButton.jsx
// Sits next to <ConnectGmailButton /> in App.jsx.
//
// Connects the user's WhatsApp Business number via Meta "Embedded Signup".
// Unlike Gmail there is no redirect: Meta opens a popup, and when it finishes
// we receive TWO separate things that can arrive in either order:
//   1. FB.login's callback         -> a one-time `code`
//   2. a window "message" event    -> { waba_id, phone_number_id } (event FINISH,
//                                     or FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING
//                                     when an existing WhatsApp Business app
//                                     number is connected)
// Once we have both, they go to POST /auth/whatsapp/connect, where the backend
// exchanges the code for a token (needs the app secret) and finishes setup.
// See app/whatsapp_connect.py + app/routers/whatsapp_router.py.
//
// The button renders nothing until the server has WhatsApp configured
// (GET /auth/whatsapp/config -> enabled), so it never shows as a dead button.

import { useEffect, useRef, useState } from "react";
import { useAuth } from "../context/AuthContext";

const BASE = (process.env.REACT_APP_API_URL || "").replace(/\/$/, "");
const SESSION_WAIT_MS = 20000;   // how long to wait for the popup's session info after the code arrives
const FB_ORIGINS = ["https://www.facebook.com", "https://web.facebook.com"];

let sdkPromise = null;
function loadFacebookSdk(appId, version) {
  if (sdkPromise) return sdkPromise;
  sdkPromise = new Promise((resolve, reject) => {
    const init = () => {
      window.FB.init({ appId, autoLogAppEvents: true, xfbml: false, version });
      resolve(window.FB);
    };
    if (window.FB) { init(); return; }
    window.fbAsyncInit = init;
    const script = document.createElement("script");
    script.src = "https://connect.facebook.net/en_US/sdk.js";
    script.async = true;
    script.defer = true;
    script.crossOrigin = "anonymous";
    script.onerror = () => { sdkPromise = null; reject(new Error("Could not load Facebook SDK")); };
    document.body.appendChild(script);
  });
  return sdkPromise;
}

export default function ConnectWhatsAppButton() {
  const { token } = useAuth();
  const [config, setConfig]       = useState(null);    // null until loaded; {enabled,...}
  const [connected, setConnected] = useState(false);
  const [number, setNumber]       = useState(null);
  const [busy, setBusy]           = useState(false);
  const [message, setMessage]     = useState(null);    // {kind: "ok"|"error", text}
  const [disconnecting, setDisconnecting] = useState(false);
  const cleanupRef = useRef(null);

  const authHeaders = { Authorization: `Bearer ${token}` };

  useEffect(() => {
    if (!token) return;
    let cancelled = false;
    (async () => {
      try {
        const [cfgRes, stRes] = await Promise.all([
          fetch(`${BASE}/auth/whatsapp/config`, { headers: authHeaders }),
          fetch(`${BASE}/auth/whatsapp/status`, { headers: authHeaders }),
        ]);
        if (cancelled) return;
        if (cfgRes.ok) setConfig(await cfgRes.json());
        if (stRes.ok) {
          const st = await stRes.json();
          setConnected(!!st.connected);
          setNumber(st.display_number || null);
        }
      } catch {
        // Leave config null -> button stays hidden
      }
    })();
    return () => { cancelled = true; };
  }, [token]);

  // Stop listening if the component unmounts mid-flow
  useEffect(() => () => { if (cleanupRef.current) cleanupRef.current(); }, []);

  const completeConnect = async ({ code, waba_id, phone_number_id }) => {
    try {
      const res = await fetch(`${BASE}/auth/whatsapp/connect`, {
        method: "POST",
        headers: { ...authHeaders, "Content-Type": "application/json" },
        body: JSON.stringify({ code, waba_id, phone_number_id: phone_number_id || null }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data.detail || "Could not connect WhatsApp.");
      setConnected(true);
      setNumber(data.display_number || null);
      setMessage({ kind: "ok", text: "WhatsApp connected! New task-like messages will show up here automatically." });
    } catch (err) {
      setMessage({ kind: "error", text: err.message || "Something went wrong. Please try again." });
    } finally {
      setBusy(false);
    }
  };

  const handleConnect = async () => {
    if (!config?.enabled || busy) return;
    setBusy(true);
    setMessage(null);

    let FB;
    try {
      FB = await loadFacebookSdk(config.app_id, config.graph_version);
    } catch {
      setMessage({ kind: "error", text: "Could not load Facebook. Check your connection or ad-blocker and try again." });
      setBusy(false);
      return;
    }

    const flow = { code: null, waba_id: null, phone_number_id: null, finished: false, timer: null };

    const teardown = () => {
      window.removeEventListener("message", onMessage);
      clearTimeout(flow.timer);
      cleanupRef.current = null;
    };
    const fail = (text) => {
      if (flow.finished) return;
      flow.finished = true;
      teardown();
      setMessage({ kind: "error", text });
      setBusy(false);
    };
    const tryFinish = () => {
      if (flow.finished || !flow.code || !flow.waba_id) return;
      flow.finished = true;
      teardown();
      completeConnect({ code: flow.code, waba_id: flow.waba_id, phone_number_id: flow.phone_number_id });
    };

    function onMessage(event) {
      if (!FB_ORIGINS.includes(event.origin)) return;     // only trust Meta's popup
      let payload;
      try { payload = typeof event.data === "string" ? JSON.parse(event.data) : event.data; } catch { return; }
      if (!payload || payload.type !== "WA_EMBEDDED_SIGNUP") return;

      if (payload.event === "FINISH" || payload.event === "FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING") {
        flow.waba_id = payload.data?.waba_id || null;
        flow.phone_number_id = payload.data?.phone_number_id || null;
        tryFinish();
      } else if (payload.event === "CANCEL") {
        fail("Connection cancelled.");
      } else if (payload.event === "ERROR") {
        fail("WhatsApp reported an error. Please try again.");
      }
    }

    window.addEventListener("message", onMessage);
    cleanupRef.current = teardown;

    // FB.login needs a plain (non-async) callback.
    FB.login(
      (response) => {
        const code = response?.authResponse?.code;
        if (!code) { fail("Connection cancelled."); return; }
        flow.code = code;
        // The popup's session info normally arrives right around now; don't wait forever.
        flow.timer = setTimeout(() => fail("WhatsApp did not finish setup in time. Please try again."), SESSION_WAIT_MS);
        tryFinish();
      },
      {
        config_id: config.config_id,
        response_type: "code",
        override_default_response_type: true,
        extras: {
          setup: {},
          // Lets people connect a number that is already on the WhatsApp Business app
          featureType: "whatsapp_business_app_onboarding",
          sessionInfoVersion: "3",
        },
      }
    );
  };

  const handleDisconnect = async () => {
    setDisconnecting(true);
    try {
      await fetch(`${BASE}/auth/whatsapp/disconnect`, { method: "POST", headers: authHeaders });
      setConnected(false);
      setNumber(null);
      setMessage(null);
    } finally {
      setDisconnecting(false);
    }
  };

  // Not configured on the server (or still loading) -> show nothing
  if (!config?.enabled) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 8 }}>
      {connected ? (
        <div style={{
          display: "flex", alignItems: "center", gap: 10,
          padding: "9px 16px", borderRadius: 8,
          background: "rgba(63,174,125,0.1)", border: "1px solid rgba(63,174,125,0.25)",
        }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: "#3fae7d" }}>
            ✅ WhatsApp connected{number ? ` — ${number}` : ""}
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
          disabled={busy}
          style={{
            display: "flex", alignItems: "center", gap: 10,
            padding: "10px 20px", borderRadius: 8, border: "none",
            background: "#25D366", color: "#0b1f14",
            fontSize: 14, fontWeight: 600,
            cursor: busy ? "default" : "pointer", opacity: busy ? 0.7 : 1,
            boxShadow: "0 2px 12px rgba(37,211,102,0.35)",
            transition: "opacity 0.15s, transform 0.15s",
          }}
          onMouseEnter={e => { if (!busy) { e.currentTarget.style.opacity = "0.88"; e.currentTarget.style.transform = "translateY(-1px)"; } }}
          onMouseLeave={e => { e.currentTarget.style.opacity = busy ? "0.7" : "1"; e.currentTarget.style.transform = ""; }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
            <path d="M12.04 2C6.58 2 2.13 6.45 2.13 11.91c0 1.75.46 3.45 1.32 4.95L2.05 22l5.25-1.38a9.9 9.9 0 0 0 4.74 1.21h.01c5.46 0 9.91-4.45 9.91-9.91 0-2.65-1.03-5.14-2.9-7.01A9.82 9.82 0 0 0 12.04 2zm0 18.15h-.01a8.2 8.2 0 0 1-4.19-1.15l-.3-.18-3.12.82.83-3.04-.2-.31a8.2 8.2 0 0 1-1.26-4.38c0-4.54 3.7-8.24 8.25-8.24 2.2 0 4.27.86 5.82 2.42a8.18 8.18 0 0 1 2.41 5.83c0 4.54-3.7 8.23-8.23 8.23zm4.52-6.16c-.25-.12-1.47-.72-1.69-.81-.23-.08-.39-.12-.56.12-.17.25-.64.81-.78.97-.14.17-.29.19-.54.06-.25-.12-1.05-.39-2-1.23-.74-.66-1.23-1.47-1.38-1.72-.14-.25-.02-.38.11-.51.11-.11.25-.29.37-.43.12-.14.17-.25.25-.41.08-.17.04-.31-.02-.43-.06-.12-.56-1.34-.76-1.84-.2-.48-.41-.42-.56-.43h-.48c-.17 0-.43.06-.66.31-.22.25-.86.85-.86 2.07 0 1.22.89 2.4 1.01 2.56.12.17 1.75 2.67 4.23 3.74.59.26 1.05.41 1.41.52.59.19 1.13.16 1.56.1.48-.07 1.47-.6 1.67-1.18.21-.58.21-1.07.14-1.18-.06-.1-.23-.16-.48-.29z"/>
          </svg>
          {busy ? "Connecting…" : "Connect WhatsApp"}
        </button>
      )}

      {message?.kind === "ok" && (
        <div style={{ fontSize: 13, color: "#3fae7d", fontWeight: 600 }}>✅ {message.text}</div>
      )}
      {message?.kind === "error" && (
        <div role="alert" style={{ fontSize: 13, color: "#ff4d5e" }}>⚠️ {message.text}</div>
      )}
    </div>
  );
}
