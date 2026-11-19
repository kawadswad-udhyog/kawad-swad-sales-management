# Kawad Swad ERP — Phase 1 Database & Schema Repair & Apps Script Writer Audit Report

> **STATUS: PHASE 1 CODE REPAIRS IMPLEMENTED — NOT TESTED (EXTERNAL ARTIFACT BLOCKERS REMAIN BEFORE PHASE 2)**
>
> **Constitutional Compliance Notice (Master Policy Constitution v1.2, Section 25 & POL-018):**
> - **NO** tests, builds, linters, type-checkers, `py_compile`, or runtime checks were executed.
> - **NO** live Google Sheets were accessed or modified.
> - **NO** Apps Script files were created, modified, or deployed.
> - **NO** unverified tab names, Row-1 headers, or Owner/CA policy values were fabricated.
> - **NO** GitHub pushes, Render deployments, or production data changes were performed.

---

## 1. Execution Summary Against Recommended Phase 1 Repair Order

| Step | Repair Item | Audit IDs | Status | Summary of Code / Audit Action |
|---|---|---|---|---|
| **1** | Fix the missing schema-coverage function | `DB-001` (P0) | `IMPLEMENTED — NOT TESTED` | Implemented `WORKBOOK_TARGET_TAB_COUNT = 255` and `get_schema_coverage_summary()` in `backend/app/schema_registry.py`; exposed full coverage metrics in `GET /api/v2/meta/schema-registry`; prepared startup/import regression test (`backend/tests/test_phase1_database_schema_guards.py`). |
| **2** | Add fail-closed protection for all 12 conflicting core schemas | `DB-002` (P0) | `IMPLEMENTED — NOT TESTED` | Added `CONFLICTING_CORE_SCHEMA_TABS` (all 12 `CONFLICT_RECONCILIATION_REQUIRED` tables), `get_schema_write_block_reason()`, and Owner-only reconciliation unlock contract (`SALES_APPROVED_CORE_SCHEMA_RECONCILIATIONS_JSON` / `approve_core_schema_reconciliation`, default EMPTY); wired `AppsScriptBridge.execute_governed_write` to block all 12 core conflicting tabs + 24 extended pending tabs with `HTTP 503 BLOCKED_PENDING_OWNER_SETUP` (`CORE_SCHEMA_CONFLICT_UNRECONCILED`). |
| **3** | Reconcile the complete authoritative 255-tab database blueprint | `DB-003` (P1), `DB-006` (P2), `DB-007` (P2) | `PARTIAL — BLOCKED ON AUTHORITATIVE WORKBOOK EXPORT` | **Resolved `DB-006`**: Deduplicated `ProductLots` out of Group `05` (`workbook_tabs` now 91 refs == 91 unique tabs; canonical owner = Group `03` Inventory & Warehousing; Group `05` carries `referenced_tabs: ["ProductLots"]`). **Blocked (`DB-003` / `DB-007`)**: The authoritative 255-tab Google Sheets workbook and `DBV5_FIELD_DICTIONARY_3074` export are NOT present in the repository; the remaining `164` tabs and physical Row-1 headers remain explicitly unmapped without fabrication. |
| **4** | Resolve legacy ID mappings and the `PKG`/`PKB` collision | `DB-004` (P1) | `IMPLEMENTED — NOT TESTED` (Code Enforcement Complete; Owner Cutover Pending) | Centralized all 10 legacy-to-locked aliases in `LEGACY_TO_LOCKED_ID_PREFIX_ALIASES` with explicit `allow_on_read`, `allow_on_new_allocation`, and `collides_with_locked_tab` policy; implemented `get_locked_prefix_for_tab()`, `get_allowed_id_prefixes_for_tab()`, and `validate_table_id_prefix()`; **blocked colliding `PKG-*` on NEW `PackagingBatches` allocations** (requiring `PKB-*`, while retaining `PKG-*` read-compatibility for historical batches `PKG-000001`/`PKG-000002`); removed incomplete hardcoded `if/elif` alias list from `apps_script_bridge.py`; documented `RCPT` (`Payments` vs `SalaryReceipts`) and `SAL` (`SalaryPayments` vs `SalaryIncentives`) legacy collisions in `TAB_RECONCILIATION_CONFLICTS`. |
| **5** | Add missing ID-prefix enforcement to the 11 affected actions | `DB-005` (P1) | `IMPLEMENTED — NOT TESTED` | Added explicit `locked_prefix` to all 11 affected creation actions in `backend/app/action_registry.py` (`CREATE_CUSTOMER`, `CREATE_RAW_MATERIAL_MASTER`, `ADJUST_FINISHED_GOODS_STOCK`, `CREATE_PRODUCTION_BATCH`, `RECORD_PACKAGING_PENDING_REVIEW`, `RECORD_PACKAGING_BATCH`, `CREATE_SALE`, `CREATE_SALES_INVOICE`, `CREATE_LEGACY_SALES_ORDER`, `RECORD_SALE_PAYMENT`, `RECONCILE_FACTORY_STOCK`) plus defense-in-depth lookup in `AppsScriptBridge._effective_locked_prefix()`. |
| **6** | Audit the Apps Script database writer | `DB-008` (P2) | `AUDITED — BLOCKED (MAIN WRITER SOURCE ABSENT FROM REPO)` | Static audit of all `.gs` files in the repository confirmed **only 3 offline workforce schema/diagnostic utilities exist** (`docs/workforceDiagnosticReport.gs`, `docs/workforceMigration.gs`, `docs/workforceSchemaUpgrade_2026-11-03-v1.gs`). The main ERP single-write-owner Apps Script Web App (`doPost` / `WebAppBridge.gs` / 16-file Apps Script project) is **not present in the repository** and must be supplied by the Owner for code audit before Phase 1 certification. |
| **7** | Gate to Phase 2: API & Permission Audit | Gate Hold | `HOLD — AWAITING OWNER ARTIFACTS` | Per Recommended Repair Order Step 7, Phase 2 API & Permission Audit is held until the Owner supplies (a) the authoritative 255-tab workbook/dictionary export to resolve `DB-002`/`DB-003`/`DB-007`, and (b) the Apps Script `doPost` single-write-owner source to resolve `DB-008`. |

---

## 2. Detailed Code Repairs Applied

### 2.1 `DB-001` — Restored `get_schema_coverage_summary()` (`backend/app/schema_registry.py`, `backend/app/routers/v2_erp.py`)
- Added `WORKBOOK_TARGET_TAB_COUNT: int = 255`.
- Implemented `get_schema_coverage_summary()` computing exact, honest counts dynamically from `REQUIRED_TABS`, `EXTENDED_V2_TAB_CONTRACTS`, `DATABASE_GROUPS_15`, `PENDING_OWNER_MAPPING_TABS`, `CONFLICTING_CORE_SCHEMA_TABS`, and Owner-approved reconciliations:
  - `cleaned_tab_baseline`: `255`
  - `declared_database_groups`: `15`
  - `group_tab_references_total`: `91` (down from `92` after deduplicating `ProductLots`)
  - `core_required_tabs_count`: `67`
  - `extended_v2_contracts_count`: `24`
  - `unique_catalogued_workbook_tabs`: `91`
  - `unmapped_workbook_tabs_remaining`: `164`
  - `pending_owner_mapping_tabs_count`: `24`
  - `conflicting_core_schema_tabs_count`: `12`
  - `write_blocked_schema_tabs_count`: `36`
  - `duplicate_group_placements`: `{}`
  - `coverage_complete`: `False` (`INCOMPLETE_PENDING_AUTHORITATIVE_WORKBOOK_EXPORT`)
- Updated `GET /api/v2/meta/schema-registry` to expose `conflicting_core_schema_tabs`, `schema_header_variances`, `legacy_to_locked_id_prefix_aliases`, and the complete `coverage_summary` breakdown.

### 2.2 `DB-002` — Fail-Closed Protection for All 12 Conflicting Core Schemas (`backend/app/config.py`, `backend/app/schema_registry.py`, `backend/app/apps_script_bridge.py`)
- Derived `CONFLICTING_CORE_SCHEMA_TABS` directly from `SCHEMA_HEADER_VARIANCES` (`status == "CONFLICT_RECONCILIATION_REQUIRED"`):
  `Suppliers`, `CustomRoles`, `SalaryIncentives`, `RawMaterials`, `Products`, `Workers`, `Customers`, `Sales`, `ProductionBatches`, `PackagingBatches`, `Expenses`, `ShopVisits`.
- Added fail-closed Owner reconciliation mechanism (`SALES_APPROVED_CORE_SCHEMA_RECONCILIATIONS_JSON` defaulting to `""`, plus `approve_core_schema_reconciliation()` requiring explicit `status == "RECONCILED_OWNER_APPROVED"`, non-empty `approved_by`, and verified unique physical Row-1 `headers`).
- Unified schema write-gating in `get_schema_write_block_reason(tab_name)` covering **all 36 write-blocked tabs** (`24` `PENDING_OWNER_MAPPING_TABS` + `12` unreconciled `CONFLICTING_CORE_SCHEMA_TABS`).
- Updated `AppsScriptBridge.execute_governed_write` to invoke `get_schema_write_block_reason(clean_tab)` before signing or dispatching any request, returning `BridgeResult(status="BLOCKED_PENDING_OWNER_SETUP", error_code="CORE_SCHEMA_CONFLICT_UNRECONCILED", dependency="OWNER_SCHEMA_RECONCILIATION_DEPENDENCY", retryable=False, http_status=503)`.

### 2.3 `DB-004` & `DB-005` — Centralized Legacy ID Aliases, `PKG`/`PKB` Collision Control & 11 Action Specs (`backend/app/schema_registry.py`, `backend/app/action_registry.py`, `backend/app/apps_script_bridge.py`)
- Replaced the incomplete 6-entry hardcoded `if/elif` alias check in `AppsScriptBridge._validate_id_format` with centralized `validate_table_id_prefix()` backed by `LEGACY_TO_LOCKED_ID_PREFIX_ALIASES`.
- **`PKG`/`PKB` Collision Enforcement**:
  - `PackagingMaterials`: strictly accepts `PKG-*` only (`PKB-*` rejected).
  - `PackagingBatches` new governed allocations (`for_new_allocation=True`): strictly requires `PKB-*` (`PKG-*` rejected so new packaging batches cannot collide with `PackagingMaterials`).
  - `PackagingBatches` historical reads (`for_new_allocation=False`): accepts both `PKB-*` and legacy `PKG-*` (preserving historical records such as `PKG-000001` and `PKG-000002`).
- Documented two additional legacy prefix overlaps transparently in `TAB_RECONCILIATION_CONFLICTS`:
  - `RCPT_PREFIX_COLLISION`: `Payments` (locked `RCPT`) vs legacy `SalaryReceipts` (`RCPT` in `sheets.ID_PREFIXES`).
  - `SAL_PREFIX_COLLISION`: `SalaryPayments` (locked `SAL`) vs legacy `SalaryIncentives` (`SAL` in `sheets.ID_PREFIXES`).
- Added explicit `locked_prefix` to all 11 previously ungated creation actions in `backend/app/action_registry.py`:
  1. `CREATE_CUSTOMER` -> `CUST`
  2. `CREATE_RAW_MATERIAL_MASTER` -> `RM`
  3. `ADJUST_FINISHED_GOODS_STOCK` -> `MOV`
  4. `CREATE_PRODUCTION_BATCH` -> `PB`
  5. `RECORD_PACKAGING_PENDING_REVIEW` -> `PKB`
  6. `RECORD_PACKAGING_BATCH` -> `PKB`
  7. `CREATE_SALE` -> `INV`
  8. `CREATE_SALES_INVOICE` -> `INV`
  9. `CREATE_LEGACY_SALES_ORDER` -> `INV`
  10. `RECORD_SALE_PAYMENT` -> `RCPT`
  11. `RECONCILE_FACTORY_STOCK` -> `MOV`
- Added defense-in-depth fallback in `AppsScriptBridge._effective_locked_prefix()` resolving `get_locked_prefix_for_tab(spec.target_tab)` whenever `spec.requires_allocated_id` is `True`.

### 2.4 `DB-006` — `ProductLots` Canonical Group Ownership (`backend/app/schema_registry.py`)
- Canonical owner: Group `03` (`Inventory & Warehousing`).
- Removed duplicate `"ProductLots"` from Group `05` (`Quality & Food Safety`) `workbook_tabs`, recording it cleanly under `"referenced_tabs": ["ProductLots"]`.

---

## 3. Step 6 — Static Audit of Apps Script Database Writers Present in Repository

### 3.1 Inventory of `.gs` Files in Repository
A complete repository scan found **3 `.gs` files** (all under `/docs/`):

| File | Role | Mutates Business Data? | Audit Findings |
|---|---|---|---|
| `docs/workforceDiagnosticReport.gs` | Read-only workforce sheet diagnostic utility | **No** (strictly read-only; zero `insertSheet`/`setValue`/`appendRow`) | Safe read-only diagnostic script aligned with the 16 workforce tables in `REQUIRED_TABS`. Not a runtime web-app writer. |
| `docs/workforceMigration.gs` | Offline manual Phase 4 workforce schema migration utility | **Manual-only** (dual-token guard `CONFIRM_MIGRATE_WORKFORCE_2026` + `AUTHORIZED_BY_OWNER`; explicit core-sheet protection + full-sheet backup verification) | Offline schema migration utility only; no `doPost` endpoint, no HMAC verification, no `IdAllocations` nonce ledger. |
| `docs/workforceSchemaUpgrade_2026-11-03-v1.gs` | Offline manual additive workforce tab creation utility | **Manual-only** (additive creation of missing workforce sheets) | Offline schema setup utility only; not a runtime ERP transaction writer. |

### 3.2 Critical Finding (`DB-008`) — Main ERP Single-Write-Owner Apps Script Source Is Absent
- **Absent Artifacts**: The deployed 16-file Apps Script project (`WebAppBridge.gs` / `doPost`, `AuditAndExceptions.gs`, ID allocator, ledger writers, and double-entry posting handlers referenced in the Blueprint) is **not present in this repository**.
- **Required Audit Criteria Once Owner Supplies the Apps Script Source**:
  1. **HMAC-SHA256 & Envelope Integrity**: Constant-time signature verification over canonical JSON using `>= 32`-char `SALES_APPS_SCRIPT_SHARED_SECRET`, verifying `payload_hash`, `action`, `target_tab`, `nonce`, and `correlation_id`.
  2. **Concurrency & Idempotency**: `LockService.getScriptLock()` wrapping `IdAllocations` nonce lookup/write; identical nonce + identical `payload_hash` returns idempotent replay; identical nonce + mismatched `payload_hash` rejects with conflict (`409`).
  3. **Canonical ID Allocation**: Strictly allocates `PKB-*` for `PackagingBatches`, `PKG-*` for `PackagingMaterials`, and canonical locked prefixes from `LOCKED_32_ID_PREFIXES` without recycling cancelled/failed IDs.
  4. **Header-Name Column Mapping (POL-003 / POL-024)**: Maps fields strictly by Row-1 header name (never positional column index), fails closed on missing required Row-1 columns, and never auto-creates forbidden scratch tabs (`KS_P1_*`, `KS_P2_*`, `KS_P3_*`, `DBV5_*`, `DB_*`).
  5. **Atomicity & Compensating Rollback**: Multi-tab writes (`Sales` + `SaleItems` + `SalesmanStockLedger` + `Payments` + `JournalHeaders` + `JournalLines`) must guard against partial writes, enforce double-entry balance (`total_debit == total_credit` in integer paise), and append atomic `AuditLog` entries containing `correlation_id`, `nonce`, `allocated_id`, and `tab_name`.
  6. **Mandatory Response Echoes**: Every JSON response (`CONFIRMED` or `REJECTED`) must echo `correlation_id`, `nonce`, `action`, `target_tab`, `payload_hash`, and (for creation actions) `allocated_id`.

---

## 4. Exact Owner Inputs Required to Close Phase 1 Before Phase 2

1. **Authoritative 255-Tab Workbook Export / `DBV5_FIELD_DICTIONARY_3074` CSV/JSON**:
   - Needed to map the remaining `164` unmapped tabs (`DB-003`) and verify physical Row-1 headers for all `255` tabs (`DB-007`) without inventing a single column name.
2. **Owner Header Reconciliation Decision for the 12 Conflicting Core Tabs (`DB-002`)**:
   - Confirm physical Row-1 headers & canonical mapping for `Suppliers`, `CustomRoles`, `SalaryIncentives`, `RawMaterials`, `Products`, `Workers`, `Customers`, `Sales`, `ProductionBatches`, `PackagingBatches`, `Expenses`, and `ShopVisits` (46 conflicting fields).
3. **Owner ID-Prefix Cutover Confirmation (`DB-004`)**:
   - Confirm cutover schedule for the 9 transitional non-colliding legacy aliases (`CUS`, `JRN`, `JLN`, `PAY`, `PRB`, `PST`, `RWM`, `ITEM`, `SALE`) and resolve `RCPT` (`Payments` vs `SalaryReceipts`) and `SAL` (`SalaryPayments` vs `SalaryIncentives`).
4. **Deployed Apps Script Single-Write-Owner Source Code (`DB-008`)**:
   - Export and supply the `doPost` / bridge `.gs` files for Step 6 static audit before lifting the Phase 2 gate.
5. **Separate Owner Testing Authorization (Constitution Section 25.4)**:
   - Required before executing `backend/tests/test_phase1_database_schema_guards.py` or any pytest/compile/lint suite.
