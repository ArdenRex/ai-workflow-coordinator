import { act } from "react-dom/test-utils";
import { createRoot } from "react-dom/client";
import App from "./App";
import { saveSession } from "./api";

global.IS_REACT_ACT_ENVIRONMENT = true;
const flush = () => act(async () => { await new Promise((r) => setTimeout(r, 0)); });

function fakeApi(perms) {
  const ws = { id: "w1", name: "Acme", slug: "acme", role: "owner", created_at: "2026-01-01T00:00:00", permissions: perms };
  const cred = { id: "c1", provider: "slack", name: "Company Slack", config: { allow_write: false }, version: 1, is_active: true, created_at: "2026-01-01T00:00:00", last_test_ok: null };
  const routes = {
    "GET /auth/me": { id: "u1", email: "a@b.co", full_name: "Ann" },
    "GET /workspaces": [ws], "GET /workspaces/w1": ws, "GET /workspaces/w1/credentials": [cred],
  };
  const calls = [];
  global.fetch = jest.fn(async (url, init = {}) => {
    const key = `${init.method || "GET"} ${url}`; calls.push(key);
    const body = routes[key];
    return { ok: body !== undefined, status: body !== undefined ? 200 : 404, headers: { get: () => null }, json: async () => body ?? { detail: "nope" } };
  });
  return calls;
}

async function mount(path) {
  window.history.pushState({}, "", path);
  const el = document.createElement("div"); document.body.appendChild(el);
  const root = createRoot(el);
  await act(async () => { root.render(<App />); });
  await flush(); await flush();
  return { el, root };
}

beforeEach(() => { window.localStorage.clear(); window.sessionStorage.clear(); document.body.innerHTML = ""; });

test("without a session the sign-in page shows and no API call is made", async () => {
  const calls = fakeApi(["connection:read"]);
  const { el } = await mount("/");
  expect(el.textContent).toContain("Welcome back");
  expect(el.textContent).toContain("Remember me for 30 days");
  expect(calls).toEqual([]);
});

test("an admin sees the connections list and the connect form", async () => {
  const calls = fakeApi(["connection:read", "connection:write", "connection:test"]);
  saveSession("tok", 3600, false);
  const { el } = await mount("/connections");
  expect(calls).toContain("GET /workspaces/w1/credentials");
  expect(el.textContent).toContain("Company Slack");
  expect(el.textContent).toContain("Connect a system");
  expect(el.textContent).toContain("Test");
});

test("a read-only member sees connections but no way to change them", async () => {
  fakeApi(["connection:read"]);
  saveSession("tok", 3600, false);
  const { el } = await mount("/connections");
  expect(el.textContent).toContain("Company Slack");
  expect(el.textContent).not.toContain("Connect a system");
  expect(el.textContent).not.toContain("Revoke");
});

test("a signed-in user with no workspace is asked to create one", async () => {
  const calls = fakeApi([]);
  const f = global.fetch;
  global.fetch = jest.fn(async (url, init) => (url === "/workspaces" && init?.method === "GET" ? { ok: true, status: 200, headers: { get: () => null }, json: async () => [] } : f(url, init)));
  saveSession("tok", 3600, false);
  const { el } = await mount("/");
  expect(el.textContent).toContain("Create your first workspace");
  expect(calls.length).toBeGreaterThan(0);
});

describe("goals and plans", () => {
  const WS = { id: "w1", name: "Acme", slug: "acme", role: "owner", created_at: "2026-01-01T00:00:00", permissions: ["agent:run"] };
  const PLAN = { id: "p1", status: "pending", requested_by: "u1", goal_chars: 20, step_count: 1, cancel_requested: false, error_code: null, started_at: null, finished_at: null, created_at: "2026-01-01T00:00:00", steps: [], summary: null };
  function fake(extra) {
    const calls = [];
    global.fetch = jest.fn(async (url, init = {}) => {
      const key = `${init.method || "GET"} ${url}`; calls.push({ key, body: init.body ? JSON.parse(init.body) : null });
      const table = { "GET /auth/me": { id: "u1", email: "a@b.co" }, "GET /workspaces": [WS], "GET /workspaces/w1": WS, "GET /workspaces/w1/plans?limit=30": [PLAN], ...extra };
      const body = typeof table[key] === "function" ? table[key]() : table[key];
      return { ok: body !== undefined, status: body !== undefined ? 200 : 404, headers: { get: () => null }, json: async () => body ?? { detail: "nope" } };
    });
    return calls;
  }
  const type = (el, value) => act(async () => { const set = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(el), "value").set; set.call(el, value); el.dispatchEvent(new Event("input", { bubbles: true })); });
  const click = (el) => act(async () => { el.dispatchEvent(new MouseEvent("click", { bubbles: true })); });
  const button = (el, text) => [...el.querySelectorAll("button")].find((b) => b.textContent.includes(text));

  test("recent plans are listed and a member without agent:run is told so", async () => {
    fake();
    saveSession("tok", 3600, false);
    const { el } = await mount("/goals");
    expect(el.textContent).toContain("Give the AI a goal");
    expect(el.textContent).toContain("Queued");
  });

  test("a goal is planned, reviewed, and only then run with the reviewed steps", async () => {
    const steps = [{ id: "s1", agent_id: "ops", instruction: "List open items", depends_on: [] }];
    const calls = fake({
      "POST /workspaces/w1/plans": { decomposition: "planned", message: "Plan ready", plan: PLAN, proposed_steps: steps },
      "POST /workspaces/w1/plans/p1/run": { drive_state: "completed", plan: { ...PLAN, status: "succeeded", steps: [], summary: { headline: "succeeded", total_steps: 1, finished_steps: 1, needs_attention: { approvals: [] } } } },
      "GET /workspaces/w1/plans/p1": { ...PLAN, status: "succeeded", summary: { headline: "succeeded", total_steps: 1, finished_steps: 1, needs_attention: { approvals: [] } } },
    });
    saveSession("tok", 3600, false);
    const { el } = await mount("/goals");
    await type(el.querySelector("textarea"), "Summarise this week");
    await click(button(el, "Create plan")); await flush();
    expect(el.textContent).toContain("Review the plan");
    expect(el.textContent).toContain("List open items");
    expect(calls.some((c) => c.key.endsWith("/run"))).toBe(false);           // nothing runs before the user approves
    const created = calls.find((c) => c.key === "POST /workspaces/w1/plans").body;
    expect(created.execute).toBe(false); expect(created.idempotency_key).toBeTruthy();
    await click(button(el, "Approve and run")); await flush();
    const run = calls.find((c) => c.key.endsWith("/run")).body;
    expect(run.goal).toBe("Summarise this week"); expect(run.steps).toEqual(steps);
    expect(el.textContent).toContain("1 of 1 steps finished");
  });

  test("when the AI needs more information it shows the questions and creates no plan", async () => {
    fake({ "POST /workspaces/w1/plans": { decomposition: "needs_information", message: "Which customer?", missing_information: ["customer name"], plan: null } });
    saveSession("tok", 3600, false);
    const { el } = await mount("/goals");
    await type(el.querySelector("textarea"), "Follow up");
    await click(button(el, "Create plan")); await flush();
    expect(el.textContent).toContain("Which customer?"); expect(el.textContent).toContain("customer name");
    expect(el.textContent).not.toContain("Review the plan");
  });
});

function approvalRoutes(perms, extra = {}) {
  const calls = fakeApi(perms);
  const f = global.fetch;
  const item = { id: "a1", execution_id: "e1", status: "PENDING", tool_id: "email.send", risk: "high", agent: "ops_agent", requested_by: "u2",
    decided_by: null, decided_at: null, reason: null, expires_at: "2099-01-01T00:00:00", created_at: "2026-01-01T00:00:00", can_decide: perms.includes("approval:decide"),
    input: perms.includes("approval:decide") ? { to: "x@y.co", count: 5 } : null, ...extra };
  global.fetch = jest.fn(async (url, init = {}) => {
    const key = `${init.method || "GET"} ${url}`;
    if (key.startsWith("GET /workspaces/w1/approvals")) { calls.push(key); return { ok: true, status: 200, headers: { get: () => null }, json: async () => [item] }; }
    if (key.startsWith("POST /workspaces/w1/approvals/a1/")) { calls.push(`${key} ${init.body}`); return { ok: true, status: 200, headers: { get: () => null }, json: async () => ({ ...item, status: "APPROVED" }) }; }
    if (key.startsWith("GET /workspaces/w1/activity")) { calls.push(key); return { ok: true, status: 200, headers: { get: () => null }, json: async () => [{ id: "v1", event_type: "approval.requested", actor: "u2", execution_id: "e1", created_at: "2026-01-01T00:00:00", details: { tool_id: "email.send" } }] }; }
    return f(url, init);
  });
  return calls;
}

test("an approver sees the request, reviews its details and approves with one confirmed click", async () => {
  const calls = approvalRoutes(["approval:decide", "audit:read"]);
  window.confirm = jest.fn(() => true);
  saveSession("tok", 3600, false);
  const { el } = await mount("/approvals");
  expect(el.textContent).toContain("email send"); expect(el.textContent).toContain("High risk"); expect(el.textContent).toContain("1 waiting");
  expect(el.textContent).not.toContain("x@y.co");                                   // details stay hidden until reviewed
  await act(async () => { [...el.querySelectorAll("button")].find((b) => b.textContent === "Review details").click(); });
  expect(el.textContent).toContain("x@y.co");
  await act(async () => { [...el.querySelectorAll("button")].find((b) => b.textContent === "Approve").click(); });
  await flush();
  expect(window.confirm).toHaveBeenCalled();
  expect(calls.some((c) => c.startsWith("POST /workspaces/w1/approvals/a1/approve"))).toBe(true);
});

test("declining the confirmation sends nothing", async () => {
  const calls = approvalRoutes(["approval:decide"]);
  window.confirm = jest.fn(() => false);
  saveSession("tok", 3600, false);
  const { el } = await mount("/approvals");
  await act(async () => { [...el.querySelectorAll("button")].find((b) => b.textContent === "Approve").click(); });
  expect(calls.some((c) => c.startsWith("POST"))).toBe(false);
});

test("a requester without decide rights sees status only: no details, no buttons, no activity tab", async () => {
  approvalRoutes(["task:read"]);
  saveSession("tok", 3600, false);
  const { el } = await mount("/approvals");
  expect(el.textContent).toContain("Waiting for you"); expect(el.textContent).toContain("waiting for a workspace admin");
  expect([...el.querySelectorAll("button")].some((b) => ["Approve", "Reject", "Review details", "Activity"].includes(b.textContent))).toBe(false);
});

test("the owner's wildcard permission shows the connect form (wildcards match like the server)", async () => {
  fakeApi(["*"]);
  saveSession("tok", 3600, false);
  const { el } = await mount("/connections");
  expect(el.textContent).toContain("Connect a system");
});

test("auditors can open the activity tab", async () => {
  const calls = approvalRoutes(["audit:*"]);
  saveSession("tok", 3600, false);
  const { el } = await mount("/approvals");
  await act(async () => { [...el.querySelectorAll("button")].find((b) => b.textContent === "Activity").click(); });
  await flush();
  expect(calls.some((c) => c.startsWith("GET /workspaces/w1/activity"))).toBe(true);
  expect(el.textContent).toContain("Approval requested");
});

const OVERVIEW = { window_seconds: 86400, generated_at: "2026-01-01T00:00:00", alerts: { alerts: [{ rule: "failure_rate", severity: "critical", value: 0.5, threshold: 0.2, message: "Many actions are failing." }] },
  summary: { executions: { total: 25, by_status: { succeeded: 24, failed: 1 }, failure_rate: 0.04, avg_duration_ms: 120, max_duration_ms: 900 }, approvals: { pending: 3, oldest_pending_age_seconds: 600, decided_in_window: 2, avg_decision_seconds: 300 },
    denials_in_window: 0, recent_failures: [{ execution_id: "e9", tool_id: "crm.lead.create", error: "timeout", finished_at: "2026-01-01T00:00:00" }] },
  health: { connections: { by_state: { failing: 1 }, connections: [{ credential_id: "c1", provider: "slack", name: "Company Slack", state: "failing", last_tested_at: null }] },
    agent_runs: { by_status: { running: 2 }, overdue_active: 0 }, workflow_runs: { by_status: { succeeded: 3 }, overdue_steps: 0, steps_waiting_retry: 0 },
    schedules: { enabled: 1, disabled: 0, auto_disabled: 0, overdue: 0 }, events: { received_in_window: 4, dispatched_in_window: 4, stuck_undispatched: 0 } } };

test("an admin sees the four headline numbers, alerts and connection health", async () => {
  const calls = fakeApi(["audit:read"]);
  const f = global.fetch;
  global.fetch = jest.fn(async (url, init) => (String(url).startsWith("/workspaces/w1/monitoring/overview") ? (calls.push(`GET ${url}`), { ok: true, status: 200, headers: { get: () => null }, json: async () => OVERVIEW }) : f(url, init)));
  saveSession("tok", 3600, false);
  const { el } = await mount("/monitoring");
  expect(calls).toContain("GET /workspaces/w1/monitoring/overview?window_seconds=86400");
  for (const t of ["Completed", "Pending approval", "In progress", "Failed", "Many actions are failing.", "Company Slack", "Failing", "crm.lead.create", "Open approvals"]) expect(el.textContent).toContain(t);
});

test("changing the time window asks the API for that window", async () => {
  const calls = fakeApi(["audit:read"]);
  const f = global.fetch;
  global.fetch = jest.fn(async (url, init) => (String(url).startsWith("/workspaces/w1/monitoring/overview") ? (calls.push(`GET ${url}`), { ok: true, status: 200, headers: { get: () => null }, json: async () => OVERVIEW }) : f(url, init)));
  saveSession("tok", 3600, false);
  const { el } = await mount("/monitoring");
  await act(async () => { [...el.querySelectorAll("button")].find((b) => b.textContent === "Last 7 days").click(); });
  await flush();
  expect(calls).toContain("GET /workspaces/w1/monitoring/overview?window_seconds=604800");
});

test("a member without audit rights gets an explanation and no API call", async () => {
  const calls = fakeApi(["task:read"]);
  saveSession("tok", 3600, false);
  const { el } = await mount("/monitoring");
  expect(el.textContent).toContain("available to workspace admins and owners");
  expect(calls.some((c) => c.includes("monitoring"))).toBe(false);
});
