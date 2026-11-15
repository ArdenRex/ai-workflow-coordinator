# Backup and recovery (Step 13.4)

## SQLite (what this repo runs on)
    python -m app.backup backup  <db_path> <backup_path>
    python -m app.backup verify  <backup_path>
    python -m app.backup restore <backup_path> <db_path> [--force]

- **backup** uses SQLite's online backup API, so it is a consistent snapshot while the app is running. It writes to a temp file, verifies it, then moves it into place (mode 0600). It never overwrites an existing backup.
- **verify** checks `integrity_check`, `foreign_key_check` and that the Alembic revision is the current head. Problems are fixed-text codes, never row content.
- **restore** verifies first and touches nothing if the backup is invalid. It refuses to overwrite an existing database without `--force`; with it, the old file is kept as `<db_path>.pre-restore`. Stale `-wal`/`-shm` files are removed. Stop the app before restoring.
- A backup from an older revision is rejected (`revision_not_current_head`): restore it into an older release, then migrate.

## Secrets
A backup holds credential **ciphertext**. It is useless without `APP_SECRET_KEY` (and any `APP_SECRET_KEY_PREVIOUS`). Back the keys up separately, in a different place from the database backups. Losing the key means stored connection credentials cannot be decrypted and must be re-entered.

## Suggested routine
Daily backup, keep at least 7, copy off the host, run `verify` on each, and do a test restore into a scratch path monthly. Restoring is not complete until `verify` passes and `GET /ready` is healthy.

## PostgreSQL
Not handled by this tool. Use `pg_dump -Fc` and `pg_restore` (plus point-in-time recovery from your provider) and then run `alembic upgrade head`. A tested Postgres procedure stays on the Step 14 list.

## Not done
No scheduled or automatic backups, no off-host copy, no encryption of the backup file itself, and no restore of a single workspace.
