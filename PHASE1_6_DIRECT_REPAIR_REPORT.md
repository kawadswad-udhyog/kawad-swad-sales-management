# Kawad Swad ERP — Phase 1.6 Direct Code Repair Report

**Mission:** Phase 1.6 Direct Code Repair Mission  
**Reference Source:** Local workspace copy corresponding to `kawad-swad-sales-management-main (39).zip` (`/app/applet`)  
**Overall Phase 1.6 Status:** `REPAIR COMPLETE, READY FOR INDEPENDENT VERIFICATION`  
**Official Phase 1 ERP Gate:** `BLOCKED` *(external artifacts `DB-003`, `DB-007`, and `DB-008` remain missing and are NOT fabricated)*

---

## 1. Baseline Repository State & Local Isolation

Verified prior to all edits and re-verified after final test runs:
- **Working directory:** `/app/applet` (isolated local workspace, no `.git` remote attached).
- **Live environment variables set:** `[]` (`0` of 12 live/production variables set: `SALES_GOOGLE_SPREADSHEET_ID`, `SALES_GOOGLE_CREDENTIALS_JSON`, `SALES_GOOGLE_CREDENTIALS_B64`, `SALES_APPS_SCRIPT_WEBAPP_URL`, `SALES_APPS_SCRIPT_SHARED_SECRET`, `SALES_APPS_SCRIPT_ENABLED`, `SALES_MIGRATION_AUTH_CODE`, `SALES_ALLOW_OFFLINE_SHEETS_MIGRATION`, `RENDER`, `RENDER_SERVICE_ID`, `GOOGLE_APPLICATION_CREDENTIALS`, `SALES_APPROVED_CORE_SCHEMA_RECONCILIATIONS_JSON`).
- **Live service account file:** `/etc/secrets/sales-service-account.json` -> `False` (absent).
- **Live systems accessed/modified:** None (`0` Google Sheets calls, `0` Apps Script calls, `0` Render deployments, `0` production secrets).

---

## 2. Direct Code Repairs Implemented (Prescribed Priority Order)

### Priority 1 — Critical Security & Data Integrity

#### 1. `P1.5-001` (CRITICAL) — Secondary-Tab Schema Bypass
- **Root Cause:** `AppsScriptBridge.execute_governed_write()` previously fell back to `spec.allowed_invalidate_tabs` only when caller-supplied `invalidate_tabs` was empty, letting a caller-supplied non-empty subset (e.g., `["GoodsReceipts"]` on `RECEIVE_GOODS` or `["MillingBatches", "RawMaterialLedger"]` on `RECORD_MILLING_BATCH`) skip schema conflict checks on secondary tabs (`RawMaterials`, `Products`). Several router call-sites also omitted secondary tabs.
- **Actual Code Changes:**
  - `backend/app/apps_script_bridge.py`: `candidate_write_tabs` now ALWAYS checks the authoritative full union of `clean_tab` + all `sorted(spec.allowed_invalidate_tabs)` + all allowlisted `requested_inv` + all `spec.readback.child_checks` tabs before dispatch. Unknown requested tabs fail closed with `HTTP 422 UNAUTHORIZED_INVALIDATION_TAB`. Post-write cache invalidation also uses the full union.
  - `backend/app/routers/purchasing.py`: Added `"RawMaterials"` and `"PurchaseOrders"` to `RECEIVE_GOODS` `invalidate_tabs`.
  - `backend/app/routers/v2_erp.py`: Added `"Products"` to `RECORD_PACKAGING_BATCH` and `"RawMaterials"` to `RECORD_MILLING_BATCH` and `CREATE_PRODUCTION_BATCH`.
- **Verification:** `TestP15001SecondaryTabSchemaBypass` + `test_p15001_unknown_requested_invalidation_tab_fails_closed_zero_http` + updated `test_db002_bridge_blocks_primary_and_secondary_conflicting_core_tabs` (all governed actions touching any write-blocked tab tested with `[target_tab]`, `[]`, `None`; `0` HTTP calls attempted).

#### 2. `P1.5-003` (HIGH) — Token Revocation Fail-Open
- **Root Cause:** `is_token_revoked()` previously caught all `RevokedTokens` sheet read exceptions and returned `False` (fail-open). Corrupted `sessions_revoked_at` timestamps were ignored, account deactivation flags (`"0"`, `"no"`, `""`) diverged between login and token checks, login 503 leaked raw exceptions, and `/logout` hid failed bridge persistence.
- **Actual Code Changes:**
  - `backend/app/auth.py`: Added `RevocationVerificationError`, shared `is_account_deactivated()`, and `check_token_revocation(token, payload, fresh=True) -> Tuple[bool, Optional[str]]`. Missing/unreachable `RevokedTokens` fails closed with `HTTP 503 REVOCATION_STORE_UNAVAILABLE`; non-list/non-dict responses fail closed with `HTTP 503 REVOCATION_DATA_MALFORMED`; unparseable `sessions_revoked_at` fails closed with `HTTP 401`.
  - `backend/app/routers/auth.py`: Switched login active check to `is_account_deactivated()`, sanitized 503 login detail, and added `persisted: False` + explicit `warning` on unpersisted `/logout`.
- **Verification:** `TestP15003TokenRevocationFailClosedAndAuthHardening` (6 tests) + `test_p15003_protected_write_and_auth_request_denied_during_revocation_outage` (asserting `HTTP 503` and `0` remote bridge calls).

#### 3. `P1.5-005` (MEDIUM/HIGH) — Unsafe Schema Reconciliation Unlock
- **Root Cause:** Both `approve_core_schema_reconciliation()` and `SALES_APPROVED_CORE_SCHEMA_RECONCILIATIONS_JSON` validated only non-empty unique header strings, allowing fabricated headers (`["totally_fake_column"]`) to unlock write-blocked core tables without rejection logs.
- **Actual Code Changes:**
  - `backend/app/schema_registry.py`: Added `get_expected_canonical_reconciliation_headers()`, `validate_reconciliation_headers()`, `_validate_approved_entry()`, and structured `logger.warning(...)` rejection logging. Both runtime and environment-variable unlocks now require trusted baseline membership (`REQUIRED_TABS` + `CONFLICTING_CORE_SCHEMA_TABS`), exact leading `REQUIRED_TABS` column ordering, all declared `missing_from_required_tabs` variance fields, zero unexpected columns, and exact `physical_headers` match when supplied. All 12 conflicting core tables remain write-blocked by default.
- **Verification:** `TestP15005SafeSchemaReconciliationUnlock` (3 tests) + `test_p15005_reconciliation_rejection_emits_clear_warning_logs` + updated `test_db002_all_12_conflicting_core_tabs_blocked_and_unlock_hardened`.

#### 4. `P1.5-002` (HIGH) — Salary Incentive ID Allocation Deadlock & `RCPT` Collisions
- **Root Cause:** `CREATE_SALARY_INCENTIVE` declared `locked_prefix="SAL"` in `action_registry.py` while `COLLIDING_LEGACY_PREFIX_TABS["SalaryIncentives"]` blocked `SAL` on new allocation (deadlock). Meanwhile, `AppsScriptBridge._validate_id_format()` short-circuited `if not effective_prefix: return True`, bypassing `COLLIDING_LEGACY_PREFIX_TABS` for `SalaryIncentives` and `SalaryReceipts`.
- **Actual Code Changes:**
  - `backend/app/action_registry.py`: Removed contradictory `locked_prefix="SAL"` on `CREATE_SALARY_INCENTIVE` (`locked_prefix=None`) without inventing an unapproved locked prefix.
  - `backend/app/apps_script_bridge.py`: Removed `_validate_id_format()` `None` short-circuit so `validate_table_id_prefix()` always enforces `COLLIDING_LEGACY_PREFIX_TABS` and locked-prefix isolation; added pre-write and post-write `SalaryReceipts` child `RCPT` rejection and bidirectional cross-table `Payments`/`SalaryReceipts` and `SalaryIncentives`/`SalaryPayments` collision checks.
- **Verification:** `TestP15002SalaryIncentiveDeadlockAndRcptCollision` (3 tests including 127-action non-deadlock sweep) + `test_p15002_p15007_duplicate_child_ids_in_same_request_and_workforce_cross_table_collision`.

---

### Priority 2 — Remaining Defects

#### 5. `P1.5-007` (MEDIUM) — Identifier Validation After Remote Write
- **Root Cause:** `execute_governed_write()` validated IDs only after remote Apps Script execution.
- **Actual Code Changes:**
  - `backend/app/apps_script_bridge.py`: Added `_extract_payload_field()`, `_id_exists_in_tab()`, and `_preflight_validate_payload_ids()` invoked BEFORE `is_configured()` and HTTP POST, rejecting invalid primary/child prefixes (`422`), blank single-key update targets (`422`), duplicate primary IDs (`409`), duplicate child IDs within the same request or existing sheet (`409`), and cross-table collisions (`409`) with zero remote calls. Post-write checks remain as defense in depth.
- **Verification:** `TestP15007PreWriteIdValidation` (2 tests) + same-request duplicate child ID & cross-table collision tests asserting `mock_opener.assert_not_called()`.

#### 6. `P1.5-008` (MEDIUM) — Ungoverned Direct-Write Pathways & OAuth Scope
- **Root Cause:** `backend/app/sheets.py` requested read-write `spreadsheets` and `drive.file` OAuth scopes; `workforce_migration.py` and offline/legacy scripts lacked Single-Write-Owner fail-closed opt-in and production refusal guards.
- **Actual Code Changes:**
  - `backend/app/sheets.py`: Restricted `SHEETS_OAUTH_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]` (read-only least privilege). Verified `_assert_direct_mutation_allowed()` guards `append_record`, `update_record`, `delete_record`, `_ensure_headers`, and read-only telemetry mode in `log_audit`.
  - `backend/app/workforce_migration.py`: Hardened `_assert_offline_migration_allowed()` to fail closed by default AND unconditionally refuse `SALES_ENV=production` even if `SALES_ALLOW_OFFLINE_SHEETS_MIGRATION=1` is set.
  - `backend/scripts/migrate_workforce_stage3.py`: Declared `SCRIPT_MUTATION_MODE = "OFFLINE_MAINTENANCE_OPT_IN_REQUIRED"` and enforced `_assert_offline_migration_allowed()` on `--execute` and `--rollback` (keeping `--dry-run` read-only).
  - `backend/scripts/bootstrap_owner.py`, `backend/scripts/reset_password.py`, `backend/scripts/update_sheets_recipe_master.py`: Added `SCRIPT_MUTATION_MODE = "LEGACY_DIRECT_WRITE_DISABLED"` and `_assert_offline_script_allowed()` failing closed by default and unconditionally refusing `SALES_ENV=production`.
- **Verification:** `TestP15008DirectWritePathsAndReadOnlyOAuthScope` (4 tests) + `test_p15008_offline_opt_in_cannot_activate_in_production_and_direct_db_write_blocked` + full source-wide inventory in `PHASE1_6_WRITE_PATH_AUDIT.md`.

#### 7. `P1.5-006` (MEDIUM) — Frontend Schema Status & Error Mapping
- **Root Cause:** `api.ts` did not normalize backend `detail.status === 'BLOCKED_PENDING_OWNER_SETUP'` or blocked error codes; `ErpOperationsHubView.tsx` fell back to green styling for unknown statuses; `schema_registry.py` labeled Groups `02` (`Suppliers`) and `10` (`Expenses`) as `VERIFIED_CORE`.
- **Actual Code Changes:**
  - `backend/app/schema_registry.py`: Updated Group `02` and Group `10` `header_mapping_status` to `CONFLICT_RECONCILIATION_REQUIRED`.
  - `src/services/api.ts`: Exported `BLOCKED_OWNER_SETUP_ERROR_CODES`, `normalizeApiErrorPayload()`, `isBlockedOwnerSetupError()`, and `classifySchemaStatusBadge()` and wired them into `apiRequest`.
  - `src/views/ErpOperationsHubView.tsx`: Wired `isBlockedOwnerSetupError()` and `classifySchemaStatusBadge()`, eliminated green fallback on unknown/blocked/pending/loading states, and surfaced coverage gap counters (`unmapped_workbook_tabs_remaining`, `write_blocked_schema_tabs_count`).
- **Verification:** `TestP15006BackendGroupStatusAlignment` + `scripts/test_phase1_6_frontend_contracts.ts` (`14/14` scenarios PASS) + `npm run lint` (`0` errors) + `npm run build` (`2,325` modules).

#### 8. `P1.5-009` (LOW) — Authentication, Lockout & Test Fidelity
- **Root Cause:** Mock `jwt.decode` in `backend/tests/__init__.py` skipped HMAC verification and ignored `exp`; login lockout duration/message were hardcoded; `require_sheets_connection()` passed when `SALES_ENV == "production"` and `SALES_GOOGLE_SPREADSHEET_ID` was empty.
- **Actual Code Changes:**
  - `backend/tests/__init__.py`: Upgraded mock `jwt.decode` to verify HMAC-SHA256 signatures (`hmac.compare_digest`) and enforce `exp`.
  - `backend/app/config.py` & `backend/app/routers/auth.py`: Added configurable `SALES_LOGIN_MAX_ATTEMPTS` (`5`) and `SALES_LOGIN_LOCKOUT_SECONDS` (`300.0`) with dynamic `_format_lockout_duration()` matching actual lockout duration.
  - `backend/app/auth.py`: Failed closed (`HTTP 503`) in `require_sheets_connection()` when `SALES_ENV == "production"` and `SALES_GOOGLE_SPREADSHEET_ID` is empty.
- **Verification:** `TestP15009AuthConfigLockoutAndTestFidelity` (4 tests covering valid/invalid-signature/expired/malformed JWTs, lockout threshold/duration/expiry/reset, deactivated login `403`, and production empty-spreadsheet-ID `503`).

#### 9. `P1.5-004` (HIGH) — Schema-Conflict Audit Report Accuracy
- **Root Cause:** `PHASE1_MASTER_AUDIT_REPORT.md` drifted from `SCHEMA_HEADER_VARIANCES`, misreporting 7 non-conflicting tables and containing `PSL`/`SI` prefix typos.
- **Actual Code Changes:**
  - `PHASE1_MASTER_AUDIT_REPORT.md`: Rebuilt the exact 12 conflicting core tables (`Suppliers`, `CustomRoles`, `SalaryIncentives`, `RawMaterials`, `Products`, `Workers`, `Customers`, `Sales`, `ProductionBatches`, `PackagingBatches`, `Expenses`, `ShopVisits` — 46 declared missing fields) directly from `backend/app/schema_registry.py:273-351`, corrected prefix references (`MOV`, `INVI`), and preserved write-blocked status pending `DB-007`.
- **Verification:** `TestP15004SchemaConflictAuditReportAccuracy` (programmatic set equality check against `schema_registry.CONFLICTING_CORE_SCHEMA_TABS`).

---

## 3. Remaining Limitations & Open External Blockers

1. **`DB-003` (External Blocker — Open):** 164 of 255 workbook tabs are absent from the repository (`91/255` catalogued, `35.69%`). Requires authoritative Owner workbook export + DBV5 field dictionary.
2. **`DB-007` (External Blocker — Open):** Authoritative physical Row-1 Google Sheets headers for the 12 conflicting core tables are absent; all 12 remain write-blocked fail-closed.
3. **`DB-008` (External Blocker — Open):** Apps Script `WebAppBridge.gs` / `doPost` writer source is absent from the repository and cannot be independently audited until supplied by the Owner.
4. **Legacy Pre-v2.1 Test Suite Debt (`42/51` files):** Documented with evidence-based per-file categorization in `PHASE1_6_DIRECT_TEST_RESULTS.md`; none are Phase 1.6 regressions and none were weakened or deleted.
