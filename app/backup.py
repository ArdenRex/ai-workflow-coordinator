"""Backup and recovery for the SQLite database (13.4).

    python -m app.backup backup  <db_path> <backup_path>
    python -m app.backup verify  <backup_path>
    python -m app.backup restore <backup_path> <db_path> [--force]

- backup: SQLite's online backup API (a consistent snapshot while the app runs), written to a temp file, verified, then
  moved into place with owner-only permissions. An existing backup file is never overwritten.
- verify: integrity_check, foreign_key_check, and the Alembic revision must be the current head.
- restore: verifies first; refuses to overwrite an existing database unless --force, and then keeps the old file as
  `<db_path>.pre-restore`. Restore never touches a database when the backup is invalid.
The backup holds credential CIPHERTEXT only; APP_SECRET_KEY (and any previous keys) must be backed up separately.
PostgreSQL is not handled here: use pg_dump/pg_restore (see docs/BACKUP.md).
"""
import os
import shutil
import sqlite3
import sys
from pathlib import Path
from typing import List

from alembic.config import Config
from alembic.script import ScriptDirectory


class BackupError(Exception):
    """Fixed-text, content-free errors."""


def current_head() -> str:
    cfg = Config(str(Path(__file__).resolve().parent.parent / "alembic.ini"))
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "alembic"))
    heads = ScriptDirectory.from_config(cfg).get_heads()
    if len(heads) != 1:
        raise BackupError("migrations do not have a single head")
    return heads[0]


def verify(path: str) -> List[str]:
    """Returns a list of problems (empty = good). Opens the file read-only."""
    p = Path(path)
    if not p.is_file():
        return ["file_missing"]
    problems: List[str] = []
    try:
        con = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    except sqlite3.Error:
        return ["not_a_database"]
    try:
        if [r[0] for r in con.execute("PRAGMA integrity_check")] != ["ok"]:
            problems.append("integrity_check_failed")
        if con.execute("PRAGMA foreign_key_check").fetchall():
            problems.append("foreign_key_violations")
        try:
            rev = con.execute("select version_num from alembic_version").fetchall()
        except sqlite3.Error:
            rev = []
        if len(rev) != 1:
            problems.append("no_migration_revision")
        elif rev[0][0] != current_head():
            problems.append("revision_not_current_head")
    except sqlite3.Error:
        problems.append("not_a_database")
    finally:
        con.close()
    return problems


def backup(db_path: str, backup_path: str) -> None:
    src_p, dst_p = Path(db_path), Path(backup_path)
    if not src_p.is_file():
        raise BackupError("database_missing")
    if dst_p.exists():
        raise BackupError("backup_exists")
    tmp = dst_p.with_name(dst_p.name + ".tmp")
    tmp.unlink(missing_ok=True)
    src = sqlite3.connect(f"file:{src_p}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(tmp))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    os.chmod(tmp, 0o600)
    problems = verify(str(tmp))
    if problems:
        tmp.unlink(missing_ok=True)
        raise BackupError("backup_failed_verification:" + ",".join(problems))
    os.replace(tmp, dst_p)


def restore(backup_path: str, db_path: str, *, force: bool = False) -> None:
    problems = verify(backup_path)
    if problems:
        raise BackupError("backup_invalid:" + ",".join(problems))
    target = Path(db_path)
    if target.exists():
        if not force:
            raise BackupError("target_exists")
        shutil.copy2(target, target.with_name(target.name + ".pre-restore"))
    for suffix in ("-wal", "-shm"):                     # stale journals must not be replayed onto the restored file
        target.with_name(target.name + suffix).unlink(missing_ok=True)
    tmp = target.with_name(target.name + ".restore.tmp")
    shutil.copyfile(backup_path, tmp)
    os.chmod(tmp, 0o600)
    os.replace(tmp, target)
    problems = verify(str(target))
    if problems:
        raise BackupError("restored_file_invalid:" + ",".join(problems))


def main(argv: List[str]) -> int:
    try:
        if len(argv) >= 3 and argv[0] == "backup":
            backup(argv[1], argv[2])
        elif len(argv) == 2 and argv[0] == "verify":
            problems = verify(argv[1])
            if problems:
                raise BackupError(",".join(problems))
        elif len(argv) >= 3 and argv[0] == "restore":
            restore(argv[1], argv[2], force="--force" in argv[3:])
        else:
            print(__doc__)
            return 2
    except BackupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
