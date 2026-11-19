# Kawad Swad ERP — Master Registers & Decisions (`REG-06`, `REG-07`, `REG-09`, `REG-12`)

**Governing Constitution:** `/docs/MASTER_POLICY_CONSTITUTION_V1_2.md` (`POL-001`–`POL-028`)  
**Calculation Register:** `/docs/CALCULATION_REGISTER_REG03.md` (`CALC-001`–`CALC-032`)  
**Status Discipline:** Per Section 25 Testing Moratorium (`POL-028`) and Section 22.5 (`POL-027`), **no item is marked `VERIFIED` or `ACCEPTED`**. Only `IMPLEMENTED — NOT TESTED`, `BLOCKED`, or `PENDING_CA_APPROVAL` are used.

---

## 1. `REG-06` — Governed `/api/v2/*` API & Apps Script Action Register (36 Endpoints)

| # | HTTP | Endpoint (`/api/v2/...`) | Apps Script Action | Nonce Behavior | Target Sheet Tab(s) | Authorized Roles (12-Role Canonical) | Implementation Status |
|---|---|---|---|---|---|---|---|
| 1 | `GET` | `/meta/capabilities` | Read-only | N/A | `Settings` (policy config) | Any authenticated user | `IMPLEMENTED — NOT TESTED` |
| 2 | `GET` | `/meta/schema-registry` | Read-only | N/A | In-memory `schema_registry` (redacts confidential headers for non-owners) | Any authenticated user | `IMPLEMENTED — NOT TESTED` |
| 3 | `GET` | `/meta/policies` | Read-only | N/A | `Settings` / `DEFAULT_CA_POLICIES` | Any authenticated user | `IMPLEMENTED — NOT TESTED` |
| 4 | `PUT` | `/meta/policies/{policy_key}` | `UPDATE_CA_POLICY` | Required (`nonce` / `X-KS-Idempotency-Key`) | `Settings` | `OWNER_ADMIN` only | `IMPLEMENTED — NOT TESTED` |
| 5 | `GET` | `/reports/trial-balance` | Read-only | N/A | `RPT_TrialBalance` / `JournalLines` | `OWNER_ADMIN`, `PA`, `ACCOUNTS`, `AUDITOR` | `IMPLEMENTED — NOT TESTED` |
| 6 | `GET` | `/reports/stock-status` | Read-only | N/A | `RPT_StockStatus` / Stock Ledgers | `OWNER_ADMIN`, `PA`, `STORE`, `PRODUCTION`, `PACKAGING`, `SALES`, `AUDITOR` | `IMPLEMENTED — NOT TESTED` |
| 7 | `GET` | `/reports/sales-receivables` | Read-only | N/A | `RPT_SalesAndReceivables` / `Sales`, `Payments` | `OWNER_ADMIN`, `PA`, `ACCOUNTS`, `SALES`, `AUDITOR` | `IMPLEMENTED — NOT TESTED` |
| 8 | `GET` | `/packaging/batches` | Read-only | N/A | `PackagingBatches` | `OWNER_ADMIN`, `PA`, `PACKAGING`, `PRODUCTION`, `QUALITY`, `STORE`, `AUDITOR` | `IMPLEMENTED — NOT TESTED` |
| 9 | `POST` | `/packaging/batches` | `RECORD_PACKAGING_BATCH` | Required (`PKB` / `nonce`) | `PackagingBatches` (+ `ProductLots` `RELEASED` check) | `OWNER_ADMIN`, `PA`, `PACKAGING` | `IMPLEMENTED — NOT TESTED` |
| 10 | `GET` | `/logistics/dispatches` | Read-only | N/A | `ProductionDispatches` | `OWNER_ADMIN`, `PA`, `STORE`, `SALES`, `FIELD_SALESMAN`, `AUDITOR` | `IMPLEMENTED — NOT TESTED` |
| 11 | `POST` | `/logistics/dispatches` | `RECORD_DISTRIBUTION_DISPATCH` | Required (`MOV` / `nonce`) | `ProductionDispatches` (+ `ProductLots` `RELEASED` check) | `OWNER_ADMIN`, `PA`, `STORE`, `SALES` | `IMPLEMENTED — NOT TESTED` |
| 12 | `GET` | `/channels/settlements` | Read-only | N/A | `MarketplaceSettlements` | `OWNER_ADMIN`, `PA`, `ACCOUNTS`, `SALES`, `AUDITOR` | `IMPLEMENTED — NOT TESTED` |
| 13 | `POST` | `/channels/settlements` | `RECORD_MARKETPLACE_SETTLEMENT` | Required (`STL` / `nonce`) | `MarketplaceSettlements` (`PENDING_OWNER_MAPPING` fail-closed; CA GST gate) | `OWNER_ADMIN`, `ACCOUNTS`, `SALES` | `BLOCKED` (`PENDING_OWNER_MAPPING` + `PENDING_CA_APPROVAL` for GST) |
| 14 | `GET` | `/compliance/records` | Read-only | N/A | `ComplianceRecords` | `OWNER_ADMIN`, `PA`, `QUALITY`, `HR`, `ACCOUNTS`, `PRODUCTION`, `AUDITOR` | `IMPLEMENTED — NOT TESTED` |
| 15 | `POST` | `/compliance/records` | `RECORD_COMPLIANCE_ITEM` | Required (`STAT` / `nonce`) | `ComplianceRecords` (`PENDING_OWNER_MAPPING` fail-closed) | `OWNER_ADMIN`, `QUALITY` | `BLOCKED` (`PENDING_OWNER_MAPPING`) |
| 16 | `GET` | `/assets/maintenance` | Read-only | N/A | `AssetsMaintenance` | `OWNER_ADMIN`, `PA`, `PRODUCTION`, `QUALITY`, `ACCOUNTS`, `AUDITOR` | `IMPLEMENTED — NOT TESTED` |
| 17 | `POST` | `/assets/maintenance` | `RECORD_ASSET_MAINTENANCE` | Required (`MAINT` / `nonce`) | `AssetsMaintenance` (`PENDING_OWNER_MAPPING` fail-closed) | `OWNER_ADMIN`, `QUALITY` | `BLOCKED` (`PENDING_OWNER_MAPPING`) |
| 18 | `GET` | `/workforce/confidential/salary-payments` | Read-only (no-cache) | N/A | `SalaryPayments` | `OWNER_ADMIN` strictly (`PA`, `ACCOUNTS`, `HR`, `AUDITOR` -> `403`) | `IMPLEMENTED — NOT TESTED` |
| 19 | `GET` | `/workforce/advances` | Read-only (no-cache) | N/A | `EmployeeAdvances` | `OWNER_ADMIN` (full) / `ACCOUNTS` (`APPROVED_ADVANCE_DISBURSEMENT` minimal fields only); all others `403` | `IMPLEMENTED — NOT TESTED` |
| 20 | `POST` | `/workforce/advances/{advance_id}/disburse` | `DISBURSE_APPROVED_ADVANCE` | Required (`EADV` / `nonce`) | `EmployeeAdvances` (`PENDING_OWNER_MAPPING` fail-closed) | `OWNER_ADMIN`, `ACCOUNTS` (approved advances only) | `BLOCKED` (`PENDING_OWNER_MAPPING`) |
| 21 | `GET` | `/workforce/gig-entries` | Read-only | N/A | `LabourWorkEntries` | `OWNER_ADMIN`, `PA`, `PRODUCTION`, `HR`, `AUDITOR` | `IMPLEMENTED — NOT TESTED` |
| 22 | `POST` | `/workforce/gig-entries` | `SUBMIT_GIG_WORK_ENTRY` | Required (`PWE` / `nonce`) | `LabourWorkEntries` (initial status `SUBMITTED`) | `OWNER_ADMIN`, `PA`, `PRODUCTION` | `IMPLEMENTED — NOT TESTED` |
| 23 | `POST` | `/workforce/gig-entries/{entry_id}/verify` | `VERIFY_GIG_WORK_ENTRY` | Required (`PWE` / `nonce`) | `LabourWorkEntries` (`SUBMITTED -> VERIFIED`) | `OWNER_ADMIN`, `HR` | `IMPLEMENTED — NOT TESTED` |
| 24 | `POST` | `/workforce/gig-entries/{entry_id}/pay` | `PAY_GIG_WORK_ENTRY` | Required (`PWE` / `nonce`) | `LabourWorkEntries` (`VERIFIED -> PAID`) | `OWNER_ADMIN` only | `IMPLEMENTED — NOT TESTED` |
| 25 | `POST` | `/procurement/purchase-orders` | `CREATE_PURCHASE_ORDER` | Required (`PO` / `nonce`) | `PurchaseOrders` | `OWNER_ADMIN`, `PA`, `PROCUREMENT` | `IMPLEMENTED — NOT TESTED` |
| 26 | `POST` | `/procurement/goods-receipts` | `CREATE_GOODS_RECEIPT` | Required (`GRN` / `nonce`) | `GoodsReceipts` | `OWNER_ADMIN`, `PROCUREMENT`, `STORE` | `IMPLEMENTED — NOT TESTED` |
| 27 | `GET` | `/store/ledger` | Read-only | N/A | `ProductionStockLedger` / `RawMaterialLedger` | `OWNER_ADMIN`, `PA`, `STORE`, `PRODUCTION`, `PACKAGING`, `QUALITY`, `PROCUREMENT`, `ACCOUNTS`, `SALES`, `AUDITOR` | `IMPLEMENTED — NOT TESTED` |
| 28 | `POST` | `/store/stock-adjustments` | `REQUEST_STOCK_ADJUSTMENT` | Required (`MOV` / `nonce`) | `StockDiscrepancies` | `OWNER_ADMIN`, `PA`, `STORE` | `IMPLEMENTED — NOT TESTED` |
| 29 | `POST` | `/milling/batches` | `RECORD_MILLING_BATCH` | Required (`PB` / `nonce`) | `MillingBatches` | `OWNER_ADMIN`, `PA`, `PRODUCTION` | `IMPLEMENTED — NOT TESTED` |
| 30 | `POST` | `/production/batches` | `CREATE_PRODUCTION_BATCH` | Required (`PB` / `nonce`) | `ProductionBatches` | `OWNER_ADMIN`, `PA`, `PRODUCTION` | `IMPLEMENTED — NOT TESTED` |
| 31 | `POST` | `/sales/orders` | `CREATE_SALES_ORDER` | Required (`SO` / `nonce`) | `SalesOrders` (`PENDING_OWNER_MAPPING` fail-closed) | `OWNER_ADMIN`, `PA`, `SALES`, `FIELD_SALESMAN` | `BLOCKED` (`PENDING_OWNER_MAPPING`) |
| 32 | `POST` | `/sales/invoices` | `CREATE_SALES_INVOICE` | Required (`INV` / `nonce`) | `Sales` (+ `ProductLots` `RELEASED` gate) | `OWNER_ADMIN`, `PA`, `SALES`, `FIELD_SALESMAN` | `IMPLEMENTED — NOT TESTED` |
| 33 | `POST` | `/accounting/journals` | `POST_JOURNAL_VOUCHER` | Required (`JV` / `nonce`) | `JournalHeaders` (balanced double-entry required) | `OWNER_ADMIN`, `ACCOUNTS` | `IMPLEMENTED — NOT TESTED` |
| 34 | `GET` | `/transactions/status/{nonce}` | Read-only (`fresh=True`) | Path param `nonce` + optional `correlation_id` | `IdAllocations`, `AuditLog` (redacts confidential tabs for non-owners) | Any authenticated user | `IMPLEMENTED — NOT TESTED` |
| 35 | `GET` | `/control/audit-logs` | Read-only | N/A | `AuditLog` | `OWNER_ADMIN`, `PA`, `AUDITOR` | `IMPLEMENTED — NOT TESTED` |
| 36 | `GET` | `/control/exceptions` | Read-only | N/A | `ExceptionRegister` (canonical reconciled tab; `EXC` headers `PENDING_OWNER_MAPPING`) | `OWNER_ADMIN`, `PA`, `AUDITOR` | `IMPLEMENTED — NOT TESTED` |

> **Legacy Operational Routers (`/api/*`)**: All mutations across `auth`, `users`, `approvals`, `products`, `customers`, `purchasing`, `production`, `quality`, `stock`, `sales`, `expenses`, `visits`, `closing`, `salary`, `accounting`, and `workforce` delegate exclusively via `apps_script_bridge` (0 direct `db.append_record`/`update_record`/`delete_record` calls remain in `backend/app/`).

---

## 2. `REG-07` — Canonical 12-Role Permission & Confidentiality Register

Source of truth: `backend/app/permissions.py` (`TWELVE_ROLES`, `V2_ROLE_PERMISSIONS`, `OWNER_ONLY_PERMISSIONS`, `filter_confidential_record`) & `src/utils/permissions.ts`.

| Canonical Role | Legacy Aliases Mapped | Module Capabilities | Confidential Payroll (`SalaryPayments`, `SalaryStructures`, `PayrollRuns`, `SalaryReceipts`) | `EmployeeAdvances` | Personal Bank & Gov IDs (`CONFIDENTIAL_PERSONAL_FIELDS`) |
|---|---|---|---|---|---|
| **`OWNER_ADMIN`** | `OWNER`, `ADMIN` | Full wildcard (`*`) across all 15 groups + sole holder of `OWNER_ONLY_PERMISSIONS` | **Full Access** | **Full Access** | **Full Access** |
| **`PA`** | `PERSONAL_ASSISTANT` | View control/accounting/quality/channels/reports; create/update catalogue, procurement, production, packaging, sales, logistics, expenses; manage attendance & user approval requests | **ABSENT (`403` / stripped)** | **ABSENT (`403` / stripped)** | **STRIPPED server-side** |
| **`ACCOUNTS`** | `ACCOUNTANT` | Accounting vouchers & reconciliation read; supplier bills/payments; sales payments; channel settlements; expenses; reports | **ABSENT (`403` / stripped)** | **Narrow Scope Only:** `APPROVED_ADVANCE_DISBURSEMENT` allowed fields (`ACCOUNTS_ADVANCE_DISBURSEMENT_ALLOWED_FIELDS`) | **STRIPPED server-side** |
| **`PROCUREMENT`** | — | Catalogue view/create/update; procurement PO/GRN/returns; store & quality view | **ABSENT** | **ABSENT** | **STRIPPED server-side** |
| **`STORE`** | `DISPATCH` (legacy fallback) | Store ledger/issue/transfer/adjust request; GRN receive; inventory transfer; logistics dispatch | **ABSENT** | **ABSENT** | **STRIPPED server-side** |
| **`PRODUCTION`** | `FACTORY_WORKER`, `PRODUCTION_WORKER`, `WORKER` | Production batch creation, consumption, output, loss, gig work submit (`SUBMITTED`), QC submission | **ABSENT** | **ABSENT** | **STRIPPED server-side** |
| **`QUALITY`** | — | QC inspections (`IPQC`/`FGQC`), lot `RELEASED`/`ON_HOLD`/`REJECTED` decisions, complaints/recalls, compliance records | **ABSENT** | **ABSENT** | **STRIPPED server-side** |
| **`PACKAGING`** | — | Packaging batch creation & output recording (`{200, 500, 1000}`g retail packs) | **ABSENT** | **ABSENT** | **STRIPPED server-side** |
| **`SALES`** | `DISPATCH` | Sales orders/invoices/export, logistics dispatch, channels, inventory transfer, expenses | **ABSENT** | **ABSENT** | **STRIPPED server-side** |
| **`FIELD_SALESMAN`** | `SALESMAN` | Own sales orders/bills, own van loading pass acceptance, own inventory, own attendance check-in/out, own expenses | **ABSENT** | **ABSENT** | **STRIPPED server-side** |
| **`HR`** | — | Staff directory (non-confidential), attendance management, gig work `VERIFY` (`SUBMITTED -> VERIFIED`), task management | **ABSENT** | **ABSENT** | **STRIPPED server-side** |
| **`AUDITOR`** | — | **Strictly Read-Only (`view` only)** across control, catalogue, procurement, store, production, packaging, quality, sales, logistics, channels, accounting, compliance/assets, reports, inventory; all write buttons hidden/locked in UI and `403` on backend | **ABSENT (`403` / UI blocked in `SalaryView` & `WorkforceView`)** | **ABSENT (`403`)** | **STRIPPED server-side** |

---

## 3. `REG-09` — Open Decisions & Governance Blockers Register

### 3.1 Pending Owner & CA Decisions (`D-001` to `D-016`)

| Decision ID | Topic / Area | Owner / Sign-Off Authority | Current Status | Codebase Handling Until Resolved |
|---|---|---|---|---|
| **D-001** | HSN & GST Tax Rate Schedule (`hsn_gst_tax_rates`) | Chartered Accountant + Owner | `PENDING_CA_APPROVAL` | `assert_ca_policy_approved` blocks automated GST posting (`HTTP 403`/`409`) |
| **D-002** | Inventory Valuation Method (`FIFO` vs `WEIGHTED_AVERAGE`) | Chartered Accountant + Owner | `PENDING_CA_APPROVAL` | `DEFAULT_CA_POLICIES` defaults to `PENDING_CA_APPROVAL`; surfaced in `CALC-019` |
| **D-003** | Production Overhead & Labour Allocation Basis (`DIRECT_KG` / `BATCH_HOURS` / `STANDARD_ABSORPTION`) | Chartered Accountant + Owner | `PENDING_CA_APPROVAL` | Surfaced as `PENDING_CA_APPROVAL` in `CALC-019` & policy API |
| **D-004** | Fixed Assets Depreciation Policy (`WDV_INCOME_TAX` vs `SLM_COMPANIES_ACT`) | Chartered Accountant + Owner | `PENDING_CA_APPROVAL` | Automated depreciation posting blocked until approved |
| **D-005** | Apps Script Web App (`doPost`) Deployment & Shared HMAC Secret (`SALES_APPS_SCRIPT_*`) | Owner / Google Workspace Admin | `BLOCKED` (`APPS_SCRIPT_DEPENDENCY`) | All governed writes fail closed with `503 BLOCKED_PENDING_OWNER_SETUP` |
| **D-006** | Canonical Row-1 Headers for 24 `PENDING_OWNER_MAPPING` Extended Tabs | Owner (from Master `.xlsx`) | `PENDING_OWNER_MAPPING` | Writes to unmapped tabs fail closed with `503`; zero fabricated headers |
| **D-007** | `EXC` Tab Physical Row-1 Headers (`ExceptionRegister`) | Owner | `RECONCILED_TAB_NAME_ONLY` (`PENDING_OWNER_MAPPING`) | Tab name reconciled to `ExceptionRegister` (`AuditAndExceptions.gs`); headers fail closed |
| **D-008** | `PKG` vs `PKB` Historical Prefix Reconciliation (`PackagingMaterials` vs `PackagingBatches`) | Owner + Apps Script | `CONFLICT_RECONCILIATION_REQUIRED` | Apps Script allocates canonical `PKB-*` / `PKG-*`; reads remain backward-compatible |
| **D-009** | Legacy-to-Locked Prefix Cutover (`CUS->CUST`, `JRN->JV`, `PAY->RCPT`, `PRB->PB`, `SALE->INV`, etc.) | Owner + Apps Script | `PENDING_OWNER_DECISION` | Tracked in `LEGACY_TO_LOCKED_ID_PREFIX_ALIASES`; reads accept legacy IDs |
| **D-010** | Physical Verification of Raw Material Opening Stock Balances | Owner (Physical Stock Count) | `PENDING_OWNER_DECISION` | Unverified opening balances blocked from production issuance (`CALC-031`, `POL-017`) |
| **D-011** | Review & Disposition of Pending 2.4 kg Packaging Discrepancy | Owner | `PENDING_OWNER_DECISION` | Preserved intact without auto-adjustment (`CALC-017`, `POL-018`) |
| **D-012** | Schema Header Variance Reconciliation across 12 Core Tabs (`SCHEMA_HEADER_VARIANCES`: `Suppliers`, `CustomRoles`, `SalaryIncentives`, `RawMaterials`, `Products`, `Workers`, `Customers`, `Sales`, `ProductionBatches`, `PackagingBatches`, `Expenses`, `ShopVisits`) | Owner (Spreadsheet Column Audit) | `CONFLICT_RECONCILIATION_REQUIRED` | Documented verbatim in `schema_registry.SCHEMA_HEADER_VARIANCES` |
| **D-013** | Accounting Opening Balances Backfill Authorization | Chartered Accountant + Owner | `PENDING_CA_APPROVAL` | Live backfill requires explicit Owner confirmation + active Apps Script bridge |
| **D-014** | Financial Year Period Lock & Closing Cutoff Dates (`AccountingPeriods`) | Chartered Accountant + Owner | `PENDING_OWNER_DECISION` | `CLOSE_ACCOUNTING_PERIOD` restricted strictly to `OWNER_ADMIN` |
| **D-015** | Credit Sales Limit & Owner Credit Approval Thresholds | Owner | `PENDING_OWNER_DECISION` | Credit approvals delegated via `RESERVE_CREDIT_APPROVAL` / `CONSUME_CREDIT_APPROVAL` |
| **D-016** | Authorization to Lift Section 25 Testing Moratorium (Phase 16 Staging QA) | Owner | `PENDING_OWNER_DECISION` | Testing moratorium strictly observed; zero tests/builds/deploys executed |

### 3.2 Blueprint Section 17 Governance Items (`1–47`) Mapping

| Blueprint Sec. 17 Group | Item Range | Summary of Governed Items | Mapped Decision / Status |
|---|---|---|---|
| **A. Core Infrastructure & Apps Script Bridge** | Items `1–8` | Single write owner, HMAC-SHA256 secret >=32 chars, HTTPS-only prod, redirect block, `IdAllocations` nonce ledger, response echo validation, atomic `AuditLog`, timeout/504 status check | Implemented in FastAPI/React (`IMPLEMENTED — NOT TESTED`); live Apps Script `doPost` deployment `BLOCKED` (`D-005`) |
| **B. Workbook & Schema Governance (255 Tabs)** | Items `9–18` | 15 groups (`00`–`14`), 46 deleted scratch tab blocklist, 32 locked ID prefixes, `ExceptionRegister` reconciliation (`EXC`), 24 `PENDING_OWNER_MAPPING` tabs, 12 `SCHEMA_HEADER_VARIANCES`, zero auto-create | Implemented fail-closed in `schema_registry.py`; physical Row-1 header supply `PENDING_OWNER_MAPPING` (`D-006`, `D-007`, `D-008`, `D-009`, `D-012`) |
| **C. RBAC, Confidentiality & Auditor Controls** | Items `19–26` | 12 canonical roles, default-deny permissions, `OWNER_ONLY_PERMISSIONS`, server-side field stripping (`CONFIDENTIAL_PERSONAL_FIELDS`), no-cache confidential tabs, narrow `ACCOUNTS` advance disbursement, `PA` payroll exclusion, `AUDITOR` strict read-only | `IMPLEMENTED — NOT TESTED` across `permissions.py`, routers, `SalaryView.tsx`, `WorkforceView.tsx`, and all operational views |
| **D. Operations, Quality & Inventory Safeguards** | Items `27–35` | Retail packs `{200, 500, 1000}`g, `ProductLots` `RELEASED` gate on packaging/dispatch/invoicing, unverified RM opening stock block, deterministic recipe mapping, historical 55 kg / 2.4 kg discrepancy preservation, van loading acceptance, gig `SUBMITTED->VERIFIED->PAID` | `IMPLEMENTED — NOT TESTED`; physical RM stock verification & 2.4 kg disposition `PENDING_OWNER_DECISION` (`D-010`, `D-011`) |
| **E. Accounting, Tax & CA Policy Gates** | Items `36–42` | Double-entry balance (`Decimal`), compensating reversals only, `hsn_gst_tax_rates`, `inventory_valuation_method`, `overhead_and_labour_allocation_basis`, `depreciation_policy`, period close & opening balance backfill | Fail-closed gates `IMPLEMENTED — NOT TESTED`; policy values `PENDING_CA_APPROVAL` (`D-001`–`D-004`, `D-013`–`D-015`) |
| **F. Frontend Safety, Governance Docs & Phase 16 Gate** | Items `43–47` | Zero `initialData.ts` imports in production, zero native browser dialogs, `UnknownOutcomeBanner` + `GET /api/v2/transactions/status/{nonce}` across write views, Governance Constitution + `REG-03`/`06`/`07`/`09`/`12` docs, Section 25 Moratorium | `IMPLEMENTED — NOT TESTED`; Phase 16 testing `PENDING_OWNER_DECISION` (`D-016`) |

---

## 4. `REG-12` — Completion Ledger (`REQ-001` to `REQ-115`)

> **Mandatory Status Rule:** Zero items marked `VERIFIED` or `ACCEPTED`. Every completed code/doc requirement is recorded as `IMPLEMENTED — NOT TESTED`; external Apps Script/header/CA-gated items are recorded as `BLOCKED` or `PENDING_CA_APPROVAL`.

| Requirement Range | Domain / Capability Group | Count | `IMPLEMENTED — NOT TESTED` | `BLOCKED` (Owner / Apps Script) | `PENDING_CA_APPROVAL` | Notes & Primary Evidence |
|---|---|---:|---:|---:|---:|---|
| **`REQ-001`–`REQ-012`** | Architecture: Google Sheets sole DB, Apps Script single write owner, zero direct FastAPI writes, zero SQL/NoSQL | 12 | 11 | 1 (`REQ-012`: Live Apps Script `doPost` deployment & Render env wiring) | 0 | `apps_script_bridge.py`, `sheets.py`, `config.py` (`D-005`) |
| **`REQ-013`–`REQ-024`** | Schema Registry: 15 groups (`00`–`14`), 255-tab catalog, 46 deleted scratch tab blocks, 32 locked ID prefixes, `EXC` -> `ExceptionRegister` | 12 | 9 | 3 (`REQ-022`: 24 extended tab Row-1 headers; `REQ-023`: `EXC` Row-1 headers; `REQ-024`: 12 core tab header variances) | 0 | `schema_registry.py` (`D-006`, `D-007`, `D-008`, `D-012`) |
| **`REQ-025`–`REQ-036`** | Transport Security & Idempotency: HMAC-SHA256 signing, TLS prod check, redirect block, echo validation, read-back verification, `GET /api/v2/transactions/status/{nonce}` | 12 | 12 | 0 | 0 | `apps_script_bridge.py`, `routers/v2_erp.py` |
| **`REQ-037`–`REQ-050`** | 12-Role RBAC & Confidentiality: Default-deny permissions, `OWNER_ONLY_PERMISSIONS`, server-side personal/bank field stripping, `SalaryPayments`/`EmployeeAdvances` separation, `AUDITOR` strict read-only | 14 | 14 | 0 | 0 | `permissions.py`, `routers/workforce.py`, `routers/salary.py`, `routers/v2_erp.py`, `SalaryView.tsx`, `WorkforceView.tsx`, `PurchasingView.tsx`, `SalesView.tsx`, `AccountingView.tsx`, `ProductionView.tsx` |
| **`REQ-051`–`REQ-066`** | Calculation Engine (`REG-03`: `CALC-001`–`CALC-032`): Units/Decimal rounding, deterministic recipe mapping, production reconciliation, packaging `{200,500,1000}`g & discrepancy classification, costing, unverified RM stock block, consolidated FG register | 16 | 15 | 0 | 1 (`REQ-062`: Authoritative overhead/labour capitalization & valuation policy selection in `CALC-019`) | `backend/app/calculations/*.py`, `/docs/CALCULATION_REGISTER_REG03.md` (`D-002`, `D-003`) |
| **`REQ-067`–`REQ-080`** | Operational Workflows (`/api/*` & `/api/v2/*`): Procurement PO/GRN/Bill/Payment/Advance, Milling, Production, Quality `ProductLots` `RELEASED` gate, Packaging, Logistics Dispatch, Van Loading, Sales, Gig 3-stage workflow | 14 | 10 | 4 (`REQ-075`–`REQ-078`: Writes to `PENDING_OWNER_MAPPING` tabs `SalesOrders`, `MarketplaceSettlements`, `ComplianceRecords`, `AssetsMaintenance`, `EmployeeAdvances` fail closed until Owner supplies headers) | 0 | `routers/v2_erp.py` + legacy operational routers (`D-006`) |
| **`REQ-081`–`REQ-092`** | Accounting, Tax & CA Policy Gates: Double-entry journal balance, compensating reversals, `Settings` CA policy endpoint, fail-closed GST/valuation/overhead/depreciation gates, period lock | 12 | 8 | 0 | 4 (`REQ-088`–`REQ-091`: CA sign-off on `hsn_gst_tax_rates`, `inventory_valuation_method`, `overhead_and_labour_allocation_basis`, `depreciation_policy`) | `accounting/journal_engine.py`, `schema_registry.DEFAULT_CA_POLICIES`, `routers/v2_erp.py` (`D-001`–`D-004`, `D-013`) |
| **`REQ-093`–`REQ-106`** | Frontend Reliability & UX Safety: `StoreContext.tsx` disconnected from `initialData.ts`, zero native browser dialogs, `UnknownOutcomeBanner` + `"Check Transaction Status"` wired across write views, preserved client nonces & unsaved form inputs | 14 | 14 | 0 | 0 | `src/context/StoreContext.tsx`, `src/services/api.ts`, `src/components/common/UnknownOutcomeBanner.tsx`, `MobileOrderWizard.tsx`, `SalaryView.tsx`, `SalesView.tsx`, `AccountingView.tsx`, `ExpensesView.tsx`, `StockView.tsx`, `PurchasingView.tsx`, `ProductionView.tsx`, `WorkforceView.tsx`, `ErpOperationsHubView.tsx` |
| **`REQ-107`–`REQ-115`** | Governance Documentation, Registers & Phase 16 Pre-Testing Gate: Constitution v1.2 Reference Index, `REG-03`, `REG-06`, `REG-07`, `REG-09`, `REG-12`, Section 25 Moratorium adherence | 9 | 8 | 1 (`REQ-115`: Phase 16 Staging QA & Production Promotion awaiting Owner sign-off) | 0 | `/docs/MASTER_POLICY_CONSTITUTION_V1_2.md`, `/docs/CALCULATION_REGISTER_REG03.md`, `/docs/MASTER_REGISTERS_AND_DECISIONS.md` (`D-016`) |
| **TOTAL** | **`REQ-001`–`REQ-115`** | **115** | **101** | **9** | **5** | **0 `VERIFIED` / 0 `ACCEPTED` (Moratorium Compliant)** |
