# Kawad Swad ERP — Phase 1.6 Source-Wide Write-Path & OAuth Scope Audit

**Audit Scope:** Exhaustive static and AST scan across `backend/app/`, `backend/scripts/`, and `src/` for every mutation-capable pathway, Google Sheets API call, HTTP client, migration utility, and OAuth scope declaration.  
**Date:** 2026-11-19  
**Architecture Baseline:** Blueprint v2.1 Single-Write-Owner (Apps Script is the sole governed database writer; FastAPI backend is strictly read-only toward Google Sheets).

---

## 1. OAuth Scope Analysis (`backend/app/sheets.py`)

| Location | Previous Scope(s) | Repaired Scope(s) | Classification | Risk After Repair |
|---|---|---|---|---|
| `backend/app/sheets.py:31-33` (`SHEETS_OAUTH_SCOPES`) & `init_connection()` | `https://www.googleapis.com/auth/spreadsheets`, `https://www.googleapis.com/auth/drive.file` | `["https://www.googleapis.com/auth/spreadsheets.readonly"]` | **Read-only (Least Privilege)** | **LOW** — OAuth token itself cannot perform Google Sheets writes even if code were bypassed. Service account IAM permissions in GCP must also be verified by Owner outside the repo. |

**Evidence:** `TestP15008DirectWritePathsAndReadOnlyOAuthScope.test_p15008_sheets_oauth_scopes_are_strictly_readonly` verifies `SHEETS_OAUTH_SCOPES == ["https://www.googleapis.com/auth/spreadsheets.readonly"]` and confirms neither `auth/spreadsheets"` nor `auth/drive.file` appears in `backend/app/sheets.py`.

---

## 2. Complete Mutation-Capable Pathway Inventory

| Pathway / File | Symbols / Operations Found | Classification | Guard Mechanism Verified | Status |
|---|---|---|---|---|
| `backend/app/apps_script_bridge.py` (`execute_governed_write`) | Signed HTTPS POST (`urllib.request`, `_NoRedirectHandler`) to Apps Script WebApp | **Governed / Protected** | 127-action 1:1 allowlist, full-union primary/secondary/child schema conflict block (`P1.5-001`), pre-write ID/prefix/duplicate/cross-table validation (`P1.5-007`), HMAC-SHA256 signing, echo validation, read-back verification | **SAFE (subject to DB-008 remote writer audit)** |
| `backend/app/routers/*.py` (all routers) | All business mutations delegate through `apps_script_bridge` | **Governed / Protected** | AST audit confirms **0** direct `db.append_row`, `append_rows`, `update_row`, `delete_row`, `update_cell`, `batch_update`, `clear`, or `insert_row` calls across every router file | **SAFE** |
| `backend/app/sheets.py` (`append_record`, `update_record`, `delete_record`, `_ensure_headers`) | Legacy `gspread` write helpers (`worksheet.append_row`, `worksheet.update`, etc.) | **Local Isolated Test Only (Blocked in Runtime)** | `_assert_direct_mutation_allowed()` raises `RuntimeError("BLOCKED_PENDING_OWNER_SETUP...")` whenever `(self.is_connected and self.spreadsheet)` OR `not self.allow_in_memory_fallback`; OAuth scope is strictly `spreadsheets.readonly` | **SAFE** |
| `backend/app/sheets.py` (`log_audit`) | Audit logging helper | **Read-only in Runtime / Local Test Only** | When connected or `not allow_in_memory_fallback`, writes only structured Python `logger.info(...)` without mutating Sheets; in-memory append only in isolated `SALES_TESTING=1` | **SAFE** |
| `backend/app/workforce_migration.py` (`execute_safe_workforce_migration`, `execute_safe_workforce_rollback`) | `spreadsheet.add_worksheet`, `spreadsheet.del_worksheet`, `ws.clear()`, header append | **Offline Maintenance (Fail-Closed + Production Refusal)** | `_assert_offline_migration_allowed()` unconditionally raises `AuthorizationError` if `SALES_ENV=production` (even if opt-in flag set), fails closed by default unless `SALES_ALLOW_OFFLINE_SHEETS_MIGRATION=1` (non-production) or `SALES_TESTING=1`, plus requires `SALES_MIGRATION_AUTH_CODE` + `confirm_spreadsheet_id` + backup manifest verification | **SAFE** |
| `backend/scripts/migrate_workforce_stage3.py` | CLI wrapper for `workforce_migration.py` (`--dry-run`, `--execute`, `--rollback`) | **Offline Maintenance (Fail-Closed + Production Refusal)** | `SCRIPT_MUTATION_MODE = "OFFLINE_MAINTENANCE_OPT_IN_REQUIRED"`; `--dry-run` is read-only; `--execute` and `--rollback` invoke `_assert_offline_migration_allowed()` and fail closed by default & on `SALES_ENV=production` | **SAFE** |
| `backend/scripts/bootstrap_owner.py` | Legacy direct `Users`/`AuthUsers` row creation | **Legacy Disabled** | `SCRIPT_MUTATION_MODE = "LEGACY_DIRECT_WRITE_DISABLED"`; `_assert_offline_script_allowed()` raises `BLOCKED_SINGLE_WRITE_OWNER` by default and unconditionally refuses `SALES_ENV=production` | **SAFE** |
| `backend/scripts/reset_password.py` | Legacy direct `AuthUsers` password hash update | **Legacy Disabled** | `SCRIPT_MUTATION_MODE = "LEGACY_DIRECT_WRITE_DISABLED"`; `_assert_offline_script_allowed()` raises `BLOCKED_SINGLE_WRITE_OWNER` by default and unconditionally refuses `SALES_ENV=production` | **SAFE** |
| `backend/scripts/update_sheets_recipe_master.py` | Legacy direct `Recipes`/`RawMaterials` sync | **Legacy Disabled** | `SCRIPT_MUTATION_MODE = "LEGACY_DIRECT_WRITE_DISABLED"`; `_assert_offline_script_allowed()` raises `BLOCKED_SINGLE_WRITE_OWNER` by default and unconditionally refuses `SALES_ENV=production` | **SAFE** |
| `backend/scripts/audit_users.py` | Reads `Users` and `AuthUsers` via `audit_user_reconciliation()` | **Read-Only** | Zero write calls; strictly diagnostic read-only CLI | **SAFE** |
| `backend/scripts/run_staging_walkthrough.py` | Sets `SALES_TESTING=1` and writes to in-memory `db.memory_store` | **Local Isolated Test Only** | Forces `SALES_TESTING=1` with synthetic in-memory seed data; never connects to live Sheets | **SAFE (Offline Harness Only)** |
| `backend/app/schema_registry.py` (`_RUNTIME_CORE_SCHEMA_RECONCILIATIONS.clear()`) | Python dict `.clear()` in memory | **Local Isolated Test Only** | Pure in-memory Python dictionary reset (no Sheets or DB I/O) | **SAFE** |

---

## 3. Mutation Guard Verification Results

All automated static and behavioral write-path tests in `tests.test_phase1_6_targeted_repairs` passed:
- `test_p15008_sheets_oauth_scopes_are_strictly_readonly`: **PASS**
- `test_p15008_workforce_migration_fails_closed_without_explicit_offline_flag`: **PASS**
- `test_p15008_legacy_direct_write_scripts_fail_closed_by_default`: **PASS**
- `test_p15008_zero_direct_sheets_mutations_or_rogue_http_in_routers`: **PASS**
- `test_p15008_offline_opt_in_cannot_activate_in_production_and_direct_db_write_blocked`: **PASS**

---

## 4. Remaining Risks

1. **External Apps Script Writer (`DB-008`):** The remote Google Apps Script `WebAppBridge.gs` / `doPost` source is not present in this repository. Until audited, remote atomicity, lock usage (`LockService`), and server-side Apps Script validation cannot be independently certified.
2. **External IAM Role:** While the backend code now requests only `spreadsheets.readonly`, the Owner should ensure the Google Cloud service account shared with the spreadsheet is restricted to **Viewer** (read-only) access in Google Drive/Sheets sharing settings so defense-in-depth holds at both OAuth and IAM layers.
