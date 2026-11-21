import time
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException, status, Depends, BackgroundTasks, Request
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.apps_script_bridge import apps_script_bridge
from app.config import SALES_LOGIN_MAX_ATTEMPTS, SALES_LOGIN_LOCKOUT_SECONDS
from app.models import LoginRequest, TokenResponse
from app.sheets import db
from app.auth import (
    verify_password,
    create_access_token,
    get_current_user,
    hash_password,
    is_account_active,
    is_account_deactivated,
    password_needs_reset,
    revoke_token,
    require_sheets_connection,
    _validate_authoritative_role,
    _USER_REVOKED_AT,
    security,
)
from app.permissions import ui_role, role_v2_of
from app.timeutil import now_iso

router = APIRouter(tags=["Authentication"])

# In-memory brute force protection tracking failed logins per username
_LOGIN_ATTEMPTS: Dict[str, List[float]] = {}
_MAX_FAILED_ATTEMPTS = SALES_LOGIN_MAX_ATTEMPTS
_LOCKOUT_WINDOW_SECONDS = SALES_LOGIN_LOCKOUT_SECONDS


def _format_lockout_duration(seconds: float) -> str:
    secs = max(1, int(round(seconds)))
    if secs % 60 == 0:
        mins = secs // 60
        return f"{mins} minute" if mins == 1 else f"{mins} minutes"
    return f"{secs} seconds"


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


def _token_for(row: dict) -> TokenResponse:
    raw_user_id = str(row.get("user_id") or "").strip()
    raw_username = str(row.get("username") or "").strip()
    user_id = raw_user_id or raw_username
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account identity is incomplete in AuthUsers. Access denied.",
        )
    username = raw_username or user_id
    authoritative_role = _validate_authoritative_role(row.get("role"), user_id)
    role = ui_role(authoritative_role)
    full_name = str(row.get("full_name") or raw_username or user_id)
    must_change = str(row.get("must_change_password", "false")).strip().lower() == "true"
    token = create_access_token({
        "sub": user_id,
        "user_id": user_id,
        "username": username,
        "full_name": full_name,
        "role": authoritative_role,
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
        duration_label = _format_lockout_duration(_LOCKOUT_WINDOW_SECONDS)
        raise HTTPException(
            status_code=getattr(status, "HTTP_429_TOO_MANY_REQUESTS", 429),
            detail=f"Account temporarily locked due to repeated failed login attempts. Please wait {duration_label} before trying again.",
        )

    try:
        auth_records = db.get_records("AuthUsers", fresh=True)
    except Exception as exc:
        err_str = str(exc).lower()
        if "429" in err_str or "quota" in err_str:
            raise HTTPException(
                status_code=getattr(status, "HTTP_429_TOO_MANY_REQUESTS", 429),
                detail="Google Sheets API quota temporarily exceeded. Please wait 10-15 seconds and try signing in again.",
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not verify login credentials with Google Sheets.",
        )
    if not isinstance(auth_records, list):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication store returned malformed data. Access denied.",
        )
    if not auth_records:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No login accounts exist yet. The owner must create the first account with the local reset/bootstrap script. Passwordless login is disabled.",
        )

    matching_accounts = []
    for auth in auth_records:
        if not isinstance(auth, dict):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Authentication store contains malformed records. Access denied.",
            )
        if str(auth.get("username", "")).strip().lower() == username:
            matching_accounts.append(auth)

    if len(matching_accounts) > 1:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ambiguous login identity detected in AuthUsers. Sign-in blocked until resolved by Owner.",
        )

    match = None
    if matching_accounts:
        auth = matching_accounts[0]
        if not is_account_active(auth.get("active")):
            raise HTTPException(status_code=403, detail="Account is deactivated or inactive")
        stored = str(auth.get("password_hash", ""))
        if password_needs_reset(stored):
            raise HTTPException(
                status_code=403,
                detail="This account still has a legacy password and cannot sign in. An owner must set a new password with backend/scripts/reset_password.py.",
            )
        if verify_password(req.password, stored):
            match = auth
        else:
            past_attempts.append(now_ts)
            _LOGIN_ATTEMPTS[username] = past_attempts
            raise HTTPException(status_code=401, detail="Invalid username or password")

    if not match:
        past_attempts.append(now_ts)
        _LOGIN_ATTEMPTS[username] = past_attempts
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # Validate authoritative role BEFORE minting token (AUTH-02: never default missing/invalid role).
    token_resp = _token_for(match)

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
    return token_resp


@router.post("/api/auth/logout")
@router.post("/auth/logout")
async def logout(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    current_user: dict = Depends(get_current_user),
):
    user_id = str(current_user.get("user_id") or "")
    persisted = True
    if credentials and credentials.credentials:
        persisted = revoke_token(credentials.credentials, user_id, reason="User logged out")
    db.log_audit(user_id, "LOGOUT", "AuthUsers", user_id, reason="User logged out and session revoked")
    if not persisted:
        return {
            "ok": True,
            "persisted": False,
            "warning": "Token revoked in local process memory only; persistent RevokedTokens bridge write did not confirm.",
            "message": "Signed out locally; persistent cross-worker revocation could not be confirmed.",
        }
    return {"ok": True, "message": "Signed out and session revoked successfully", "persisted": True}


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


@router.post("/api/auth/change-password", dependencies=[Depends(require_sheets_connection)])
async def change_password(req: ChangePasswordRequest, request: Request, current_user: dict = Depends(get_current_user)):
    user_id = str(current_user.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="Authenticated user identity is missing user_id.")
    rows = db.get_records("AuthUsers", fresh=True)
    if not isinstance(rows, list):
        raise HTTPException(status_code=503, detail="Unable to verify account credentials from AuthUsers.")
    matches = []
    for row in rows:
        if not isinstance(row, dict):
            raise HTTPException(status_code=503, detail="AuthUsers contains malformed records. Password change blocked.")
        if str(row.get("user_id") or "").strip() == user_id:
            matches.append(row)
    if len(matches) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ambiguous identity: Multiple authentication records exist for this account. Password change blocked.",
        )
    if not matches:
        raise HTTPException(status_code=404, detail="Login account not found")
    match = matches[0]
    if not verify_password(req.current_password, str(match.get("password_hash", ""))):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    if req.new_password == req.current_password:
        raise HTTPException(status_code=422, detail="Choose a different password")

    revoke_ts = now_iso()
    res = apps_script_bridge.delegate_governed_write(
        action="CHANGE_PASSWORD",
        target_tab="AuthUsers",
        payload={
            "user_id": user_id,
            "password_hash": hash_password(req.new_password),
            "must_change_password": "false",
            "sessions_revoked_at": revoke_ts,
            "revoke_all_sessions": True,
        },
        request=request,
        actor_user_id=user_id,
        actor_role=role_v2_of(current_user),
        id_field="user_id",
        invalidate_tabs=["AuthUsers"],
    )
    _USER_REVOKED_AT[user_id.strip().lower()] = time.time()
    db.log_audit(user_id, "CHANGE_PASSWORD", "AuthUsers", user_id, reason="User changed password and invalidated prior sessions")
    return {"ok": True, **res}

