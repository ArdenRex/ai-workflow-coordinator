# Monitoring (Step 13)

## 13.1 Workspace execution monitoring (mini step 1)
- `GET /workspaces/{id}/monitoring/summary?window_seconds=3600|86400|604800` (default one day; anything else is `422 invalid_window`).
  Needs `audit:read` (admin and owner; members get 403, outsiders get the same 404 as every other workspace route, anonymous 401).
- **Read-only.** It never writes, retries, approves or runs anything; POST/PUT are 405 and a test checks no rows change.
- **Workspace-scoped:** every query filters on `workspace_id`; another workspace's executions, approvals and events never appear.
- **Content-free:** no tool input or output, no user ids, no error text beyond the short type/code the kernel already stores (cut to 120 characters).
- **What it reports** (all for the window, using each row's `created_at`, approvals by `decided_at`):
  - executions: total, count per status, failure rate (failed / (succeeded + failed), `null` if nothing finished), average and maximum run time in ms;
  - approvals: how many are pending now, the age of the oldest pending one, rejected and expired in the window;
  - denials: how many `execution.denied` events and the top reasons (fixed reason codes);
  - the five tools that failed most, and the ten most recent failures (id, tool id, short error, finish time);
  - `needs_attention`: true if anything failed in the window or a pending approval is older than 24 hours.
- Run times and denial reasons are read from at most 5000 rows; if more exist `duration_sample_capped` says so (reasons are then a sample, the denial total is exact).
- Code: `app/monitoring/service.py` (logic), `app/api/monitoring.py` (route). No migration, setting or dependency.
- Tests: `tests/test_monitoring.py` (15). Mutation check: removing a workspace filter failed the isolation test.
- **Not done (later Step 13 mini steps):** connector and workflow/agent-run health, approval-delay and latency percentiles, retries and idempotency review, an operational dashboard UI,
  alerting, backup and recovery. This is a point-in-time summary over existing tables, not a metrics store. SQLite only.

## 13.2 Connection and background-work health (mini step 2)
- `GET /workspaces/{id}/monitoring/health?window_seconds=3600|86400|604800` (default one day). Same access rules, window validation, read-only and content-free guarantees as 13.1
  (`audit:read`; admin and owner; members 403; outsiders the usual 404; anonymous 401; other workspaces never included; POST/PUT are 405).
- **Connections:** each *active* credential is classed from the last connection test already stored on it (nothing is tested by this call, so it makes **no external request**):
  `failing` (last test failed), `stale` (passed, but more than 7 days ago), `untested` (never tested), `ok`. The list is worst first (failing, stale, untested, ok), at most 50.
  Only the credential id, provider, label, state, test time and the stored safe code are returned: never the secret, the ciphertext or the config (base URLs included).
  Revoked credentials are not listed.
- **Agent runs (window):** counts per status, the top failure codes of failed runs, and `overdue_active` = queued/running/waiting-for-approval runs whose own `expires_at` has already passed
  (a snapshot of now, not windowed). No goals, results or user ids.
- **Workflow runs (window):** counts per status, top failure codes, the ten most recent failed runs (id, workflow key, code, finish time), `overdue_steps` = steps still RUNNING after their attempt
  deadline, and `steps_waiting_retry` = steps queued for a retry (both snapshots of now). No step results.
- `needs_attention` is true if any connection is failing, any agent run or workflow step is overdue, or any agent or workflow run failed in the window. A stale or untested connection alone does not set it.
- Code: `app/monitoring/health.py` (logic) and a second route in `app/api/monitoring.py`. No migration, setting or dependency.
- Tests: `tests/test_monitoring_health.py` (10). Mutation checks: removing the workspace filter from the overdue agent-run count, the overdue-step count or the retry count each failed a test (a first check missed one, so `test_overdue_and_retry_snapshots_ignore_other_workspaces` was added).
- **Not done (later Step 13 mini steps):** latency percentiles and approval-delay trends, schedules/events health, retries and idempotency review, a dashboard UI, alerting, backup and recovery.
  Overdue only reports what is stuck; it does not expire, retry or cancel anything. SQLite only.

## 13.5 Latency percentiles and approval-decision delay (mini step 5)
Added to `GET /workspaces/{id}/monitoring/summary` (same access rules; read-only, workspace-scoped, content-free). No new route, migration, setting or dependency.
- `executions.p50_duration_ms` and `p95_duration_ms`: nearest-rank percentiles of the same run-time sample as the average and maximum (always an observed value; `null` if nothing ran).
- `approvals.decided_in_window`, `avg_decision_seconds`, `p95_decision_seconds`: approvals a human approved or rejected in the window, measured from request to decision. Expired approvals are not decisions and are excluded; no decider identity is returned.
- `approvals.decision_sample_capped`: true if more than 5000 decisions existed (the figures then use the first 5000).
- Existing fields are unchanged; the new ones are additive. Tests: `tests/test_monitoring_latency.py` (19 cases). Mutation check: removing the workspace filter on the decision query failed the isolation test.
- **Not done:** per-tool percentiles, trends over time, schedule and event health, a dashboard UI, alerting. Percentiles are point-in-time over existing tables, not a metrics store. SQLite only.

## 13.6 Schedule and event health (mini step 6)
Added to `GET /workspaces/{id}/monitoring/health` (same access, window, read-only, workspace-scoped and content-free rules as 13.2). No new route, migration, setting or dependency; new keys are additive.
- `schedules`: total, enabled, disabled; `auto_disabled` (disabled by the scheduler with a stored fixed reason, as opposed to switched off by a person) with the reasons; `overdue` (enabled and `next_fire_at` more than 5 minutes in the past, a snapshot of now) with the ten most overdue (id, workflow key, interval, due time); total skipped slots.
- `events`: received and dispatched in the window, how many were truncated (matched more workflows than one dispatch could start), and `stuck_undispatched` (not dispatched more than 5 minutes after arrival; a snapshot of now, not windowed).
- `needs_attention` is now also true for any overdue schedule, any auto-disabled schedule, or any stuck event. A schedule a person disabled never triggers it.
- Never returned: event types, event refs, payloads, user ids. Report-only: nothing is fired, retried or dispatched by this call.
- Tests: `tests/test_monitoring_schedules_events.py` (7). Mutation checks: removing the workspace filter on the event counts and on the overdue-schedule query each failed the isolation test.
- **Not done:** per-tool percentiles and trends, a dashboard UI, alerting. SQLite only.

## 13.7 Alerts (mini step 7)
- `GET /workspaces/{id}/monitoring/alerts?window_seconds=3600|86400|604800` (default one day). Same access (`audit:read`: admin and owner), window validation, read-only (POST/PUT 405), workspace-scoped and content-free rules as 13.1/13.2. No migration, setting or dependency.
- A **fixed set of 12 rules** is evaluated against the workspace's summary (13.1/13.5) and health (13.2/13.6) reports. Nothing is stored, sent or changed: it only reports what is firing now.
- Each alert has `rule`, `severity` (`critical` | `warning`), the measured `value`, the `threshold` it crossed, and fixed message text. Alerts are sorted critical first, then by rule name; `highest_severity` is `null` when nothing fires.
- Rules (threshold): `execution_failure_rate` (>= 25% warning, >= 50% critical, only with at least 4 finished runs), `approval_waiting_too_long` (>= 1 day warning, >= 3 days critical), `many_denials` (>= 20), `slow_executions` (p95 >= 30 s), `connection_failing` (any, critical), `agent_runs_overdue`, `agent_runs_failed`, `workflow_steps_overdue`, `workflow_runs_failed`, `schedules_overdue`, `schedules_auto_disabled`, `events_stuck` (each: any).
- Never returned: tool names, ids, error text, payloads, user ids.
- Tests: `tests/test_monitoring_alerts.py` (8), including a check that the rule count stays honest. Mutation checks: disabling the connection rule and loosening the failure-rate threshold each failed a test.
- **Not done:** per-workspace thresholds, notifications (email, chat, webhook), acknowledgement or snoozing, alert history, and the dashboard UI. Thresholds are constants in `app/monitoring/alerts.py`. SQLite only.

## 13.8 Operations dashboard (mini step 8)
- `GET /workspaces/{id}/monitoring/overview?window_seconds=3600|86400|604800`: the 13.1/13.5 summary, the 13.2/13.6 health report and the 13.7 alerts in one response (computed once, so they agree). Same access (`audit:read`), window validation, read-only, workspace-scoped and content-free rules. No migration, setting or dependency.
- `GET /dashboard`: a static page (three fixed files in `app/monitoring/dashboard_assets/`: HTML, CSS, JS; no framework, no build step, no external requests). The page holds **no data and no secrets**: the user types a workspace id and their own access token, and the page calls the overview endpoint with it. Access control is therefore the API's. The token is kept in a JS variable only (no cookies, no local or session storage) and requests are sent with `credentials: "omit"`.
- Hardening: strict `Content-Security-Policy` (scripts and styles from this origin only, no inline script or style, no framing, `connect-src 'self'`), `nosniff`, `no-store`, `no-referrer`, `X-Frame-Options: DENY`. Assets come from a fixed allowlist, never from a request path. The script writes every server value with `textContent`, so a tool name like `<img onerror=...>` shows as plain text (checked in a real browser).
- Shows: alerts (critical first), execution counts, rates and latency, approvals and decision time, connections, agent and workflow runs, schedules and events, recent failures. Manual refresh only (press Load again).
- Tests: `tests/test_dashboard.py` (8): permissions, overview equals the three separate reports, workspace isolation, headers, no inline script or dangerous sinks, JS parses with node. Mutation-free area; the browser render check was run by hand with mocked requests.
- **Not done:** auto-refresh, charts or trends, login screen (the user pastes a token), a dashboard for non-admin members, notifications. Serving `/dashboard` from the API origin means a separate frontend origin would need CORS config. SQLite only.
- **Step 13 status:** monitoring, health, retries and idempotency review, backup and recovery, percentiles, schedule and event health, alerts and the dashboard are done. See "Not done" lists above for what remains open (Postgres backup procedure, notifications, atomic cap check for Step 14).
