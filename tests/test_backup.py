"""Substep 13.4: backup and recovery (SQLite)."""
import sqlite3

import pytest
from alembic import command
from alembic.config import Config

from app import backup as bk
from app.backup import BackupError


@pytest.fixture
def live(tmp_path):
    path = tmp_path / "live.db"
    cfg = Config("alembic.ini")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(cfg, "head")
    con = sqlite3.connect(path)
    con.execute("create table probe (v text)")
    con.execute("insert into probe values ('kept')")
    con.commit()
    con.close()
    return path


def names(path):
    con = sqlite3.connect(path)
    try:
        return con.execute("select count(*) from probe").fetchone()[0]
    finally:
        con.close()


def test_backup_is_verified_private_and_restorable(live, tmp_path):
    out = tmp_path / "b.db"
    bk.backup(str(live), str(out))
    assert bk.verify(str(out)) == [] and oct(out.stat().st_mode & 0o777) == "0o600"
    assert not (tmp_path / "b.db.tmp").exists()
    fresh = tmp_path / "restored.db"
    bk.restore(str(out), str(fresh))
    assert names(fresh) == names(live) and bk.verify(str(fresh)) == []


def test_backup_never_overwrites_and_needs_a_database(live, tmp_path):
    out = tmp_path / "b.db"
    bk.backup(str(live), str(out))
    with pytest.raises(BackupError, match="backup_exists"):
        bk.backup(str(live), str(out))
    with pytest.raises(BackupError, match="database_missing"):
        bk.backup(str(tmp_path / "nope.db"), str(tmp_path / "x.db"))


def test_backup_taken_while_the_source_is_open_and_written(live, tmp_path):
    con = sqlite3.connect(live)
    con.execute("begin")
    out = tmp_path / "b.db"
    bk.backup(str(live), str(out))                       # snapshot works beside an open connection
    con.close()
    assert bk.verify(str(out)) == []


def test_restore_refuses_to_overwrite_without_force_and_keeps_the_old_file_with_it(live, tmp_path):
    out = tmp_path / "b.db"
    bk.backup(str(live), str(out))
    with pytest.raises(BackupError, match="target_exists"):
        bk.restore(str(out), str(live))
    con = sqlite3.connect(live)
    con.execute("create table marker (x)")
    con.commit()
    con.close()
    bk.restore(str(out), str(live), force=True)
    assert (tmp_path / "live.db.pre-restore").exists()
    con = sqlite3.connect(live)
    assert not con.execute("select name from sqlite_master where name='marker'").fetchall()
    con.close()


@pytest.mark.parametrize("make,expected", [
    (lambda p: None, "file_missing"),
    (lambda p: p.write_bytes(b"not a database at all" * 50), "not_a_database"),
])
def test_invalid_backup_is_rejected_and_restore_touches_nothing(live, tmp_path, make, expected):
    bad = tmp_path / "bad.db"
    make(bad)
    assert expected in bk.verify(str(bad))
    before = live.read_bytes()
    with pytest.raises(BackupError, match="backup_invalid"):
        bk.restore(str(bad), str(live), force=True)
    assert live.read_bytes() == before and not (tmp_path / "live.db.pre-restore").exists()


def test_stale_revision_and_missing_revision_are_flagged(live, tmp_path):
    old = tmp_path / "old.db"
    bk.backup(str(live), str(old))
    con = sqlite3.connect(old)
    con.execute("update alembic_version set version_num='0001'")
    con.commit()
    con.close()
    assert "revision_not_current_head" in bk.verify(str(old))
    con = sqlite3.connect(old)
    con.execute("drop table alembic_version")
    con.commit()
    con.close()
    assert "no_migration_revision" in bk.verify(str(old))


def test_corrupted_file_fails_verification(live, tmp_path):
    out = tmp_path / "b.db"
    bk.backup(str(live), str(out))
    data = bytearray(out.read_bytes())
    for i in range(4096, min(len(data), 4096 * 3)):
        data[i] = 0xFF
    out.write_bytes(bytes(data))
    assert bk.verify(str(out)) != []


def test_restore_removes_stale_journals(live, tmp_path):
    out = tmp_path / "b.db"
    bk.backup(str(live), str(out))
    (tmp_path / "live.db-wal").write_bytes(b"stale")
    bk.restore(str(out), str(live), force=True)
    assert not (tmp_path / "live.db-wal").exists()


def test_cli_exit_codes(live, tmp_path, capsys):
    out = tmp_path / "b.db"
    assert bk.main(["backup", str(live), str(out)]) == 0
    assert bk.main(["verify", str(out)]) == 0
    assert bk.main(["backup", str(live), str(out)]) == 1
    assert bk.main(["verify", str(tmp_path / "missing.db")]) == 1
    assert bk.main([]) == 2
