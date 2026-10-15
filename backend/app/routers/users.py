from datetime import datetime
from typing import List
from fastapi import APIRouter, HTTPException, status, Depends
from app.models import UserProfile, UserCreate
from app.sheets import db
from app.auth import get_current_user, hash_password

router = APIRouter(prefix="/api/users", tags=["Users"])

@router.get("", response_model=List[UserProfile])
async def list_users(current_user: dict = Depends(get_current_user)):
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
    caller_role = current_user.get("role", "").upper()
    if caller_role not in ["OWNER", "OWNER_ADMIN", "PA"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only Owner or PA can create users")

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
    db.append_record("Users", user_record)

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
    db.append_record("AuthUsers", auth_record)

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
