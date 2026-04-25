"""
routers/locale.py
──────────────────
Segment 12 — Multi-language, multi-timezone, multi-currency.

Endpoints:
  GET  /locale/options              All supported languages, timezones, currencies
  GET  /locale/settings             Current user's locale prefs
  PUT  /locale/settings             Update current user's locale prefs
  GET  /locale/workspace            Workspace-level locale defaults (Architect)
  PUT  /locale/workspace            Update workspace locale defaults (Architect only)
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import UserRole
from app.routers.auth import get_current_user
from app.schemas import (
    LocaleOptionsResponse,
    UserLocaleResponse,
    UserLocaleUpdate,
    WorkspaceLocaleResponse,
    WorkspaceLocaleUpdate,
    SUPPORTED_LANGUAGES,
    SUPPORTED_CURRENCIES,
    SUPPORTED_TIMEZONES,
)
from app import crud

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/locale", tags=["Locale"])


# ── GET /locale/options ────────────────────────────────────────────────────────

@router.get("/options", response_model=LocaleOptionsResponse)
async def get_locale_options():
    """
    Returns all supported languages, timezones, and currencies.
    Used by the frontend to populate dropdowns — no auth required.
    """
    return LocaleOptionsResponse(
        languages=SUPPORTED_LANGUAGES,
        timezones=SUPPORTED_TIMEZONES,
        currencies=SUPPORTED_CURRENCIES,
    )


# ── GET /locale/settings ───────────────────────────────────────────────────────

@router.get("/settings", response_model=UserLocaleResponse)
async def get_user_locale_settings(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the current user's locale preferences."""
    locale = crud.get_user_locale(db, current_user.id)
    return UserLocaleResponse(
        user_id=current_user.id,
        language=locale["language"],
        language_label=SUPPORTED_LANGUAGES.get(locale["language"], locale["language"]),
        timezone=locale["timezone"],
        currency=locale["currency"],
        currency_label=SUPPORTED_CURRENCIES.get(locale["currency"], locale["currency"]),
    )


# ── PUT /locale/settings ───────────────────────────────────────────────────────

@router.put("/settings", response_model=UserLocaleResponse)
async def update_user_locale_settings(
    body: UserLocaleUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update the current user's language, timezone, and/or currency."""
    if not body.language and not body.timezone and not body.currency:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one of language, timezone, or currency must be provided.",
        )
    locale = crud.save_user_locale(
        db,
        user_id=current_user.id,
        language=body.language,
        timezone=body.timezone,
        currency=body.currency,
    )
    return UserLocaleResponse(
        user_id=current_user.id,
        language=locale["language"],
        language_label=SUPPORTED_LANGUAGES.get(locale["language"], locale["language"]),
        timezone=locale["timezone"],
        currency=locale["currency"],
        currency_label=SUPPORTED_CURRENCIES.get(locale["currency"], locale["currency"]),
    )


# ── GET /locale/workspace ──────────────────────────────────────────────────────

@router.get("/workspace", response_model=WorkspaceLocaleResponse)
async def get_workspace_locale_settings(
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return workspace-level locale defaults. Visible to all workspace members."""
    if not current_user.workspace_id:
        raise HTTPException(status_code=400, detail="User has no workspace.")
    locale = crud.get_workspace_locale(db, current_user.workspace_id)
    return WorkspaceLocaleResponse(
        workspace_id=current_user.workspace_id,
        default_language=locale["default_language"],
        default_language_label=SUPPORTED_LANGUAGES.get(locale["default_language"], locale["default_language"]),
        default_timezone=locale["default_timezone"],
        default_currency=locale["default_currency"],
        default_currency_label=SUPPORTED_CURRENCIES.get(locale["default_currency"], locale["default_currency"]),
    )


# ── PUT /locale/workspace ──────────────────────────────────────────────────────

@router.put("/workspace", response_model=WorkspaceLocaleResponse)
async def update_workspace_locale_settings(
    body: WorkspaceLocaleUpdate,
    current_user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Update workspace-level locale defaults. Architect only."""
    if current_user.role != UserRole.architect:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only Architects can update workspace locale settings.",
        )
    if not current_user.workspace_id:
        raise HTTPException(status_code=400, detail="User has no workspace.")
    if not body.default_language and not body.default_timezone and not body.default_currency:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one of default_language, default_timezone, or default_currency must be provided.",
        )
    locale = crud.save_workspace_locale(
        db,
        workspace_id=current_user.workspace_id,
        default_language=body.default_language,
        default_timezone=body.default_timezone,
        default_currency=body.default_currency,
    )
    return WorkspaceLocaleResponse(
        workspace_id=current_user.workspace_id,
        default_language=locale["default_language"],
        default_language_label=SUPPORTED_LANGUAGES.get(locale["default_language"], locale["default_language"]),
        default_timezone=locale["default_timezone"],
        default_currency=locale["default_currency"],
        default_currency_label=SUPPORTED_CURRENCIES.get(locale["default_currency"], locale["default_currency"]),
    )
