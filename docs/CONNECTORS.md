# Connectors (Step 3)

Connectors are the only code that talks to external systems, and they are only ever
reached through kernel tools (`ToolExecutionService`). Aceden is one connected system;
the AI OS imports none of its code.

## Layers
    kernel tool (aceden.task.list)  ->  provider(workspace_id)  ->  AcedenConnector  ->  HttpConnector  ->  HTTPS
| File | Role |
|---|---|
| `connectors/base.py` | `BaseConnector` contract; `HttpConnector` with timeouts, error mapping, size cap, no redirects, safe paths, GET-only retries |
| `connectors/errors.py` | Typed errors with generic messages (no bodies, no credentials) |
| `connectors/aceden/` | Aceden connector (X-API-Key), schemas (output allow-lists), kernel tool definitions, factory |
| `connectors/check.py` | `python -m app.connectors.check` connection test (status only, exit code 0/1) |

## Configuration (env)
    ACEDEN_BASE_URL=https://your-aceden-host
    ACEDEN_API_KEY=...            # set both or neither; https required in production
    ACEDEN_TIMEOUT_SECONDS=10
The key is a `SecretStr`: it never appears in `repr`, logs, audit events, errors or tool descriptions.
Env credentials are a single-tenant/dev convenience: `bound_provider(workspace_id, connector)`
lets only that one workspace use them. Step 4.5 adds encrypted per-workspace connections (below).

## Aceden tools (read-only, low risk, permission `task:read`)
- `aceden.task.list` — filters: status, priority, assignee; `skip`, `limit` (max 200)
- `aceden.task.get` — `task_id`
Outputs are allow-listed (id, title, description, assignee, deadline, priority, status, timestamps);
source message text and Aceden-internal workspace ids are never exposed.

## Adding a connector
1. Subclass `HttpConnector` (override `_auth_headers`, `probe_path`).
2. Define input/output schemas (extra=forbid inputs, allow-listed outputs).
3. Expose `xxx_tool_definitions(provider)` with the correct permission and risk level
   (writes: MEDIUM/HIGH, never retried, approval per policy).
4. Test with `httpx.MockTransport`, plus a kernel-level test (permissions, workspace credentials).

## Per-workspace connections (Step 4.5)
    kernel tool -> provider(workspace_id) -> WorkspaceConnectors -> credentials (encrypted, workspace-scoped) -> spec.build -> connector
- `connectors/registry.py`: provider -> `ConnectorSpec`. Adding a connector = one spec (+ its tools). Providers without a spec
  can store credentials but cannot be tested or used yet.
- `connectors/workspace.py`: `WorkspaceConnectors.provider("aceden")` returns the `provider(workspace_id)` callable the tools already
  use. It opens its own short-lived DB session (handlers run on pool threads), reads only that workspace's credential, checks
  it is still active on every call, caches one connector per credential (rebuilt after rotation, never served after revocation).
  Exactly one active credential per provider per workspace is expected; several -> refused, not guessed.
- `register_workspace_tools(registry, connectors)` registers the tools wired this way. Env-based Aceden settings remain as a
  dev convenience (`bound_provider`) and are untouched.
- **SSRF guard** (`connectors/netguard.py`): users supply `config.base_url`, so every host must resolve ONLY to globally routable
  addresses (blocks loopback, RFC1918, link-local/metadata, CGNAT, multicast, `localhost`/`.internal`/`.local`). Checked at creation
  (shape + literal IPs, no DNS) and again with DNS at every connector build and test. `ALLOW_PRIVATE_CONNECTOR_HOSTS=true` is dev-only.
  Known limit: resolve-then-connect leaves a DNS-rebinding window; closing it needs a pinned transport or egress proxy (Step 14).
- **Connection test:** `POST /workspaces/{id}/credentials/{cid}/test` (`connection:test`, admin/owner). One outbound call,
  cooldown `CONNECTION_TEST_COOLDOWN_SECONDS` (default 5, 429 inside it). Stores `last_tested_at/last_test_ok/last_test_message`
  on the credential (message is a safe connector code only), writes a `connection.tested` audit event, returns capabilities on success.
  A blocked or misconfigured host is reported as a failed test, never as an outbound call.

## Known limits
- Aceden write tools are intentionally not built yet (Step 10/12 decide approval and autonomy rules).
- No scheduled connection monitoring yet (status is updated by explicit tests; periodic checks arrive with Step 9/13).
- No HTTP endpoint submits kernel executions yet; tools are reachable through `ToolExecutionService` (agents/orchestration, Steps 5-7).

# Business connectors (Step 10)

Step 10 connects the first business systems. It is built so that adding one connector never changes the safety model.

## Plan
- 10.1 Connector kit, business domains, domain-level provider resolution (no provider yet, no migration) — DONE
- 10.2 CRM domain interface and HubSpot connector (read tools) — DONE
- 10.3 Chat (Slack) and project-management (Asana) connectors (read tools) — DONE
- 10.4 Calendar (Google Calendar) and email (Gmail) read connectors with OAuth token refresh — DONE
- 10.5 Write tools (crm.lead.create, email.draft, email.send, calendar.meeting.create, chat.message.post), all approval-gated
- 10.6 Step 10 hardening: outbound call limit, cross-connector invariants, audited end-to-end journey — DONE

## 10.1 The kit (`app/connectors/kit.py`, `app/connectors/domains.py`)
- **Auth schemes.** `KitConnector` declares `auth_kind` = `bearer`, `header` (a named header) or `basic`. Secrets are
  validated before any request (non-blank, <= 4096 chars, no control characters or spaces, `user:password` for basic),
  so a stored value can never inject a header. Header names are validated at class creation (no `Authorization`, `Host`,
  `Cookie`, `Content-Length` and similar). The secret never appears in `repr`.
- **`build_config`.** The one place a stored credential becomes a `ConnectorConfig`: https in production, the DNS-checked
  SSRF guard, bounded timeout. New connectors use it instead of copying the Aceden builder (Aceden is untouched).
- **Untrusted external text.** `clean_text` / `ExternalText(n)` strip control, zero-width and bidi-override characters and
  cap length; non-strings are rejected, never coerced. Every free-text field a business connector returns uses it.
- **`paginate`.** Bounded cursor pagination (max 20 pages, max 1000 items), loop detection, and an honest `truncated` flag.
- **Domains.** Five domains: `email`, `calendar`, `crm`, `chat`, `project`, each with a fixed verb list. Tools are
  domain-level (`crm.lead.create`), so agents and workflows never name a vendor. `business_tool` is the only builder:
  read -> LOW, no approval, retries allowed; write -> MEDIUM/HIGH, approval always, never retried; send (`email.send`,
  `chat.post`) -> HIGH, approval always, never retried. Permission is always `<domain>:<verb>`.
- **Who may use them.** All domain permissions (`crm:*`, `email:*`, ...) are held by ADMIN and OWNER only. Members and
  viewers have none, and an agent additionally needs the permission in its scope. This is deliberately conservative; Steps
  11/12 assign them more widely. Approval is forced for every write until the Step 12 policy work.
- **Which system serves a domain.** `ConnectorSpec.domains` says what a provider serves. `WorkspaceConnectors.for_domain`
  resolves the ONE active connection for the domain in the calling workspace: none or several is refused, never guessed;
  revocation and rotation take effect on the next call, and other workspaces never resolve.

Not in 10.1: any real provider, any write tool, OAuth. Everything is tested with in-memory fakes.

## 10.2 CRM domain and HubSpot (`app/connectors/crm/`)
- **Vendor-neutral tools:** `crm.lead.list` (limit 1-100, optional cursor) and `crm.lead.get` (numeric `lead_id`). Both are
  low risk, need `crm:read` (admin/owner only, see 10.1) and no approval. Inputs are strict: a cursor or id that could alter
  the request path or query is rejected before any call.
- **Interface:** a connector serves the domain by implementing `CrmConnector` (`list_leads`, `get_lead`). If the single
  connected CRM does not, the tool fails with `ConnectorConfigError` instead of guessing.
- **HubSpot** (`provider: "hubspot"`, bearer private-app token, `config.base_url` required, e.g. `https://api.hubapi.com`):
  contacts are leads. Only GET requests are ever sent. Archived records are skipped, a page never exceeds `limit`, and the
  next-page cursor is validated. `get_lead` rejects an answer for a different id.
- **Allow-list:** id, first/last name, email, company, lifecycle stage, created/updated times. Phone numbers, addresses,
  notes, owners and every other remote field are neither requested nor returned. Free text is cleaned and length-capped.
- **Wiring:** `register_workspace_tools` registers the CRM tools next to the Aceden tools, resolved per workspace through
  `for_domain("crm")`: one active CRM connection per workspace, none or several refused, revocation and rotation immediate.
- **Connection test** works for HubSpot through the existing endpoint and lists `lead.list`, `lead.get`.
- **Changed existing test:** `test_provider_without_connector_is_stored_but_cannot_be_tested` used `hubspot` as its example of
  a provider with no connector; it now uses `mailchimp`.
- **Not verified against real HubSpot.** The request and response shapes follow HubSpot's CRM v3 objects API as I know it and are
  tested against an in-memory fake only. Run the connection test and one list call against a HubSpot sandbox before relying on it.
- Not in 10.2: search, writes (10.5), OAuth, custom properties, other CRMs.

## 10.3 Chat (Slack) and project (Asana) (`app/connectors/chat/`, `app/connectors/project/`)
Same pattern as CRM: vendor-neutral tools, a domain interface (`ChatConnector`, `ProjectConnector`), strict inputs, allow-listed
outputs with cleaned and capped external text, GET-only connectors, resolved per workspace through `for_domain`. All tools are low
risk reads; permissions `chat:read` and `project:read` are admin/owner only (10.1).

**Chat tools:** `chat.channel.list`, `chat.message.list`. **Slack** (`provider: "slack"`, bot token, `config.base_url` e.g.
`https://slack.com/api`):
- Only public channels exist for these tools: listing asks for `public_channel` and drops anything private, DM, group DM or archived
  even if the remote returns it; before history is read the channel is fetched and must be a public channel, so a private
  channel, DM or group id looks like a missing channel and `conversations.history` is never called for it.
- Slack's HTTP-200 `{"ok": false, "error": ...}` is mapped to fixed connector errors (auth, not found, rate limited, bad
  response); the remote error text is never echoed. Join/leave/topic style messages are skipped.
- Messages return only ts, author user id, text (cleaned, 1000 chars) and thread ts: no names, profiles, files, reactions or
  blocks. Message text is untrusted user content; it is returned as data and nothing in the system acts on it.

**Project tools:** `project.project.list`, `project.task.list`, `project.task.get`. **Asana** (`provider: "asana"`, personal
access token, `config.base_url` e.g. `https://app.asana.com/api/1.0`, `config.workspace_gid` digits, required and validated at
credential creation):
- A token can often reach several Asana workspaces, so every read is scoped to the configured one: project lists are filtered
  by it, a project is fetched and checked (same workspace, not archived) before its tasks are listed, and a task of another
  workspace looks like "not found".
- Tasks return id, name, completed, due date, assignee name and modified time; `task.get` adds notes (2000 chars). Followers,
  custom fields, links and everything else are neither requested nor returned. Open tasks only unless `include_completed`.

**Kit change:** `ConnectorSpec.check_config` lets a provider add create-time config rules (used for `workspace_gid`).
External booleans and integers are strict types, so a remote's `"yes"` or `"10"` is a bad response, not silently coerced.

**Not verified against the real services.** Request and response shapes follow Slack's Web API and Asana's REST API as I know
them and are tested only against in-memory fakes. Run the connection test and one read per tool against a Slack test workspace
and an Asana test workspace before relying on them. Not in 10.3: posting messages, task writes (10.5), search, OAuth, private
channels or DMs.

## 10.4 OAuth refresh, email (Gmail) and calendar (Google Calendar) (`app/connectors/oauth.py`, `email/`, `calendar/`)
Same pattern as before: vendor-neutral domain tools, strict inputs, allow-listed outputs with cleaned and capped external text,
resolved per workspace through `for_domain`. All tools are low-risk reads; `email:read` and `calendar:read` are admin/owner only.
Gmail and Google Calendar are two providers (`gmail`, `google_calendar`), each with its own credential and read-only grant.

**OAuth (`oauth.py`).** The one stored secret is `client_id:client_secret:refresh_token`. Config: `base_url` (e.g.
`https://gmail.googleapis.com` or `https://www.googleapis.com`) and optional `oauth_url` (token endpoint, default Google's;
same https rule and SSRF guard as `base_url`; the key avoids the word "token" because the credential store rejects secret-looking
config keys).
- Access tokens live in memory only and are refreshed 60 s before expiry, one refresh at a time across threads.
- If the API rejects a token older than 30 s, it is dropped and the request retried once with a fresh one. A freshly issued
  token that is rejected is not refreshed again (a real permission problem).
- After a failed refresh no new call is made to the identity provider for 30 s, so a revoked grant cannot be hammered.
- Token responses are strictly validated (token shape, `Bearer`, integer `expires_in` 1..86400, size cap, no redirects).
- Read-only is enforced: if the token response lists scopes, anything beyond `gmail.readonly` (Gmail) or the two read-only
  calendar scopes (plus openid/email/profile) is refused before any API call. If the response lists no scopes this cannot be checked.
- A rotated refresh token is kept in memory only; persisting rotation is not built (Google does not rotate them).
- Errors are fixed text; the token endpoint's body and every secret are never echoed.

**Email tools:** `email.message.list` (label INBOX/SENT/STARRED/IMPORTANT, `unread_only`, optional query <= 200 chars, limit <= 25) and
`email.message.get` (hex message id). Lists return id, thread id, sender, subject, date, snippet, unread flag. `get` adds To, Cc
and a plain-text body (HTML stripped as a fallback, 4000 chars, `body_truncated` flag). Attachments are only noticed
(`has_attachments`), never read; no other headers or labels are returned. A reply for a different id is "not found".
Email text is untrusted content: returned as data, nothing acts on it.

**Calendar tools:** all on the PRIMARY calendar only. `calendar.event.list` (window <= 31 days), `calendar.event.get`,
`calendar.availability.read` (window <= 14 days; merged busy intervals, no titles; free/transparent and cancelled events ignored;
all-day events count as busy for whole UTC days). Times need a UTC offset and are returned in UTC. Attendees are a count, never
addresses; private and confidential events show "(private)" with no location or description; links and organizer are not returned.

**Existing tests changed:** two assertions in `tests/test_connector_kit.py` assumed no email or calendar provider existed; they
now expect `gmail` and `google_calendar`.

**Not verified against real Google.** Request and response shapes follow Gmail API v1, Calendar API v3 and Google's OAuth token
endpoint as I know them and are tested only against in-memory fakes. Run the connection test and one read per tool with a test
Google account before relying on them. Not in 10.4: the OAuth consent flow itself (you obtain the refresh token outside the
system for now), Microsoft 365, writes and sending (10.5), free-text search beyond the Gmail query, shared or secondary calendars,
persisting rotated refresh tokens.

## 10.5 Write tools (`app/connectors/writes.py` plus `*_write_tool_definitions` in each domain)
Five tools, each with its own permission, all admin/owner only, all approval-gated by the kernel and never retried:

| Tool | Permission | Risk | What it does |
|---|---|---|---|
| `crm.lead.create` | `crm:write` | medium | Creates a HubSpot contact (email required; first/last name, company optional) |
| `email.draft` | `email:draft` | medium | Saves a Gmail draft; nothing is sent |
| `email.send` | `email:send` | high | Sends a plain-text email (<= 5 `to`, <= 5 `cc`, no bcc, body <= 10000) |
| `calendar.meeting.create` | `calendar:write` | medium | Creates an event on the primary calendar (<= 8 h, <= 10 attendees) |
| `chat.message.post` | `chat:post` | high | Posts text (<= 2000) to one public Slack channel |

**Two opt-ins for any write.** (1) The credential config has `"allow_write": true` (strict boolean, checked at creation). Without it every
write method refuses before any request, and the token endpoint is not even called. (2) For Google, the grant must stay inside the read
scopes plus the write allow-list (Gmail: `gmail.compose`, `gmail.send`; Calendar: `calendar.events`). Broader scopes (`gmail.modify`,
`mail.google.com`, full `calendar`) are always refused. On a connection without `allow_write`, a grant that carries write scopes is refused
even for reads. Write capabilities (`draft`, `send`, `meeting.create`, `lead.create`, `message.post`) appear in the connection test only when `allow_write` is on.

**What a human approves is what happens.** `email.draft` and `email.send` share one input model; the kernel binds the approval to the exact
normalised input. Inputs are strict: addresses are plain `user@host` (no display names), subjects, names, titles and locations are
single-line with no control characters, bodies reject control and bidi/zero-width characters, duplicate or overlapping recipients are
refused. Slack text containing `<!` (channel, here, everyone, subteam mentions) is refused; messages are sent with parse none, no
link-name expansion and no unfurling, and only after confirming the channel is public. Calendar invitations are emailed by Google only when
`notify_attendees` is true (default false). Remote replies are checked against what was asked (created contact has the requested
email, Slack channel matches, event not cancelled, ids well-formed).

**Behaviours to know.** A request the remote rejected for authentication (401/403) after our token is older than 30 s is retried once with a
fresh token; a rejected request was not executed, so this cannot duplicate a send. Any other failure is never retried: if a send times out after
Google accepted it the result is unknown, so check the Sent folder before re-approving. An approved write on a connection without
`allow_write` fails after approval with a configuration error and sends nothing (the kernel cannot see connector config before approval).
Idempotency keys on the kernel submit protect against duplicate submissions only.

**Not verified against real services.** Request and response shapes (Gmail drafts/send, Calendar insert, HubSpot contacts, Slack chat.postMessage)
follow the vendors' APIs as I know them and are tested only against in-memory fakes. Before relying on them, use test accounts: one draft, one
send to yourself, one event without notification, one contact, one post in a test channel. The Slack bot also needs the `chat:write` scope,
which cannot be checked from here. Not in 10.5: recipient allow-lists and send limits (Step 12 policies), HTML email, attachments, Bcc,
replies/threads, updating or deleting anything, Asana task writes, Microsoft 365, the OAuth consent flow.

## 10.6 Step 10 hardening (`app/connectors/ratelimit.py`, `tests/test_step10_hardening.py`)
**Outbound call limit.** Each connection (one cached connector per credential) has a sliding one-minute window,
`CONNECTOR_MAX_CALLS_PER_MINUTE` (default 120, 0 = unlimited). Over the limit, the call is refused locally with `connector_rate_limited`
(and a retry-after) and NO request is made, so a runaway agent or workflow cannot hammer a customer's CRM, mailbox or Slack. It counts
logical requests (a retried GET counts once), covers reads and writes, and for Google is checked before any token refresh. It is
in-process: with several server processes each keeps its own window, so the real ceiling is per process. Editing a credential builds a new
connector and so resets its window.

**Invariants over every registered tool** (so a new connector cannot quietly weaken the model): every domain has a connector; tool ids are
well formed and use `<domain>:<verb>` permissions; read tools are low risk with no approval; write and send tools always need approval,
are never retried, and send/post tools are high risk; every input schema forbids extra fields; no input or output field is named like a
secret, token or password.

**End-to-end journey test:** connect (credential with `allow_write`), connection test lists write capabilities, request `email.send`,
it stops for a human with nothing sent, a second user approves, it executes once, and the audit trail shows
created, approval requested, approved, started and executed in order with no message text and no secrets.

## Step 10 status (honest)
Built: CRM (HubSpot), chat (Slack), project (Asana, read only), email (Gmail), calendar (Google Calendar), OAuth refresh, five approval-gated
write tools, per-connection outbound limit. 1738 tests pass; every safety rule above was mutation-checked.

Not done, and not claimed:
- **No connector has run against a real service.** All tests use in-memory fakes built from the vendors' documented shapes. Before any
  customer use, run the connection test and one read and one write per tool against test accounts (HubSpot, Slack, Asana, Google).
- **No OAuth consent flow.** The refresh token is obtained outside the system and stored as `client_id:client_secret:refresh_token`.
- **Webhooks and inbound events from connectors** are not built (Step 9 event intake stays internal).
- **No Microsoft 365, no Asana writes, no recipient allow-lists or send limits** (those are Step 12 policies).
- **Everything ran on SQLite**; the Postgres concurrency re-check, rate-limit behaviour across several processes, and load behaviour are Step 13/14 work.
- Message, email and event text is untrusted external content. It is returned as data and nothing acts on it, but an agent that reads it
  can still be influenced; Step 11/12 policies must treat it as untrusted.
