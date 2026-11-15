import { headlineOf, hintForError, isActive, isFinished, newKey, stepOrder } from "./plans";

test("headline prefers the summary's word (waiting_approval) over the raw status", () => {
  expect(headlineOf({ status: "running", summary: { headline: "waiting_approval" } })).toBe("waiting_approval");
  expect(headlineOf({ status: "pending", summary: null })).toBe("pending");
});
test("active and finished states do not overlap", () => {
  for (const s of ["pending", "running"]) { expect(isActive({ status: s })).toBe(true); expect(isFinished({ status: s })).toBe(false); }
  for (const s of ["succeeded", "failed", "cancelled"]) { expect(isActive({ status: s })).toBe(false); expect(isFinished({ status: s })).toBe(true); }
});
test("keys are unique per call", () => { expect(newKey()).not.toBe(newKey()); });
test("steps sort naturally (s2 before s10)", () => {
  expect(stepOrder([{ key: "s10" }, { key: "s2" }, { key: "s1" }]).map((s) => s.key)).toEqual(["s1", "s2", "s10"]);
});
test("a missing AI model points to Connections", () => {
  expect(hintForError({ status: 502 })).toMatch(/Connections/);
  expect(hintForError({ status: 500 })).toBe("");
});
