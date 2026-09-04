// src/pages/ResetPasswordPage.jsx
// Public page: /reset-password?token=<token>
// Reached from the link in the "reset your password" email.
// Reuses AuthPage's visual language so it feels like part of the same flow.

import { useState, useCallback } from "react";
import { useAuth } from "../context/AuthContext";
import PasswordInput from "../components/PasswordInput";

const STYLES = `
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@700;800&display=swap');

  .rp-root {
    min-height: 100vh;
    background: #120705;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    font-family: 'Inter', system-ui, sans-serif;
    padding: clamp(12px, 3vw, 24px);
    position: relative;
    overflow: hidden;
  }

  .rp-root::before {
    content: '';
    position: fixed;
    top: -200px; left: -200px;
    width: 600px; height: 600px;
    background: radial-gradient(circle, rgba(255,106,82,0.08) 0%, transparent 70%);
    pointer-events: none;
  }
  .rp-root::after {
    content: '';
    position: fixed;
    bottom: -200px; right: -200px;
    width: 600px; height: 600px;
    background: radial-gradient(circle, rgba(200,31,48,0.07) 0%, transparent 70%);
    pointer-events: none;
  }

  .rp-card {
    width: 100%;
    max-width: 440px;
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 24px;
    padding: clamp(20px, 5vw, 40px);
    backdrop-filter: blur(20px);
    box-shadow: 0 24px 64px rgba(0,0,0,0.4);
    position: relative;
    z-index: 1;
    animation: rpCardIn 0.5s cubic-bezier(0.16,1,0.3,1) both;
  }

  @keyframes rpCardIn {
    from { opacity: 0; transform: translateY(24px) scale(0.97); }
    to   { opacity: 1; transform: translateY(0) scale(1); }
  }

  .rp-logo {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 32px;
  }

  .rp-logo-icon {
    width: 36px; height: 36px;
    border-radius: 10px;
    background: linear-gradient(135deg, #ff6a52 0%, #c81f30 100%);
    display: flex; align-items: center; justify-content: center;
    font-size: 14px; font-weight: 700; color: #f5f0eb;
    box-shadow: 0 0 20px rgba(255,106,82,0.4);
    flex-shrink: 0;
  }

  .rp-logo-text {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 16px; font-weight: 800;
    color: #efe7df;
    letter-spacing: -0.02em;
  }

  .rp-logo-sub {
    font-size: 11px;
    color: #6b6058;
    margin-top: 1px;
  }

  .rp-title {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 24px; font-weight: 800;
    color: #efe7df;
    letter-spacing: -0.03em;
    margin-bottom: 6px;
    background: linear-gradient(135deg, #efe7df 0%, #ffb199 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }

  .rp-subtitle {
    font-size: 13px;
    color: #9a908a;
    margin-bottom: 28px;
    line-height: 1.5;
  }

  .rp-field {
    margin-bottom: 16px;
  }

  .rp-label {
    display: block;
    font-size: 12px; font-weight: 600;
    color: #9a908a;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 8px;
  }

  .rp-input {
    width: 100%;
    height: 44px;
    padding: 0 14px;
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 10px;
    font-family: 'Inter', sans-serif;
    font-size: 14px;
    color: #efe7df;
    outline: none;
    transition: border-color 0.15s, background 0.15s, box-shadow 0.15s;
    box-sizing: border-box;
  }

  .rp-input:focus {
    border-color: rgba(255,106,82,0.6);
    background: rgba(255,106,82,0.07);
    box-shadow: 0 0 0 3px rgba(255,106,82,0.12);
  }

  .rp-input::placeholder { color: #6b6058; }

  .rp-btn {
    width: 100%;
    height: 46px;
    border-radius: 12px;
    border: none;
    background: linear-gradient(135deg, #ff6a52 0%, #c81f30 100%);
    color: #f5f0eb;
    font-family: 'Inter', sans-serif;
    font-size: 14px; font-weight: 600;
    cursor: pointer;
    transition: opacity 0.15s, transform 0.1s, box-shadow 0.15s;
    box-shadow: 0 0 24px rgba(255,106,82,0.35);
    margin-top: 8px;
    display: flex; align-items: center; justify-content: center; gap: 8px;
  }

  .rp-btn:hover:not(:disabled) {
    opacity: 0.9;
    transform: translateY(-1px);
    box-shadow: 0 4px 32px rgba(255,106,82,0.45);
  }

  .rp-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
    transform: none;
  }

  .rp-error {
    padding: 12px 14px;
    border-radius: 10px;
    background: rgba(255,77,94,0.1);
    border: 1px solid rgba(255,77,94,0.25);
    color: #ff4d5e;
    font-size: 13px;
    margin-bottom: 16px;
  }

  .rp-success {
    padding: 12px 14px;
    border-radius: 10px;
    background: rgba(63,174,125,0.1);
    border: 1px solid rgba(63,174,125,0.25);
    color: #3fae7d;
    font-size: 13px;
    margin-bottom: 16px;
  }

  .rp-link {
    display: block;
    text-align: center;
    margin-top: 20px;
    font-size: 13px;
    color: #9a908a;
    text-decoration: none;
    transition: color 0.15s;
  }

  .rp-link:hover { color: #ffb199; }

  @keyframes rpSpin { to { transform: rotate(360deg); } }
  .rp-spinner {
    width: 16px; height: 16px;
    border: 2px solid rgba(255,255,255,0.3);
    border-top-color: #f5f0eb;
    border-radius: 50%;
    animation: rpSpin 0.6s linear infinite;
    flex-shrink: 0;
  }
`;

export default function ResetPasswordPage() {
  const { resetPassword } = useAuth();

  const token = new URLSearchParams(window.location.search).get("token") || "";

  const [newPassword, setNewPassword]         = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [loading, setLoading]                 = useState(false);
  const [error, setError]                     = useState(null);
  const [done, setDone]                       = useState(false);

  const handleSubmit = useCallback(async () => {
    setError(null);

    if (!token) {
      setError("This reset link is missing its token. Please request a new one.");
      return;
    }
    if (newPassword.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (newPassword !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setLoading(true);
    try {
      await resetPassword({ token, newPassword });
      setDone(true);
    } catch (err) {
      setError(err.message || "Could not reset your password. Please try again.");
    } finally {
      setLoading(false);
    }
  }, [token, newPassword, confirmPassword, resetPassword]);

  const handleKeyDown = (e) => {
    if (e.key === "Enter") handleSubmit();
  };

  return (
    <>
      <style>{STYLES}</style>
      <div className="rp-root">
        <div className="rp-card">

          <div className="rp-logo">
            <div className="rp-logo-icon">AI</div>
            <div>
              <div className="rp-logo-text">AI Workflow</div>
              <div className="rp-logo-sub">Coordinator</div>
            </div>
          </div>

          <div className="rp-title">
            {done ? "Password reset" : "Choose a new password"}
          </div>
          <div className="rp-subtitle">
            {done
              ? "Your password has been changed. You can now sign in with it."
              : "Enter a new password for your account."}
          </div>

          {error && <div className="rp-error" role="alert">⚠ {error}</div>}

          {done ? (
            <>
              <div className="rp-success" role="status">✓ Password updated successfully.</div>
              <a className="rp-link" href="/" style={{ marginTop: 4 }}>Go to Sign In</a>
            </>
          ) : (
            <>
              <div className="rp-field">
                <label className="rp-label">New Password</label>
                <PasswordInput
                  className="rp-input"
                  value={newPassword}
                  onChange={e => setNewPassword(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Min. 8 characters"
                  autoComplete="new-password"
                />
              </div>

              <div className="rp-field">
                <label className="rp-label">Confirm New Password</label>
                <PasswordInput
                  className="rp-input"
                  value={confirmPassword}
                  onChange={e => setConfirmPassword(e.target.value)}
                  onKeyDown={handleKeyDown}
                  placeholder="Re-enter your new password"
                  autoComplete="new-password"
                />
              </div>

              <button className="rp-btn" onClick={handleSubmit} disabled={loading}>
                {loading
                  ? <><div className="rp-spinner" />Resetting…</>
                  : "Reset Password"
                }
              </button>

              <a className="rp-link" href="/">Back to Sign In</a>
            </>
          )}

        </div>
      </div>
    </>
  );
}
