import * as api from "./api";

const first = Object.entries(api).find(([k, v]) => typeof v === "function" && /fetch|get|list/i.test(k));

function mockFetch(status, body) {
  global.fetch = jest.fn(async () => ({ ok: status < 400, status, json: async () => body }));
}

test("a 402 fires 'billing-required' and still throws the readable message", async () => {
  mockFetch(402, { detail: "Your free trial has ended. Please subscribe to keep using the app." });
  const seen = jest.fn();
  window.addEventListener("billing-required", seen);
  await expect(first[1]({})).rejects.toMatchObject({ status: 402, message: expect.stringContaining("free trial has ended") });
  expect(seen).toHaveBeenCalledTimes(1);
  window.removeEventListener("billing-required", seen);
});

test.each([401, 403, 404, 500])("a %i does NOT fire 'billing-required'", async (status) => {
  mockFetch(status, { detail: "x" });
  const seen = jest.fn();
  window.addEventListener("billing-required", seen);
  await expect(first[1]({})).rejects.toMatchObject({ status });
  expect(seen).not.toHaveBeenCalled();
  window.removeEventListener("billing-required", seen);
});

test("a successful response does not fire it", async () => {
  mockFetch(200, { tasks: [], total: 0 });
  const seen = jest.fn();
  window.addEventListener("billing-required", seen);
  await first[1]({});
  expect(seen).not.toHaveBeenCalled();
  window.removeEventListener("billing-required", seen);
});
