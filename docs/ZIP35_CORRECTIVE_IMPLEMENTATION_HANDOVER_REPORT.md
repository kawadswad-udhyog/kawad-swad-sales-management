# Kawad Swad ERP — ZIP (35) Corrective Implementation Handover Report

**Status:** Code & Static Audit Complete (Pending Test/Build Authorization, Owner/CA Decisions, Apps Script `WebAppBridge.gs` Deployment, & Staging Verification)  
**Governing References:** ZIP (35) Static Acceptance Audit, Corrective Implementation Prompt v1.2, Upgrade Blueprint v2.1, Database Blueprint v2.0, Master Operations Manual v2.0  

---

## 1. Mandatory Verification & Execution Boundary

```text
TESTS NOT RUN AS INSTRUCTED. BUILDS/LINTERS NOT RUN. LIVE GOOGLE SHEETS NOT ACCESSED. APPS SCRIPT NOT MODIFIED OR DEPLOYED. WEBAPPBRIDGE NOT CREATED/DEPLOYED. GITHUB NOT PUSHED. RENDER NOT DEPLOYED. PRODUCTION DATA NOT MODIFIED.
```

> All verification claims below come strictly from read-only Python `ast` syntax parsing, AST call-site/decorator inspection, regex/grep static scans, and direct source code inspection in `/app/applet`. No `pytest`, `npm test`, `npm run build`, `npm run lint`, `tsc`, `eslint`, or runtime execution was performed.

---

## 2. Executive Summary

This corrective phase resolves the implementation defects identified in the **ZIP (35) Static Acceptance Audit** across all eight mandatory priorities while preserving existing business rules, UI design, Google Sheets as the sole authoritative business record, and strict fail-closed semantics:

1. **Stable Idempotency & Retry Behavior (Backend + Frontend):** Preserved deterministic `payload_hash` (excluding volatile `timestamp`/`correlation_id`), disabled silent random UUID fallback generation (`allow_generated_nonce=False` default), eliminated non-idempotent fallback IDs (`id(req)`, `POL-{policy_key}`), and made every mutating ERP view, employee portal view, and wizard retry-safe using persisted submission nonces, double-submit guards, persisted fallback client references (`RECON-*` / `PKG-*`), and HTTP 504 / `AbortError` `ApiOutcomeUnknownError` preservation.
2. **Strict Centralized Action-to-Table Allowlist:** Enforced `GOVERNED_ACTION_REGISTRY` in `/backend/app/action_registry.py` (`127` registered actions). Every call to `execute_governed_write` / `delegate_governed_write` must match `action -> target_tab`, `id_field`, and `allowed_invalidate_tabs` fail-closed. Remediated unregistered `RECONCILE_WAREHOUSE_STOCK` discovered during final static cross-check.
3. **Request/Response Correlation & Confirmation Validation:** Enforced HTTP 409 conflict rejection on header/body nonce disagreement (`IDEMPOTENCY_NONCE_MISMATCH`), blocked HTTP `3xx` redirects (`_NoRedirectHandler`), validated non-dict/empty Apps Script responses, validated echoed `correlation_id`, `nonce`/`idempotency_key`, `action`, `target_tab`, required `allocated_id`, and `locked_prefix` format before accepting `CONFIRMED`.
4. **Explicit Transaction-Specific Read-Back Verification:** Replaced generic primary-ID checks with explicit `ReadBackSpec` contracts (primary match fields, expected state assertions, foreign-key child tab row-count checks, and `JournalLines` debit/credit balance checks) in `/backend/app/apps_script_bridge.py` (`_verify_readback`). Failures return `504 PENDING_UNKNOWN` (`READ_BACK_UNCONFIRMED`, `retryable=True`).
5. **Verified-Only Database Registry:** Completed `/backend/app/schema_registry.py` with verified core + workforce tables, `SCHEMA_HEADER_VARIANCES` (`Settings` verified; `Suppliers` 12 vs 14 header conflict flagged), `TAB_RECONCILIATION_CONFLICTS` (`EXC` `ExceptionRegister` vs `ExceptionLogs`, `PKG` vs `PKB`), and `PENDING_OWNER_MAPPING_TABS` without fabricating unverified Row-1 headers.
6. **Legacy Write Path & Route Guard Audit:** Verified `0` direct `db.append_record` / `db.update_record` / `db.delete_record` / `generate_id` / `get_next_id` / `allocate_bill_number` calls outside `/backend/app/sheets.py`, added `Depends(require_sheets_connection)` on `/api/auth/change-password`, removed leftover fallback reads to nonexistent `"RawMaterialsMaster"`, and audited RBAC across all `120` mutating router endpoints.
7. **Strict Fail-Closed Semantics Preserved:** Missing bridge config (`503 APPS_SCRIPT_BRIDGE_UNCONFIGURED`), unmapped/conflicting tabs (`503 PENDING_OWNER_MAPPING` / `CONFLICT_RECONCILIATION_REQUIRED`), forbidden scratch tabs (`403 SCRATCH_TAB_FORBIDDEN`), disconnected Sheets (`503`), and pending CA policies (`409` / `PermissionError`) all fail closed with zero local/in-memory business persistence fallbacks.
8. **Unresolved Dependencies Documented:** All open Owner, CA, Row-1 schema mapping, and Apps Script deployment dependencies are cataloged explicitly in Section 6.

---

## 3. Priority-by-Priority Implementation Summary

### Priority 1 — Stable Idempotency & Retry Behavior

**Backend (`/backend/app/apps_script_bridge.py`, `/backend/app/auth.py`, `/backend/app/accounting/journal_engine.py`, routers):**
- `AppsScriptBridge.compute_payload_hash(...)` computes a canonical SHA-256 digest over `(action, target_tab, nonce, actor_user_id, actor_role, payload)` while excluding volatile attempt fields (`timestamp`, `correlation_id`). Sent in both envelope `payload_hash` and `X-KS-Payload-Hash` header.
- `AppsScriptBridge.extract_request_nonce(...)` reads `explicit_nonce` or `X-KS-Idempotency-Key` / `X-Idempotency-Key`; raises `409 IDEMPOTENCY_NONCE_MISMATCH` if both are present and differ.
- `delegate_governed_write(..., allow_generated_nonce: bool = False)` keeps random UUID nonce generation disabled by default; `execute_governed_write` rejects empty nonces with `422 MISSING_IDEMPOTENCY_NONCE`.
- Deterministic domain nonces preserved for internal automated calls (e.g., `JV-{reference_type}-{reference_id}`, `REV-{journal_id}`, `RVK-{token_id[:24]}`, deterministic manual voucher hashes in `/backend/app/routers/accounting.py`).
- Session revocation in `/backend/app/auth.py` uses deterministic reason-hashed nonces (`REVOKE-SESS-...`).

**Frontend (`/src/services/api.ts`, `/src/context/StoreContext.tsx`, `/src/views/*.tsx`, `/src/employee/views/*.tsx`, `/src/components/salesman/MobileOrderWizard.tsx`):**
- `/src/services/api.ts`: Exports `createSubmissionNonce`, `isUnknownOutcomeError`, and `ApiOutcomeUnknownError`. Non-GET `apiRequest` attaches/forwards `X-KS-Idempotency-Key` and throws `ApiOutcomeUnknownError` on HTTP `504` or `AbortError`. `apiFetch` callers explicitly check `res.status === 504` before safe `res.text()` JSON parsing and handle `AbortError` as unknown outcome.
- `/src/context/StoreContext.tsx`: Mutating store methods forward caller-supplied `idempotencyKey?: string` to `apiRequest`.
- **All Operational Views Hardened (18 ERP views + MobileOrderWizard; `MySalaryView.tsx` read-only):**
  - Core views previously updated: `CustomersView.tsx`, `ProductsView.tsx`, `VisitsView.tsx`, `ExpensesView.tsx`, `ApprovalsView.tsx`, `UsersView.tsx`, `SalaryView.tsx`, `AttendanceView.tsx`, `SalesView.tsx`, `ClosingView.tsx`, `ErpOperationsHubView.tsx`, `MobileOrderWizard.tsx`.
  - Employee portal views (5/5): `EmployeeOverviewView.tsx`, `MyTasksView.tsx`, `MyAttendanceView.tsx`, `MyProjectsView.tsx`, `MyProfileView.tsx`.
  - Final 6 complex ERP views updated in this phase:
    - `/src/views/QualityView.tsx`: Per-modal/action nonces (`lotActionNonces`, `checkNonce`, `lotNonce`, `returnNonce`, `complaintNonce`, `resolveNonce`), submitting guards, `SaveButton` `isLoading`, reset only on success or explicit cancel/close.
    - `/src/views/AccountingView.tsx`: `reversalNonce` (`ACC-REV`), `reconcileNonce` (`ACC-REC`), double-submit guards, 504 unknown-outcome messaging, preserved nonces across failed retries.
    - `/src/views/WorkforceView.tsx`: Added `parseApiFetchJson` (explicit `res.status === 504` check), nonces & guards for bulk attendance (`bulkAttNonce`), work entries (`workEntryNonce`), payroll calculation (`calcPayrollNonce`), payroll approval (`approvePayrollNonces`, `approvingRunId`), disbursement (`disburseNonce`), and all 5 modals (`AddLabourModal`, `AssignTaskModal`, `ReviewTaskModal`, `CreateProjectModal`, `AddMilestoneModal` — fixing silent error swallowing in the latter three).
    - `/src/views/PurchasingView.tsx`: Added nonces (`supplierNonce`, `orderNonce`, `cancelOrderNonces`, `receiptNonce`, `billNonce`, `returnNonce`), `cancellingOrderId` lock, `SaveButton` `isLoading`, HTTP 504 handling across all 8 catch blocks (preserving `newPayment.idempotency_key` and `applyAdvanceModal.idempotency_key`).
    - `/src/views/StockView.tsx`: Added nonces & guards across all 7 flows (`createPassNonce`, `acceptPassNonces`, `discrepancyNonce`, `cancelPassNonces`, `resolveCostNonces`, `reconNonce` + `reconFallbackRef`, `movementNonce`, `discSubmitNonce`, `reviewNonces`); persisted `reconFallbackRef` across failed retries; replaced `alert(...)` in `handleReportDiscrepancy` with inline `discrepancyError` alert banner.
    - `/src/views/ProductionView.tsx`: Added nonces & guards across all 15+ flows (`recoverPkgNonces`, `confirmRecipeNonces`, `rawMasterNonce`, `verifyIdempKey`, `receiveNonce`, `millingNonce`, `workerNonce`, `attNonce`, `editAttNonce`, `delAttNonces`, `recipeNonce`, `batchNonce`, `batchApprovalNonces`, `pkgNonce` + `pkgRef`, `reviewPkgNonces`, `dispatchNonce`); persisted `pkgRef` across failed retries; converted fire-and-forget `runAction` handlers to `async/await` so forms and nonces clear only when `ok === true`.

### Priority 2 — Strict Centralized Action-to-Table Allowlist

- `/backend/app/action_registry.py` defines `GOVERNED_ACTION_REGISTRY` (`127` `GovernedActionSpec` entries covering Groups `00`–`14`).
- `AppsScriptBridge.execute_governed_write` validates:
  1. Action exists in `GOVERNED_ACTION_REGISTRY` (`403 UNREGISTERED_GOVERNED_ACTION`).
  2. `target_tab == spec.target_tab` (`422 ACTION_TABLE_MISMATCH`).
  3. `id_field == spec.id_field` (`422 ACTION_ID_FIELD_MISMATCH`).
  4. All requested `invalidate_tabs` belong to `spec.allowed_invalidate_tabs` and are not forbidden scratch tabs (`422 UNAUTHORIZED_INVALIDATION_TAB`).
- **Defect Remediated During Static Cross-Check:** `backend/app/routers/stock.py` line `609` dispatches `action="RECONCILE_WAREHOUSE_STOCK"` targeting `SalesmanStockLedger` (`id_field="stock_txn_id"`), which was missing from `GOVERNED_ACTION_REGISTRY`. Registered `RECONCILE_WAREHOUSE_STOCK` in `/backend/app/action_registry.py`.

### Priority 3 — Request/Response Correlation & Confirmation Validation

- `/backend/app/apps_script_bridge.py`:
  - `_NoRedirectHandler` blocks HTTP `3xx` redirects (`502 APPS_SCRIPT_REDIRECT_BLOCKED_{code}`).
  - Rejects empty or non-JSON-object HTTP responses cleanly into `504 PENDING_UNKNOWN` (`retryable=True`).
  - Validates echoed `correlation_id` (`504 RESPONSE_CORRELATION_MISMATCH`), `nonce`/`idempotency_key` (`504 RESPONSE_NONCE_MISMATCH`), `action` (`502 RESPONSE_ACTION_MISMATCH`), and `target_tab` (`502 RESPONSE_TABLE_MISMATCH`).
  - Enforces `spec.requires_allocated_id` (`504 MISSING_ALLOCATED_ID`) and `_validate_id_format` against `spec.locked_prefix` (plus documented legacy prefix aliases for existing tables, `504 INVALID_ALLOCATED_ID_FORMAT`).
  - Only HTTP `200` + `status == "CONFIRMED"` + validated read-back produces `CONFIRMED`. HTTP `5xx` or network/timeout exceptions return `504 PENDING_UNKNOWN` instructing safe retry with the same nonce; HTTP `4xx` / explicit `"REJECTED"` returns fail-closed rejection (`Form data was NOT SAVED`).

### Priority 4 — Explicit Transaction-Specific Read-Back Verification

- `ReadBackSpec` and `ChildTabCheck` in `/backend/app/action_registry.py` define per-action verification requirements, executed by `_verify_readback` in `/backend/app/apps_script_bridge.py` (`fresh=True` after `db.invalidate_tab_cache`):
  - **Primary Row Presence:** Matches by `spec.id_field == lookup_id` or `primary_match_fields` (e.g., `jti`, `user_id`, `attendance_date`).
  - **State Assertions:** Verifies post-write state values (e.g., `status`, `approval_status`, `txn_status`, `bill_status`, `delivery_status`, `quality_status`, `active`, `is_closed`, `materials_issued`, `discrepancy_approved`) using `_normalize_scalar` and `_lookup_expected_value`.
  - **Child / Ledger Tab Checks:** Verifies foreign-key linked rows and minimum row counts (e.g., `PurchaseOrderItems`, `GoodsReceiptItems`, `SupplierReturnItems`, `CustomerReturnItems`, `SaleItems`, `SalesOrderItems`, `SalesmanStockLedger`, `ProductionStockLedger`, `LotMovements`, `AuthUsers`, `PayrollItems`, `SalaryReceipts`, `ProductionBatches`).
  - **Double-Entry Balance Assertion:** For `POST_JOURNAL_VOUCHER` and `REVERSE_JOURNAL_VOUCHER`, sums `Decimal(debit_amount)` vs `Decimal(credit_amount)` across `JournalLines` for the `journal_id` and fails closed with `504 READ_BACK_UNCONFIRMED` if `abs(tot_deb - tot_crd) > Decimal("0.01")`.

### Priority 5 — Database Registry Completion (Verified Evidence Only)

- `/backend/app/schema_registry.py` separates:
  - **Verified Tables (`REQUIRED_TABS`):** `VERIFIED_CORE` headers sourced directly from `/backend/app/sheets.py`, `/docs/SALES_MANAGEMENT_SCHEMA.md`, and `/docs/workforceSchemaUpgrade_2026-11-03-v1.gs`.
  - **Documented Variances (`SCHEMA_HEADER_VARIANCES`):** `Suppliers` (`12` columns in `REQUIRED_TABS` vs `14` fields including `payment_terms` and `opening_balance` used in `purchasing.py`) marked `CONFLICT_RECONCILIATION_REQUIRED`.
  - **Unverified Extended v2.1 Tabs (`PENDING_OWNER_MAPPING_TABS`):** `25` entries (`headers: None`, `auto_create: False`) across Groups `00`, `01`, `04`, `05`, `06`, `07`, `08`, `09`, `11`, `12`, `13`, `14` — zero fabricated Row-1 headers.
  - **Prefix Collisions (`TAB_RECONCILIATION_CONFLICTS`):** `EXC` (`ExceptionRegister` vs `ExceptionLogs`) and `PKG_PREFIX_COLLISION` (`PKG` -> `PackagingMaterials` vs `PKB` -> `PackagingBatches`) explicitly surfaced via `GET /api/v2/meta/schema-registry` and blocked on writes until reconciled.

### Priority 6 — Legacy Write Path & Route Guard Audit

- Static Python AST + regex inspection across all `52` files in `backend/app/`:
  - `0` direct `db.append_record`, `db.update_record`, `db.delete_record`, `generate_id`, `get_next_id`, or `allocate_bill_number` calls outside `/backend/app/sheets.py` (`IdAllocations` & testing-only `AuditLog` fallback).
  - Removed remaining fallback reads to non-canonical `"RawMaterialsMaster"` in `/backend/app/routers/sales.py:212` and `/backend/app/accounting/reconciliation.py:156`.
  - Audited all `120` `@router.(post|put|patch|delete)` endpoints across `/backend/app/routers/`:
    - Added `dependencies=[Depends(require_sheets_connection)]` to `POST /api/auth/change-password` in `/backend/app/routers/auth.py`.
    - Remaining `3` mutating router endpoints without `require_sheets_connection` are intentional: `POST /api/audit-logs` (`audit.py:43`, returns HTTP `410 Gone`), `POST /api/auth/login` (`auth.py:64`, handles `429`/disconnected Sheets explicitly), and `POST /api/auth/logout` (`auth.py:137`, revokes session in memory immediately).
    - Every operational mutating endpoint enforces authentication and role/module RBAC (`OWNER_ADMIN` sole approval/payroll/policy/period-close owner; `PA` blocked from confidential payroll/bank records and accounting writes; `ACCOUNTS` scoped to minimal `APPROVED_ADVANCE_DISBURSEMENT` fields; `AUDITOR` strictly read-only).

### Priority 7 — Fail-Closed Behavior

- Disconnected Google Sheets -> `503` via `require_sheets_connection` (no silent in-memory or SQLite/MongoDB business fallback).
- Unconfigured Apps Script bridge -> `503 APPS_SCRIPT_BRIDGE_UNCONFIGURED` (`dependency: "APPS_SCRIPT_DEPENDENCY"`).
- Target tab in `PENDING_OWNER_MAPPING_TABS` -> `503 PENDING_OWNER_MAPPING` / `CONFLICT_RECONCILIATION_REQUIRED`.
- Forbidden scratch tab (`KS_P1_`, `KS_P2_`, `KS_P3_`, `DBV5_` except `DBV5_FIELD_DICTIONARY_3074`, `DB_`) -> `403 SCRATCH_TAB_FORBIDDEN`.
- Unapproved CA policies (`hsn_gst_tax_rates`, `inventory_valuation_method`, `overhead_and_labour_allocation_basis`, `depreciation_policy`) -> `PermissionError` / `409` on automated posting gates.

---

## 4. Static Verification Summary (Read-Only Checks Only)

All checks below ran cleanly after the final code edits (no tests, builds, or linters were run):

| Check | Scope | Result |
|---|---|---|
| Python `ast.parse` syntax check | All `52` `.py` files in `backend/app/` | `52` files checked; `0` syntax errors |
| Direct DB mutation & ID-alloc scan | `backend/app/` excluding `sheets.py` | `0` external calls |
| Action registry AST cross-check | `GOVERNED_ACTION_REGISTRY` (`127` specs) vs `132` call sites | `0` registry mismatches (`1` dynamic ternary `REACTIVATE_USER`/`DEACTIVATE_USER` verified against both specs) |
| Mutating route connection & auth audit | All `120` `@router.(post\|put\|patch\|delete)` routes | `117/120` have `require_sheets_connection` (`audit.py` `410`, `login`, `logout` excepted); `119/120` auth/RBAC guarded (`login` excepted) |
| Legacy `RawMaterialsMaster` fallback check | `backend/app/` active modules | `0` live code reads (`costing.py` comments only) |
| Frontend mutating call idempotency scan | All `62` `.ts`/`.tsx` files in `src/` | `0` `apiFetch`/`apiRequest` POST/PUT/PATCH/DELETE calls missing `idempotencyKey`/`nonce`; `0` missing `createSubmissionNonce`/`isUnknownOutcomeError` imports; `0` `alert(`/`window.alert(`/`window.open(` calls |

---

## 5. Key Files Modified Across Backend & Frontend

- **Backend Core Governance:** `/backend/app/action_registry.py`, `/backend/app/apps_script_bridge.py`, `/backend/app/schema_registry.py`, `/backend/app/sheets.py`, `/backend/app/auth.py`, `/backend/app/permissions.py`, `/backend/app/user_service.py`, `/backend/app/accounting/journal_engine.py`, `/backend/app/accounting/postings.py`, `/backend/app/accounting/reconciliation.py`, `/backend/app/accounting/customer_ledger.py`
- **Backend Routers:** `/backend/app/routers/{accounting,approvals,auth,closing,customers,expenses,production,products,purchasing,quality,salary,sales,stock,users,v2_erp,visits,workforce}.py`
- **Frontend Core & Context:** `/src/services/api.ts`, `/src/context/StoreContext.tsx`, `/src/types/index.ts`, `/src/App.tsx`, `/src/components/Header.tsx`, `/src/components/salesman/MobileOrderWizard.tsx`
- **Frontend Views:**
  - `/src/views/{Accounting,Approvals,Attendance,Closing,Customers,ErpOperationsHub,Expenses,Production,Products,Purchasing,Quality,Salary,Sales,Stock,Users,Visits,Workforce}View.tsx`
  - `/src/employee/views/{EmployeeOverview,MyAttendance,MyProfile,MyProjects,MyTasks}View.tsx`
- **Documentation:** `/docs/ZIP35_CORRECTIVE_IMPLEMENTATION_HANDOVER_REPORT.md`

---

## 6. Unresolved Owner, CA, Schema & Apps Script Dependencies (Priority 8)

The following external decisions and artifacts are required before enabling governed writes against the live ERP:

1. **Apps Script Single-Write-Owner Web App (`WebAppBridge.gs` — Not Created/Deployed per Restriction):**
   - Implement `doPost(e)` verifying `X-KS-Signature` (HMAC-SHA256 over raw body), deduplicating on `nonce` / `X-KS-Idempotency-Key` + `payload_hash` against an idempotency ledger (`IdAllocations`), allocating sequential IDs for all `LOCKED_32_ID_PREFIXES`, writing target + child rows atomically with `LockService`, posting balanced `JournalHeaders`/`JournalLines`, appending `AuditLog`, and echoing `{ status: "CONFIRMED" | "REJECTED", correlation_id, nonce, action, target_tab, allocated_id, record }`.
   - Deploy as Google Apps Script Web App (`https://script.google.com/.../exec`) and configure on staging/production Render:
     - `SALES_APPS_SCRIPT_ENABLED=true`
     - `SALES_APPS_SCRIPT_WEBAPP_URL=https://...`
     - `SALES_APPS_SCRIPT_SHARED_SECRET=<32+ character shared HMAC secret>`
     - `SALES_APPS_SCRIPT_TIMEOUT_SECONDS=15`

2. **Unapproved CA & Owner Financial Policies (`PENDING_CA_APPROVAL` in `DEFAULT_CA_POLICIES`):**
   - `hsn_gst_tax_rates`: Needs CA-signed HSN & GST slab schedule (`EXEMPT_0` / `GST_5` / `GST_12` / `GST_18` / `CUSTOM_BY_HSN`). Automated marketplace GST journal posting remains blocked (`409`) until approved.
   - `inventory_valuation_method`: Needs CA selection (`FIFO` vs `WEIGHTED_AVERAGE`).
   - `overhead_and_labour_allocation_basis`: Needs CA sign-off (`DIRECT_KG` vs `BATCH_HOURS` vs `STANDARD_ABSORPTION`).
   - `depreciation_policy`: Needs CA sign-off (`WDV_INCOME_TAX` vs `SLM_COMPANIES_ACT`).

3. **Unmapped `PENDING_OWNER_MAPPING` Tabs (`25` Entries — Writes Fail Closed `503`):**
   - Canonical `.xlsx` Row-1 headers must be supplied by Owner before activating writes for:
     `ProductSKUs`, `PackagingMaterials`, `MaterialConsumptions`, `ProductionOutputs`, `ProductionLosses`, `ProductionWorkEntries`, `QualityChecks_IPQC`, `QualityChecks_FGQC`, `PackagingOutputs`, `SalesOrders`, `SalesOrderItems`, `PaymentAllocations`, `Employees`, `SalaryPayments`, `EmployeeAdvances`, `DistributionDispatches`, `MarketplaceSettlements`, `ComplianceRecords`, `AssetsMaintenance`, `ExceptionRegister` / `ExceptionLogs`, `RPT_TrialBalance`, `RPT_StockStatus`, `RPT_SalesAndReceivables`, `DBV5_FIELD_DICTIONARY_3074`.

4. **Owner Reconciliation Conflicts (`CONFLICT_RECONCILIATION_REQUIRED`):**
   - **Exception Tab Name (`EXC`):** Confirm whether the authoritative workbook tab is `ExceptionRegister` (snapshot) or `ExceptionLogs` (earlier draft) and provide canonical Row-1 headers.
   - **`Suppliers` Column Variance:** Reconcile `REQUIRED_TABS["Suppliers"]` (`12` columns) vs operational router payload (`14` fields including `payment_terms` and `opening_balance`) against physical Row-1 headers.
   - **Legacy vs Locked ID Prefixes:** Confirm transitional cutover plan in Apps Script for legacy prefixes (`CUS`->`CUST`, `JRN`->`JV`, `JLN`->`JVL`, `PKG`->`PKB`, `PAY`->`RCPT`, `PRB`->`PB`, `PST`->`MOV`, `RWM`->`RM`, `ITEM`->`INVI`, `SALE`->`INV`).

5. **UX Consistency Follow-Up (Non-Blocking Notice):**
   - `window.confirm` / `prompt` / `window.prompt` still exist in `AttendanceView.tsx`, `PurchasingView.tsx`, `SalesView.tsx`, `StockView.tsx`, `UsersView.tsx`, and `WorkforceView.tsx` (zero `alert`/`window.alert`/`window.open` remain). Replace with inline confirmation/reason modals in a future UI polish pass if desired.

---

## 7. Recommended Next Steps Upon Authorization

1. **Owner & CA Review:** Approve `DEFAULT_CA_POLICIES` values, confirm `EXC` tab naming + `Suppliers` header count, and supply verified Row-1 headers for active Group `00`–`14` tabs.
2. **Test & Build Verification (When Explicitly Authorized):** Run clean frontend dependency installation + TypeScript lint + Vite build, and run backend `pytest` suite against mocked/staging Apps Script bridge responses covering HTTP `409`, `403`, `503`, `504`, `READ_BACK_UNCONFIRMED`, and double-entry `JournalLines` imbalance rejection.
3. **Staging Deployment:** Deploy `WebAppBridge.gs` to a staging spreadsheet copy, set `SALES_APPS_SCRIPT_*` environment variables, verify end-to-end idempotent retries and read-back confirmation, then review diffs before any GitHub push or Render deployment.
