"""Authenticated encryption for stored credentials (AES-256-GCM).

Envelope: "v1.<key_id>.<base64url(nonce || ciphertext+tag)>". Keys are derived from the root
secret (purpose "credentials"). The AAD binds a ciphertext to its workspace and credential
row, so a blob copied to another row or workspace fails authentication. Previous root
secrets are accepted for decryption only, so a key change doesn't brick stored credentials.
"""
import base64
import hashlib
import os
from typing import Iterable

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import Settings
from app.security.tokens import derive_key

_VERSION = "v1"


class DecryptionError(Exception):
    """Wrong key, tampering, wrong binding, or malformed token. Never carries the data."""


def _key_id(key: bytes) -> str:
    return hashlib.sha256(b"key-id:" + key).hexdigest()[:8]


class CredentialCipher:
    def __init__(self, settings: Settings):
        self._current = derive_key(settings, "credentials")
        self._by_id = {_key_id(self._current): self._current}
        for old in settings.previous_secret_keys:
            k = derive_key(settings.model_copy(update={"app_secret_key": old}), "credentials")
            self._by_id.setdefault(_key_id(k), k)
        self.current_key_id = _key_id(self._current)

    def encrypt(self, plaintext: str, aad: str) -> str:
        nonce = os.urandom(12)
        ct = AESGCM(self._current).encrypt(nonce, plaintext.encode("utf-8"), aad.encode("utf-8"))
        return f"{_VERSION}.{self.current_key_id}.{base64.urlsafe_b64encode(nonce + ct).decode()}"

    def decrypt(self, token: str, aad: str) -> str:
        try:
            version, key_id, blob = token.split(".")
            key = self._by_id.get(key_id)
            if version != _VERSION or key is None:
                raise DecryptionError("unknown key or version")
            raw = base64.urlsafe_b64decode(blob)
            return AESGCM(key).decrypt(raw[:12], raw[12:], aad.encode("utf-8")).decode("utf-8")
        except DecryptionError:
            raise
        except (InvalidTag, ValueError, UnicodeError) as exc:
            raise DecryptionError("cannot decrypt") from exc

    def uses_current_key(self, token: str) -> bool:
        parts = token.split(".")
        return len(parts) == 3 and parts[1] == self.current_key_id


def credential_aad(workspace_id: str, credential_id: str) -> str:
    return f"{workspace_id}:{credential_id}"
