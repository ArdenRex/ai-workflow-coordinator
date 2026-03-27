// src/api.js
// Thin wrapper around the FastAPI backend.

const BASE = (process.env.REACT_APP_API_URL || "").replace(/\/$/, "");

// ── Shared request helper ─────────────────────────────────────────────────────

async function request(path, options = {}) {
  const url = `${BASE}${path}`;
  let res;
  try {
    res = await fetch(url, {
      ...options,
      headers: {
        "Content-Type": "application/json",
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

// ── Public API ────────────────────────────────────────────────────────────────

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
