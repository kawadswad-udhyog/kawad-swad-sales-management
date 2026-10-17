from fastapi import APIRouter, HTTPException, status, Depends, BackgroundTasks
from app.models import (
    LoginRequest,
    TokenResponse,
    UserProfile,
)
from app.sheets import db
from app.auth import verify_password, create_access_token, get_current_user, hash_password

router = APIRouter(tags=["Authentication"])


@router.post("/api/auth/login", response_model=TokenResponse)
@router.post("/auth/login", response_model=TokenResponse)
async def login(req: LoginRequest, background_tasks: BackgroundTasks):
    auth_records = db.get_records("AuthUsers")
    user_match = None

    for auth in auth_records:
        if auth.get("username", "").strip().lower() == req.username.strip().lower():
            if str(auth.get("active", "true")).lower() == "false":
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is deactivated")
            if verify_password(req.password, auth.get("password_hash", "")):
                user_match = auth
                break

    if not user_match:
        # Check standard Users tab for development fallback
        users = db.get_records("Users")
        for u in users:
            if u.get("user_id", "").strip().lower() == req.username.strip().lower() or \
               u.get("full_name", "").strip().lower() == req.username.strip().lower():
                # Allow dev login if no AuthUsers records exist yet
                if len(auth_records) == 0:
                    user_match = {
                        "user_id": u.get("user_id"),
                        "username": req.username,
                        "full_name": u.get("full_name"),
                        "role": u.get("role", "SALESMAN"),
                    }
                    break

    if not user_match:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")

    user_id = user_match.get("user_id")
    role = user_match.get("role", "SALESMAN")
    full_name = user_match.get("full_name", user_id)

    token_data = {
        "sub": user_id,
        "user_id": user_id,
        "full_name": full_name,
        "role": role,
    }
    access_token = create_access_token(token_data)

    # Authentication must not wait for a Google Sheets audit write. Sheets
    # latency can otherwise make valid credentials look like failed logins.
    background_tasks.add_task(
        db.log_audit,
        actor=user_id,
        action="LOGIN",
        entity_type="AuthUsers",
        entity_id=user_id,
        reason="User successfully authenticated",
    )

    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        user_id=user_id,
        full_name=full_name,
        role=role,
    )

@router.get("/api/auth/me")
@router.get("/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {
        "user_id": current_user.get("user_id"),
        "full_name": current_user.get("full_name"),
        "role": current_user.get("role"),
    }
