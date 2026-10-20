from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field

from app.models import UserProfile, UserCreate, UserUpdate, UserStatusUpdate
from app.sheets import db
from app.auth import get_current_user
from app.permissions import is_manager, is_owner, require_manager, require_owner
from app.user_service import (
    get_all_users_with_auth,
    validate_unique_username,
    execute_create_user,
    execute_update_user,
    execute_set_user_status,
    execute_reset_password,
    audit_user_reconciliation,
    inspect_user_references,
)
from app.routers.approvals import create_approval_request

router = APIRouter(prefix="/api/users", tags=["Users"])


class PasswordResetRequest(BaseModel):
    new_password: Optional[str] = ""


def _get_target_user_role(user_id: str) -> str:
    """Helper to check target user's current role."""
    users = db.get_records("Users", fresh=True) or []
    target = next((u for u in users if str(u.get("user_id") or "").strip() == user_id.strip()), None)
    if not target:
        auth_users = db.get_records("AuthUsers", fresh=True) or []
        target = next((u for u in auth_users if str(u.get("user_id") or "").strip() == user_id.strip()), None)
    if not target:
        raise HTTPException(status_code=404, detail="Employee record not found.")
    return str(target.get("role") or "SALESMAN").upper()


@router.get("", response_model=List[UserProfile])
async def list_users(current_user: dict = Depends(get_current_user)):
    """List all employees with real username from AuthUsers and verified active status."""
    require_manager(current_user)
    users = get_all_users_with_auth()
    return [UserProfile(**u) for u in users]


@router.post("")
async def create_user(req: UserCreate, current_user: dict = Depends(get_current_user)):
    """Owner creates employee directly. PA creates a PENDING approval request."""
    require_manager(current_user)
    requested_role = str(req.role or "SALESMAN").upper()

    # Rule: PA cannot create an Owner account
    if requested_role in {"OWNER", "OWNER_ADMIN", "ADMIN"} and not is_owner(current_user):
        raise HTTPException(status_code=403, detail="Only the business owner can create another owner account.")

    if requested_role not in {"OWNER", "OWNER_ADMIN", "PA", "SALESMAN", "FIELD_SALESMAN"}:
        raise HTTPException(status_code=422, detail="Role must be OWNER, PA, or SALESMAN.")

    # Validate username uniqueness upfront before creating request or record
    validate_unique_username(req.username)

    actor_id = str(current_user.get("user_id") or "")
    actor_name = str(current_user.get("full_name") or actor_id)

    if is_owner(current_user):
        # Owner executes directly
        if not req.password or len(req.password) < 8:
            raise HTTPException(status_code=422, detail="Password must be at least 8 characters.")
        created = execute_create_user(req.dict(), actor_id)
        return UserProfile(**created)
    else:
        # PA submits approval request WITHOUT PASSWORD
        creation_payload = {
            "username": req.username,
            "full_name": req.full_name,
            "role": requested_role,
            "mobile": req.mobile,
            "email": req.email,
            "notes": req.notes,
        }
        app_req = create_approval_request(
            request_type="CREATE_USER",
            target_user_id=None,
            payload=creation_payload,
            requested_by=actor_id,
            requested_by_name=actor_name,
        )
        return {
            "ok": True,
            "pending_approval": True,
            "message": f"Account creation request for {req.username} submitted for Owner approval.",
            "request_id": app_req.request_id,
        }


@router.put("/{user_id}")
async def update_user(user_id: str, req: UserUpdate, current_user: dict = Depends(get_current_user)):
    """Owner updates employee details directly. PA submits an approval request."""
    require_manager(current_user)
    target_role = _get_target_user_role(user_id)

    # Rule: PA cannot edit or change role of an Owner account
    if target_role in {"OWNER", "OWNER_ADMIN", "ADMIN"} and not is_owner(current_user):
        raise HTTPException(status_code=403, detail="PA cannot edit or change the role of an Owner account.")

    # Rule: PA cannot promote any user to Owner
    if req.role and str(req.role).upper() in {"OWNER", "OWNER_ADMIN", "ADMIN"} and not is_owner(current_user):
        raise HTTPException(status_code=403, detail="PA cannot promote an employee to Owner.")

    actor_id = str(current_user.get("user_id") or "")
    actor_name = str(current_user.get("full_name") or actor_id)

    try:
        update_data = req.dict(exclude_unset=True)
    except TypeError:
        update_data = {k: v for k, v in req.dict().items() if v is not None}

    if is_owner(current_user):
        # Owner executes directly
        updated = execute_update_user(user_id, update_data, actor_id)
        return {"ok": True, "user": updated}
    else:
        # PA submits approval request
        app_req = create_approval_request(
            request_type="UPDATE_USER",
            target_user_id=user_id,
            payload=update_data,
            requested_by=actor_id,
            requested_by_name=actor_name,
        )
        return {
            "ok": True,
            "pending_approval": True,
            "message": f"Employee update request for {user_id} submitted for Owner approval.",
            "request_id": app_req.request_id,
        }


@router.post("/{user_id}/status")
async def set_user_status(user_id: str, req: UserStatusUpdate, current_user: dict = Depends(get_current_user)):
    """Owner activates/deactivates directly. PA submits an approval request."""
    require_manager(current_user)
    target_role = _get_target_user_role(user_id)

    # Rule: PA cannot deactivate or modify status of an Owner account
    if target_role in {"OWNER", "OWNER_ADMIN", "ADMIN"} and not is_owner(current_user):
        raise HTTPException(status_code=403, detail="PA cannot deactivate or modify an Owner account.")

    actor_id = str(current_user.get("user_id") or "")
    actor_name = str(current_user.get("full_name") or actor_id)

    action_type = "REACTIVATE_USER" if req.active else "DEACTIVATE_USER"

    if is_owner(current_user):
        # Owner executes directly
        res = execute_set_user_status(user_id, req.active, actor_id, reason=req.reason or "")
        return res
    else:
        # PA submits approval request
        app_req = create_approval_request(
            request_type=action_type,
            target_user_id=user_id,
            payload={"active": req.active, "reason": req.reason or ""},
            requested_by=actor_id,
            requested_by_name=actor_name,
        )
        return {
            "ok": True,
            "pending_approval": True,
            "message": f"Account {action_type.lower()} request for {user_id} submitted for Owner approval.",
            "request_id": app_req.request_id,
        }


@router.post("/{user_id}/reset-password")
async def reset_password(user_id: str, req: PasswordResetRequest, current_user: dict = Depends(get_current_user)):
    """Owner resets password directly and revokes all active sessions. PA submits an approval request."""
    require_manager(current_user)
    target_role = _get_target_user_role(user_id)

    # Rule: PA cannot reset password for an Owner account
    if target_role in {"OWNER", "OWNER_ADMIN", "ADMIN"} and not is_owner(current_user):
        raise HTTPException(status_code=403, detail="PA cannot reset the password of an Owner account.")

    actor_id = str(current_user.get("user_id") or "")
    actor_name = str(current_user.get("full_name") or actor_id)

    if is_owner(current_user):
        # Owner executes directly
        if not req.new_password or len(req.new_password) < 8:
            raise HTTPException(status_code=422, detail="Password must be at least 8 characters.")
        res = execute_reset_password(user_id, req.new_password, actor_id, reason="Owner reset user password")
        return res
    else:
        # PA submits approval request WITHOUT PASSWORD
        app_req = create_approval_request(
            request_type="RESET_PASSWORD",
            target_user_id=user_id,
            payload={"reason": "PA requested password reset for employee"},
            requested_by=actor_id,
            requested_by_name=actor_name,
        )
        return {
            "ok": True,
            "pending_approval": True,
            "message": f"Password reset request for {user_id} submitted for Owner approval.",
            "request_id": app_req.request_id,
        }


@router.get("/reconciliation")
async def get_user_reconciliation(current_user: dict = Depends(get_current_user)):
    """Owner-only read-only audit comparing Users and AuthUsers sheets."""
    require_owner(current_user)
    return audit_user_reconciliation()


@router.get("/references/{user_id}")
async def get_user_references(user_id: str, current_user: dict = Depends(get_current_user)):
    """Owner-only audit tool to check all historical transactions referencing user_id before renumbering."""
    require_owner(current_user)
    return inspect_user_references(user_id)
