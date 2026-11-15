import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { hasPermission } from "../permissions";

const Ctx = createContext(null);
export const useWorkspace = () => useContext(Ctx);
const KEY = "aceden_ai_os_workspace"; // only a workspace id: not a secret

export function WorkspaceProvider({ children }) {
  const [list, setList] = useState(null);
  const [current, setCurrent] = useState(null); // { id, name, role, permissions }
  const [error, setError] = useState("");

  const select = useCallback(async (id) => {
    try {
      const ws = await api.workspace(id);
      window.localStorage.setItem(KEY, id);
      setCurrent(ws);
    } catch (e) { setError(e.message); }
  }, []);

  const reload = useCallback(async (preferId) => {
    try {
      const items = await api.workspaces();
      setList(items);
      const saved = preferId || window.localStorage.getItem(KEY);
      const pick = items.find((w) => w.id === saved) || items[0];
      if (pick) await select(pick.id); else setCurrent(null);
    } catch (e) { setError(e.message); setList([]); }
  }, [select]);

  useEffect(() => { reload(); }, [reload]);

  const create = useCallback(async (name) => { const ws = await api.createWorkspace(name); await reload(ws.id); }, [reload]);
  const can = useCallback((perm) => !!current && hasPermission(current.permissions, perm), [current]);
  const value = useMemo(() => ({ list, current, error, select, create, can }), [list, current, error, select, create, can]);
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
