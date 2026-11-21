from datetime import datetime, timezone
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Request, status, Depends
from pydantic import BaseModel, Field

from app.apps_script_bridge import apps_script_bridge
from app.models import UserProfile, UserCreate, UserUpdate, UserStatusUpdate, CustomRoleCreate, CustomRoleResponse
from app.sheets import db
from app.auth import get_current_user, require_sheets_connection
from app.permissions import (
    KNOWN_SYSTEM_ROLES,
    is_active_custom_role,
    is_manager,
    is_owner,
    require_manager,
    require_owner,
    role_v2_of,
)
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
    """
    Resolve target user's authoritative role across ALL matching AuthUsers and Users rows
    without silent defaults (M07-A02).
    - Rejects malformed non-list/non-dict records fail-closed (503).
    - Rejects duplicate matching user_id rows in either table fail-closed (409 Conflict).
    - If any matching row across either table indicates Owner, returns 'OWNER_ADMIN' so PA
      cannot bypass Owner protection via stale or blank Users.role.
    """
    clean_uid = str(user_id or "").strip()
    if not clean_uid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Valid target user_id is required.",
        )
    auth_users = db.get_records("AuthUsers", fresh=True)
    users = db.get_records("Users", fresh=True)
    if not isinstance(auth_users, list) or not isinstance(users, list):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Unable to verify target user identity from authoritative sheets.",
        )

    auth_matches = []
    for a in auth_users:
        if not isinstance(a, dict):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="AuthUsers contains malformed records. Action blocked.",
            )
        if str(a.get("user_id") or "").strip() == clean_uid:
            auth_matches.append(a)

    user_matches = []
    for u in users:
        if not isinstance(u, dict):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Users contains malformed records. Action blocked.",
            )
        if str(u.get("user_id") or "").strip() == clean_uid:
            user_matches.append(u)

    if not auth_matches and not user_matches:
        raise HTTPException(status_code=404, detail="Employee record not found.")

    if len(auth_matches) > 1 or len(user_matches) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Ambiguous identity: Multiple records exist for user_id '{clean_uid}' "
                f"(Users={len(user_matches)}, AuthUsers={len(auth_matches)}). "
                "Account changes are blocked until duplicates are resolved by Owner."
            ),
        )

    all_roles = [
        str(row.get("role") or "").strip().upper()
        for row in (auth_matches + user_matches)
    ]
    if any(r in {"OWNER", "OWNER_ADMIN", "ADMIN"} for r in all_roles):
        return "OWNER_ADMIN"
    auth_role = str(auth_matches[0].get("role") or "").strip().upper() if auth_matches else ""
    user_role = str(user_matches[0].get("role") or "").strip().upper() if user_matches else ""
    return auth_role or user_role


@router.get("", response_model=List[UserProfile])
async def list_users(current_user: dict = Depends(get_current_user)):
    """List all employees with real username from AuthUsers and verified active status."""
    require_manager(current_user)
    users = get_all_users_with_auth()
    if not is_owner(current_user):
        # PA may see the operational directory needed to route requests, but not
        # personal contact details, banking info, salary structure IDs, login names, or notes.
        redacted_users = []
        for user in users:
            safe_user = dict(user)
            for field in (
                "username", "mobile", "email", "notes",
                "address", "emergency_contact", "bank_details",
                "salary_structure_id", "document_references",
            ):
                safe_user[field] = ""
            redacted_users.append(safe_user)
        users = redacted_users
    return [UserProfile(**u) for u in users]


@router.post("", dependencies=[Depends(require_sheets_connection)])
async def create_user(req: UserCreate, current_user: dict = Depends(get_current_user), request: Request = None):
    """Owner creates employee directly. PA creates a PENDING approval request."""
    require_manager(current_user)
    requested_role = str(req.role or "").strip().upper()
    if not requested_role:
        raise HTTPException(status_code=422, detail="An explicit valid role is required.")

    # Rule: PA cannot create an Owner account
    if requested_role in {"OWNER", "OWNER_ADMIN", "ADMIN"} and not is_owner(current_user):
        raise HTTPException(status_code=403, detail="Only the business owner can create another owner account.")

    allowed_roles = {
        "OWNER", "OWNER_ADMIN", "PA", "ACCOUNTS", "PROCUREMENT", "STORE",
        "PRODUCTION", "QUALITY", "PACKAGING", "SALES", "FIELD_SALESMAN", "HR", "AUDITOR",
        "SALESMAN", "FREELANCER", "ACCOUNTANT", "SOCIAL_MEDIA_ECOMMERCE_MANAGER",
        "SOCIAL_MEDIA_MANAGER", "ECOMMERCE_MANAGER",
    }
    if requested_role not in allowed_roles:
        raise HTTPException(status_code=422, detail=f"Role must be one of: {', '.join(sorted(allowed_roles))}.")

    # Validate username uniqueness upfront before creating request or record
    validate_unique_username(req.username)

    actor_id = str(current_user.get("user_id") or "")
    actor_name = str(current_user.get("full_name") or actor_id)

    req_nonce = apps_script_bridge.extract_request_nonce(request=request)

    if is_owner(current_user):
        # Owner executes directly
        if not req.password or len(req.password) < 8:
            raise HTTPException(status_code=422, detail="Password must be at least 8 characters.")
        created = execute_create_user(req.dict(), actor_id, nonce=req_nonce)
        return UserProfile(**created)
    else:
        # PA submits approval request WITHOUT PASSWORD
        creation_payload = {
            "username": req.username,
            "full_name": req.full_name,
            "role": requested_role,
            "mobile": req.mobile if is_owner(current_user) else "",
            "email": req.email if is_owner(current_user) else "",
            "employment_type": req.employment_type,
            "designation": req.designation,
            "department": req.department,
            "reporting_manager_id": req.reporting_manager_id,
            "joining_date": req.joining_date,
            "salary_frequency": req.salary_frequency if is_owner(current_user) else "",
            "salary_structure_id": req.salary_structure_id if is_owner(current_user) else "",
            "address": req.address if is_owner(current_user) else "",
            "emergency_contact": req.emergency_contact if is_owner(current_user) else "",
            "bank_details": req.bank_details if is_owner(current_user) else "",
            "notes": req.notes if is_owner(current_user) else "",
        }
        app_req = create_approval_request(
            request_type="CREATE_USER",
            target_user_id=None,
            payload=creation_payload,
            requested_by=actor_id,
            requested_by_name=actor_name,
            nonce=req_nonce,
        )
        return {
            "ok": True,
            "pending_approval": True,
            "message": f"Account creation request for {req.username} submitted for Owner approval.",
            "request_id": app_req.request_id,
        }


@router.put("/{user_id}", dependencies=[Depends(require_sheets_connection)])
async def update_user(user_id: str, req: UserUpdate, current_user: dict = Depends(get_current_user), request: Request = None):
    """Owner updates employee details directly. PA submits an approval request."""
    require_manager(current_user)
    target_role = _get_target_user_role(user_id)

    # Rule: PA cannot edit or change role of an Owner or unassigned/corrupted account
    if (not target_role or target_role in {"OWNER", "OWNER_ADMIN", "ADMIN"}) and not is_owner(current_user):
        raise HTTPException(status_code=403, detail="PA cannot edit or change the role of an Owner or unassigned account.")

    # Rule: PA cannot promote any user to Owner
    if req.role and str(req.role).strip().upper() in {"OWNER", "OWNER_ADMIN", "ADMIN"} and not is_owner(current_user):
        raise HTTPException(status_code=403, detail="PA cannot promote an employee to Owner.")

    actor_id = str(current_user.get("user_id") or "")
    actor_name = str(current_user.get("full_name") or actor_id)

    try:
        update_data = req.dict(exclude_unset=True)
    except TypeError:
        update_data = {k: v for k, v in req.dict().items() if v is not None}

    req_nonce = apps_script_bridge.extract_request_nonce(request=request)

    if is_owner(current_user):
        # Owner executes directly
        updated = execute_update_user(user_id, update_data, actor_id, nonce=req_nonce)
        return {"ok": True, "user": updated}
    else:
        # PA may request operational updates, but not private employee, contact,
        # banking, identity, or compensation changes.
        owner_only_fields = {
            "username", "mobile", "email", "address", "emergency_contact",
            "bank_details", "document_references", "salary_frequency",
            "salary_structure_id",
        }
        update_data = {k: v for k, v in update_data.items() if k not in owner_only_fields}
        if not update_data:
            raise HTTPException(status_code=403, detail="Only the Owner can change private employee or authentication details.")
        # PA submits approval request
        app_req = create_approval_request(
            request_type="UPDATE_USER",
            target_user_id=user_id,
            payload=update_data,
            requested_by=actor_id,
            requested_by_name=actor_name,
            nonce=req_nonce,
        )
        return {
            "ok": True,
            "pending_approval": True,
            "message": f"Employee update request for {user_id} submitted for Owner approval.",
            "request_id": app_req.request_id,
        }


@router.post("/{user_id}/status", dependencies=[Depends(require_sheets_connection)])
async def set_user_status(user_id: str, req: UserStatusUpdate, current_user: dict = Depends(get_current_user), request: Request = None):
    """Owner activates/deactivates directly. PA submits an approval request."""
    require_manager(current_user)
    target_role = _get_target_user_role(user_id)

    # Rule: PA cannot deactivate or modify status of an Owner or unassigned/corrupted account
    if (not target_role or target_role in {"OWNER", "OWNER_ADMIN", "ADMIN"}) and not is_owner(current_user):
        raise HTTPException(status_code=403, detail="PA cannot deactivate or modify an Owner or unassigned account.")

    actor_id = str(current_user.get("user_id") or "")
    actor_name = str(current_user.get("full_name") or actor_id)

    action_type = "REACTIVATE_USER" if req.active else "DEACTIVATE_USER"

    req_nonce = apps_script_bridge.extract_request_nonce(request=request)

    if is_owner(current_user):
        # Owner executes directly
        res = execute_set_user_status(user_id, req.active, actor_id, reason=req.reason or "", nonce=req_nonce)
        return res
    else:
        # PA submits approval request
        app_req = create_approval_request(
            request_type=action_type,
            target_user_id=user_id,
            payload={"active": req.active, "reason": req.reason or ""},
            requested_by=actor_id,
            requested_by_name=actor_name,
            nonce=req_nonce,
        )
        return {
            "ok": True,
            "pending_approval": True,
            "message": f"Account {action_type.lower()} request for {user_id} submitted for Owner approval.",
            "request_id": app_req.request_id,
        }


@router.post("/{user_id}/reset-password", dependencies=[Depends(require_sheets_connection)])
async def reset_password(user_id: str, req: PasswordResetRequest, current_user: dict = Depends(get_current_user), request: Request = None):
    """Owner resets password directly and revokes all active sessions. PA submits an approval request."""
    require_manager(current_user)
    target_role = _get_target_user_role(user_id)

    # Rule: PA cannot reset password for an Owner or unassigned/corrupted account
    if (not target_role or target_role in {"OWNER", "OWNER_ADMIN", "ADMIN"}) and not is_owner(current_user):
        raise HTTPException(status_code=403, detail="PA cannot reset the password of an Owner or unassigned account.")

    actor_id = str(current_user.get("user_id") or "")
    actor_name = str(current_user.get("full_name") or actor_id)

    req_nonce = apps_script_bridge.extract_request_nonce(request=request)

    if is_owner(current_user):
        # Owner executes directly
        if not req.new_password or len(req.new_password) < 8:
            raise HTTPException(status_code=422, detail="Password must be at least 8 characters.")
        res = execute_reset_password(user_id, req.new_password, actor_id, reason="Owner reset user password", nonce=req_nonce)
        return res
    else:
        # PA submits approval request WITHOUT PASSWORD
        app_req = create_approval_request(
            request_type="RESET_PASSWORD",
            target_user_id=user_id,
            payload={"reason": "PA requested password reset for employee"},
            requested_by=actor_id,
            requested_by_name=actor_name,
            nonce=req_nonce,
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


def _is_active_custom_role(row: dict) -> bool:
    return is_active_custom_role(row)


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

    # Custom roles (exclude soft-deleted/inactive rows)
    custom_records = [cr for cr in (db.get_records("CustomRoles", fresh=True) or []) if _is_active_custom_role(cr)]
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


@router.post("/roles", dependencies=[Depends(require_sheets_connection)])
async def create_or_update_custom_role(req: CustomRoleCreate, request: Request, current_user: dict = Depends(get_current_user)):
    """Owner creates or updates custom role with module-based permissions via Apps Script."""
    require_owner(current_user)
    from app.permissions import validate_custom_role_permissions
    import json

    clean_name = str(req.role_name or "").strip().upper()
    if not clean_name or len(clean_name) < 2:
        raise HTTPException(422, "Role name must be at least 2 characters.")

    if clean_name in KNOWN_SYSTEM_ROLES:
        raise HTTPException(400, f"Cannot override built-in system role '{clean_name}'.")

    # Validate that custom role does not grant Owner-level or wildcard permissions
    validate_custom_role_permissions(req.permissions)

    actor_id = str(current_user.get("user_id") or "")
    existing = next(
        (
            r for r in (db.get_records("CustomRoles", fresh=True) or [])
            if _is_active_custom_role(r) and str(r.get("role_name", "")).upper() == clean_name
        ),
        None,
    )
    now_iso_str = datetime.now(timezone.utc).isoformat()

    if existing:
        role_id = str(existing.get("role_id"))
        res = apps_script_bridge.delegate_governed_write(
            action="UPDATE_CUSTOM_ROLE",
            target_tab="CustomRoles",
            payload={
                "role_id": role_id,
                "role_name": clean_name,
                "description": req.description or "",
                "permissions_json": json.dumps(req.permissions),
                "updated_at": now_iso_str,
            },
            request=request,
            actor_user_id=actor_id,
            actor_role=role_v2_of(current_user),
            id_field="role_id",
            invalidate_tabs=["CustomRoles"],
        )
        db.log_audit(actor_id, "UPDATE_CUSTOM_ROLE", "CustomRoles", role_id, reason=f"Updated permissions for custom role {clean_name}")
        return {"ok": True, "role_id": role_id, "role_name": clean_name, "message": f"Updated custom role {clean_name}", **res}
    else:
        res = apps_script_bridge.delegate_governed_write(
            action="CREATE_CUSTOM_ROLE",
            target_tab="CustomRoles",
            payload={
                "role_name": clean_name,
                "description": req.description or "",
                "permissions_json": json.dumps(req.permissions),
                "created_by": actor_id,
                "created_at": now_iso_str,
                "updated_at": now_iso_str,
            },
            request=request,
            actor_user_id=actor_id,
            actor_role=role_v2_of(current_user),
            id_field="role_id",
            invalidate_tabs=["CustomRoles"],
        )
        role_id = str(res.get("allocated_id") or "")
        db.log_audit(actor_id, "CREATE_CUSTOM_ROLE", "CustomRoles", role_id, reason=f"Created custom role {clean_name}")
        return {"ok": True, "role_id": role_id, "role_name": clean_name, "message": f"Created custom role {clean_name}", **res}


@router.delete("/roles/{role_name}", dependencies=[Depends(require_sheets_connection)])
async def delete_custom_role(role_name: str, request: Request, current_user: dict = Depends(get_current_user)):
    """Owner deletes a custom role if no active users are assigned to it via Apps Script."""
    require_owner(current_user)
    clean_name = str(role_name or "").strip().upper()

    existing = next(
        (
            r for r in (db.get_records("CustomRoles", fresh=True) or [])
            if _is_active_custom_role(r) and str(r.get("role_name", "")).upper() == clean_name
        ),
        None,
    )
    if not existing:
        raise HTTPException(404, f"Custom role '{clean_name}' not found.")

    users = db.get_records("Users", fresh=True) or []
    auth_users = db.get_records("AuthUsers", fresh=True) or []
    assigned_count = sum(1 for u in users if str(u.get("role", "")).upper() == clean_name) + \
                     sum(1 for a in auth_users if str(a.get("role", "")).upper() == clean_name)
    if assigned_count > 0:
        raise HTTPException(400, f"Cannot delete role '{clean_name}': {assigned_count} employee(s) are assigned to it.")

    role_id = str(existing.get("role_id"))
    res = apps_script_bridge.delegate_governed_write(
        action="DELETE_CUSTOM_ROLE",
        target_tab="CustomRoles",
        payload={"role_id": role_id, "role_name": clean_name, "deleted": "true", "active": "false"},
        request=request,
        actor_user_id=str(current_user.get("user_id") or ""),
        actor_role=role_v2_of(current_user),
        id_field="role_id",
        invalidate_tabs=["CustomRoles"],
    )
    db.log_audit(str(current_user.get("user_id")), "DELETE_CUSTOM_ROLE", "CustomRoles", role_id, reason=f"Deleted custom role {clean_name}")
    return {"ok": True, "message": f"Custom role {clean_name} deleted.", **res}


@router.post("/reconcile-role-alias", dependencies=[Depends(require_sheets_connection)])
async def reconcile_role_alias(user_id: str, request: Request, current_user: dict = Depends(get_current_user)):
    """
    Owner synchronizes canonical role mapping across Users and AuthUsers via Apps Script.
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
        changes.append(f"Users sheet role '{u_role}' -> '{target_canonical}'")
    if a_match and a_role != target_canonical:
        changes.append(f"AuthUsers sheet role '{a_role}' -> '{target_canonical}'")

    res = {}
    if changes:
        res = apps_script_bridge.delegate_governed_write(
            action="RECONCILE_ROLE_ALIAS",
            target_tab="Users",
            payload={
                "user_id": clean_uid,
                "target_canonical_role": target_canonical,
                "update_users": bool(u_match and u_role != target_canonical),
                "update_auth_users": bool(a_match and a_role != target_canonical),
            },
            request=request,
            actor_user_id=actor_id,
            actor_role=role_v2_of(current_user),
            id_field="user_id",
            invalidate_tabs=["Users", "AuthUsers"],
        )

    db.log_audit(actor_id, "RECONCILE_ROLE_ALIAS", "Users", clean_uid, reason=f"Reconciled role to canonical {target_canonical}: {'; '.join(changes) or 'Already aligned'}")
    return {
        "ok": True,
        "user_id": clean_uid,
        "canonical_role": target_canonical,
        "changes": changes,
        "message": f"User {clean_uid} role aligned to {target_canonical}.",
        **res,
    }

