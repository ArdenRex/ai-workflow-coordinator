"""
app/routers/auth.py
────────────────────
Authentication endpoints.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

import httpx
from pydantic import BaseModel
from fastapi import APIRouter, Cookie, Depends, HTTPException, Query, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import crud
from app.auth import (
    create_access_token,
    create_refresh_token,
    get_current_user,
    decode_token,
)
from app.database import get_db
from app.models import User, UserRole, FreelancerRequest, Freelancer
from app.schemas import (
    LoginRequest,
    OnboardingRequest,
    OnboardingResponse,
    RegisterRequest,
    RegisterResponse,
    TokenResponse,
    UserResponse,
    WorkspaceResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["Auth"])

# ─── Auth Logic ───────────────────────────────────────────────────────────────

@router.post("/register", response_model=RegisterResponse)
def register(req: RegisterRequest, db: Session = Depends(get_db)):
    try:
        user = crud.create_user(db, email=req.email, password=req.password)
        access_token = create_access_token(data={"sub": user.email})
        return {"access_token": access_token, "token_type": "bearer", "user": user}
    except IntegrityError:
        raise HTTPException(status_code=400, detail="Email already registered")

@router.post("/login")
def login(response: Response, req: LoginRequest, db: Session = Depends(get_db)):
    user = crud.authenticate_user(db, req.email, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    access_token = create_access_token(data={"sub": user.email})
    refresh_token = create_refresh_token(data={"sub": user.email})

    response.set_cookie(
        key="refresh_token",
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="none",
        max_age=7 * 24 * 3600,
    )

    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {
            "id": user.id,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role,
            "onboarding_completed": user.onboarding_completed,
        }
    }

@router.post("/logout")
def logout(response: Response):
    response.delete_cookie("refresh_token", httponly=True, secure=True, samesite="none")
    return {"detail": "Logged out"}

@router.get("/me", response_model=UserResponse)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user

@router.post("/refresh")
def refresh_token_endpoint(response: Response, refresh_token: str = Cookie(None)):
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Refresh token missing")
    
    payload = decode_token(refresh_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")
    
    email = payload.get("sub")
    new_access_token = create_access_token(data={"sub": email})
    return {"access_token": new_access_token, "token_type": "bearer"}

@router.post("/onboarding", response_model=OnboardingResponse)
def onboarding(
    req: OnboardingRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    # CIRCULAR IMPORT FIX: Import inside the function
    from app.routers import integrations as integrations_router
    
    user = crud.update_user_onboarding(
        db, 
        user_id=current_user.id,
        role=req.role,
        full_name=req.full_name,
        workspace_name=req.workspace_name,
        join_workspace_id=req.join_workspace_id
    )
    return {
        "success": True,
        "user": user,
        "workspace_id": user.workspace_id
    }

@router.get("/billing-status")
def get_billing_status(current_user: User = Depends(get_current_user)):
    now = datetime.now(timezone.utc)
    card_on_file = bool(getattr(current_user, "ls_customer_id", None))

    if current_user.subscription_status == "exempt":
        return {"status": "exempt", "show_wall": False, "card_on_file": True}

    if current_user.subscription_status == "active":
        return {"status": "active", "show_wall": False, "card_on_file": True}

    if current_user.subscription_status == "trialing" and current_user.trial_ends_at:
        trial_end = current_user.trial_ends_at
        if trial_end.tzinfo is None:
            trial_end = trial_end.replace(tzinfo=timezone.utc)
        if trial_end > now:
            days_left = (trial_end - now).days
            return {
                "status": "trialing",
                "show_wall": not card_on_file,
                "card_on_file": card_on_file,
                "days_left": days_left,
                "trial_ends_at": trial_end.isoformat(),
            }

    return {
        "status": current_user.subscription_status,
        "show_wall": True,
        "card_on_file": card_on_file
    }