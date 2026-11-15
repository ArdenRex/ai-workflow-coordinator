# Workspace isolation (Step 4, Substep 4.6)

Company A must never see, change, use or infer anything about Company B. `tests/test_isolation.py`
attacks that property at every layer.

## How isolation is enforced

| Layer | Mechanism | Where |
|---|---|---|
| HTTP | Every `{workspace_id}` route resolves the caller's membership from the DB. Non-member, removed member, inactive workspace and nonexistent workspace all return the same 404 body. | `app/identity/context.py` |
| Role | The role is read from the DB, never supplied by the caller. Only `ctx.principal()` makes a kernel `Principal`. | `context.py`, `roles.py` |
| Credentials | Every lookup filters by `workspace_id`; a foreign credential id is a 404. | `credentials_service.py` |
| Crypto | AES-GCM AAD = `workspace_id:credential_id`, so a ciphertext copied to another row/workspace fails authentication. | `security/crypto.py` |
| Connectors | One cached connector per credential id, rebuilt on rotation, dropped on revoke. Lookups are by the principal's workspace. | `connectors/workspace.py` |
| Kernel | Executions, approvals and audit reads filter by `workspace_id`; policy denies `workspace_mismatch`; idempotency keys are unique per workspace. | `kernel/*` |
| Database | `workspace_id` on kernel and credential tables is a foreign key to `workspaces.id`. | migrations 0004, 0005 |

## What the tests prove

- **Route sweep:** every route containing `{workspace_id}` is discovered automatically. An outsider gets a 404
  identical to the response for a nonexistent workspace; an anonymous caller gets 401. A new route can't dodge this.
  The test asserts a minimum route count so it can't pass vacuously.
- **Credentials:** foreign credential ids can't be read, rotated, revoked or tested through another workspace's
  path (and the original is unchanged); listings are scoped and never contain secrets or ciphertext; ciphertext
  moved between workspaces fails to decrypt; the same secret in two workspaces is stored differently.
- **Connectors:** each workspace gets its own connector with its own key; rotating A rebuilds only A; revoking A
  does not affect B.
- **Kernel/approvals:** B's principal cannot read, audit, approve or execute A's execution, even after A approves
  it; audit events stay in their own workspace and contain no secrets or emails; the same idempotency key in two
  workspaces doesn't collide.
- **Identity:** one user holds independent roles per workspace; a removed member loses access immediately and
  only for that workspace; deactivated workspaces and users are cut off; role-escalation attempts fail and change
  nothing; a non-member can't add themselves to another workspace.
- **Secrets:** no secret (current, rotated or attacker-supplied) appears in logs or error bodies across create,
  test, rotate, run and revoke.

## Checked by mutation

Removing the workspace filter from `ApprovalService.get` makes the kernel isolation test fail, confirming the
tests detect a real regression.

## Known gaps (carried to Step 14 hardening)

- Tested on SQLite. Postgres row-locking (owner rows, credential `FOR UPDATE`) and concurrent behaviour are not
  exercised; run these tests against Postgres in Step 14.
- No rate limiting on login/register or on cross-workspace probing.
- DNS-rebinding window between the SSRF check and the connection (see CONNECTORS.md).
- Add-member-by-email lets admins probe whether an email is registered.
- Tokens can't be revoked before expiry except by deactivating the user.
- No workspace-level row-security policy in Postgres (isolation is enforced in application code and FKs).
