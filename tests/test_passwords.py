import pytest

from app.security import passwords as pw


def test_hash_verify_roundtrip_and_salting():
    h1, h2 = pw.hash_password("correct horse battery"), pw.hash_password("correct horse battery")
    assert h1 != h2 and h1.startswith("scrypt$")
    assert pw.verify_password("correct horse battery", h1)
    assert not pw.verify_password("wrong password!!", h1)
    assert "correct horse" not in h1


@pytest.mark.parametrize("bad", ["short", " " * 12, "x" * 129, ""])
def test_policy_rejects(bad):
    with pytest.raises(pw.WeakPasswordError):
        pw.hash_password(bad)


@pytest.mark.parametrize("stored", [None, "", "garbage", "bcrypt$1$2$3$a$b", "scrypt$x$8$1$AA==$AA==",
                                    "scrypt$1048576000$8$1$AA==$AA=="])
def test_malformed_hash_is_false_not_error(stored):
    assert pw.verify_password("whatever-password", stored) is False


def test_needs_rehash():
    assert not pw.needs_rehash(pw.hash_password("another good password"))
    assert pw.needs_rehash("scrypt$1024$8$1$AA==$AA==")
    assert pw.needs_rehash("junk")


def test_unicode_password():
    h = pw.hash_password("pässwörd-日本語-ok")
    assert pw.verify_password("pässwörd-日本語-ok", h)
