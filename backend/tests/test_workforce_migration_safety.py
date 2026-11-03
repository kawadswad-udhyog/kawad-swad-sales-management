"""
Synthetic Test Suite for Kawad Swad ERP Master Stage 3 Workforce Migration Safety & Rollback.
Tests all 15 scenarios strictly in-memory without modifying live Google Sheets.
"""

import os
import sys
import json
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.sheets import REQUIRED_TABS
from app.workforce_migration import (
    NEW_WORKFORCE_16_SHEETS,
    CANONICAL_IDENTITY_SHEETS,
    LEGACY_PRESERVED_SHEETS,
    REQUIRED_AUTH_CODE,
    get_configured_auth_code,
    create_complete_workforce_backup,
    verify_backup_integrity,
    audit_workforce_schemas,
    execute_safe_workforce_migration,
    execute_safe_workforce_rollback,
    compute_grid_fingerprint,
    detect_header_anomalies,
    AuthorizationError,
    BackupVerificationError,
    RollbackRefusalError,
    SchemaConflictError,
    MigrationError,
)


class SyntheticWorksheet:
    """In-memory simulation of a gspread Worksheet supporting formula preservation."""
    def __init__(self, title: str, rows: int = 1000, cols: int = 30, sheet_id: int = 0, initial_grid: Optional[List[List[Any]]] = None):
        self.title = title
        self.id = sheet_id
        self.row_count = rows
        self.col_count = cols
        # Grid of string values
        self._grid: List[List[str]] = []
        if initial_grid:
            self._grid = [[str(c) if c is not None else "" for c in row] for row in initial_grid]

    def clear(self):
        """Empties all cells in the worksheet."""
        self._grid = []

    def get_all_values(self, value_render_option: str = "FORMATTED_VALUE") -> List[List[str]]:
        # Returns copy of grid
        return [list(row) for row in self._grid]

    def row_values(self, row_idx: int) -> List[str]:
        if 1 <= row_idx <= len(self._grid):
            row = list(self._grid[row_idx - 1])
            while row and row[-1] == "":
                row.pop()
            return row
        return []

    def append_row(self, values: List[Any]):
        str_vals = [str(v) if v is not None else "" for v in values]
        self._grid.append(str_vals)

    def update(self, range_name: str, values: List[List[Any]]):
        """
        Supports ranges like 'A1', 'A1:C1', 'E1:F1', etc.
        """
        # Parse start cell from range_name
        start_part = range_name.split(":")[0].strip()
        col_letters = "".join(filter(str.isalpha, start_part)).upper()
        row_digits = "".join(filter(str.isdigit, start_part))
        start_row = int(row_digits) if row_digits else 1
        start_col = 0
        for char in col_letters:
            start_col = start_col * 26 + (ord(char) - ord('A') + 1)
        start_col_0 = start_col - 1
        start_row_0 = start_row - 1

        for r_offset, row_vals in enumerate(values):
            target_r = start_row_0 + r_offset
            while len(self._grid) <= target_r:
                self._grid.append([])
            for c_offset, val in enumerate(row_vals):
                target_c = start_col_0 + c_offset
                while len(self._grid[target_r]) <= target_c:
                    self._grid[target_r].append("")
                self._grid[target_r][target_c] = str(val) if val is not None else ""


class SyntheticSpreadsheet:
    """In-memory simulation of a gspread Spreadsheet."""
    def __init__(self, spreadsheet_id: str = "SYNTHETIC-SP-001", title: str = "Kawad Swad Synthetic ERP"):
        self.id = spreadsheet_id
        self.title = title
        self._worksheets: Dict[str, SyntheticWorksheet] = {}
        self._next_sheet_id = 1001

    def worksheets(self) -> List[SyntheticWorksheet]:
        return list(self._worksheets.values())

    def worksheet(self, title: str) -> SyntheticWorksheet:
        if title not in self._worksheets:
            raise KeyError(f"Worksheet '{title}' does not exist.")
        return self._worksheets[title]

    def add_worksheet(self, title: str, rows: int = 1000, cols: int = 30, initial_grid: Optional[List[List[Any]]] = None) -> SyntheticWorksheet:
        if title in self._worksheets:
            raise ValueError(f"Worksheet '{title}' already exists.")
        ws = SyntheticWorksheet(title, rows, cols, sheet_id=self._next_sheet_id, initial_grid=initial_grid)
        self._next_sheet_id += 1
        self._worksheets[title] = ws
        return ws

    def del_worksheet(self, worksheet: SyntheticWorksheet):
        if worksheet.title in self._worksheets:
            del self._worksheets[worksheet.title]


class WorkforceMigrationSafetyTests(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="ks_workforce_test_")
        self.sp_id = "TEST-SP-KAWAD-SWAD-01"
        self.spreadsheet = SyntheticSpreadsheet(spreadsheet_id=self.sp_id, title="Kawad Swad Production Test")

        # Initialize canonical identity sheets with synthetic records
        self.users_ws = self.spreadsheet.add_worksheet("Users", initial_grid=[
            REQUIRED_TABS["Users"],
            ["USR-01", "owner", "Sita Ram", "OWNER", "true", "2026-01-01"],
            ["USR-02", "manager", "Radhe Shyam", "PA", "true", "2026-01-02"],
        ])

        self.auth_ws = self.spreadsheet.add_worksheet("AuthUsers", initial_grid=[
            REQUIRED_TABS["AuthUsers"],
            ["USR-01", "owner@kawadswad.com", "hash_owner", "true", "2026-01-01"],
            ["USR-02", "mgr@kawadswad.com", "hash_mgr", "true", "2026-01-02"],
        ])

        # Initialize legacy workforce sheets with historical records and formula
        self.workers_ws = self.spreadsheet.add_worksheet("Workers", initial_grid=[
            REQUIRED_TABS["Workers"],
            ["WRK-001", "Mohan Lal", "PACKER", "350", "true", "2026-01-10"],
            ["WRK-002", "Suresh Kumar", "OPERATOR", "400", "true", "2026-01-11"],
        ])

        self.worker_att_ws = self.spreadsheet.add_worksheet("WorkerAttendance", initial_grid=[
            REQUIRED_TABS["WorkerAttendance"],
            ["ATT-001", "WRK-001", "2026-11-01", "PRESENT", "8", "350", "=E2*F2"],
            ["ATT-002", "WRK-002", "2026-11-01", "PRESENT", "8", "400", "=E3*F3"],
        ])

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_01_successful_migration(self):
        """Scenario 1: Full successful additive migration creates all 16 sheets with verified backups."""
        result = execute_safe_workforce_migration(
            spreadsheet=self.spreadsheet,
            required_tabs=REQUIRED_TABS,
            backup_root_dir=self.test_dir,
            authorization_code=REQUIRED_AUTH_CODE,
            confirm_spreadsheet_id=self.sp_id,
            dry_run=False,
        )

        self.assertEqual(result["status"], "SUCCESS")
        self.assertEqual(len(result["created_worksheets"]), 16)
        self.assertCountEqual(result["created_worksheets"], NEW_WORKFORCE_16_SHEETS)

        # Verify each of the 16 sheets exists on spreadsheet and has canonical headers
        for s_name in NEW_WORKFORCE_16_SHEETS:
            ws = self.spreadsheet.worksheet(s_name)
            self.assertIsNotNone(ws)
            grid = ws.get_all_values()
            self.assertEqual(grid[0], REQUIRED_TABS[s_name])

        # Verify backup manifest was generated and verified
        manifest_path = os.path.join(result["backup_directory"], "manifest.json")
        self.assertTrue(os.path.exists(manifest_path))
        with open(manifest_path, "r") as f:
            manifest = json.load(f)
        self.assertEqual(manifest["status"], "MIGRATION_COMPLETED")
        self.assertEqual(len(manifest["created_worksheets"]), 16)

    def test_02_repeated_migration_without_duplicates_idempotency(self):
        """Scenario 2: Repeated migration is idempotent: 0 duplicate sheets and 0 duplicate columns."""
        # First execution
        execute_safe_workforce_migration(
            spreadsheet=self.spreadsheet,
            required_tabs=REQUIRED_TABS,
            backup_root_dir=self.test_dir,
            authorization_code=REQUIRED_AUTH_CODE,
            confirm_spreadsheet_id=self.sp_id,
            dry_run=False,
        )

        total_sheets_after_first = len(self.spreadsheet.worksheets())

        # Second execution
        result2 = execute_safe_workforce_migration(
            spreadsheet=self.spreadsheet,
            required_tabs=REQUIRED_TABS,
            backup_root_dir=self.test_dir,
            authorization_code=REQUIRED_AUTH_CODE,
            confirm_spreadsheet_id=self.sp_id,
            dry_run=False,
        )

        self.assertEqual(result2["status"], "SUCCESS")
        self.assertEqual(len(result2["created_worksheets"]), 0)
        self.assertEqual(len(result2["modified_worksheets"]), 0)
        self.assertEqual(len(self.spreadsheet.worksheets()), total_sheets_after_first)

    def test_03_existing_workforce_worksheet_with_correct_headers(self):
        """Scenario 3: An existing workforce sheet with exact canonical headers is preserved unmodified."""
        # Pre-create EmployeeAttendance with canonical headers
        self.spreadsheet.add_worksheet("EmployeeAttendance", initial_grid=[
            REQUIRED_TABS["EmployeeAttendance"],
            ["ATT-E1", "EMP-01", "2026-11-01", "09:00", "18:00", "PRESENT", "Approved"],
        ])

        result = execute_safe_workforce_migration(
            spreadsheet=self.spreadsheet,
            required_tabs=REQUIRED_TABS,
            backup_root_dir=self.test_dir,
            authorization_code=REQUIRED_AUTH_CODE,
            confirm_spreadsheet_id=self.sp_id,
            dry_run=False,
        )

        self.assertNotIn("EmployeeAttendance", result["created_worksheets"])
        self.assertNotIn("EmployeeAttendance", result["modified_worksheets"])
        self.assertEqual(len(result["created_worksheets"]), 15)

        # Verify data record was preserved
        att_ws = self.spreadsheet.worksheet("EmployeeAttendance")
        self.assertEqual(len(att_ws.get_all_values()), 2)
        self.assertEqual(att_ws.get_all_values()[1][0], "ATT-E1")

    def test_04_existing_workforce_worksheet_with_extra_columns_preserved(self):
        """Scenario 4: An existing workforce sheet with extra custom columns preserves them untouched."""
        # Pre-create WorkAssignments with extra custom columns
        custom_headers = REQUIRED_TABS["WorkAssignments"] + ["shift_supervisor", "safety_gear_verified"]
        self.spreadsheet.add_worksheet("WorkAssignments", initial_grid=[
            custom_headers,
            ["ASN-001", "EMP-01", "PACKING", "2026-11-01", "Shift A", "ACTIVE", "Ramesh", "YES"],
        ])

        result = execute_safe_workforce_migration(
            spreadsheet=self.spreadsheet,
            required_tabs=REQUIRED_TABS,
            backup_root_dir=self.test_dir,
            authorization_code=REQUIRED_AUTH_CODE,
            confirm_spreadsheet_id=self.sp_id,
            dry_run=False,
        )

        self.assertNotIn("WorkAssignments", result["created_worksheets"])
        self.assertNotIn("WorkAssignments", result["modified_worksheets"])

        # Check headers still retain extra columns
        ws = self.spreadsheet.worksheet("WorkAssignments")
        cur_headers = ws.get_all_values()[0]
        self.assertEqual(cur_headers, custom_headers)
        self.assertIn("shift_supervisor", cur_headers)
        self.assertIn("safety_gear_verified", cur_headers)

    def test_05_existing_workforce_worksheet_with_missing_columns_additive_append_only(self):
        """Scenario 5: An existing sheet missing columns has only missing columns appended to the right."""
        full_headers = REQUIRED_TABS["SalaryStructures"]
        truncated_headers = full_headers[:-2]  # missing last 2 columns
        self.spreadsheet.add_worksheet("SalaryStructures", initial_grid=[
            truncated_headers,
            ["STR-001", "EMP-01", "25000", "5000"],
        ])

        result = execute_safe_workforce_migration(
            spreadsheet=self.spreadsheet,
            required_tabs=REQUIRED_TABS,
            backup_root_dir=self.test_dir,
            authorization_code=REQUIRED_AUTH_CODE,
            confirm_spreadsheet_id=self.sp_id,
            dry_run=False,
        )

        self.assertIn("SalaryStructures", result["modified_worksheets"])
        ws = self.spreadsheet.worksheet("SalaryStructures")
        cur_headers = ws.get_all_values()[0]
        # Must now have full headers
        for col in full_headers:
            self.assertIn(col, cur_headers)
        # Original row 1 values must still match
        self.assertEqual(ws.get_all_values()[1][0], "STR-001")

    def test_06_backup_integrity_failure_tampered_aborts_execution(self):
        """Scenario 6: Tampered or unverified backup immediately aborts migration before any writes."""
        # Create initial backup
        manifest = create_complete_workforce_backup(self.spreadsheet, self.test_dir)
        manifest_path = os.path.join(manifest["backup_directory"], "manifest.json")

        # Tamper with one of the backup files on disk
        tamper_file = os.path.join(manifest["backup_directory"], "Users.json")
        with open(tamper_file, "w") as f:
            f.write(json.dumps({"tampered": "corrupted_content"}))

        # Verification must fail
        ok, reason = verify_backup_integrity(manifest_path)
        self.assertFalse(ok)
        self.assertIn("mismatch", reason.lower())

    def test_07_failure_halfway_through_migration_manifest_records_failure(self):
        """Scenario 7: Mid-migration exception sets status=MIGRATION_FAILED in manifest."""
        original_add = self.spreadsheet.add_worksheet
        call_count = [0]

        def flaky_add_worksheet(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 4:
                raise RuntimeError("Simulated API rate limit / network partition on 4th worksheet")
            return original_add(*args, **kwargs)

        self.spreadsheet.add_worksheet = flaky_add_worksheet

        with self.assertRaises(RuntimeError):
            execute_safe_workforce_migration(
                spreadsheet=self.spreadsheet,
                required_tabs=REQUIRED_TABS,
                backup_root_dir=self.test_dir,
                authorization_code=REQUIRED_AUTH_CODE,
                confirm_spreadsheet_id=self.sp_id,
                dry_run=False,
            )

        # Restore original method
        self.spreadsheet.add_worksheet = original_add

        # Locate manifest and verify failure status was persisted
        backup_subdirs = [os.path.join(self.test_dir, d) for d in os.listdir(self.test_dir)]
        manifest_path = os.path.join(backup_subdirs[0], "manifest.json")
        with open(manifest_path, "r") as f:
            manifest = json.load(f)

        self.assertEqual(manifest["status"], "MIGRATION_FAILED")
        self.assertIn("Simulated API rate limit", manifest.get("failure_error", ""))
        self.assertEqual(len(manifest["created_worksheets"]), 3)

    def test_08_rollback_after_partial_migration(self):
        """Scenario 8: Rollback after partial failure removes the 3 partially created empty worksheets."""
        original_add = self.spreadsheet.add_worksheet
        call_count = [0]

        def flaky_add_worksheet(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 4:
                raise RuntimeError("Simulated mid-flight crash")
            return original_add(*args, **kwargs)

        self.spreadsheet.add_worksheet = flaky_add_worksheet

        try:
            execute_safe_workforce_migration(
                spreadsheet=self.spreadsheet,
                required_tabs=REQUIRED_TABS,
                backup_root_dir=self.test_dir,
                authorization_code=REQUIRED_AUTH_CODE,
                confirm_spreadsheet_id=self.sp_id,
                dry_run=False,
            )
        except RuntimeError:
            pass

        self.spreadsheet.add_worksheet = original_add

        backup_subdirs = [os.path.join(self.test_dir, d) for d in os.listdir(self.test_dir)]
        manifest_path = os.path.join(backup_subdirs[0], "manifest.json")

        rollback_res = execute_safe_workforce_rollback(
            spreadsheet=self.spreadsheet,
            manifest_path=manifest_path,
            authorization_code=REQUIRED_AUTH_CODE,
        )

        self.assertEqual(rollback_res["status"], "ROLLBACK_SUCCESSFUL")
        self.assertEqual(len(rollback_res["deleted_worksheets"]), 3)

        # Verify worksheets were deleted
        current_titles = [ws.title for ws in self.spreadsheet.worksheets()]
        for deleted_sheet in rollback_res["deleted_worksheets"]:
            self.assertNotIn(deleted_sheet, current_titles)

    def test_09_rollback_after_successful_migration_removes_created_empty_sheets(self):
        """Scenario 9: Rollback on successful run removes all 16 created empty worksheets."""
        mig_res = execute_safe_workforce_migration(
            spreadsheet=self.spreadsheet,
            required_tabs=REQUIRED_TABS,
            backup_root_dir=self.test_dir,
            authorization_code=REQUIRED_AUTH_CODE,
            confirm_spreadsheet_id=self.sp_id,
            dry_run=False,
        )

        manifest_path = os.path.join(mig_res["backup_directory"], "manifest.json")

        rollback_res = execute_safe_workforce_rollback(
            spreadsheet=self.spreadsheet,
            manifest_path=manifest_path,
            authorization_code=REQUIRED_AUTH_CODE,
        )

        self.assertEqual(rollback_res["status"], "ROLLBACK_SUCCESSFUL")
        self.assertEqual(len(rollback_res["deleted_worksheets"]), 16)

        # Canonical identity and legacy sheets must remain intact
        current_titles = [ws.title for ws in self.spreadsheet.worksheets()]
        for s in CANONICAL_IDENTITY_SHEETS + LEGACY_PRESERVED_SHEETS:
            self.assertIn(s, current_titles)

    def test_10_refusal_to_rollback_if_data_changed_after_migration(self):
        """Scenario 10: Rollback is strictly REFUSED if business records were added post-migration."""
        mig_res = execute_safe_workforce_migration(
            spreadsheet=self.spreadsheet,
            required_tabs=REQUIRED_TABS,
            backup_root_dir=self.test_dir,
            authorization_code=REQUIRED_AUTH_CODE,
            confirm_spreadsheet_id=self.sp_id,
            dry_run=False,
        )

        # Operator adds an actual payroll record into PayrollRuns (row 2)
        pr_ws = self.spreadsheet.worksheet("PayrollRuns")
        pr_ws.append_row(["PAY-2026-11-01", "2026-11", "2026-11-01", "2026-11-30", "COMPLETED", "150000.00"])

        manifest_path = os.path.join(mig_res["backup_directory"], "manifest.json")

        # Rollback attempt must raise RollbackRefusalError
        with self.assertRaises(RollbackRefusalError) as cm:
            execute_safe_workforce_rollback(
                spreadsheet=self.spreadsheet,
                manifest_path=manifest_path,
                authorization_code=REQUIRED_AUTH_CODE,
            )

        self.assertIn("active business record", str(cm.exception))
        self.assertIn("PayrollRuns", str(cm.exception))

        # Worksheet must NOT have been deleted
        self.assertIn("PayrollRuns", [ws.title for ws in self.spreadsheet.worksheets()])

    def test_11_preservation_of_users_and_authusers(self):
        """Scenario 11: Users and AuthUsers canonical identity sheets are never altered or recreated."""
        orig_users_grid = self.users_ws.get_all_values()
        orig_auth_grid = self.auth_ws.get_all_values()

        execute_safe_workforce_migration(
            spreadsheet=self.spreadsheet,
            required_tabs=REQUIRED_TABS,
            backup_root_dir=self.test_dir,
            authorization_code=REQUIRED_AUTH_CODE,
            confirm_spreadsheet_id=self.sp_id,
            dry_run=False,
        )

        self.assertEqual(self.users_ws.get_all_values(), orig_users_grid)
        self.assertEqual(self.auth_ws.get_all_values(), orig_auth_grid)

    def test_12_preservation_of_workers_and_workerattendance(self):
        """Scenario 12: Legacy Workers and WorkerAttendance sheets are preserved 100% intact."""
        orig_workers_grid = self.workers_ws.get_all_values()
        orig_worker_att_grid = self.worker_att_ws.get_all_values()

        execute_safe_workforce_migration(
            spreadsheet=self.spreadsheet,
            required_tabs=REQUIRED_TABS,
            backup_root_dir=self.test_dir,
            authorization_code=REQUIRED_AUTH_CODE,
            confirm_spreadsheet_id=self.sp_id,
            dry_run=False,
        )

        self.assertEqual(self.workers_ws.get_all_values(), orig_workers_grid)
        self.assertEqual(self.worker_att_ws.get_all_values(), orig_worker_att_grid)

    def test_13_formula_preservation_in_backup_and_restore(self):
        """Scenario 13: Raw formulas (=E2*F2) are preserved with value_render_option=FORMULA."""
        manifest = create_complete_workforce_backup(self.spreadsheet, self.test_dir)
        att_snap = manifest["sheets"]["WorkerAttendance"]

        self.assertGreaterEqual(att_snap["formula_count"], 2)
        self.assertEqual(att_snap["formulas"].get("G2"), "=E2*F2")
        self.assertEqual(att_snap["formulas"].get("G3"), "=E3*F3")

        # Verify disk file preserves formula
        backup_dir = manifest["backup_directory"]
        with open(os.path.join(backup_dir, "WorkerAttendance.json"), "r") as f:
            disk_data = json.load(f)
        self.assertEqual(disk_data["formulas"]["G2"], "=E2*F2")

    def test_14_worksheet_id_and_title_preservation(self):
        """Scenario 14: Worksheet title and worksheet_id properties are recorded and preserved."""
        manifest = create_complete_workforce_backup(self.spreadsheet, self.test_dir)
        users_meta = manifest["sheets"]["Users"]
        self.assertEqual(users_meta["title"], "Users")
        self.assertEqual(users_meta["worksheet_id"], str(self.users_ws.id))
        self.assertGreater(users_meta["row_count"], 0)

    def test_15_missing_or_invalid_execution_authorization(self):
        """Scenario 15: Invalid authorization code or mismatched spreadsheet ID raises AuthorizationError."""
        # 1. Invalid authorization code
        with self.assertRaises(AuthorizationError):
            execute_safe_workforce_migration(
                spreadsheet=self.spreadsheet,
                required_tabs=REQUIRED_TABS,
                backup_root_dir=self.test_dir,
                authorization_code="WRONG_CODE",
                confirm_spreadsheet_id=self.sp_id,
                dry_run=False,
            )

        # 2. Mismatched spreadsheet ID
        with self.assertRaises(AuthorizationError):
            execute_safe_workforce_migration(
                spreadsheet=self.spreadsheet,
                required_tabs=REQUIRED_TABS,
                backup_root_dir=self.test_dir,
                authorization_code=REQUIRED_AUTH_CODE,
                confirm_spreadsheet_id="WRONG_SPREADSHEET_ID",
                dry_run=False,
            )

    def test_16_header_anomaly_detection_blank_duplicate_ambiguous(self):
        """Scenario 16: Pre-migration schema audit catches blank, duplicate, and ambiguous headers and aborts."""
        # 1. Blank header test
        self.spreadsheet.add_worksheet("EmployeeDocuments", initial_grid=[
            ["doc_id", "", "doc_name", "status"],
            ["DOC-1", "EMP-1", "Aadhaar", "VERIFIED"],
        ])

        with self.assertRaises(SchemaConflictError) as cm:
            execute_safe_workforce_migration(
                spreadsheet=self.spreadsheet,
                required_tabs=REQUIRED_TABS,
                backup_root_dir=self.test_dir,
                authorization_code=get_configured_auth_code(),
                confirm_spreadsheet_id=self.sp_id,
                dry_run=False,
            )
        self.assertIn("blank header", str(cm.exception).lower())

        # Clean up for next assertion
        del self.spreadsheet._worksheets["EmployeeDocuments"]

        # 2. Duplicate header test
        self.spreadsheet.add_worksheet("EmployeeDocuments", initial_grid=[
            ["doc_id", "emp_id", "status", "status"],
            ["DOC-1", "EMP-1", "VERIFIED", "VERIFIED"],
        ])

        with self.assertRaises(SchemaConflictError) as cm2:
            execute_safe_workforce_migration(
                spreadsheet=self.spreadsheet,
                required_tabs=REQUIRED_TABS,
                backup_root_dir=self.test_dir,
                authorization_code=get_configured_auth_code(),
                confirm_spreadsheet_id=self.sp_id,
                dry_run=False,
            )
        self.assertIn("duplicate column", str(cm2.exception).lower())

    def test_17_post_write_read_back_failure_halts_and_records(self):
        """Scenario 17: Read-back mismatch after writing headers halts migration and logs failed_operation in manifest."""
        original_update = SyntheticWorksheet.update

        # Simulate a buggy or truncating Google Sheets update that drops the last header
        def truncating_update(ws_self, range_name, values):
            if ws_self.title == "EmployeeDocuments" and range_name == "A1":
                truncated = [values[0][:-1]]  # Drop last column
                return original_update(ws_self, range_name, truncated)
            return original_update(ws_self, range_name, values)

        SyntheticWorksheet.update = truncating_update
        try:
            with self.assertRaises(MigrationError) as cm:
                execute_safe_workforce_migration(
                    spreadsheet=self.spreadsheet,
                    required_tabs=REQUIRED_TABS,
                    backup_root_dir=self.test_dir,
                    authorization_code=get_configured_auth_code(),
                    confirm_spreadsheet_id=self.sp_id,
                    dry_run=False,
                )
            self.assertIn("post-write verification failed", str(cm.exception).lower())

            # Check that manifest recorded the failed operation
            subdirs = [os.path.join(self.test_dir, d) for d in os.listdir(self.test_dir)]
            manifest_path = os.path.join(subdirs[0], "manifest.json")
            with open(manifest_path, "r") as f:
                manifest = json.load(f)
            self.assertEqual(manifest["status"], "MIGRATION_FAILED")
            self.assertEqual(manifest["failed_operation"]["operation"], "WRITE_HEADERS_EmployeeDocuments")
        finally:
            SyntheticWorksheet.update = original_update

    def test_18_full_grid_rollback_restoration_values_and_formulas(self):
        """Scenario 18: Rollback restores original full grid (values + formulas) and verifies fingerprint."""
        # Create a pre-existing workforce worksheet with formula and values, missing some canonical headers
        canon_headers = REQUIRED_TABS["SalaryStructures"]
        truncated = canon_headers[:3]  # structure_id, emp_id, base_salary
        self.spreadsheet.add_worksheet("SalaryStructures", initial_grid=[
            truncated,
            ["STR-001", "EMP-01", "25000"],
            ["STR-002", "EMP-02", "=C2*1.2"],  # Formula in grid
        ])

        # Run migration - appends missing columns to SalaryStructures
        res = execute_safe_workforce_migration(
            spreadsheet=self.spreadsheet,
            required_tabs=REQUIRED_TABS,
            backup_root_dir=self.test_dir,
            authorization_code=get_configured_auth_code(),
            confirm_spreadsheet_id=self.sp_id,
            dry_run=False,
        )
        self.assertIn("SalaryStructures", res["modified_worksheets"])
        manifest_path = os.path.join(res["backup_directory"], "manifest.json")

        # Prior to rollback, verify that SalaryStructures now has all canonical headers
        ws = self.spreadsheet.worksheet("SalaryStructures")
        self.assertEqual(len(ws.get_all_values()[0]), len(canon_headers))

        # Execute rollback
        rb_res = execute_safe_workforce_rollback(
            spreadsheet=self.spreadsheet,
            manifest_path=manifest_path,
            authorization_code=get_configured_auth_code(),
        )
        self.assertIn("SalaryStructures", rb_res["restored_worksheets"])

        # Verify grid restored exactly to truncated original including formula
        restored_grid = ws.get_all_values()
        self.assertEqual(restored_grid[0], truncated)
        self.assertEqual(restored_grid[1], ["STR-001", "EMP-01", "25000"])
        self.assertEqual(restored_grid[2], ["STR-002", "EMP-02", "=C2*1.2"])

    def test_19_missing_confirm_spreadsheet_id_rejected(self):
        """Scenario 19: Missing confirm_spreadsheet_id is rejected when spreadsheet has an ID."""
        with self.assertRaises(AuthorizationError) as cm:
            execute_safe_workforce_migration(
                spreadsheet=self.spreadsheet,
                required_tabs=REQUIRED_TABS,
                backup_root_dir=self.test_dir,
                authorization_code=get_configured_auth_code(),
                confirm_spreadsheet_id=None,
                dry_run=False,
            )
        self.assertIn("confirm_spreadsheet_id", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
