#!/usr/bin/env python3
"""
Kawad Swad ERP - User System Reconciliation Auditor
Independent, read-only analysis of 'Users' and 'AuthUsers' sheets.
Detects:
- Mismatched employee counts
- Orphaned profiles (Users without AuthUsers)
- Orphaned authentication accounts (AuthUsers without Users)
- Duplicate user IDs or usernames
- Role divergence between profile and login account
- Status divergence (active/inactive desynchronization)
- Insecure or empty password hashes

Usage:
  python3 backend/scripts/audit_users.py
"""

import os
import sys
import json
from datetime import datetime

# Add backend directory to sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.sheets import db
from app.user_service import audit_user_reconciliation


def main():
    print("=" * 70)
    print("KAWAD SWAD ERP: USER SYSTEM RECONCILIATION AUDIT (READ-ONLY)")
    print("Authoritative Store: Google Sheets ('Users' and 'AuthUsers')")
    print("=" * 70)

    try:
        report = audit_user_reconciliation()
    except Exception as exc:
        print(f"\n[ERROR] Failed to read Google Sheets: {exc}")
        sys.exit(1)

    print(f"\nAudit Timestamp: {report['timestamp']}")
    print(f"Total 'Users' Records:     {report['total_users_count']}")
    print(f"Total 'AuthUsers' Records: {report['total_auth_users_count']}")
    print(f"System Health Status:      {'ALL RECORDS SYNCHRONIZED (HEALTHY)' if report['healthy'] else 'DISCREPANCIES DETECTED'}")
    print(f"Total Discrepancies Found: {report['total_issues_count']}\n")

    if report["healthy"]:
        print("✓ All employee profiles in 'Users' match exactly with their login credentials in 'AuthUsers'.")
        print("✓ No orphaned accounts, duplicate IDs, role divergences, or status mismatches found.")
        print("=" * 70)
        return

    # 1. Orphaned Profiles
    if report["orphaned_profiles"]:
        print(f"\n--- [1] ORPHANED PROFILES IN 'Users' ({len(report['orphaned_profiles'])}) ---")
        print("Profiles present in 'Users' that have NO corresponding login credentials in 'AuthUsers':")
        for op in report["orphaned_profiles"]:
            print(f"  • User ID: {op.get('user_id')} | Name: {op.get('full_name')} | Username: {op.get('username')} | Role: {op.get('role')} | Active: {op.get('active')}")

    # 2. Orphaned Auth Accounts
    if report["orphaned_auth_accounts"]:
        print(f"\n--- [2] ORPHANED CREDENTIALS IN 'AuthUsers' ({len(report['orphaned_auth_accounts'])}) ---")
        print("Login accounts present in 'AuthUsers' that have NO matching profile in 'Users':")
        for oa in report["orphaned_auth_accounts"]:
            print(f"  • User ID: {oa.get('user_id')} | Username: {oa.get('username')} | Role: {oa.get('role')} | Active: {oa.get('active')}")

    # 3. Role Mismatches
    if report["role_mismatches"]:
        print(f"\n--- [3] ROLE MISMATCHES ({len(report['role_mismatches'])}) ---")
        print("Employees where Users.role differs from AuthUsers.role:")
        for rm in report["role_mismatches"]:
            print(f"  • User ID: {rm.get('user_id')} | Username: {rm.get('username')} | Users Role: '{rm.get('users_role')}' vs AuthUsers Role: '{rm.get('auth_role')}'")

    # 4. Status Mismatches
    if report["status_mismatches"]:
        print(f"\n--- [4] ACTIVE/INACTIVE STATUS MISMATCHES ({len(report['status_mismatches'])}) ---")
        print("Employees where Users.active differs from AuthUsers.active:")
        for sm in report["status_mismatches"]:
            print(f"  • User ID: {sm.get('user_id')} | Username: {sm.get('username')} | Users Active: {sm.get('users_active')} vs AuthUsers Active: {sm.get('auth_active')}")

    # 5. Duplicate User IDs / Usernames
    if report["duplicate_users"] or report["duplicate_auth_users"] or report["duplicate_usernames"]:
        print(f"\n--- [5] DUPLICATE RECORDS ---")
        for du in report["duplicate_users"]:
            print(f"  • Duplicate user_id in Users: {du.get('user_id')} (Count: {du.get('count')})")
        for da in report["duplicate_auth_users"]:
            print(f"  • Duplicate user_id in AuthUsers: {da.get('user_id')} (Count: {da.get('count')})")
        for dn in report["duplicate_usernames"]:
            print(f"  • Duplicate username in AuthUsers: '{dn.get('username')}' across user IDs {dn.get('user_ids')}")

    # 6. Insecure Credentials
    if report["insecure_credentials"]:
        print(f"\n--- [6] INSECURE CREDENTIALS ({len(report['insecure_credentials'])}) ---")
        for ic in report["insecure_credentials"]:
            print(f"  • User ID: {ic.get('user_id')} | Username: {ic.get('username')} | Issue: {ic.get('issue')}")

    print("\n" + "=" * 70)
    print("RECOMMENDATION: Use this report to remediate specific mismatched rows in Google Sheets.")
    print("=" * 70)


if __name__ == "__main__":
    main()
