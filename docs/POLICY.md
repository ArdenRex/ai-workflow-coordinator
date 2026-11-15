# Workspace policy (Step 12)

## 12.1 Policy store and autonomy levels
`GET|PUT /workspaces/{workspace_id}/policy` (humans only; admin and owner via the existing `policy:*`; members, viewers and outsiders get 403/404;
agents cannot reach HTTP and `PolicyService.set` refuses an agent principal). Code: `app/models/policy.py`, `app/kernel/policy_store.py`,
`app/api/policy.py`, migration `0013` (table `workspace_policies`, one row per workspace).

**What a policy holds.** `autonomy_level` (1-5), `disabled_tools` and `approval_required_tools` (registered tool ids, at most 100 each, sorted and
de-duplicated), a `version` and who last changed it. No free text is stored.

**Only tightening.** `policy.evaluate()` is unchanged: a policy can disable a tool or force approval, and cannot waive a tool's own approval rule or
the HIGH-risk rule. A stored level never raises the automatic-execution limit: every stored row maps to "reads only run unattended".

**No row = the baseline**: level 3, nothing disabled, reads unattended, everything else needs approval. That is exactly `WorkspacePolicy()`, so a
workspace that never sets a policy behaves as before. `GET` returns it with `version: 0` and `is_default: true`.

| Level | Meaning | Status in 12.1 |
|---|---|---|
| 1 observe | AI observes | can be set; recorded |
| 2 recommend | AI recommends | can be set; recorded |
| 3 prepare | AI prepares actions, humans approve | can be set; this is today's behaviour |
| 4 execute low-risk | AI executes approved low-risk actions | refused: `autonomy_level_unavailable` |
| 5 autonomous | AI operates within explicit policies | refused: `autonomy_level_unavailable` |

Levels 4 and 5 are refused on purpose: nothing can enforce them yet, and we do not claim autonomy that is not enforced (blueprint rule 6).
Levels 1 and 2 are recorded but, in 12.1, behave like level 3 (the difference needs agent-aware enforcement, planned for a later substep).

**Writes.** `PUT` body: `expected_version` (0 for the first write), `autonomy_level`, optional `disabled_tools`, `approval_required_tools`. A write
replaces the whole policy. A stale version gives 409 `version_conflict` (compare-and-swap in the UPDATE itself, so a read that went stale between
check and write still cannot overwrite). Errors are fixed text (`invalid_policy`, `autonomy_level_unavailable`, `version_conflict`) and never echo
the input. Every change writes a content-free audit event (`policy.created` / `policy.updated`: version, level, previous level and counts, no tool ids).

**Provider.** `db_policy_provider(session_factory)` returns a `Callable[[workspace_id], WorkspacePolicy]` for `ToolExecutionService`, agent
contexts and the composite tools. It reads the store on every call (a change applies immediately) and fails closed: a store error propagates and is
never turned into a looser default. Tested against the real kernel: a stored approval rule parks `system.ping`, a stored disable denies it.

### Limits and not done in 12.1
- (Resolved in 12.2: the provider is now wired into every path, see below.)
- No risk classification, execution limits, escalation rules or approval routing (later Step 12 substeps). Levels 4-5 unavailable. Levels 1-2 not
  yet distinguished from 3. No per-tool risk override. No policy history beyond the audit events.
- SQLite only: the Postgres concurrency re-check (including the first-write race, decided by the unique constraint) stays on the Step 14 list.

## 12.2a Wiring: Step 11 HTTP routes and composite tools (mini step 1 of 3)
- `app/runtime.py` now owns the provider: `get_policy_provider()` (own short session per read, used by the composite tools),
  `request_policy_provider` (FastAPI dependency; reads on the request's own session and never closes it).
- The four `/workspaces/{id}/capabilities/*` routes build their kernel with `policy_provider=...`, and the four composite tools
  (attention, opportunities, changes, meetings) are registered with the shared provider, so their nested reads obey a stored policy.
- Both providers fail closed: a store error propagates and never becomes a looser default.
- Tests: `tests/test_policy_wiring_capabilities.py` (4). `tests/test_step11_hardening.py` pins the exact wiring text and now also requires the provider.
- **Still not wired (12.2b / 12.2c):** agent runs, plans, workflows (and agent-aware `base_policy_provider`), then end-to-end tests on every path.

## 12.2b Wiring: agent runs, plans, workflows (mini step 2 of 3)
- Every `AgentExecutor` built in the API layer (`agent_runs` start + resume, `plans._orch`, `workflows._engine`, which the scheduler tick also uses)
  now receives `base_policy_provider=session_policy_provider(db)`. The agent context applies `agent_policy(...)` on top, so a stored policy can only
  tighten what an agent is already allowed to do. Intent understanding and planning see the same policy (a disabled tool leaves their catalog).
- Tests: `tests/test_policy_wiring_agents.py` (4): baseline unchanged; a stored approval rule parks an agent run; a stored disable never executes;
  another workspace is unaffected; every executor in the API layer is wired.
- **Still to do (12.2c):** end-to-end through a plan and a workflow, and a closing guard that no kernel is built without a provider.

## 12.2c End-to-end and closing guard (mini step 3 of 3) - 12.2 complete
- `tests/test_policy_wiring_paths.py` (4): a stored approval rule stops a **plan** step and pauses a **workflow** run (nothing executes unattended);
  plan and workflow baseline is unchanged without a stored policy; and a **closing guard** scans `app/` and fails if any `ToolExecutionService(...)`
  lacks `policy_provider=` or any `AgentExecutor(...)` lacks `base_policy_provider=`.
- Together with 12.2a and 12.2b a stored policy now takes effect on: the four Step 11 routes and tools, agent runs (start and resume), plans and workflows
  (including scheduler ticks). Policies only tighten; levels 4-5 are still refused; levels 1-2 still behave like 3.

### Limits after 12.2
- **Not covered:** `app/api/ai.py` and the approvals/execution routes were not changed in 12.2 (the guard shows no bare `ToolExecutionService` remains in `app/`,
  but routes that never build a kernel are untouched). Direct `/tools` execution routes, if any, should be checked in 12.3.
- No risk classification, execution limits, escalation rules or approval routing yet (12.3+). No per-tool risk override. No policy history beyond audit events.
- Plans and workflows are tested with approval rules only; disable rules are covered end to end on agent runs and at the kernel (12.1).
- SQLite only: the Postgres concurrency re-check stays on the Step 14 list.

## 12.3a Per-tool risk override (mini step 1 of 2 for risk classification)
- A workspace can raise the risk of a registered tool: `risk_overrides` on `PUT /workspaces/{id}/policy`, a map of tool id to `"medium"` or `"high"`
  (migration `0014`, column `workspace_policies.risk_overrides`). The write replaces the whole policy like the other fields.
- **Tighten only.** Effective risk is the higher of the tool's own risk and the override (`effective_risk()` in `app/kernel/policy.py`). The store refuses
  an override that is not strictly above the tool's own risk (`invalid_policy`), and the engine also ignores a lower one if it ever got stored.
- A tool whose effective risk is above the automatic limit needs approval, with reason code `workspace_risk_override` (visible in the
  `execution.created` event). Deny rules still come first; a tool's own `high_risk` / `tool_requires_approval` keep their codes. A stored override cannot
  raise the automatic-execution limit, and it is per workspace.
- The execution record stores the **effective** risk. The audit event carries only `risk_override_count`, never tool ids.
- Tests: `tests/test_policy_risk_override.py`. Changed existing tests: `test_database.py` (head 0014) and `test_policy_store.py` (the default view and the
  audit payload each gained a key).
- **Not done:** an override only ever forces approval. Agent-level risk ceilings are unchanged. Execution limits, escalation rules and approval routing are
  still to come (12.3b and later). SQLite only; the Postgres re-check stays on the Step 14 list.

## 12.3b Effective risk everywhere it is shown or decided (mini step 2 of 2 for risk classification)
- Found by reading every risk read in `app/`: the capability **catalog** (what the model is shown) and the **plan proposal** still reported the tool's own risk
  while the kernel already forced approval from the override. Both now use `effective_risk(tool, policy)`, so what is shown matches what is enforced.
  Approvals and executions already carried the stored effective risk (12.3a), so no change was needed there.
- **Direct `/tools` routes:** there are none. `app/` has no HTTP route that executes a tool directly, and no approval or execution view endpoint;
  every route that runs tools builds its kernel with the stored policy (guard from 12.2c).
- **Guard:** `tests/test_policy_effective_risk_views.py` fails if any file outside a short allowlist reads `tool.risk_level` (`registry.py`, `policy.py`,
  `policy_store.py`, `agents/definition.py`). It asserts it found reads, so it cannot pass vacuously.
- Tests (4): catalog shows effective risk and never lowers it; plan proposal carries effective risk and needs approval; no-policy plan unchanged; the guard.
- **Not done:** the agent risk ceiling (`effective_tools` in `app/agents/definition.py`) still uses the tool's base risk; it is on the guard allowlist on purpose.
  Execution limits, escalation rules and approval routing are still to come (12.3c and later). SQLite only.

## 12.3c Workspace execution limit (mini step 1 of 3 for execution limits)
- A workspace can cap how many tool runs start in a time window: `execution_limit` on `PUT /workspaces/{id}/policy`, `{"max_executions": 1..100000,
  "window_seconds": 60 | 3600 | 86400}` or absent/`null` for no cap (migration `0015`, column `workspace_policies.execution_limit`). A write replaces the whole policy.
- **Tighten only.** No row or no limit = baseline (no cap). The limit can only refuse; it never allows anything a rule denied or parked.
- **Enforced in the kernel** (`ToolExecutionService._enforce_limit`), the single trusted boundary: (1) in `submit()` when the decision is ALLOW, before any
  record is created; (2) in `execute_approved()` just before an approved execution would run. A parked execution does not use budget (it ran nothing);
  if the cap is full when it is released it stays `APPROVED` and can be released later. Refusal raises `PolicyDeniedError("execution_limit_reached")` and writes a
  content-free `execution.denied` event. Idempotent replays are not new runs.
- **What counts:** executions of this workspace whose `started_at` falls inside the window (all tools, humans and agents; nested reads inside composite tools count
  too). Other workspaces never count.
- Validation is strict and fixed-text (`invalid_policy`): exactly the two keys, plain ints (no bool/float/string), allowed windows only. A malformed stored value raises
  when read (fail closed), never "no limit". Audit event gains `has_execution_limit`.
- Tests: `tests/test_policy_execution_limit.py`. Changed existing tests: `test_database.py` (head 0015), `test_policy_store.py` (default view and audit payload gained a key).
- **Known limit:** the count-then-run check is not atomic, so two truly concurrent submits can overshoot the cap by a little. The Postgres concurrency re-check is on the
  Step 14 list (SQLite serialises writes). **Not done:** per-tool limits, escalation rules and approval routing (12.3d and later). SQLite only.

## 12.3d Escalation rule (mini step 2 of 3 for execution limits and escalation)
- A workspace can ask for a human look after trouble: `escalation` on `PUT /workspaces/{id}/policy`, `{"threshold": 1..1000, "window_seconds": 60 | 3600 | 86400}`
  or absent/`null` for off (migration `0016`, column `workspace_policies.escalation`). A write replaces the whole policy.
- **Rule.** When the workspace's **failed runs plus denied attempts** in the window reach the threshold, a run that would have executed unattended (decision ALLOW)
  is parked for approval instead, with reason code `escalation_threshold` (visible in the `execution.created` event). Nothing runs until a human approves.
- **Tighten only.** It turns ALLOW into REQUIRE_APPROVAL and nothing else: a deny stays a deny, an approval requirement is never waived, and no run is created or started by it.
  Baseline (no rule) is unchanged however many failures there are.
- **Enforced in the kernel** (`ToolExecutionService._escalated`, called in `submit()`), before the 12.3c cap check, so a parked run uses no budget. An execution a human
  already approved is not escalated again when released (a person already looked at it).
- **What counts:** `tool_executions` with status FAILED whose `finished_at` is in the window, plus `execution.denied` events in the window, this workspace only.
  Idempotent replays are not counted twice (they create nothing).
- Validation is strict and fixed-text (`invalid_policy`): exactly the two keys, plain ints, allowed windows only. A malformed stored value raises when read (fail closed).
  Audit event gains `has_escalation`.
- Tests: `tests/test_policy_escalation.py`. Changed existing tests: `test_database.py` (head 0016), `test_policy_store.py` (default view and audit payload gained a key).
- **Known limits:** (1) the capability catalog and plan proposal call the pure `evaluate()`, which cannot see history, so they do not show escalation; enforcement is in the kernel
  and every route that runs tools goes through it. (2) Denied attempts include every `execution.denied` event (for example probing for unknown tools by a member of the
  workspace), so a member can trigger escalation: that only makes runs ask for approval, never loosens anything. (3) Count-then-park is not atomic; the Postgres
  concurrency re-check stays on the Step 14 list. **Not done:** approval routing (12.3e), per-tool limits. Levels 4-5 still refused. SQLite only.

## 12.3e Approval routing (mini step 3 of 3 for execution limits, escalation and routing) - 12.3 complete
- A workspace can require the **owner** to decide approvals of a given risk level: `approval_routing` on `PUT /workspaces/{id}/policy`, a map of `"medium"` and/or `"high"`
  to `"owner"` (`{}` = no routing; migration `0017`, column `workspace_policies.approval_routing`). A write replaces the whole policy.
- **Tighten only.** Deciding an approval (approve or reject) then needs one more permission, `owner:approve`, in addition to `approval:decide`. Only the OWNER role holds it
  (`"*"`; no other role in `identity/roles.py` lists it), so an admin is refused. Nothing is ever removed from the existing checks: agents still cannot decide,
  requesters still cannot decide their own approval, terminal states stay immutable.
- **Which risk:** the execution's stored **effective** risk (12.3a), so an override that raised a tool to high routes its approvals as high. Runs parked by escalation
  (12.3d) keep their own risk, so they are routed by that risk, not by the escalation.
- **Enforced in `ApprovalService.decide`** (`approval_routing` check, after the permission check, before the state check). A refusal leaves the approval PENDING, raises
  `ApprovalPermissionError` (fixed text) and writes a content-free `approval.decision_refused` event. The kernel's own `ApprovalService` is built with the stored policy provider;
  a provider error propagates (fail closed). An `ApprovalService` built without a provider behaves as before.
- Validation is strict and fixed-text (`invalid_policy`): only `medium`/`high` keys and only the value `"owner"`. A malformed stored value raises on read. Audit event gains
  `approval_routing_count`.
- **Closing guard:** `tests/test_policy_approval_routing.py` scans `app/` and fails if any `ApprovalService(...)` lacks `policy_provider=`, except `agents/runs.py`, which only withdraws
  (rejects) approvals. It asserts it found constructions, so it cannot pass vacuously.
- Tests (25 cases): `tests/test_policy_approval_routing.py`. Mutation checks: with the routing check removed, 2 behaviour tests failed; with the provider removed from the kernel's
  service, the guard failed. Changed existing tests: `test_database.py` (head 0017) and `test_policy_store.py` (default view and audit payload gained a key).
- **Known limits:** there are still no HTTP routes to decide approvals, so routing is enforced at the service and will apply to any route added later only if it builds the service
  with the provider (the guard catches a bare one). Only one routing target (`owner`) exists; per-role or per-user routing and per-tool limits are not built. Levels 4-5 still
  refused. SQLite only; the Postgres concurrency re-check stays on the Step 14 list.

### 12.3 summary
Risk overrides (a, b), a workspace execution cap (c), an escalation rule (d) and approval routing (e) all tighten only and are enforced in the kernel or approval service.

## 12.4 Autonomy level 4 (first level that can loosen anything)
- Level 4 (`execute_low`) can now be set; **level 5 is still refused** (`autonomy_level_unavailable`). Levels 1-3 behave as before.
- Level 4 adds one field, `auto_execute_tools` (migration `0018`, column `workspace_policies.auto_execute_tools`): an explicit list of tool ids that may run **without approval** although
  their risk is above the automatic limit (reads still run unattended; everything else still needs approval). This is the **only loosening** in the whole policy, so it is narrow:
  - **Level 4 needs an execution cap** (`execution_limit`, 12.3c); without one the write is refused (`invalid_policy`). The list is refused at any other level.
  - A listed tool must exist, have its **own** risk at most MEDIUM, have no approval requirement of its own, not be disabled, not be in `approval_required_tools`, and not be
    overridden to HIGH. Anything else is refused with the fixed `invalid_policy` error.
  - The engine re-checks the same limits (defence in depth): HIGH risk (own or override) always needs approval, a tool's own `requires_approval` and a workspace approval rule win over
    the list, deny rules and permission/agent-scope checks come first, and a listed tool is still subject to the **execution cap**, the **escalation rule** and **approval routing**.
- **Wording note:** the blueprint says level 4 is "AI executes approved low-risk actions". Low-risk reads already run unattended at every level, so level 4 is implemented as
  "the workspace pre-approves named medium-risk tools". Nothing is pre-approved by default.
- A stored list that is not at level 4 with a cap raises when read (fail closed), never a quiet loosening. Audit event gains `auto_execute_count`.
- Tests: `tests/test_policy_level4.py`. Changed existing tests: `test_database.py` (head 0018) and `test_policy_store.py` (the level-4 refusal case was removed, default view and audit payload gained a key).
- **Known limits:** the capability catalog and plan proposal use `evaluate()` and so show a listed tool as automatic (correct); they do not show escalation (12.3d). Level 5, per-tool limits and
  per-role routing are not built. SQLite only; the Postgres concurrency re-check stays on the Step 14 list.

## 12.5 Autonomy level 5 (Step 12 policy work complete)
- Level 5 (`autonomous`) can now be set. All five levels are settable; `autonomy_level_unavailable` is no longer reachable from the API.
- **Level 5 is level 4 plus mandatory guardrails. It grants no extra authority.** A level-5 write is refused (`invalid_policy`) unless it carries **all three**:
  an execution cap (`execution_limit`, 12.3c), an escalation rule (`escalation`, 12.3d) and high-risk approvals routed to the owner (`approval_routing` with `high: owner`, 12.3e).
  The optional `auto_execute_tools` list follows the level-4 rules exactly (own risk at most MEDIUM, no own approval requirement, not disabled or approval-ruled, not overridden to HIGH).
- High-risk actions, a tool's own approval requirement and workspace approval rules still always need approval; nothing about level 5 changes the engine (`policy.evaluate` is untouched).
  What level 5 changes is what a workspace must have in place before it may run unattended tools at all.
- **Fail closed:** a stored level 5 that is missing any guardrail raises when read, never a quiet fallback.
- Tests: `tests/test_policy_level5.py`. Changed existing tests: `test_policy_store.py` (the level-5 refusal case was removed; the stored-level loop gives level 5 its guardrails) and
  `tests/test_policy_level4.py` (the "level 5 is refused" assertion was removed).
- **Honest scope note:** because the roadmap's HIGH-risk rule is never waived, level 5 cannot let the AI do more than level 4; it makes the safe configuration mandatory. If a later step
  wants level 5 to mean broader authority, that must be a deliberate, separately tested loosening.
- **Known limits:** same as 12.3/12.4 (no per-tool limits or per-role routing; count-then-run is not atomic; SQLite only, Postgres re-check on the Step 14 list).

### Step 12 status
Policies, autonomy levels 1-5, risk classification, execution limits, escalation rules and approval routing are implemented and tested. Remaining Step 12 gaps are those listed under the known limits above.

## 14.2 note: the execution cap under concurrency
The cap is now re-checked inside the claim under a per-workspace lock (PostgreSQL), so parallel runs cannot exceed it. See docs/POSTGRES.md. The escalation threshold is still count-then-park.
