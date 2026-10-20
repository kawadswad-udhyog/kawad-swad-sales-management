from datetime import datetime, timezone
import json
import logging
from typing import Optional, Dict, Any, List
from fastapi import HTTPException, status

from app.sheets import db
from app.auth import hash_password, revoke_all_user_sessions

logger = logging.getLogger("kawad_swad.users")


def get_all_users_with_auth() -> List[Dict[str, Any]]:
    """Merge Users and AuthUsers to ensure real username and accurate active status."""
    user_records = db.get_records("Users", fresh=True)
    auth_records = db.get_records("AuthUsers", fresh=True)

    auth_by_uid: Dict[str, Dict[str, Any]] = {}
    for a in auth_records:
        uid = str(a.get("user_id") or "").strip()
        if uid:
            auth_by_uid[uid] = a

    result = []
    for u in user_records:
        uid = str(u.get("user_id") or "").strip()
        auth = auth_by_uid.get(uid, {})
        real_username = str(auth.get("username") or u.get("username") or uid).strip()

        # Both records must be active for the account to be considered fully active
        u_active = str(u.get("active", "true")).lower() in {"true", "1", "yes"}
        a_active = str(auth.get("active", "true")).lower() in {"true", "1", "yes"}
        is_active = u_active and a_active

        result.append({
            "user_id": uid,
            "full_name": str(u.get("full_name") or ""),
            "username": real_username,
            "role": str(auth.get("role") or u.get("role") or "SALESMAN"),
            "mobile": str(u.get("mobile") or ""),
            "email": str(u.get("email") or ""),
            "active": is_active,
            "created_at": str(u.get("created_at") or ""),
            "notes": str(u.get("notes") or ""),
        })
    return result


def validate_unique_username(username: str, exclude_user_id: Optional[str] = None) -> None:
    """Ensure username is unique across all AuthUsers records."""
    clean_username = username.strip().lower()
    if not clean_username:
        raise HTTPException(status_code=422, detail="Username cannot be blank.")
    
    auth_records = db.get_records("AuthUsers", fresh=True)
    for a in auth_records:
        uid = str(a.get("user_id") or "").strip()
        if exclude_user_id and uid == exclude_user_id.strip():
            continue
        existing_username = str(a.get("username") or "").strip().lower()
        if existing_username == clean_username:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Username '{username}' is already taken. Please choose another username.",
            )


def execute_create_user(payload: Dict[str, Any], actor_user_id: str) -> Dict[str, Any]:
    """Two-phase creation of profile (Users) and credentials (AuthUsers) with safe failure rollback."""
    username = str(payload.get("username") or "").strip()
    full_name = str(payload.get("full_name") or "").strip()
    role = str(payload.get("role") or "SALESMAN").upper()
    mobile = str(payload.get("mobile") or "").strip()
    email = str(payload.get("email") or "").strip()
    notes = str(payload.get("notes") or "").strip()
    password = str(payload.get("password") or "").strip()

    if not username:
        raise HTTPException(status_code=422, detail="Username is required.")
    if not full_name:
        raise HTTPException(status_code=422, detail="Full name is required.")
    if len(password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters.")

    validate_unique_username(username)

    user_id = db.generate_id("Users")
    auth_id = db.generate_id("AuthUsers")
    now_iso = datetime.now(timezone.utc).isoformat()

    # Step 1: Write profile to Users
    user_record = {
        "user_id": user_id,
        "full_name": full_name,
        "username": username,
        "role": role,
        "mobile": mobile,
        "email": email,
        "active": "true",
        "created_at": now_iso,
        "notes": notes,
    }

    if not db.append_record("Users", user_record, raise_on_error=True):
        raise HTTPException(status_code=503, detail="Failed to save profile record to Google Sheets.")

    # Step 2: Write credentials to AuthUsers
    hashed_pw = hash_password(password)
    auth_record = {
        "auth_id": auth_id,
        "user_id": user_id,
        "username": username,
        "password_hash": hashed_pw,
        "role": role,
        "active": "true",
        "created_at": now_iso,
        "must_change_password": "false",
        "sessions_revoked_at": "",
    }

    try:
        if not db.append_record("AuthUsers", auth_record, raise_on_error=True):
            raise RuntimeError("AuthUsers write returned False")
    except Exception as exc:
        # Roll back step 1 so no orphan user profile without auth exists
        logger.error(f"AuthUsers write failed for {user_id}. Rolling back Users profile: {exc}")
        try:
            db.update_record("Users", "user_id", user_id, {
                "active": "false",
                "notes": f"INCOMPLETE_CREATION: {exc}",
            })
        except Exception:
            pass
        raise HTTPException(
            status_code=503,
            detail=f"The login record could not be saved ({exc}). The employee profile creation was safely rolled back.",
        )

    db.log_audit(
        actor=actor_user_id,
        action="CREATE_USER",
        entity_type="Users",
        entity_id=user_id,
        reason=f"Created employee account {username} ({role})",
    )

    return {
        "user_id": user_id,
        "full_name": full_name,
        "username": username,
        "role": role,
        "mobile": mobile,
        "email": email,
        "active": True,
        "created_at": now_iso,
        "notes": notes,
    }


def execute_update_user(user_id: str, payload: Dict[str, Any], actor_user_id: str) -> Dict[str, Any]:
    """Update profile and credentials, revoking existing sessions if role changes."""
    user_records = db.get_records("Users", fresh=True)
    target = next((u for u in user_records if str(u.get("user_id") or "").strip() == user_id.strip()), None)
    if not target:
        raise HTTPException(status_code=404, detail="Employee record not found.")

    old_role = str(target.get("role") or "").upper()
    new_role = str(payload.get("role") or old_role).upper()

    user_updates: Dict[str, Any] = {}
    if "full_name" in payload and payload["full_name"] is not None:
        user_updates["full_name"] = str(payload["full_name"]).strip()
    if "role" in payload and payload["role"] is not None:
        user_updates["role"] = new_role
    if "mobile" in payload and payload["mobile"] is not None:
        user_updates["mobile"] = str(payload["mobile"]).strip()
    if "email" in payload and payload["email"] is not None:
        user_updates["email"] = str(payload["email"]).strip()
    if "notes" in payload and payload["notes"] is not None:
        user_updates["notes"] = str(payload["notes"]).strip()

    if user_updates:
        if not db.update_record("Users", "user_id", user_id, user_updates, raise_on_error=True):
            raise HTTPException(status_code=503, detail="Failed to update Users record in Google Sheets.")

    # Synchronize AuthUsers
    auth_updates: Dict[str, Any] = {}
    if "full_name" in user_updates:
        auth_updates["full_name"] = user_updates["full_name"]
    if "role" in user_updates and user_updates["role"] != old_role:
        auth_updates["role"] = user_updates["role"]
        # Audit requirement: Role change must immediately revoke existing sessions!
        revoke_all_user_sessions(user_id, f"Role changed from {old_role} to {new_role}")

    if auth_updates:
        try:
            db.update_record("AuthUsers", "user_id", user_id, auth_updates, raise_on_error=True)
        except Exception as exc:
            logger.warning(f"Failed to synchronize AuthUsers for {user_id}: {exc}")

    db.log_audit(
        actor=actor_user_id,
        action="UPDATE_USER",
        entity_type="Users",
        entity_id=user_id,
        reason=f"Updated employee details. Role: {old_role} -> {new_role}",
    )

    merged = dict(target)
    merged.update(user_updates)
    merged["active"] = str(merged.get("active", "true")).lower() in {"true", "1", "yes"}
    return merged


def execute_set_user_status(user_id: str, active: bool, actor_user_id: str, reason: str = "") -> Dict[str, Any]:
    """Toggle user active/deactive status in both Users and AuthUsers. Invalidate sessions immediately on deactivation."""
    active_str = "true" if active else "false"

    # Step 1: Update Users
    if not db.update_record("Users", "user_id", user_id, {"active": active_str}, raise_on_error=True):
        raise HTTPException(status_code=503, detail="Failed to update status in Users sheet.")

    # Step 2: Update AuthUsers
    auth_updates = {"active": active_str}
    if not active:
        # Invalidate all existing sessions immediately across devices
        revoke_all_user_sessions(user_id, f"Account deactivated by {actor_user_id}: {reason}")

    try:
        db.update_record("AuthUsers", "user_id", user_id, auth_updates, raise_on_error=True)
    except Exception as exc:
        logger.warning(f"AuthUsers status update warning for {user_id}: {exc}")

    action_label = "REACTIVATE_USER" if active else "DEACTIVATE_USER"
    db.log_audit(
        actor=actor_user_id,
        action=action_label,
        entity_type="Users",
        entity_id=user_id,
        reason=f"Account {'reactivated' if active else 'deactivated'}. Reason: {reason or 'Administrative action'}",
    )

    return {"ok": True, "user_id": user_id, "active": active}


def execute_reset_password(user_id: str, new_password: str, actor_user_id: str, reason: str = "Owner password reset") -> Dict[str, Any]:
    """Reset user password, set must_change_password=True, and revoke all existing sessions across all devices."""
    if len(new_password) < 8:
        raise HTTPException(status_code=422, detail="New password must be at least 8 characters.")

    auth_records = db.get_records("AuthUsers", fresh=True)
    target_auth = next((r for r in auth_records if str(r.get("user_id", "")).strip() == user_id.strip()), None)
    if not target_auth:
        raise HTTPException(status_code=404, detail="Login account was not found in AuthUsers.")

    current_active_status = str(target_auth.get("active", "true")).lower()

    # Invalidate all existing sessions across devices immediately
    revoke_all_user_sessions(user_id, reason=reason)

    update_payload = {
        "password_hash": hash_password(new_password),
        "must_change_password": "true",
        "active": current_active_status,  # Preserve existing active status!
    }
    if not db.update_record("AuthUsers", "user_id", user_id, update_payload, raise_on_error=True):
        raise HTTPException(status_code=503, detail="The password update failed to save to Google Sheets.")

    db.log_audit(
        actor=actor_user_id,
        action="RESET_PASSWORD",
        entity_type="AuthUsers",
        entity_id=user_id,
        reason=f"{reason}. Revoked all existing sessions.",
    )
    return {"ok": True, "user_id": user_id, "must_change_password": True, "active": current_active_status == "true"}
