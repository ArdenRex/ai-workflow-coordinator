# Security review (Step 14.1)

Scope of this first review pass: authentication, request handling, configuration and what the API returns. Method: read the code, then test.
Workspace isolation, permissions, approval enforcement and credential handling were reviewed in earlier steps and are covered by the existing
route sweeps and kernel tests; they get a dedicated pass in later 14.x mini steps.

## Reviewed and found sound (no change)
- Passwords: scrypt with per-password salt, constant-time compare, parameters bounded on verify, unknown-email timing equalised, same 401 for wrong password / unknown / disabled.
- Tokens: HS256 pinned (no `none`, no algorithm confusion), `exp`/`iat`/`sub`/`iss` required, purpose-derived key, deactivated users rejected on every request.
- Production config refuses: the default or short secret, SQLite, the fake LLM, non-https connector and LLM URLs. API docs are off in production.
- No log line passes a password, secret, token or key.

## Findings fixed in 14.1
| # | Finding | Fix |
|---|---|---|
| 1 | No limit on `/auth/login` and `/auth/register`: unlimited password guessing (blueprint section 15, rate limiting) | `app/security/throttle.py`: failed logins limited per (email, address) and per email (4x), plus a per-address request limit. A locked key gets 429 + `Retry-After` **before** any password check, identically for existing and unknown emails. Bounded memory. Settings `AUTH_MAX_FAILED_LOGINS` (5), `AUTH_LOCKOUT_WINDOW_SECONDS` (900), `AUTH_MAX_REQUESTS_PER_MINUTE` (30) |
| 2 | API responses carried no security headers | Every response now has `nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store` and a deny-all CSP. A route's own header wins (the dashboard keeps its stricter script policy); `/docs` (development only) is excluded from the CSP |
| 3 | No request size limit | A declared `Content-Length` above `MAX_REQUEST_BYTES` (default 4 MiB) gets 413 before any work |
| 4 | `ALLOWED_ORIGINS=*` and disabling throttling were allowed in production | Production now refuses both |

## Known limits (open, for later 14.x or Step 15)
- **Throttle state is per process.** With several workers each keeps its own counters, so the effective limit is multiplied. Exact limits need a shared store.
- The client address is the direct peer. Forwarded headers are not trusted; behind a reverse proxy all users may share one address unless the proxy is configured accordingly.
- Lockout is a trade-off: someone who knows an email can lock that (email, address) pair, and, with enough failures from many addresses, the email-wide limit, for the window. It never reveals or bypasses anything.
- The size cap checks the declared `Content-Length`; a chunked body without one is not capped here. Set a limit at the reverse proxy too.
- PostgreSQL: validated in 14.2 (see POSTGRES.md). Still untested: load, pool tuning, failover.
- Tokens can be revoked only per user (`POST /auth/logout`, 14.7), not one by one; otherwise they expire after `ACCESS_TOKEN_TTL_MINUTES` (default 60). No password reset, email verification or MFA.
- The count-then-run cap and escalation checks are not atomic (see KERNEL.md / POLICY.md).
- Registration reveals whether an email is taken (409).

## Tests
`tests/test_security_hardening.py` (18). Mutation checks: removing the pre-password lockout check failed 2 tests; removing failure recording failed 2 tests.

## 14.3 Isolation and surface sweeps
- **The four "known failing" route sweeps were a test-discovery problem, not a regression.** Newer FastAPI wraps included routers in private objects, so `app.routes` listed zero workspace routes and the sweeps' "not vacuous" guards failed. Discovery now goes through the public OpenAPI schema (`tests/route_discovery.py`), one entry per path and method. `test_isolation`, `test_memory_api`, `test_orchestration_safety` and `test_agents_safety` now pass on any FastAPI version, and they genuinely cover the routes again (59 workspace operations).
- New automatic sweeps in `tests/test_surface_sweeps.py` (no per-route code, so a future route cannot dodge them):
  1. **Only four operations are public** (`POST /auth/register`, `POST /auth/login`, `GET /health`, `GET /ready`). Every other operation answers 401 without a token. A new public route has to be added to that list on purpose. Mutation check: removing `/ready` from the list fails.
  2. **Every table with a `workspace_id` has a foreign key to `workspaces` and a leading index or constraint** (tenant column cannot be added unconstrained).
  3. **No workspace route answers 5xx** to unknown ids or junk bodies (`{}`, `[]`, a string, a deep object) from a workspace owner.
- Result: no new vulnerability found. Approval bypass and cross-workspace access were already covered by kernel, approval, credential, memory, agent, plan and workflow tests (self-approval, agents never decide, cross-workspace decisions 404, ciphertext moved between workspaces fails, and so on).
- **Not done in this pass:** a sweep with real foreign ids (every id-taking route called with a resource that exists in another workspace). The per-area tests cover credentials, executions, approvals, runs, plans and memory; workflow definitions, schedules and events rely on the generic outsider sweep. Role-by-role permission matrix for every route is also not generated automatically.

## 14.4 Credential security and real-foreign-id sweeps
A canary secret and a canary password are pushed through every credential and auth flow (`tests/test_credential_security.py`, 17 tests).
- **Fixed 1: validation errors echoed the request body.** FastAPI's default 422 includes the submitted `input`, so a request with a missing field returned the whole body, including a credential `secret` or a login `password`, in the response. A `RequestValidationError` handler (app/main.py) now returns only `loc`, `msg` and `type`.
- **Fixed 2: `repr(settings)` and `str(settings)` printed `APP_SECRET_KEY` and the previous keys.** Anything that logged the settings object, a traceback with locals, or a debugger would expose the root secret. Both are now shown as `***` (the values themselves are unchanged).
- **Checked and already sound:** responses (create, list, get, rotate, test, revoke, duplicate, rotate-after-revoke, validation errors); audit event payloads (ids, provider, name, version only); every table (no plaintext, only `v1.` ciphertext); DEBUG logs during create, test and rotate; unexpected 500s (generic text); revoke wipes the stored ciphertext; a ciphertext moved to another workspace or row fails authentication without carrying data; a backup file holds ciphertext only, never the plaintext secret or the root key.
- **Real-foreign-id sweeps:** workspace A holds a real workflow, run, event, schedule, memory item and document. The owner of workspace B addresses those real ids through B's own workspace id on every workflow route (definition, versions, archive, start, run get/drive/cancel, event get, schedules, disarm, events, tick) and every memory route (get, delete, document put/delete, search, lists). Every id route answers 404 identically to a made-up id, lists are empty, nothing of A is shown, and A's rows are byte-identical afterwards.
- **Mutation checks:** removing the 422 handler failed 8 tests; removing the settings redaction failed 1. Both restored.
- **Not done:** log scrubbing for secrets inside exception text (an exception whose message contains a secret would still be logged by the 500 handler; no such code path was found); a role-by-role permission matrix; real-foreign-id sweeps for agents, plans and policy routes (covered by their own tests); the earlier open list below 14.3 is unchanged.

## 14.5 Production configuration review and end-to-end journey
Every setting's production behaviour was reviewed (`tests/test_production_config.py`, 18 tests).
- **Fixed 1: `/openapi.json` was public in production.** Only `/docs` was switched off, so anyone could still download the full list of routes and schemas. It is now off in production (`openapi_url=None`). The route sweeps read the schema in-process, so they are unaffected.
- **Fixed 2: production accepted `ALLOW_PRIVATE_CONNECTOR_HOSTS=true`**, which lets stored connections call private, loopback and cloud-metadata addresses (SSRF). Production now refuses to start with it.
- **Fixed 3: production accepted `CONNECTOR_MAX_CALLS_PER_MINUTE=0` (unlimited outbound calls).** Refused in production; still allowed in development.
- **Fixed 4: `/health` revealed the version and environment to anonymous callers.** In production it returns status and service name only.
- **Production now refuses** (each tested): a weak or short `APP_SECRET_KEY` or previous key, SQLite, the fake LLM, `ALLOWED_ORIGINS=*`, disabled login throttling, private connector hosts, unlimited connector calls, plain-http LLM or Aceden URLs.
- **Guards that keep config honest:** every key in `.env.example` must be a real setting (no stale or misspelled names); the Dockerfile must run as a non-root user and run migrations before the server starts.
- **End-to-end journey** (the blueprint's "ready" definition, over HTTP): goal -> controlled plan -> approval required with nothing executed -> an outsider cannot decide -> a human owner approves -> approving alone still executes nothing -> the run's owner resumes -> exactly one execution -> the audit trail holds plan, approval request and decision, execution and run events in this workspace only -> the admin sees it in the monitoring overview and a member cannot.
- **Mutation checks:** serving the schema in production failed 1 test; removing the private-hosts guard failed 1. Both restored.
- **Not done / for deployment:** the container has no `HEALTHCHECK` and uvicorn does not trust proxy headers (set both at the platform or reverse proxy, and set a request-size limit there too); no secret-manager integration (secrets come from environment variables); a very weak but long key such as 40 identical characters is accepted; `docker-compose.yml` is development only (weak database password, port exposed).

## 14.6 Failure and burst testing (`tests/test_failure_hardening.py`, 8 tests)
- **Fixed 1: a huge integer in a path crashed with a 500.** `POST /workflows/{key}/versions/9999...9/archive` (and the `version` query and body fields on workflow routes) overflowed the database driver. These now have an upper bound (2,147,483,647) and answer 422. A body sweep with a 10^40 value in every integer-looking field found no other overflow.
- **Fixed 2: escalation is re-checked at the claim.** The escalation rule was evaluated only before the execution was created, so failures or denials arriving in between did not park the run. It is now re-checked under the same per-workspace lock as the execution cap (PostgreSQL advisory lock), for fresh runs only. An execution a human already approved is never re-escalated. Without an escalation rule there is no extra query. It only ever turns a run into "needs approval".
- **Limit that remains (inherent):** failures count only once a run has finished, so several runs already in flight when the threshold is crossed still complete. The rule bounds what starts next, not what is already running.
- **Checked, already sound:** a crashing tool stores only the exception type name (no message, host or password) in the execution and the audit event; a database failure mid-request is a generic 500 with no detail, and `/ready` answers 503 `unavailable`; every workspace route survives hostile path values (5000-character ids, NUL bytes, `../`, emoji, SQL text, 40-digit numbers) and malformed bodies (invalid JSON, invalid UTF-8, 2000-deep nesting, `null`, form data) with no 5xx; 60 bad logins in a burst give only 401 and 429, and another email is not locked out; 150 authenticated reads in a row all succeed with p95 under 1 s on the test setup.
- **Mutation checks:** disabling the claim-time recheck failed 1 test; removing the path bound failed 1 test. Both restored.
- **Not done:** a real multi-process load test (the burst test is sequential in one process), connector outage tests beyond the existing connector suites, and a PostgreSQL concurrency test for the escalation recheck (the recheck is unit-tested with a controlled flip, not raced).

## 14.7 Token revocation (`tests/test_token_revocation.py`, 12 tests)
- **Gap closed:** a stolen or leaked access token stayed valid until it expired, and there was no logout. New `POST /auth/logout` (needs a valid token, answers 204) invalidates **every** token the user has been issued so far, on all devices. Logging in again gives a working token.
- **How:** `users.token_version` (migration `0019`, integer, default 0, so existing users and tokens keep working). Each token carries a `tv` claim; `get_current_user` rejects a token whose version differs from the user's current one. Logout does an atomic `token_version = token_version + 1`, so concurrent logouts cannot lose an increment. Tokens without a `tv` claim count as version 0. A malformed claim (bool, negative, string, float, null) is rejected.
- **Effect on every route:** a revoked token gets 401 on all authenticated routes, including workspace routes.
- **Not done:** revoking a single token (one device) needs a `jti` deny-list table; password reset, email verification and MFA; automatic revocation on password change (there is no password-change endpoint yet); no audit event for logout (audit events are workspace-scoped and auth routes are not audited yet).
- **Not done: PostgreSQL backup/restore.** PostgreSQL is not installed in this sandbox, so the documented `pg_dump`/`pg_restore` procedure (docs/BACKUP.md) is still untested. The 0019 migration was tested on SQLite (upgrade with an existing user, downgrade, upgrade); run `alembic upgrade head` against a scratch PostgreSQL database before deploying (see docs/POSTGRES.md).
- **Mutation check:** removing the version comparison failed the revocation tests (restored).

## 14.8 Password change and account activity (`tests/test_auth_activity.py`, 10 tests)
- **`POST /auth/password`** (token required; body `current_password`, `new_password`; unknown fields refused). It verifies the current password, applies the same strength rules as registration, refuses a new password equal to the current one, stores the new hash and **invalidates every token the user holds** (14.7 version bump, same atomic update). The response carries a fresh token for the caller, so they stay signed in; other devices must log in again. A wrong current password answers 403 and changes nothing. Guessing the current password is throttled with the same per-email/per-address limiter as login (429 and locked even for the right password while locked).
- **Account activity:** new table `auth_events` (migration `0020`): user id, event type, direct peer address, time. Recorded: `register`, `login`, `login_failed` (only for an existing account), `logout`, `password_changed`, `password_change_failed`. It holds no email, password or token, and failed logins for unknown emails store nothing (so an attacker cannot grow the table with made-up addresses). `GET /auth/activity?limit=50` returns the caller's own events, newest first; nobody can read another user's.
- **Not done:** password reset by email and email verification (no mail system yet), MFA, retention or pruning of `auth_events`, admin-level view of a workspace member's activity, and alerting on repeated failed logins.
- **Mutation check:** dropping the token-version bump from the password change failed the revocation tests (restored).

## 14.9 Final validation (`docs/PRODUCTION.md`, `tests/test_release_hygiene.py`, 5 tests)
- **Dependency audit (`pip-audit -r requirements.txt`) found 35 known vulnerabilities** in three packages: PyJWT 2.8.0 (15 advisories, authentication library), python-dotenv 1.0.1 (1) and Starlette 0.37.2 (the web layer under FastAPI 0.111; 7 distinct advisories). Pins raised to `fastapi 0.162.7`, `starlette 1.10.0`, `pydantic 2.14.3` (required by that FastAPI), `PyJWT 2.15.1`, `python-dotenv 1.2.4`. The packages with no findings keep the versions the earlier steps were tested on (SQLAlchemy 2.0.30, Alembic 1.13.1, httpx 0.27.0, uvicorn 0.29.0, psycopg2-binary 2.9.9). Re-audit: **no known vulnerabilities**. The full suite was re-run in a clean virtual environment with exactly these versions (result in the step summary). **You must reinstall dependencies** (`pip install -r requirements.txt`) and re-run the suite on your own environment.
- **Secret scan:** a test scans every file in the repository for private keys, AWS, GitHub, OpenAI-style and Slack tokens, bearer JWTs and database URLs with real passwords. Only two test files are allowed to hold hits (fabricated placeholders that test secret refusal). Planting a fake key made the test fail (checked, then removed). It also checks no `.env` or `.db` file is in the tree, `.gitignore` covers them, `.env.example` holds placeholders, and every package in `requirements.txt` is pinned exactly (cryptography keeps a range).
- **`docs/PRODUCTION.md`:** one checklist covering required settings, database and migrations, network and platform, backup drill, monitoring, security properties, dependency audit, the honest limitations list, and a 10-minute first-day smoke test. A test fails if it stops naming the current migration head or any production-guarded setting.
- **Not done:** PostgreSQL still could not be run in this sandbox (migrations 0019 and 0020, `pg_dump` restore, the PostgreSQL test suite at the new dependency versions); an external penetration test; a multi-process load test; static analysis tooling (bandit or similar); automated dependency auditing in CI.

## 15.2 Launch-day gaps: trusted proxy, healthcheck, runbook (`tests/test_trusted_proxy.py`, 17 tests; `docs/RUNBOOK.md`)
- **`TRUSTED_PROXY_COUNT`** (default 0, range 0 to 5). At 0 the app uses the direct peer and ignores `X-Forwarded-For`, exactly as before, so a client can never pick its own address. At N it uses the N-th entry from the right of the header (the entries your own proxies appended; anything the client wrote further left is ignored). A missing header, fewer entries than N, or a value that is not an IP address falls back to the direct peer. IPv6 works. It feeds the login throttle and the account activity log. **Set it only if the app is reachable solely through those proxies**; otherwise a client that bypasses the proxy can forge its address.
- **Container `HEALTHCHECK`** on `/health` (liveness). Point your platform's readiness probe at `/ready`.
- **`docs/RUNBOOK.md`:** deploy, rollback, `APP_SECRET_KEY` rotation, a leaked token or key, what each of the 12 alerts means and where to look, database trouble, locked-out users. A test fails if the runbook stops naming any alert rule in the code.
- **Worth knowing:** rotating `APP_SECRET_KEY` signs every user out (tokens are signed with a key derived from the current secret only). The runbook says so.
- **Mutation checks:** taking the first `X-Forwarded-For` entry instead of the Nth-from-right failed 4 tests; renaming an alert rule in the runbook failed 1. Both on a copy.
- **Still not done:** shared throttle storage (counters are per process), a PostgreSQL run of the migrations and restore, an external penetration test, a multi-process load test.

## 15.3 Launch-gate preflight (`scripts/preflight.py`, `tests/test_preflight.py`, 10 tests)
A standard-library script that checks a deployed instance and exits 1 on any failed gate. It prints gate names and fixed hints only: never a token, password, response body or exception text. The tests run it in-process against a production-shaped app (all 14 gates pass), a development app (schema and health gates fail), a missing header, a down database, permissive CORS and a crashing transport.
Limits: it sees only what is reachable over HTTP, so it cannot prove TLS settings, proxy count or firewalling; `--smoke` leaves one test user behind; the approval journey needs a real connected system and is not scripted.

## 15.4 Launch checklist (`docs/LAUNCH.md`)
One ordered table of launch gates, who owns each, and how it is proven. A hygiene test fails if it references a file or script that does not exist. No code change.

## F1 Web interface sign-in (`frontend/`, `tests/test_remember_me.py`, `tests/test_frontend_contract.py`)
- Login and password change accept `remember_me` (boolean). True issues a token valid for `REMEMBER_ME_TTL_DAYS` (1-90, default 30); false keeps `ACCESS_TOKEN_TTL_MINUTES`. Logout and password change still revoke every token, remembered or not.
- Remembered tokens sit in browser `localStorage` (readable by any script on the page); other sessions use `sessionStorage`. A 30-day token that leaks is valid until it expires or the user signs out, so keep third-party scripts off the frontend.
- A contract test fails if the frontend calls a route or method the API does not have.

## F2 Workspaces and connections screens (`frontend/`)
No backend change. The secret field is a password input that is cleared after a successful save; the API never returns a secret, so the screen cannot show one. Read-only members get no write controls (the API still refuses them). The contract test now checks all 14 frontend calls against the API's routes and methods.

## F3 Goals and plans screen (`frontend/`)
No backend change. The page creates plans with `execute: false`, so nothing runs until the user presses Approve and run; the server still applies permissions, approvals and policy to every step. The goal text and proposed steps live only in page memory and are never written to browser storage.


## F4 Approvals and activity (`app/api/approvals.py`, `frontend/`)
New routes: `GET /approvals`, `GET /approvals/{id}`, `POST /approvals/{id}/approve|reject`, `GET /activity`. All decision rules stay in `ApprovalService` (needs `approval:decide`, never the requester, never an agent, atomic single decision, routing policy, expiry); the route only maps its errors to fixed text. Callers without `approval:decide` see only approvals they requested, and never the tool input; another workspace's approval is a plain 404. `/activity` needs `audit:read` and returns event type, actor, execution id, time and a whitelist of code/id fields (tool, risk, reason, policy, agent, approval id); payload content and input digests are never returned. Deciding does not execute anything; the kernel still re-checks approval and the exact approved input when the run resumes. F2/F3 UI fix: `can()` now honours wildcard grants like the server (previously admins and owners would not have seen write controls). Tests: `tests/test_approvals_api.py` (9), frontend approvals/permissions/render tests; contract test now checks 23 frontend calls.

## F5 Monitoring page (`frontend/`)
No backend change. The page calls `GET /workspaces/{id}/monitoring/overview`, which already requires `audit:read` and returns counts and fixed codes only; the page makes no call for people without that permission. It shows data in memory only (nothing is written to browser storage) and stops its refresh timer when left. Alerts are displayed, not sent anywhere. The contract test now checks 24 frontend calls.

## F6 Vercel deployment (`api/index.py`, `vercel.json`, `.vercelignore`, `docs/DEPLOY_VERCEL.md`)
No application code change. The API entry point only re-exports `app`; all settings still come from the environment and production guards still apply. `.vercelignore` keeps tests, docs, migrations and any `.env` out of the deployed function. Known weaker point on Vercel: the login throttle is per instance (see docs/DEPLOY_VERCEL.md).
