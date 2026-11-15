from datetime import datetime, timedelta, timezone

import jwt
import pytest

from app.config import Settings
from app.security.tokens import ALGORITHM, InvalidTokenError, create_access_token, decode_access_token, derive_key


@pytest.fixture
def s():
    return Settings(app_env="test", database_url="sqlite:///:memory:", _env_file=None)


def test_roundtrip(s):
    token, ttl = create_access_token(s, "user-1")
    assert ttl == s.access_token_ttl_minutes * 60
    assert decode_access_token(s, token) == "user-1"


def test_expired(s):
    old = datetime.now(timezone.utc) - timedelta(hours=5)
    token, _ = create_access_token(s, "u", now=old)
    with pytest.raises(InvalidTokenError):
        decode_access_token(s, token)


def test_wrong_key_and_tamper(s):
    other = Settings(app_env="test", database_url="sqlite:///:memory:", app_secret_key="x" * 40, _env_file=None)
    token, _ = create_access_token(other, "u")
    with pytest.raises(InvalidTokenError):
        decode_access_token(s, token)
    good, _ = create_access_token(s, "u")
    head, body, sig = good.split(".")
    with pytest.raises(InvalidTokenError):
        decode_access_token(s, f"{head}.{body}.{sig[:-2]}AA")


def test_alg_none_rejected(s):
    forged = jwt.encode({"sub": "u", "typ": "access", "iss": s.jwt_issuer, "iat": 1, "exp": 9999999999},
                        key=None, algorithm="none")
    with pytest.raises(InvalidTokenError):
        decode_access_token(s, forged)


def test_wrong_issuer_type_and_missing_claims(s):
    key = derive_key(s, "jwt")
    now = int(datetime.now(timezone.utc).timestamp())
    base = {"sub": "u", "typ": "access", "iss": s.jwt_issuer, "iat": now, "exp": now + 60}
    for bad in ({**base, "iss": "evil"}, {**base, "typ": "refresh"}, {k: v for k, v in base.items() if k != "sub"},
                {k: v for k, v in base.items() if k != "exp"}, {**base, "sub": ""}):
        with pytest.raises(InvalidTokenError):
            decode_access_token(s, jwt.encode(bad, key, algorithm=ALGORITHM))


def test_garbage(s):
    for t in ("", "abc", "a.b.c"):
        with pytest.raises(InvalidTokenError):
            decode_access_token(s, t)


def test_derived_key_is_purpose_bound(s):
    assert derive_key(s, "jwt") != derive_key(s, "credentials")
    assert derive_key(s, "jwt") != s.app_secret_key.encode()
