"""CredentialService: the only code that encrypts or decrypts stored secrets.

Everything is scoped by workspace_id. `reveal_secret` is for server-side connector
construction only (4.5) and is never exposed through an API.
"""
import uuid
from typing import List

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.kernel.audit import record_event
from app.models.base import utcnow
from app.models.credentials import Credential
from app.models.identity import User
from app.security.crypto import CredentialCipher, DecryptionError, credential_aad  # noqa: F401


class CredentialError(Exception):
    pass


class CredentialNotFoundError(CredentialError): ...
class CredentialExistsError(CredentialError): ...
class CredentialRevokedError(CredentialError): ...


class CredentialService:
    def __init__(self, db: Session, settings: Settings | None = None):
        self.db = db
        self.cipher = CredentialCipher(settings or get_settings())

    def create(self, workspace_id: str, actor: User, *, provider: str, name: str, secret: str,
               config: dict | None = None) -> Credential:
        cid = str(uuid.uuid4())
        cred = Credential(id=cid, workspace_id=workspace_id, provider=provider, name=name,
                          config=config or {}, created_by=actor.id,
                          secret_ciphertext=self.cipher.encrypt(secret, credential_aad(workspace_id, cid)))
        self.db.add(cred)
        try:
            self.db.flush()
        except IntegrityError:
            self.db.rollback()
            raise CredentialExistsError("A credential with this provider and name already exists")
        self._audit(cred, "credential.created", actor)
        self.db.commit()
        return cred

    def get(self, workspace_id: str, credential_id: str) -> Credential:
        cred = self.db.scalar(select(Credential).where(Credential.id == credential_id,
                                                       Credential.workspace_id == workspace_id))
        if cred is None:
            raise CredentialNotFoundError("Credential not found")
        return cred

    def list(self, workspace_id: str) -> List[Credential]:
        return list(self.db.scalars(select(Credential).where(Credential.workspace_id == workspace_id)
                                    .order_by(Credential.created_at)))

    def rotate(self, workspace_id: str, credential_id: str, actor: User, new_secret: str) -> Credential:
        cred = self._locked(workspace_id, credential_id)
        if not cred.is_active:
            raise CredentialRevokedError("Credential is revoked")
        cred.version += 1
        cred.rotated_at = utcnow()
        cred.secret_ciphertext = self.cipher.encrypt(new_secret, credential_aad(workspace_id, cred.id))
        self._audit(cred, "credential.rotated", actor)
        self.db.commit()
        return cred

    def revoke(self, workspace_id: str, credential_id: str, actor: User) -> Credential:
        cred = self._locked(workspace_id, credential_id)
        if cred.is_active:
            cred.is_active, cred.secret_ciphertext, cred.revoked_at = False, None, utcnow()
            self._audit(cred, "credential.revoked", actor)
            self.db.commit()
        return cred

    def reveal_secret(self, workspace_id: str, credential_id: str) -> str:
        """Server-side only. Raises if revoked or if the ciphertext fails authentication."""
        cred = self.get(workspace_id, credential_id)
        if not cred.is_active or not cred.secret_ciphertext:
            raise CredentialRevokedError("Credential is revoked")
        return self.cipher.decrypt(cred.secret_ciphertext, credential_aad(workspace_id, cred.id))

    def record_test(self, workspace_id: str, credential_id: str, actor: User, *, ok: bool, message: str) -> bool:
        cred = self._locked(workspace_id, credential_id)
        cred.last_tested_at, cred.last_test_ok, cred.last_test_message = utcnow(), ok, message
        record_event(self.db, workspace_id=workspace_id, event_type="connection.tested", actor=actor.id,
                     payload={"credential_id": cred.id, "provider": cred.provider, "ok": ok, "message": message})
        self.db.commit()
        return True

    def reencrypt_all(self) -> int:
        """Re-encrypt every active credential under the current key. Returns rows changed."""
        n = 0
        for cred in self.db.scalars(select(Credential).where(Credential.is_active.is_(True))).all():
            if cred.secret_ciphertext and not self.cipher.uses_current_key(cred.secret_ciphertext):
                aad = credential_aad(cred.workspace_id, cred.id)
                cred.secret_ciphertext = self.cipher.encrypt(self.cipher.decrypt(cred.secret_ciphertext, aad), aad)
                n += 1
        self.db.commit()
        return n

    def _locked(self, workspace_id: str, credential_id: str) -> Credential:
        cred = self.db.scalar(select(Credential).where(Credential.id == credential_id,
                                                       Credential.workspace_id == workspace_id).with_for_update())
        if cred is None:
            raise CredentialNotFoundError("Credential not found")
        return cred

    def _audit(self, cred: Credential, event: str, actor: User) -> None:
        record_event(self.db, workspace_id=cred.workspace_id, event_type=event, actor=actor.id,
                     payload={"credential_id": cred.id, "provider": cred.provider, "name": cred.name,
                              "version": cred.version})
