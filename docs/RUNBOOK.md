# Runbook (Step 15.2)

For whoever is on call. Commands assume the repository root and the production environment variables. Read docs/PRODUCTION.md first.

## Deploy a new version
1. Take a database backup (docs/BACKUP.md; PostgreSQL: `pg_dump`).
2. Build the image and run its tests (`pytest`). Audit dependencies: `pip-audit -r requirements.txt`.
3. Start the new version. The container runs `alembic upgrade head` before serving; if it fails, the container exits and the old version keeps running. Check the logs for the migration error.
4. Smoke test (docs/PRODUCTION.md section 10): `/ready` is 200, register or log in, approval-gated action stops for approval.

## Roll back
- **No migration in the release:** redeploy the previous image.
- **Migration in the release:** prefer fixing forward. To go back: stop the app, restore the pre-deploy backup (`python -m app.backup restore ...` for SQLite, `pg_restore` for PostgreSQL), then deploy the previous image. `alembic downgrade <previous revision>` exists for every migration but drops the data added by that migration (for example `auth_events` rows).

## Rotate APP_SECRET_KEY (suspected leak, or scheduled)
1. Generate a new key: `python -c "import secrets;print(secrets.token_urlsafe(48))"`.
2. Set `APP_SECRET_KEY` to the new value and `APP_SECRET_KEY_PREVIOUS` to the old one. Deploy.
3. Run `python -m app.reencrypt` (re-encrypts every stored credential; it prints the count).
4. Remove `APP_SECRET_KEY_PREVIOUS`. Deploy again. Store the new key offline, separately from backups.
- **Everyone is signed out** by this: access tokens are signed with a key derived from the current secret only. Tell users to log in again.
- If you skip step 3 and drop the old key, stored connection secrets become unreadable and every connection must be re-entered.

## A credential or token leaked
- A user's token: the user calls `POST /auth/logout` (revokes all of that user's tokens) or changes their password. For a user who cannot, deactivate the user.
- A connection secret (an external system's key): rotate it in the external system, then `POST /workspaces/{id}/credentials/{cid}/rotate`, or revoke the credential.
- The root key: rotate APP_SECRET_KEY as above, and rotate every external key that was stored.

## When an alert fires (`GET /workspaces/{id}/monitoring/alerts`)
| Rule | Severity | First look |
|---|---|---|
| connection_failing | critical | Credentials page: press **test** on the connection. Expired or rotated key in the external system? Network from the app to that system? |
| execution_failure_rate | warning / critical | `monitoring/summary` for the window; which tool class is failing (connection test, external outage). Failed executions are final and are not retried automatically. |
| approval_waiting_too_long | warning / critical | Someone must decide the approval. Escalate to a workspace owner. Pending approvals expire on their own. |
| many_denials | warning | An agent or user keeps requesting something not allowed. Check the policy and the role of the requester. |
| slow_executions | warning | p95 duration: external system slow or timeouts too long. |
| agent_runs_overdue / agent_runs_failed / workflow_steps_overdue / workflow_runs_failed | warning | Drive or cancel the stuck run (`POST /workflow-runs/{id}/drive` or `/cancel`). Failed runs: read the run's error code, fix the cause, start a new run. |
| schedules_overdue / schedules_auto_disabled | warning | The scheduler tick is not running, or a schedule failed repeatedly and was switched off. Call `POST /workflow-tick`, then re-arm the schedule after fixing the cause. |
| events_stuck | warning | Inbound events were received but not dispatched. Call `POST /workflow-tick`. |
The dashboard (`/dashboard`) shows the same overview. Alerts are pull-only: poll the endpoint from your own monitor.

## Database trouble
- `/ready` returns 503: the database is unreachable. Check the database service, `DATABASE_URL`, connection limits. The app recovers by itself when the database returns.
- Restore: stop the app, restore the backup, start the app (migrations run), confirm `alembic current` equals the head named in docs/PRODUCTION.md, then run the smoke test. Do one drill on a scratch database before you need it.

## Locked-out users and abuse
- Login throttling: 5 failed logins per email and address lock that pair for the window (default 15 minutes) with a 429. It clears on its own, or restart the process to clear all counters (they are per process).
- Behind a reverse proxy set `TRUSTED_PROXY_COUNT` to the number of proxies, only if the app is reachable solely through them; otherwise everyone shares the proxy's address.

## Do not
- Do not set `ALLOW_PRIVATE_CONNECTOR_HOSTS`, `ALLOWED_ORIGINS=*` or a zero rate limit in production: the app refuses to start.
- Do not edit approval, execution or event rows by hand; they are the audit trail.

## Post-deploy gate (Step 15.3)
After every deploy and rollback run `python scripts/preflight.py https://your-host --check-migrations`. Any `FAIL` line names the gate and a fixed hint; fix it before sending traffic. Use `--smoke` once per environment (it leaves one throwaway user and workspace behind).
