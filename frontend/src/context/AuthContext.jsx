// src/context/AuthContext.jsx
// Global auth state — wraps the entire app.
// Handles: token storage, remember me, auto-refresh, user profile.

import { createContext, useContext, useState, useEffect, useCallback, useRef } from "react";

const BASE = (process.env.REACT_APP_API_URL || "").replace(/\/$/, "");

const AuthContext = createContext(null);

// ── Token storage helpers ─────────────────────────────────────────────────────
// access_token → sessionStorage (cleared when tab closes)
// If remember_me → also stored in localStorage (survives browser restart)

const TOKEN_KEY = "access_token";
const USER_KEY  = "auth_user";

function saveToken(token, rememberMe) {
  sessionStorage.setItem(TOKEN_KEY, token);
  if (rememberMe) {
    localStorage.setItem(TOKEN_KEY, token);
    localStorage.setItem("remember_me", "true");
  }
}

function loadToken() {
  // sessionStorage first (current tab), then localStorage (remember me)
  return sessionStorage.getItem(TOKEN_KEY) || localStorage.getItem(TOKEN_KEY) || null;
}

function saveUser(user) {
  const str = JSON.stringify(user);
  sessionStorage.setItem(USER_KEY, str);
  if (localStorage.getItem("remember_me") === "true") {
    localStorage.setItem(USER_KEY, str);
  }
}

function loadUser() {
  try {
    const str = sessionStorage.getItem(USER_KEY) || localStorage.getItem(USER_KEY);
    return str ? JSON.parse(str) : null;
  } catch {
    return null;
  }
}

function clearStorage() {
  sessionStorage.removeItem(TOKEN_KEY);
  sessionStorage.removeItem(USER_KEY);
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  localStorage.removeItem("remember_me");
}

// ── API helpers ───────────────────────────────────────────────────────────────

async function apiFetch(path, options = {}, token = null) {
  const headers = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(options.headers || {}),
  };
  const res = await fetch(`${BASE}${path}`, {
    ...options,
    headers,
    credentials: "include",  // send cookies (refresh token)
  });
  return res;
}

// ── Provider ──────────────────────────────────────────────────────────────────

export function AuthProvider({ children }) {
  const [user, setUser]         = useState(() => loadUser());
  const [token, setToken]       = useState(() => loadToken());
  const [loading, setLoading]   = useState(true);   // true until initial auth check done
  const [error, setError]       = useState(null);

  const refreshTimerRef = useRef(null);

  // ── Persist state changes ──────────────────────────────────────────────────
  useEffect(() => {
    if (token && user) {
      saveToken(token, localStorage.getItem("remember_me") === "true");
      saveUser(user);
    }
  }, [token, user]);

  // ── Auto-refresh access token before it expires ────────────────────────────
  // Access token lasts 30 min. We refresh at 28 min to avoid expiry mid-request.
  const scheduleRefresh = useCallback(() => {
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    const delay = (28 * 60 * 1000); // 28 minutes
    refreshTimerRef.current = setTimeout(async () => {
      try {
        const res = await apiFetch("/auth/refresh", { method: "POST" });
        if (res.ok) {
          const data = await res.json();
          setToken(data.access_token);
          setUser(data.user);
          scheduleRefresh(); // schedule next refresh
        } else {
          // Refresh failed — log user out silently
          logout();
        }
      } catch {
        logout();
      }
    }, delay);
  }, []); // eslint-disable-line

  // ── Initial auth check on app load ────────────────────────────────────────
  // If token exists in storage, verify it's still valid by calling /auth/me
  useEffect(() => {
    const storedToken = loadToken();
    if (!storedToken) {
      setLoading(false);
      return;
    }

    apiFetch("/auth/me", {}, storedToken)
      .then(async (res) => {
        if (res.ok) {
          const userData = await res.json();
          setToken(storedToken);
          setUser(userData);
          scheduleRefresh();
        } else {
          // Token invalid — try refresh cookie
          const refreshRes = await apiFetch("/auth/refresh", { method: "POST" });
          if (refreshRes.ok) {
            const data = await refreshRes.json();
            setToken(data.access_token);
            setUser(data.user);
            saveToken(data.access_token, true);
            scheduleRefresh();
          } else {
            clearStorage();
            setToken(null);
            setUser(null);
          }
        }
      })
      .catch(() => {
        clearStorage();
        setToken(null);
        setUser(null);
      })
      .finally(() => setLoading(false));
  }, []); // eslint-disable-line

  // ── Cleanup timer on unmount ───────────────────────────────────────────────
  useEffect(() => {
    return () => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
    };
  }, []);

  // ── Auth actions ───────────────────────────────────────────────────────────

  const register = useCallback(async ({ name, email, password }) => {
    setError(null);
    const res = await apiFetch("/auth/register", {
      method: "POST",
      body: JSON.stringify({ name, email, password }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Registration failed.");
    return data; // { message, user }
  }, []);

  const login = useCallback(async ({ email, password, rememberMe = false }) => {
    setError(null);
    const res = await apiFetch("/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password, remember_me: rememberMe }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Login failed.");

    saveToken(data.access_token, rememberMe);
    saveUser(data.user);
    setToken(data.access_token);
    setUser(data.user);
    scheduleRefresh();

    return data;
  }, [scheduleRefresh]);

  const completeOnboarding = useCallback(async ({
    role,
    teamName,
    createWorkspace,
    workspaceName,
    inviteCode,
  }, accessToken) => {
    setError(null);
    const res = await apiFetch(
      "/auth/onboarding",
      {
        method: "POST",
        body: JSON.stringify({
          role,
          team_name:        teamName || null,
          create_workspace: createWorkspace,
          workspace_name:   workspaceName || null,
          invite_code:      inviteCode || null,
        }),
      },
      accessToken || token,
    );
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Onboarding failed.");

    setUser(data.user);
    saveUser(data.user);
    return data;
  }, [token]);

  const logout = useCallback(async () => {
    try {
      await apiFetch("/auth/logout", { method: "POST" }, token);
    } catch { /* ignore network errors on logout */ }
    clearStorage();
    setToken(null);
    setUser(null);
    if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current);
  }, [token]);

  const loginWithSlack = useCallback(() => {
    // Redirect browser to backend Slack OAuth login flow
    window.location.href = `${BASE}/auth/slack/login`;
  }, []);

  // ── Role helpers ───────────────────────────────────────────────────────────
  const isArchitect = user?.role === "architect";
  const isNavigator = user?.role === "navigator";
  const isOperator  = user?.role === "operator";
  const isSolo      = user?.role === "solo";
  const isOnboarded = !!user?.workspace || user?.role === "solo";

  return (
    <AuthContext.Provider value={{
      user,
      token,
      loading,
      error,
      setError,
      isAuthenticated: !!token && !!user,
      isOnboarded,
      isArchitect,
      isNavigator,
      isOperator,
      isSolo,
      register,
      login,
      logout,
      loginWithSlack,
      completeOnboarding,
    }}>
      {children}
    </AuthContext.Provider>
  );
}

// ── Hook ──────────────────────────────────────────────────────────────────────
export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
