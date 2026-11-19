# Kawad Swad ERP — Phase 1.6 Changelog

All files modified or added during Phase 1.6 Direct Code Repair Mission (local workspace only; **0 files deleted**):

## Backend Production Modules Modified
1. **`backend/app/apps_script_bridge.py`** (`P1.5-001`, `P1.5-002`, `P1.5-007`)
   - Enforced full-union secondary-tab schema gating (`target_tab` + all `spec.allowed_invalidate_tabs` + allowlisted `requested_inv` + all `spec.readback.child_checks`) and full-union post-write cache invalidation.
   - Removed `_validate_id_format()` `None` short-circuit so `validate_table_id_prefix()` always enforces `COLLIDING_LEGACY_PREFIX_TABS` and locked-prefix isolation.
   - Added `_extract_payload_field()`, `_id_exists_in_tab()`, and `_preflight_validate_payload_ids()` running BEFORE `is_configured()` and HTTP POST, plus post-write `SalaryReceipts` child `receipt_id` verification.
2. **`backend/app/action_registry.py`** (`P1.5-002`)
   - Removed contradictory `locked_prefix="SAL"` on `CREATE_SALARY_INCENTIVE` (`locked_prefix=None`) to resolve prefix deadlock while maintaining `SAL-*` new-allocation blocking and historical read support.
3. **`backend/app/schema_registry.py`** (`P1.5-005`, `P1.5-006`)
   - Added `get_expected_canonical_reconciliation_headers()`, `validate_reconciliation_headers()`, `_validate_approved_entry()`, and structured `logger.warning(...)` rejection logging enforced identically on `approve_core_schema_reconciliation()` and `get_approved_core_schema_reconciliations()`.
   - Updated Group `02` (`Suppliers`) and Group `10` (`Expenses`) `header_mapping_status` from `VERIFIED_CORE` to `CONFLICT_RECONCILIATION_REQUIRED`.
4. **`backend/app/auth.py`** (`P1.5-003`, `P1.5-009`)
   - Added `RevocationVerificationError`, `is_account_deactivated()`, and `check_token_revocation()` failing closed (`HTTP 503`) on missing/failing/malformed `RevokedTokens`.
   - Failed closed (`HTTP 401`) on malformed `sessions_revoked_at` timestamps.
   - Hardened `require_sheets_connection()` to fail closed (`HTTP 503`) in `production` when `SALES_GOOGLE_SPREADSHEET_ID` is empty.
5. **`backend/app/routers/auth.py`** (`P1.5-003`, `P1.5-009`)
   - Switched login active check to `is_account_deactivated()`, sanitized `HTTP 503` login error detail, added explicit `persisted: False` + `warning` on unpersisted `/logout`, and wired `SALES_LOGIN_MAX_ATTEMPTS` + `SALES_LOGIN_LOCKOUT_SECONDS` with dynamic `_format_lockout_duration()`.
6. **`backend/app/config.py`** (`P1.5-008`, `P1.5-009`)
   - Added `SALES_LOGIN_MAX_ATTEMPTS`, `SALES_LOGIN_LOCKOUT_SECONDS`, and `SALES_ALLOW_OFFLINE_SHEETS_MIGRATION`.
7. **`backend/app/routers/purchasing.py`** (`P1.5-001`)
   - Added `"RawMaterials"` and `"PurchaseOrders"` to `RECEIVE_GOODS` `invalidate_tabs`.
8. **`backend/app/routers/v2_erp.py`** (`P1.5-001`)
   - Added `"Products"` to `RECORD_PACKAGING_BATCH` and `"RawMaterials"` to `RECORD_MILLING_BATCH` and `CREATE_PRODUCTION_BATCH` `invalidate_tabs`.
9. **`backend/app/sheets.py`** (`P1.5-008`)
   - Restricted `SHEETS_OAUTH_SCOPES` strictly to `["https://www.googleapis.com/auth/spreadsheets.readonly"]` and removed read-write `spreadsheets` / `drive.file` scopes.
10. **`backend/app/workforce_migration.py`** (`P1.5-008`)
    - Added `_assert_offline_migration_allowed()` fail-closed guard on non-dry-run execution and rollback, unconditionally refusing `SALES_ENV=production`.

## Backend Operational Scripts Modified
11. **`backend/scripts/migrate_workforce_stage3.py`** (`P1.5-008`) — Added `SCRIPT_MUTATION_MODE = "OFFLINE_MAINTENANCE_OPT_IN_REQUIRED"` and enforced `_assert_offline_migration_allowed()` on `--execute` and `--rollback`.
12. **`backend/scripts/bootstrap_owner.py`** (`P1.5-008`) — Added `SCRIPT_MUTATION_MODE = "LEGACY_DIRECT_WRITE_DISABLED"` and fail-closed / production-refusal guard.
13. **`backend/scripts/reset_password.py`** (`P1.5-008`) — Added `SCRIPT_MUTATION_MODE = "LEGACY_DIRECT_WRITE_DISABLED"` and fail-closed / production-refusal guard.
14. **`backend/scripts/update_sheets_recipe_master.py`** (`P1.5-008`) — Added `SCRIPT_MUTATION_MODE = "LEGACY_DIRECT_WRITE_DISABLED"` and fail-closed / production-refusal guard.

## Frontend Modules Modified
15. **`src/services/api.ts`** (`P1.5-006`) — Exported `BLOCKED_OWNER_SETUP_ERROR_CODES`, `normalizeApiErrorPayload()`, `isBlockedOwnerSetupError()`, and `classifySchemaStatusBadge()`, wired into `apiRequest`.
16. **`src/views/ErpOperationsHubView.tsx`** (`P1.5-006`) — Wired `isBlockedOwnerSetupError()` and `classifySchemaStatusBadge()`, removed green fallback on unknown/blocked/pending/loading states, and surfaced coverage gap counts.

## Tests Modified / Added
17. **`backend/tests/__init__.py`** (`P1.5-009`) — Upgraded stdlib mock `jwt.decode` to verify HMAC-SHA256 signatures and enforce `exp` expiration.
18. **`backend/tests/test_phase1_database_schema_guards.py`** (`P1.5-001`, `P1.5-005`) — Updated reconciliation test to assert fake/subset headers raise `ValueError` and test `[primary_tab]`/`[]` secondary-tab subset calls.
19. **`backend/tests/test_phase1_6_targeted_repairs.py`** *(NEW)* — 32 regression and adversarial security tests covering all 9 findings.
20. **`scripts/test_phase1_6_frontend_contracts.ts`** *(NEW)* — 14 frontend contract and error-mapping regression tests.

## Documentation & Phase 1.6 Deliverables Updated / Added
21. **`PHASE1_MASTER_AUDIT_REPORT.md`** (`P1.5-004`) — Rebuilt exact 12 conflicting core tables, fixed prefix typos, and aligned unlock/secondary-tab documentation.
22. **`PHASE1_6_DIRECT_REPAIR_REPORT.md`** *(NEW)*
23. **`PHASE1_6_REPAIR_MATRIX.csv`** *(NEW)*
24. **`PHASE1_6_DIRECT_TEST_RESULTS.md`** *(NEW)*
25. **`PHASE1_6_WRITE_PATH_AUDIT.md`** *(NEW)*
26. **`PHASE1_6_CHANGELOG.md`** *(UPDATED)*
27. **`PHASE1_6_FINAL_GATE.md`** *(UPDATED)*
28. *(Retained from earlier Phase 1.6 pass for traceability: `PHASE1_6_REPAIR_REPORT.md`, `PHASE1_6_DEFECT_REPAIR_MATRIX.csv`, `PHASE1_6_TEST_RESULTS.md`, `PHASE1_6_SECURITY_CHANGES.md`)*
