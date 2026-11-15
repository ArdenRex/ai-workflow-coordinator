# PostgreSQL validation (Step 14.2)

Production refuses SQLite, so until 14.2 the production database had never been exercised. This step ran the migrations, the whole test suite and real parallel-load tests on **PostgreSQL 16**.

## What was checked
- `alembic upgrade head`, `downgrade base`, `upgrade head` on an empty database: all pass (head 0018). `alembic check` reports no difference between the models and the migrations.
- The whole suite against PostgreSQL (see "Running the tests"). SQLite-only test code was made portable or skipped on server databases; no application behaviour was weakened.
- `tests/test_postgres_concurrency.py`: parallel submits, each on its own session and connection (skipped on SQLite).

## Findings fixed
| # | Finding | Fix |
|---|---|---|
| 1 | **The execution cap could be exceeded under parallel load.** A cap of 3 let all 8 parallel runs through, because the check happened long before the run started (the count uses start time, which is set later). This was the "count-then-run is not atomic" item from 12.3c | The cap is re-checked inside the claim, under a per-workspace PostgreSQL advisory lock held to the end of the claim transaction. A fresh run that loses the race is ended as FAILED with `execution_limit_reached` (it never started) and raises the normal denial; an approved run stays APPROVED and can be released later. 5 of 5 repeated parallel runs ran the tool exactly `cap` times |
| 2 | Time zone leakage: the server session time zone came back on timestamps, which shifted backoff and expiry arithmetic by the server's UTC offset | Every PostgreSQL connection is opened with `timezone=UTC` |
| 3 | Idempotency under real concurrency | Verified as is: 8 parallel submits with one key ran the tool once; different requests on one key give one winner and clean conflicts (the 13.3 fix, now proven on a real database). Removing that fix fails the test |

Mutation checks: removing the advisory lock fails the cap test; removing the unique-violation recovery fails both idempotency tests.

## Running the tests on PostgreSQL
    createdb aceden_test          # an EMPTY, disposable database
    TEST_DATABASE_URL=postgresql+psycopg://user@host:5432/aceden_test python -m pytest -q
Tables are created once and TRUNCATED after every test. Needs a PostgreSQL driver: `psycopg2-binary` is already in `requirements.txt` (URL `postgresql://...`). The suite and the concurrency tests were run with it and also with psycopg 3 (`postgresql+psycopg://...`).

## Still open
- **Escalation threshold** (12.3d) has the same count-then-park shape. It only ever turns an automatic run into a parked one, so a race can let a few extra runs through right at the threshold; it cannot loosen anything. Not locked yet.
- A late-refused run is recorded as FAILED and also as a denial, so it counts twice towards escalation and the failure rate. It only tightens.
- The advisory lock is per workspace and held only for the claim, not while the tool runs. Many parallel runs in one workspace with a cap serialise on that short step.
- Only PostgreSQL 16 was tested. No load test, no connection-pool tuning, no failover or replica testing.
- The backup tool (`python -m app.backup`) is SQLite only. Use `pg_dump`/`pg_restore` for PostgreSQL; that procedure is documented but its restore has not been tested end to end.
