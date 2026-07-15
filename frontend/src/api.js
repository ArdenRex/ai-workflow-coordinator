// src/api.js
// Thin wrapper around the FastAPI backend.

const BASE = (process.env.REACT_APP_API_URL || "").replace(/\/$/, "");

// ── Token helper ──────────────────────────────────────────────────────────────
function getToken() {
  return localStorage.getItem("access_token") || sessionStorage.getItem("access_token") || null;
}

// ── Shared request helper ─────────────────────────────────────────────────────
async function request(path, options = {}) {
  const url = `${BASE}${path}`;
  const token = getToken();

  let res;
  try {
    res = await fetch(url, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(options.headers || {}),
      },
    });
  } catch (networkErr) {
    throw new Error(`Network error reaching ${url}: ${networkErr.message}`);
  }

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) {
        detail = typeof body.detail === "string"
          ? body.detail
          : JSON.stringify(body.detail);
      }
    } catch (_) {}
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }

  if (res.status === 204) return null;
  return res.json();
}

// ── Auth API ──────────────────────────────────────────────────────────────────

export async function registerUser({ name, email, password }) {
  return request("/auth/register", {
    method: "POST",
    body: JSON.stringify({ name, email, password }),
  });
}

export async function loginUser({ email, password, remember_me = false }) {
  return request("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password, remember_me }),
  });
}

export async function logoutUser() {
  return request("/auth/logout", { method: "POST" });
}

export async function fetchMe() {
  return request("/auth/me");
}

export async function completeOnboarding({ role, teamName, createWorkspace, workspaceName, inviteCode }) {
  return request("/auth/onboarding", {
    method: "POST",
    body: JSON.stringify({
      role,
      team_name:        teamName || null,
      create_workspace: createWorkspace,
      workspace_name:   workspaceName || null,
      invite_code:      inviteCode || null,
    }),
  });
}

export async function refreshToken() {
  return request("/auth/refresh", { method: "POST" });
}

// ── Tasks API ─────────────────────────────────────────────────────────────────

export async function fetchTasks({ status, assignee, priority, skip = 0, limit = 200 } = {}) {
  const params = new URLSearchParams();
  if (status)   params.set("status", status);
  if (assignee) params.set("assignee", assignee);
  if (priority) params.set("priority", priority);
  params.set("skip", String(skip));
  params.set("limit", String(Math.min(limit, 200)));
  return request(`/tasks?${params}`);
}

export async function updateTaskStatus(taskId, status) {
  if (!taskId || taskId <= 0) throw new Error("taskId must be a positive integer.");
  if (!status) throw new Error("status is required.");
  return request(`/tasks/${taskId}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

export async function deleteTask(taskId) {
  if (!taskId || taskId <= 0) throw new Error("taskId must be a positive integer.");
  return request(`/tasks/${taskId}`, { method: "DELETE" });
}

export async function processMessage(message, source = "manual") {
  if (!message || !message.trim()) throw new Error("message must not be empty.");
  return request("/process-message", {
    method: "POST",
    body: JSON.stringify({ message: message.trim(), source }),
  });
}

export async function fetchTask(taskId) {
  if (!taskId || taskId <= 0) throw new Error("taskId must be a positive integer.");
  return request(`/tasks/${taskId}`);
}

// ── Billing API ───────────────────────────────────────────────────────────────

/**
 * Creates a Lemon Squeezy hosted checkout session.
 * Returns { checkout_url, test_mode }.
 * Redirect the user to checkout_url immediately.
 */
export async function createCheckout() {
  return request("/billing/checkout", { method: "POST" });
}

/**
 * Fetches the current user's billing status from the backend.
 * Returns { status, show_wall, days_left, trial_ends_at, card_on_file }.
 */
export async function fetchBillingStatus() {
  return request("/auth/billing-status");
}

/**
 * Gets the Lemon Squeezy customer portal URL so the user can
 * manage / cancel their subscription.
 * Returns { portal_url }.
 */
export async function fetchCustomerPortal() {
  return request("/billing/portal");
}
