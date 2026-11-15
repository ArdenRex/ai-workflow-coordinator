"""Password hashing (stdlib scrypt, no extra dependency) and password policy.

Stored format: scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>. Parameters are embedded so they
can be raised later and old hashes still verify (see needs_rehash).
"""
import base64
import hashlib
import hmac
import os

N, R, P = 2 ** 14, 8, 1
_DKLEN = 32
_MAXMEM = 64 * 1024 * 1024
MIN_LEN, MAX_LEN = 10, 128


class WeakPasswordError(ValueError):
    pass


def validate_password_strength(password: str) -> str:
    if not isinstance(password, str) or not (MIN_LEN <= len(password) <= MAX_LEN):
        raise WeakPasswordError(f"Password must be {MIN_LEN}-{MAX_LEN} characters")
    if not password.strip():
        raise WeakPasswordError("Password cannot be blank")
    return password


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=_DKLEN, maxmem=_MAXMEM)


def hash_password(password: str) -> str:
    validate_password_strength(password)
    salt = os.urandom(16)
    digest = _derive(password, salt, N, R, P)
    b64 = lambda b: base64.b64encode(b).decode()
    return f"scrypt${N}${R}${P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, stored: str | None) -> bool:
    """Constant-time check. Any malformed/empty hash simply returns False."""
    try:
        if not stored or not isinstance(password, str) or len(password) > 1024:
            return False
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        n, r, p = int(n), int(r), int(p)
        if n > 2 ** 20 or r > 32 or p > 16:          # refuse absurd cost from a corrupted row
            return False
        expected = base64.b64decode(hash_b64)
        actual = _derive(password, base64.b64decode(salt_b64), n, r, p)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def needs_rehash(stored: str) -> bool:
    try:
        _, n, r, p, *_ = stored.split("$")
        return (int(n), int(r), int(p)) != (N, R, P)
    except Exception:
        return True


# Verified against when the account doesn't exist, so response time doesn't reveal it.
_DUMMY_HASH = hash_password("dummy-password-for-timing")


def burn_verify(password: str) -> None:
    verify_password(password, _DUMMY_HASH)
