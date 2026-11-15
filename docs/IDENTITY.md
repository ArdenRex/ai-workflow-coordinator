# Workspaces, roles, context (Step 4.3)

**Request identity -> kernel:** `get_current_user` (JWT) -> `get_workspace_context` (membership lookup on the
`{workspace_id}` path param) -> `ctx.principal()` -> `ToolExecutionService`. The role always comes from the
database membership, never from the client. Non-member / removed member / inactive workspace / nonexistent
workspace all return the same 404.

**Roles** (`app/identity/roles.py`, the only role->permission mapping): viewer (reads) < member (+task:write)
< admin (+manage members, connections, policies, approvals, audit) < owner (`*`). Permissions are allow-lists:
a new permission not listed there is owner-only until deliberately assigned. **Whoever adds a tool must decide
which roles get its permission.**

**Membership rules** (`app/identity/service.py`): an actor may only grant roles <= their own and only modify
members <= their own role (admins can't touch owners); a workspace always keeps >=1 active owner (owner rows are
locked `FOR UPDATE` on Postgres); memberships are deactivated, never deleted, and re-adding reactivates; every
change writes a `workspace.created` / `member.added` / `member.role_changed` / `member.removed` audit event
(user ids only, no emails) in the same transaction.

**Endpoints:** `POST/GET /workspaces`, `GET /workspaces/{id}` (role + permissions), `GET|POST /workspaces/{id}/members`,
`PATCH|DELETE /workspaces/{id}/members/{user_id}`.

**Kernel FKs (migration 0004):** `tool_executions`, `approvals`, `system_events` `.workspace_id` now reference
`workspaces.id`. The migration refuses to run (clear message) if legacy rows point at missing workspaces.
Kernel-level tests use the `seed_workspaces` fixture (ids w1..w3).

**Known gaps:** add-member-by-email lets admins probe whether an email is registered (acceptable for admins;
revisit with invitations); no workspace rename/deactivate endpoints yet; no invitation flow for unregistered users.
