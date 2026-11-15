import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api, clearSession, loadSession, saveSession, setUnauthorizedHandler } from "../api";

const Ctx = createContext(null);
export const useAuth = () => useContext(Ctx);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [remember, setRemember] = useState(false);
  const [booting, setBooting] = useState(() => !!loadSession());
  const [notice, setNotice] = useState("");

  const drop = useCallback((message = "") => { clearSession(); setUser(null); setNotice(message); }, []);

  useEffect(() => { setUnauthorizedHandler(() => drop("Your session has ended. Please sign in again.")); }, [drop]);

  useEffect(() => { // resume a stored session (remembered, or same tab)
    const s = loadSession();
    if (!s) { setBooting(false); return; }
    setRemember(s.remember);
    api.me().then(setUser).catch(() => {}).finally(() => setBooting(false));
  }, []);

  const signIn = useCallback(async (email, password, rememberMe) => {
    const t = await api.login(email, password, rememberMe);
    saveSession(t.access_token, t.expires_in, rememberMe);
    setRemember(!!rememberMe);
    setNotice("");
    setUser(await api.me());
  }, []);

  const signUp = useCallback(async (email, password, fullName, rememberMe) => {
    await api.register(email, password, fullName);
    await signIn(email, password, rememberMe);
  }, [signIn]);

  const signOut = useCallback(async () => {
    try { await api.logout(); } catch (_) { /* clear locally even if the server cannot be reached */ }
    drop("");
  }, [drop]);

  const replaceToken = useCallback((t, rememberMe) => { saveSession(t.access_token, t.expires_in, rememberMe); setRemember(!!rememberMe); }, []);

  const value = useMemo(() => ({ user, remember, booting, notice, signIn, signUp, signOut, replaceToken }),
    [user, remember, booting, notice, signIn, signUp, signOut, replaceToken]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
