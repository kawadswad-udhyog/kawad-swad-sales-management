from fastapi import APIRouter, HTTPException, status, Depends, BackgroundTasks
from pydantic import BaseModel, Field

from app.models import LoginRequest, TokenResponse
from app.sheets import db
from app.auth import verify_password, create_access_token, get_current_user, hash_password, password_needs_reset
from app.permissions import ui_role

router = APIRouter(tags=["Authentication"])


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=8, max_length=128)


def _token_for(row: dict) -> TokenResponse:
    user_id = str(row.get("user_id") or "")
    username = str(row.get("username") or user_id)
    role = ui_role(str(row.get("role") or "SALESMAN"))
    full_name = str(row.get("full_name") or user_id)
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
        username=username,
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
    try:
        auth_records = db.get_records("AuthUsers", fresh=False)
    except Exception as exc:
        err_str = str(exc).lower()
        if "429" in err_str or "quota" in err_str:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
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
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not match:
        raise HTTPException(status_code=401, detail="Invalid username or password")

    # Match login credentials to exactly one staff profile using immutable user_id.
    try:
        profiles = db.get_records("Users", fresh=False)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Could not verify the staff profile. Please retry shortly.") from exc
    user_id = str(match.get("user_id") or "").strip()
    profile_matches = [r for r in profiles if str(r.get("user_id") or "").strip() == user_id]
    if len(profile_matches) != 1:
        raise HTTPException(status_code=409, detail="Account mismatch: login account must match exactly one staff profile. Ask the owner to review Users and AuthUsers.")
    profile = profile_matches[0]
    if str(profile.get("active", "true")).strip().lower() in {"false", "0", "no", "inactive"}:
        raise HTTPException(status_code=403, detail="Staff profile is deactivated")
    auth_role = ui_role(str(match.get("role") or ""))
    profile_role = ui_role(str(profile.get("role") or ""))
    if auth_role != profile_role:
        raise HTTPException(status_code=409, detail="Account mismatch: login role and staff profile role differ. Ask the owner to review Users and AuthUsers.")
    match = {**match, "full_name": profile.get("full_name") or user_id, "role": profile.get("role") or match.get("role")}
    background_tasks.add_task(
        db.log_audit,
        actor=match.get("user_id"),
        action="LOGIN",
        entity_type="AuthUsers",
        entity_id=str(match.get("user_id")),
        reason="User successfully authenticated",
    )
    return _token_for(match)


@router.get("/api/auth/me")
@router.get("/auth/me")
async def get_me(current_user: dict = Depends(get_current_user)):
    return {
        "user_id": current_user.get("user_id"),
        "username": current_user.get("username") or current_user.get("user_id"),
        "full_name": current_user.get("full_name"),
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
    updated = db.update_record("AuthUsers", "user_id", user_id, {
        "password_hash": hash_password(req.new_password),
        "must_change_password": "false",
    })
    if not updated:
        raise HTTPException(status_code=503, detail="Password was not saved. Try again.")
    db.log_audit(user_id, "CHANGE_PASSWORD", "AuthUsers", user_id, reason="User changed password")
    return {"ok": True}
