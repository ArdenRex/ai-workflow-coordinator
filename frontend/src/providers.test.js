import { buildConnection, statusOf, PROVIDERS } from "./providers";

const ok = { name: "Company Slack", base_url: "https://slack.com/api", secret: "xoxb-123", allow_write: false };

test("a valid Slack connection builds the API body", () => {
  const r = buildConnection("slack", ok);
  expect(r.body).toEqual({ provider: "slack", name: "Company Slack", secret: "xoxb-123", config: { base_url: "https://slack.com/api", allow_write: false } });
});

test("secrets never go into config", () => {
  const r = buildConnection("slack", ok);
  expect(JSON.stringify(r.body.config)).not.toContain("xoxb");
});

test("plain http and a missing address are refused", () => {
  expect(buildConnection("slack", { ...ok, base_url: "http://slack.com" }).error).toMatch(/https/);
  expect(buildConnection("slack", { ...ok, base_url: "" }).error).toMatch(/https/);
});

test("bad names and blank secrets are refused", () => {
  expect(buildConnection("slack", { ...ok, name: "  " }).error).toBeTruthy();
  expect(buildConnection("slack", { ...ok, name: "bad/name" }).error).toBeTruthy();
  expect(buildConnection("slack", { ...ok, secret: "   " }).error).toMatch(/required/);
});

test("Asana needs its workspace id, the AI model needs a model name", () => {
  expect(buildConnection("asana", { ...ok, base_url: PROVIDERS.asana.base }).error).toMatch(/workspace/i);
  expect(buildConnection("asana", { ...ok, base_url: PROVIDERS.asana.base, workspace_gid: "12345" }).body.config.workspace_gid).toBe("12345");
  expect(buildConnection("llm", { ...ok, base_url: "https://llm.example/v1" }).error).toMatch(/model/i);
  expect(buildConnection("llm", { ...ok, base_url: "https://llm.example/v1", model: "m1" }).body.config.allow_write).toBeUndefined();
});

test("Google connections need the three-part OAuth secret", () => {
  expect(buildConnection("gmail", { ...ok, base_url: PROVIDERS.gmail.base, secret: "only-one" }).error).toMatch(/client_id/);
  expect(buildConnection("gmail", { ...ok, base_url: PROVIDERS.gmail.base, secret: "a:b:c", allow_write: true }).body.config.allow_write).toBe(true);
});

test("unknown systems are refused", () => { expect(buildConnection("nope", ok).error).toBeTruthy(); });

test("status labels", () => {
  expect(statusOf({ is_active: false }).text).toBe("Revoked");
  expect(statusOf({ is_active: true, last_test_ok: true }).tone).toBe("ok");
  expect(statusOf({ is_active: true, last_test_ok: false }).tone).toBe("bad");
  expect(statusOf({ is_active: true, last_test_ok: null }).text).toBe("Not tested");
});
