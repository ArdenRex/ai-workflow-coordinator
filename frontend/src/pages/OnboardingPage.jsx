// src/pages/OnboardingPage.jsx
// 3-step onboarding after registration:
//   Step 1 → Pick your role
//   Step 2 → Team name (navigator only) / skipped for others
//   Step 3 → Create or join a workspace (skipped for solo)

import { useState, useCallback } from "react";
import { useAuth } from "../context/AuthContext";

// ── Styles ────────────────────────────────────────────────────────────────────
const STYLES = `
  @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@700;800&display=swap');

  .ob-root {
    min-height: 100vh;
    background: #0d0f1e;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: 'Inter', system-ui, sans-serif;
    padding: clamp(12px, 3vw, 24px);
    position: relative;
    overflow: hidden;
  }

  .ob-root::before {
    content: '';
    position: fixed;
    top: -200px; left: -200px;
    width: 600px; height: 600px;
    background: radial-gradient(circle, rgba(79,142,247,0.08) 0%, transparent 70%);
    pointer-events: none;
  }

  .ob-root::after {
    content: '';
    position: fixed;
    bottom: -200px; right: -200px;
    width: 500px; height: 500px;
    background: radial-gradient(circle, rgba(123,92,240,0.07) 0%, transparent 70%);
    pointer-events: none;
  }

  .ob-card {
    width: 100%;
    max-width: 520px;
    background: rgba(255,255,255,0.03);
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 24px;
    padding: clamp(20px, 5vw, 40px);
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

  .ob-logo {
    display: flex;
    align-items: center;
    gap: 10px;
    margin-bottom: 32px;
  }

  .ob-logo-icon {
    width: 36px; height: 36px;
    border-radius: 10px;
    background: linear-gradient(135deg, #4f8ef7 0%, #7b5cf0 100%);
    display: flex; align-items: center; justify-content: center;
    font-size: 14px; font-weight: 700; color: #fff;
    box-shadow: 0 0 20px rgba(79,142,247,0.4);
  }

  .ob-logo-text {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 16px; font-weight: 800;
    color: #e8eaf6; letter-spacing: -0.02em;
  }

  .ob-logo-sub { font-size: 11px; color: #555a80; margin-top: 1px; }

  /* Progress bar */
  .ob-progress {
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 32px;
  }

  .ob-step-dot {
    height: 4px;
    border-radius: 999px;
    transition: all 0.3s ease;
    flex: 1;
  }

  .ob-step-dot.done    { background: linear-gradient(90deg, #4f8ef7, #7b5cf0); }
  .ob-step-dot.active  { background: linear-gradient(90deg, #4f8ef7, #7b5cf0); opacity: 0.5; }
  .ob-step-dot.pending { background: rgba(255,255,255,0.08); }

  .ob-step-label {
    font-size: 11px; font-weight: 600;
    color: #555a80;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    white-space: nowrap;
  }

  .ob-title {
    font-family: 'Plus Jakarta Sans', sans-serif;
    font-size: 22px; font-weight: 800;
    letter-spacing: -0.03em;
    margin-bottom: 6px;
    background: linear-gradient(135deg, #f0f2ff 0%, #a5b4fc 100%);
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
  }

  .ob-subtitle {
    font-size: 13px; color: #8b90b8;
    margin-bottom: 28px; line-height: 1.5;
  }

  /* Role cards grid */
  .ob-roles {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 12px;
    margin-bottom: 28px;
  }

  .ob-role-card {
    padding: 18px 16px;
    border-radius: 14px;
    border: 1px solid rgba(255,255,255,0.08);
    background: rgba(255,255,255,0.03);
    cursor: pointer;
    transition: all 0.2s;
    text-align: left;
    position: relative;
    overflow: hidden;
  }

  .ob-role-card:hover {
    border-color: rgba(79,142,247,0.3);
    background: rgba(79,142,247,0.05);
    transform: translateY(-2px);
  }

  .ob-role-card.selected {
    border-color: rgba(79,142,247,0.6);
    background: rgba(79,142,247,0.1);
    box-shadow: 0 0 20px rgba(79,142,247,0.15);
  }

  .ob-role-card.selected::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, #4f8ef7, #7b5cf0);
  }

  .ob-role-emoji {
    font-size: 24px;
    margin-bottom: 10px;
    display: block;
  }

  .ob-role-name {
    font-size: 14px; font-weight: 700;
    color: #e8eaf6;
    margin-bottom: 4px;
    letter-spacing: -0.01em;
  }

  .ob-role-desc {
    font-size: 11px;
    color: #8b90b8;
    line-height: 1.4;
  }

  .ob-role-badge {
    position: absolute;
    top: 10px; right: 10px;
    width: 18px; height: 18px;
    border-radius: 50%;
    background: linear-gradient(135deg, #4f8ef7, #7b5cf0);
    display: flex; align-items: center; justify-content: center;
    opacity: 0;
    transition: opacity 0.2s;
  }

  .ob-role-card.selected .ob-role-badge { opacity: 1; }

  /* Workspace toggle */
  .ob-toggle {
    display: flex;
    background: rgba(255,255,255,0.04);
    border: 1px solid rgba(255,255,255,0.07);
    border-radius: 12px;
    padding: 4px;
    margin-bottom: 20px;
    gap: 4px;
  }

  .ob-toggle-btn {
    flex: 1;
    padding: 9px;
    border-radius: 9px;
    border: none;
    font-family: 'Inter', sans-serif;
    font-size: 13px; font-weight: 600;
    cursor: pointer;
    transition: all 0.2s;
  }

  .ob-toggle-btn.active {
    background: linear-gradient(135deg, #4f8ef7 0%, #7b5cf0 100%);
    color: #fff;
    box-shadow: 0 0 16px rgba(79,142,247,0.3);
  }

  .ob-toggle-btn.inactive {
    background: transparent;
    color: #8b90b8;
  }

  .ob-toggle-btn.inactive:hover {
    background: rgba(255,255,255,0.06);
    color: #e8eaf6;
  }

  /* Input */
  .ob-field { margin-bottom: 16px; }

  .ob-label {
    display: block;
    font-size: 12px; font-weight: 600;
    color: #8b90b8;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 8px;
  }

  .ob-input {
    width: 100%;
    height: 44px;
    padding: 0 14px;
    background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.09);
    border-radius: 10px;
    font-family: 'Inter', sans-serif;
    font-size: 14px; color: #e8eaf6;
    outline: none;
    transition: all 0.15s;
    box-sizing: border-box;
  }

  .ob-input:focus {
    border-color: rgba(79,142,247,0.6);
    background: rgba(79,142,247,0.07);
    box-shadow: 0 0 0 3px rgba(79,142,247,0.12);
  }

  .ob-input::placeholder { color: #555a80; }

  .ob-hint {
    font-size: 11px; color: #555a80;
    margin-top: 6px; line-height: 1.4;
  }

  /* Buttons row */
  .ob-actions {
    display: flex;
    gap: 10px;
    margin-top: 8px;
  }

  .ob-btn-back {
    height: 46px;
    padding: 0 20px;
    border-radius: 12px;
    border: 1px solid rgba(255,255,255,0.1);
    background: rgba(255,255,255,0.04);
    color: #8b90b8;
    font-family: 'Inter', sans-serif;
    font-size: 14px; font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
    flex-shrink: 0;
  }

  .ob-btn-back:hover {
    background: rgba(255,255,255,0.08);
    color: #e8eaf6;
  }

  .ob-btn-next {
    flex: 1;
    height: 46px;
    border-radius: 12px;
    border: none;
    background: linear-gradient(135deg, #4f8ef7 0%, #7b5cf0 100%);
    color: #fff;
    font-family: 'Inter', sans-serif;
    font-size: 14px; font-weight: 600;
    cursor: pointer;
    transition: all 0.15s;
    box-shadow: 0 0 24px rgba(79,142,247,0.35);
    display: flex; align-items: center; justify-content: center; gap: 8px;
  }

  .ob-btn-next:hover:not(:disabled) {
    opacity: 0.9;
    transform: translateY(-1px);
  }

  .ob-btn-next:disabled {
    opacity: 0.4;
    cursor: not-allowed;
    transform: none;
  }

  /* Error */
  .ob-error {
    padding: 12px 14px;
    border-radius: 10px;
    background: rgba(248,113,113,0.1);
    border: 1px solid rgba(248,113,113,0.25);
    color: #f87171;
    font-size: 13px;
    margin-bottom: 16px;
  }

  @keyframes spin { to { transform: rotate(360deg); } }
  .spinner {
    width: 16px; height: 16px;
    border: 2px solid rgba(255,255,255,0.3);
    border-top-color: #fff;
    border-radius: 50%;
    animation: spin 0.6s linear infinite;
    flex-shrink: 0;
  }

  /* Step slide animation */
  .ob-step { animation: stepIn 0.35s cubic-bezier(0.16,1,0.3,1) both; }


  @media (max-width: 480px) {
    .ob-card { border-radius: 16px; }
    .ob-roles { grid-template-columns: 1fr 1fr; gap: 8px; }
    .ob-title { font-size: 18px; }
    .ob-input { height: 40px; font-size: 13px; }
    .ob-btn-next, .ob-btn-back { height: 42px; font-size: 13px; }
  }
  @media (max-width: 360px) {
    .ob-roles { grid-template-columns: 1fr; }
  }

  @keyframes stepIn {
    from { opacity: 0; transform: translateX(20px); }
    to   { opacity: 1; transform: translateX(0); }
  }
`;

// ── Role definitions ──────────────────────────────────────────────────────────
const ROLES = [
  {
    value:  "architect",
    emoji:  "🏛️",
    name:   "Architect",
    desc:   "Manager or owner. See all tasks across your entire workspace.",
  },
  {
    value:  "navigator",
    emoji:  "🧭",
    name:   "Navigator",
    desc:   "Team lead. See all tasks assigned to your team.",
  },
  {
    value:  "operator",
    emoji:  "⚙️",
    name:   "Operator",
    desc:   "Team member. See tasks assigned to you.",
  },
  {
    value:  "solo",
    emoji:  "🚀",
    name:   "Solo",
    desc:   "Working independently. Your own private task board.",
  },
];

// ── Progress dots ─────────────────────────────────────────────────────────────
function ProgressBar({ currentStep, totalSteps }) {
  return (
    <div className="ob-progress">
      {Array.from({ length: totalSteps }).map((_, i) => (
        <div
          key={i}
          className={`ob-step-dot ${
            i < currentStep ? "done" : i === currentStep ? "active" : "pending"
          }`}
        />
      ))}
      <span className="ob-step-label">Step {currentStep + 1} of {totalSteps}</span>
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export default function OnboardingPage({ onComplete }) {
  const { completeOnboarding, token } = useAuth();

  const [step, setStep]                     = useState(0);
  const [selectedRole, setSelectedRole]     = useState(null);
  const [teamName, setTeamName]             = useState("");
  const [createWorkspace, setCreateWorkspace] = useState(true);
  const [workspaceName, setWorkspaceName]   = useState("");
  const [inviteCode, setInviteCode]         = useState("");
  const [loading, setLoading]               = useState(false);
  const [error, setError]                   = useState(null);

  // For solo users: only 2 steps (role → done)
  // For navigator: 3 steps (role → team → workspace)
  // For others: 2 steps (role → workspace)
  const isSolo      = selectedRole === "solo";
  const isNavigator = selectedRole === "navigator";
  const totalSteps  = isSolo ? 1 : isNavigator ? 3 : 2;

  const handleNext = async () => {
    setError(null);

    // Step 0 — role selection
    if (step === 0) {
      if (!selectedRole) {
        setError("Please select your role to continue.");
        return;
      }
      if (isSolo) {
        await submitOnboarding();
        return;
      }
      setStep(1);
      return;
    }

    // Step 1 — team name (navigator) or workspace (others)
    if (step === 1) {
      if (isNavigator) {
        if (!teamName.trim()) {
          setError("Please enter a team name.");
          return;
        }
        setStep(2);
        return;
      }
      // Others — this is the workspace step
      await submitOnboarding();
      return;
    }

    // Step 2 — workspace (navigator only)
    if (step === 2) {
      await submitOnboarding();
    }
  };

  const submitOnboarding = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Validate workspace input
      if (!isSolo) {
        if (createWorkspace && !workspaceName.trim()) {
          setError("Please enter a workspace name.");
          setLoading(false);
          return;
        }
        if (!createWorkspace && !inviteCode.trim()) {
          setError("Please enter the invite code from your team.");
          setLoading(false);
          return;
        }
      }

      const data = await completeOnboarding({
        role:            selectedRole,
        teamName:        isNavigator ? teamName : null,
        createWorkspace: isSolo ? false : createWorkspace,
        workspaceName:   createWorkspace ? workspaceName : null,
        inviteCode:      !createWorkspace ? inviteCode : null,
      }, token);

      onComplete(data.user);
    } catch (err) {
      setError(err.message || "Something went wrong. Please try again.");
    } finally {
      setLoading(false);
    }
  }, [
    isSolo, isNavigator, createWorkspace, workspaceName,
    inviteCode, selectedRole, teamName, token, completeOnboarding, onComplete,
  ]);

  const handleBack = () => {
    setError(null);
    setStep(s => Math.max(0, s - 1));
  };

  const handleKeyDown = (e) => {
    if (e.key === "Enter") handleNext();
  };

  // ── Current step label ─────────────────────────────────────────────────────
  const stepLabels = isSolo
    ? ["Choose Role"]
    : isNavigator
      ? ["Choose Role", "Your Team", "Workspace"]
      : ["Choose Role", "Workspace"];

  return (
    <>
      <style>{STYLES}</style>
      <div className="ob-root">
        <div className="ob-card">

          {/* Logo */}
          <div className="ob-logo">
            <div className="ob-logo-icon">AI</div>
            <div>
              <div className="ob-logo-text">AI Workflow</div>
              <div className="ob-logo-sub">Coordinator</div>
            </div>
          </div>

          {/* Progress */}
          <ProgressBar currentStep={step} totalSteps={totalSteps} />

          {/* Error */}
          {error && <div className="ob-error" role="alert">⚠ {error}</div>}

          {/* ── Step 0: Role selection ── */}
          {step === 0 && (
            <div className="ob-step">
              <div className="ob-title">What's your role?</div>
              <div className="ob-subtitle">
                This determines what tasks you see on your personal dashboard.
              </div>

              <div className="ob-roles">
                {ROLES.map(role => (
                  <div
                    key={role.value}
                    className={`ob-role-card ${selectedRole === role.value ? "selected" : ""}`}
                    onClick={() => setSelectedRole(role.value)}
                    role="radio"
                    aria-checked={selectedRole === role.value}
                    tabIndex={0}
                    onKeyDown={e => e.key === "Enter" && setSelectedRole(role.value)}
                  >
                    <div className="ob-role-badge">
                      <svg width="10" height="8" viewBox="0 0 10 8" fill="none">
                        <path d="M1 4l2.5 2.5L9 1" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                      </svg>
                    </div>
                    <span className="ob-role-emoji">{role.emoji}</span>
                    <div className="ob-role-name">{role.name}</div>
                    <div className="ob-role-desc">{role.desc}</div>
                  </div>
                ))}
              </div>

              <div className="ob-actions">
                <button
                  className="ob-btn-next"
                  onClick={handleNext}
                  disabled={!selectedRole || loading}
                >
                  {loading
                    ? <><div className="spinner" />Setting up…</>
                    : isSolo ? "Finish Setup →" : "Continue →"
                  }
                </button>
              </div>
            </div>
          )}

          {/* ── Step 1 (Navigator): Team name ── */}
          {step === 1 && isNavigator && (
            <div className="ob-step">
              <div className="ob-title">Name your team</div>
              <div className="ob-subtitle">
                Tasks assigned to members of this team will appear on your Navigator dashboard.
              </div>

              <div className="ob-field">
                <label className="ob-label">Team Name</label>
                <input
                  className="ob-input"
                  type="text"
                  placeholder="e.g. Engineering, Design, Sales"
                  value={teamName}
                  onChange={e => setTeamName(e.target.value)}
                  onKeyDown={handleKeyDown}
                  autoFocus
                />
                <div className="ob-hint">
                  You'll see all tasks where the assignee matches this team name.
                </div>
              </div>

              <div className="ob-actions">
                <button className="ob-btn-back" onClick={handleBack}>← Back</button>
                <button className="ob-btn-next" onClick={handleNext}>
                  Continue →
                </button>
              </div>
            </div>
          )}

          {/* ── Step 1 (non-Navigator) or Step 2 (Navigator): Workspace ── */}
          {((step === 1 && !isNavigator) || (step === 2 && isNavigator)) && (
            <div className="ob-step">
              <div className="ob-title">Set up your workspace</div>
              <div className="ob-subtitle">
                A workspace groups your team's tasks together. Create a new one or join an existing workspace.
              </div>

              {/* Create / Join toggle */}
              <div className="ob-toggle">
                <button
                  className={`ob-toggle-btn ${createWorkspace ? "active" : "inactive"}`}
                  onClick={() => setCreateWorkspace(true)}
                >
                  Create New
                </button>
                <button
                  className={`ob-toggle-btn ${!createWorkspace ? "active" : "inactive"}`}
                  onClick={() => setCreateWorkspace(false)}
                >
                  Join Existing
                </button>
              </div>

              {createWorkspace ? (
                <div className="ob-field">
                  <label className="ob-label">Workspace Name</label>
                  <input
                    className="ob-input"
                    type="text"
                    placeholder="e.g. Acme Corp, My Startup"
                    value={workspaceName}
                    onChange={e => setWorkspaceName(e.target.value)}
                    onKeyDown={handleKeyDown}
                    autoFocus
                  />
                  <div className="ob-hint">
                    An invite code will be generated — share it with your teammates.
                  </div>
                </div>
              ) : (
                <div className="ob-field">
                  <label className="ob-label">Invite Code</label>
                  <input
                    className="ob-input"
                    type="text"
                    placeholder="e.g. aB3kR9xZ"
                    value={inviteCode}
                    onChange={e => setInviteCode(e.target.value)}
                    onKeyDown={handleKeyDown}
                    autoFocus
                  />
                  <div className="ob-hint">
                    Ask your Architect (workspace owner) for the invite code.
                  </div>
                </div>
              )}

              <div className="ob-actions">
                <button className="ob-btn-back" onClick={handleBack}>← Back</button>
                <button
                  className="ob-btn-next"
                  onClick={handleNext}
                  disabled={loading}
                >
                  {loading
                    ? <><div className="spinner" />Setting up…</>
                    : "Finish Setup →"
                  }
                </button>
              </div>
            </div>
          )}

        </div>
      </div>
    </>
  );
}
