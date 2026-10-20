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


VALID_ROLES = {"OWNER", "PA", "SALESMAN", "PRODUCTION", "DISPATCH"}
VALID_BOOLEANS = {"true", "false", "1", "0", "yes", "no"}
PLACEHOLDER_NAMES = {"your full name", "test user", "placeholder", "dummy", "admin", "owner", ""}


def audit_user_reconciliation() -> Dict[str, Any]:
    """
    Read-only independent audit of Users and AuthUsers sheets.
    Detects:
    - Sheet connectivity errors (returns status="INCOMPLETE")
    - Orphaned profiles and orphaned auth credentials
    - Duplicate employee IDs in Users and AuthUsers
    - Duplicate auth_ids in AuthUsers
    - Duplicate usernames (case-insensitive normalized)
    - Username mismatches between Users and AuthUsers (Finding 1)
    - Ambiguous duplicate identities with full details without arbitrary cross-row matching (Finding 2)
    - Role and status mismatches on unambiguous records
    - Missing or malformed records: blank IDs, missing usernames, invalid roles, invalid booleans, malformed password hashes (Finding 3)
    - Insecure / missing credentials
    - Incomplete or placeholder Owner profiles (Finding C4)
    """
    try:
        users = db.get_records("Users", fresh=True) or []
        auth_users = db.get_records("AuthUsers", fresh=True) or []
    except Exception as exc:
        logger.error(f"Failed to read sheets for reconciliation audit: {exc}")
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "status": "INCOMPLETE",
            "healthy": False,
            "error_detail": f"Could not complete reconciliation audit: Google Sheets read failed ({exc}).",
            "total_issues_count": 1,
            "system_errors": [str(exc)],
            "total_users_count": 0,
            "total_auth_users_count": 0,
            "orphaned_profiles": [],
            "orphaned_auth_accounts": [],
            "duplicate_users": [],
            "duplicate_auth_users": [],
            "duplicate_auth_ids": [],
            "duplicate_usernames": [],
            "username_mismatches": [],
            "ambiguous_identity_records": [],
            "role_mismatches": [],
            "status_mismatches": [],
            "malformed_or_invalid_records": [],
            "insecure_credentials": [],
            "incomplete_owner_profiles": [],
        }

    # Group by user_id
    users_by_id: Dict[str, List[dict]] = {}
    for idx, u in enumerate(users):
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
    duplicate_auth_ids = []
    duplicate_usernames = []
    username_mismatches = []
    ambiguous_identity_records = []
    role_mismatches = []
    status_mismatches = []
    malformed_or_invalid_records = []
    insecure_credentials = []
    incomplete_owner_profiles = []

    # 1. Missing or malformed records validation (Finding 3)
    for idx, u in enumerate(users):
        row_num = idx + 2
        uid = str(u.get("user_id") or "").strip()
        fname = str(u.get("full_name") or "").strip()
        role = str(u.get("role") or "").strip().upper()
        active = str(u.get("active") or "").strip().lower()

        if not uid:
            malformed_or_invalid_records.append({
                "sheet": "Users",
                "row_index": row_num,
                "field": "user_id",
                "value": "",
                "issue": "Blank or missing user_id in Users sheet.",
            })
        if not fname or fname.lower() in PLACEHOLDER_NAMES:
            malformed_or_invalid_records.append({
                "sheet": "Users",
                "row_index": row_num,
                "user_id": uid,
                "field": "full_name",
                "value": fname,
                "issue": f"Placeholder or missing employee full_name: '{fname or '<blank>'}'.",
            })
        if role and role not in VALID_ROLES:
            malformed_or_invalid_records.append({
                "sheet": "Users",
                "row_index": row_num,
                "user_id": uid,
                "field": "role",
                "value": role,
                "issue": f"Unrecognized role '{role}' in Users sheet (allowed: {', '.join(sorted(VALID_ROLES))}).",
            })
        if active and active not in VALID_BOOLEANS:
            malformed_or_invalid_records.append({
                "sheet": "Users",
                "row_index": row_num,
                "user_id": uid,
                "field": "active",
                "value": active,
                "issue": f"Invalid active-status format '{active}' in Users sheet.",
            })

    for idx, a in enumerate(auth_users):
        row_num = idx + 2
        uid = str(a.get("user_id") or "").strip()
        aid = str(a.get("auth_id") or "").strip()
        uname = str(a.get("username") or "").strip()
        role = str(a.get("role") or "").strip().upper()
        active = str(a.get("active") or "").strip().lower()
        pw_hash = str(a.get("password_hash") or "").strip()

        if not uid:
            malformed_or_invalid_records.append({
                "sheet": "AuthUsers",
                "row_index": row_num,
                "field": "user_id",
                "value": "",
                "issue": "Blank or missing user_id in AuthUsers sheet.",
            })
        if not aid:
            malformed_or_invalid_records.append({
                "sheet": "AuthUsers",
                "row_index": row_num,
                "user_id": uid,
                "field": "auth_id",
                "value": "",
                "issue": "Blank or missing auth_id in AuthUsers sheet.",
            })
        if not uname:
            malformed_or_invalid_records.append({
                "sheet": "AuthUsers",
                "row_index": row_num,
                "user_id": uid,
                "field": "username",
                "value": "",
                "issue": "Blank or missing username in AuthUsers sheet.",
            })
        if role and role not in VALID_ROLES:
            malformed_or_invalid_records.append({
                "sheet": "AuthUsers",
                "row_index": row_num,
                "user_id": uid,
                "field": "role",
                "value": role,
                "issue": f"Unrecognized role '{role}' in AuthUsers sheet.",
            })
        if active and active not in VALID_BOOLEANS:
            malformed_or_invalid_records.append({
                "sheet": "AuthUsers",
                "row_index": row_num,
                "user_id": uid,
                "field": "active",
                "value": active,
                "issue": f"Invalid active-status format '{active}' in AuthUsers sheet.",
            })
        if not pw_hash:
            insecure_credentials.append({
                "user_id": uid,
                "username": uname,
                "issue": "Empty or missing password hash in AuthUsers.",
            })
        elif not (pw_hash.startswith("pbkdf2:sha256:") and len(pw_hash.split("$")) == 3):
            malformed_or_invalid_records.append({
                "sheet": "AuthUsers",
                "row_index": row_num,
                "user_id": uid,
                "username": uname,
                "field": "password_hash",
                "issue": "Malformed or insecure password hash (not in standard PBKDF2-SHA256 format).",
            })

    # 2. Check duplicates in Users and AuthUsers
    for uid, rows in users_by_id.items():
        if len(rows) > 1:
            duplicate_users.append({
                "user_id": uid,
                "count": len(rows),
                "profiles": [{"full_name": r.get("full_name"), "username": r.get("username"), "role": r.get("role")} for r in rows],
            })

    for uid, rows in auth_by_id.items():
        if len(rows) > 1:
            duplicate_auth_users.append({
                "user_id": uid,
                "count": len(rows),
                "logins": [{"auth_id": r.get("auth_id"), "username": r.get("username"), "role": r.get("role")} for r in rows],
            })

    # Check duplicate auth_ids
    auth_by_auth_id: Dict[str, List[dict]] = {}
    for a in auth_users:
        aid = str(a.get("auth_id") or "").strip()
        if aid:
            auth_by_auth_id.setdefault(aid, []).append(a)

    for aid, rows in auth_by_auth_id.items():
        if len(rows) > 1:
            duplicate_auth_ids.append({
                "auth_id": aid,
                "count": len(rows),
                "user_ids": [r.get("user_id") for r in rows],
                "usernames": [r.get("username") for r in rows],
                "issue": f"Duplicate auth_id '{aid}' shared across {len(rows)} AuthUsers rows.",
            })

    # Check duplicate usernames
    for uname, rows in auth_by_username.items():
        if len(rows) > 1:
            duplicate_usernames.append({
                "username": uname,
                "count": len(rows),
                "user_ids": [r.get("user_id") for r in rows],
            })

    # 3. Handle Ambiguous Identifiers vs 1-to-1 Field Comparisons (Finding 2)
    all_uids = set(users_by_id.keys()).union(set(auth_by_id.keys()))
    for uid in all_uids:
        u_rows = users_by_id.get(uid, [])
        a_rows = auth_by_id.get(uid, [])

        if len(u_rows) > 1 or len(a_rows) > 1:
            # Ambiguous identity! Record under ambiguous_identity_records and avoid arbitrary row-0 assertions
            ambiguous_identity_records.append({
                "user_id": uid,
                "users_rows_count": len(u_rows),
                "auth_rows_count": len(a_rows),
                "users_records": [
                    {"full_name": r.get("full_name"), "username": r.get("username"), "role": r.get("role"), "active": r.get("active")}
                    for r in u_rows
                ],
                "auth_records": [
                    {"auth_id": r.get("auth_id"), "username": r.get("username"), "role": r.get("role"), "active": r.get("active")}
                    for r in a_rows
                ],
                "issue": f"Ambiguous identity: Multiple records share user_id '{uid}'. Unambiguous field comparison is frozen until separate IDs are assigned.",
            })
            continue

        if len(u_rows) == 1 and len(a_rows) == 0:
            u = u_rows[0]
            orphaned_profiles.append({
                "user_id": uid,
                "full_name": u.get("full_name"),
                "username": u.get("username"),
                "role": u.get("role"),
                "active": u.get("active"),
                "issue": "Profile exists in Users sheet but has NO login credentials in AuthUsers sheet.",
            })
        elif len(u_rows) == 0 and len(a_rows) == 1:
            a = a_rows[0]
            orphaned_auth_accounts.append({
                "user_id": uid,
                "username": a.get("username"),
                "role": a.get("role"),
                "active": a.get("active"),
                "issue": "Login credentials exist in AuthUsers sheet but has NO profile in Users sheet.",
            })
        elif len(u_rows) == 1 and len(a_rows) == 1:
            u = u_rows[0]
            a = a_rows[0]

            # Finding 1: Check username mismatches
            u_uname_raw = str(u.get("username") or "").strip()
            a_uname_raw = str(a.get("username") or "").strip()
            if u_uname_raw and a_uname_raw and u_uname_raw.lower() != a_uname_raw.lower():
                username_mismatches.append({
                    "user_id": uid,
                    "users_username": u_uname_raw,
                    "auth_username": a_uname_raw,
                    "issue": f"Username mismatch: Users sheet has '{u_uname_raw}' but AuthUsers sheet has '{a_uname_raw}'.",
                })

            # Check role mismatches
            u_role = str(u.get("role") or "").strip().upper()
            a_role = str(a.get("role") or "").strip().upper()
            if u_role != a_role:
                role_mismatches.append({
                    "user_id": uid,
                    "username": a_uname_raw or u_uname_raw,
                    "users_role": u_role,
                    "auth_role": a_role,
                    "issue": f"Role mismatch: Users says '{u_role}' but AuthUsers says '{a_role}'.",
                })

            # Check status mismatches
            u_active = str(u.get("active", "true")).lower() in {"true", "1", "yes"}
            a_active = str(a.get("active", "true")).lower() in {"true", "1", "yes"}
            if u_active != a_active:
                status_mismatches.append({
                    "user_id": uid,
                    "username": a_uname_raw or u_uname_raw,
                    "users_active": u_active,
                    "auth_active": a_active,
                    "issue": f"Status mismatch: Users is {'active' if u_active else 'inactive'} but AuthUsers is {'active' if a_active else 'inactive'}.",
                })

    # Incomplete Owner profile check (C4)
    for u in users:
        if str(u.get("role") or "").strip().upper() == "OWNER":
            fname = str(u.get("full_name") or "").strip()
            uname = str(u.get("username") or "").strip()
            if fname.lower() in PLACEHOLDER_NAMES or not uname:
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
        len(username_mismatches) +
        len(ambiguous_identity_records) +
        len(role_mismatches) +
        len(status_mismatches) +
        len(malformed_or_invalid_records) +
        len(insecure_credentials) +
        len(incomplete_owner_profiles)
    )

    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "status": "COMPLETED",
        "healthy": total_issues == 0,
        "total_issues_count": total_issues,
        "total_users_count": len(users),
        "total_auth_users_count": len(auth_users),
        "username_mismatches": username_mismatches,
        "ambiguous_identity_records": ambiguous_identity_records,
        "malformed_or_invalid_records": malformed_or_invalid_records,
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


def inspect_user_references(user_id: str) -> Dict[str, Any]:
    """
    Search across all ledger, sales, production, and audit tabs to identify
    every historical transaction referencing user_id before renumbering or repairing.
    """
    clean_id = str(user_id or "").strip()
    references: Dict[str, List[Dict[str, Any]]] = {
        "Sales": [],
        "Payments": [],
        "ProductionBatches": [],
        "PackagingBatches": [],
        "ProductionStockLedger": [],
        "RawMaterialLedger": [],
        "ApprovalRequests": [],
        "AuditTrail": [],
    }

    if not clean_id:
        return {"user_id": clean_id, "total_references": 0, "references": references}

    try:
        sales = db.get_records("Sales", fresh=True) or []
        for s in sales:
            if clean_id in {str(s.get("salesman_id", "")).strip(), str(s.get("created_by", "")).strip()}:
                references["Sales"].append({"sale_id": s.get("sale_id"), "date": s.get("sale_date"), "amount": s.get("total_amount")})

        payments = db.get_records("Payments", fresh=True) or []
        for p in payments:
            if clean_id in {str(p.get("received_by", "")).strip(), str(p.get("created_by", "")).strip()}:
                references["Payments"].append({"payment_id": p.get("payment_id"), "date": p.get("payment_date"), "amount": p.get("amount")})

        prod_batches = db.get_records("ProductionBatches", fresh=True) or []
        for b in prod_batches:
            if clean_id in {str(b.get("created_by", "")).strip(), str(b.get("approved_by", "")).strip()}:
                references["ProductionBatches"].append({"production_id": b.get("production_id"), "product": b.get("product_name_snapshot"), "status": b.get("status")})

        pack_batches = db.get_records("PackagingBatches", fresh=True) or []
        for pb in pack_batches:
            if clean_id in {str(pb.get("created_by", "")).strip(), str(pb.get("approved_by", "")).strip()}:
                references["PackagingBatches"].append({"packaging_id": pb.get("packaging_id"), "product": pb.get("product_name_snapshot"), "status": pb.get("status")})

        approvals = db.get_records("ApprovalRequests", fresh=True) or []
        for ar in approvals:
            if clean_id in {str(ar.get("requested_by", "")).strip(), str(ar.get("approved_by", "")).strip(), str(ar.get("target_user_id", "")).strip()}:
                references["ApprovalRequests"].append({"request_id": ar.get("request_id"), "type": ar.get("request_type"), "status": ar.get("status")})

        audit_rows = db.get_records("AuditTrail", fresh=True) or []
        for a in audit_rows:
            if clean_id in {str(a.get("actor", "")).strip(), str(a.get("entity_id", "")).strip()}:
                references["AuditTrail"].append({"audit_id": a.get("audit_id"), "action": a.get("action"), "entity_type": a.get("entity_type")})
    except Exception as exc:
        logger.warning(f"Error inspecting user references for {clean_id}: {exc}")

    total_refs = sum(len(v) for v in references.values())
    return {
        "user_id": clean_id,
        "total_references": total_refs,
        "references": references,
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
