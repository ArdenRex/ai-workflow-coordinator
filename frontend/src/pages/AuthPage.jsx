// src/pages/AuthPage.jsx
// Login + Register page — matches the existing dark dashboard aesthetic.
// Uses useAuth() hook for all auth actions.

import { useState, useCallback } from "react";
import { useAuth } from "../context/AuthContext";

// ── Styles ────────────────────────────────────────────────────────────────────
const STYLES = `
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@700;800&display=swap');

  .auth-root {
    min-height: 100vh;
    background: #0d0f1e;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: 'Inter', system-ui, sans-serif;
    padding: 24px;
    position: relative;
    overflow: hidden;
  }

  /* Background glow orbs */
  .auth-root::before {
    content: '';
    position: fixed;
    top: -200px; left: -200px;
    width: 600px; height: 600px;
    background: radial-gradient(circle, rgba(79,142,247,0.08) 0%, transparent 70%);
    pointer-events: none;
  }
  .auth-root::after {
    content: '';
    position: fixed;
    bottom: -200px; right: -200px;
    width: 600px; height: 600px;
    background: radial-gradient(circle, rgba(123,92,240,0.07) 0%, transparent 70%);
    pointer-events: none;
  }

  .auth-card {
    width: 100%;
    max-width: 440px;
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 24px;
    padding: 40px;
    backdrop-filter: blur(20px);
    box-shadow: 0 24px 64px rgba(0,0,0,0.4);
    position: relative;
    z-index: 1;
    animation: cardIn 0.5s cubic-bezier(0.16,1,0.3,1) both;
  }

  @keyframes cardIn {
    from { opacity: 0; transform: translateY(24px) scale(0.97); }
    to   { opacity: 1; transform: translateY(0) scale(1); }
  }

  .auth-logo {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 32px;
  }

  .auth-logo-icon {
    width: 36px; height: 36px;
    border-radius: 10px;
    background: linear-gradient(135deg, #4f8ef7 0%, #7b5cf0 100%);
    display: flex; align-items: center; justify-content: center;
    font-size: 14px; font-weight: 700; color: #fff;
    box-shadow: 0 0 20px rgba(79,142,247,0.4);
    flex-shrink: 0;
  }

  .auth-logo-text {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 16px; font-weight: 800;
    color: #e8eaf6;
    letter-spacing: -0.02em;
  }

  .auth-logo-sub {
    font-size: 11px;
    color: #555a80;
    margin-top: 1px;
  }

  .auth-title {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 24px; font-weight: 800;
    color: #e8eaf6;
    letter-spacing: -0.03em;
    margin-bottom: 6px;
    background: linear-gradient(135deg, #f0f2ff 0%, #a5b4fc 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }

  .auth-subtitle {
    font-size: 13px;
    color: #8b90b8;
    margin-bottom: 28px;
    line-height: 1.5;
  }

  /* Tab switcher */
  .auth-tabs {
    display: flex;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 12px;
    padding: 4px;
    margin-bottom: 28px;
    gap: 4px;
  }

  .auth-tab {
    flex: 1;
    padding: 9px;
    border-radius: 9px;
    border: none;
    font-family: 'Inter', sans-serif;
    font-size: 13px; font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
  }

  .auth-tab.active {
    background: linear-gradient(135deg, #4f8ef7 0%, #7b5cf0 100%);
    color: #fff;
    box-shadow: 0 0 16px rgba(79,142,247,0.35);
  }

  .auth-tab.inactive {
    background: transparent;
    color: #8b90b8;
  }

  .auth-tab.inactive:hover {
    background: rgba(255,255,255,0.06);
    color: #e8eaf6;
  }

  /* Form fields */
  .auth-field {
    margin-bottom: 16px;
  }

  .auth-label {
    display: block;
    font-size: 12px; font-weight: 600;
    color: #8b90b8;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 8px;
  }

  .auth-input {
    width: 100%;
    height: 44px;
    padding: 0 14px;
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 10px;
    font-family: 'Inter', sans-serif;
    font-size: 14px;
    color: #e8eaf6;
    outline: none;
    transition: border-color 0.15s, background 0.15s, box-shadow 0.15s;
    box-sizing: border-box;
  }

  .auth-input:focus {
    border-color: rgba(79,142,247,0.6);
    background: rgba(79,142,247,0.07);
    box-shadow: 0 0 0 3px rgba(79,142,247,0.12);
  }

  .auth-input::placeholder { color: #555a80; }

  /* Remember me row */
  .auth-remember {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 24px;
    cursor: pointer;
    user-select: none;
  }

  .auth-checkbox {
    width: 18px; height: 18px;
    border-radius: 5px;
    border: 1px solid rgba(255,255,255,0.15);
    background: rgba(255,255,255,0.05);
    display: flex; align-items: center; justify-content: center;
    flex-shrink: 0;
    transition: all 0.15s;
    cursor: pointer;
  }

  .auth-checkbox.checked {
    background: linear-gradient(135deg, #4f8ef7, #7b5cf0);
    border-color: transparent;
    box-shadow: 0 0 10px rgba(79,142,247,0.4);
  }

  .auth-remember-label {
    font-size: 13px;
    color: #8b90b8;
  }

  /* Primary button */
  .auth-btn {
    width: 100%;
    height: 46px;
    border-radius: 12px;
    border: none;
    background: linear-gradient(135deg, #4f8ef7 0%, #7b5cf0 100%);
    color: #fff;
    font-family: 'Inter', sans-serif;
    font-size: 14px; font-weight: 600;
    cursor: pointer;
    transition: opacity 0.15s, transform 0.1s, box-shadow 0.15s;
    box-shadow: 0 0 24px rgba(79,142,247,0.35);
    margin-bottom: 16px;
    display: flex; align-items: center; justify-content: center; gap: 8px;
  }

  .auth-btn:hover:not(:disabled) {
    opacity: 0.9;
    transform: translateY(-1px);
    box-shadow: 0 4px 32px rgba(79,142,247,0.45);
  }

  .auth-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
    transform: none;
  }

  /* Divider */
  .auth-divider {
    display: flex;
    align-items: center;
    gap: 12px;
    margin-bottom: 16px;
    color: #555a80;
    font-size: 12px;
  }

  .auth-divider::before,
  .auth-divider::after {
    content: '';
    flex: 1;
    height: 1px;
    background: rgba(255,255,255,0.07);
  }

  /* Slack button */
  .auth-slack-btn {
    width: 100%;
    height: 46px;
    border-radius: 12px;
    border: 1px solid rgba(255,255,255,0.1);
    background: rgba(74,21,75,0.25);
    color: #e8eaf6;
    font-family: 'Inter', sans-serif;
    font-size: 14px; font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
    display: flex; align-items: center; justify-content: center; gap: 10px;
  }

  .auth-slack-btn:hover {
    background: rgba(74,21,75,0.5);
    border-color: rgba(74,21,75,0.6);
    transform: translateY(-1px);
  }

  /* Error banner */
  .auth-error {
    padding: 12px 14px;
    border-radius: 10px;
    background: rgba(248,113,113,0.1);
    border: 1px solid rgba(248,113,113,0.25);
    color: #f87171;
    font-size: 13px;
    margin-bottom: 16px;
    animation: shake 0.3s ease;
  }

  @keyframes shake {
    0%,100% { transform: translateX(0); }
    25%      { transform: translateX(-6px); }
    75%      { transform: translateX(6px); }
  }

  /* Success banner */
  .auth-success {
    padding: 12px 14px;
    border-radius: 10px;
    background: rgba(34,211,168,0.1);
    border: 1px solid rgba(34,211,168,0.25);
    color: #22d3a8;
    font-size: 13px;
    margin-bottom: 16px;
  }

  /* Spinner */
  @keyframes spin { to { transform: rotate(360deg); } }
  .spinner {
    width: 16px; height: 16px;
    border: 2px solid rgba(255,255,255,0.3);
    border-top-color: #fff;
    border-radius: 50%;
    animation: spin 0.6s linear infinite;
    flex-shrink: 0;
  }
`;

// ── Slack Logo SVG ────────────────────────────────────────────────────────────
function SlackLogo() {
  return (
    <svg width="18" height="18" viewBox="0 0 122.8 122.8" xmlns="http://www.w3.org/2000/svg">
      <path d="M25.8 77.6c0 7.1-5.8 12.9-12.9 12.9S0 84.7 0 77.6s5.8-12.9 12.9-12.9h12.9v12.9zm6.5 0c0-7.1 5.8-12.9 12.9-12.9s12.9 5.8 12.9 12.9v32.3c0 7.1-5.8 12.9-12.9 12.9s-12.9-5.8-12.9-12.9V77.6z" fill="#E01E5A"/>
      <path d="M45.2 25.8c-7.1 0-12.9-5.8-12.9-12.9S38.1 0 45.2 0s12.9 5.8 12.9 12.9v12.9H45.2zm0 6.5c7.1 0 12.9 5.8 12.9 12.9s-5.8 12.9-12.9 12.9H12.9C5.8 58.1 0 52.3 0 45.2s5.8-12.9 12.9-12.9h32.3z" fill="#36C5F0"/>
      <path d="M97 45.2c0-7.1 5.8-12.9 12.9-12.9s12.9 5.8 12.9 12.9-5.8 12.9-12.9 12.9H97V45.2zm-6.5 0c0 7.1-5.8 12.9-12.9 12.9s-12.9-5.8-12.9-12.9V12.9C64.7 5.8 70.5 0 77.6 0s12.9 5.8 12.9 12.9v32.3z" fill="#2EB67D"/>
      <path d="M77.6 97c7.1 0 12.9 5.8 12.9 12.9s-5.8 12.9-12.9 12.9-12.9-5.8-12.9-12.9V97h12.9zm0-6.5c-7.1 0-12.9-5.8-12.9-12.9s5.8-12.9 12.9-12.9h32.3c7.1 0 12.9 5.8 12.9 12.9s-5.8 12.9-12.9 12.9H77.6z" fill="#ECB22E"/>
    </svg>
  );
}

// ── Auth Page ─────────────────────────────────────────────────────────────────
export default function AuthPage({ onAuthSuccess }) {
  const { login, register, loginWithSlack } = useAuth();

  const [tab, setTab]               = useState("login");  // "login" | "register"
  const [name, setName]             = useState("");
  const [email, setEmail]           = useState("");
  const [password, setPassword]     = useState("");
  const [rememberMe, setRememberMe] = useState(false);
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState(null);
  const [success, setSuccess]       = useState(null);

  const switchTab = (t) => {
    setTab(t);
    setError(null);
    setSuccess(null);
  };

  const handleSubmit = useCallback(async () => {
    setError(null);
    setSuccess(null);
    setLoading(true);

    try {
      if (tab === "login") {
        const data = await login({ email, password, rememberMe });
        onAuthSuccess(data.user);
      } else {
        // Register → then auto-login → send to onboarding
        await register({ name, email, password });
        const data = await login({ email, password, rememberMe: false });
        setSuccess("Account created! Setting up your workspace…");
        setTimeout(() => onAuthSuccess(data.user, true), 800);
      }
    } catch (err) {
      setError(err.message || "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  }, [tab, name, email, password, rememberMe, login, register, onAuthSuccess]);

  const handleKeyDown = (e) => {
    if (e.key === "Enter") handleSubmit();
  };

  return (
    <>
      <style>{STYLES}</style>
      <div className="auth-root">
        <div className="auth-card">

          {/* Logo */}
          <div className="auth-logo">
            <div className="auth-logo-icon">AI</div>
            <div>
              <div className="auth-logo-text">AI Workflow</div>
              <div className="auth-logo-sub">Coordinator</div>
            </div>
          </div>

          {/* Title */}
          <div className="auth-title">
            {tab === "login" ? "Welcome back" : "Create your account"}
          </div>
          <div className="auth-subtitle">
            {tab === "login"
              ? "Sign in to access your personal dashboard."
              : "Join AI Workflow Coordinator and manage your tasks smarter."}
          </div>

          {/* Tab switcher */}
          <div className="auth-tabs" role="tablist">
            <button
              role="tab"
              aria-selected={tab === "login"}
              className={`auth-tab ${tab === "login" ? "active" : "inactive"}`}
              onClick={() => switchTab("login")}
            >Sign In</button>
            <button
              role="tab"
              aria-selected={tab === "register"}
              className={`auth-tab ${tab === "register" ? "active" : "inactive"}`}
              onClick={() => switchTab("register")}
            >Create Account</button>
          </div>

          {/* Error / Success banners */}
          {error   && <div className="auth-error"   role="alert">⚠ {error}</div>}
          {success && <div className="auth-success" role="status">✓ {success}</div>}

          {/* Name field (register only) */}
          {tab === "register" && (
            <div className="auth-field">
              <label className="auth-label">Full Name</label>
              <input
                className="auth-input"
                type="text"
                placeholder="Jane Smith"
                value={name}
                onChange={e => setName(e.target.value)}
                onKeyDown={handleKeyDown}
                autoComplete="name"
              />
            </div>
          )}

          {/* Email */}
          <div className="auth-field">
            <label className="auth-label">Email</label>
            <input
              className="auth-input"
              type="email"
              placeholder="you@company.com"
              value={email}
              onChange={e => setEmail(e.target.value)}
              onKeyDown={handleKeyDown}
              autoComplete="email"
            />
          </div>

          {/* Password */}
          <div className="auth-field" style={{ marginBottom: tab === "login" ? 0 : 16 }}>
            <label className="auth-label">Password</label>
            <input
              className="auth-input"
              type="password"
              placeholder={tab === "register" ? "Min. 8 characters" : "••••••••"}
              value={password}
              onChange={e => setPassword(e.target.value)}
              onKeyDown={handleKeyDown}
              autoComplete={tab === "login" ? "current-password" : "new-password"}
            />
          </div>

          {/* Remember Me (login only) */}
          {tab === "login" && (
            <div
              className="auth-remember"
              onClick={() => setRememberMe(v => !v)}
              role="checkbox"
              aria-checked={rememberMe}
              tabIndex={0}
              onKeyDown={e => e.key === " " && setRememberMe(v => !v)}
              style={{ marginTop: 16 }}
            >
              <div className={`auth-checkbox ${rememberMe ? "checked" : ""}`}>
                {rememberMe && (
                  <svg width="10" height="8" viewBox="0 0 10 8" fill="none">
                    <path d="M1 4l2.5 2.5L9 1" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                  </svg>
                )}
              </div>
              <span className="auth-remember-label">
                Remember me for 30 days
              </span>
            </div>
          )}

          {/* Submit button */}
          <button
            className="auth-btn"
            onClick={handleSubmit}
            disabled={loading}
            style={{ marginTop: tab === "register" ? 8 : 0 }}
          >
            {loading
              ? <><div className="spinner" />{tab === "login" ? "Signing in…" : "Creating account…"}</>
              : tab === "login" ? "Sign In" : "Create Account"
            }
          </button>

          {/* Divider */}
          <div className="auth-divider">or continue with</div>

          {/* Slack OAuth */}
          <button className="auth-slack-btn" onClick={loginWithSlack}>
            <SlackLogo />
            Continue with Slack
          </button>

        </div>
      </div>
    </>
  );
}
