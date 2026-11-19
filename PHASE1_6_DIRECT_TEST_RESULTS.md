# Kawad Swad ERP — Phase 1.6 Direct Test & Build Verification Results

## 1. Test Environment & Isolation Checks

- **Working Directory:** `/app/applet`
- **Python Environment:** Python 3.12 (`SALES_TESTING=1`, `SALES_ENV=development`, `PYTHONPATH=backend`)
- **Node / Frontend Tooling:** Node + `tsx` + TypeScript `tsc --noEmit` + Vite `6.4.5`
- **Live Credentials / Env Vars Check:**
  - `LIVE_ENV_SET = []` (0 of 12 live/production variables configured)
  - `/etc/secrets/sales-service-account.json` exists: `False`
  - Network calls to live Google Sheets, Apps Script, or Render: **0**

---

## 2. Backend Syntax Compilation

```bash
python3 -m compileall -q backend/app backend/scripts backend/tests && echo "PY_COMPILE_OK"
```
- **Result:** `PY_COMPILE_OK` (exit code `0`)

---

## 3. Targeted, Security & Regression Backend Suites (9 Passing Suites — 91/91 Tests Passed)

```bash
SALES_TESTING=1 SALES_ENV=development PYTHONPATH=backend python3 -m unittest \
  tests.test_alias_adapter \
  tests.test_cors_preflight \
  tests.test_health_diagnostics_security_and_quota \
  tests.test_owner_setup \
  tests.test_phase1_database_schema_guards \
  tests.test_phase1_6_targeted_repairs \
  tests.test_production_backend_routing \
  tests.test_sheets_quota_handling \
  tests.test_workforce_migration_safety
```

| Suite | Category | Tests Run | Passed | Failed | Errors | Status |
|---|---|---:|---:|---:|---:|---|
| `tests.test_phase1_6_targeted_repairs` *(NEW)* | Phase 1.6 Direct Repair + Adversarial Security | 32 | 32 | 0 | 0 | **PASS** |
| `tests.test_phase1_database_schema_guards` *(UPDATED)* | Phase 1 Schema & Reconciliation Guards | 8 | 8 | 0 | 0 | **PASS** |
| `tests.test_workforce_migration_safety` | Migration & Rollback Safety | 21 | 21 | 0 | 0 | **PASS** |
| `tests.test_cors_preflight` | CORS & Preflight Security | 8 | 8 | 0 | 0 | **PASS** |
| `tests.test_health_diagnostics_security_and_quota` | Health, Diagnostics & Quota Security | 8 | 8 | 0 | 0 | **PASS** |
| `tests.test_alias_adapter` | Alias Adapter Compatibility | 5 | 5 | 0 | 0 | **PASS** |
| `tests.test_production_backend_routing` | Production Routing Guard | 5 | 5 | 0 | 0 | **PASS** |
| `tests.test_sheets_quota_handling` | Sheets Quota & Cache Resilience | 3 | 3 | 0 | 0 | **PASS** |
| `tests.test_owner_setup` | Owner Setup Guard | 1 | 1 | 0 | 0 | **PASS** |
| **Total Isolated Passing Suites** | **9 suites** | **91** | **91** | **0** | **0** | **OK (1.466s)** |

---

## 4. Full 51-File Backend Test Sweep — Evidence-Based Failure Categorization (Stage D)

All **51** test files under `backend/tests/test_*.py` were executed individually in isolated subprocesses.
- **Passed:** `9/51` files (`91` tests)
- **Failed:** `42/51` files (all investigated and categorized below; **0 new regressions** introduced by Phase 1.6; **0 legacy tests weakened or deleted**)
- **Skipped:** `0`

### Evidence-Based Categorization of the 42 Failing Legacy Test Files

| Category | Count | Root Cause (Verified from Actual Stderr/Traceback) | Affected Test Files |
|---|---:|---|---|
| **Cat A — Pre-v2.1 Endpoint Signature Incompatibility** | **28** | Pre-v2.1 tests invoke router coroutine functions directly with old positional arguments without the v2.1 `request: Request` parameter (added when v2.1 introduced `X-KS-Idempotency-Key` nonce extraction), producing `TypeError: ... missing 1 required positional argument: 'request'` or `AttributeError: 'function' object has no attribute 'get'` (when `Depends(...)` default is bound to a positional arg). | `test_attendance_and_workflow`, `test_buyer_info_optional`, `test_daily_operations_readiness`, `test_dal_milling_stage2`, `test_duplicate_sale_idempotency`, `test_erp_full_lifecycle`, `test_erp_stabilization`, `test_finished_goods_inventory`, `test_integrity`, `test_live_audit_fixes`, `test_master_repair_and_readiness`, `test_multi_batch_costing`, `test_phase1_4_1_sales_payment`, `test_phase1_4_sales_payment`, `test_phase1_fixes`, `test_phase4_clean_data_contracts`, `test_product_activation`, `test_production_and_attendance_v2`, `test_production_module`, `test_raw_material_issuance_recovery`, `test_raw_material_receiving_stage1`, `test_recipe_master_v2`, `test_stabilization_upgrade`, `test_stage1_comprehensive_verification`, `test_stage1_failure_injection`, `test_stock_discrepancy_idempotency`, `test_supplier_payment_integrity`, `test_workforce_management` |
| **Cat B — Pre-v2.1 Tests Expecting Live/Unblocked Bridge Writes** | **9** | Pre-v2.1 tests assert successful local writes without mocking the v2.1 Apps Script bridge or reconciling conflicting core schemas, so they now correctly receive `HTTP 503 BLOCKED_PENDING_OWNER_SETUP` (`APPS_SCRIPT_BRIDGE_UNCONFIGURED` or `CORE_SCHEMA_CONFLICT_UNRECONCILED`). | `test_accounting_integrity`, `test_audit_fixes_regression`, `test_audit_reconciliation`, `test_double_entry_accounting`, `test_master_stage3_production_safety`, `test_phase1_4_1_failure_injection`, `test_phase2a_van_loading`, `test_production_corrections`, `test_user_system_phase2` |
| **Cat C — Legacy Direct-Sheets Write Tests Blocked by Single-Write-Owner** | **4** | Pre-v2.1 tests call `db.append_record()` directly with `allow_in_memory_fallback=False` or disconnected live-sheet assertions and now correctly hit `RuntimeError: BLOCKED_PENDING_OWNER_SETUP: Direct Google Sheets mutation 'append_record' ... is disabled under Blueprint v2.1 Single-Write-Owner`. | `test_master_plan_phase1_integrity`, `test_startup_port_bind_and_resilience`, `test_storage_connectivity_protection`, `test_update_sheets_recipe_master` |
| **Cat D — Removed Pre-v2.1 Private Helper** | **1** | References removed pre-v2.1 private function `app.routers.approvals._run_request`. | `test_phase4_2a_security_guards` |

**Assessment:** All 42 failures are genuine pre-v2.1 architectural incompatibilities (outdated direct-write/positional-arg test harnesses written before Blueprint v2.1 Single-Write-Owner). None are Phase 1.6 regressions, and none were weakened or removed.

---

## 5. Frontend Contract Tests, Lint & Build Results (Stage E)

### A. Frontend Contract Tests (`14/14` Passed)
```bash
npx tsx scripts/test_phase1_6_frontend_contracts.ts
```
- **Passed:** `14/14` (`VERIFIED`, `BLOCKED`, `CONFLICT`, `UNKNOWN`, `PENDING OWNER SETUP`, `401`, `403`, `409`, `422`, `503`, `Unknown API error`, `Write blocked`, `Loading state`, `Retry state`)
- **Failed:** `0`

### B. TypeScript Lint / Typecheck
```bash
npm run lint   # runs: tsc --noEmit
```
- **Result:** PASS (`0` TypeScript errors, exit code `0`)

### C. Production Build
```bash
npm run build  # runs: tsc && vite build
```
- **Result:** PASS (`2,325` modules transformed, production bundle compiled cleanly)

---

## 6. Missing Dependencies / Limitations / Blocked Checks

- **Python Test Runtime Note:** This isolated container runs with the stdlib FastAPI/Pydantic/JWT fallback shims in `backend/tests/__init__.py` (upgraded in `P1.5-009` so mock JWT enforces HMAC-SHA256 signatures and `exp` expiration). Full real-`fastapi`/`starlette`/`PyJWT` runtime verification should also be confirmed in a full virtualenv during Phase 1.7.
- **Blocked Live Integration Checks (Intentional):** Live Google Sheets Row-1 header verification (`DB-007`), full 255-tab workbook validation (`DB-003`), and live Apps Script `WebAppBridge.gs`/`doPost` execution (`DB-008`) were **NOT RUN** (prohibited by local-only safety rules and missing external artifacts).
