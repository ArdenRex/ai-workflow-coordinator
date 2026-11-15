import { clearSession, errorText, loadSession, saveSession } from "./api";

beforeEach(() => { window.localStorage.clear(); window.sessionStorage.clear(); });

test("a normal sign-in lives in sessionStorage only", () => {
  saveSession("tok", 3600, false);
  expect(window.sessionStorage.getItem("aceden_ai_os_session")).toContain("tok");
  expect(window.localStorage.getItem("aceden_ai_os_session")).toBeNull();
  expect(loadSession().remember).toBe(false);
});

test("remember me lives in localStorage and survives a closed tab", () => {
  saveSession("tok", 30 * 86400, true);
  window.sessionStorage.clear();
  const s = loadSession();
  expect(s.token).toBe("tok");
  expect(s.remember).toBe(true);
});

test("an expired session is never returned and is removed", () => {
  saveSession("tok", 60, true, Date.now() - 120000);
  expect(loadSession()).toBeNull();
  expect(window.localStorage.getItem("aceden_ai_os_session")).toBeNull();
});

test("saving replaces any earlier session in the other store", () => {
  saveSession("old", 3600, true);
  saveSession("new", 3600, false);
  expect(window.localStorage.getItem("aceden_ai_os_session")).toBeNull();
  expect(loadSession().token).toBe("new");
});

test("clearSession removes both", () => {
  saveSession("a", 3600, true); clearSession();
  expect(loadSession()).toBeNull();
});

test("a garbage stored value is ignored", () => {
  window.localStorage.setItem("aceden_ai_os_session", "{not json");
  expect(loadSession()).toBeNull();
});

test("error text is readable and never dumps raw JSON", () => {
  expect(errorText(401, { detail: "Invalid credentials" })).toBe("Invalid credentials");
  expect(errorText(422, { detail: [{ msg: "Value error, Password must be 10-128 characters" }] })).toBe("Password must be 10-128 characters");
  expect(errorText(429, {}, "30")).toContain("30 seconds");
  expect(errorText(500, { detail: "boom" })).not.toContain("boom");
});
