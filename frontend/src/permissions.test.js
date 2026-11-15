import { hasPermission, permissionMatches } from "./permissions";
test("exact, wildcard and global grants match like the server", () => {
  expect(permissionMatches("connection:read", "connection:read")).toBe(true);
  expect(permissionMatches("connection:*", "connection:write")).toBe(true);
  expect(permissionMatches("*", "anything:here")).toBe(true);
});
test("a wildcard does not leak into other families or shorter names", () => {
  expect(permissionMatches("conn:*", "connection:read")).toBe(false);
  expect(permissionMatches("connection:read", "connection:write")).toBe(false);
  expect(permissionMatches("audit:*", "audit")).toBe(false);
});
test("an owner holding only * can do everything and an empty list nothing", () => {
  expect(hasPermission(["*"], "approval:decide")).toBe(true);
  expect(hasPermission([], "approval:decide")).toBe(false);
  expect(hasPermission(undefined, "x:y")).toBe(false);
});
