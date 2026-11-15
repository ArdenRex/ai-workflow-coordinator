import { detailText, eventLabel, inboxCounts, inputLines, toolLabel } from "./approvals";

test("tool ids become readable", () => { expect(toolLabel("email.send")).toBe("email send"); expect(toolLabel(null)).toBe(""); });
test("known events have fixed text and unknown ones are still readable", () => {
  expect(eventLabel("approval.requested")).toBe("Approval requested");
  expect(eventLabel("agent_run.waiting_approval")).toBe("Agent run waiting approval");
  expect(eventLabel("")).toBe("Event");
});
test("counts only pending items and only those the person may decide", () => {
  expect(inboxCounts([{ status: "PENDING", can_decide: true }, { status: "PENDING", can_decide: false }, { status: "APPROVED", can_decide: false }]))
    .toEqual({ pending: 2, decidable: 1 });
});
test("input lines are sorted, strings stay plain and other values are JSON", () => {
  expect(inputLines({ b: 2, a: "x", c: [1] })).toEqual([{ key: "a", value: "x" }, { key: "b", value: "2" }, { key: "c", value: "[1]" }]);
  expect(inputLines(null)).toEqual([]);
});
test("details skip empty values", () => { expect(detailText({ tool_id: "a.b", reason: "", x: null })).toBe("tool id: a.b"); });
