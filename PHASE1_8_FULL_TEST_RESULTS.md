# Kawad Swad ERP — Phase 1.8 Full Test Results

## 1. Execution Environment & Local Isolation

- **Working Directory:** `/app/applet`
- **Python Runtime:** `Python 3.11.2` (`SALES_TESTING=1`, `SALES_ENV=development`, `PYTHONPATH=backend`)
- **Node / Frontend Runtime:** `Node v22.23.2`, `npm 10.9.8`, TypeScript (`tsc --noEmit`), Vite `6.4.5`
- **Live System Isolation Check:**
  - `GOOGLE_SHEETS_SPREADSHEET_ID`: `False` (unset)
  - `GOOGLE_SERVICE_ACCOUNT_JSON`: `False` (unset)
  - `APPS_SCRIPT_WEBAPP_URL`: `False` (unset)
  - `APPS_SCRIPT_SHARED_SECRET`: `False` (unset)
  - `/etc/secrets/sales-service-account.json` exists: `False`
  - Live Google Sheets / Apps Script / Render calls made: **0**

---

## 2. Executive Verification Matrix (Baseline vs. Post-Repair)

| Metric | Phase 1.8 Starting Baseline | Phase 1.8 Final Actual Result |
|---|---:|---:|
| Backend test files discovered | 51 | **52** (+1 new `test_phase1_8_duplicate_id_security.py`) |
| Total backend tests discovered | 561 | **569** (+8 adversarial duplicate-ID security tests) |
| Backend tests passed | 203 | **568** |
| Backend tests failed | 25 | **0** |
| Backend tests errored | 332 | **0** |
| Backend tests skipped | 1 | **1** *(pre-existing `@unittest.skipUnless` for real `uvicorn`)* |
| Backend Python compilation (`compileall`) | PASS | **PASS** (exit code `0`) |
| Backend full discovery duration | — | **17.575s** (`OK (skipped=1)`, exit code `0`) |
| Security re-audit suites (6 suites) | — | **72/72 PASS** (`1.292s`, exit code `0`) |
| Concurrency determinism (6 suites × 3 runs) | — | **116/116 PASS × 3 consecutive runs** (`6.105s`, `5.605s`, `4.339s`) |
| Frontend TypeScript typecheck (`npx tsc --noEmit`) | Unverified | **PASS** (0 errors, exit code `0`) |
| Frontend lint (`npm run lint`) | Unverified | **PASS** (0 errors, exit code `0`) |
| Frontend contract tests (`test_phase1_6_frontend_contracts.ts`) | Unverified | **14/14 PASS** (exit code `0`) |
| Frontend production build (`npm run build`) | Unverified | **PASS** (`2,325 modules`, `14.84s`, exit code `0`) |

---

## 3. Exact Full Backend Unittest Discovery Output

```bash
python3 -m compileall -q backend/app backend/scripts backend/tests && \
SALES_TESTING=1 SALES_ENV=development PYTHONPATH=backend python3 -m unittest discover -s backend/tests -p "test_*.py" -t backend -v
```

**Final Summary Line (verbatim):**
```text
Ran 569 tests in 17.575s

OK (skipped=1)
```

### Single Skipped Test (Pre-Existing Environment Guard)
- **File:** `backend/tests/test_startup_port_bind_and_resilience.py:398`
- **Test:** `TestStartupPortBindAndResilience.test_uvicorn_binds_and_serves_health_within_3s_when_sheets_hangs_over_5s`
- **Skip Reason:** `@unittest.skipUnless(_has_real_uvicorn_and_fastapi(), "Requires real uvicorn and fastapi packages")`
- **Verification:** Confirmed via static scan across all 52 `backend/tests/test_*.py` files that this is the **sole** skip declaration in the repository. No test was skipped or deleted during Phase 1.8.

---

## 4. Complete Per-File Backend Test Breakdown (All 52 Modules)

| # | Test Module | Tests | Passed | Failed | Errors | Skipped | Status |
|---:|---|---:|---:|---:|---:|---:|---|
| 1 | `tests.test_accounting_integrity` | 11 | 11 | 0 | 0 | 0 | PASS |
| 2 | `tests.test_alias_adapter` | 5 | 5 | 0 | 0 | 0 | PASS |
| 3 | `tests.test_attendance_and_workflow` | 8 | 8 | 0 | 0 | 0 | PASS |
| 4 | `tests.test_audit_fixes_regression` | 6 | 6 | 0 | 0 | 0 | PASS |
| 5 | `tests.test_audit_reconciliation` | 18 | 18 | 0 | 0 | 0 | PASS |
| 6 | `tests.test_buyer_info_optional` | 12 | 12 | 0 | 0 | 0 | PASS |
| 7 | `tests.test_cors_preflight` | 8 | 8 | 0 | 0 | 0 | PASS |
| 8 | `tests.test_daily_operations_readiness` | 22 | 22 | 0 | 0 | 0 | PASS |
| 9 | `tests.test_dal_milling_stage2` | 6 | 6 | 0 | 0 | 0 | PASS |
| 10 | `tests.test_double_entry_accounting` | 13 | 13 | 0 | 0 | 0 | PASS |
| 11 | `tests.test_duplicate_sale_idempotency` | 4 | 4 | 0 | 0 | 0 | PASS |
| 12 | `tests.test_erp_full_lifecycle` | 7 | 7 | 0 | 0 | 0 | PASS |
| 13 | `tests.test_erp_stabilization` | 7 | 7 | 0 | 0 | 0 | PASS |
| 14 | `tests.test_finished_goods_inventory` | 4 | 4 | 0 | 0 | 0 | PASS |
| 15 | `tests.test_health_diagnostics_security_and_quota` | 8 | 8 | 0 | 0 | 0 | PASS |
| 16 | `tests.test_integrity` | 7 | 7 | 0 | 0 | 0 | PASS |
| 17 | `tests.test_live_audit_fixes` | 6 | 6 | 0 | 0 | 0 | PASS |
| 18 | `tests.test_master_plan_phase1_integrity` | 4 | 4 | 0 | 0 | 0 | PASS |
| 19 | `tests.test_master_repair_and_readiness` | 9 | 9 | 0 | 0 | 0 | PASS |
| 20 | `tests.test_master_stage3_production_safety` | 8 | 8 | 0 | 0 | 0 | PASS |
| 21 | `tests.test_multi_batch_costing` | 10 | 10 | 0 | 0 | 0 | PASS |
| 22 | `tests.test_owner_setup` | 1 | 1 | 0 | 0 | 0 | PASS |
| 23 | `tests.test_phase1_4_1_failure_injection` | 40 | 40 | 0 | 0 | 0 | PASS |
| 24 | `tests.test_phase1_4_1_sales_payment` | 15 | 15 | 0 | 0 | 0 | PASS |
| 25 | `tests.test_phase1_4_sales_payment` | 14 | 14 | 0 | 0 | 0 | PASS |
| 26 | `tests.test_phase1_6_targeted_repairs` | 32 | 32 | 0 | 0 | 0 | PASS |
| 27 | `tests.test_phase1_8_duplicate_id_security` *(NEW)* | 8 | 8 | 0 | 0 | 0 | PASS |
| 28 | `tests.test_phase1_database_schema_guards` | 8 | 8 | 0 | 0 | 0 | PASS |
| 29 | `tests.test_phase1_fixes` | 7 | 7 | 0 | 0 | 0 | PASS |
| 30 | `tests.test_phase2a_van_loading` | 24 | 24 | 0 | 0 | 0 | PASS |
| 31 | `tests.test_phase4_2a_security_guards` | 12 | 12 | 0 | 0 | 0 | PASS |
| 32 | `tests.test_phase4_clean_data_contracts` | 17 | 17 | 0 | 0 | 0 | PASS |
| 33 | `tests.test_product_activation` | 4 | 4 | 0 | 0 | 0 | PASS |
| 34 | `tests.test_production_and_attendance_v2` | 7 | 7 | 0 | 0 | 0 | PASS |
| 35 | `tests.test_production_backend_routing` | 5 | 5 | 0 | 0 | 0 | PASS |
| 36 | `tests.test_production_corrections` | 26 | 26 | 0 | 0 | 0 | PASS |
| 37 | `tests.test_production_module` | 2 | 2 | 0 | 0 | 0 | PASS |
| 38 | `tests.test_raw_material_issuance_recovery` | 11 | 11 | 0 | 0 | 0 | PASS |
| 39 | `tests.test_raw_material_receiving_stage1` | 15 | 15 | 0 | 0 | 0 | PASS |
| 40 | `tests.test_recipe_master_v2` | 7 | 7 | 0 | 0 | 0 | PASS |
| 41 | `tests.test_sheets_quota_handling` | 3 | 3 | 0 | 0 | 0 | PASS |
| 42 | `tests.test_stabilization_upgrade` | 10 | 10 | 0 | 0 | 0 | PASS |
| 43 | `tests.test_stage1_comprehensive_verification` | 7 | 7 | 0 | 0 | 0 | PASS |
| 44 | `tests.test_stage1_failure_injection` | 4 | 4 | 0 | 0 | 0 | PASS |
| 45 | `tests.test_startup_port_bind_and_resilience` | 9 | 8 | 0 | 0 | 1 | PASS (1 expected skip) |
| 46 | `tests.test_stock_discrepancy_idempotency` | 14 | 14 | 0 | 0 | 0 | PASS |
| 47 | `tests.test_storage_connectivity_protection` | 4 | 4 | 0 | 0 | 0 | PASS |
| 48 | `tests.test_supplier_payment_integrity` | 31 | 31 | 0 | 0 | 0 | PASS |
| 49 | `tests.test_update_sheets_recipe_master` | 1 | 1 | 0 | 0 | 0 | PASS |
| 50 | `tests.test_user_system_phase2` | 12 | 12 | 0 | 0 | 0 | PASS |
| 51 | `tests.test_workforce_management` | 15 | 15 | 0 | 0 | 0 | PASS |
| 52 | `tests.test_workforce_migration_safety` | 21 | 21 | 0 | 0 | 0 | PASS |
| **TOTAL** | **52 Modules** | **569** | **568** | **0** | **0** | **1** | **OK** |

---

## 5. Dedicated Security & Concurrency Determinism Runs

### A. Security Re-Audit Bundle (`72/72 PASS` in `1.292s`)
- `tests.test_phase1_6_targeted_repairs` (32 tests)
- `tests.test_phase1_8_duplicate_id_security` (8 tests)
- `tests.test_phase4_2a_security_guards` (12 tests)
- `tests.test_phase1_database_schema_guards` (8 tests)
- `tests.test_health_diagnostics_security_and_quota` (8 tests)
- `tests.test_master_plan_phase1_integrity` (4 tests)

### B. Concurrency & Failure-Injection Determinism (3 Consecutive Runs — `116/116 PASS` × 3)
Executed 3 back-to-back runs of:
- `tests.test_phase1_8_duplicate_id_security` (8)
- `tests.test_attendance_and_workflow` (8)
- `tests.test_phase1_4_1_failure_injection` (40)
- `tests.test_phase2a_van_loading` (24)
- `tests.test_stock_discrepancy_idempotency` (14)
- `tests.test_daily_operations_readiness` (22)

- **Run 1:** `Ran 116 tests in 6.105s — OK`
- **Run 2:** `Ran 116 tests in 5.605s — OK`
- **Run 3:** `Ran 116 tests in 4.339s — OK`

---

## 6. Standalone Legacy Script Note (Non-Test Utility)
- `backend/tests/verify_acceptance_and_reconciliation.py` is a manual pre-v2.1 standalone walkthrough script (not matched by `test_*.py` discovery). When executed directly it currently fails at line 191 (`TypeError: receive_raw_material() missing 1 required positional argument: 'request'`) because it invokes routes directly without a `Request` object. It is documented honestly here and was not silently deleted.
