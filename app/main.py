# ... (imports stay the same)

router = APIRouter(prefix="/auth", tags=["Auth"])

@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest, 
    response: Response, 
    db: Session = Depends(get_db)
):
    """
    Email + password login.
    """
    user = crud.get_user_by_email(db, email=payload.email)
    if not user or not user.verify_password(payload.password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )
    
    # ... (rest of your login logic)