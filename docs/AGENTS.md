# Agents (Step 6)

An agent is **data**, not a privileged program: capabilities + tool access rules + a permission scope + a risk
ceiling. Agents hold no authority of their own. They will act only through the execution kernel as a scoped
principal (the kernel already intersects `agent_scope` with the acting user's permissions), so an agent can
never do more than both the user and its own scope allow.

## Substep 6.1: definition, validation, registry

    app/agents/definition.py   AgentDefinition (frozen), effective_tools()
    app/agents/registry.py     AgentRegistry (register / get / list / find_by_capability)
    app/agents/errors.py       AgentError tree

**AgentDefinition fields:** `id` (slug, 2-32 chars), `name`, `description`, `capabilities` (descriptive tags such
as `ops.monitor`), `tool_patterns` (exact tool ids or `<literal prefix>.*`; a bare `*` is never valid),
`scope_permissions` (`resource:action` or trailing `resource:*`; never `*`), `max_risk` (default LOW).
Collections are normalised to immutable, de-duplicated values and size-capped.

**Fail-closed rules**
- Agents can never hold permissions in the platform namespaces `approval`, `member`, `connection`, `policy`,
  `audit`, `billing`, `workspace`, `agent`: they cannot approve their own work, change who may do what, touch
  credentials or settings, or manage other agents.
- An agent with tools must declare an explicit scope. An agent with no tools (e.g. a future coordinator) is allowed.
- Wildcards: only a trailing `:*` in permissions and a trailing `.*` after a literal prefix in tool patterns;
  `aceden.task.*` matches `aceden.task.list` but not `aceden.tasks.export` or `aceden.task` itself.
- `effective_tools(agent, tool_registry)` = tools named by the rules AND covered by the scope AND within `max_risk`.
- `AgentRegistry(tools)` validates at registration: a pattern that matches no registered tool (typo), or an
  agent whose tools are all unusable because of its scope/risk ceiling, is rejected, so mistakes fail at startup.
- `describe()` returns only id, name, description, capabilities and risk ceiling (never patterns or permissions).

## Substep 6.2: agent context

    app/agents/context.py   agent_principal(), agent_policy(), AgentContext, build_agent_context()

- **Principal:** an agent acts as the same user and workspace as the person it works for, with that user's
  permissions and `agent_scope` = the agent's scope. The kernel already requires BOTH to allow an action, so an
  agent's rights are the **intersection** of user and agent (an owner's narrow agent stays narrow; a viewer's
  powerful agent stays a viewer). An agent cannot act for another agent. An agent with no scope can do nothing.
- **Tool access rules are enforced by the kernel**, not by convention: `agent_policy` adds every tool the agent's
  rules don't allow (or that exceed its risk ceiling) to the workspace policy's `disabled_tools`, and the agent's
  execution service uses it. No kernel changes. The policy is recomputed on every kernel call, so a tool
  registered after the agent was built is **denied by default**. Workspace policy (its own disabled tools,
  approval list, auto-execute limit) is preserved and still applies, including at `execute_approved`.
- **Approvals still bind agents:** medium/high tools still need a human; an agent cannot decide approvals (kernel
  rule), and neither can the requesting user.
- **Agent-scoped AI chain:** `AgentContext.catalog()` is the agent's view; passing `principal` + `policy` to the
  Step 5 understanding and planning services makes the model see, and the planner accept, only that view.
- **Attribution and binding:** executions record the agent; `ToolCallProposal` now carries `agent`, and
  `submit_proposal` refuses a proposal presented by a different user, workspace or agent (or by the plain user
  when an agent made it). `intent.resolved` / `plan.*` audit events name the agent when one acted.

## Substep 6.3: agent runs and lifecycle

    app/models/agents.py   AgentRun (table agent_runs, migration 0007)
    app/agents/runs.py     AgentRunService, ALLOWED_TRANSITIONS, TERMINAL

A run is a **lifecycle record**, not a transcript. Nothing in 6.3 executes anything; the executor arrives in 6.4.

    QUEUED --start--> RUNNING --wait_for_approval--> WAITING_APPROVAL --resume--> RUNNING
    RUNNING --succeed--> SUCCEEDED     any non-terminal --fail--> FAILED
    any non-terminal --cancel--> CANCELLED     any non-terminal past its deadline --> EXPIRED
    (SUCCEEDED, FAILED, CANCELLED, EXPIRED are final.)

- **Compare-and-swap transitions:** every change is an `UPDATE ... WHERE status IN (legal sources)`, so two workers
  (or a worker and a cancel) cannot both win and a final state can never be left. `start` is legal only from QUEUED
  and `resume` only from WAITING_APPROVAL, even though both lead to RUNNING.
- **Hard limits:** `max_steps`, `max_tool_calls`, `max_llm_calls` are charged *before* the work by an atomic
  conditional UPDATE (`charge(kind)`); a caller may ask for less than the ceiling (`AGENT_RUN_MAX_*`), never more.
  Exhausting a budget fails the run with a fixed code (`limit_steps`, `limit_tool_calls`, `limit_llm_calls`).
  Database CHECK constraints also stop `used > max` even if the service is bypassed.
- **Deadlines are per stretch:** queue wait and each active stretch get `AGENT_RUN_TIMEOUT_SECONDS`; a run waiting
  on a human gets `AGENT_RUN_APPROVAL_WAIT_SECONDS`. Total work is bounded by the budgets. Expiry is enforced at
  `start`/`charge`/`checkpoint` and by `expire_overdue()` (idempotent; a scheduler will call it in Step 9).
- **Cancel:** QUEUED and WAITING_APPROVAL runs cancel immediately; a RUNNING run is flagged (`cancel_requested`) and
  stops at its next `charge`/`checkpoint`. Cancel is idempotent and cannot undo a finished run. If the work already
  finished, `succeed` still records the truth.
- **Approvals:** `wait_for_approval(run, execution)` only accepts an execution in AWAITING_APPROVAL that belongs to
  this workspace, user and agent; `resume` refuses until the approval has been decided (approved, rejected or expired).
- **Content-free:** the goal is stored only as a SHA-256 digest + length; `error_code` must be a short slug (never free
  text); `result` is redacted and capped at 16 KB; audit payloads hold ids, states, counters and codes only.
- **Audit:** `agent_run.created / started / waiting_approval / resumed / succeeded / failed / cancel_requested /
  cancelled / expired`, each with from/to status and the agent id; approval events carry the execution id.
- **Authority:** a run belongs to the user who created it. Creating needs `agent:run` (member and up) and a human
  principal; users see and cancel their own runs; `agent:manage` (admin and up, via `agent:*`) sees and cancels all
  runs in the workspace. An agent principal can drive only its own run (never create, cancel, or touch another
  agent's or user's run), and a manager cannot drive someone else's run. Missing, foreign and invisible runs are
  all `RunNotFoundError`. Idempotency keys are per workspace; replays with a different user, agent or goal conflict.

## Substep 6.4: bounded agent executor

    app/agents/executor.py   AgentExecutor.execute() / .resume(), _BudgetedLLM
    app/kernel/approvals.py  ApprovalService.withdraw()  (additive: system-initiated REJECT of a PENDING approval)

`execute(user, run_id, goal)` drives one run through the Step 5 chain: start, understand, plan, submit one proposal
to the kernel. `resume(user, run_id)` continues after a human decided the approval.

- **No authority of its own:** it acts as the agent principal (user intersect agent scope). Every real action goes
  through `submit_proposal` into the kernel, which re-validates input, permission, policy and approval. Agent tool
  rules are enforced by the kernel policy from 6.2. One tool call per run (multi-step plans are Step 7).
- **Budgets cannot be bypassed:** `_BudgetedLLM` charges the run's LLM budget before EVERY provider call, so
  structured-output repairs count; steps are charged before understand / plan / execute and the tool call before
  the kernel call. Each charge also checks cancellation and the deadline, so a cancel or expiry that happens while
  the model is thinking stops the run before the next model call or any tool.
- **Outcomes:** executed -> SUCCEEDED (result: outcome, tool id, execution id; never tool output or model text);
  needs approval -> WAITING_APPROVAL; nothing to do -> SUCCEEDED with `no_action` / `needs_information` and a fixed
  reason; denied, invalid or failed -> FAILED with a fixed slug (`plan_*`, `kernel_*`, `tool_failed`, `llm_*`,
  `approval_rejected`, `approval_expired`, `limit_*`, `executor_error`).
- **Integrity:** the goal is passed in memory and must match the run's recorded digest, so the audited run is the run
  that executed. Kernel idempotency key `run:<id>` means a repeated submit can never create a second execution; a run
  can be executed only once.
- **Approvals:** `resume` refuses until the approval is decided. Approved: the kernel's `execute_approved` re-checks
  the approval, the input binding and policy. Rejected / expired: the run fails and nothing runs. Cancelling,
  expiring or failing a WAITING run **withdraws its pending approval** (`approval.withdrawn`, actor `system`), so a
  human can no longer approve work whose run has ended. `withdraw` can only reject a PENDING approval, never approve
  and never touch a decided one.
- **Authority:** only the user who started the run can execute or resume it. Agent principals, other users, admins
  and other workspaces cannot (admins may cancel, per 6.3).
- **Failure safety:** unexpected errors fail the run with `executor_error`; details go to logs only.

## Starter agents and HTTP API (6.5)
Two read-only agents (LOW risk ceiling) in `app/agents/starter.py`, validated against the real tool registry at
startup (a dead tool pattern fails the app boot, not a run): `ops_agent` (`system.ping`, `aceden.task.*`) and
`insight_agent` (`aceden.task.*`). Routes (all under `/workspaces/{workspace_id}/agents`, all need `agent:run`,
so viewers get 403 and non-members 404):

    GET  /                      list agents (descriptions only)
    POST /runs                  create AND execute a run (synchronous; the goal is never stored)
    GET  /runs[?status=&limit=] own runs; admins (agent:manage) see every run in the workspace
    GET  /runs/{id}             a run you cannot see is a plain 404
    POST /runs/{id}/cancel      own run, or any run for admins; withdraws a pending approval
    POST /runs/{id}/resume      continue after the approval was decided; only the user who started the run

Run responses are content-free: no goal, no goal digest, no tool output; only ids, status, counters, fixed result
words and fixed error slugs. A caller can request smaller budgets, never larger (422 above the ceilings). The
model is resolved BEFORE the run is created, so a workspace without a usable LLM gets a generic 502 and no orphan
run. `idempotency_key` replays return the existing run and never execute twice. Resume needs no model call.

## Safety tests (6.6) and Step 6 closed
`tests/test_agents_safety.py` treats the model and the goal as hostile: an automatic route sweep (every `/agents`
route: 401 anonymous, 404 outsider, 403 viewer; a new route cannot skip it); a hostile model naming unknown,
platform or out-of-rules tools executes nothing; prompt injection in the goal changes nothing; a zero tool budget
means no execution; a canary in the goal and the LLM key never reach responses, logs, run rows, audit events or
executions; same idempotency key in two workspaces does not collide and run ids resolve only through their own
workspace path; removed members, deactivated users and demoted roles lose access on the next request; admins can
see and cancel but never drive or resume another user's run; finished runs cannot be reopened; overdue-run expiry is
workspace-scoped. Run isolation has two independent layers (the workspace filter in the run lookup, and the workspace check in the visibility rule); removing either one alone is still caught by the other, and removing both fails the tests.

## Known gaps
Definitions are code-defined and static (no per-workspace agent customisation yet); A single tool call per run (planning across
several steps is Step 7); executing is synchronous in the caller (no background worker yet, Step 9); there is no HTTP
endpoint for deciding approvals yet (approvals are decided through the kernel service); the `llm.*` audit events still don't name the agent;
runs are tested on SQLite only (Postgres concurrency re-check is on the Step 14 list).

## Fix (7.6): approval deadline enforced at resume
`resume` now refuses a waiting run whose deadline has passed: the run becomes EXPIRED, its pending approval is withdrawn
and nothing executes, even if a human approved after the deadline and no sweeper has run yet.
