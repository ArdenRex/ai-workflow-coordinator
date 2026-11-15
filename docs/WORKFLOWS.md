# Workflows and events (Step 9)

Makes work repeatable and proactive. A workflow is a stored template of agent steps plus the triggers that may start
it. Nothing here adds authority: every step will run as an ordinary Step 6 agent run, so the starting user's
permissions, the agent's scope and tool rules, workspace policy, approvals and audit all still apply, and the kernel
stays the only place work executes. A trigger says WHEN a run may be requested, never what it may do.

## Substeps
- 9.1 Workflow definition model (pure, no DB/LLM) — DONE
- 9.2 Workflow persistence: versioned definitions, runs and step records, migration 0010, state machines, retry bookkeeping, content-free audit — DONE
- 9.3 Workflow engine: drive a run through agent runs, retries, timeouts, approval pause/resume — DONE
- 9.4 Events: internal event intake, trigger matching, idempotent starts — DONE
- 9.5 Scheduling: interval triggers fired by a bounded tick, resumable after restart — DONE
- 9.6 HTTP API + end-to-end safety tests, close Step 9 — DONE

## 9.1 The definition (`app/workflows/definition.py`)
`WorkflowDefinition(id, name, steps, version, description, triggers)` is immutable.

- Steps reuse the plan rules by building a `PlanStep` and `ExecutionPlan` (`to_plan()`): slug ids, up to 20 steps,
  at most 5 dependencies, instructions up to 1000 plain characters, unique ids, no cycles. Error codes are the same.
  `WORKFLOW_MAX_STEPS` (default 10, 1-20) is the per-system ceiling checked by `validate_for_workspace`, which also
  checks every agent is registered.
- Retry policy per step: 1-5 attempts, `fixed` or `exponential` backoff, delays up to 3600 s, a cap
  (`max_delay_seconds`). Deterministic, no jitter. `should_retry(failed)` and `delay_after(failed)` are pure
  functions the 9.3 engine will use. The default is one attempt (no retry).
- Timeout per step: 1-3600 s (default 120, the agent-run default).
- Failure is fail-closed, as in plans: a failed, skipped or cancelled step never unblocks a dependent.
- Triggers (1-5, unique, default manual only): `manual`; `event` with a dotted lowercase `event_type` such as
  `lead.created` (up to 4 parts); `schedule` with `interval_seconds` 60 s to 30 days. No cron syntax (no new
  dependency, simpler to bound).
- No secrets: names, descriptions and instructions that look like credentials are rejected (`secret_detected`)
  without echoing the text. This reuses the Step 8 filter.
- Names are one line up to 100 characters; descriptions are up to 300 plain characters.
- `from_dict` is a strict parser for untrusted input: unknown keys, missing fields and wrong types are rejected (a
  bool is not an int), and list sizes are bounded before any item is parsed. Error messages never echo input.
- `digest()` is a SHA-256 over the canonical behaviour (id, version, steps, retry, timeouts, triggers), ignoring
  name, description and dependency order, so runs can later bind to the exact definition they started from.
- The module is pure (no database, LLM, network, clock or randomness) and a test enforces it.

No migration, no new dependency, no routes in 9.1.

## 9.2 The store (`app/workflows/store.py`, `app/models/workflows.py`, migration 0010)
Tables `workflow_definitions`, `workflow_runs` and `workflow_run_steps`. `WorkflowService` executes nothing: the
engine (9.3) will drive it, the same way `PlanService` is driven by the orchestrator.

    definition:  ACTIVE --archive--> ARCHIVED
    run:         PENDING --start--> RUNNING --complete--> SUCCEEDED | FAILED        cancel: PENDING/RUNNING -> CANCELLED
    step:        PENDING -> RUNNING <-> WAITING_APPROVAL -> SUCCEEDED | FAILED | CANCELLED
                 RUNNING --fail_attempt--> PENDING (+ next_attempt_at) while attempts remain, else FAILED
                 PENDING -> SKIPPED | CANCELLED

- **Versions are immutable.** A new key starts at version 1; each change is the next version (no gaps, no edits).
  Re-sending the latest version unchanged is a no-op; the same version with different content is a conflict.
  `WORKFLOW_MAX_DEFINITIONS` (default 100) bounds distinct workflows per workspace. Definitions store their text
  (the template); it was secret-filtered on the way in. The stored JSON is re-checked against its digest every time it
  is loaded, so a tampered definition fails closed.
- **Archiving** a version stops new runs from it (a run without an explicit version uses the newest ACTIVE one).
  Existing runs are unaffected.
- **Runs bind to the exact version and digest** they started from. Runs and steps store ids, states, attempt counts,
  timing and fixed codes, never instructions or inputs; results are redacted and capped (16 KB).
- **Triggers:** a run may only be started by a trigger its definition declares. Event and schedule starts need a
  `trigger_ref` (event id or schedule slot); the same ref for the same workflow can start at most one run
  (database-enforced), so redelivery or a repeated tick cannot double-start. `idempotency_key` works as for plans.
  `WORKFLOW_MAX_ACTIVE_RUNS` (default 20) bounds pending/running runs per workspace.
- **Retries:** the step row holds `attempts`, `max_attempts` (copied from the policy) and `next_attempt_at`.
  `fail_attempt` returns the step to PENDING with the policy's delay while attempts remain and the run is not being
  cancelled; otherwise the step FAILS. `begin_step` refuses a step whose delay has not elapsed or whose attempts are
  used up, and `due_steps` lists what may start now. All of it lives in the database, so a restarted process resumes
  without any in-memory state. Each attempt is bound to its own agent run (one agent run serves at most one step).
- **Timeouts:** `deadline_at` is set when an attempt starts; enforcing it is the engine's job (9.3).
- **Authority:** defining and archiving need `agent:manage` (admin+); starting a run needs `agent:run`; definitions
  are readable by anyone who may run or manage. A run belongs to the user who created it: they see and drive it;
  `agent:manage` sees every run and may cancel but not drive. Agent principals can do nothing here, even with a broad
  scope (a test proves it). Invisible and missing records are indistinguishable.
- **Audit:** `workflow.defined`, `workflow.archived`, `workflow.run_created|started|succeeded|failed|cancel_requested|
  cancelled` and `workflow.step_started|waiting|resumed|succeeded|failed|cancelled|skipped|retry_scheduled`. Payloads
  carry ids, digests, states, attempt numbers, delays and codes only.
- Everything ran on SQLite; the Postgres concurrency re-check stays on the Step 14 list.

## 9.3 The engine (`app/workflows/engine.py`)
`WorkflowEngine.drive(user, run_id)` runs a stored run through ordinary agent runs and returns `completed`,
`cancelled`, `paused_approval`, `in_flight` or `waiting_retry` (with `retry_at`). It has no authority of its own: every
step is an agent run, so the user's permissions, the agent's scope and tool rules, policy, approvals and audit apply.

- **Instructions come from the stored definition** the run is bound to (digest re-verified before anything moves), so a
  caller cannot substitute text; a tampered definition runs nothing. Only the creator drives; admins can cancel.
- **Order:** dependencies are checked in the engine (`due_steps`) and again in the store (`begin_step`). A failed,
  skipped or cancelled dependency never unblocks anything; its dependents are skipped and independent branches go on.
- **Retries** use the definition's policy (max 5 attempts, fixed or exponential delay, capped) and happen only when the
  cause is transient (`llm_rate_limited`, `llm_timeout`, `llm_unavailable`, `run_expired`, `step_timeout`) AND the
  failed attempt made no tool call. A step that already touched a tool is never retried automatically, so a retry cannot
  repeat a side effect. Approval rejection/expiry, policy denial, auth errors, bad plans and cancellations are never
  retried. Each attempt is its own agent run (idempotency key `workflow:<run>:<step>:<attempt>`).
- **`drive` never sleeps.** When only a retry delay is left it returns `waiting_retry` and the time it is due; drive
  again later (the scheduler in 9.5 will). All state is in the database, so a restart resumes where it stopped.
- **Timeouts:** an attempt running past its deadline has its agent run cancelled (withdrawing any pending approval) and
  counts as a failed attempt (`step_timeout`). The step timeout is capped by the agent-run timeout ceiling
  (`AGENT_RUN_TIMEOUT_SECONDS`). Time spent waiting for approval does not count: the deadline is cleared while waiting
  and restarted on resume.
- **Approvals:** a step that needs a human waits while independent steps carry on; `drive` resumes it once decided.
  Nothing here can approve anything.
- **Cancel:** cancels the run and every linked live agent run (withdrawing approvals); mid-drive cancels are honoured at
  the next checkpoint. **Crash safety:** run creation is idempotent per attempt and `drive` reconciles steps whose
  agent run already finished, so repeating it never executes anything twice.
- Content-free: step results hold fixed outcome words and ids only; no instruction or error text reaches events,
  results, agent-run rows or logs (tested with a canary).
- Execution is synchronous and sequential; background workers are not part of this substep.

## 9.4 Events (`app/workflows/events.py`, table `workflow_events`, migration 0011)
`EventService.emit(principal, event_type, event_ref)` records an internal event, finds the workflows that listen for
it and creates one PENDING run for each. It executes nothing; driving the runs is the scheduler's job (9.5), or the
emitter's call to `WorkflowEngine.drive`.

- **No new authority.** A run started by an event is an ordinary workflow run owned by the user who emitted it: that
  user needs `agent:run`, and only they can drive it. Viewers cannot emit, and agents cannot emit even with a broad
  scope, because that would let an agent start workflows by itself.
- **Matching** follows the manual-start rule: the newest ACTIVE version of each workflow, and that version must declare
  an `event` trigger of that type. Archived workflows never start. Everything is workspace-scoped.
- **Idempotent.** (workspace, type, ref) is one event, enforced by a unique constraint. Redelivery of a dispatched event
  returns the recorded outcome and does not match again, so a workflow defined later is not retro-started. A delivery
  that was interrupted is finished on redelivery; each run's `trigger_ref` is the event's id, so nothing starts twice.
  A redelivery from a different user is a conflict.
- **Bounded.** At most `WORKFLOW_MAX_EVENT_FANOUT` runs per event (default 10, 1-50; alphabetical by workflow key;
  `truncated` is recorded). The per-workspace active-run limit still applies: a workflow that cannot start is counted
  as skipped with a fixed reason code, and the others still start. A workflow whose stored definition fails its
  integrity check is skipped and counted.
- **Content-free.** An event holds a type, a reference and counts. There is deliberately NO payload: event data would be
  untrusted input to prompts, so carrying it is a separate later decision. Audit events (`workflow.event_received`,
  `workflow.event_dispatched`) carry ids, counts and codes only, never the reference or any instruction.
- Reading: the emitter sees their own events and `agent:manage` sees all; others get a plain not-found.
- Not in this substep: HTTP intake and webhooks (9.6 and Step 10), event retention/purging and intake rate limiting
  (Step 13/14), time-based triggers (9.5).

## 9.5 Scheduling (`app/workflows/scheduler.py`, table `workflow_schedules`, migration 0012)
`ScheduleService.arm/disarm` manage schedules; `Scheduler.tick()` fires due schedules and then drives scheduled and
event-started runs. Nothing loops or sleeps: something calls `tick` periodically (an HTTP trigger in 9.6, a cron, or a
worker). All state is in the database, so a restart resumes exactly where it stopped.

- **Arming** needs `agent:manage` (admin+); agents never can. The newest ACTIVE version of the workflow must declare that
  exact `schedule` trigger. The first fire is one interval after arming. One schedule per (workflow, interval);
  `WORKFLOW_MAX_SCHEDULES` (default 20) bounds them per workspace. Re-arming a disarmed schedule resets its clock.
- **Authority is re-read on every fire and drive.** Runs belong to the user who armed the schedule and are created and
  driven as that user, with their CURRENT role looked up from memberships (`principal_from_membership`: active user,
  active membership, active workspace). If they lost admin rights, left, or were deactivated, the schedule disables itself
  (`owner_unavailable`) instead of running with stale authority.
- **Exactly-once slots.** A run's `trigger_ref` is `<schedule id>:<slot epoch>`, unique in the database. The run is created
  first (idempotent), then the schedule advances with a compare-and-swap on `next_fire_at`. A crash between the two
  re-fires the same slot and adopts the existing run; two concurrent ticks cannot start a slot twice.
- **No backfill, no pile-up.** After downtime ONE run fires and the schedule jumps to the next boundary after now (missed
  slots are counted in the audit event). A slot is skipped, not queued, while the previous run from the same schedule is
  still pending or running, or while the workspace run limit is full.
- **Fail-closed.** A schedule whose trigger was removed (`trigger_removed`), whose workflow is archived
  (`workflow_unavailable`) or whose stored definition fails its integrity check (`definition_invalid`) disables itself.
- **Bounded per tick:** `WORKFLOW_TICK_MAX_SCHEDULES` (20) schedules fired and `WORKFLOW_TICK_MAX_RUNS` (10) runs driven. One
  failing schedule or run never stops the others; errors are counted by fixed code, never with content.
- **Driving** uses the ordinary engine (9.3), so every step is an agent run under the owner's permissions with approvals,
  policy, retries and audit. Only schedule- and event-started runs are driven by the tick; manual runs are driven by their
  creator. Retry delays resume on later ticks (`waiting_retry` costs nothing).
- Audit: `workflow.schedule_armed|disabled|fired|skipped` with ids, slots, counts and fixed reasons only.
- Known gap: a run whose owner is no longer eligible is left untouched (and counted); an admin can cancel it. Stuck-run
  reporting belongs to Step 13 observability.

## 9.6 HTTP API (`app/api/workflows.py`) and the Step 9 safety suite

Thin routes under `/workspaces/{workspace_id}`; all authority, digests, dedupe and audit stay in the services.

| Area | Routes | Who |
|---|---|---|
| Definitions | `POST /workflows`, `POST /workflows/{key}/versions/{version}/archive` | admin (`agent:manage`) |
| | `GET /workflows`, `GET /workflows/{key}[?version=]`, `GET /workflows/{key}/versions` | `agent:run` and up |
| Runs | `POST /workflows/{key}/runs` (manual start, creates a PENDING run), `GET /workflow-runs[/{id}]` | member |
| | `POST /workflow-runs/{id}/drive` | the run's creator only |
| | `POST /workflow-runs/{id}/cancel` | creator or admin |
| Events | `POST /workflow-events`, `GET /workflow-events[/{id}]` | member (emitter sees own, admin sees all) |
| Schedules | `GET /workflow-schedules` | member |
| | `POST /workflow-schedules` (arm), `POST /workflow-schedules/disarm` | admin |
| Tick | `POST /workflow-tick` `{"drive": true}` | admin |

- **Humans only.** The caller is the signed-in user; an agent principal cannot reach any of these routes, so an agent
  can never define, start, emit, arm or tick. Viewers and outsiders get 403 / 404 on every route.
- **No new authority.** Starting a run only creates a PENDING run. `drive` runs it through the ordinary engine, so each
  step is an agent run under the owner's permissions, the agent's scope, policy, approvals and audit. A not-actionable
  or disallowed model choice ends as a step with outcome `no_action` and executes nothing.
- **Tick is per workspace.** `Scheduler.tick` gained an optional `workspace_id`; the HTTP route always sets it, so one
  tenant can never fire or drive another's schedules or runs. `{"drive": false}` only fires due schedules and needs no
  model. Manual runs are never driven by a tick. An operator cron may still call `Scheduler.tick()` for all workspaces.
- **Content.** Run, step, event and schedule responses carry ids, states, counters and fixed codes. Definitions hold
  their template text (secret-filtered on the way in); it is returned only by the single-definition read, never in lists.
  Event references are returned to the emitter and admins, never written to audit.
- **Errors** are fixed text plus a code (`422` invalid, `403`, `404`, `409` conflict/state/limit); rejected input is
  never echoed and unexpected failures return a generic 500.
- No migration, no new setting, no new dependency in 9.6.

Safety suite (`tests/test_workflow_api.py`, 47 tests): access on every route, workspace isolation, creator-only
driving, approval pause and resume (a decision alone executes nothing), cancel withdrawing approvals, retry via HTTP,
event idempotency and trigger matching, schedule arming rules, per-workspace tick, owner-lost-admin disabling,
content-free audit over the whole lifecycle, and no echo of rejected input.

### Honest status of Step 9
- Everything ran on SQLite; the Postgres concurrency re-check stays on the Step 14 list.
- Nothing calls the tick on its own: an external cron or worker must hit `POST /workflow-tick` (or run `Scheduler.tick`).
- Event intake is internal and payload-free; external webhooks arrive with the Step 10 connectors.
- Event/schedule runs driven by a tick use the workspace's configured model. Stuck-run reporting, retention and intake
  rate limiting belong to Steps 13 and 14.

