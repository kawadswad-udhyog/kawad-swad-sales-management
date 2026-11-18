#!/usr/bin/env python3
"""Secure, local-only bootstrap for the first Kawad Swad Owner account.

Run from a trusted owner-controlled machine:
    python backend/scripts/bootstrap_owner.py

The public FastAPI bootstrap endpoint is intentionally disabled. This utility
requires direct access to the configured Google Sheets service account.
"""
import getpass
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.sheets import db
from app.auth import hash_password


def _read_rows(tab_name):
    rows = db.get_records(tab_name, fresh=True)
    if rows is None:
        raise RuntimeError(f"Could not verify {tab_name}; refusing bootstrap.")
    return [row for row in rows if any(str(value or "").strip() for value in row.values())]


def bootstrap_owner():
    print("=== Kawad Swad ERP: Local First-Owner Bootstrap ===")
    print("This command creates the first Owner account in the configured Google Sheet.")
    print("It does not restore or import any pre-reset business data.\n")

    if not db.init_connection() or not db.is_connected or db.spreadsheet is None:
        raise RuntimeError(f"Google Sheets connection failed: {db.last_connection_error or 'unknown error'}")

    users = _read_rows("Users")
    auth_users = _read_rows("AuthUsers")
    if users or auth_users:
        raise RuntimeError(
            "Bootstrap refused: Users or AuthUsers already contains records. "
            "Do not clear these tabs to force bootstrap; reconcile the existing state first."
        )

    username = input("Owner username (3-50 characters): ").strip().lower()
    if not re.fullmatch(r"[a-z0-9._-]{3,50}", username):
        raise ValueError("Username must use 3-50 lowercase letters, numbers, dots, underscores or hyphens.")

    full_name = input("Owner full name: ").strip()
    if len(full_name) < 2:
        raise ValueError("Full name must contain at least 2 characters.")

    password = getpass.getpass("Owner password (minimum 12 characters): ")
    confirmation = getpass.getpass("Confirm owner password: ")
    if len(password) < 12:
        raise ValueError("Owner password must be at least 12 characters.")
    if password != confirmation:
        raise ValueError("Passwords do not match.")

    confirm = input("Type CREATE FIRST OWNER to continue: ").strip()
    if confirm != "CREATE FIRST OWNER":
        print("Cancelled. No account was created.")
        return

    # Recheck immediately before allocating IDs and appending records.
    if _read_rows("Users") or _read_rows("AuthUsers"):
        raise RuntimeError("Bootstrap aborted: account rows appeared during confirmation.")

    user_id = db.generate_id("Users")
    auth_id = db.generate_id("AuthUsers")
    now_iso = datetime.now(timezone.utc).isoformat()

    user_record = {
        "user_id": user_id,
        "full_name": full_name,
        "username": username,
        "role": "OWNER",
        "mobile": "",
        "email": "",
        "active": "true",
        "created_at": now_iso,
        "notes": "Initial Owner account created through local-only bootstrap utility",
        "created_by": user_id,
        "updated_at": now_iso,
        "effective_from": now_iso,
        "effective_to": "",
    }
    auth_record = {
        "auth_id": auth_id,
        "user_id": user_id,
        "username": username,
        "password_hash": hash_password(password),
        "role": "OWNER",
        "active": "true",
        "created_at": now_iso,
        "must_change_password": "false",
        "sessions_revoked_at": "",
    }

    user_written = False
    auth_written = False
    try:
        if not db.append_record("Users", user_record, raise_on_error=True):
            raise RuntimeError("Users row append was not confirmed.")
        user_written = True

        if not db.append_record("AuthUsers", auth_record, raise_on_error=True):
            raise RuntimeError("AuthUsers row append was not confirmed.")
        auth_written = True

        # Read-back verification is required before declaring success.
        users_after = _read_rows("Users")
        auth_after = _read_rows("AuthUsers")
        user_ok = any(str(row.get("user_id")) == user_id for row in users_after)
        auth_ok = any(
            str(row.get("user_id")) == user_id
            and str(row.get("username", "")).strip().lower() == username
            and str(row.get("password_hash", "")).startswith("pbkdf2:sha256:")
            for row in auth_after
        )
        if not (user_ok and auth_ok):
            raise RuntimeError("Owner rows could not be verified by read-back. Stop and reconcile manually.")

    except Exception:
        rollback_errors = []
        if auth_written:
            try:
                db.delete_record("AuthUsers", "user_id", user_id, raise_on_error=True)
            except Exception as rollback_error:
                rollback_errors.append(f"AuthUsers rollback failed: {rollback_error}")
        if user_written:
            try:
                db.delete_record("Users", "user_id", user_id, raise_on_error=True)
            except Exception as rollback_error:
                rollback_errors.append(f"Users rollback failed: {rollback_error}")
        if rollback_errors:
            raise RuntimeError(
                f"Bootstrap is partially written. User ID {user_id}; Auth ID {auth_id}. "
                + " | ".join(rollback_errors)
                + " Do not retry before manual reconciliation."
            )
        raise
    finally:
        password = ""
        confirmation = ""

    db.log_audit(
        actor=user_id,
        action="BOOTSTRAP_OWNER",
        entity_type="AuthUsers",
        entity_id=user_id,
        reason="First Owner account created through local-only bootstrap utility",
    )
    print("\n[SUCCESS] Owner account created and verified.")
    print(f"User ID: {user_id}")
    print(f"Username: {username}")
    print("Password was not displayed or saved by this utility.")


if __name__ == "__main__":
    try:
        bootstrap_owner()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
