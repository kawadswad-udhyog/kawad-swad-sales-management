import time
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, status, Depends, BackgroundTasks
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.models import LoginRequest, TokenResponse
from app.sheets import db
from app.auth import (
    verify_password,
    create_access_token,
    get_current_user,
    hash_password,
    password_needs_reset,
    revoke_token,
    revoke_all_user_sessions,
    security,
)
from app.permissions import ui_role

router = APIRouter(tags=["Authentication"])

# In-memory brute force protection tracking failed logins per username
_LOGIN_ATTEMPTS: Dict[str, List[float]] = {}
_MAX_FAILED_ATTEMPTS = 5
_LOCKOUT_WINDOW_SECONDS = 120.0  # 2 minutes


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


def _token_for(row: dict) -> TokenResponse:
    raw_user_id = str(row.get("user_id") or "").strip()
    raw_username = str(row.get("username") or "").strip()
    user_id = raw_user_id or raw_username or "user"
    username = raw_username or raw_user_id or user_id
    role = ui_role(str(row.get("role") or "SALESMAN"))
    full_name = str(row.get("full_name") or raw_username or user_id)
    must_change = str(row.get("must_change_password", "false")).lower() == "true"
    token = create_access_token({
        "sub": user_id,
        "user_id": user_id,
        "username": username,
        "full_name": full_name,
        "role": str(row.get("role") or role),
        "must_change_password": must_change,
    })
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user_id=user_id,
        full_name=full_name,
        role=role,
        must_change_password=must_change,
    )


@router.post("/api/auth/login", response_model=TokenResponse)
@router.post("/auth/login", response_model=TokenResponse)
async def login(req: LoginRequest, background_tasks: BackgroundTasks):
    username = req.username.strip().lower()
    if not username or not req.password:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # Brute-force rate limiting check
    now_ts = time.time()
    past_attempts = [t for t in _LOGIN_ATTEMPTS.get(username, []) if now_ts - t < _LOCKOUT_WINDOW_SECONDS]
    _LOGIN_ATTEMPTS[username] = past_attempts
    if len(past_attempts) >= _MAX_FAILED_ATTEMPTS:
        raise HTTPException(
            status_code=getattr(status, "HTTP_429_TOO_MANY_REQUESTS", 429),
            detail="Account temporarily locked due to repeated failed login attempts. Please wait 5 minutes before trying again.",
        )

    try:
        auth_records = db.get_records("AuthUsers", fresh=False)
    except Exception as exc:
        err_str = str(exc).lower()
        if "429" in err_str or "quota" in err_str:
            raise HTTPException(
                status_code=getattr(status, "HTTP_429_TOO_MANY_REQUESTS", 429),
                detail="Google Sheets API quota temporarily exceeded. Please wait 10-15 seconds and try signing in again.",
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Could not verify login credentials with Google Sheets: {exc}",
        )
    if not auth_records:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No login accounts exist yet. The owner must create the first account with the local reset/bootstrap script. Passwordless login is disabled.",
        )
    match = None
    for auth in auth_records:
        if str(auth.get("username", "")).strip().lower() != username:
            continue
        if str(auth.get("active", "true")).lower() == "false":
            raise HTTPException(status_code=403, detail="Account is deactivated")
        stored = str(auth.get("password_hash", ""))
        if password_needs_reset(stored):
            raise HTTPException(
                status_code=403,
                detail="This account still has a legacy password and cannot sign in. An owner must set a new password with backend/scripts/reset_password.py.",
            )
        if verify_password(req.password, stored):
            match = auth
            break
        # Record failed attempt
        past_attempts.append(now_ts)
        _LOGIN_ATTEMPTS[username] = past_attempts
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not match:
        past_attempts.append(now_ts)
        _LOGIN_ATTEMPTS[username] = past_attempts
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # Clear failed attempts on successful login
    _LOGIN_ATTEMPTS.pop(username, None)

    background_tasks.add_task(
        db.log_audit,
        actor=match.get("user_id"),
        action="LOGIN",
        entity_type="AuthUsers",
        entity_id=str(match.get("user_id")),
        reason="User successfully authenticated",
    )
    return _token_for(match)


@router.post("/api/auth/logout")
@router.post("/auth/logout")
async def logout(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user.get("user_id") or "")
    if credentials and credentials.credentials:
        revoke_token(credentials.credentials, user_id, reason="User logged out")
    db.log_audit(user_id, "LOGOUT", "AuthUsers", user_id, reason="User logged out and session revoked")
    return {"ok": True, "message": "Signed out and session revoked successfully"}


@router.get("/api/auth/me")
@router.get("/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {
        "user_id": current_user.get("user_id"),
        "full_name": current_user.get("full_name"),
        "username": current_user.get("username"),
        "role": ui_role(str(current_user.get("role") or "")),
        "must_change_password": bool(current_user.get("must_change_password")),
    }


@router.post("/api/auth/change-password")
async def change_password(req: ChangePasswordRequest, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user.get("user_id") or "")
    rows = db.get_records("AuthUsers", fresh=True)
    match = next((row for row in rows if str(row.get("user_id")) == user_id), None)
    if not match:
        raise HTTPException(status_code=404, detail="Login account not found")
    if not verify_password(req.current_password, str(match.get("password_hash", ""))):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if req.new_password == req.current_password:
        raise HTTPException(status_code=422, detail="Choose a different password")
    
    # Invalidate all existing sessions across devices
    revoke_all_user_sessions(user_id, reason="User changed password")

    updated = db.update_record("AuthUsers", "user_id", user_id, {
        "password_hash": hash_password(req.new_password),
        "must_change_password": "false",
    }, raise_on_error=True)
    if not updated:
        raise HTTPException(status_code=503, detail="Password was not saved. Try again.")
    db.log_audit(user_id, "CHANGE_PASSWORD", "AuthUsers", user_id, reason="User changed password and invalidated prior sessions")
    return {"ok": True}
