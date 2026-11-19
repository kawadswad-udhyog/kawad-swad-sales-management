# Kawad Swad ERP — Corrective Implementation v1.3 Handover Report

> **STATUS: IMPLEMENTED — NOT TESTED**
>
> **Constitutional Compliance Notice (Master Policy Constitution v1.2, Section 25):**
> - **NO** tests, builds, linters, formatters, type-checkers, `py_compile`, AST scripts, or runtime checks were executed.
> - **NO** live Google Sheets were accessed or modified.
> - **NO** Apps Script files (`WebAppBridge.gs` or any `.gs` script) were created or modified.
> - **NO** Render settings, GitHub commits/pushes, deployments, credentials, secrets, or production data were touched.
> - **NO** unverified workbook Row-1 headers, tab names, or Owner/CA policy values were fabricated.
> - Verification was performed strictly via static source inspection. Wait for explicit Owner authorization before running tests, builds, or deployments.

---

## Executive Summary

Corrective Implementation v1.3 addressed all 8 priority areas derived from the ZIP (36) Static Acceptance Audit and Master Policy Constitution v1.2:

1. **Mandatory Response Echo Validation (`backend/app/apps_script_bridge.py`)** — Hardened response parsing so omitted or mismatched `correlation_id`, `nonce`/`idempotency_key`, `action`, `target_tab`, or `payload_hash` (when echoed) fail closed with `504 PENDING_UNKNOWN` (`retryable=True`) before trusting `CONFIRMED` or `REJECTED`.
2. **Deletion & Absence Read-Back Verification (`backend/app/action_registry.py`, `backend/app/apps_script_bridge.py`, `backend/app/routers/production.py`, `backend/app/routers/users.py`)** — Implemented `expect_absent`, `allow_soft_delete_inactive`, and `min_remaining_matching_fields` in `ReadBackSpec` / `_verify_readback`; wired `REMOVE_DUPLICATE_ATTENDANCE` (`id_field="attendance_id"`, absence + ≥1 surviving row check) and `DELETE_CUSTOM_ROLE` (`expect_absent=True`, `allow_soft_delete_inactive=True`); added fail-closed zero-check guard in `_verify_readback`.
3. **Exhaustive Action Call-Site to Registry Cross-Reference** — Verified 100% of governed write call sites across all backend routers and services match `GOVERNED_ACTION_REGISTRY` 1:1 on `action`, `target_tab`, `id_field`, and `allowed_invalidate_tabs`.
4. **Read-Back Contract Strengthening (`backend/app/apps_script_bridge.py`, `backend/app/action_registry.py`)** — Fixed silent state-assertion skipping caused by missing nested payload wrapper keys (`record`, `updates`, `packaging_updates`, `batch_updates`, `leg2_row`, `po`, `grn`, `supplier_return`, `payment_update`, `salary_structure`, `execution`), added Decimal-safe scalar equality, added `fixed_state_assertions`, implemented row-by-row bulk attendance verification for `RECORD_BULK_WORKER_ATTENDANCE` and `BULK_LABOUR_ATTENDANCE`, aligned `APPROVE_RECIPE_VERSION` (`requires_allocated_id=True`), and strengthened create/update assertions across the registry.
5. **Schema Registry Evidence & Coverage Reconciliation (`backend/app/schema_registry.py`, `backend/app/routers/v2_erp.py`)** — Confirmed `Settings` is backed by `docs/SALES_MANAGEMENT_SCHEMA.md:29` and `REQUIRED_TABS`, deduplicated `ProductLots` across `DATABASE_GROUPS_15`, documented `CustomRoles` schema variance, and added `get_schema_coverage_summary()` exposing honest counts against the 255-tab cleaned workbook baseline (`91` unique catalogued tabs, `164` unmapped tabs remaining pending Owner workbook export).
6. **Route-by-Route RBAC Audit & Fixes (`backend/app/routers/dashboard.py`, `backend/app/routers/stock.py`, `backend/app/routers/sales.py`)** — Closed verified data-scoping and role-gate defects across dashboard digital collections/workforce/factory counts, stock summary/transactions/discrepancies/van loading passes, and sales dispatch summary.
7. **Frontend Mutation-Path Safety Audit (`src/services/api.ts`, `src/components/common/ConfirmDialog.tsx`, 6 views)** — Eliminated volatile `Date.now()` fallback in `createGoodsReceipt` (`api.ts`) so retried GRN submissions preserve identical `payload_hash`; replaced all 7 remaining native `window.confirm` / `confirm` / `window.prompt` / `prompt` calls across 6 views with `ConfirmDialog` while preserving idempotency nonces and single-flight guards (including adding nonce preservation + single-flight guard to `SalesView.tsx` bill cancellation).
8. **Direct & Indirect Business-Write Path Re-Audit (`backend/app/sheets.py`)** — Closed a POL-024 violation where `ensure_required_tabs` and `_get_worksheet` could call `add_worksheet` / `worksheet.update` directly on live Google Sheets during startup or read misses; guarded `_ensure_headers` with `_assert_direct_mutation_allowed`; verified `workforce_migration.py` has zero runtime FastAPI imports.

---

## Priority 1: Mandatory Response Echo Validation

**File Modified:** `backend/app/apps_script_bridge.py`

### Defect Fixed
Previously, `execute_governed_write` checked echoed fields only conditionally (`if echo_corr and echo_corr != corr_id`, etc.). If Apps Script omitted `correlation_id`, `nonce`, `action`, or `target_tab`, validation silently passed, and `payload_hash` echoes were ignored.

### Correction Applied
- Extracted `echo_corr`, `echo_nonce` (`nonce` or `idempotency_key`), `echo_action`, `echo_tab`, and `echo_payload_hash`.
- Required ALL four mandatory echoes (`correlation_id`, `nonce`, `action`, `target_tab`) to be present and non-empty; any omission returns `BridgeResult(status="PENDING_UNKNOWN", error_code="MISSING_RESPONSE_ECHO", retryable=True, http_status=504)`.
- Enforced exact matching on `correlation_id`, `nonce`, `action`, `target_tab`, and (when returned) `payload_hash`. Any mismatch returns `504 PENDING_UNKNOWN` (`retryable=True`) so callers neither assume success nor generate a fresh nonce that could double-post.

---

## Priority 2: `REMOVE_DUPLICATE_ATTENDANCE` & Absence/Delete Read-Back Verification

**Files Modified:** `backend/app/action_registry.py`, `backend/app/apps_script_bridge.py`, `backend/app/routers/production.py`, `backend/app/routers/users.py`

### Defects Fixed
1. `REMOVE_DUPLICATE_ATTENDANCE` had `id_field=None`, `primary_match_fields=()`, `state_assertions=()`, `child_checks=()` — a no-op read-back. `production.py:2191` omitted `id_field="attendance_id"`.
2. `DELETE_CUSTOM_ROLE` used `primary_match_fields=("role_id",)`, which asserted that the deleted row STILL EXISTED; meanwhile `REQUIRED_TABS["CustomRoles"]` has no `deleted`/`active` column, and `users.py:list_roles` did not filter soft-deleted rows.
3. `_verify_readback` could return `None` without executing any check if a `ReadBackSpec` had no matching criteria.

### Corrections Applied
- Extended `ReadBackSpec` with `expect_absent: bool = False`, `allow_soft_delete_inactive: bool = False`, and `min_remaining_matching_fields: Tuple[str, ...] = ()`.
- Updated `_verify_readback`:
  - When `expect_absent=True`, requires `spec.id_field` and `lookup_id`, confirms the target row is absent from `fresh_rows` (or if `allow_soft_delete_inactive=True`, accepts `deleted=="true"` or `active=="false"`), and when `min_remaining_matching_fields` is set, verifies ≥1 surviving row with a different ID still matches those fields.
  - Added `checks_executed` counter; if `checks_executed == 0`, raises `_ReadBackFailure` (fail-closed).
- Updated `REMOVE_DUPLICATE_ATTENDANCE` in `action_registry.py` (`id_field="attendance_id"`, `expect_absent=True`, `min_remaining_matching_fields=("worker_id", "attendance_date")`) and passed `id_field="attendance_id"` in `production.py:2198`.
- Updated `DELETE_CUSTOM_ROLE` in `action_registry.py` (`expect_absent=True`, `allow_soft_delete_inactive=True`) and filtered `deleted=="true"` / `active=="false"` rows in `users.py:list_roles`.

---

## Priority 3: Exhaustive Action-Call-Site to Registry Cross-Reference

Every `delegate_governed_write` and `execute_governed_write` call site across `backend/app/` was inspected and cross-referenced against `GOVERNED_ACTION_REGISTRY` (`backend/app/action_registry.py`):

| Module | Actions Invoked | Target Tab / `id_field` / `invalidate_tabs` Alignment |
|---|---|---|
| `backend/app/auth.py` | `REVOKE_TOKEN`, `REVOKE_USER_SESSIONS` | 100% aligned |
| `backend/app/routers/auth.py` | `CHANGE_PASSWORD` | 100% aligned |
| `backend/app/user_service.py` | `CREATE_USER`, `UPDATE_USER`, `REACTIVATE_USER`, `DEACTIVATE_USER`, `RESET_PASSWORD` | 100% aligned |
| `backend/app/routers/users.py` | `UPDATE_CUSTOM_ROLE`, `CREATE_CUSTOM_ROLE`, `DELETE_CUSTOM_ROLE`, `RECONCILE_ROLE_ALIAS` | 100% aligned |
| `backend/app/routers/approvals.py` | `CREATE_APPROVAL_REQUEST`, `REJECT_APPROVAL_REQUEST`, `APPROVE_AND_EXECUTE_REQUEST`, `CANCEL_APPROVAL_REQUEST` | 100% aligned |
| `backend/app/routers/products.py` | `CREATE_PRODUCT`, `UPDATE_PRODUCT` | 100% aligned |
| `backend/app/routers/customers.py` | `CREATE_CUSTOMER`, `UPDATE_CUSTOMER` | 100% aligned |
| `backend/app/routers/purchasing.py` | `CREATE_SUPPLIER`, `UPDATE_SUPPLIER`, `CREATE_PURCHASE_ORDER`, `CANCEL_PURCHASE_ORDER`, `RECEIVE_GOODS`, `RECORD_SUPPLIER_BILL`, `RECORD_SUPPLIER_PAYMENT`, `APPLY_SUPPLIER_ADVANCE`, `CREATE_SUPPLIER_RETURN` | 100% aligned |
| `backend/app/routers/production.py` | `CREATE_RAW_MATERIAL_MASTER`, `UPDATE_RAW_MATERIAL_RATE`, `VERIFY_RAW_MATERIAL_OPENING_STOCK`, `RECEIVE_RAW_MATERIAL`, `RECOVER_MILLING_BATCH`, `RECORD_MILLING_BATCH`, `ADJUST_RAW_MATERIAL_STOCK`, `ADJUST_FINISHED_GOODS_STOCK`, `CREATE_WORKER`, `RECORD_WORKER_ATTENDANCE`, `RECORD_BULK_WORKER_ATTENDANCE`, `CORRECT_WORKER_ATTENDANCE`, `REMOVE_DUPLICATE_ATTENDANCE` (fixed `id_field="attendance_id"`), `CREATE_RECIPE`, `APPROVE_RECIPE_VERSION`, `CREATE_PRODUCTION_BATCH`, `RECOVER_RAW_MATERIALS_STATUS`, `ISSUE_RAW_MATERIALS`, `REJECT_PRODUCTION_BATCH`, `APPROVE_PRODUCTION_BATCH`, `RECORD_PACKAGING_PENDING_REVIEW`, `RECONCILE_PACKAGING_BATCH`, `RECORD_PACKAGING_BATCH`, `RESOLVE_LEGACY_BATCH_COST`, `RECOVER_PACKAGING`, `APPROVE_PACKAGING_DISCREPANCY`, `RECONCILE_DISPATCH`, `PRODUCTION_STOCK_DISPATCH` | 100% aligned (28 call sites) |
| `backend/app/routers/quality.py` | `CREATE_QUALITY_CHECK`, `CREATE_PRODUCT_LOT`, `UPDATE_LOT_STATUS`, `CREATE_CUSTOMER_RETURN`, `CREATE_COMPLAINT_OR_RECALL`, `CLOSE_COMPLAINT` | 100% aligned |
| `backend/app/routers/sales.py` | `MARK_SALE_COMPLETE`, `CREATE_SALE`, `RESUME_SALE`, `CANCEL_SALE`, `RECORD_SALE_PAYMENT`, `CREATE_LEGACY_SALES_ORDER`, `CONFIRM_SALES_ORDER` | 100% aligned |
| `backend/app/routers/stock.py` | `RECORD_STOCK_MOVEMENT`, `SUBMIT_STOCK_DISCREPANCY`, `REVIEW_STOCK_DISCREPANCY`, `RECONCILE_FACTORY_STOCK`, `RECONCILE_WAREHOUSE_STOCK`, `RECONCILE_SALESMAN_STOCK`, `CREATE_VAN_LOADING_PASS`, `ACCEPT_VAN_LOADING_PASS`, `REPORT_VAN_LOADING_DISCREPANCY`, `CANCEL_VAN_LOADING_PASS` | 100% aligned |
| `backend/app/routers/visits.py` | `LOG_SHOP_VISIT` | 100% aligned |
| `backend/app/routers/expenses.py` | `SUBMIT_EXPENSE`, `REVIEW_EXPENSE` | 100% aligned |
| `backend/app/routers/closing.py` | `SUBMIT_DAILY_CLOSING`, `REVIEW_DAILY_CLOSING` | 100% aligned |
| `backend/app/routers/accounting.py` | `CLOSE_ACCOUNTING_PERIOD` | 100% aligned |
| `backend/app/accounting/journal_engine.py` | `POST_JOURNAL_VOUCHER`, `REVERSE_JOURNAL_VOUCHER` | 100% aligned |
| `backend/app/accounting/customer_ledger.py` | `RESERVE_CREDIT_APPROVAL`, `CONSUME_CREDIT_APPROVAL`, `RELEASE_CREDIT_APPROVAL` | 100% aligned |
| `backend/app/routers/workforce.py` | `SUBMIT_TASK`, `CHECK_IN_ATTENDANCE`, `CHECK_OUT_ATTENDANCE`, `UPDATE_SELF_PROFILE`, `SUBMIT_MILESTONE`, `CREATE_LABOUR`, `UPDATE_LABOUR`, `BULK_LABOUR_ATTENDANCE`, `CREATE_WORK_ENTRY`, `ASSIGN_TASK`, `UPDATE_TASK`, `REVIEW_TASK`, `CREATE_PROJECT`, `CREATE_MILESTONE`, `REVIEW_MILESTONE`, `UPSERT_SALARY_STRUCTURE`, `CALCULATE_PAYROLL`, `UPDATE_PAYROLL_ITEM`, `APPROVE_PAYROLL`, `RECORD_WORKFORCE_PAYMENT` | 100% aligned (20 call sites) |
| `backend/app/routers/salary.py` | `CREATE_SALARY_INCENTIVE`, `APPROVE_SALARY_INCENTIVE`, `PAY_SALARY_INCENTIVE` | 100% aligned |
| `backend/app/routers/v2_erp.py` | `UPDATE_CA_POLICY`, `RECORD_PACKAGING_BATCH`, `RECORD_DISTRIBUTION_DISPATCH`, `RECORD_MARKETPLACE_SETTLEMENT`, `RECORD_COMPLIANCE_ITEM`, `RECORD_ASSET_MAINTENANCE`, `DISBURSE_APPROVED_ADVANCE`, `SUBMIT_GIG_WORK_ENTRY`, `VERIFY_GIG_WORK_ENTRY`, `PAY_GIG_WORK_ENTRY`, `CREATE_PURCHASE_ORDER`, `CREATE_GOODS_RECEIPT`, `REQUEST_STOCK_ADJUSTMENT`, `RECORD_MILLING_BATCH`, `CREATE_PRODUCTION_BATCH`, `CREATE_SALES_ORDER`, `CREATE_SALES_INVOICE`, `POST_JOURNAL_VOUCHER` | 100% aligned (18 call sites) |

**Result:** Zero unregistered actions, zero mismatched target tabs, zero mismatched `id_field` arguments, and zero unallowlisted cache-invalidation tabs across all call sites.

---

## Priority 4: Read-Back Contract Audit & Strengthening

**Files Modified:** `backend/app/apps_script_bridge.py`, `backend/app/action_registry.py`

### Root-Cause Defects Fixed
1. **Silent Skip on Nested Payload Wrappers:** `_lookup_expected_value` previously searched only `("sale", "order", "payroll_run", "payment", "user_updates", "auth_updates", "item_update")`. Routers wrapping payloads in `"record"`, `"updates"`, `"packaging_updates"`, `"batch_updates"`, `"leg2_row"`, `"po"`, `"grn"`, `"supplier_return"`, `"payment_update"`, `"salary_structure"`, or `"execution"` caused `_lookup_expected_value` to return `None`, silently bypassing `state_assertions`. All verified wrapper keys are now included in `_NESTED_PAYLOAD_WRAPPER_KEYS`.
2. **Numeric Format Mismatches:** Added `_scalar_values_equal` supporting exact normalized string match AND finite `Decimal` numeric equivalence (`15000.0` == `"15000"`).
3. **Bulk Attendance Weakness:** Upgraded `RECORD_BULK_WORKER_ATTENDANCE` (`bulk_rows_keys=("records",)`, match `("worker_id", "attendance_date")`, state `("status",)`) and `BULK_LABOUR_ATTENDANCE` (`bulk_rows_keys=("inserts", "updates")`, match `("labour_id", "attendance_date")`, state `("status",)`) so EVERY submitted row is individually verified on read-back.
4. **Fixed-State Assertions:** Added `fixed_state_assertions` for actions whose target sheet state is a fixed lifecycle transition not directly echoed under the same payload key (`APPROVE_AND_EXECUTE_REQUEST`: `status in ("EXECUTED", "APPROVED")`; `DISBURSE_APPROVED_ADVANCE`: `status in ("DISBURSED", "PAID")`).
5. **`APPROVE_RECIPE_VERSION` Alignment:** Changed `requires_allocated_id=False` to `requires_allocated_id=True` with `state_assertions=(("approved", "approved"), ("version", "version"))`, matching `production.py:2429` which creates a new immutable recipe version.
6. **Weak Update & Create Actions Strengthened:** Added verified payload `state_assertions` to `UPDATE_USER`, `UPDATE_SELF_PROFILE`, `UPDATE_PRODUCT`, `CREATE_RECIPE`, `UPDATE_SUPPLIER`, `RECEIVE_GOODS`, `CREATE_GOODS_RECEIPT`, `RECORD_SUPPLIER_PAYMENT`, `APPLY_SUPPLIER_ADVANCE`, `CREATE_SUPPLIER_RETURN`, `VERIFY_RAW_MATERIAL_OPENING_STOCK`, `RECEIVE_RAW_MATERIAL`, `ADJUST_RAW_MATERIAL_STOCK`, `ADJUST_FINISHED_GOODS_STOCK`, `RECORD_MILLING_BATCH`, `RECOVER_MILLING_BATCH`, `CREATE_PRODUCTION_BATCH`, `ISSUE_RAW_MATERIALS`, `RESOLVE_LEGACY_BATCH_COST`, `RECONCILE_PACKAGING_BATCH`, `RECORD_PACKAGING_BATCH`, `RECOVER_PACKAGING`, `CREATE_CUSTOMER_RETURN`, `CREATE_SALES_INVOICE`, `CREATE_SALES_ORDER`, `CREATE_LEGACY_SALES_ORDER`, `LOG_SHOP_VISIT`, `RECONCILE_FACTORY_STOCK`, `RECONCILE_WAREHOUSE_STOCK`, `RECONCILE_SALESMAN_STOCK`, `PRODUCTION_STOCK_DISPATCH`, `RECONCILE_DISPATCH`, `RECORD_DISTRIBUTION_DISPATCH`, `RECORD_MARKETPLACE_SETTLEMENT`, `RECORD_ASSET_MAINTENANCE`, `REVERSE_JOURNAL_VOUCHER`, `CREATE_WORKER`, `RECORD_WORKER_ATTENDANCE`, `CHECK_IN_ATTENDANCE`, `CHECK_OUT_ATTENDANCE`, `UPDATE_TASK`, `CREATE_PROJECT`, `CREATE_LABOUR`, `UPDATE_LABOUR`, `CREATE_WORK_ENTRY`, `UPSERT_SALARY_STRUCTURE`, `CALCULATE_PAYROLL`, `UPDATE_PAYROLL_ITEM`, `RECORD_WORKFORCE_PAYMENT`, and `DISBURSE_APPROVED_ADVANCE`.

---

## Priority 5: Schema Registry Evidence & Coverage Reconciliation

**Files Modified:** `backend/app/schema_registry.py`, `backend/app/routers/v2_erp.py`

### Evidence-Backed Reconciliation Summary
- **Baseline:** 255 cleaned workbook tabs (`WORKBOOK_TARGET_TAB_COUNT = 255`).
- **Verified Core / Workforce Tabs (`sheets.py:REQUIRED_TABS`):** **67 tabs**, including `Settings` (`["setting_key", "setting_value", "description"]`), independently verified in `docs/SALES_MANAGEMENT_SCHEMA.md:29`.
  - Of these 67 tabs, `66` have status `VERIFIED_CORE` and `1` (`Suppliers`) is explicitly flagged `CONFLICT_RECONCILIATION_REQUIRED` (12 columns in `REQUIRED_TABS` vs 14 fields including `payment_terms` and `opening_balance` in `purchasing.py`).
  - `CustomRoles` (7 columns in `REQUIRED_TABS`) now documents its physical-delete / optional soft-delete variance in `SCHEMA_HEADER_VARIANCES`.
- **Extended Blueprint v2.1 Tabs (`EXTENDED_V2_TAB_CONTRACTS`):** **25 entries** (`23` `PENDING_OWNER_MAPPING` + `2` `CONFLICT_RECONCILIATION_REQUIRED` for `ExceptionRegister` vs draft alias `ExceptionLogs`). All 25 fail closed on writes (`PENDING_OWNER_MAPPING_TABS`) until Owner supplies canonical Row-1 headers.
- **Deduplication Fix:** Removed duplicate `"ProductLots"` from Group `05` in `DATABASE_GROUPS_15` (already catalogued in Group `03` Inventory & Warehousing).
- **Honest Coverage Exposure:** Added `get_schema_coverage_summary()` and exposed `unique_catalogued_workbook_tabs` (`91`) and `unmapped_workbook_tabs_remaining` (`164`) via `GET /api/v2/meta/schema-registry`. Zero unverified tab names or Row-1 headers were fabricated.

---

## Priority 6: Route-by-Route RBAC Audit & Justified Exceptions

### RBAC Defects Fixed in v1.3
1. **`backend/app/routers/dashboard.py` (`GET /api/dashboard`, `GET /api/dashboard/metrics`):**
   - Previously leaked company-wide `today_digital_total` across all salesmen, plus `active_salesmen`, `active_workers_count`, `workers_present_today`, and `factory_pkts` to unprivileged roles.
   - **Fix:** Scoped `today_digital_total` to the caller's visible sales/collections when not manager/auditor; gated `active_salesmen` to managers/auditors, workforce counts to managers/auditors/`HR`/`PRODUCTION_SUPERVISOR`, and factory stock packet totals to managers/auditors/`STORE`/`PRODUCTION_SUPERVISOR`/`PACKAGING`/`QUALITY`/`LOGISTICS`.
2. **`backend/app/routers/stock.py`:**
   - `GET /api/stock/summary`, `GET /api/stock/transactions`, `GET /api/stock/discrepancies` lacked explicit `require_roles` (allowing e.g. `FREELANCER` or `HR` to view company warehouse stock).
   - `GET /api/stock/loading-passes` and `GET /api/stock/loading-passes/{pass_id_or_number}` only scoped `SALESMAN`/`FIELD_SALESMAN`, allowing non-sales non-manager roles (`FREELANCER`, `HR`, etc.) to view all van loading passes.
   - **Fix:** Enforced `STOCK_READ_ROLES` / `STOCK_ALL_SCOPE_ROLES` and `VAN_PASS_READ_ROLES`; scoped non-all-scope roles strictly to their own records and hid `company_stock` from non-warehouse/non-manager roles.
3. **`backend/app/routers/sales.py` (`GET /api/sales/dispatch-summary`):**
   - Previously returned all company sales bills to `FIELD_SALESMAN`.
   - **Fix:** Scoped rows to the caller's own sales (`salesman_user_id` / `entered_by_user_id`) when `not _can_view_all_sales(current_user)`.

### Route-by-Route Audit Overview & Justified Exceptions

| Router / Area | RBAC Enforcement Status | Justified Exceptions |
|---|---|---|
| `main.py` | Root `/` & `/api/health` public minimal liveness; detailed diagnostics (`/api/health/details`, `/api/health/diagnostics`) restricted to `OWNER_ADMIN` | Public `/` & `/api/health` required by Render health checks (no sensitive data exposed) |
| `routers/auth.py` | `POST /api/auth/login` public; `/me`, `/logout`, `/change-password` require valid JWT; `POST /logout` & `POST /change-password` delegate via Apps Script | `POST /api/auth/login` is the authentication entry point |
| `routers/users.py` | Owner/PA gated directory & management; custom role CRUD & role alias reconciliation strictly Owner-only; `_reject_auditor` enforced | `GET /api/users/me` self-read for any authenticated user |
| `routers/approvals.py` | Pending list/actions Owner/PA scoped; approve/reject strictly Owner-only; cancel restricted to requester or Owner | None |
| `routers/dashboard.py` | Fixed in v1.3: strictly scoped to caller's role & own records when non-manager | Authenticated landing endpoint for all logged-in roles with role-scoped aggregation |
| `routers/products.py` | Read allowed for operational roles; create/update restricted to management/product roles; Auditor read-only | None |
| `routers/customers.py` | Read/write gated to sales/management/accounts roles; Auditor read-only | None |
| `routers/purchasing.py` | Gated to procurement/accounts/management roles; Auditor read-only | None |
| `routers/production.py` | `require_production_read` / `require_production_access` / `require_owner` consistently enforced across all 45+ endpoints; Auditor read-only | `POST /api/production/recipes/calculate` uses `require_production_read` because it is a stateless read-only cost estimator (performs zero writes) |
| `routers/quality.py` | Gated to quality/production/management roles; lot release/hold/reject gated; Auditor read-only | None |
| `routers/sales.py` | Fixed in v1.3 (`dispatch-summary` scoped); all reads/writes check `SALES_READ_ROLES` / `SALES_WRITE_ROLES` / `_can_view_all_sales` / `_reject_auditor` | None |
| `routers/stock.py` | Fixed in v1.3 (`summary`, `transactions`, `discrepancies`, `loading-passes` gated & scoped); all writes block `AUDITOR` and enforce role allowlists | None |
| `routers/visits.py`, `expenses.py`, `closing.py` | Salesmen scoped to own records; manager review/approval gated to Owner/PA; Auditor read-only | None |
| `routers/salary.py` | Owner/PA/HR/Accounts gated; salesmen limited to own records; approve/pay strictly Owner; Auditor read-only | None |
| `routers/workforce.py` | Self-service `/me/*` strictly bound to `current_user["user_id"]`; HR/Payroll/Advance confidential fields strictly redacted for non-Owner/non-HR; all writes call `_reject_auditor` | `GET/PUT /api/workforce/me/*` authenticated self-service for own attendance, tasks, profile, and payslips |
| `routers/accounting.py` | Accounts/Owner/PA/Auditor read access; manual vouchers, reversals, period close gated to Accounts/Owner; Auditor read-only | None |
| `routers/audit.py` | Restricted to Owner/PA/Auditor | None |
| `routers/workspace.py` | Authenticated user workspace preference / navigation summary; zero business writes | Authenticated read-only navigation helper |
| `routers/v2_erp.py` | Every route enforces `require_module_action` / `require_roles` / `is_owner`, blocks `AUDITOR` on writes, redacts confidential fields, and enforces fail-closed CA policy gates | `GET /api/v2/meta/capabilities` returns role-specific capability matrix for the authenticated user |

---

## Priority 7: Frontend Mutation-Path Safety Audit

**Files Modified:** `src/services/api.ts`, `src/components/common/ConfirmDialog.tsx`, `src/views/AttendanceView.tsx`, `src/views/UsersView.tsx`, `src/views/PurchasingView.tsx`, `src/views/WorkforceView.tsx`, `src/views/StockView.tsx`, `src/views/SalesView.tsx`

### Defects Fixed
1. **Non-Idempotent `Date.now()` Payload Mutation (`src/services/api.ts:1459`):**
   - `createGoodsReceipt` previously synthesized `CH-${Date.now().toString().slice(-6)}` when no challan/invoice reference was provided. Retrying the same GRN with the same `idempotencyKey` after a `504 PENDING_UNKNOWN` mutated `invoice_reference` and `delivery_challan`, altering `payload_hash`.
   - **Fix:** Derived the fallback reference deterministically from `idempotencyKey || payload.idempotency_key || ${supplier_id}-${receipt_date}`.
2. **Native Browser Dialogs Replaced (7 occurrences across 6 views — Constitution Section 3.3):**
   - Extended `src/components/common/ConfirmDialog.tsx` with optional text-input prompt mode (`inputLabel`, `inputPlaceholder`, `inputValue`, `onInputChange`, `inputRequired`) while preserving backward compatibility.
   - Replaced all 7 native dialogs:
     - `AttendanceView.tsx`: `window.confirm` on duplicate attendance deletion -> `ConfirmDialog` (preserves `deleteNonces` & single-flight `isSubmitting`).
     - `UsersView.tsx`: both `window.confirm` calls (toggle status + cancel approval request) -> `ConfirmDialog` (preserves `actionNonces` & added single-flight `isConfirmSubmitting`).
     - `PurchasingView.tsx`: `prompt` on PO cancellation -> `ConfirmDialog` prompt mode (preserves `cancelOrderNonces`, reason, and modal on `504 PENDING_UNKNOWN`).
     - `WorkforceView.tsx`: `window.confirm` on payroll run approval -> `ConfirmDialog` (preserves `approvePayrollNonces` & `approvingRunId`).
     - `StockView.tsx`: `confirm` on van loading pass cancellation -> `ConfirmDialog` (preserves `cancelPassNonces` & `cancellingPassId`).
     - `SalesView.tsx`: `window.prompt` on bill cancellation -> `ConfirmDialog` prompt mode + added preserved `cancelSaleNonces` and `isCancellingSale` single-flight guard, passing the preserved `activeNonce` to `cancelSale(sale_id, reason, activeNonce)`.
   - Re-verified via grep across `src/`: **zero** runtime `window.confirm`, `confirm(`, `window.prompt`, `prompt(`, `window.alert`, or `alert(` calls remain.
3. **`StoreContext.tsx` Audit:**
   - Inspected `Date.now()` usages at L454 (`addAuditLog` — strictly non-authoritative local UI activity hint, never written to backend), and L1270/1291/1313 (local salary preview `record_id` values that are explicitly stripped at L1337–1348 before POSTing to `/api/salary`, with UI state updated only from server-confirmed persisted rows). Confirmed safe.

---

## Priority 8: Direct & Indirect Business-Write Path Re-Audit

**File Modified:** `backend/app/sheets.py`

### Critical POL-024 Violation Fixed
- `ensure_required_tabs` (`sheets.py:1088`) and `_get_worksheet` (`sheets.py:1160`) previously called `ss.add_worksheet(...)` and `worksheet.update("A1", [headers])` directly against live Google Sheets during startup or read misses, and `_ensure_headers` (`sheets.py:1122`) lacked `_assert_direct_mutation_allowed`.
- **Fix:**
  - Converted `ensure_required_tabs` to strictly read-only worksheet discovery (`ss.worksheets()`), caching existing worksheets and logging a warning for any missing `REQUIRED_TABS` without ever calling `add_worksheet` or `worksheet.update`.
  - Converted `_get_worksheet` to strictly read-only lookup (`self.spreadsheet.worksheet(tab_name)`), failing closed on missing tabs instead of auto-creating them.
  - Guarded `_ensure_headers` with `self._assert_direct_mutation_allowed("_ensure_headers", tab_title)`.

### Indirect Path Verification
- **`backend/app/workforce_migration.py`:** Confirmed via full repository search that it is imported ONLY by `backend/tests/test_workforce_migration_safety.py` and offline CLI script `backend/scripts/migrate_workforce_stage3.py` — **zero** FastAPI runtime router/startup references.
- **`db.log_audit` (`sheets.py:1898`):** Calls `self.append_record("AuditLog", record, raise_on_error=False)`, which passes through `_assert_direct_mutation_allowed` and does not perform unauthorized live Google Sheets mutations when Apps Script is the single write owner.
- **Routers & Services:** Re-verified zero direct `db.append_record`, `db.update_record`, or `db.delete_record` calls exist in any runtime FastAPI router or service module.

---

## Remaining Blockers & Owner / CA / Apps Script Dependencies

1. **Apps Script Web App (`WebAppBridge.gs` — NOT CREATED per strict restriction):**
   - Must implement handlers for all governed actions in `GOVERNED_ACTION_REGISTRY`, verify HMAC-SHA256 + `payload_hash` + `nonce` idempotency, **always echo** `correlation_id`, `nonce`, `action`, `target_tab`, and `payload_hash` in every JSON response (both `CONFIRMED` and `REJECTED`), and perform atomic multi-tab writes + ID allocation.
2. **Owner Schema Workbook Export (`164` unmapped tabs + `25` `PENDING_OWNER_MAPPING` / conflict tabs):**
   - Canonical Row-1 headers must be supplied by Owner from the cleaned 255-tab workbook before enabling writes on any `PENDING_OWNER_MAPPING_TABS`.
   - Reconcile `ExceptionRegister` vs `ExceptionLogs`, `Suppliers` (12 vs 14 columns), `CustomRoles` (physical delete vs soft-delete columns), and legacy `PKG` prefix collision (`PackagingBatches` vs `PackagingMaterials`).
3. **Pending CA Sign-Off Policies (fail-closed in `schema_registry.py`):**
   - `hsn_gst_tax_rates`, `inventory_valuation_method`, `overhead_and_labour_allocation_basis`, and `depreciation_policy` remain `PENDING_CA_APPROVAL`.
4. **Verification Gate:**
   - All changes in v1.3 are **IMPLEMENTED — NOT TESTED**. Awaiting Owner authorization before running unit/integration tests, TypeScript/Vite build checks, or any GitHub/Render operations.
