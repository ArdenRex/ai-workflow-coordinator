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

# This import is now safe because integrations.py moved its auth import inside a function
from app.routers import integrations as integrations_router

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["Auth"])

# ... Rest of your existing auth.py code (login, register, logout, etc.)