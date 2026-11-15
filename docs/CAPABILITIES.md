# Business capabilities (Step 11)

Step 11 adds the first cross-system capabilities: useful answers built from several connected systems. They follow one rule: a capability
has no connector access and no authority of its own. It gathers facts only by submitting the ordinary domain tools to the execution
kernel as the calling user, so every read is permission-checked, policy-checked, rate-limited per connection and audited like any other
tool call, and a capability that never calls a write tool can never write.

## 11.1 Operations digest: "Show me what requires attention"
`POST /workspaces/{workspace_id}/capabilities/attention` (any member; humans only; it is a POST because it creates audited executions).
Code: `app/capabilities/attention.py` (service), `app/api/capabilities.py` (route). Deterministic: no model is involved, so the same
data always gives the same digest and every item says why it is there.

| Source | Reads (kernel tools) | Rule | Kind | Severity |
|---|---|---|---|---|
| calendar | `calendar.event.list` (next 24 h) | event overlaps the next one (back-to-back is not an overlap) | `calendar_conflict` | high |
| | | timed event starting within 2 h | `meeting_soon` | medium |
| | | other timed event within 24 h | `meeting_today` | low |
| project | `project.project.list`, `project.task.list` (<= 5 projects, 50 tasks each) | open task past due | `task_overdue` | high |
| | | open task due within 2 days | `task_due_soon` | medium |
| crm | `crm.lead.list` (50) | lead created in the last 7 days | `new_lead` | medium |
| email | `email.message.list` (unread INBOX, 25) | unread message | `unread_email` | low |

Items are sorted by severity, then time, then source. At most 10 items per source and 50 in total. Each item has `source`, `kind`,
`severity`, `title`, a fixed-text `reason`, `ref_tool` and `ref_id` (how to open it), an optional `when`, and `external_text`.

**Sources never fail the digest.** `sources[]` reports each source as `ok`, `not_permitted` (the caller lacks that permission; no
execution and no denial noise is recorded), `unavailable` (not connected, or misconfigured), `auth_failed`, `rate_limited` or `failed`,
plus `checked` and `truncated`. `partial` is true if any source is not ok or was truncated. No remote error text is ever returned.
A member (no business permissions by default) therefore gets an empty, honest digest; an admin or owner gets everything connected.

**Untrusted text.** Titles (email subjects, event titles, task and lead names) come from external systems. Connectors clean and cap them;
the digest flags them `external_text: true`, returns them as data, and nothing acts on them. Whatever reads a digest later (an agent, a
UI) must treat them as untrusted. `reason` is always fixed text from this module.

**Audit.** A digest creates one ordinary low-risk execution per read (about 5 to 10), requested by the caller. There is no
digest-level audit record yet.

### Limits and not done in 11.1
- Chat (Slack) is not included; reading every channel is expensive and noisy, and needs a policy for which channels matter.
- Thresholds (2 h, 24 h, 7 days, 2 days) are fixed constants, not workspace settings; Step 12 policies may make them configurable.
- Only the primary calendar, the inbox, and the first 5 Asana projects are looked at; a source that hit a limit is marked `truncated`.
- No per-endpoint rate limit beyond the per-connection outbound limit (a digest costs about 5 to 10 calls); endpoint limiting is Step 14.
- Tested with canned kernel handlers using the real tool schemas, not against live connectors (see the Step 10 status in CONNECTORS.md).
- Agents can call it as the `insight.attention.read` kernel tool since 11.2 (see below).

## 11.2 The digest as an agent tool: `insight.attention.read`
Code: `app/capabilities/attention_tool.py`, wired in `app/runtime.py`; the Business Insight agent (`insight_agent`) now carries the
`insight.attention` capability. Agents, Step 7 plans and Step 9 workflows reach the digest the normal way: run -> scope -> kernel -> audit.

- **Tool:** `insight.attention.read`, LOW risk, no approval, no input, needs `insight:read` (admin and owner only, via `insight:*`).
  Output is the 11.1 digest shape. One ordinary audited execution for the digest plus one per nested read.
- **No new authority.** The handler still reads only through the kernel, submitting the five fixed read tools. The identity is rebuilt
  from the execution context: the user's CURRENT membership permissions (removed or deactivated => the run fails closed with
  `DigestIdentityError`, no reads) plus the calling agent's scope. A nested read therefore needs the user's rights AND the agent's
  scope, and is recorded as requested by that user and agent. A demoted user gets an honest all-`not_permitted` digest.
- **Scope is not tool access.** `insight_agent` holds `email:read`, `calendar:read`, `crm:read` and `project:read` in scope so the
  digest can read on its behalf, but its tool rules name only `aceden.task.*` and `insight.attention.read`; the kernel still denies
  it `email.message.list` directly. Other agents (e.g. `ops_agent`) cannot name the tool.
- **Concurrency cap.** A digest occupies one of the kernel's 8 pool workers while its reads queue behind it, so at most 4 run at once;
  extra callers fail fast with `DigestBusyError` rather than risk a stall. The slot is always released.
- **Untrusted text.** Titles stay `external_text` data. Agent runs return only an outcome and execution id (6.4), never tool output,
  so nothing here feeds remote text to a model; anything that later does must treat it as untrusted.
- **Roles:** the only change is `insight:*` for admin (owner already has `*`). Members and viewers still use the 11.1 HTTP endpoint.

### Limits and not done in 11.2
- No workspace policy store exists yet, so nested reads use the default workspace policy; the tool accepts a policy provider for Step 12.
- A digest that exceeds its 120 s timeout is reported failed, but its worker thread finishes its reads in the background (same as any kernel tool).
- No digest-level audit record, no per-endpoint rate limit (Step 14), thresholds still fixed constants.
- Tested with canned handlers and the real tool schemas, not live connectors.

## 11.3 Sales: "Show me qualified opportunities"
`POST /workspaces/{workspace_id}/capabilities/opportunities` (any member; humans only; a POST because it creates audited executions) and
the kernel tool `sales.opportunity.list` (LOW risk, read-only, no approval, no input, needs `sales:read` = admin and owner via `sales:*`).
Code: `app/capabilities/opportunities.py` (service), `opportunities_tool.py` (tool), `app/api/capabilities.py` (route). Deterministic:
no model is involved, and every item says why it is listed. The `insight_agent` carries the `sales.opportunities` capability and may
name the tool (a dedicated Sales agent waits until there are sales actions for it to own).

**What "qualified" means.** The CRM connector exposes only name, email, company, lifecycle stage and created/updated times, so a lead is
qualified only if its CRM stage says so (lower-cased, punctuation removed). Nothing is scored from content and nothing is guessed.

| Tier | CRM stage | Rank |
|---|---|---|
| `opportunity` | `opportunity` | 1 |
| `sales_qualified` | `salesqualifiedlead` | 2 |
| `marketing_qualified` | `marketingqualifiedlead` | 3 |

Every other stage (lead, subscriber, customer, evangelist, other, missing or unknown) is not listed. Order: tier, then most recent
activity first (updated_at, else created_at; a lead with no usable date, or only a future date, comes last in its tier), then lead id.
`fresh` means activity in the last 30 days; `reason` is fixed text such as "Marked sales qualified; no activity in 30+ days".

**Limits and honesty.** At most 3 pages of 100 leads are read (more in the CRM => `truncated`, `partial`); at most 25 opportunities are
returned, while `counts` and `qualified_total` cover every qualified lead that was read. A failure on the first page returns an empty
list with a fixed `status` (`not_permitted`, `unavailable`, `auth_failed`, `rate_limited`, `failed`); a failure on a later page keeps
what was read, sets the status and marks `truncated`. No remote error text is returned. A member (no CRM permission) gets an empty,
honest `not_permitted` result with no executions and no denial noise. The lead's email is never returned: open the lead with
`ref_tool` / `ref_id` (`crm.lead.get`). Names and companies are external text: flagged `external_text`, data only, never acted on.
Each page read is one ordinary audited low-risk `crm.lead.list` execution requested by the caller (and the agent, for the tool).

### Shared composite-tool safety (refactored in 11.3)
The digest tool (11.2) and the opportunities tool share `app/capabilities/composite.py` and `kernel_read.py`: identity rebuilt from the
user's CURRENT membership plus the calling agent's scope, nested reads only through the kernel, and ONE worker cap (4 of the kernel's
8 pool workers) shared by all composite tools, wired once in `app/runtime.py`. In 11.2 the cap was per tool, which would have let two
tools together hold every worker; that is fixed. The digest's own behaviour is unchanged (its 23 tests pass untouched).

### Limits and not done in 11.3
- Stage text is the only signal. No lead scoring from activity, deal size or email content, and no per-workspace qualification rules
  (Step 12 policies may make tiers configurable). Only HubSpot lifecycle stages exist today; another CRM must map into the same stage text.
- Opportunities and deals as separate CRM objects are not read; the lead list is the only CRM read tool.
- No capability-level audit record, no per-endpoint rate limit (Step 14); each call costs 1 to 3 CRM reads against the per-connection limit.
- Tested with canned handlers and the real tool schemas, not live connectors (see the Step 10 status in CONNECTORS.md).

## 11.4 Business Intelligence: "What changed this week?"
`POST /workspaces/{workspace_id}/capabilities/changes` (any member; humans only; a POST because it creates audited executions) and the
kernel tool `insight.changes.read` (LOW risk, read-only, no approval, no input, needs `insight:read` = admin and owner via `insight:*`).
Code: `app/capabilities/changes.py` (service), `changes_tool.py` (tool), `app/api/capabilities.py` (route). Deterministic: no model is
involved and every item says why it is listed. The `insight_agent` carries the `insight.changes` capability and may name the tool; it
already held the four read scopes. The tool is wired on the same shared worker cap as the other composite tools (`app/runtime.py`).

**Window.** The last 7 days, `[now - 7 days, now]`, returned as `window_start` / `window_end`. Dates in the future are never evidence of change.

| Source | Kind | Rule |
|---|---|---|
| calendar | `meeting_held` | non-cancelled event that started in the window and has ended (all-day events by date) |
| calendar | counts only | `meetings_cancelled`: cancelled events that started in the window |
| project | `task_overdue` | open task whose due date fell inside the window (became overdue this week) |
| project | `task_completed` | complete task last modified in the window |
| project | `task_updated` | open task last modified in the window |
| crm | `lead_created` | lead created in the window |
| crm | `lead_updated` | lead created earlier, updated in the window (a new lead is never also counted as updated) |
| email | counts only | `emails_received` (INBOX), `emails_unread` (of those), `emails_sent` (SENT) |

A task yields one item with the precedence overdue > completed > updated. `counts` always holds all ten keys (zero when nothing
happened) and covers everything that was read, not only the capped items.

**Honesty about the evidence.** The connectors expose no change history, only timestamps. Asana has no completion time, so
`task_completed` means "complete, and last changed in the past 7 days" (the reason text says exactly that). Calendar events carry no
created or updated time, so the calendar reports meetings that took place, not edits. CRM `lead_updated` relies on the CRM's own updated
time. Nothing is compared against an earlier snapshot, so "removed" or "reopened" cannot be reported.

**Email is counts only.** No subject, sender or snippet is returned, because email is the most sensitive and most injectable text.
Gmail's `newer_than:7d` does the date filtering; a message whose Date header parses cleanly and falls outside the window is dropped too,
and an unparseable header is kept.

**Limits.** Items: at most 10 per source and 40 in total, newest first (then source, then id). Reads: calendar 2 pages of 50, project the
first 5 projects with one page of 100 tasks each (completed tasks included), CRM 3 pages of 100, email 2 pages of 25 per label; anything
left marks the source `truncated`. A first-read failure gives the source a fixed status (`not_permitted`, `unavailable`, `auth_failed`,
`rate_limited`, `failed`) and no data; a later failure keeps what was read, sets the status and marks it `truncated`. A broken source
never breaks the report and no remote error text is returned. A member (no read permissions) gets four `not_permitted` sources with no
executions and no denial noise. Titles and names are external text: flagged `external_text`, data only, never acted on. A full report
costs about 6 to 15 audited low-risk reads, each requested by the caller (and the agent, for the tool).

### Limits and not done in 11.4
- Fixed 7-day window; no custom range, no comparison with the previous week, no trends (would need stored snapshots).
- Chat is not included (same reason as 11.1: it needs a policy for which channels matter). No deal or revenue figures: not exposed.
- No capability-level audit record and no per-endpoint rate limit (Step 14).
- Tested with canned handlers and the real tool schemas, not live connectors (see the Step 10 status in CONNECTORS.md).
- SQLite only: the Postgres concurrency re-check stays on the Step 14 list.

## 11.5 Coordination: "Prepare the information needed for tomorrow's meetings"
`POST /workspaces/{workspace_id}/capabilities/meetings` (any member; humans only; a POST because it creates audited executions) and the
kernel tool `insight.meetings.read` (LOW risk, read-only, no approval, no input, needs `insight:read` = admin and owner via `insight:*`).
Code: `app/capabilities/meetings.py` (service), `meetings_tool.py` (tool), `app/api/capabilities.py` (route). Deterministic: no model.
The `insight_agent` carries the `insight.meetings` capability and may name the tool; it is wired on the shared worker cap.

**Which day.** "Tomorrow" is the next UTC calendar day. The calendar connector works in UTC and exposes no user time zone, so a workspace far
from UTC sees a shifted day. `day`, `window_start` and `window_end` are returned so this is never hidden.

**Per meeting** (non-cancelled; timed ones by start then id, all-day ones after them; at most 15, more marks the calendar `truncated`):
title, start, end, all_day, location, `attendee_count` (a count, never addresses), `conflicts_with` (timed events it overlaps, both ways;
back-to-back is not an overlap) and `related_leads`. `counts` has meetings, all_day, conflicts and with_related_leads.

**Related leads are possible matches by text only**, because the calendar exposes no attendee emails. A lead is listed when its full name
(first and last, each 2+ letters, whole words in order) or its company (4+ letters, whole words in order) appears in the event title. "Ann
Lee" does not match "Joann Lee". Name matches rank before company matches, then lead id; at most 3 per meeting. `reason` is fixed text
("Lead name appears in the event title") and `match` says `name` or `company`. The lead's email is never returned; open it with `ref_tool` /
`ref_id` (`crm.lead.get`). Private events show "(private)" and match nothing.

**Reads and failures.** One `calendar.event.list` for the day (50 events), then `crm.lead.list` (up to 3 pages of 100) only when there is at
least one meeting. A calendar failure gives no meetings and a fixed status. A CRM failure keeps the meetings with no related leads and
sets the crm status; a failure on a later CRM page keeps the leads already read and marks the crm `truncated`. Statuses are `ok`,
`not_permitted`, `unavailable`, `auth_failed`, `rate_limited`, `failed`; no remote error text is returned. A member gets `not_permitted`
with no executions and no denial noise. Titles, locations, names, companies and stages are external text: flagged, data only, never acted on.

### Limits and not done in 11.5
- Title matching only: no attendee emails, event descriptions or meeting history are read (`calendar.event.get` is not called, to keep
  free-text descriptions out of the briefing). A lead whose name is not in the title is not found.
- Nothing is prepared beyond what the read tools expose: no email threads, no tasks, no notes, no talking points.
- No custom date, no time zone setting, no capability-level audit record, no per-endpoint rate limit (Step 14).
- Tested with canned handlers and the real tool schemas, not live connectors (see the Step 10 status in CONNECTORS.md).
- SQLite only: the Postgres concurrency re-check stays on the Step 14 list.

## 11.6 Step 11 closing pass
No new capability. `tests/test_step11_hardening.py` (9 tests) locks the safety shape shared by all four capabilities so a later change cannot
weaken one quietly:
- **One shape.** `insight.attention.read`, `sales.opportunity.list`, `insight.changes.read` and `insight.meetings.read` are all LOW risk, no
  approval, no retries, strict empty input, 120 s timeout at most, no secret-looking output fields, and need `insight:read` (sales: `sales:read`).
- **One owner.** Only `insight_agent` carries the four capabilities and may name the tools. `ops_agent` and members cannot. The insight agent
  holds the read scopes the composites need but still cannot name `email.message.list`, `calendar.event.list`, `crm.lead.list` or
  `project.task.list` itself.
- **No new authority.** Capability modules import no connector, no HTTP client and name no write tool; the endpoints use only the caller's
  principal; `runtime.py` creates exactly one shared worker cap and wires all four tools on it.
- **One cap.** While the shared cap is held, all four tools fail fast (`DigestBusyError`) with no nested read; each releases its slot after use.
- **Fail closed.** A removed member gets `DigestIdentityError` from every tool and no nested read.
- **Journey.** Agent calls all four tools; every nested read is a LOW-risk execution attributed to the same user and `insight_agent`; no approval
  is created; each execution has an ordered event trail; remote text (task name, email subject) appears in the result as flagged data and
  never in the audit payloads.
Mutation checks: six rules broken once each (risk level, slot release, ops agent scope, write tool named in a module, membership check,
insight agent naming a direct read); one slipped (membership: the run still failed, with the wrong error), the test now requires the exact error.

### Step 11 status
**Built and tested:** operations digest, qualified opportunities, weekly changes, meeting briefing, each as an HTTP endpoint and a kernel tool
for agents; all deterministic and read-only; all reads go through the kernel with permission checks, per-connection rate limits and audit.
**Not done, and not claimed:**
- Nothing has run against a real service (see the Step 10 status in CONNECTORS.md): canned handlers with the real tool schemas only. Check
  Gmail `newer_than:7d` and your real HubSpot stage values before relying on 11.3 and 11.4.
- Evidence is weak by nature: stage text, timestamps and title matching only. No scoring, no comparison with earlier periods, no attendee data.
- No custom date range or time zone, chat is not read, no capability-level audit record, thresholds are fixed constants (Step 12 policies).
- No per-endpoint rate limit (Step 14). Titles, names and subjects are untrusted external text: anything that later feeds them to an LLM must
  treat them as data.
- SQLite only: the Postgres concurrency re-check stays on the Step 14 list.
