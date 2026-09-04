// src/components/PasswordInput.jsx
// A password <input> with a click-to-reveal eye icon.
// Drop-in replacement for a plain <input type="password" .../> — pass the
// same className used by the surrounding form (e.g. "auth-input") and it
// will style itself to match.

import { useState } from "react";

function EyeIcon({ open }) {
  return open ? (
    // Open eye — password is currently visible as plain text
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M1 12s4-7 11-7 11 7 11 7-4 7-11 7-11-7-11-7z" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  ) : (
    // Eye with a slash — password is currently hidden
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">
      <path d="M17.94 17.94A10.94 10.94 0 0 1 12 19c-7 0-11-7-11-7a21.7 21.7 0 0 1 5.06-5.94M9.9 4.24A10.4 10.4 0 0 1 12 4c7 0 11 7 11 7a21.6 21.6 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24" />
      <line x1="1" y1="1" x2="23" y2="23" />
    </svg>
  );
}

export default function PasswordInput({
  className = "auth-input",
  value,
  onChange,
  onKeyDown,
  placeholder,
  autoComplete = "current-password",
  style = {},
  inputId,
}) {
  const [visible, setVisible] = useState(false);

  return (
    <div style={{ position: "relative", width: "100%" }}>
      <input
        id={inputId}
        className={className}
        type={visible ? "text" : "password"}
        placeholder={placeholder}
        value={value}
        onChange={onChange}
        onKeyDown={onKeyDown}
        autoComplete={autoComplete}
        style={{ paddingRight: 42, ...style }}
      />
      <button
        type="button"
        onClick={() => setVisible(v => !v)}
        aria-label={visible ? "Hide password" : "Show password"}
        tabIndex={-1}
        style={{
          position: "absolute",
          right: 12,
          top: "50%",
          transform: "translateY(-50%)",
          background: "none",
          border: "none",
          padding: 0,
          margin: 0,
          cursor: "pointer",
          color: visible ? "#ffb199" : "#6b6058",
          display: "flex",
          alignItems: "center",
          lineHeight: 0,
        }}
      >
        <EyeIcon open={visible} />
      </button>
    </div>
  );
}
