#!/usr/bin/env python3
"""
Bootstrap utility to initialize the first OWNER account in Google Sheets AuthUsers and Users tabs.
Usage:
    python backend/scripts/bootstrap_owner.py
"""
import sys
import os
from datetime import datetime

# Add backend directory to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.sheets import db
from app.auth import hash_password

def bootstrap_owner():
    print("=== Kawad Swad Sales Management - Owner Account Bootstrap ===")
    
    username = input("Enter Owner username (e.g. ankit): ").strip()
    if not username:
        print("Error: Username cannot be empty.")
        return

    full_name = input("Enter Owner Full Name (e.g. Ankit): ").strip() or username
    password = input("Enter Owner Password: ").strip()
    if len(password) < 6:
        print("Error: Password should be at least 6 characters.")
        return

    user_id = db.generate_id("Users")
    auth_id = db.generate_id("AuthUsers")
    now_iso = datetime.utcnow().isoformat()

    # 1. Append Users record
    user_record = {
        "user_id": user_id,
        "full_name": full_name,
        "role": "OWNER",
        "mobile": "",
        "email": "",
        "active": "true",
        "created_at": now_iso,
        "notes": "Initial Owner account created via bootstrap utility",
    }
    db.append_record("Users", user_record)

    # 2. Append AuthUsers record
    hashed_pw = hash_password(password)
    auth_record = {
        "auth_id": auth_id,
        "user_id": user_id,
        "username": username,
        "password_hash": hashed_pw,
        "role": "OWNER",
        "active": "true",
        "created_at": now_iso,
        "must_change_password": "false",
    }
    db.append_record("AuthUsers", auth_record)

    print(f"\n[SUCCESS] Successfully created Owner account!")
    print(f"  User ID:   {user_id}")
    print(f"  Username:  {username}")
    print(f"  Full Name: {full_name}")
    print(f"  Role:      OWNER")
    print(f"  Auth ID:   {auth_id}")
    print("\nYou can now sign in through the React frontend using these credentials.")

if __name__ == "__main__":
    bootstrap_owner()
