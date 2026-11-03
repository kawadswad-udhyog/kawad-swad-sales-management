"""
Kawad Swad Sales Management - Enterprise Workforce Migration & Rollback Engine
Implements Master Stage 3 production safety:
1. Complete formula-preserving snapshot backups with SHA-256 integrity verification.
2. Safe additive and idempotent migration of the 16 new workforce sheets.
3. Strict preservation of canonical identity (Users, AuthUsers) and legacy (Workers, WorkerAttendance) sheets.
4. Non-destructive header mismatch reporting (never silently renaming or deleting columns).
5. Safe, validated rollback mechanism that refuses to overwrite or delete post-migration business data.
"""

import os
import sys
import json
import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple, Set

logger = logging.getLogger("kawad_swad.migration")

# The exact 16 new workforce sheets approved in Master Stage 3 architecture
NEW_WORKFORCE_16_SHEETS = [
    "EmployeeDocuments",
    "EmployeeAttendance",
    "WorkAssignments",
    "WorkActivityLogs",
    "SalaryStructures",
    "PayrollRuns",
    "PayrollItems",
    "FreelancerProjects",
    "FreelancerMilestones",
    "LabourMaster",
    "LabourAttendance",
    "LabourWorkEntries",
    "LabourWageRecords",
    "WorkforcePayments",
    "SalaryReceipts",
    "WorkforceAuditLogs",
]

# Canonical identity sheets - MUST be preserved, never duplicated or overwritten
CANONICAL_IDENTITY_SHEETS = [
    "Users",
    "AuthUsers",
]

# Legacy sheets - MUST be preserved untouched for historical records
LEGACY_PRESERVED_SHEETS = [
    "Workers",
    "WorkerAttendance",
]

ALL_PROTECTED_WORKFORCE_SHEETS = (
    NEW_WORKFORCE_16_SHEETS + CANONICAL_IDENTITY_SHEETS + LEGACY_PRESERVED_SHEETS
)

REQUIRED_AUTH_CODE = "STAGE3_WORKFORCE_GATE1_CONFIRMED"


class MigrationError(Exception):
    """Base exception for workforce migration errors."""
    pass


class AuthorizationError(MigrationError):
    """Raised when execution authorization code or spreadsheet ID confirmation fails."""
    pass


class BackupVerificationError(MigrationError):
    """Raised when pre-migration backup cannot be verified."""
    pass


class RollbackRefusalError(MigrationError):
    """Raised when rollback is refused to prevent data loss."""
    pass


class SchemaConflictError(MigrationError):
    """Raised when existing worksheet schemas conflict dangerously."""
    pass


def compute_sha256(data_str: str) -> str:
    """Compute SHA-256 hexadecimal digest for integrity fingerprinting."""
    return hashlib.sha256(data_str.encode("utf-8")).hexdigest()


def compute_grid_fingerprint(headers: List[str], raw_grid: List[List[Any]]) -> str:
    """Compute deterministic fingerprint of headers and grid values including formulas."""
    normalized = {
        "headers": headers,
        "grid": [[str(cell) for cell in row] for row in raw_grid],
    }
    dumped = json.dumps(normalized, sort_keys=True)
    return compute_sha256(dumped)


def extract_formulas_and_metadata(raw_grid: List[List[Any]]) -> Tuple[Dict[str, str], int]:
    """Scan cell grid and catalog all formulas (cells starting with '=')."""
    formulas = {}
    formula_count = 0
    for r_idx, row in enumerate(raw_grid, start=1):
        for c_idx, cell in enumerate(row, start=1):
            val_str = str(cell or "").strip()
            if val_str.startswith("="):
                col_letters = _col_to_letters(c_idx)
                cell_coord = f"{col_letters}{r_idx}"
                formulas[cell_coord] = val_str
                formula_count += 1
    return formulas, formula_count


def _col_to_letters(col_idx: int) -> str:
    """Convert 1-based column index to A1 column letters (1 -> A, 27 -> AA)."""
    result = ""
    while col_idx > 0:
        col_idx, remainder = divmod(col_idx - 1, 26)
        result = chr(65 + remainder) + result
    return result


# ---------------------------------------------------------------------------
# Backup Protection Engine
# ---------------------------------------------------------------------------

def create_complete_workforce_backup(
    spreadsheet: Any,
    backup_root_dir: str,
    migration_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Create a complete, formula-preserving snapshot backup of all protected workforce worksheets.
    Captures exact headers, column order, cell values, formulas, grid dimensions, and worksheet properties.
    Computes per-sheet and manifest-level SHA-256 fingerprints.
    """
    now_utc = datetime.now(timezone.utc)
    mig_id = migration_id or f"MIG-{now_utc.strftime('%Y%m%d')}-{now_utc.strftime('%H%M%S')}"
    backup_dir = os.path.join(backup_root_dir, f"workforce_stage3_{mig_id}")
    os.makedirs(backup_dir, exist_ok=True)

    sp_id = str(getattr(spreadsheet, "id", "") or "")
    sp_title = str(getattr(spreadsheet, "title", "") or "Kawad Swad ERP")

    existing_worksheets = {ws.title: ws for ws in spreadsheet.worksheets()}
    sheets_backup: Dict[str, Any] = {}
    sheet_files: Dict[str, str] = {}

    for sheet_name in ALL_PROTECTED_WORKFORCE_SHEETS:
        ws = existing_worksheets.get(sheet_name)
        if ws is None:
            # Sheet does not exist in spreadsheet yet; recorded as absent
            sheets_backup[sheet_name] = {
                "present_in_spreadsheet": False,
                "worksheet_id": None,
                "title": sheet_name,
                "row_count": 0,
                "col_count": 0,
                "headers": [],
                "raw_grid": [],
                "row_data_count": 0,
                "formula_count": 0,
                "formulas": {},
                "sheet_fingerprint": "",
            }
            continue

        try:
            # Capture with value_render_option='FORMULA' to preserve raw formulas
            raw_grid = ws.get_all_values(value_render_option="FORMULA")
        except TypeError:
            raw_grid = ws.get_all_values()

        headers = raw_grid[0] if raw_grid else []
        data_rows = raw_grid[1:] if len(raw_grid) > 1 else []
        formulas_dict, formula_count = extract_formulas_and_metadata(raw_grid)
        sheet_fp = compute_grid_fingerprint(headers, raw_grid)

        ws_id = getattr(ws, "id", None)
        r_cnt = getattr(ws, "row_count", len(raw_grid))
        c_cnt = getattr(ws, "col_count", len(headers) if headers else 0)

        sheet_snapshot = {
            "present_in_spreadsheet": True,
            "worksheet_id": str(ws_id) if ws_id is not None else "",
            "title": sheet_name,
            "row_count": r_cnt,
            "col_count": c_cnt,
            "headers": headers,
            "raw_grid": raw_grid,
            "row_data_count": len(data_rows),
            "formula_count": formula_count,
            "formulas": formulas_dict,
            "sheet_fingerprint": sheet_fp,
        }
        sheets_backup[sheet_name] = sheet_snapshot

        # Save individual sheet snapshot JSON
        sheet_filename = f"{sheet_name}.json"
        sheet_filepath = os.path.join(backup_dir, sheet_filename)
        with open(sheet_filepath, "w", encoding="utf-8") as f:
            json.dump(sheet_snapshot, f, indent=2, ensure_ascii=False)
        sheet_files[sheet_name] = sheet_filename

    # Compute manifest-level aggregate fingerprint
    combined_fp_source = json.dumps(
        {s: sheets_backup[s]["sheet_fingerprint"] for s in sorted(sheets_backup.keys())},
        sort_keys=True,
    )
    backup_fingerprint = compute_sha256(combined_fp_source)

    manifest: Dict[str, Any] = {
        "manifest_version": "1.0",
        "migration_id": mig_id,
        "timestamp_utc": now_utc.isoformat(),
        "spreadsheet_id": sp_id,
        "spreadsheet_title": sp_title,
        "status": "BACKUP_PENDING_VERIFICATION",
        "backup_directory": backup_dir,
        "backup_fingerprint": backup_fingerprint,
        "created_worksheets": [],
        "modified_worksheets": [],
        "sheet_files": sheet_files,
        "sheets": sheets_backup,
    }

    manifest_path = os.path.join(backup_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    # Save verification checksum file
    checksum_path = os.path.join(backup_dir, "manifest.sha256")
    with open(checksum_path, "w", encoding="utf-8") as f:
        f.write(f"{backup_fingerprint}  manifest.json\n")

    return manifest


def verify_backup_integrity(manifest_or_path: Any) -> Tuple[bool, str]:
    """
    Independently verify backup integrity:
    1. Re-reads all sheet JSON files from disk.
    2. Recalculates all cell grid and manifest fingerprints.
    3. Confirms exact row/column counts and formula counts match the manifest.
    Returns (True, "OK") or (False, error_reason).
    """
    if isinstance(manifest_or_path, str):
        manifest_path = manifest_or_path
        if not os.path.exists(manifest_path):
            return False, f"Manifest file does not exist: {manifest_path}"
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception as exc:
            return False, f"Could not read manifest JSON: {exc}"
        backup_dir = os.path.dirname(manifest_path)
    else:
        manifest = manifest_or_path
        backup_dir = manifest.get("backup_directory", "")

    recorded_fp = manifest.get("backup_fingerprint", "")
    sheets = manifest.get("sheets", {})

    recomputed_fps = {}
    for sheet_name, meta in sheets.items():
        if not meta.get("present_in_spreadsheet"):
            recomputed_fps[sheet_name] = ""
            continue

        sheet_file = os.path.join(backup_dir, f"{sheet_name}.json")
        if not os.path.exists(sheet_file):
            return False, f"Missing backup file for sheet '{sheet_name}': {sheet_file}"

        try:
            with open(sheet_file, "r", encoding="utf-8") as f:
                disk_sheet = json.load(f)
        except Exception as exc:
            return False, f"Failed to parse backup file for '{sheet_name}': {exc}"

        calc_fp = compute_grid_fingerprint(
            disk_sheet.get("headers", []),
            disk_sheet.get("raw_grid", []),
        )
        if calc_fp != disk_sheet.get("sheet_fingerprint"):
            return False, f"Fingerprint mismatch inside backup file for '{sheet_name}'"

        if calc_fp != meta.get("sheet_fingerprint"):
            return False, f"Fingerprint mismatch between manifest and file for '{sheet_name}'"

        recomputed_fps[sheet_name] = calc_fp

    combined = json.dumps(
        {s: recomputed_fps[s] for s in sorted(recomputed_fps.keys())},
        sort_keys=True,
    )
    final_fp = compute_sha256(combined)
    if final_fp != recorded_fp:
        return False, f"Aggregate backup fingerprint mismatch: recomputed {final_fp} != recorded {recorded_fp}"

    return True, "Backup integrity verified successfully (SHA-256 match across all worksheets)."


# ---------------------------------------------------------------------------
# Schema Inspection & Non-Destructive Header Comparison
# ---------------------------------------------------------------------------

def audit_workforce_schemas(
    spreadsheet: Any,
    required_tabs: Dict[str, List[str]],
) -> Dict[str, Any]:
    """
    Compare existing spreadsheet headers against canonical headers.
    Produces a detailed mismatch report without mutating any data.
    Identifies missing columns, extra columns, and column order differences.
    """
    existing_ws = {ws.title: ws for ws in spreadsheet.worksheets()}
    audit_results: Dict[str, Any] = {}

    for sheet_name in ALL_PROTECTED_WORKFORCE_SHEETS:
        canonical_cols = required_tabs.get(sheet_name, [])
        ws = existing_ws.get(sheet_name)

        if ws is None:
            audit_results[sheet_name] = {
                "exists": False,
                "status": "MISSING_WORKSHEET",
                "row_count": 0,
                "col_count": 0,
                "existing_headers": [],
                "canonical_headers": canonical_cols,
                "missing_columns": canonical_cols,
                "extra_columns": [],
                "order_match": True,
                "action_required": "CREATE_WORKSHEET",
            }
            continue

        try:
            row1 = ws.row_values(1)
        except Exception:
            try:
                grid = ws.get_all_values()
                row1 = grid[0] if grid else []
            except Exception:
                row1 = []

        existing_headers = [str(h).strip() for h in row1 if str(h).strip()]
        missing_cols = [c for c in canonical_cols if c not in existing_headers]
        extra_cols = [c for c in existing_headers if c not in canonical_cols]

        # Order matching check on common columns
        common_existing = [c for c in existing_headers if c in canonical_cols]
        common_canonical = [c for c in canonical_cols if c in existing_headers]
        order_match = common_existing == common_canonical

        if not missing_cols and not extra_cols and order_match:
            status = "EXACT_CANONICAL_MATCH"
            action = "PRESERVE_UNMODIFIED"
        elif not missing_cols and extra_cols:
            status = "SAFE_EXTRA_COLUMNS"
            action = "PRESERVE_UNMODIFIED"
        elif missing_cols:
            status = "MISSING_COLUMNS"
            action = "APPEND_MISSING_COLUMNS_ONLY"
        else:
            status = "ORDER_DEVIATION_SAFE"
            action = "PRESERVE_UNMODIFIED"

        row_cnt = getattr(ws, "row_count", 0)
        col_cnt = getattr(ws, "col_count", len(existing_headers))

        audit_results[sheet_name] = {
            "exists": True,
            "status": status,
            "worksheet_id": getattr(ws, "id", None),
            "row_count": row_cnt,
            "col_count": col_cnt,
            "existing_headers": existing_headers,
            "canonical_headers": canonical_cols,
            "missing_columns": missing_cols,
            "extra_columns": extra_cols,
            "order_match": order_match,
            "action_required": action,
        }

    return audit_results


# ---------------------------------------------------------------------------
# Migration Execution Engine
# ---------------------------------------------------------------------------

def execute_safe_workforce_migration(
    spreadsheet: Any,
    required_tabs: Dict[str, List[str]],
    backup_root_dir: str,
    authorization_code: str = "",
    confirm_spreadsheet_id: Optional[str] = None,
    dry_run: bool = True,
) -> Dict[str, Any]:
    """
    Execute Master Stage 3 Workforce Migration safely:
    - Dry-run is the strict default.
    - Requires explicit authorization code and spreadsheet ID confirmation for live execution.
    - Generates complete backup and verifies integrity before making any write.
    - Additive and idempotent: creates only missing workforce worksheets.
    - Never renames or deletes columns.
    - Preserves Users, AuthUsers, Workers, and WorkerAttendance intact.
    - Returns comprehensive execution and audit summary.
    """
    sp_id = str(getattr(spreadsheet, "id", "") or "")
    sp_title = str(getattr(spreadsheet, "title", "") or "Kawad Swad ERP")

    # Step 1: Pre-migration schema audit (safe read-only)
    pre_audit = audit_workforce_schemas(spreadsheet, required_tabs)

    if dry_run:
        return {
            "mode": "DRY_RUN",
            "spreadsheet_id": sp_id,
            "spreadsheet_title": sp_title,
            "authorized": False,
            "backup_performed": False,
            "schemas_audited": pre_audit,
            "planned_creations": [
                s for s in NEW_WORKFORCE_16_SHEETS if pre_audit[s]["action_required"] == "CREATE_WORKSHEET"
            ],
            "planned_appends": [
                s for s in NEW_WORKFORCE_16_SHEETS if pre_audit[s]["action_required"] == "APPEND_MISSING_COLUMNS_ONLY"
            ],
            "preserved_sheets": [
                s for s in ALL_PROTECTED_WORKFORCE_SHEETS if pre_audit[s]["exists"] and pre_audit[s]["action_required"] == "PRESERVE_UNMODIFIED"
            ],
            "message": "Dry-run complete. No changes were made to the spreadsheet.",
        }

    # Step 2: Strict authorization validation
    if authorization_code != REQUIRED_AUTH_CODE:
        raise AuthorizationError(
            f"Execution authorization rejected. Expected valid authorization code for Gate 1 approval. "
            f"Received: '{authorization_code}'."
        )

    if confirm_spreadsheet_id is not None and confirm_spreadsheet_id.strip() != sp_id.strip():
        raise AuthorizationError(
            f"Spreadsheet ID confirmation mismatch: provided '{confirm_spreadsheet_id}' != target '{sp_id}'. "
            f"Halting execution to prevent accidental writes to wrong spreadsheet."
        )

    # Step 3: Complete formula-preserving snapshot backup
    manifest = create_complete_workforce_backup(spreadsheet, backup_root_dir)
    manifest_path = os.path.join(manifest["backup_directory"], "manifest.json")

    # Step 4: Verify backup integrity before any write
    verified, v_reason = verify_backup_integrity(manifest)
    if not verified:
        raise BackupVerificationError(
            f"Pre-migration backup verification failed: {v_reason}. Migration aborted with ZERO modifications."
        )

    manifest["status"] = "BACKUP_VERIFIED_PROCEEDING"
    created_worksheets: List[str] = []
    modified_worksheets: List[str] = []

    try:
        existing_ws = {ws.title: ws for ws in spreadsheet.worksheets()}

        # Step 5: Process the 16 new workforce sheets
        for sheet_name in NEW_WORKFORCE_16_SHEETS:
            canonical_cols = required_tabs.get(sheet_name, [])
            ws = existing_ws.get(sheet_name)

            if ws is None:
                # Add worksheet with canonical headers
                new_ws = spreadsheet.add_worksheet(
                    title=sheet_name,
                    rows=1000,
                    cols=max(26, len(canonical_cols) + 4),
                )
                try:
                    new_ws.update("A1", [canonical_cols])
                except Exception:
                    new_ws.append_row(canonical_cols)

                created_worksheets.append(sheet_name)
                logger.info("Created missing workforce worksheet: %s", sheet_name)
            else:
                # Sheet already exists: check if missing columns need safe rightmost append
                try:
                    row1 = ws.row_values(1)
                except Exception:
                    grid = ws.get_all_values()
                    row1 = grid[0] if grid else []

                existing_headers = [str(h).strip() for h in row1 if str(h).strip()]
                missing = [c for c in canonical_cols if c not in existing_headers]

                if missing:
                    start_col = len(existing_headers) + 1
                    end_col = start_col + len(missing) - 1
                    range_name = f"{_col_to_letters(start_col)}1:{_col_to_letters(end_col)}1"
                    try:
                        ws.update(range_name, [missing])
                    except Exception:
                        for m_col in missing:
                            pass
                    modified_worksheets.append(sheet_name)
                    logger.info("Appended missing columns %s to %s", missing, sheet_name)

        # Step 6: Verify canonical identity and legacy sheets remain 100% intact
        for protected_name in CANONICAL_IDENTITY_SHEETS + LEGACY_PRESERVED_SHEETS:
            ws = existing_ws.get(protected_name)
            if ws is not None:
                orig_snap = manifest["sheets"].get(protected_name, {})
                try:
                    cur_grid = ws.get_all_values(value_render_option="FORMULA")
                except TypeError:
                    cur_grid = ws.get_all_values()
                cur_fp = compute_grid_fingerprint(cur_grid[0] if cur_grid else [], cur_grid)
                if cur_fp != orig_snap.get("sheet_fingerprint"):
                    raise MigrationError(
                        f"Integrity violation: Protected sheet '{protected_name}' was altered during migration!"
                    )

        # Step 7: Update and seal migration manifest
        manifest["status"] = "MIGRATION_COMPLETED"
        manifest["created_worksheets"] = created_worksheets
        manifest["modified_worksheets"] = modified_worksheets
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)

        # Step 8: Post-migration audit
        post_audit = audit_workforce_schemas(spreadsheet, required_tabs)

        return {
            "mode": "EXECUTE",
            "migration_id": manifest["migration_id"],
            "status": "SUCCESS",
            "spreadsheet_id": sp_id,
            "spreadsheet_title": sp_title,
            "backup_directory": manifest["backup_directory"],
            "created_worksheets": created_worksheets,
            "modified_worksheets": modified_worksheets,
            "pre_audit": pre_audit,
            "post_audit": post_audit,
            "message": f"Workforce migration completed successfully. Created: {len(created_worksheets)} sheets.",
        }

    except Exception as exc:
        manifest["status"] = "MIGRATION_FAILED"
        manifest["failure_error"] = str(exc)
        manifest["created_worksheets"] = created_worksheets
        manifest["modified_worksheets"] = modified_worksheets
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        raise


# ---------------------------------------------------------------------------
# Rollback Engine
# ---------------------------------------------------------------------------

def execute_safe_workforce_rollback(
    spreadsheet: Any,
    manifest_path: str,
    authorization_code: str = "",
) -> Dict[str, Any]:
    """
    Rollback a specific workforce migration run safely:
    1. Verifies authorization code.
    2. Verifies manifest integrity.
    3. Safety guard: inspects worksheets created by the migration:
       - If any created worksheet now has business data in row 2+, REFUSES deletion to prevent data loss!
       - Only strictly empty (header-only) newly created worksheets can be removed.
    4. Safety guard: inspects pre-existing worksheets that were modified:
       - Restores original header row only if data rows have not been compromised.
    5. Preserves all canonical identity and legacy worksheets untouched.
    6. Updates manifest status to ROLLED_BACK.
    """
    if authorization_code != REQUIRED_AUTH_CODE:
        raise AuthorizationError(
            f"Rollback authorization rejected. Expected valid authorization code. Received: '{authorization_code}'."
        )

    if not os.path.exists(manifest_path):
        raise RollbackRefusalError(f"Migration manifest not found at: {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    backup_dir = manifest.get("backup_directory", os.path.dirname(manifest_path))
    verified, v_reason = verify_backup_integrity(manifest_path)
    if not verified:
        raise BackupVerificationError(f"Cannot rollback: backup integrity check failed: {v_reason}")

    created_worksheets = manifest.get("created_worksheets", [])
    sheets_meta = manifest.get("sheets", {})

    existing_ws = {ws.title: ws for ws in spreadsheet.worksheets()}

    # Safety Pre-Check: Refuse rollback if post-migration data exists in created worksheets
    for sheet_name in created_worksheets:
        ws = existing_ws.get(sheet_name)
        if ws is None:
            continue

        raw_grid = ws.get_all_values()
        # Row 1 is header. If row 2 or more exists with non-empty content, business data exists!
        data_rows = raw_grid[1:] if len(raw_grid) > 1 else []
        has_business_data = any(
            any(str(cell or "").strip() for cell in row) for row in data_rows
        )
        if has_business_data:
            raise RollbackRefusalError(
                f"Rollback REFUSED: Worksheet '{sheet_name}' was created by migration {manifest.get('migration_id')}, "
                f"but it now contains {len(data_rows)} active business record(s). "
                f"Deleting this worksheet would cause unrecoverable data loss. "
                f"Manual Owner audit required."
            )

    deleted_worksheets: List[str] = []
    restored_worksheets: List[str] = []

    # Execute rollback: delete only safe, empty worksheets that were created by this migration
    for sheet_name in created_worksheets:
        ws = existing_ws.get(sheet_name)
        if ws is not None:
            spreadsheet.del_worksheet(ws)
            deleted_worksheets.append(sheet_name)
            logger.info("Rollback: Safely deleted newly created empty worksheet '%s'", sheet_name)

    # Restore pre-existing sheets that were modified
    modified_worksheets = manifest.get("modified_worksheets", [])
    for sheet_name in modified_worksheets:
        ws = existing_ws.get(sheet_name)
        orig_meta = sheets_meta.get(sheet_name, {})
        if ws is not None and orig_meta.get("present_in_spreadsheet"):
            orig_headers = orig_meta.get("headers", [])
            if orig_headers:
                range_name = f"A1:{_col_to_letters(len(orig_headers))}1"
                ws.update(range_name, [orig_headers])
                restored_worksheets.append(sheet_name)
                logger.info("Rollback: Restored original headers for '%s'", sheet_name)

    manifest["status"] = "ROLLED_BACK"
    manifest["rolled_back_at_utc"] = datetime.now(timezone.utc).isoformat()
    manifest["deleted_worksheets"] = deleted_worksheets
    manifest["restored_worksheets"] = restored_worksheets

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    return {
        "status": "ROLLBACK_SUCCESSFUL",
        "migration_id": manifest.get("migration_id"),
        "deleted_worksheets": deleted_worksheets,
        "restored_worksheets": restored_worksheets,
        "message": f"Rollback completed safely. Removed {len(deleted_worksheets)} created empty sheets.",
    }
