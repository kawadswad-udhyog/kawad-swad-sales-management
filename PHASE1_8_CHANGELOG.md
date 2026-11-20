# Kawad Swad ERP — Phase 1.8 Detailed Changelog

## 1. Production Backend Source Changes (`backend/app/`) — 9 Files Modified

| File | Defect IDs | Summary of Change |
|---|---|---|
| `backend/app/sheets.py` | `P1.8-001` | Added `get_verified_tab_headers()` to verify authoritative Row-1 headers and identifier column presence before accepting empty tables during duplicate-ID preflight; preserved strictly `spreadsheets.readonly` OAuth scope and Single-Write-Owner direct-write blocks. |
| `backend/app/apps_script_bridge.py` | `P1.8-001` | Replaced fail-open duplicate-ID lookup with `_check_id_exists_authoritative()` enforcing `fresh=True`, Row-1 header/ID-column verification, strict non-malformed list/dict checks, fail-closed HTTP `503` with zero remote HTTP calls on any storage outage, and atomic `_INFLIGHT_ID_LOCK` / `_INFLIGHT_IDS` in-process reservation with `finally` cleanup. |
| `backend/app/accounting/journal_engine.py` | `P1.8-002`, `P1.8-003` | Restored required return fields (`journal_id`, `reference_type`, `reference_id`, `total_debit`, `total_credit`, `status`) on `reverse_journal_voucher`; fixed `**bridge_res` spread in `post_journal_voucher` and `reverse_journal_voucher` so bridge status `'CONFIRMED'` never overwrites domain status `'POSTED'`. |
| `backend/app/accounting/customer_ledger.py` | `P1.8-005` | Added unique `-{uuid.uuid4().hex[:8]}` nonce suffix to credit-approval reserve and release CAS governed writes (lines 975, 1151) to prevent stale nonce replay on re-reserve after release. |
| `backend/app/routers/customers.py` | `P1.8-004` | Normalized blank `city=""` to default `"Bhilwara"` (line 62). |
| `backend/app/routers/production.py` | `P1.8-006`, `P1.8-014` | Guarded `post_packaging_batch_journal` with `if total_fin_cost > Decimal("0"):` (line 3937); added fail-closed post-write fresh readback verification (HTTP `503` if newly committed `RawMaterialLedger` row is missing) to `receive_raw_material` and `record_dal_milling_batch`; hardened `IncompleteTransactions` conflict check in `receive_raw_material` to also match invoice `line_key` (`INV:{invoice}:L:{line}`) across fresh idempotency keys. |
| `backend/app/routers/purchasing.py` | `P1.8-012`, `P1.8-013` | Fixed `record_supplier_payment` `PAID` replay to verify and recover missing accounting journals after transient `JournalHeaders` outages (lines 866–879); fixed `INCOMPLETE` supplier payment crash recovery via `APPLY_SUPPLIER_ADVANCE` (`requires_allocated_id=False`), reusing `payment_id` and skipping duplicate `SupplierBills` deduction when `[spay:{id}]` marker exists (lines 954–1035). |
| `backend/app/routers/stock.py` | `P1.8-007`, `P1.8-011` | Preserved domain `"status"` values over bridge `"CONFIRMED"` transport status (lines 290, 460); hardened `review_stock_discrepancy` (lines 434–490) with idempotent audit pre-check, embedded `audit_event`, and fail-closed HTTP `503` on `AuditLog` write outages. |
| `backend/app/routers/quality.py` | `P1.8-007` | Preserved domain `"status"` value over bridge `"CONFIRMED"` transport status (line 564). |
| `backend/app/routers/workforce.py` | `P1.8-008`, `P1.8-009`, `P1.8-010` | Propagated Apps-Script-allocated `item_id` values onto returned payroll items in `calculate_payroll_run` (lines 1384–1396); propagated posted `journal_ref` onto `saved_payment["accounting_journal_ref"]` (line 1674) and persisted `receipt_id`/`receipt_number` onto returned `"receipt"` in `record_workforce_payment` (lines 1686–1710). |

*(Note: 10 backend production files total: `sheets.py`, `apps_script_bridge.py`, `journal_engine.py`, `customer_ledger.py`, `customers.py`, `production.py`, `purchasing.py`, `stock.py`, `quality.py`, `workforce.py`.)*

---

## 2. New Backend Security & Harness Files Added (`backend/tests/`) — 2 Files Created

| File | Purpose |
|---|---|
| `backend/tests/test_phase1_8_duplicate_id_security.py` | 8 dedicated adversarial security regression tests proving fail-closed duplicate-ID enforcement across outages (`timeout`, `429`, `500`, `503`, `401`), malformed payloads, stale cache bypass prevention (`fresh=True`), Row-1 header verification, legitimate empty table handling, cross-table/child outages, zero remote bridge HTTP calls on failure, and in-process concurrent write serialization. |
| `backend/tests/v2_test_harness.py` | Shared Blueprint v2.1 Single-Write-Owner `LocalAppsScriptSimulator` and `Request` injection test harness supporting atomic multi-tab writes, `_append_row_honoring_patch()` failure-injection fidelity, multiprocess locking, `CREATE_PRODUCTION_BATCH`, `RESOLVE_LEGACY_BATCH_COST`, `IncompleteTransactions` intent/recovery, and `CREATE_SALE`/`RESUME_SALE` without disabling any production guard. |

---

## 3. Modernized Backend Test Suites (`backend/tests/`) — 42 Pre-v2.1 Test Files Updated

All 42 pre-v2.1 failing backend test files were wired to the V2.1 `LocalAppsScriptSimulator` + `Request` injection harness (zero tests deleted, zero tests skipped, zero production guards weakened):
- `test_accounting_integrity.py`, `test_attendance_and_workflow.py`, `test_audit_fixes_regression.py`, `test_audit_reconciliation.py`, `test_buyer_info_optional.py`, `test_daily_operations_readiness.py`, `test_dal_milling_stage2.py`, `test_double_entry_accounting.py`, `test_duplicate_sale_idempotency.py`, `test_erp_full_lifecycle.py`, `test_erp_stabilization.py`, `test_finished_goods_inventory.py`, `test_integrity.py`, `test_live_audit_fixes.py`, `test_master_plan_phase1_integrity.py`, `test_master_repair_and_readiness.py`, `test_master_stage3_production_safety.py`, `test_multi_batch_costing.py`, `test_phase1_4_1_failure_injection.py`, `test_phase1_4_1_sales_payment.py`, `test_phase1_4_sales_payment.py`, `test_phase1_fixes.py`, `test_phase2a_van_loading.py`, `test_phase4_2a_security_guards.py`, `test_phase4_clean_data_contracts.py`, `test_product_activation.py`, `test_production_and_attendance_v2.py`, `test_production_corrections.py`, `test_production_module.py`, `test_raw_material_issuance_recovery.py`, `test_raw_material_receiving_stage1.py`, `test_recipe_master_v2.py`, `test_stabilization_upgrade.py`, `test_stage1_comprehensive_verification.py`, `test_stage1_failure_injection.py`, `test_startup_port_bind_and_resilience.py`, `test_stock_discrepancy_idempotency.py`, `test_storage_connectivity_protection.py`, `test_supplier_payment_integrity.py`, `test_update_sheets_recipe_master.py`, `test_user_system_phase2.py`, `test_workforce_management.py`.

---

## 4. Frontend & Configuration Files
- **Frontend (`src/`, `scripts/`, `package.json`, lockfile):** Zero modifications required; TypeScript typecheck (`tsc --noEmit`), `npm run lint`, all `14/14` frontend contract tests, and Vite production build (`npm run build`) all verified PASS cleanly on the existing repaired source.

---

## 5. Phase 1.8 Audit Deliverables Created (Workspace Root `/`)
1. `PHASE1_8_CODE_CORRECTION_REPORT.md`
2. `PHASE1_8_FAILURE_INVENTORY.csv`
3. `PHASE1_8_REPAIR_MATRIX.csv`
4. `PHASE1_8_FULL_TEST_RESULTS.md`
5. `PHASE1_8_SECURITY_REAUDIT.md`
6. `PHASE1_8_FRONTEND_VERIFICATION.md`
7. `PHASE1_8_DATABASE_BLOCKERS.md`
8. `PHASE1_8_CHANGELOG.md`
9. `PHASE1_8_FINAL_GATE.md`
10. `PHASE1_8_REPRODUCTION_COMMANDS.txt`
