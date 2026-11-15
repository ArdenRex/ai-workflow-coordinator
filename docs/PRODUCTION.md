# Production readiness checklist (Step 14.9)

Work through this top to bottom before the first customer. Each line names the setting, command or test that proves it. Items marked
**UNTESTED HERE** could not be exercised in the build sandbox (no PostgreSQL, no real LLM or connector accounts) and must be run once by you.

## 1. Configuration (the app refuses to start in production if these are wrong)
- `APP_ENV=production`
- `APP_SECRET_KEY`: at least 32 random characters (`python -c "import secrets;print(secrets.token_urlsafe(48))"`). Keep a separate offline copy; **backups are useless without it**.
- `DATABASE_URL`: PostgreSQL (`postgresql://...`). SQLite is refused.
- `ALLOWED_ORIGINS`: explicit origins, never `*`.
- `LLM_PROVIDER=openai_compatible` with an `https://` `LLM_BASE_URL` and `LLM_API_KEY` (the fake LLM is refused).
- `AUTH_MAX_FAILED_LOGINS` and `AUTH_MAX_REQUESTS_PER_MINUTE` above 0 (throttling cannot be turned off).
- `ALLOW_PRIVATE_CONNECTOR_HOSTS=false` and `CONNECTOR_MAX_CALLS_PER_MINUTE` above 0.
- `ACEDEN_BASE_URL`, if used, is `https://`.
- Optional: `APP_SECRET_KEY_PREVIOUS` only while rotating (see docs/CREDENTIALS.md).
- Proof: `tests/test_production_config.py`, `tests/test_config.py`.

## 2. Database
- Run `alembic upgrade head` (current head `0020`) **before** starting the new version. The container does this on start.
- **UNTESTED HERE:** run it once on a scratch PostgreSQL database; then `alembic check` (must report no drift). Steps: docs/POSTGRES.md.
- The app sets every PostgreSQL connection to UTC. Do not override.

## 3. Network and platform (not done by the app, set at the platform or proxy)
- Terminate TLS at the proxy; serve only HTTPS.
- Set a request-body limit at the proxy (the app also refuses declared bodies over 4 MiB with 413).
- Set `TRUSTED_PROXY_COUNT` to the number of reverse proxies in front of the app (default 0 = ignore `X-Forwarded-For`). The client address is then the N-th entry from the right of the header, so a client cannot choose its own address. Set it **only** if the app is reachable solely through those proxies. Without it, behind a proxy every user shares the proxy's address in the login throttle and the activity log.
- Health checks: liveness `GET /health`, readiness `GET /ready` (503 when the database is unreachable). The Dockerfile has a `HEALTHCHECK` on `/health` (liveness only; point your platform's readiness probe at `/ready`).
- Run more than one process only after moving the throttle counters to shared storage (they are per process today).

## 4. Backups and recovery
- Take backups on a schedule (docs/BACKUP.md). SQLite tooling is tested; PostgreSQL uses `pg_dump` / `pg_restore`: **UNTESTED HERE**. Do one full restore drill into a scratch database and confirm `alembic current` shows `0020` and a login works.
- Store the `APP_SECRET_KEY` copy separately from the backups.

## 5. Monitoring
- Dashboard: `GET /dashboard` (paste a workspace id and a token). API: `GET /workspaces/{id}/monitoring/overview` (summary, health, alerts in one response; admin or owner).
- Alerts evaluate on request only. Nothing is sent. Poll `/monitoring/alerts` from your own monitor and notify on `critical`.

## 6. Security properties (each has tests; see docs/SECURITY.md)
Workspace isolation and approval enforcement; login and registration throttling; security headers; request size cap; no secrets in responses, errors, logs, audit events or backups; production guards; no public schema or version; token revocation (logout, password change); account activity log.

## 7. Dependencies
- Pinned in `requirements.txt`. Audit before every release: `pip install pip-audit && pip-audit -r requirements.txt`.
- At 14.9 the audit reported 35 known vulnerabilities (PyJWT 2.8.0, python-dotenv 1.0.1, Starlette 0.37.2). The pins were raised and the full suite re-run (see SECURITY.md 14.9).

## 8. Known limitations (honest list)
- No password reset, email verification or MFA (no mail system yet).
- Single-token revocation needs a deny-list table; logout revokes all of a user's tokens.
- Alerts are pull-only: no email, chat or webhook notifications; thresholds are constants.
- Throttle counters are per process; load tested only as a sequential burst in one process.
- In-flight runs complete after an escalation threshold is crossed (the rule bounds what starts next).
- Only PostgreSQL 16 was ever run (in an earlier session); no failover, pool-tuning or multi-process load test.
- Connectors: Aceden plus the generic HTTP connector kit; each new connector must pass the same security review.

## 9. Operations
See docs/RUNBOOK.md: deploy, rollback, key rotation, leaked credentials, what each alert means, database trouble.

## 10. First-day smoke test (10 minutes)
1. `GET /ready` is 200; `GET /openapi.json` and `GET /docs` are 404.
2. Register, log in, create a workspace, add a connection, press **test**.
3. Submit a write action: it must stop for approval; approve it as an owner; confirm it runs once.
4. Open `/dashboard`, load the overview, confirm no alerts you do not expect.
5. Log out; confirm the old token answers 401.

**Automated version (Step 15.3):** `python scripts/preflight.py https://your-host` runs 8 read-only launch gates (readiness, minimal `/health`, no public schema or docs, security headers, 401 without a token, CORS, generic login failure, no request-body echo). Add `--smoke` for steps 2, 4 and 5 above (it creates one throwaway user and workspace) and `--check-migrations` (with `DATABASE_URL` set) to compare the database with the migration head. Exit code 0 means ready. It does not replace the approval step 3 (needs a real connected system), a real LLM pass, load testing or an external review.
