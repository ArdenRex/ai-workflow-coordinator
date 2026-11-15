# Execution Kernel (Step 2)

The kernel is the single trusted boundary for real-world actions. Agents never call
connectors or tool handlers directly; they call `ToolExecutionService`.

## Flow
    submit(principal, tool_id, input)
      1 tool lookup (unknown -> audited denial)
      2 input validation against the tool schema (errors never echo values)
      3 idempotency (same key + same normalized request -> same execution)
      4 policy: workspace isolation > disabled > user permission > agent scope > approval
      5 record execution (PENDING) + audit event
      6 ALLOW -> run | REQUIRE_APPROVAL -> approval PENDING, nothing runs
    approve/reject (ApprovalService.decide)
    execute_approved(principal, execution_id)
      status APPROVED + real APPROVED approval row + input digest matches what was approved
      + policy re-checked now -> atomic claim -> run -> verify output -> audit

## Modules
| File | Responsibility |
|---|---|
| `kernel/registry.py` | Tool definitions: schemas, permission, risk, approval rule, timeout, retries |
| `kernel/permissions.py` | Principal (user + optional agent scope), wildcard matching |
| `kernel/policy.py` | Deny-first policy decision with reason codes; workspace policy can only tighten |
| `kernel/approvals.py` | PENDING -> APPROVED/REJECTED/EXPIRED -> EXECUTED; atomic decisions |
| `kernel/service.py` | The only place tool handlers are invoked (enforced by a test) |
| `kernel/audit.py` | Append-only events, secret redaction, input digest |

## Guarantees (each covered by tests)
- High-risk tools always need approval; policy and tool config cannot waive it.
- Agents can never decide approvals; requesters cannot approve their own actions by default.
- An approval is bound to the exact input requested; changing the input voids it.
- A run is claimed with one conditional update: no double execution.
- Approved work re-checks policy at run time (revoked permission / disabled tool blocks it).
- Workspace isolation on every lookup; other workspaces get "not found".
- Handler failures store only the error type; timeouts are never retried; only low-risk tools retry.
- Every denial, decision and run is audited; secrets are redacted from audit payloads.

## Known limits (tracked for later steps)
- Timeouts stop waiting but cannot kill a running thread (connectors must use their own HTTP timeouts).
- `workspace_id` has no foreign key until Step 4; roles/memberships replace caller-supplied permissions then.
- Tool inputs are stored as submitted: tools must not take credentials as input (Step 4 credential layer).
- A failed run is final; retrying a failed high-risk action requires a new submission and approval.

## 13.3 Retries and idempotency review
Audit result (no change to working behaviour except the two fixes below):
- Kernel: a failed or timed-out execution is final and never re-run automatically; a replay with the same key returns the stored execution and runs nothing. A parked (approval) execution replayed with its key creates no second approval.
- Agent runs: `run:<id>` key into the kernel; workflow steps use `workflow:<run>:<step>:<attempt>`. Workflow retries are bounded (<= 5 attempts), only for transient causes, and only if the failed attempt made no tool call (see WORKFLOWS.md).
- Fix 1: an idempotent replay now re-checks policy for the caller. A caller who is denied the tool now (disabled tool, missing permission, agent scope) gets the same denial instead of the stored result. Approval-required stays a replay, not a denial.
- Fix 2: two concurrent submits with the same key no longer end in an unhandled IntegrityError. The loser rolls back and returns the winner's row (or IdempotencyConflictError if its request differs).
- Tests: tests/test_kernel_idempotency.py (6). Still open for Step 14: the count-then-run cap/escalation check is not atomic; SQLite only.
