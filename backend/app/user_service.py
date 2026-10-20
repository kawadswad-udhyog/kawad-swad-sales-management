import time
import secrets
from datetime import datetime, timezone
import json
import logging
from typing import Optional, Dict, Any, List
from fastapi import HTTPException, status

from app.sheets import db
from app.auth import hash_password, revoke_all_user_sessions, _USER_REVOKED_AT

logger = logging.getLogger("kawad_swad.users")


def get_all_users_with_auth() -> List[Dict[str, Any]]:
    """
    Merge Users and AuthUsers to ensure real username and accurate active status.
    Never silently overwrites duplicate auth rows or conceals orphaned records.
    """
    user_records = db.get_records("Users", fresh=True) or []
    auth_records = db.get_records("AuthUsers", fresh=True) or []

    auth_by_uid: Dict[str, List[Dict[str, Any]]] = {}
    for a in auth_records:
        uid = str(a.get("user_id") or "").strip()
        if uid:
            auth_by_uid.setdefault(uid, []).append(a)

    users_by_uid: Dict[str, List[Dict[str, Any]]] = {}
    for u in user_records:
        uid = str(u.get("user_id") or "").strip()
        if uid:
            users_by_uid.setdefault(uid, []).append(u)

    used_auth_indices = set()
    result = []

    # Process all profile records in Users sheet
    for u in user_records:
        uid = str(u.get("user_id") or "").strip()
        matching_auths = auth_by_uid.get(uid, [])
        is_dup_id = len(matching_auths) > 1 or len(users_by_uid.get(uid, [])) > 1

        # Match auth record: prefer matching username, else first unused, else first
        matched_auth = None
        matched_idx = None
        u_uname = str(u.get("username") or "").strip().lower()

        for idx, a in enumerate(matching_auths):
            a_key = (uid, idx)
            if a_key not in used_auth_indices:
                a_uname = str(a.get("username") or "").strip().lower()
                if u_uname and a_uname == u_uname:
                    matched_auth = a
                    matched_idx = a_key
                    break

        if not matched_auth:
            for idx, a in enumerate(matching_auths):
                a_key = (uid, idx)
                if a_key not in used_auth_indices:
                    matched_auth = a
                    matched_idx = a_key
                    break

        if matched_idx is not None:
            used_auth_indices.add(matched_idx)
        elif matching_auths:
            matched_auth = matching_auths[0]

        real_username = str((matched_auth.get("username") if matched_auth else None) or u.get("username") or uid).strip()

        if is_dup_id:
            is_active = False
            sync_warning = "CRITICAL: Duplicate user_id detected across multiple sheet rows. Updates frozen until resolved by Owner."
        elif not matched_auth:
            is_active = False
            sync_warning = "No login account found in AuthUsers sheet"
        else:
            u_active = str(u.get("active", "true")).lower() in {"true", "1", "yes"}
            a_active = str(matched_auth.get("active", "true")).lower() in {"true", "1", "yes"}
            is_active = u_active and a_active
            sync_warning = "" if u_active == a_active else "Status mismatch between profile and credentials"

        result.append({
            "user_id": uid,
            "full_name": str(u.get("full_name") or ""),
            "username": real_username,
            "role": str((matched_auth.get("role") if matched_auth else None) or u.get("role") or "SALESMAN"),
            "mobile": str(u.get("mobile") or ""),
            "email": str(u.get("email") or ""),
            "active": is_active,
            "created_at": str(u.get("created_at") or ""),
            "notes": str(u.get("notes") or ""),
            "sync_warning": sync_warning,
            "has_duplicate_id": is_dup_id,
        })

    # Also include any unused/orphaned AuthUsers records
    for uid, auth_list in auth_by_uid.items():
        for idx, a in enumerate(auth_list):
            if (uid, idx) not in used_auth_indices:
                uname = str(a.get("username") or uid).strip()
                result.append({
                    "user_id": uid,
                    "full_name": f"[Auth Only] {uname}",
                    "username": uname,
                    "role": str(a.get("role") or "SALESMAN"),
                    "mobile": "",
                    "email": "",
                    "active": False,
                    "created_at": str(a.get("created_at") or ""),
                    "notes": "Orphaned authentication record without matching profile",
                    "sync_warning": "Credentials exist in AuthUsers but profile is missing in Users sheet",
                    "has_duplicate_id": len(auth_list) > 1,
                })

    return result


def audit_user_reconciliation() -> Dict[str, Any]:
    """
    Read-only independent audit of Users and AuthUsers sheets.
    Detects mismatches, orphaned profiles, missing auth credentials,
    duplicate IDs/usernames, role divergence, and inactive desynchronization.
    """
    users = db.get_records("Users", fresh=True) or []
    auth_users = db.get_records("AuthUsers", fresh=True) or []

    users_by_id: Dict[str, List[dict]] = {}
    for u in users:
        uid = str(u.get("user_id") or "").strip()
        if uid:
            users_by_id.setdefault(uid, []).append(u)

    auth_by_id: Dict[str, List[dict]] = {}
    auth_by_username: Dict[str, List[dict]] = {}
    for a in auth_users:
        uid = str(a.get("user_id") or "").strip()
        uname = str(a.get("username") or "").strip().lower()
        if uid:
            auth_by_id.setdefault(uid, []).append(a)
        if uname:
            auth_by_username.setdefault(uname, []).append(a)

    orphaned_profiles = []
    orphaned_auth_accounts = []
    duplicate_users = []
    duplicate_auth_users = []
    duplicate_usernames = []
    role_mismatches = []
    status_mismatches = []
    insecure_credentials = []

    # Check duplicate user_ids in Users
    for uid, rows in users_by_id.items():
        if len(rows) > 1:
            duplicate_users.append({"user_id": uid, "count": len(rows)})

    # Check duplicate user_ids in AuthUsers
    for uid, rows in auth_by_id.items():
        if len(rows) > 1:
            duplicate_auth_users.append({"user_id": uid, "count": len(rows)})

    # Check duplicate usernames in AuthUsers
    for uname, rows in auth_by_username.items():
        if len(rows) > 1:
            duplicate_usernames.append({"username": uname, "user_ids": [r.get("user_id") for r in rows]})

    # Check orphaned Users and consistency with AuthUsers
    for uid, rows in users_by_id.items():
        u = rows[0]
        if uid not in auth_by_id:
            orphaned_profiles.append({
                "user_id": uid,
                "full_name": u.get("full_name"),
                "username": u.get("username"),
                "role": u.get("role"),
                "active": u.get("active"),
                "issue": "Profile exists in Users sheet but has NO login credentials in AuthUsers sheet.",
            })
        else:
            a = auth_by_id[uid][0]
            u_role = str(u.get("role") or "").strip().upper()
            a_role = str(a.get("role") or "").strip().upper()
            if u_role != a_role:
                role_mismatches.append({
                    "user_id": uid,
                    "username": a.get("username") or u.get("username"),
                    "users_role": u_role,
                    "auth_role": a_role,
                    "issue": f"Role mismatch: Users says '{u_role}' but AuthUsers says '{a_role}'.",
                })

            u_active = str(u.get("active", "true")).lower() in {"true", "1", "yes"}
            a_active = str(a.get("active", "true")).lower() in {"true", "1", "yes"}
            if u_active != a_active:
                status_mismatches.append({
                    "user_id": uid,
                    "username": a.get("username") or u.get("username"),
                    "users_active": u_active,
                    "auth_active": a_active,
                    "issue": f"Status mismatch: Users is {'active' if u_active else 'inactive'} but AuthUsers is {'active' if a_active else 'inactive'}.",
                })

    # Check orphaned AuthUsers
    for uid, rows in auth_by_id.items():
        a = rows[0]
        if uid not in users_by_id:
            orphaned_auth_accounts.append({
                "user_id": uid,
                "username": a.get("username"),
                "role": a.get("role"),
                "active": a.get("active"),
                "issue": "Login credentials exist in AuthUsers sheet but has NO profile in Users sheet.",
            })
        # Check empty or blank password hash
        pw_hash = str(a.get("password_hash") or "").strip()
        if not pw_hash:
            insecure_credentials.append({
                "user_id": uid,
                "username": a.get("username"),
                "issue": "Empty or missing password hash in AuthUsers.",
            })

    # Check duplicate auth_ids in AuthUsers
    auth_by_auth_id: Dict[str, List[dict]] = {}
    for a in auth_users:
        aid = str(a.get("auth_id") or "").strip()
        if aid:
            auth_by_auth_id.setdefault(aid, []).append(a)

    duplicate_auth_ids = []
    for aid, rows in auth_by_auth_id.items():
        if len(rows) > 1:
            duplicate_auth_ids.append({
                "auth_id": aid,
                "count": len(rows),
                "user_ids": [r.get("user_id") for r in rows],
                "usernames": [r.get("username") for r in rows],
                "issue": f"Duplicate auth_id '{aid}' shared across {len(rows)} AuthUsers rows.",
            })

    # Check incomplete Owner profile (C4)
    incomplete_owner_profiles = []
    for u in users:
        if str(u.get("role") or "").strip().upper() == "OWNER":
            fname = str(u.get("full_name") or "").strip()
            uname = str(u.get("username") or "").strip()
            if fname.lower() in {"your full name", "owner", ""} or not uname:
                incomplete_owner_profiles.append({
                    "user_id": u.get("user_id"),
                    "full_name": fname,
                    "username": uname,
                    "issue": "Owner profile contains placeholder full_name ('Your Full Name') or blank username in Users sheet.",
                })

    total_issues = (
        len(orphaned_profiles) +
        len(orphaned_auth_accounts) +
        len(duplicate_users) +
        len(duplicate_auth_users) +
        len(duplicate_auth_ids) +
        len(duplicate_usernames) +
        len(role_mismatches) +
        len(status_mismatches) +
        len(insecure_credentials) +
        len(incomplete_owner_profiles)
    )

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "total_users_count": len(users),
        "total_auth_users_count": len(auth_users),
        "healthy": total_issues == 0,
        "total_issues_count": total_issues,
        "orphaned_profiles": orphaned_profiles,
        "orphaned_auth_accounts": orphaned_auth_accounts,
        "duplicate_users": duplicate_users,
        "duplicate_auth_users": duplicate_auth_users,
        "duplicate_auth_ids": duplicate_auth_ids,
        "duplicate_usernames": duplicate_usernames,
        "role_mismatches": role_mismatches,
        "status_mismatches": status_mismatches,
        "insecure_credentials": insecure_credentials,
        "incomplete_owner_profiles": incomplete_owner_profiles,
    }


def validate_unique_username(username: str, exclude_user_id: Optional[str] = None) -> None:
    """Ensure username is unique across all AuthUsers records."""
    clean_username = username.strip().lower()
    if not clean_username:
        raise HTTPException(status_code=422, detail="Username cannot be blank.")
    
    auth_records = db.get_records("AuthUsers", fresh=True) or []
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
    """
    Two-phase creation of profile (Users) and credentials (AuthUsers) with safe failure rollback
    and idempotent replay support.
    """
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

    # Idempotent check: if user already exists with both profile and credentials, return existing
    auth_records = db.get_records("AuthUsers", fresh=True) or []
    existing_auth = next((a for a in auth_records if str(a.get("username", "")).strip().lower() == username.lower()), None)
    if existing_auth:
        user_records = db.get_records("Users", fresh=True) or []
        existing_user = next((u for u in user_records if str(u.get("user_id", "")).strip() == str(existing_auth.get("user_id", "")).strip()), None)
        if existing_user:
            return {
                "user_id": existing_user.get("user_id"),
                "full_name": existing_user.get("full_name"),
                "username": existing_auth.get("username"),
                "role": existing_auth.get("role"),
                "mobile": existing_user.get("mobile", ""),
                "email": existing_user.get("email", ""),
                "active": str(existing_auth.get("active", "true")).lower() in {"true", "1", "yes"},
                "created_at": existing_user.get("created_at", ""),
                "notes": existing_user.get("notes", ""),
                "idempotent": True,
            }

    validate_unique_username(username)

    # Secure onboarding rule: If password is not provided (e.g. Approved PA request), generate secure temporary password
    temporary_password = ""
    must_change = "false"
    if not password:
        temporary_password = f"Kawad@{secrets.token_hex(4)}"
        password = temporary_password
        must_change = "true"
    elif len(password) < 8:
        raise HTTPException(status_code=422, detail="Password must be at least 8 characters.")

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
        "must_change_password": must_change,
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

    resp = {
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
    if temporary_password:
        resp["temporary_password"] = temporary_password
        resp["must_change_password"] = True
    return resp


def execute_update_user(user_id: str, payload: Dict[str, Any], actor_user_id: str) -> Dict[str, Any]:
    """
    Update profile and credentials, revoking existing sessions if role changes.
    Guarantees atomic rollback if AuthUsers synchronization fails so records never disagree.
    """
    user_records = db.get_records("Users", fresh=True) or []
    matching_users = [u for u in user_records if str(u.get("user_id") or "").strip() == user_id.strip()]
    if len(matching_users) > 1:
        raise HTTPException(
            status_code=409,
            detail=f"Ambiguous identity: Multiple employee records ({len(matching_users)}) exist with user_id '{user_id}'. Account changes are frozen until duplicates are resolved by Owner.",
        )
    target = matching_users[0] if matching_users else None
    if not target:
        raise HTTPException(status_code=404, detail="Employee record not found.")

    auth_records = db.get_records("AuthUsers", fresh=True) or []
    matching_auth = [a for a in auth_records if str(a.get("user_id") or "").strip() == user_id.strip()]
    if len(matching_auth) > 1:
        raise HTTPException(
            status_code=409,
            detail=f"Ambiguous identity: Multiple authentication records ({len(matching_auth)}) exist with user_id '{user_id}'. Account changes are frozen until duplicates are resolved by Owner.",
        )

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

    # Idempotent check: if nothing changed, return target state
    if not user_updates:
        merged = dict(target)
        merged["active"] = str(merged.get("active", "true")).lower() in {"true", "1", "yes"}
        return merged

    all_matched = True
    for k, v in user_updates.items():
        if str(target.get(k, "")).strip() != str(v).strip():
            all_matched = False
            break
    if all_matched:
        merged = dict(target)
        merged["active"] = str(merged.get("active", "true")).lower() in {"true", "1", "yes"}
        merged["idempotent"] = True
        return merged

    if not db.update_record("Users", "user_id", user_id, user_updates, raise_on_error=True):
        raise HTTPException(status_code=503, detail="Failed to update Users record in Google Sheets.")

    # Synchronize AuthUsers
    auth_updates: Dict[str, Any] = {}
    if "full_name" in user_updates:
        auth_updates["full_name"] = user_updates["full_name"]
    if "role" in user_updates and user_updates["role"] != old_role:
        auth_updates["role"] = user_updates["role"]
        # Audit requirement: Role change must immediately revoke existing sessions!
        now_epoch = time.time()
        now_iso = datetime.now(timezone.utc).isoformat()
        _USER_REVOKED_AT[str(user_id or "").strip().lower()] = now_epoch
        auth_updates["sessions_revoked_at"] = now_iso

    if auth_updates:
        try:
            if not db.update_record("AuthUsers", "user_id", user_id, auth_updates, raise_on_error=True):
                raise RuntimeError("AuthUsers update returned False")
        except Exception as exc:
            # Audit P0 Rule: Partial write detected! Roll back Users to prevent account divergence.
            logger.error(f"AuthUsers sync failed for {user_id}. Rolling back Users profile: {exc}")
            rollback_fields = {
                "full_name": str(target.get("full_name") or ""),
                "role": old_role,
                "mobile": str(target.get("mobile") or ""),
                "email": str(target.get("email") or ""),
                "notes": str(target.get("notes") or ""),
            }
            try:
                db.update_record("Users", "user_id", user_id, rollback_fields, raise_on_error=True)
            except Exception:
                pass
            raise HTTPException(
                status_code=503,
                detail=f"Failed to synchronize authentication credentials in AuthUsers ({exc}). Profile update was safely rolled back to prevent account mismatch.",
            )

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
    """
    Toggle user active/deactive status in both Users and AuthUsers.
    Guarantees atomic rollback if AuthUsers update fails so status records never disagree.
    """
    user_records = db.get_records("Users", fresh=True) or []
    matching_u = [u for u in user_records if str(u.get("user_id") or "").strip() == user_id.strip()]
    if len(matching_u) > 1:
        raise HTTPException(
            status_code=409,
            detail=f"Ambiguous identity: Multiple employee records ({len(matching_u)}) exist with user_id '{user_id}'. Account changes are frozen until duplicates are resolved by Owner.",
        )
    target_u = matching_u[0] if matching_u else None

    auth_records = db.get_records("AuthUsers", fresh=True) or []
    matching_a = [a for a in auth_records if str(a.get("user_id") or "").strip() == user_id.strip()]
    if len(matching_a) > 1:
        raise HTTPException(
            status_code=409,
            detail=f"Ambiguous identity: Multiple authentication records ({len(matching_a)}) exist with user_id '{user_id}'. Account changes are frozen until duplicates are resolved by Owner.",
        )
    target_a = matching_a[0] if matching_a else None

    # Idempotent check
    if target_u and target_a:
        u_act = str(target_u.get("active", "true")).lower() in {"true", "1", "yes"}
        a_act = str(target_a.get("active", "true")).lower() in {"true", "1", "yes"}
        if u_act == active and a_act == active:
            return {"ok": True, "user_id": user_id, "active": active, "idempotent": True}

    active_str = "true" if active else "false"
    old_active_str = "false" if active else "true"

    # Step 1: Update Users
    if not db.update_record("Users", "user_id", user_id, {"active": active_str}, raise_on_error=True):
        raise HTTPException(status_code=503, detail="Failed to update status in Users sheet.")

    # Step 2: Update AuthUsers
    auth_updates = {"active": active_str}
    if not active:
        # Invalidate all existing sessions immediately across devices
        now_epoch = time.time()
        now_iso = datetime.now(timezone.utc).isoformat()
        _USER_REVOKED_AT[str(user_id or "").strip().lower()] = now_epoch
        auth_updates["sessions_revoked_at"] = now_iso

    try:
        if not db.update_record("AuthUsers", "user_id", user_id, auth_updates, raise_on_error=True):
            raise RuntimeError("AuthUsers status update returned False")
    except Exception as exc:
        # Audit P0 Rule: Partial write detected! Roll back Users status to prevent account divergence.
        logger.error(f"AuthUsers status update failed for {user_id}. Rolling back Users status: {exc}")
        try:
            db.update_record("Users", "user_id", user_id, {"active": old_active_str}, raise_on_error=True)
        except Exception:
            pass
        raise HTTPException(
            status_code=503,
            detail=f"Failed to synchronize status in AuthUsers ({exc}). Status change was safely rolled back to prevent account mismatch.",
        )

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

    auth_records = db.get_records("AuthUsers", fresh=True) or []
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
    return {
        "ok": True,
        "user_id": user_id,
        "must_change_password": True,
        "active": current_active_status == "true",
    }
