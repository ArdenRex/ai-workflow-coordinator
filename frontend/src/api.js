// src/api.js
// Thin wrapper around the FastAPI backend.
// The CRA proxy in package.json forwards all /api calls to http://localhost:8000

const BASE = (process.env.REACT_APP_API_URL || "").replace(/\/$/, "");

// ── Shared request helper ─────────────────────────────────────────────────────

/**
 * @param {string} path
 * @param {RequestInit} options
 * @returns {Promise<any>}
 */
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
    // fetch() itself threw — no response at all (DNS failure, offline, CORS)
    throw new Error(`Network error reaching ${url}: ${networkErr.message}`);
  }

  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (body?.detail) {
        detail = typeof body.detail === "string"
          ? body.detail
          : JSON.stringify(body.detail);   // FastAPI validation errors are arrays
      }
    } catch (_) {
      // response body was not JSON — keep the status string
    }
    const err = new Error(detail);
    err.status = res.status;
    throw err;
  }

  // 204 No Content — return null instead of trying to parse an empty body
  if (res.status === 204) return null;

  return res.json();
}

// ── Public API ────────────────────────────────────────────────────────────────

/**
 * @param {{ status?: string, assignee?: string, priority?: string, skip?: number, limit?: number }} filters
 * @returns {Promise<{ total: number, skip: number, limit: number, tasks: object[] }>}
 */
export async function fetchTasks({ status, assignee, priority, skip = 0, limit = 200 } = {}) {
  const params = new URLSearchParams();
  if (status)   params.set("status", status);
  if (assignee) params.set("assignee", assignee);
  if (priority) params.set("priority", priority);
  params.set("skip", String(skip));
  params.set("limit", String(Math.min(limit, 200)));  // enforce backend cap client-side too

  return request(`/tasks?${params}`);
}

/**
 * @param {number} taskId
 * @param {string} status
 * @returns {Promise<object>}
 */
export async function updateTaskStatus(taskId, status) {
  if (!taskId || taskId <= 0) throw new Error("taskId must be a positive integer.");
  if (!status) throw new Error("status is required.");
  return request(`/tasks/${taskId}/status`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

/**
 * @param {string} message
 * @param {string} source
 * @returns {Promise<{ message: string, extracted: object, task: object }>}
 */
export async function processMessage(message, source = "manual") {
  if (!message || !message.trim()) throw new Error("message must not be empty.");
  return request("/process-message", {
    method: "POST",
    body: JSON.stringify({ message: message.trim(), source }),
  });
}

/**
 * @param {number} taskId
 * @returns {Promise<object>}
 */
export async function fetchTask(taskId) {
  if (!taskId || taskId <= 0) throw new Error("taskId must be a positive integer.");
  return request(`/tasks/${taskId}`);
}
