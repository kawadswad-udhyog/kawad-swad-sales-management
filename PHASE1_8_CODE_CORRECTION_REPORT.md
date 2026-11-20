# Kawad Swad ERP — Phase 1.8 Code Correction Report

## 1. Executive Summary
Phase 1.8 completed full local regression repair, duplicate-ID security hardening, and stabilization across the entire Kawad Swad ERP repository without weakening a single production security guard, without removing `request: Request` parameters, without bypassing Single-Write-Owner, without touching any live system, and without deleting or skipping tests.

- **Starting Baseline:** `561` discovered backend tests across `51` test files -> `203` passed, `25` failed, `332` errors, `1` skipped (`357` failing/errored tests).
- **Final Local Result:** **`569` discovered backend tests across `52` test files -> `568` passed, `0` failed, `0` errors, `1` skipped** (the pre-existing `@unittest.skipUnless` for real `uvicorn` in `test_startup_port_bind_and_resilience.py`).
- **Genuine Production Bugs Found & Fixed:** **14** distinct production defects (`P1.8-001` through `P1.8-014`), including the **CRITICAL** duplicate-ID fail-open vulnerability (`P1.8-001`).
- **Frontend Verification:** `npx tsc --noEmit` PASS, `npm run lint` PASS, `14/14` frontend contract tests PASS, `npm run build` PASS (`2,325` modules transformed in `14.84s`).
- **Honest Final Gate:** **`🟡 PHASE 1 CODE-STABLE, EXTERNAL GATES OPEN`** — external authoritative artifacts `DB-003`, `DB-007`, and `DB-008` remain missing and MUST be supplied and audited before Phase 1 can be declared complete or Phase 2 can begin.

---

## 2. Baseline vs. Post-Repair Comparison

| Area | Baseline | Post-Phase 1.8 |
|---|---:|---:|
| Backend Test Modules | 51 (9 pass / 42 failing) | **52 (52 pass / 0 failing)** |
| Total Backend Tests | 561 | **569** (+8 new security tests) |
| Passed | 203 | **568** |
| Failed | 25 | **0** |
| Errors | 332 | **0** |
| Skipped | 1 (uvicorn) | **1** (same pre-existing uvicorn check) |
| Security Re-Audit Bundle (6 suites) | Incomplete | **72/72 PASS** |
| Concurrency Determinism (6 suites × 3 runs) | Unverified | **116/116 PASS × 3 runs** |
| Frontend Typecheck / Lint / Contracts / Build | Unverified | **ALL PASS (14/14 contracts, 0 errors)** |

---

## 3. All 14 Genuine Production Code Defects Found & Repaired

Every failing/errored test across all 42 failing baseline suites was investigated individually. Behind the pre-v2.1 test-harness incompatibilities, **14 genuine production defects** were uncovered and fixed directly in `backend/app/`:

1. **`P1.8-001` (CRITICAL — Duplicate-ID Lookup Fail-Open & Race Condition)**
   - **Files:** `backend/app/sheets.py`, `backend/app/apps_script_bridge.py`
   - **Root Cause:** Duplicate-ID preflight previously returned `False` on storage outages/timeouts/malformed responses, allowed stale cached reads, accepted empty rows without Row-1 header verification, and lacked in-process concurrency serialization.
   - **Fix:** Added `get_verified_tab_headers()` and `_check_id_exists_authoritative()` enforcing `fresh=True`, authoritative Row-1 ID-column validation, strict list/dict payload validation, fail-closed HTTP `503` with zero remote HTTP calls, and atomic `_INFLIGHT_ID_LOCK` / `_INFLIGHT_IDS` reservation with `finally` release.
   - **Regression Suite:** `backend/tests/test_phase1_8_duplicate_id_security.py` (8 adversarial tests, all passing).

2. **`P1.8-002` (HIGH — `reverse_journal_voucher` Missing Return Keys)**
   - **File:** `backend/app/accounting/journal_engine.py`
   - **Fix:** Restored required domain return fields (`journal_id`, `reference_type`, `reference_id`, `total_debit`, `total_credit`, `status`).

3. **`P1.8-003` (HIGH — Bridge Status Overwriting Domain Status `'POSTED'`)**
   - **File:** `backend/app/accounting/journal_engine.py`
   - **Fix:** Prevented `**bridge_res` spread in `post_journal_voucher` and `reverse_journal_voucher` from overwriting `"status": "POSTED"` with bridge transport status `"CONFIRMED"`.

4. **`P1.8-004` (MEDIUM — Blank Customer City Default Missing)**
   - **File:** `backend/app/routers/customers.py:62`
   - **Fix:** Normalized blank `city=""` to default `"Bhilwara"`.

5. **`P1.8-005` (HIGH — Credit Approval Reserve/Release CAS Nonce Collision)**
   - **File:** `backend/app/accounting/customer_ledger.py:975,1151`
   - **Fix:** Added unique `-{uuid.uuid4().hex[:8]}` nonce suffix on reserve/release CAS governed writes to eliminate stale nonce replay collisions when re-reserving after a release.

6. **`P1.8-006` (HIGH — Zero-Valuation Packaging Journal HTTP 500)**
   - **File:** `backend/app/routers/production.py:3937`
   - **Fix:** Guarded `post_packaging_batch_journal` with `if total_fin_cost > Decimal("0"):` when batch overhead/labour valuation is pending.

7. **`P1.8-007` (MEDIUM — Bridge Status Overwriting Domain Status in Stock & Quality)**
   - **Files:** `backend/app/routers/stock.py:290,460`, `backend/app/routers/quality.py:564`
   - **Fix:** Preserved domain `"status"` values over bridge `"CONFIRMED"` transport status.

8. **`P1.8-008` (HIGH — Payroll Run Missing Allocated `item_id`)**
   - **File:** `backend/app/routers/workforce.py:1384-1396`
   - **Fix:** Propagated Apps-Script-allocated `item_id` values onto returned payroll items from `calculate_payroll_run`.

9. **`P1.8-009` (HIGH — Workforce Payment Missing `accounting_journal_ref`)**
   - **File:** `backend/app/routers/workforce.py:1674`
   - **Fix:** Attached posted accounting journal reference onto `saved_payment["accounting_journal_ref"]`.

10. **`P1.8-010` (MEDIUM — Workforce Payment Missing Persisted Receipt Metadata)**
    - **File:** `backend/app/routers/workforce.py:1686-1710`
    - **Fix:** Included persisted `receipt_id` and `receipt_number` on the returned `"receipt"` payload.

11. **`P1.8-011` (HIGH — Stock Discrepancy Review Missing Fail-Closed Audit Trail)**
    - **File:** `backend/app/routers/stock.py:434-490`
    - **Fix:** Added idempotent audit pre-check, embedded `audit_event`, and fail-closed HTTP `503` when `AuditLog` write fails.

12. **`P1.8-012` (HIGH — Supplier Payment PAID Replay Skipping Missing Journal Recovery)**
    - **File:** `backend/app/routers/purchasing.py:866-879`
    - **Fix:** Verified posted journal existence before returning `is_replay=True` and recovered missing accounting journals after prior transient `JournalHeaders` outages.

13. **`P1.8-013` (HIGH — Supplier Payment INCOMPLETE Crash Recovery Duplicate Deduction Risk)**
    - **File:** `backend/app/routers/purchasing.py:954-1035`
    - **Fix:** Repaired INCOMPLETE supplier payment recovery via `APPLY_SUPPLIER_ADVANCE` (`requires_allocated_id=False`), reusing existing `payment_id` and skipping duplicate `SupplierBills` deduction when `[spay:{id}]` marker exists.

14. **`P1.8-014` (HIGH — Raw Material Receipt & Dal Milling Missing Fresh Readback & Invoice Line-Key Conflict Guard)**
    - **File:** `backend/app/routers/production.py:988-1000,1108-1115,1557-1564`
    - **Fix:** Added fail-closed post-write fresh readback verification (HTTP `503` if newly committed `RawMaterialLedger` row is absent) and hardened `IncompleteTransactions` conflict check in `receive_raw_material` to also match invoice `line_key` (`INV:{invoice}:L:{line}`) even under a new idempotency key.

---

## 4. Test Modernization & Shared V2.1 Single-Write-Owner Harness (`backend/tests/v2_test_harness.py`)
Rather than weakening production routers or bypassing Single-Write-Owner:
- Built `LocalAppsScriptSimulator` + automatic `Request` injection in `backend/tests/v2_test_harness.py`, executing real production validation, RBAC, costing, accounting, and `apps_script_bridge.delegate_governed_write()` preflight/postflight logic while simulating the remote Apps Script writer locally in memory (and file-backed locks for multiprocess tests).
- Honored monkey-patched `db.append_record` in failure-injection tests via `_append_row_honoring_patch()` without disabling Single-Write-Owner.
- Modernized 6 outdated pre-v2.1 test assertions with equivalent or stronger assertions:
  1. `test_phase4_2a_security_guards.py`: Replaced removed private helper `_run_request` with public approval route endpoints.
  2. `test_erp_stabilization.py`: Updated `FACTORY_WORKER` test to reflect Blueprint V2.1 RBAC (`FACTORY_WORKER` -> `PRODUCTION` read view on `summary`, strictly denied `403` on Owner-only `approve_batch`).
  3. `test_integrity.py`: Updated `test_retry_repairs_payment_without_duplicate_stock` to verify BOTH V2.1 atomic `CREATE_SALE` rollback on `Payments` failure + idempotent retry AND legacy `INCOMPLETE` `RESUME_SALE` recovery without duplicating `SaleItems` or `SOLD_DELIVERY`.
  4. `test_dal_milling_stage2.py`: Aligned purchase-rate assertion with Phase 4 `costing.py` rule forbidding `MILLING_OUTPUT` from `get_latest_purchase_rate` (`MISSING_RATE` rule + verified ledger `rate_per_unit == 115.31` & recipe cost `116.31`).
  5. `test_production_and_attendance_v2.py`: Verified HTTP `403` containing both `'Owner'` and `'PA'` instead of brittle `'Owner or PA'` substring.
  6. `test_raw_material_receiving_stage1.py`: Replaced `setdefault()` with clean tab resets in `setUp` to prevent `JournalHeaders` leakage between tests.

---

## 5. Remaining Open Items (External Only — Zero Local Code Defects Remaining)
1. **External Blockers (`DB-003`, `DB-007`, `DB-008`):** Documented in full in `PHASE1_8_DATABASE_BLOCKERS.md`. All 12 conflicting core tables and 24 pending tables remain strictly write-blocked (`36` write-blocked tabs, `0` approved reconciliations).
2. **Standalone Walkthrough Script:** `backend/tests/verify_acceptance_and_reconciliation.py` (not part of `test_*.py` discovery) still calls pre-v2.1 route signatures directly without a `Request` argument.
3. **Environment-Gated `uvicorn` Subprocess Test:** 1 pre-existing `@unittest.skipUnless` test in `test_startup_port_bind_and_resilience.py` requires real `uvicorn` + `fastapi` packages in a full virtualenv.
4. **Independent Third-Party Audit Pending:** This repository is now code-stable and ready for independent re-verification.

---

## 6. Final Phase 1.8 Status
**Verdict:** `🟡 PHASE 1 CODE-STABLE, EXTERNAL GATES OPEN`
