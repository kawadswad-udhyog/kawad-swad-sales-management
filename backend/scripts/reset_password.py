#!/usr/bin/env python3
"""Set a PBKDF2 password for an existing username.

Run from the backend directory on a machine that already has the spreadsheet
credentials in the environment. The new password is read from the terminal and
is not printed back.

    python scripts/reset_password.py
"""
import getpass
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.auth import hash_password
from app.sheets import db


def main():
    username = input("Username to reset: ").strip()
    if not username:
        print("Username is required.")
        return 1
    password = getpass.getpass("New password (min 8 characters): ")
    if len(password) < 8:
        print("Password must be at least 8 characters.")
        return 1
    confirm = getpass.getpass("Repeat new password: ")
    if password != confirm:
        print("Passwords did not match. Nothing was changed.")
        return 1
    rows = db.get_records("AuthUsers", fresh=True)
    match = next((row for row in rows if str(row.get("username", "")).strip().lower() == username.lower()), None)
    if not match:
        print("No login row with that username was found. Nothing was changed.")
        return 1
    saved = db.update_record("AuthUsers", "user_id", str(match.get("user_id")), {
        "password_hash": hash_password(password),
        "must_change_password": "true",
    })
    if not saved:
        print("The password could not be saved. Check the spreadsheet connection.")
        return 1
    print("Password updated. The user must change it after the next sign-in.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
