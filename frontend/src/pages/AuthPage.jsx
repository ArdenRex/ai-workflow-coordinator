import { useState } from "react";
import { useAuth } from "../auth/AuthContext";
import PasswordInput from "../components/PasswordInput";

export default function AuthPage() {
  const { signIn, signUp, notice } = useAuth();
  const [mode, setMode] = useState("login");
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(e) {
    e.preventDefault();
    setError(""); setBusy(true);
    try {
      if (mode === "login") await signIn(email.trim(), password, remember);
      else await signUp(email.trim(), password, name.trim(), remember);
    } catch (err) {
      setError(err.message || "Something went wrong.");
    } finally { setBusy(false); }
  }

  const register = mode === "register";
  return (
    <div className="auth-wrap">
      <form className="auth-card" onSubmit={submit} noValidate>
        <div className="brand">ACEDEN AI OS</div>
        <h1>{register ? "Create your account" : "Welcome back"}</h1>
        <p className="sub">{register ? "Connect your business systems and let AI do controlled work." : "Sign in to your workspace."}</p>
        <div className="tabs" role="tablist">
          <button type="button" role="tab" aria-selected={!register} onClick={() => { setMode("login"); setError(""); }}>Sign in</button>
          <button type="button" role="tab" aria-selected={register} onClick={() => { setMode("register"); setError(""); }}>Register</button>
        </div>
        {notice && !error && <div className="msg err" role="alert">{notice}</div>}
        {register && (<>
          <label className="f" htmlFor="name">Full name (optional)</label>
          <input id="name" className="auth-input" value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" maxLength={200} />
        </>)}
        <label className="f" htmlFor="email">Email</label>
        <input id="email" className="auth-input" type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" required />
        <label className="f" htmlFor="pw">Password</label>
        <PasswordInput inputId="pw" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete={register ? "new-password" : "current-password"} />
        {register && <div className="hint">At least 10 characters.</div>}
        <label className="check">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          Remember me for 30 days on this device
        </label>
        {error && <div className="msg err" role="alert">{error}</div>}
        <button className="btn" disabled={busy || !email || !password}>{busy ? "Please wait…" : register ? "Create account" : "Sign in"}</button>
      </form>
    </div>
  );
}
