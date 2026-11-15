import pytest

from app.config import Settings
from app.security.crypto import CredentialCipher, DecryptionError, credential_aad

K1, K2 = "k1-" + "a" * 40, "k2-" + "b" * 40


def S(key=K1, prev=""):
    return Settings(app_env="test", database_url="sqlite:///:memory:", app_secret_key=key,
                    app_secret_key_previous=prev, _env_file=None)


def test_roundtrip_nonce_and_no_plaintext():
    c, aad = CredentialCipher(S()), credential_aad("w", "c")
    t1, t2 = c.encrypt("sk-live-123", aad), c.encrypt("sk-live-123", aad)
    assert t1 != t2 and "sk-live-123" not in t1 and t1.startswith("v1.")
    assert c.decrypt(t1, aad) == "sk-live-123"


def test_binding_to_workspace_and_credential():
    c = CredentialCipher(S())
    t = c.encrypt("secret", credential_aad("w1", "c1"))
    for aad in (credential_aad("w2", "c1"), credential_aad("w1", "c2")):
        with pytest.raises(DecryptionError):
            c.decrypt(t, aad)


def test_tamper_and_garbage():
    c, aad = CredentialCipher(S()), credential_aad("w", "c")
    t = c.encrypt("secret", aad)
    flipped = t[:-3] + ("AAA" if not t.endswith("AAA") else "BBB")
    for bad in (flipped, "", "v1", "v1.x.y", "v2." + t.split(".", 1)[1], "a.b.c.d"):
        with pytest.raises(DecryptionError):
            c.decrypt(bad, aad)


def test_wrong_key_fails_and_previous_key_decrypts():
    aad = credential_aad("w", "c")
    old = CredentialCipher(S(K1)).encrypt("secret", aad)
    with pytest.raises(DecryptionError):
        CredentialCipher(S(K2)).decrypt(old, aad)
    new = CredentialCipher(S(K2, prev=K1))
    assert new.decrypt(old, aad) == "secret" and not new.uses_current_key(old)
    assert new.uses_current_key(new.encrypt("x", aad))


def test_unicode_and_long_secret():
    c, aad = CredentialCipher(S()), credential_aad("w", "c")
    for s in ("pässwörd-日本語", "x" * 4096):
        assert c.decrypt(c.encrypt(s, aad), aad) == s


def test_previous_key_validation_in_production():
    with pytest.raises(ValueError):
        Settings(app_env="production", database_url="postgresql://x/y", app_secret_key=K1,
                 app_secret_key_previous="short", _env_file=None)
