from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, Field

from app.models import UserProfile, UserCreate, UserUpdate, UserStatusUpdate, CustomRoleCreate, CustomRoleResponse
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


@router.get("/roles")
async def list_roles(current_user: dict = Depends(get_current_user)):
    """List all available roles (built-in and custom) with module permissions."""
    require_manager(current_user)
    from app.permissions import DEFAULT_ROLE_PERMISSIONS

    roles = []
    # Built-in roles
    for r_name, perms in DEFAULT_ROLE_PERMISSIONS.items():
        roles.append({
            "role_name": r_name,
            "is_system": True,
            "description": f"Standard {r_name} role",
            "permissions": perms,
        })

    # Custom roles
    custom_records = db.get_records("CustomRoles") or []
    for cr in custom_records:
        raw_p = cr.get("permissions_json") or "{}"
        try:
            import json
            perms = json.loads(raw_p) if isinstance(raw_p, str) else raw_p
        except Exception:
            perms = {}
        roles.append({
            "role_id": cr.get("role_id"),
            "role_name": cr.get("role_name"),
            "is_system": False,
            "description": cr.get("description", ""),
            "permissions": perms,
            "created_by": cr.get("created_by", ""),
            "created_at": cr.get("created_at", ""),
        })
    return roles


@router.post("/roles")
async def create_or_update_custom_role(req: CustomRoleCreate, current_user: dict = Depends(get_current_user)):
    """Owner creates or updates custom role with module-based permissions."""
    require_owner(current_user)
    from app.permissions import validate_custom_role_permissions, OWNERS
    import json

    clean_name = str(req.role_name or "").strip().upper()
    if not clean_name or len(clean_name) < 2:
        raise HTTPException(422, "Role name must be at least 2 characters.")

    if clean_name in OWNERS or clean_name in {"PA", "SALESMAN", "FACTORY_WORKER"}:
        raise HTTPException(400, f"Cannot override system role '{clean_name}'.")

    # Validate that custom role does not grant Owner-level permissions
    validate_custom_role_permissions(req.permissions)

    actor_id = str(current_user.get("user_id") or "")
    existing = next((r for r in db.get_records("CustomRoles") if str(r.get("role_name", "")).upper() == clean_name), None)
    now_iso = datetime.now(timezone.utc).isoformat()

    if existing:
        role_id = str(existing.get("role_id"))
        db.update_record("CustomRoles", "role_id", role_id, {
            "description": req.description or "",
            "permissions_json": json.dumps(req.permissions),
            "updated_at": now_iso,
        }, raise_on_error=True)
        db.log_audit(actor_id, "UPDATE_CUSTOM_ROLE", "CustomRoles", role_id, reason=f"Updated permissions for custom role {clean_name}")
        return {"ok": True, "role_id": role_id, "role_name": clean_name, "message": f"Updated custom role {clean_name}"}
    else:
        role_id = db.generate_id("CustomRoles")
        row = {
            "role_id": role_id,
            "role_name": clean_name,
            "description": req.description or "",
            "permissions_json": json.dumps(req.permissions),
            "created_by": actor_id,
            "created_at": now_iso,
            "updated_at": now_iso,
        }
        db.append_record("CustomRoles", row, raise_on_error=True)
        db.log_audit(actor_id, "CREATE_CUSTOM_ROLE", "CustomRoles", role_id, reason=f"Created custom role {clean_name}")
        return {"ok": True, "role_id": role_id, "role_name": clean_name, "message": f"Created custom role {clean_name}"}


@router.delete("/roles/{role_name}")
async def delete_custom_role(role_name: str, current_user: dict = Depends(get_current_user)):
    """Owner deletes a custom role if no active users are assigned to it."""
    require_owner(current_user)
    clean_name = str(role_name or "").strip().upper()

    existing = next((r for r in db.get_records("CustomRoles") if str(r.get("role_name", "")).upper() == clean_name), None)
    if not existing:
        raise HTTPException(404, f"Custom role '{clean_name}' not found.")

    # Check if assigned to any user
    users = db.get_records("Users") or []
    auth_users = db.get_records("AuthUsers") or []
    assigned_count = sum(1 for u in users if str(u.get("role", "")).upper() == clean_name) + \
                     sum(1 for a in auth_users if str(a.get("role", "")).upper() == clean_name)
    if assigned_count > 0:
        raise HTTPException(400, f"Cannot delete role '{clean_name}': {assigned_count} employee(s) are assigned to it.")

    role_id = str(existing.get("role_id"))
    db.update_record("CustomRoles", "role_id", role_id, {"deleted": "true", "active": "false"})
    db.log_audit(str(current_user.get("user_id")), "DELETE_CUSTOM_ROLE", "CustomRoles", role_id, reason=f"Deleted custom role {clean_name}")
    return {"ok": True, "message": f"Custom role {clean_name} deleted."}


@router.post("/reconcile-role-alias")
async def reconcile_role_alias(user_id: str, current_user: dict = Depends(get_current_user)):
    """
    Owner synchronizes canonical role mapping across Users and AuthUsers.
    For example: USR-000003 where Users.role is FIELD_SALESMAN and AuthUsers.role is SALESMAN,
    both map to canonical SALESMAN.
    """
    require_owner(current_user)
    clean_uid = str(user_id or "").strip()
    from app.permissions import canonical_role

    users = db.get_records("Users", fresh=True) or []
    auth_users = db.get_records("AuthUsers", fresh=True) or []
    u_match = next((u for u in users if str(u.get("user_id", "")).strip() == clean_uid), None)
    a_match = next((a for a in auth_users if str(a.get("user_id", "")).strip() == clean_uid), None)

    if not u_match and not a_match:
        raise HTTPException(404, f"User '{clean_uid}' not found.")

    u_role = str((u_match or {}).get("role", "")).strip().upper()
    a_role = str((a_match or {}).get("role", "")).strip().upper()

    target_canonical = canonical_role(a_role or u_role)
    actor_id = str(current_user.get("user_id") or "")

    changes = []
    if u_match and u_role != target_canonical:
        db.update_record("Users", "user_id", clean_uid, {"role": target_canonical})
        changes.append(f"Users sheet role '{u_role}' -> '{target_canonical}'")
    if a_match and a_role != target_canonical:
        db.update_record("AuthUsers", "user_id", clean_uid, {"role": target_canonical})
        changes.append(f"AuthUsers sheet role '{a_role}' -> '{target_canonical}'")

    db.log_audit(actor_id, "RECONCILE_ROLE_ALIAS", "Users", clean_uid, reason=f"Reconciled role to canonical {target_canonical}: {'; '.join(changes) or 'Already aligned'}")
    return {
        "ok": True,
        "user_id": clean_uid,
        "canonical_role": target_canonical,
        "changes": changes,
        "message": f"User {clean_uid} role aligned to {target_canonical}."
    }

