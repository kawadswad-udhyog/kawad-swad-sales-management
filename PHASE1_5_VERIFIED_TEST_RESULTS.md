# PHASE 1.5 INDEPENDENT VERIFIED TEST RESULTS

**Audit Date:** 2026-11-19  
**Auditor Role:** Independent Verification & Integrity Auditor  
**Audit Mode:** STRICT AUDIT MODE (zero edits to existing source code, tests, configs, schemas, or dependencies)  
**Target Repository:** `kawadswad-udhyog/kawad-swad-sales-management` (workspace snapshot; `.git` metadata absent)

---

## 1. Test Environment Isolation Verification (Pre-Execution Gate)

Before running any Python or Node verification command, the runtime environment was verified to guarantee zero live connectivity to Google Sheets, Apps Script, Render, or production secrets:

| Environment Variable / Secret Path | Observed Value | Live Risk |
|---|---|---|
| `SALES_GOOGLE_SPREADSHEET_ID` | `UNSET` | None |
| `SALES_GOOGLE_SERVICE_ACCOUNT_JSON` | `UNSET` | None |
| `SALES_APPS_SCRIPT_ENABLED` | `UNSET` | None |
| `SALES_APPS_SCRIPT_WEBAPP_URL` | `UNSET` | None |
| `SALES_APPS_SCRIPT_SHARED_SECRET` | `UNSET` | None |
| `SALES_JWT_SECRET` | `UNSET` | None |
| `SALES_APPROVED_CORE_SCHEMA_RECONCILIATIONS_JSON` | `UNSET` | None |
| `GOOGLE_APPLICATION_CREDENTIALS` | `UNSET` | None |
| `ENVIRONMENT` / `APP_ENV` | `UNSET` | None |
| `/etc/secrets/sales-service-account.json` | `False` (file absent) | None |

**Result:** Isolated local test environment confirmed. Zero outbound requests to Google Sheets, Google Apps Script, or Render occurred.

---

## 2. Container Runtime & Tooling Limitations (Explicitly Disclosed)

Independent verification identified the following container environment constraints that limit runtime test depth:

1. **No `pytest`, `fastapi`, `httpx`, `starlette`, `PyJWT`, or `gspread` installed in system Python**: All backend `unittest` runs rely on the repository's stdlib mock harness (`backend/tests/__init__.py`).
2. **Mock `jwt` Ignores Token Expiration (`exp`)**: `backend/tests/__init__.py` implements a minimal `jwt` stub that decodes base64 JSON payloads without enforcing `exp` timestamps. Consequently, expired-JWT rejection could **not** be runtime-verified against real `PyJWT` in this container (logged as `P1.5-009`).
3. **No Live ASGI HTTP Stack Execution**: FastAPI middleware, CORS headers, dependency injection wiring, and actual `HTTPException` serialization over ASGI were verified via direct Python invocation and static code inspection rather than live `TestClient`/`uvicorn` HTTP requests.
4. **No `.git` Metadata in Workspace**: Pre-Phase-1 vs. Post-Phase-1 `git diff` could not be mechanically generated; verification relied on direct inspection of current source files and comparison against prior Phase 1 documentation.

---

## 3. Static Compilation & AST Integrity Verification

### 3.1 Python Bytecode Compilation (`py_compile`)
- **Command Scope:** All `.py` files recursively under `backend/`
- **Observed Result:** `PY_COMPILE: total=112, ok=112, errors=0`
- **Status:** **PASS**

### 3.2 Action Registry & Bridge Call-Site AST Cross-Reference
- **Method:** Independent Python `ast` parse of `backend/app/action_registry.py` and every `delegate_governed_write` / `execute_governed_write` call-site across `backend/app/**/*.py`.
- **Observed Result:**
  - `len(_SPECS) = 127`
  - `len(GOVERNED_ACTION_REGISTRY) = 127`
  - `duplicate_actions = 0`
  - `total_call_sites = 132` (`131` static action literals covering `125` unique actions + `1` dynamic conditional expression at `backend/app/user_service.py:1070` resolving strictly to `REACTIVATE_USER` or `DEACTIVATE_USER` -> **`127/127` registered actions accounted for**)
  - `unregistered_call_sites = []`
  - `mismatches = []`
- **Critical Finding Discovered During AST Inspection (`P1.5-001`):**
  - 4 live router call-sites pass a subset `invalidate_tabs` list that omits write-blocked secondary tabs declared in `spec.allowed_invalidate_tabs`:
    1. `backend/app/routers/purchasing.py:520` (`RECEIVE_GOODS`) — passes `["GoodsReceipts", "GoodsReceiptItems", "RawMaterialLedger", "PurchaseOrderItems"]`, omits blocked `"RawMaterials"` (**ACTIVE BYPASS**).
    2. `backend/app/routers/v2_erp.py:1146` (`RECORD_MILLING_BATCH`) — passes `["MillingBatches", "RawMaterialLedger", "JournalHeaders", "JournalLines"]`, omits blocked `"RawMaterials"` (**ACTIVE BYPASS**).
    3. `backend/app/routers/v2_erp.py:634` (`RECORD_PACKAGING_BATCH`) — passes subset omitting blocked `"Products"` (**LATENT BYPASS** once `PackagingBatches` is reconciled).
    4. `backend/app/routers/v2_erp.py:1172` (`CREATE_PRODUCTION_BATCH`) — passes subset omitting blocked `"RawMaterials"` (**LATENT BYPASS** once `ProductionBatches` is reconciled).
- **Status:** Registry coverage **PASS** (`127/127`), Secondary-Tab Enforcement **FAIL** (`P1.5-001`).

---

## 4. Phase 1 Regression Suite Reproduction (`test_phase1_database_schema_guards.py`)

- **Command:** `PYTHONPATH=backend python3 -m unittest tests.test_phase1_database_schema_guards -v`
- **Observed Output:** `Ran 8 tests in 0.108s — OK` (Exit Code: `0`)
- **Pass Count:** `8 / 8 PASS`
- **Independent Audit Assessment of Test Adequacy (CRITICAL GAP IDENTIFIED):**
  - While all 8 tests pass cleanly, `test_db002_bridge_blocks_primary_and_secondary_conflicting_core_tabs` failed to catch the active `P1.5-001` bypass because it only tested:
    - `invalidate_tabs=["StockMovements", "RawMaterials"]` (caller explicitly passes the blocked secondary tab), and
    - `invalidate_tabs=None` (caller passes empty/None, falling back to `spec.allowed_invalidate_tabs`).
  - It **never** tested `invalidate_tabs=["StockMovements"]` (non-empty subset omitting the secondary tab), which is the exact pattern used in live production endpoints (`purchasing.py:520` and `v2_erp.py:1146`).
  - Similarly, `test_db004_legacy_and_colliding_prefix_policies_are_explicit` did **not** test `_validate_id_format()` against `CREATE_SALARY_INCENTIVE` (`target_tab="SalaryIncentives"`, `locked_prefix="SAL"`), missing the `P1.5-002` total validation deadlock.
  - Similarly, `test_db002_explicit_owner_reconciliation_unlocks_only_target_table` passed valid-looking headers and never tested whether bogus 1-column headers (`["totally_fake_column"]`) unlock a core table (`P1.5-005`).

---

## 5. Full Backend Test Suite Reproduction (All 50 `backend/tests/test_*.py` Files)

Every test module under `backend/tests/test_*.py` was executed independently under isolated mode.

### 5.1 Summary Totals
| Metric | Count |
|---|---|
| Total test files discovered | **50** |
| Suites Passing (Exit Code `0`) | **8** (`59` individual tests PASS) |
| Suites Failing (Non-zero exit) | **42** |
| Phase 1 Regressions Identified | **0** (all 42 failures are pre-existing Blueprint v2.1 contract shifts) |

### 5.2 Passing Suites (8 Files / 59 Tests PASS)
| # | Test File | Tests Passed | Exit Code |
|---|---|---:|---:|
| 1 | `backend/tests/test_alias_adapter.py` | 5 | 0 |
| 2 | `backend/tests/test_cors_preflight.py` | 8 | 0 |
| 3 | `backend/tests/test_health_diagnostics_security_and_quota.py` | 8 | 0 |
| 4 | `backend/tests/test_owner_setup.py` | 1 | 0 |
| 5 | `backend/tests/test_phase1_database_schema_guards.py` | 8 | 0 |
| 6 | `backend/tests/test_production_backend_routing.py` | 5 | 0 |
| 7 | `backend/tests/test_sheets_quota_handling.py` | 3 | 0 |
| 8 | `backend/tests/test_workforce_migration_safety.py` | 21 | 0 |
| **Total** | **8 Suites** | **59** | **0** |

### 5.3 Exhaustive Classification of All 42 Failing Legacy Suites
Every failing file was inspected from its actual live traceback. None were introduced by Phase 1 database schema guards; all 42 fail due to pre-existing Blueprint v2.1 architectural changes (`request: Request` signature additions, Single-Write-Owner Apps Script enforcement, and removed pre-v2.1 helpers):

#### Category A — `V2_1_MISSING_REQUEST_ARG` / `V2_1_SHIFTED_CURRENT_USER_ARG` (32 Suites)
Root cause: Blueprint v2.1 added `request: Request` as a required parameter on FastAPI mutation endpoints to enforce idempotency/nonce headers; legacy unit tests call router handler functions directly with pre-v2.1 positional signatures.
1. `test_attendance_and_workflow.py`
2. `test_buyer_info_optional.py`
3. `test_daily_operations_readiness.py`
4. `test_dal_milling_stage2.py`
5. `test_duplicate_sale_idempotency.py`
6. `test_erp_full_lifecycle.py`
7. `test_erp_stabilization.py`
8. `test_finished_goods_inventory.py`
9. `test_integrity.py`
10. `test_live_audit_fixes.py`
11. `test_master_repair_and_readiness.py`
12. `test_master_stage3_production_safety.py`
13. `test_multi_batch_costing.py`
14. `test_phase1_4_1_failure_injection.py`
15. `test_phase1_4_1_sales_payment.py`
16. `test_phase1_4_sales_payment.py`
17. `test_phase1_fixes.py`
18. `test_phase2a_van_loading.py`
19. `test_phase4_clean_data_contracts.py`
20. `test_product_activation.py`
21. `test_production_and_attendance_v2.py`
22. `test_production_corrections.py`
23. `test_production_module.py`
24. `test_raw_material_issuance_recovery.py`
25. `test_raw_material_receiving_stage1.py`
26. `test_recipe_master_v2.py`
27. `test_stabilization_upgrade.py`
28. `test_stage1_comprehensive_verification.py`
29. `test_stage1_failure_injection.py`
30. `test_stock_discrepancy_idempotency.py`
31. `test_supplier_payment_integrity.py`
32. `test_workforce_management.py`

#### Category B — `V2_1_DIRECT_WRITE_BLOCKED` / `V2_1_BRIDGE_UNCONFIGURED_503` / `V2_1_MISSING_NONCE_422` (9 Suites)
Root cause: Blueprint v2.1 Single-Write-Owner policy intentionally blocks direct `SheetsDB` mutations (`DIRECT_SHEETS_WRITE_FORBIDDEN`), returns `HTTP 503` when the Apps Script bridge is unconfigured, and requires `X-Idempotency-Key`/`X-Request-Nonce` (`HTTP 422`).
33. `test_accounting_integrity.py`
34. `test_audit_fixes_regression.py` (5/6 tests PASS; test 6 hits unconfigured bridge `503`)
35. `test_audit_reconciliation.py`
36. `test_double_entry_accounting.py`
37. `test_master_plan_phase1_integrity.py` (asserts old pre-v2.1 error text)
38. `test_startup_port_bind_and_resilience.py`
39. `test_storage_connectivity_protection.py`
40. `test_update_sheets_recipe_master.py`
41. `test_user_system_phase2.py`

#### Category C — `V2_1_REMOVED_PRE_V2_HELPER` (1 Suite)
Root cause: Legacy test patches a pre-v2.1 helper removed during Blueprint v2.1 approval router refactor.
42. `test_phase4_2a_security_guards.py` (9/12 tests PASS; 3 tests error patching removed `app.routers.approvals._run_request_execution`)

*(Total accounted: `32 + 9 + 1 = 42` failing suites; `42 + 8 = 50` total suites.)*

---

## 6. Independent Live Security, Integrity & Bypass Probes (Reproduced)

All probes were executed locally in-process against the unmodified source code using mocked HTTP/Sheets adapters (zero live calls):

| # | Probe Description | Expected Safe Behavior | Actual Reproduced Result | Verdict | Defect ID |
|---|---|---|---|---|---|
| 1 | Multi-tab secondary `DB-002` bypass probe across all 63 multi-tab actions (32 touching write-blocked tabs) passing `invalidate_tabs=[primary_tab]` | All 12 secondary-tab actions with unblocked primary & blocked secondary must fail closed (`503 CORE_SCHEMA_CONFLICT_UNRECONCILED`) | **11 of 12 BYPASSED `DB-002`** and reached bridge execution (`RECEIVE_GOODS`, `RECORD_MILLING_BATCH`, etc.) | **FAIL (CRITICAL)** | `P1.5-001` |
| 2 | Live router call-site check on `purchasing.py:520` (`RECEIVE_GOODS`) & `v2_erp.py:1146` (`RECORD_MILLING_BATCH`) | Blocked because both mutate `RawMaterials` (conflicting core table) | Both pass non-empty `invalidate_tabs` omitting `RawMaterials` and **actively bypass `DB-002`** | **FAIL (CRITICAL)** | `P1.5-001` |
| 3 | `CREATE_SALARY_INCENTIVE` (`target_tab="SalaryIncentives"`, `locked_prefix="SAL"`) ID validation via `_validate_id_format()` | Canonical prefix passes validation | Returns `False` for `SAL-000001`, `INC-000001`, AND `SINC-000001` (**100% deadlock**) | **FAIL (HIGH)** | `P1.5-002` |
| 4 | `SalaryReceipts` (`RCPT` collision) enforcement during `RECORD_WORKFORCE_PAYMENT` | Collision policy enforced on child `SalaryReceipts` IDs | `AppsScriptBridge` only checks `if effective_locked_prefix:` on top-level `allocated_id`; `SalaryReceipts` collision rule is **dead code at runtime** | **FAIL (HIGH)** | `P1.5-002` |
| 5 | `approve_core_schema_reconciliation("Customers", headers=["totally_fake_column"], approved_by="USR-OWNER-001")` | Reject invalid header list missing required `Customers` columns | **Succeeded**; `get_schema_write_block_reason("Customers")` returned `None` (**unlocked with 1 fake column**) | **FAIL (MEDIUM)** | `P1.5-005` |
| 6 | Auth probe: missing `Authorization` header | `401 Unauthorized` | `401 Unauthorized` | **PASS** | — |
| 7 | Auth probe: invalid/malformed JWT | `401 Unauthorized` | `401 Unauthorized` | **PASS** | — |
| 8 | Auth probe: valid JWT with active user | `ALLOW` | `ALLOW` | **PASS** | — |
| 9 | Auth probe: expired JWT (`exp` in past) | `401 Unauthorized` | `ALLOW` under stdlib mock `jwt` (mock ignores `exp`; real `PyJWT` absent in container) | **UNVERIFIED (ENV GAP)** | `P1.5-009` |
| 10 | Auth probe: `revoke_token()` with unconfigured bridge + in-memory cache check | Reject or fail closed if persistence fails | `revoke_token()` returned `False`; in-memory check returned `401` on same process only | **PARTIAL / RISK** | `P1.5-003` |
| 11 | Auth probe: `is_token_revoked()` when `db.get_records("RevokedTokens", fresh=False)` raises `RuntimeError` | Fail closed (`True` / `503`) | Caught `except Exception: pass` and returned **`False` (`ALLOW` — FAIL-OPEN)** | **FAIL (HIGH)** | `P1.5-003` |
| 12 | Auth probe: deactivated user `active="0"` in `get_current_user` vs. `routers/auth.py:101` | Consistent rejection for `"false"`, `"0"`, `"no"` | `get_current_user` returns `401`, but `routers/auth.py:101` login only checks `== "false"` | **FAIL (HIGH)** | `P1.5-003` |
| 13 | RBAC probe: `require_owner(FIELD_SALESMAN)` | `403 Forbidden` | `403 Forbidden` | **PASS** | — |
| 14 | Connectivity guard probe: `require_sheets_connection()` with empty `SALES_GOOGLE_SPREADSHEET_ID` and `db.is_connected == False` | Fail closed if disconnected | Returned **`True`** (fail-open in non-prod; mitigated in prod by `assert_runtime_config()`) | **FAIL (LOW)** | `P1.5-009` |

---

## 7. Frontend TypeScript Lint & Production Build Reproduction

Executed cleanly from workspace root without modifying any source files or dependencies:

### 7.1 `npm run lint` (`tsc --noEmit`)
- **Command:** `npm run lint`
- **Result:** Exit Code `0` (0 TypeScript errors)
- **Status:** **PASS**

### 7.2 `npm run build` (`tsc && vite build`)
- **Command:** `npm run build`
- **Observed Output:**
  - `vite v6.4.5 building for production...`
  - `✓ 2325 modules transformed.`
  - `dist/index.html` (`1.30 kB | gzip: 0.53 kB`) + 36 asset chunks emitted cleanly
  - `✓ built in 17.83s`
- **Result:** Exit Code `0`
- **Status:** **PASS**

### 7.3 Frontend Runtime/Contract Findings (Static Verification)
Although TypeScript compilation and Vite bundling pass cleanly, static cross-layer contract audit uncovered two functional UI defects (`P1.5-006`):
- `src/services/api.ts:677` and `src/views/ErpOperationsHubView.tsx:294` expect `errorCode === 'BLOCKED_PENDING_OWNER_SETUP'` or `detailObj?.workflow_status`, whereas `backend/app/apps_script_bridge.py:970-973` returns `detail.status = "BLOCKED_PENDING_OWNER_SETUP"` and `detail.error_code = "CORE_SCHEMA_CONFLICT_UNRECONCILED"` (causing blocked-schema responses to fall through to generic `NOT_SAVED`).
- `ErpOperationsHubView.tsx:1522-1528` renders green `VERIFIED_CORE` badges for Group `02` (`Suppliers`) and Group `10` (`Expenses`) because `schema_registry.py:563, 638` classifies those groups as `"VERIFIED_CORE"` despite containing write-blocked conflicting tables, and omits `unmapped_workbook_tabs_remaining` (`164`) and `write_blocked_schema_tabs_count` (`36`) from top summary cards.

---

## 8. External Artifact Discovery Scan (Reproduced)

Repository-wide filesystem and code search confirmed that all three external Phase 1 blockers remain genuinely absent from the workspace:

- `XLSX_FILES = []` (no `.xlsx` workbook in workspace)
- `GS_FILES = ['docs/workforceDiagnosticReport.gs', 'docs/workforceMigration.gs', 'docs/workforceSchemaUpgrade_2026-11-03-v1.gs']` (workforce migration utilities only; **no** `WebAppBridge.gs` or `doPost` writer)
- `CODE_MATCHES['WebAppBridge'] = []`
- `CODE_MATCHES['function doPost'] = []`
- `CODE_MATCHES['DBV5_FIELD_DICTIONARY_3074'] = ['backend/app/schema_registry.py']` (referenced only as a metadata note string; dictionary file absent)

---

## 9. Verification Verdict Summary

| Verification Domain | Status | Notes |
|---|---|---|
| Isolated Environment Check | **PASS** | All live env vars unset; service account file absent |
| Python Compilation (`py_compile`) | **PASS** | `112/112` files clean |
| Frontend `npm run lint` & `npm run build` | **PASS** | `tsc --noEmit` & `vite build` (`2325` modules, `17.83s`) |
| `test_phase1_database_schema_guards` | **PASS (INCOMPLETE COVERAGE)** | `8/8` pass, but missed `P1.5-001`, `P1.5-002`, `P1.5-005` |
| Full Backend Suite (`50` files) | **8 PASS / 42 LEGACY V2.1 FAIL** | `59/59` passing tests; `0` Phase 1 regressions; `42` pre-existing v2.1 contract drift |
| Live Security & Bypass Probes | **FAIL** | **1 CRITICAL (`P1.5-001`) + 3 HIGH (`P1.5-002`–`P1.5-004`) + 4 MEDIUM + 1 LOW** |
| External Artifact Availability | **BLOCKED** | `DB-003`, `DB-007`, `DB-008` remain absent |
