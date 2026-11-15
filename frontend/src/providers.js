// What the "Connect a system" form offers. Base URLs are suggestions the user can edit; the server validates everything again.
export const PROVIDERS = {
  slack: { label: "Slack", domain: "Chat", base: "https://slack.com/api", secretLabel: "Bot token", write: true },
  hubspot: { label: "HubSpot", domain: "CRM", base: "https://api.hubapi.com", secretLabel: "Private app token", write: true },
  asana: { label: "Asana", domain: "Projects", base: "https://app.asana.com/api/1.0", secretLabel: "Personal access token", fields: [{ key: "workspace_gid", label: "Asana workspace ID (digits)", required: true }] },
  gmail: { label: "Gmail", domain: "Email", base: "https://gmail.googleapis.com", secretLabel: "client_id:client_secret:refresh_token", write: true, oauth: true },
  google_calendar: { label: "Google Calendar", domain: "Calendar", base: "https://www.googleapis.com", secretLabel: "client_id:client_secret:refresh_token", write: true, oauth: true },
  aceden: { label: "Aceden", domain: "Business system", base: "", secretLabel: "API token" },
  llm: { label: "AI model", domain: "Language model", base: "", secretLabel: "API key", fields: [{ key: "model", label: "Model name", required: true }] },
};
export const PROVIDER_IDS = Object.keys(PROVIDERS);

// Form values -> the API's { provider, name, secret, config } body, or { error } with a readable message.
export function buildConnection(provider, form) {
  const p = PROVIDERS[provider];
  if (!p) return { error: "Choose a system to connect." };
  const name = (form.name || "").trim();
  const secret = form.secret || "";
  const baseUrl = (form.base_url || "").trim();
  if (!/^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$/.test(name)) return { error: "Name must be 1-64 characters: letters, digits, space, . _ -" };
  if (!/^https:\/\/[^\s/]+/.test(baseUrl)) return { error: "Address must start with https://" };
  if (!secret.trim()) return { error: `${p.secretLabel} is required.` };
  if (p.oauth && secret.split(":").length !== 3) return { error: "Use the form client_id:client_secret:refresh_token." };
  const config = { base_url: baseUrl };
  for (const f of p.fields || []) {
    const v = (form[f.key] || "").trim();
    if (f.required && !v) return { error: `${f.label} is required.` };
    if (v) config[f.key] = v;
  }
  if (p.write) config.allow_write = !!form.allow_write;
  return { body: { provider, name, secret, config } };
}

export const statusOf = (c) =>
  !c.is_active ? { text: "Revoked", tone: "off" }
    : c.last_test_ok === true ? { text: "Working", tone: "ok" }
      : c.last_test_ok === false ? { text: "Test failed", tone: "bad" }
        : { text: "Not tested", tone: "warn" };
