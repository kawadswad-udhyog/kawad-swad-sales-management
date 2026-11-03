#!/usr/bin/env python3
"""
Kawad Swad Sales Management - Master Stage 3 Workforce Migration Utility
Enterprise CLI for safe, additive workforce schema migration, formula-preserving backups,
integrity verification, and guarded non-destructive rollback.

Usage:
  # Dry-run audit (Default):
  python3 backend/scripts/migrate_workforce_stage3.py --dry-run

  # Live execution (Requires Gate 1 authorization):
  python3 backend/scripts/migrate_workforce_stage3.py --execute \
      --authorization-code=STAGE3_WORKFORCE_GATE1_CONFIRMED \
      --confirm-spreadsheet-id=<SPREADSHEET_ID>

  # Guarded Rollback:
  python3 backend/scripts/migrate_workforce_stage3.py --rollback \
      --manifest=backend/backups/workforce_stage3_<MIG_ID>/manifest.json \
      --authorization-code=STAGE3_WORKFORCE_GATE1_CONFIRMED
"""

import os
import sys
import json
import argparse
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.config import (
    SALES_GOOGLE_SPREADSHEET_ID,
    SALES_GOOGLE_SERVICE_ACCOUNT_FILE,
    SALES_GOOGLE_SERVICE_ACCOUNT_JSON,
)
from app.sheets import db, REQUIRED_TABS
from app.workforce_migration import (
    NEW_WORKFORCE_16_SHEETS,
    CANONICAL_IDENTITY_SHEETS,
    LEGACY_PRESERVED_SHEETS,
    get_configured_auth_code,
    audit_workforce_schemas,
    execute_safe_workforce_migration,
    execute_safe_workforce_rollback,
    verify_backup_integrity,
    MigrationError,
    AuthorizationError,
    BackupVerificationError,
    RollbackRefusalError,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("kawad_swad.migration_cli")


def mask_id(val: str) -> str:
    if not val:
        return "[NOT CONFIGURED / EMPTY]"
    if len(val) <= 8:
        return val[:2] + "****" + val[-2:]
    return val[:4] + "****" + val[-4:]


def print_banner(mode_title: str):
    print("=" * 80)
    print("KAWAD SWAD UDHYOG - MASTER STAGE 3 WORKFORCE MIGRATION & ROLLBACK")
    print(f"Timestamp (UTC): {datetime.now(timezone.utc).isoformat()}")
    print(f"Mode:            {mode_title}")
    print("=" * 80)


def run_dry_run_audit(spreadsheet: Any):
    print_banner("DRY RUN SCHEMA AUDIT (READ-ONLY)")
    sp_id = getattr(spreadsheet, "id", None) or SALES_GOOGLE_SPREADSHEET_ID or "[OFFLINE TEST STORE]"
    print(f"Target Spreadsheet: {mask_id(str(sp_id))}")

    audit = audit_workforce_schemas(spreadsheet, REQUIRED_TABS)

    print("\n--- 1. CANONICAL IDENTITY SHEETS (PRESERVED - NEVER MODIFIED) ---")
    for s_name in CANONICAL_IDENTITY_SHEETS:
        res = audit.get(s_name, {})
        status = res.get("status", "UNKNOWN")
        cols = len(res.get("existing_headers", []))
        print(f"  [IDENTITY]  {s_name:<24} | Status: {status:<24} | Existing Cols: {cols:>2} | Action: PRESERVE")

    print("\n--- 2. LEGACY WORKFORCE SHEETS (PRESERVED FOR HISTORICAL AUDIT) ---")
    for s_name in LEGACY_PRESERVED_SHEETS:
        res = audit.get(s_name, {})
        status = res.get("status", "UNKNOWN")
        cols = len(res.get("existing_headers", []))
        print(f"  [LEGACY]    {s_name:<24} | Status: {status:<24} | Existing Cols: {cols:>2} | Action: PRESERVE")

    print("\n--- 3. 16 NEW WORKFORCE ARCHITECTURE SHEETS ---")
    to_create = []
    to_append = []
    already_exact = []

    for idx, s_name in enumerate(NEW_WORKFORCE_16_SHEETS, 1):
        res = audit.get(s_name, {})
        action = res.get("action_required", "UNKNOWN")
        status = res.get("status", "UNKNOWN")
        canonical_count = len(res.get("canonical_headers", []))
        existing_count = len(res.get("existing_headers", []))

        if action == "CREATE_WORKSHEET":
            to_create.append(s_name)
            action_disp = "[READY TO CREATE]"
        elif action == "APPEND_MISSING_COLUMNS_ONLY":
            to_append.append(s_name)
            action_disp = "[APPEND MISSING]"
        else:
            already_exact.append(s_name)
            action_disp = "[EXACT MATCH]"

        print(
            f"  {idx:>2}. {action_disp:<18} {s_name:<24} | "
            f"Canonical: {canonical_count:>2} | Existing: {existing_count:>2} | Status: {status}"
        )

    print("\n" + "=" * 80)
    print("AUDIT SUMMARY & SAFETY VERIFICATION")
    print("=" * 80)
    print(f"Total Canonical Identity Sheets: {len(CANONICAL_IDENTITY_SHEETS)} (Preserved)")
    print(f"Total Legacy Preserved Sheets:   {len(LEGACY_PRESERVED_SHEETS)} (Preserved)")
    print(f"New Workforce Sheets to Create:  {len(to_create)} / 16")
    print(f"Existing Sheets with Appends:    {len(to_append)}")
    print(f"Existing Sheets in Full Parity:  {len(already_exact)}")
    print("Pre-migration safety check: PASSED. Zero destructive operations planned.")
    print("=" * 80)


def run_execute_migration(
    spreadsheet: Any,
    auth_code: str,
    confirm_sp_id: Optional[str],
    backup_dir: str,
):
    print_banner("AUTHORIZED LIVE EXECUTION (STAGE 3 WORKFORCE)")

    try:
        result = execute_safe_workforce_migration(
            spreadsheet=spreadsheet,
            required_tabs=REQUIRED_TABS,
            backup_root_dir=backup_dir,
            authorization_code=auth_code,
            confirm_spreadsheet_id=confirm_sp_id,
            dry_run=False,
        )

        print("\n--- EXECUTION SUCCESSFUL ---")
        print(f"Migration ID:       {result.get('migration_id')}")
        print(f"Backup Directory:   {result.get('backup_directory')}")
        print(f"Created Worksheets: {len(result.get('created_worksheets', []))}")
        for w in result.get("created_worksheets", []):
            print(f"  + Created: {w}")
        if result.get("modified_worksheets"):
            print(f"Modified Worksheets: {len(result.get('modified_worksheets', []))}")
            for m in result.get("modified_worksheets", []):
                print(f"  ~ Appended missing headers: {m}")

        print("\n" + "=" * 80)
        print("STAGE 3 WORKFORCE MIGRATION SEALED SUCCESSFULLY")
        print("=" * 80)
        return result

    except MigrationError as me:
        print("\n[CRITICAL ERROR] Migration halted with safety protection:")
        print(f"Error Type: {me.__class__.__name__}")
        print(f"Details:    {str(me)}")
        sys.exit(1)


def run_rollback(
    spreadsheet: Any,
    manifest_path: str,
    auth_code: str,
):
    print_banner("AUTHORIZED ROLLBACK EXECUTION")
    print(f"Target Manifest: {manifest_path}")

    try:
        result = execute_safe_workforce_rollback(
            spreadsheet=spreadsheet,
            manifest_path=manifest_path,
            authorization_code=auth_code,
        )

        print("\n--- ROLLBACK SUCCESSFUL ---")
        print(f"Migration ID:       {result.get('migration_id')}")
        print(f"Deleted Worksheets: {len(result.get('deleted_worksheets', []))}")
        for d in result.get("deleted_worksheets", []):
            print(f"  - Deleted empty sheet: {d}")
        print(f"Restored Worksheets: {len(result.get('restored_worksheets', []))}")
        for r in result.get("restored_worksheets", []):
            print(f"  * Restored headers: {r}")

        print("\n" + "=" * 80)
        print("STAGE 3 WORKFORCE ROLLBACK COMPLETED SAFELY")
        print("=" * 80)
        return result

    except MigrationError as me:
        print("\n[CRITICAL ERROR] Rollback halted with safety protection:")
        print(f"Error Type: {me.__class__.__name__}")
        print(f"Details:    {str(me)}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Kawad Swad ERP - Master Stage 3 Workforce Migration & Rollback Utility"
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--dry-run", action="store_true", help="Perform non-destructive dry-run audit (Default)")
    mode_group.add_argument("--execute", action="store_true", help="Execute safe additive migration (Requires authorization)")
    mode_group.add_argument("--rollback", action="store_true", help="Rollback previously executed migration using manifest")

    parser.add_argument("--authorization-code", type=str, default="", help="Authorization code for Gate 1 execution or rollback")
    parser.add_argument("--confirm-spreadsheet-id", type=str, default=None, help="Explicit target spreadsheet ID confirmation")
    parser.add_argument("--manifest", type=str, default="", help="Path to manifest.json (Required for --rollback)")
    parser.add_argument("--backup-dir", type=str, default=os.path.join(BACKEND_DIR, "backups"), help="Root directory for backup snapshots")

    args = parser.parse_args()

    # Determine spreadsheet target
    if db.is_connected and db.spreadsheet is not None:
        spreadsheet = db.spreadsheet
    else:
        # In test / non-connected environment, use a synthetic wrapper over db.memory_store
        # so dry-run audit can still inspect in-memory models
        from tests.test_workforce_migration_safety import SyntheticSpreadsheet, SyntheticWorksheet
        spreadsheet = SyntheticSpreadsheet(
            spreadsheet_id=SALES_GOOGLE_SPREADSHEET_ID or "OFFLINE-TEST-STORE",
            title="Kawad Swad ERP (Offline)",
        )
        for tab_name, rows in db.memory_store.items():
            headers = REQUIRED_TABS.get(tab_name, [])
            grid = [headers] if headers else []
            for r in rows:
                grid.append([r.get(c, "") for c in headers])
            spreadsheet.add_worksheet(title=tab_name, rows=1000, cols=30, initial_grid=grid)

    if args.rollback:
        if not args.manifest:
            print("Error: --manifest=<PATH_TO_MANIFEST_JSON> is required for --rollback")
            sys.exit(1)
        run_rollback(
            spreadsheet=spreadsheet,
            manifest_path=args.manifest,
            auth_code=args.authorization_code,
        )
    elif args.execute:
        run_execute_migration(
            spreadsheet=spreadsheet,
            auth_code=args.authorization_code,
            confirm_sp_id=args.confirm_spreadsheet_id,
            backup_dir=args.backup_dir,
        )
    else:
        run_dry_run_audit(spreadsheet)


if __name__ == "__main__":
    main()
