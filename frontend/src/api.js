// Thin client for the ACEDEN AI OS API. One place for the base URL, the token and error text.
// Storage: a "remember me" sign-in lives in localStorage until the token's own expiry; otherwise sessionStorage (cleared when the tab closes).
const BASE = (process.env.REACT_APP_API_URL || "").replace(/\/$/, "");
const KEY = "aceden_ai_os_session";

export function loadSession(now = Date.now()) {
  for (const store of [window.localStorage, window.sessionStorage]) {
    try {
      const s = JSON.parse(store.getItem(KEY) || "null");
      if (s && typeof s.token === "string" && typeof s.expiresAt === "number") {
        if (s.expiresAt > now) return { token: s.token, expiresAt: s.expiresAt, remember: store === window.localStorage };
        store.removeItem(KEY); // expired: never offer a token the server will refuse
      }
    } catch (_) { /* unreadable entry: ignore */ }
  }
  return null;
}

export function saveSession(token, expiresInSeconds, remember, now = Date.now()) {
  clearSession();
  const store = remember ? window.localStorage : window.sessionStorage;
  store.setItem(KEY, JSON.stringify({ token, expiresAt: now + expiresInSeconds * 1000 }));
}

export function clearSession() {
  try { window.localStorage.removeItem(KEY); } catch (_) {}
  try { window.sessionStorage.removeItem(KEY); } catch (_) {}
}

// Turns the API's error bodies (string, validation list, throttle) into one readable sentence.
export function errorText(status, body, retryAfter) {
  if (status === 429) return `Too many attempts. Try again in ${retryAfter ? `${retryAfter} seconds` : "a moment"}.`;
  if (status === 413) return "That request is too large.";
  if (status >= 500) return "Something went wrong on the server. Try again in a moment.";
  const d = body && body.detail;
  if (typeof d === "string") return d;
  if (Array.isArray(d) && d.length) {
    return d.map((e) => (e && e.msg ? String(e.msg).replace(/^Value error, /, "") : "Invalid input")).join(" ");
  }
  return `Request failed (${status}).`;
}

export class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}

let onUnauthorized = () => {};
export function setUnauthorizedHandler(fn) { onUnauthorized = fn; }

export async function request(path, { method = "GET", body, auth = true } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth) {
    const session = loadSession();
    if (!session) { onUnauthorized(); throw new ApiError(401, "Please sign in."); }
    headers.Authorization = `Bearer ${session.token}`;
  }
  let res;
  try {
    res = await fetch(`${BASE}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) });
  } catch (_) {
    throw new ApiError(0, "Cannot reach the server. Check your connection.");
  }
  if (res.status === 204) return null;
  let data = null;
  try { data = await res.json(); } catch (_) { /* empty or non-JSON body */ }
  if (!res.ok) {
    if (res.status === 401 && auth) onUnauthorized();
    throw new ApiError(res.status, errorText(res.status, data, res.headers.get("Retry-After")));
  }
  return data;
}

export const api = {
  register: (email, password, fullName) =>
    request("/auth/register", { method: "POST", auth: false, body: { email, password, full_name: fullName || null } }),
  login: (email, password, rememberMe) =>
    request("/auth/login", { method: "POST", auth: false, body: { email, password, remember_me: !!rememberMe } }),
  logout: () => request("/auth/logout", { method: "POST" }),
  me: () => request("/auth/me"),
  changePassword: (current, next, rememberMe) =>
    request("/auth/password", { method: "POST", body: { current_password: current, new_password: next, remember_me: !!rememberMe } }),
  activity: (limit = 50) => request(`/auth/activity?limit=${limit}`),
  workspaces: () => request("/workspaces"),
  createWorkspace: (name) => request("/workspaces", { method: "POST", body: { name } }),
  workspace: (id) => request(`/workspaces/${encodeURIComponent(id)}`),
  credentials: (ws) => request(`/workspaces/${encodeURIComponent(ws)}/credentials`),
  createCredential: (ws, body) => request(`/workspaces/${encodeURIComponent(ws)}/credentials`, { method: "POST", body }),
  rotateCredential: (ws, id, secret) => request(`/workspaces/${encodeURIComponent(ws)}/credentials/${encodeURIComponent(id)}/rotate`, { method: "POST", body: { secret } }),
  revokeCredential: (ws, id) => request(`/workspaces/${encodeURIComponent(ws)}/credentials/${encodeURIComponent(id)}`, { method: "DELETE" }),
  plans: (ws, limit = 30) => request(`/workspaces/${encodeURIComponent(ws)}/plans?limit=${limit}`),
  plan: (ws, id) => request(`/workspaces/${encodeURIComponent(ws)}/plans/${encodeURIComponent(id)}`),
  createPlan: (ws, goal, idempotencyKey) => request(`/workspaces/${encodeURIComponent(ws)}/plans`, { method: "POST", body: { goal, idempotency_key: idempotencyKey, execute: false } }),
  runPlan: (ws, id, goal, steps) => request(`/workspaces/${encodeURIComponent(ws)}/plans/${encodeURIComponent(id)}/run`, { method: "POST", body: { goal, steps: steps.map((s) => ({ id: s.id, agent_id: s.agent_id, instruction: s.instruction, depends_on: s.depends_on })) } }),
  cancelPlan: (ws, id) => request(`/workspaces/${encodeURIComponent(ws)}/plans/${encodeURIComponent(id)}/cancel`, { method: "POST" }),
  testCredential: (ws, id) => request(`/workspaces/${encodeURIComponent(ws)}/credentials/${encodeURIComponent(id)}/test`, { method: "POST" }),
  approvals: (ws, limit = 50) => request(`/workspaces/${encodeURIComponent(ws)}/approvals?limit=${limit}`),
  approve: (ws, id, reason) => request(`/workspaces/${encodeURIComponent(ws)}/approvals/${encodeURIComponent(id)}/approve`, { method: "POST", body: { reason } }),
  reject: (ws, id, reason) => request(`/workspaces/${encodeURIComponent(ws)}/approvals/${encodeURIComponent(id)}/reject`, { method: "POST", body: { reason } }),
  activity_workspace: (ws, limit = 50) => request(`/workspaces/${encodeURIComponent(ws)}/activity?limit=${limit}`),
  overview: (ws, windowSeconds = 86400) => request(`/workspaces/${encodeURIComponent(ws)}/monitoring/overview?window_seconds=${windowSeconds}`),
};
