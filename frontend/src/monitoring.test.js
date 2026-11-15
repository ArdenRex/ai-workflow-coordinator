import { age, attentionList, connectionState, duration, headlineCounts, pct } from "./monitoring";

const ov = (over = {}) => ({
  summary: { executions: { by_status: { succeeded: 24, failed: 1 } }, approvals: { pending: 3 } },
  health: { connections: { by_state: { failing: 2 } }, agent_runs: { by_status: { running: 4, waiting_approval: 1 }, overdue_active: 0 },
    workflow_runs: { overdue_steps: 0 }, schedules: { overdue: 0 }, events: { stuck_undispatched: 0 } }, ...over });

test("headline numbers match the blueprint's activity view", () => {
  expect(headlineCounts(ov())).toEqual({ completed: 24, pending: 3, inProgress: 5, failed: 1 });
  expect(headlineCounts(null)).toEqual({ completed: 0, pending: 0, inProgress: 0, failed: 0 });
});
test("attention reasons are plain and ordered", () => {
  expect(attentionList(ov())).toEqual(["2 connections failing", "1 failed action", "3 approvals waiting"]);
  const calm = ov({ summary: { executions: { by_status: {} }, approvals: { pending: 0 } } });
  calm.health.connections.by_state = {};
  expect(attentionList(calm)).toEqual([]);
});
test("formatting handles missing values and units", () => {
  expect(pct(null)).toBe("—"); expect(pct(0.0123)).toBe("1.2%"); expect(pct(0)).toBe("0%");
  expect(duration(250)).toBe("250 ms"); expect(duration(2500)).toBe("2.5 s"); expect(duration(null)).toBe("—");
  expect(age(30)).toBe("30 s"); expect(age(600)).toBe("10 min"); expect(age(7200)).toBe("2 h"); expect(age(259200)).toBe("3 days");
});
test("unknown connection states do not crash", () => {
  expect(connectionState("ok").text).toBe("Working"); expect(connectionState("weird").tone).toBe("off");
});
