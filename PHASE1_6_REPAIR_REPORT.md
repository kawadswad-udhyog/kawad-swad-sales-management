# Kawad Swad ERP — Phase 1.6 Targeted Repair Report

**Mission:** Phase 1.6 Targeted Repair Mission (remediation of all 9 verified Phase 1.5 findings `P1.5-001` through `P1.5-009`)  
**Scope:** Local workspace source copy only (`/app/applet`). Zero live Google Sheets, Apps Script, Render, or production secret access.  
**Phase 1.6 Overall Status:** `REPAIR COMPLETE, READY FOR INDEPENDENT VERIFICATION`  
**Phase 1 Official Gate Status:** `BLOCKED` (unchanged — external artifacts `DB-003`, `DB-007`, and `DB-008` remain absent and are NOT fabricated)

---

## 1. Executive Summary

Phase 1.5 independent verification identified **9 verified defects** across database schema write gating, ID prefix enforcement, token revocation security, audit documentation accuracy, schema reconciliation unlock validation, frontend error/badge mapping, pre-write ID validation, Sheets OAuth scope & offline write-path hardening, and authentication configuration/test fidelity.

All **9 findings (`P1.5-001` through `P1.5-009`)** were reproduced in the local source, repaired at root cause, verified with dedicated regression tests that fail on the defective behavior and pass on the repaired implementation, and validated via isolated backend tests (`85/85` across 9 suites), frontend contract tests (`10/10`), TypeScript typecheck (`tsc --noEmit`), and Vite production build (`2,325` modules).

No Phase 2 features, database migrations, live deployments, or ERP redesigns were performed.

---

## 2. Finding-by-Finding Repair Breakdown

### `P1.5-001` (CRITICAL) — Secondary-Tab Schema Guard Bypass
- **Status:** `REPAIRED AND TESTED`
- **Reproduced:** Yes. Passing a non-empty subset `invalidate_tabs` (e.g., `["GoodsReceipts"]` on `RECEIVE_GOODS` or `["MillingBatches", "RawMaterialLedger"]` on `RECORD_MILLING_BATCH`) bypassed the conflicting core schema check on `RawMaterials` because `candidate_write_tabs` previously fell back to `spec.allowed_invalidate_tabs` only when `requested_inv` was empty.
- **Root Cause:** Conditional `if requested_inv else spec.allowed_invalidate_tabs` logic in `backend/app/apps_script_bridge.py` (`execute_governed_write`) allowed caller-supplied subsets to shrink the set of validated tabs, compounded by router call-sites omitting secondary tabs (`purchasing.py`, `v2_erp.py`).
- **Repair:**
  - Updated `backend/app/apps_script_bridge.py` so `candidate_write_tabs` ALWAYS computes the authoritative full union of `clean_tab` + all `sorted(spec.allowed_invalidate_tabs)` + all allowlisted `requested_inv` + all `spec.readback.child_checks` tabs.
  - Updated post-write cache invalidation to also invalidate the full union `set(requested_inv) | set(spec.allowed_invalidate_tabs) | {spec.target_tab}`.
  - Updated router call-sites in `backend/app/routers/purchasing.py` (`RECEIVE_GOODS`) and `backend/app/routers/v2_erp.py` (`RECORD_PACKAGING_BATCH`, `RECORD_MILLING_BATCH`, `CREATE_PRODUCTION_BATCH`) to explicitly include `"RawMaterials"`, `"PurchaseOrders"`, and `"Products"`.
- **Verification:** `TestP15001SecondaryTabSchemaBypass` (3 tests, including exhaustive sweep across all governed actions touching any write-blocked tab with `[target_tab]`, `[]`, and `None`, asserting `HTTP 503` and `0` bridge HTTP calls) + `test_db002_bridge_blocks_primary_and_secondary_conflicting_core_tabs`.

### `P1.5-002` (HIGH) — Salary Incentive ID Deadlock & `RCPT` Cross-Table Collision
- **Status:** `REPAIRED AND TESTED`
- **Reproduced:** Yes. `CREATE_SALARY_INCENTIVE` declared `locked_prefix="SAL"` in `action_registry.py` while `COLLIDING_LEGACY_PREFIX_TABS["SalaryIncentives"]` blocked `SAL` on new allocation, creating a mathematical deadlock where zero IDs could pass `_validate_id_format()`. Simultaneously, `_validate_id_format()` short-circuited `if not effective_prefix: return True`, bypassing `COLLIDING_LEGACY_PREFIX_TABS` for non-locked tables (`SalaryIncentives`, `SalaryReceipts`).
- **Root Cause:** Contradictory `locked_prefix="SAL"` assignment on a non-locked table and a premature `return True` bypass in `AppsScriptBridge._validate_id_format()`.
- **Repair:**
  - Set `locked_prefix=None` on `CREATE_SALARY_INCENTIVE` in `backend/app/action_registry.py` without inventing an unapproved locked prefix.
  - Fixed `AppsScriptBridge._validate_id_format()` in `backend/app/apps_script_bridge.py` to ALWAYS delegate to `validate_table_id_prefix()`.
  - Added pre-write and post-write enforcement of `SalaryReceipts` child `receipt_id`/`receipt_number` (blocking `RCPT-*` collisions and cross-table duplicates against `Payments`) and `SalaryIncentives` vs `SalaryPayments` cross-table checks.
- **Verification:** `TestP15002SalaryIncentiveDeadlockAndRcptCollision` (3 tests, including exhaustive non-deadlock check across all 127 governed actions).

### `P1.5-003` (HIGH) — Token Revocation Fail-Open & Auth Hardening
- **Status:** `REPAIRED AND TESTED`
- **Reproduced:** Yes. `is_token_revoked()` swallowed exceptions from `db.get_records("RevokedTokens")` and returned `False`, allowing revoked tokens to authenticate when the sheet was unreachable or malformed. In addition, `sessions_revoked_at` parse errors were ignored, login vs token deactivation predicates diverged (`"0"`, `"no"`, `""`), login 503 leaked raw exception text, and `/logout` returned silent success when bridge persistence failed.
- **Root Cause:** Broad `except Exception: return False` fail-open pattern in `backend/app/auth.py` and unshared account status checks.
- **Repair:**
  - Added `RevocationVerificationError`, shared `is_account_deactivated()`, and `check_token_revocation(token, payload, fresh=True) -> Tuple[bool, Optional[str]]` in `backend/app/auth.py`.
  - Missing sheet/network errors return `REVOCATION_STORE_UNAVAILABLE` (`HTTP 503`); non-list or non-dict `RevokedTokens` responses return `REVOCATION_DATA_MALFORMED` (`HTTP 503`); malformed `sessions_revoked_at` timestamps fail closed with `HTTP 401`.
  - Updated `backend/app/routers/auth.py` to use `is_account_deactivated()`, sanitize 503 login error detail, and return `persisted: False` with explicit `warning` when `/logout` cannot confirm bridge persistence.
- **Verification:** `TestP15003TokenRevocationFailClosedAndAuthHardening` (6 tests).

### `P1.5-004` (HIGH) — Incorrect Schema-Conflict Audit Report
- **Status:** `REPAIRED AND TESTED`
- **Reproduced:** Yes. `PHASE1_MASTER_AUDIT_REPORT.md` previously mislisted 7 non-conflicting tables (`ApprovalRequests`, `Attendance`, `DailyClosings`, `GoodsReceipts`, `MillingBatches`, `StockMovements`, `SupplierBills`) instead of the actual 12 conflicting core tables in `schema_registry.py`, and contained `PSL`/`SI` prefix typos.
- **Root Cause:** Manual transcription drift between audit prose and `SCHEMA_HEADER_VARIANCES` in `backend/app/schema_registry.py`.
- **Repair:** Reconstructed the exact 12 conflicting core tables (`Suppliers`, `CustomRoles`, `SalaryIncentives`, `RawMaterials`, `Products`, `Workers`, `Customers`, `Sales`, `ProductionBatches`, `PackagingBatches`, `Expenses`, `ShopVisits` — 46 missing fields) directly from `backend/app/schema_registry.py:273-351`, corrected prefix references (`MOV`, `INVI`), updated unlock description, and kept all 12 conflicts marked unresolved/write-blocked pending `DB-007`.
- **Verification:** `TestP15004SchemaConflictAuditReportAccuracy` (programmatically parses `PHASE1_MASTER_AUDIT_REPORT.md` and asserts set equality with `CONFLICTING_CORE_SCHEMA_TABS`).

### `P1.5-005` (MEDIUM) — Unsafe Schema Reconciliation Unlock
- **Status:** `REPAIRED AND TESTED`
- **Reproduced:** Yes. `approve_core_schema_reconciliation("Customers", headers=["totally_fake_column"], approved_by="USR-OWNER-001")` previously succeeded and unlocked writes for `Customers`, and environment JSON `SALES_APPROVED_CORE_SCHEMA_RECONCILIATIONS_JSON` lacked canonical header validation.
- **Root Cause:** Unlock helper checked only non-empty unique strings without validating against `REQUIRED_TABS` or `SCHEMA_HEADER_VARIANCES`.
- **Repair:** Added `get_expected_canonical_reconciliation_headers()`, `validate_reconciliation_headers()`, and `_validate_approved_entry()` in `backend/app/schema_registry.py`, enforced identically for both runtime `approve_core_schema_reconciliation()` and env-var `get_approved_core_schema_reconciliations()`. Rejects missing baseline columns, missing variance columns, unexpected extra columns, wrong leading baseline order, untrusted tabs, and mismatched `physical_headers`.
- **Verification:** `TestP15005SafeSchemaReconciliationUnlock` (3 tests) + updated `test_db002_all_12_conflicting_core_tabs_blocked_and_unlock_hardened`.

### `P1.5-006` (MEDIUM) — Frontend Error Mapping & Schema Status Badges
- **Status:** `REPAIRED AND TESTED`
- **Reproduced:** Yes. `src/services/api.ts` did not normalize backend `detail.status === 'BLOCKED_PENDING_OWNER_SETUP'` or blocked `error_code` values (`CORE_SCHEMA_CONFLICT_UNRECONCILED`, `PENDING_OWNER_MAPPING`, etc.) into `workflowStatus`, `ErpOperationsHubView.tsx` fell back to green styling for unrecognized/unknown group statuses, and backend `DATABASE_GROUPS_15` labeled Group `02` (`Suppliers`) and Group `10` (`Expenses`) as `VERIFIED_CORE`.
- **Root Cause:** Unaligned status string checks and green default ternary branch.
- **Repair:**
  - Updated Group `02` and Group `10` `header_mapping_status` in `backend/app/schema_registry.py` to `CONFLICT_RECONCILIATION_REQUIRED`.
  - Added and exported `BLOCKED_OWNER_SETUP_ERROR_CODES`, `normalizeApiErrorPayload()`, `isBlockedOwnerSetupError()`, and `classifySchemaStatusBadge()` in `src/services/api.ts`, wired into `apiRequest`.
  - Wired `isBlockedOwnerSetupError()` and `classifySchemaStatusBadge()` into `src/views/ErpOperationsHubView.tsx` so blocked, pending, and unknown states never render green and coverage gaps (`unmapped_workbook_tabs_remaining`, `write_blocked_schema_tabs_count`) are surfaced accurately.
- **Verification:** `TestP15006BackendGroupStatusAlignment` + `scripts/test_phase1_6_frontend_contracts.ts` (`10/10` scenarios passing) + `npm run lint` + `npm run build`.

### `P1.5-007` (MEDIUM) — Post-Write-Only ID Validation
- **Status:** `REPAIRED AND TESTED`
- **Reproduced:** Yes. `execute_governed_write()` validated ID format only after Apps Script returned a response, allowing invalid caller-supplied primary/child IDs, duplicates, blank update keys, and cross-table collisions to reach the remote bridge.
- **Root Cause:** Absence of a pre-flight validation phase prior to bridge dispatch.
- **Repair:** Implemented `_extract_payload_field()`, `_id_exists_in_tab()`, and `_preflight_validate_payload_ids()` in `backend/app/apps_script_bridge.py`, invoked BEFORE `is_configured()` and HTTP POST. Rejects invalid prefixes (`422`), blank target keys on single-key updates (`422`), duplicate primary IDs (`409`), cross-table collisions (`409`), and invalid/duplicate child IDs (`SalaryReceipts`, `SaleItems`, `JournalLines`, `SalesOrderItems`) with zero HTTP requests sent. Post-write checks remain active as defense in depth.
- **Verification:** `TestP15007PreWriteIdValidation` (2 tests asserting `mock_opener.assert_not_called()` across invalid prefix, malformed ID, duplicate ID, blank target ID, and invalid child journal line ID).

### `P1.5-008` (MEDIUM) — Direct Write Paths & Over-Privileged Sheets OAuth Scope
- **Status:** `REPAIRED AND TESTED`
- **Reproduced:** Yes. `backend/app/sheets.py` requested full read-write Google Sheets and Drive OAuth scopes (`spreadsheets`, `drive.file`); `workforce_migration.py` and legacy scripts (`bootstrap_owner.py`, `reset_password.py`, `update_sheets_recipe_master.py`) lacked fail-closed Single-Write-Owner offline opt-in guards.
- **Root Cause:** Legacy pre-v2.1 direct-write OAuth scopes and unguarded operational scripts.
- **Repair:**
  - Restricted `SHEETS_OAUTH_SCOPES` in `backend/app/sheets.py` strictly to `["https://www.googleapis.com/auth/spreadsheets.readonly"]`.
  - Added `_assert_offline_migration_allowed()` in `backend/app/workforce_migration.py` requiring explicit `SALES_ALLOW_OFFLINE_SHEETS_MIGRATION=1` (allowing isolated mock tests under `SALES_TESTING=1`).
  - Added `SCRIPT_MUTATION_MODE = "LEGACY_DIRECT_WRITE_DISABLED"` and `_assert_offline_script_allowed()` fail-closed guard to `bootstrap_owner.py`, `reset_password.py`, and `update_sheets_recipe_master.py`.
- **Verification:** `TestP15008DirectWritePathsAndReadOnlyOAuthScope` (4 tests, including AST audit confirming zero direct `db` write calls across all routers).

### `P1.5-009` (LOW) — Auth Config, Lockout Consistency & Test Fidelity
- **Status:** `REPAIRED AND TESTED`
- **Reproduced:** Yes. The stdlib mock `jwt.decode` in `backend/tests/__init__.py` skipped HMAC signature verification and ignored `exp`; login lockout duration was hardcoded (`300.0`) with a hardcoded `"5 minutes"` string; `require_sheets_connection()` passed when `SALES_ENV == "production"` and `SALES_GOOGLE_SPREADSHEET_ID` was empty.
- **Root Cause:** Test double shortcut and unparameterized auth constants.
- **Repair:**
  - Upgraded `backend/tests/__init__.py` mock `jwt.decode` to verify HMAC-SHA256 signature via `hmac.compare_digest` and enforce `exp` expiration.
  - Added `SALES_LOGIN_MAX_ATTEMPTS`, `SALES_LOGIN_LOCKOUT_SECONDS`, and `SALES_ALLOW_OFFLINE_SHEETS_MIGRATION` in `backend/app/config.py`, wired into `backend/app/routers/auth.py` with dynamic `_format_lockout_duration()`.
  - Hardened `require_sheets_connection()` in `backend/app/auth.py` to fail closed (`HTTP 503`) if `SALES_ENV == "production"` and `SALES_GOOGLE_SPREADSHEET_ID` is empty.
- **Verification:** `TestP15009AuthConfigLockoutAndTestFidelity` (3 tests verifying expired JWT rejection, tampered signature rejection, 401 -> 429 lockout with matching duration -> expiry -> reset on login, deactivated login 403, and production empty-spreadsheet-ID 503).

---

## 3. Open External Blockers (Unchanged & Explicitly Preserved)

The following external artifact gaps cannot be solved by local code changes and remain **OPEN**:
1. **`DB-003`:** 164 of 255 workbook tabs are absent from the repository (`91/255` catalogued, `35.69%`). No tabs were invented.
2. **`DB-007`:** Authoritative physical Row-1 Google Sheets headers for the 12 conflicting core tables have not been supplied by the Owner; all 12 remain write-blocked fail-closed.
3. **`DB-008`:** Apps Script `WebAppBridge.gs` / `doPost` writer source is absent from the repository and could not be independently audited.
