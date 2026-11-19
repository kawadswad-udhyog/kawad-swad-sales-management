# Kawad Swad ERP — Blueprint v2.1 Corrective Implementation Handover Report

**Status:** Code & Documentation Complete (Pending Owner / CA Decisions, Apps Script `doPost` Handler Deployment, & Environment Wiring)  
**Target Architecture:** Upgrade Blueprint v2.1 + Database Blueprint v2.0 + Master Manual v2.0 + Corrective Implementation Prompt v1.1  

---

## 1. Execution & Verification Boundary (Mandatory Statement)

```text
TESTS NOT RUN AS INSTRUCTED. LIVE GOOGLE SHEETS NOT ACCESSED. APPS SCRIPT NOT DEPLOYED. GITHUB NOT PUSHED. RENDER NOT DEPLOYED. PRODUCTION DATA NOT MODIFIED.
```

> All observations below are grounded exclusively in static source code inspection and read-only `grep` checks against the isolated workspace. No automated test suite, linter, TypeScript compiler, production build, or live runtime execution was performed.

---

## 2. Executive Summary

This corrective implementation pass eliminates direct FastAPI business writes to Google Sheets and establishes Google Apps Script as the single governed write owner across the ERP (`backend/app` and `src/`).

Key outcomes implemented in code:
1. **Single Governed Write Owner (`apps_script_bridge`)**: Direct FastAPI Google Sheets mutation calls (`db.append_record`, `db.update_record`, `db.delete_record`, `db.generate_id`, `db.get_next_id`, `db.allocate_bill_number`, `make_id`) were eliminated across `backend/app/`. All operational routers and accounting engines delegate mutations to `apps_script_bridge.execute_governed_write` / `apps_script_bridge.delegate_governed_write` with fail-closed `HTTP 503` (`BLOCKED_PENDING_OWNER_SETUP` / `APPS_SCRIPT_DEPENDENCY`) when the signed bridge is unconfigured.
2. **Official 15 Functional Database Groups & 32 Locked ID Prefixes**: `schema_registry.py` exposes `DATABASE_GROUPS_15` (`00`..`14`) across the cleaned 255-tab architecture, `LOCKED_32_ID_PREFIXES`, `FORBIDDEN_SCRATCH_PREFIXES` (`KS_P1_`, `KS_P2_`, `KS_P3_`, `DBV5_`, `DB_`), `PENDING_OWNER_MAPPING_TABS`, and `TAB_RECONCILIATION_CONFLICTS` (surfacing `EXC`: `ExceptionRegister` vs `ExceptionLogs` as `CONFLICT_RECONCILIATION_REQUIRED`). Zero unapproved scratch prefixes (`DSP`/`DISP`, `CHN`, `CMP`, `AST`, `RPT`) remain in frontend nonces or backend registries.
3. **12-Role RBAC, Strict Confidentiality & `AUDITOR` Read-Only Enforcement**: Canonical 12 roles enforced in `permissions.py`, `/api/v2`, legacy routers, and React views using `resolveCanonical12Role(...)`. `OWNER_ADMIN` holds sole authority over confidential payroll/salary/bank/personal identity records and approval decisions; `PA` is stripped of confidential payroll/salary/bank views; `ACCOUNTS` is restricted to minimal `APPROVED_ADVANCE_DISBURSEMENT` fields; `AUDITOR` is strictly read-only across both backend and frontend.
4. **Expanded `/api/v2` & Frontend Alignment**: Added governed `/api/v2` operational routes for procurement, store ledger/adjustments, milling, production, sales orders/invoices (with `ProductLots` `RELEASED` gate), and double-entry journal vouchers (`validate_journal_lines`), and aligned frontend types, API client, store context, global banners, and views.

---

## 3. Architecture: Signed Single-Write-Owner Apps Script Bridge

Implemented in `/backend/app/apps_script_bridge.py` and configured in `/backend/app/config.py`:

### 3.1 Configuration & Fail-Closed Startup
- `SALES_APPS_SCRIPT_ENABLED` (boolean; `"true"` / `"1"` / `"yes"`)
- `SALES_APPS_SCRIPT_WEBAPP_URL` (`https://` enforced in production; non-TLS allowed only on `localhost` / `127.0.0.1` / `::1` when `SALES_ENV != "production"`)
- `SALES_APPS_SCRIPT_SHARED_SECRET` (minimum `32` characters for HMAC-SHA256)
- `SALES_APPS_SCRIPT_TIMEOUT_SECONDS` (bounded between `3.0` and `30.0` seconds; default `15.0`)
- `SALES_CA_POLICY_CONFIG_JSON` (optional JSON override for CA/Owner policies)

### 3.2 Request Signing, Idempotency & Safety Guarantees
- **HMAC-SHA256 Envelope**: Canonical JSON envelope (`action`, `target_tab`, `nonce`, `correlation_id`, `actor_user_id`, `actor_role`, `timestamp`, `payload`) signed via `HMAC-SHA256` and transmitted with headers `X-KS-Signature`, `X-KS-Correlation-Id`, and `X-KS-Idempotency-Key`.
- **Redirect Blocker**: `_NoRedirectHandler` blocks HTTP `3xx` redirects (`APPS_SCRIPT_REDIRECT_BLOCKED_{code}`, HTTP `502`) so signed HMAC envelopes are never forwarded across redirect targets.
- **Client `nonce` Preservation**: Client-supplied `nonce` / `X-KS-Idempotency-Key` / `X-Idempotency-Key` is preserved unchanged across retries; missing nonce returns `422 MISSING_IDEMPOTENCY_NONCE` on `execute_governed_write`.
- **Unmapped / Conflicting Tab Blocker**: Writes targeting any tab in `PENDING_OWNER_MAPPING_TABS` fail closed with `503 BLOCKED_PENDING_OWNER_SETUP` (`PENDING_OWNER_MAPPING` or `CONFLICT_RECONCILIATION_REQUIRED`).
- **Forbidden Scratch Tab Blocker**: Writes or `/api/v2` queries targeting any tab matching `FORBIDDEN_SCRATCH_PREFIXES` (`KS_P1_`, `KS_P2_`, `KS_P3_`, `DBV5_`, `DB_`, except `DBV5_FIELD_DICTIONARY_3074`) fail closed with `403 SCRATCH_TAB_FORBIDDEN`.
- **Explicit Outcome States**:
  - `CONFIRMED`: Optionally verified via `db.get_records(target_tab, fresh=True)` read-back matching `id_field == allocated_id`, followed by immediate `db.invalidate_tab_cache(...)` across `target_tab` and `invalidate_tabs`.
  - `REJECTED`: HTTP `4xx` or non-confirmed Apps Script status (fail-closed; `Form data was NOT SAVED`).
  - `PENDING_UNKNOWN`: HTTP `5xx`, network/timeout errors, or read-back mismatch (`504 READ_BACK_UNCONFIRMED` / `APPS_SCRIPT_UNKNOWN_OUTCOME`, `retryable=True`; instructs caller to retry safely with the same `nonce`).
  - `BLOCKED_PENDING_OWNER_SETUP`: Missing bridge configuration (`503 APPS_SCRIPT_BRIDGE_UNCONFIGURED`, `dependency="APPS_SCRIPT_DEPENDENCY"`) or unmapped/conflicting target tab (`OWNER_SCHEMA_MAPPING_DEPENDENCY`).
- **Audit Logging (`db.log_audit`)**: In `/backend/app/sheets.py`, `db.log_audit(...)` emits structured Python telemetry without direct Google Sheets writes in non-testing runtimes (`AuditLog` mutations occur atomically inside Apps Script governed writes). Direct client-authored `POST /api/audit-logs` returns `410 Gone`.

---

## 4. Backend Changes Summary

### 4.1 Static Verification of Eliminated Direct FastAPI Writes
Read-only repository check confirmed **0 remaining direct Sheets mutation/ID-allocation calls** in `backend/app/`:
- Command: `grep -rnE "db\.(append_record|update_record|delete_record|generate_id|get_next_id|allocate_bill_number)|make_id\(" backend/app/` -> exit code `1` (0 matches).

### 4.2 Modules & Routers Updated for Governed Write Delegation
| File | Governed Delegation / Changes |
|---|---|
| `/backend/app/config.py` | Added `SALES_APPS_SCRIPT_ENABLED`, `SALES_APPS_SCRIPT_WEBAPP_URL`, `SALES_APPS_SCRIPT_SHARED_SECRET`, `SALES_APPS_SCRIPT_TIMEOUT_SECONDS`, `SALES_CA_POLICY_CONFIG_JSON`. |
| `/backend/app/apps_script_bridge.py` | Signed HMAC-SHA256 bridge, `_NoRedirectHandler`, fail-closed tab/config guards, read-back verification, cache invalidation, `delegate_governed_write` helper. |
| `/backend/app/schema_registry.py` | `DATABASE_GROUPS_15` (`00`..`14`), `LOCKED_32_ID_PREFIXES`, `FORBIDDEN_SCRATCH_PREFIXES`, `CONFIDENTIAL_TABS_NO_CACHE`, `CONFIDENTIAL_PERSONAL_FIELDS`, `ACCOUNTS_ADVANCE_DISBURSEMENT_ALLOWED_FIELDS`, `EXTENDED_V2_TAB_CONTRACTS`, `PENDING_OWNER_MAPPING_TABS`, `TAB_RECONCILIATION_CONFLICTS`, `DEFAULT_CA_POLICIES`, retail pack weights `{200, 500, 1000}`g, lot quality states, gig statuses. |
| `/backend/app/permissions.py` | Canonical 12-role matrix (`V2_ROLE_PERMISSIONS`), `CANONICAL_ROLE_V2_MAP`, `OWNER_ONLY_PERMISSIONS`, `filter_confidential_records`, `require_module_action`, `require_owner`. |
| `/backend/app/sheets.py` | Read/query + cache invalidation + non-mutating `db.log_audit` in production/Sheets mode (no direct router writes). |
| `/backend/app/auth.py` | Delegates `REVOKE_TOKEN` and `REVOKE_USER_SESSIONS` via `apps_script_bridge.execute_governed_write`. |
| `/backend/app/accounting/journal_engine.py` | `validate_journal_lines` double-entry balance check; delegates `POST_JOURNAL_VOUCHER` & `REVERSE_JOURNAL_VOUCHER` via `delegate_governed_write`. |
| `/backend/app/accounting/customer_ledger.py` | Delegates `RESERVE_CREDIT_APPROVAL`, `CONSUME_CREDIT_APPROVAL`, and `RELEASE_CREDIT_APPROVAL` via `delegate_governed_write`. |
| `/backend/app/routers/auth.py` | Delegates `LOGIN` (token/audit tracking if governed) and `CHANGE_PASSWORD`. |
| `/backend/app/routers/users.py` | Delegates custom role CRUD (`CREATE_CUSTOM_ROLE`, `UPDATE_CUSTOM_ROLE`, `DELETE_CUSTOM_ROLE`, `RECONCILE_ROLE_ALIAS`); routes user lifecycle mutations through `ApprovalRequests` / Apps Script. |
| `/backend/app/routers/approvals.py` | Delegates `CREATE_APPROVAL_REQUEST`, `REJECT_APPROVAL_REQUEST`, `APPROVE_AND_EXECUTE_REQUEST`; redacts sensitive keys for PA views; Owner-only decision gating. |
| `/backend/app/routers/products.py` | Delegates `CREATE_PRODUCT`, `UPDATE_PRODUCT`. |
| `/backend/app/routers/customers.py` | Delegates `CREATE_CUSTOMER`, `UPDATE_CUSTOMER`. |
| `/backend/app/routers/purchasing.py` | Delegates `CREATE_SUPPLIER`, `UPDATE_SUPPLIER`, `CREATE_PURCHASE_ORDER`, `CANCEL_PURCHASE_ORDER`, `RECEIVE_GOODS`, `RECORD_SUPPLIER_BILL`, `RECORD_SUPPLIER_PAYMENT`, `APPLY_SUPPLIER_ADVANCE`, `CREATE_SUPPLIER_RETURN`. |
| `/backend/app/routers/production.py` | Delegates raw material master/rate/opening stock/receive/adjustments, milling & recovery, worker & attendance records, recipe creation & version confirmation, batch creation/issue/approval, finished goods adjustments, packaging & recovery/discrepancy, and production dispatch/reconciliation. |
| `/backend/app/routers/quality.py` | Delegates `CREATE_QUALITY_CHECK`, `CREATE_PRODUCT_LOT`, `UPDATE_LOT_STATUS`, `CREATE_CUSTOMER_RETURN`, `CREATE_COMPLAINT_OR_RECALL`, `CLOSE_COMPLAINT`. |
| `/backend/app/routers/stock.py` | Delegates `RECORD_STOCK_MOVEMENT`, discrepancies/review, opening reconciliation, and van loading pass create/accept/discrepancy/cancel. |
| `/backend/app/routers/sales.py` | Delegates `CREATE_SALE`, `MARK_SALE_COMPLETE`, `RESUME_SALE`, `CANCEL_SALE`, `RECORD_SALE_PAYMENT`, `CREATE_SALES_ORDER`, `CONFIRM_SALES_ORDER`. |
| `/backend/app/routers/expenses.py` | Delegates `SUBMIT_EXPENSE`, `REVIEW_EXPENSE`. |
| `/backend/app/routers/visits.py` | Delegates `LOG_SHOP_VISIT` / `LOG_VISIT`. |
| `/backend/app/routers/closing.py` | Delegates `SUBMIT_DAILY_CLOSING`, `REVIEW_DAILY_CLOSING` / `REVIEW_CLOSING`. |
| `/backend/app/routers/salary.py` | Delegates `CREATE_SALARY_INCENTIVE`, `APPROVE_SALARY_INCENTIVE`, and payment; confidential Owner-only enforcement. |
| `/backend/app/routers/accounting.py` | Delegates `CLOSE_ACCOUNTING_PERIOD` (and journal/voucher routes via `journal_engine`). |
| `/backend/app/routers/workforce.py` | Delegates self-service task/attendance/profile/milestone writes, labour CRUD/attendance/work entries, task/project/milestone reviews, `UPSERT_SALARY_STRUCTURE`, `CALCULATE_PAYROLL`, `UPDATE_PAYROLL_ITEM`, `APPROVE_PAYROLL`, `RECORD_WORKFORCE_PAYMENT`. |
| `/backend/app/routers/v2_erp.py` | Blueprint v2.1 API surface (see Section 4.3). |

### 4.3 `/api/v2` Endpoints Inventory (`/backend/app/routers/v2_erp.py`)
- **Meta & Governance**:
  - `GET /api/v2/meta/capabilities` — Role permissions, `DATABASE_GROUPS_15`, `LOCKED_32_ID_PREFIXES`, valid pack weights `{200, 500, 1000}`g, `apps_script_bridge_configured`, `pending_ca_policies`.
  - `GET /api/v2/meta/schema-registry` — Cleaned 255-tab catalog, `pending_owner_mapping_tabs`, `tab_reconciliation_conflicts`, `table_registry_summary`, `table_schema_registry` (redacts confidential headers as `REDACTED_NON_OWNER` for non-owners).
  - `GET /api/v2/meta/policies` & `PUT /api/v2/meta/policies/{policy_key}` (`OWNER_ADMIN` only; governed write `UPDATE_CA_POLICY` -> `Settings`).
  - `GET /api/v2/control/audit-logs` & `GET /api/v2/control/exceptions` (exposes `EXC` `CONFLICT_RECONCILIATION_REQUIRED` metadata).
- **Official Reports**:
  - `GET /api/v2/reports/trial-balance` (`RPT_TrialBalance`)
  - `GET /api/v2/reports/stock-status` (`RPT_StockStatus`)
  - `GET /api/v2/reports/sales-receivables` (`RPT_SalesAndReceivables`)
- **Procurement, Store, Milling & Production**:
  - `POST /api/v2/procurement/purchase-orders` (`CREATE_PURCHASE_ORDER`)
  - `POST /api/v2/procurement/goods-receipts` (`CREATE_GOODS_RECEIPT`)
  - `GET /api/v2/store/ledger` & `POST /api/v2/store/stock-adjustments` (`REQUEST_STOCK_ADJUSTMENT`)
  - `POST /api/v2/milling/batches` (`RECORD_MILLING_BATCH`)
  - `POST /api/v2/production/batches` (`CREATE_PRODUCTION_BATCH`)
- **Packaging, Quality-Gated Logistics & Sales**:
  - `GET /api/v2/packaging/batches` & `POST /api/v2/packaging/batches` (`RECORD_PACKAGING_BATCH`; rejects non-`RELEASED` lot refs; requires >0 packets in `{200g, 500g, 1000g}`)
  - `GET /api/v2/logistics/dispatches` & `POST /api/v2/logistics/dispatches` (`RECORD_DISTRIBUTION_DISPATCH`; blocks unless lot `quality_status == "RELEASED"`)
  - `POST /api/v2/sales/orders` (`CREATE_SALES_ORDER`)
  - `POST /api/v2/sales/invoices` (`CREATE_SALES_INVOICE`; blocks billing any lot where `quality_status != "RELEASED"`)
- **Channels, Compliance, Assets & Accounting**:
  - `GET /api/v2/channels/settlements` & `POST /api/v2/channels/settlements` (`RECORD_MARKETPLACE_SETTLEMENT`; blocks `apply_automated_gst_posting=true` unless CA policy `hsn_gst_tax_rates` is `APPROVED`)
  - `GET /api/v2/compliance/records` & `POST /api/v2/compliance/records` (`RECORD_COMPLIANCE_ITEM`)
  - `GET /api/v2/assets/maintenance` & `POST /api/v2/assets/maintenance` (`RECORD_ASSET_MAINTENANCE`)
  - `POST /api/v2/accounting/journals` (`POST_JOURNAL_VOUCHER`; validates double-entry balance)
- **Workforce Confidentiality Separation & Gig Workflow**:
  - `GET /api/v2/workforce/confidential/salary-payments` (`OWNER_ADMIN` only)
  - `GET /api/v2/workforce/advances` & `POST /api/v2/workforce/advances/{advance_id}/disburse` (`DISBURSE_APPROVED_ADVANCE`; `OWNER_ADMIN` full / `ACCOUNTS` `APPROVED_ADVANCE_DISBURSEMENT` minimal fields only; hidden from `PA`, `HR`, `AUDITOR`)
  - `GET /api/v2/workforce/gig-entries`, `POST /api/v2/workforce/gig-entries` (`SUBMIT_GIG_WORK_ENTRY`), `POST .../verify` (`VERIFY_GIG_WORK_ENTRY`), `POST .../pay` (`PAY_GIG_WORK_ENTRY`, `OWNER_ADMIN` only)

---

## 5. Official 15 Functional Database Groups & 32 Locked ID Prefixes

### 5.1 Official 15 Groups (`DATABASE_GROUPS_15`)
| Code | Group Name | Module Key | Header Mapping Status |
|---|---|---|---|
| `00` | Control & Setup | `control` | `VERIFIED_CORE_AND_PENDING_XLSX` |
| `01` | Business & Master Data | `catalogue` | `VERIFIED_CORE_AND_PENDING_EXTENDED` |
| `02` | Procurement & Supplier | `procurement` | `VERIFIED_CORE` |
| `03` | Inventory & Warehousing | `store` | `VERIFIED_CORE` |
| `04` | Milling & Production | `production` | `VERIFIED_CORE_AND_PENDING_EXTENDED` |
| `05` | Quality & Food Safety | `quality` | `VERIFIED_CORE_AND_PENDING_EXTENDED` |
| `06` | Packaging & Finished Goods | `packaging` | `VERIFIED_CORE_AND_PENDING_EXTENDED` |
| `07` | Sales & Customer | `sales` | `VERIFIED_CORE_AND_PENDING_EXTENDED` |
| `08` | Channel, Marketplace & Marketing | `channels` | `PENDING_OWNER_MAPPING` |
| `09` | Distribution & Logistics | `logistics` | `VERIFIED_CORE_AND_PENDING_EXTENDED` |
| `10` | Finance & Accounting | `accounting` | `VERIFIED_CORE` |
| `11` | Workforce & Payroll | `workforce` | `VERIFIED_WORKFORCE_AND_PENDING_EXTENDED` |
| `12` | Governance, Compliance & Audit | `compliance_assets` | `VERIFIED_AUDIT_AND_PENDING_EXTENDED` |
| `13` | Assets, Environment & Risk | `compliance_assets` | `PENDING_OWNER_MAPPING` |
| `14` | Reports & Planning | `reports` | `PENDING_OWNER_MAPPING` |

### 5.2 Locked 32 Official ID Prefixes (`LOCKED_32_ID_PREFIXES`)
`PRD`, `SKU`, `RM`, `PKG`, `CUST`, `SUP`, `USR`, `EMP`, `LOT`, `MOV`, `PO`, `PB`, `MCON`, `POUT`, `PLOSS`, `PWE`, `IPQC`, `FGQC`, `PKB`, `PKOUT`, `SO`, `SOI`, `INV`, `INVI`, `RCPT`, `RCPTA`, `JV`, `JVL`, `SAL`, `EADV`, `AUD`, `EXC`.

- **Forbidden unapproved prefixes removed** (`grep` across `src/`, `backend/app/permissions.py`, `backend/app/schema_registry.py` returned `0` matches): `DSP` / `DISP`, `CHN`, `CMP`, `AST`, `RPT`.
- **`PENDING_OWNER_MAPPING` Tabs (Fail-Closed on Writes until Row-1 Headers Supplied)**:
  `ProductSKUs`, `PackagingMaterials`, `MaterialConsumptions`, `ProductionOutputs`, `ProductionLosses`, `ProductionWorkEntries`, `QualityChecks_IPQC`, `QualityChecks_FGQC`, `PackagingOutputs`, `SalesOrders`, `SalesOrderItems`, `PaymentAllocations`, `Employees`, `SalaryPayments`, `EmployeeAdvances`, `DistributionDispatches`, `MarketplaceSettlements`, `ComplianceRecords`, `AssetsMaintenance`, `RPT_TrialBalance`, `RPT_StockStatus`, `RPT_SalesAndReceivables`, `DBV5_FIELD_DICTIONARY_3074`.
- **`CONFLICT_RECONCILIATION_REQUIRED` (`EXC`)**:
  `ExceptionRegister` (Workbook Snapshot) vs `ExceptionLogs` (earlier blueprint draft). Writes fail closed until Owner confirms canonical tab name and Row-1 headers.

---

## 6. Frontend Changes Summary (`/src`)

| File | Summary of Changes |
|---|---|
| `/src/types/index.ts` | Extended `SchemaRegistryPayload` with `pending_owner_mapping_tabs`, `tab_reconciliation_conflicts`, `table_registry_summary`, and `table_schema_registry`; includes `BLOCKED_PENDING_OWNER_SETUP` status. |
| `/src/services/api.ts` | Added `apps_script_bridge_configured` on `BackendHealthResponse`, `nonce` & `ApiOutcomeUnknownError` preservation on `updateV2Policy`, plus helpers `fetchV2SchemaRegistry`, `createV2PurchaseOrder`, `createV2GoodsReceipt`, `fetchV2StoreLedger`, `createV2StockAdjustment`, `createV2MillingBatch`, `createV2ProductionBatch`, `createV2SalesOrder`, `createV2SalesInvoice`, `createV2JournalVoucher`. |
| `/src/context/StoreContext.tsx` | Exposes `appsScriptBridgeConfigured` populated from `/api/v2/meta/capabilities` & `/api/health` and cleared on `logout`. |
| `/src/components/Header.tsx` | Shows `Gateway Pending` status badge when `capabilities && !appsScriptBridgeConfigured` and `Apps Script Write Gateway` state inside the Diagnostics modal. |
| `/src/App.tsx` | Renders global `Apps Script Gateway Pending (BLOCKED_PENDING_OWNER_SETUP)` warning banner referencing `SALES_APPS_SCRIPT_ENABLED`, `SALES_APPS_SCRIPT_WEBAPP_URL`, and `SALES_APPS_SCRIPT_SHARED_SECRET`. |
| `/src/views/ErpOperationsHubView.tsx` | Replaced forbidden nonce prefixes (`DISP`, `CHN`, `CMP`, `AST`, `GIG_...`) with `MOV`, `STL`, `STAT`, `MAINT`, `PWE`; aligned `MODULE_META` group numbers (`channels` -> Group 08, `logistics` -> Group 09, `compliance_assets` -> Groups 12 & 13, `control_policies` -> Group 00); added `policyNonces`, `writesLocked` guards (`isAuditor \|\| !bridgeReady \|\| ...`), `!isAuditor` table header alignment, and `table_registry_summary` / `tab_reconciliation_conflicts` / `pending_owner_mapping_tabs` governance cards. |
| `/src/views/ApprovalsView.tsx` | Fixed inverted write-lock condition (`!isBackendConnected \|\| !isGoogleSheetsConnected \|\| !persistentWritesEnabled`) on approve/reject/retry/cancel buttons and standardized `canDecide` to `resolveCanonical12Role(currentUser?.role) === 'OWNER_ADMIN'`. |
| `/src/views/AccountingView.tsx` | Switched `isOwnerOrAdmin` to `resolveCanonical12Role` (`OWNER_ADMIN`) and added `writesLocked` guards on voucher reversal & live reconciliation controls. |
| `/src/views/WorkforceView.tsx` | Restricted confidential `payroll` & `receipts` tabs, `Run Monthly Payroll` action, `Base Pay` column, and confidential fetches exclusively to `OWNER_ADMIN` (never `PA`); added `isAuditor` guard. |
| `/src/views/SalaryView.tsx` | Enforced `OWNER_ADMIN` vs `AUDITOR` read-only (`PA` and non-owners blocked), normalized `FIELD_SALESMAN` filters via `resolveCanonical12Role`, added `writesLocked` guards, and replaced `window.prompt` with an inline payment reference disbursement form. |
| `/src/views/AttendanceView.tsx` | Normalized `isOwner` via `resolveCanonical12Role` (`OWNER_ADMIN`) and hid mutating Actions column for `AUDITOR`. |
| `/src/views/StockView.tsx` | Normalized `isManager` & `FIELD_SALESMAN` filters via `resolveCanonical12Role`; blocked van pass accept mutations for `AUDITOR`. |
| `/src/views/ExpensesView.tsx` & `/src/views/VisitsView.tsx` | Normalized role checks via `resolveCanonical12Role`, hid submission forms for `AUDITOR`, and applied `writesLocked` button guards. |
| `/src/employee/views/MySalaryView.tsx` & `/src/employee/views/EmployeeOverviewView.tsx` | Normalized `'SALESMAN' \|\| 'FIELD_SALESMAN'` role checks. |

---

## 7. Open Blockers Requiring Owner / CA / Apps Script Action

The following items **cannot** be completed from FastAPI/React alone and will remain fail-closed (`503` / `409`) until supplied or deployed:

1. **Apps Script Web App Deployment & Render Environment Variables (`APPS_SCRIPT_DEPENDENCY`)**:
   - Deploy the Google Apps Script Web App (`doPost`) bound to the authoritative spreadsheet with HMAC-SHA256 signature verification (`X-KS-Signature`), `nonce` idempotency table (`IdAllocations` / `IdempotencyLedger`), atomic sequential ID allocation for the 32 locked prefixes, and atomic `AuditLog` insertion.
   - Implement Apps Script `doPost` handlers for every `action` dispatched by `/api/v2` and legacy delegated routers (notably: `UPDATE_CA_POLICY`, `RECORD_PACKAGING_BATCH`, `RECORD_DISTRIBUTION_DISPATCH`, `RECORD_MARKETPLACE_SETTLEMENT`, `RECORD_COMPLIANCE_ITEM`, `RECORD_ASSET_MAINTENANCE`, `DISBURSE_APPROVED_ADVANCE`, `SUBMIT_GIG_WORK_ENTRY`, `VERIFY_GIG_WORK_ENTRY`, `PAY_GIG_WORK_ENTRY`, `REQUEST_STOCK_ADJUSTMENT`, `POST_JOURNAL_VOUCHER`, `REVERSE_JOURNAL_VOUCHER`, `APPROVE_AND_EXECUTE_REQUEST`, `REJECT_APPROVAL_REQUEST`, plus all legacy operational actions).
   - Configure on Render backend:
     - `SALES_APPS_SCRIPT_ENABLED=true`
     - `SALES_APPS_SCRIPT_WEBAPP_URL=https://...`
     - `SALES_APPS_SCRIPT_SHARED_SECRET=<32+ char secret matching Apps Script PropertiesService>`
     - `SALES_APPS_SCRIPT_TIMEOUT_SECONDS=15`

2. **CA / Owner Policy Sign-Off (`PENDING_CA_APPROVAL`)**:
   Default automated tax/valuation/costing/depreciation rules in `DEFAULT_CA_POLICIES` fail closed until approved by CA & Owner via `PUT /api/v2/meta/policies/{policy_key}` or `SALES_CA_POLICY_CONFIG_JSON`:
   - `hsn_gst_tax_rates` (`EXEMPT_0`, `GST_5`, `GST_12`, `GST_18`, `CUSTOM_BY_HSN`)
   - `inventory_valuation_method` (`FIFO`, `WEIGHTED_AVERAGE`)
   - `overhead_and_labour_allocation_basis` (`DIRECT_KG`, `BATCH_HOURS`, `STANDARD_ABSORPTION`)
   - `depreciation_policy` (`WDV_INCOME_TAX`, `SLM_COMPANIES_ACT`)

3. **Canonical Row-1 Headers for `PENDING_OWNER_MAPPING` Tabs (`OWNER_SCHEMA_MAPPING_DEPENDENCY`)**:
   Supply the exact Row-1 spreadsheet headers from the master `.xlsx` workbook for the 21 unmapped `PENDING_OWNER_MAPPING` tabs (Section 5.2) before enabling Apps Script writes to those sheets.

4. **Exception Tab Naming Reconciliation (`CONFLICT_RECONCILIATION_REQUIRED`)**:
   Confirm whether the live spreadsheet uses `ExceptionRegister` (Workbook Snapshot) or `ExceptionLogs` (earlier draft) and supply its Row-1 headers.

---

## 8. Recommended Verification Sequence Once Owner Approves Testing

1. Configure `SALES_APPS_SCRIPT_*` variables in a staging environment pointing to a test copy of the workbook and staging Apps Script deployment.
2. Run backend test suite (`pytest`) and verify all tests pass with mocked/staging Apps Script responses and fail-closed checks when unconfigured.
3. Run clean frontend install, TypeScript check/lint, and production Vite build (`npm ci`, `npm run lint`, `npm run build`).
4. Verify RBAC matrix end-to-end across `OWNER_ADMIN`, `PA` (verifying zero confidential salary/bank leakage), `ACCOUNTS` (verifying minimal advance-disbursement view only), `AUDITOR` (verifying 403/disabled mutations), and operational roles.
5. Reconcile `EXC` (`ExceptionRegister` vs `ExceptionLogs`) and `PENDING_OWNER_MAPPING` tabs, deploy Apps Script `doPost`, then promote via GitHub and Render.
