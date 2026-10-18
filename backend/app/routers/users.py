from datetime import datetime
from typing import List
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field
from app.models import UserProfile, UserCreate
from app.sheets import db
from app.auth import get_current_user, hash_password
from app.permissions import is_manager, is_owner, require_manager, require_owner

router = APIRouter(prefix="/api/users", tags=["Users"])

@router.get("", response_model=List[UserProfile])
async def list_users(current_user: dict = Depends(get_current_user)):
    require_manager(current_user)
    records = db.get_records("Users")
    users = []
    for r in records:
        users.append(UserProfile(
            user_id=str(r.get("user_id", "")),
            full_name=str(r.get("full_name", "")),
            username=str(r.get("user_id", "")),
            role=str(r.get("role", "SALESMAN")),
            mobile=str(r.get("mobile", "")),
            email=str(r.get("email", "")),
            active=str(r.get("active", "true")).lower() == "true",
            created_at=str(r.get("created_at", "")),
            notes=str(r.get("notes", "")),
        ))
    return users

@router.post("", response_model=UserProfile)
async def create_user(req: UserCreate, current_user: dict = Depends(get_current_user)):
    require_manager(current_user)
    requested = str(req.role or "SALESMAN").upper()
    if requested in {"OWNER", "OWNER_ADMIN", "ADMIN"} and not is_owner(current_user):
        raise HTTPException(status_code=403, detail="Only the owner can create another owner account.")
    if requested not in {"OWNER", "OWNER_ADMIN", "PA", "SALESMAN", "FIELD_SALESMAN"}:
        raise HTTPException(status_code=422, detail="Role must be OWNER, PA, or SALESMAN.")

    user_id = db.generate_id("Users")
    auth_id = db.generate_id("AuthUsers")
    now_iso = datetime.utcnow().isoformat()

    user_record = {
        "user_id": user_id,
        "full_name": req.full_name,
        "role": req.role,
        "mobile": req.mobile or "",
        "email": req.email or "",
        "active": "true",
        "created_at": now_iso,
        "notes": req.notes or "",
    }
    if not db.append_record("Users", user_record, raise_on_error=True):
        raise HTTPException(status_code=503, detail="The user record was not saved.")

    hashed_pw = hash_password(req.password)
    auth_record = {
        "auth_id": auth_id,
        "user_id": user_id,
        "username": req.username,
        "password_hash": hashed_pw,
        "role": req.role,
        "active": "true",
        "created_at": now_iso,
        "must_change_password": "false",
    }
    if not db.append_record("AuthUsers", auth_record, raise_on_error=True):
        raise HTTPException(status_code=503, detail="The login record was not saved. Retry before using this username.")

    db.log_audit(
        actor=current_user.get("user_id"),
        action="CREATE_USER",
        entity_type="Users",
        entity_id=user_id,
        reason=f"Created user {req.username} with role {req.role}"
    )

    return UserProfile(
        user_id=user_id,
        full_name=req.full_name,
        username=req.username,
        role=req.role,
        mobile=req.mobile or "",
        email=req.email or "",
        active=True,
        created_at=now_iso,
        notes=req.notes or "",
    )


class PasswordResetRequest(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/{user_id}/reset-password")
async def reset_password(user_id: str, req: PasswordResetRequest, current_user: dict = Depends(get_current_user)):
    """Owner recovery path for a legacy or forgotten password. Does not reveal the old hash."""
    require_owner(current_user)
    if not db.update_record("AuthUsers", "user_id", user_id, {
        "password_hash": hash_password(req.new_password),
        "must_change_password": "true",
        "active": "true",
    }, raise_on_error=True):
        raise HTTPException(status_code=404, detail="Login account was not found or the sheet update failed.")
    db.log_audit(current_user.get("user_id"), "RESET_PASSWORD", "AuthUsers", user_id, reason="Owner reset a password")
    return {"ok": True, "must_change_password": True}
