# Launch gates (Step 15.4)

One ordered list of what must be true before the first customer, and who does each item. The roadmap ends at Step 15; this file closes it.
Software gates are proven by tests in this repo. Human gates cannot be proven by software and stay open until you tick them.

| # | Gate | Who | How to prove it | Status |
|---|------|-----|-----------------|--------|
| 1 | Reinstall pinned dependencies and run the whole suite | You | `pip install -r requirements.txt -r requirements-dev.txt` then `pytest` | OPEN (never run on your environment) |
| 2 | PostgreSQL migration and drift check | You | `alembic upgrade head` on a scratch database, then `alembic check` (docs/POSTGRES.md) | OPEN (0019, 0020 untested on PostgreSQL) |
| 3 | Backup and restore drill | You | `pg_dump` / `pg_restore` into a scratch database (docs/BACKUP.md) | OPEN |
| 4 | Production settings accepted by the app | You | the app starts with `APP_ENV=production` (docs/PRODUCTION.md section 1) | OPEN |
| 5 | TLS, request-size limit and proxy count set | You (platform) | `TRUSTED_PROXY_COUNT` matches your proxies; HTTPS only (docs/PRODUCTION.md section 3) | OPEN |
| 6 | Preflight against the deployed instance | You | `python scripts/preflight.py https://host --smoke --check-migrations` exits 0 | OPEN |
| 7 | One real pass with a real LLM and a real connector | You | the first-day journey with the approval step (docs/PRODUCTION.md section 10) | OPEN |
| 8 | External security review or penetration test | Third party | written report, findings fixed | OPEN |
| 9 | Load test with several processes | You | note: login throttle counters are per process, so run one process or size the limits | OPEN |
| 10 | Monitoring and alert routing chosen | You | alerts are read-only (no notifications); decide who watches `/dashboard` | OPEN |
| 11 | Acceptance criteria 1 to 14 | Software | `python scripts/acceptance_report.py` writes docs/ACCEPTANCE.md | DONE (14 of 15; see that file) |
| 12 | Security hardening, isolation, approval-bypass, credential and production-config tests | Software | steps 14.1 to 14.9 and 15.2, listed in docs/SECURITY.md | DONE |
| 13 | Measurable real-world business value (criterion 15) | You, with pilot customers | pilots with measured results | OPEN (MANUAL) |

## Rules for calling it launched
- Gates 1 to 7 must be ticked before any customer data is stored.
- Gate 8 before selling to a customer that asks for a security review; gate 13 is what the commercialization phase is for.
- Re-run gate 6 after every deploy and rollback (docs/RUNBOOK.md).

## Known limits you accept at launch
- Alerts are not delivered anywhere; a person has to look at the dashboard.
- No password reset by email, no email verification, no MFA, no single-token revocation (logout revokes all tokens).
- Throttle counters are per process.
- The acceptance journey uses a scripted fake LLM and a mock connector.
