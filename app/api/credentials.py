"""Credential endpoints. Write-only for secrets: no endpoint ever returns one."""
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.config import get_settings
from app.connectors import registry as connector_registry
from app.connectors import workspace as ws_connectors
from app.connectors.errors import ConnectorConfigError
from app.credentials_service import (CredentialError, CredentialExistsError, CredentialNotFoundError,
                                     CredentialRevokedError, CredentialService)
from app.database import get_db
from app.identity.context import WorkspaceContext, require_permission
from app.llm.credentials import LLM_CREDENTIAL_PROVIDER, validate_llm_config
from app.llm.errors import LLMConfigError
from app.schemas_credentials import ConnectionTestOut, CredentialCreate, CredentialOut, CredentialRotate

router = APIRouter(prefix="/workspaces/{workspace_id}/credentials", tags=["credentials"])

_STATUS = {CredentialNotFoundError: 404, CredentialExistsError: 409, CredentialRevokedError: 409}


def _http(exc: CredentialError) -> HTTPException:
    return HTTPException(_STATUS.get(type(exc), 400), str(exc))


@router.post("", response_model=CredentialOut, status_code=status.HTTP_201_CREATED)
def create_credential(body: CredentialCreate, ctx: WorkspaceContext = Depends(require_permission("connection:write")),
                      db: Session = Depends(get_db)):
    try:
        if body.provider == LLM_CREDENTIAL_PROVIDER:
            validate_llm_config(body.config, get_settings())
        else:
            connector_registry.validate_config(body.provider, body.config, get_settings())
    except (ConnectorConfigError, LLMConfigError) as exc:
        raise HTTPException(422, f"Invalid connection config: {exc}")
    try:
        return CredentialService(db).create(ctx.workspace.id, ctx.user, provider=body.provider, name=body.name,
                                            secret=body.secret.get_secret_value(), config=body.config)
    except CredentialError as exc:
        raise _http(exc)


@router.get("", response_model=list[CredentialOut])
def list_credentials(ctx: WorkspaceContext = Depends(require_permission("connection:read")),
                     db: Session = Depends(get_db)):
    return CredentialService(db).list(ctx.workspace.id)


@router.get("/{credential_id}", response_model=CredentialOut)
def get_credential(credential_id: str, ctx: WorkspaceContext = Depends(require_permission("connection:read")),
                   db: Session = Depends(get_db)):
    try:
        return CredentialService(db).get(ctx.workspace.id, credential_id)
    except CredentialError as exc:
        raise _http(exc)


@router.post("/{credential_id}/rotate", response_model=CredentialOut)
def rotate_credential(credential_id: str, body: CredentialRotate,
                      ctx: WorkspaceContext = Depends(require_permission("connection:write")),
                      db: Session = Depends(get_db)):
    try:
        return CredentialService(db).rotate(ctx.workspace.id, credential_id, ctx.user, body.secret.get_secret_value())
    except CredentialError as exc:
        raise _http(exc)


@router.delete("/{credential_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke_credential(credential_id: str, ctx: WorkspaceContext = Depends(require_permission("connection:write")),
                      db: Session = Depends(get_db)):
    try:
        CredentialService(db).revoke(ctx.workspace.id, credential_id, ctx.user)
    except CredentialError as exc:
        raise _http(exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{credential_id}/test", response_model=ConnectionTestOut)
def test_connection(credential_id: str, ctx: WorkspaceContext = Depends(require_permission("connection:test")),
                    db: Session = Depends(get_db)):
    """Makes one outbound call with the stored credential (admin/owner only, rate-limited)."""
    try:
        return ws_connectors.test_credential(db, get_settings(), ctx.workspace.id, credential_id, ctx.user)
    except ws_connectors.TestTooSoonError as exc:
        raise HTTPException(429, str(exc))
    except ws_connectors.UnsupportedProviderError as exc:
        raise HTTPException(400, str(exc))
    except CredentialError as exc:
        raise _http(exc)
