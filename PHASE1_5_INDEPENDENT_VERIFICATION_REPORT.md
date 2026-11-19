# KAWAD SWAD ERP — PHASE 1.5 INDEPENDENT VERIFICATION REPORT
**Audit Mode:** Strict Read-Only Independent Verification (Zero Source Code Modifications)
**Repository:** `kawadswad-udhyog/kawad-swad-sales-management` (local workspace snapshot; no `.git` directory present — before/after diff comparison against pre-Phase-1 originals is incomplete and noted explicitly)
**Audit Date:** 2026-11-19
**Official Phase 1.5 Verdict:** **`FAIL`** *(Live-reproduced CRITICAL secondary-tab `DB-002` bypass across 11 bridge actions and 2 live production endpoints, HIGH ID-validation deadlock on `CREATE_SALARY_INCENTIVE`, HIGH fail-open token revocation check, HIGH factual misreporting in `PHASE1_MASTER_AUDIT_REPORT.md`, plus unresolved external artifact blockers `DB-003`, `DB-007`, `DB-008`)*

---

## 1. Executive Summary

An independent, skeptical audit of the actual ERP source code was conducted without relying on prior Phase 1 reports, summaries, or test claims. All local tests were executed in a verified isolated environment (`SALES_TESTING=1`, `SALES_ENV=development`, zero Sheets/Apps Script credentials, `db.is_connected == False`).

### Core Audit Conclusions
1. **Partially Solid Foundation:** `DB-001` (`get_schema_coverage_summary()`), `DB-006` (`ProductLots` single canonical Group `03` ownership), `P1-NEW-06` (`auth.py` missing `require_sheets_connection` import), all 11 `DB-005` `locked_prefix` declarations, primary-tab blocking for all 12 `CONFLICTING_CORE_SCHEMA_TABS`, Blueprint v2.1 single-write-owner enforcement in `sheets.py`, and frontend `tsc`/`vite build` compilation are genuinely implemented in source code.
2. **CRITICAL Bypass Invalidates `P1-NEW-01` / `DB-002` Claim (`P1.5-001`):** `backend/app/apps_script_bridge.py:557` computes `secondary_tabs_to_check = requested_inv if requested_inv else sorted(spec.allowed_invalidate_tabs)`. Any caller supplying a non-empty `invalidate_tabs` list that omits a conflicting secondary tab **completely bypasses `DB-002`**. Independent AST + live bridge execution proved **11 of 12 secondary-tab actions are bypassable**, and **2 live production router endpoints actively trigger this bypass today** (`backend/app/routers/purchasing.py:520` `RECEIVE_GOODS` and `backend/app/routers/v2_erp.py:1146` `RECORD_MILLING_BATCH` both omit `RawMaterials` from `invalidate_tabs`).
3. **HIGH ID-Prefix Contradiction & Deadlock (`P1.5-002`):** `backend/app/action_registry.py:1241` declares `locked_prefix="SAL"` on `CREATE_SALARY_INCENTIVE` (`target_tab="SalaryIncentives"`), directly contradicting `schema_registry.py:256-260` (`COLLIDING_LEGACY_PREFIX_TABS["SalaryIncentives"]`). Live execution proved `_validate_id_format()` rejects **every possible ID** (`SAL-*`, `INC-*`, `SINC-*`). Separately, `SalaryReceipts` (`RCPT` collision) is written as a child row of `RECORD_WORKFORCE_PAYMENT` and is never prefix-validated by `AppsScriptBridge` at runtime.
4. **HIGH Fail-Open Token Revocation Defect (`P1.5-003`):** `backend/app/auth.py:216-226` catches and ignores all exceptions reading `RevokedTokens` (`except Exception: pass; return False`), **failing OPEN** when Google Sheets is rate-limited or unreachable (live-reproduced). Additionally, `RevokedTokens` and `AuthUsers` are read with `fresh=False` (30-second cache), `sessions_revoked_at` swallows parse errors fail-open, and `routers/auth.py:101` checks only `active == "false"` (missing `"0"`/`"no"`).
5. **HIGH Factual Misrepresentation in Prior Phase 1 Report (`P1.5-004`):** `PHASE1_MASTER_AUDIT_REPORT.md` Section 4 listed **7 wrong tables** (`ApprovalRequests`, `Attendance`, `DailyClosings`, `GoodsReceipts`, `MillingBatches`, `StockMovements`, `SupplierBills`) instead of the actual 12 in `CONFLICTING_CORE_SCHEMA_TABS`, and Section 3 inaccurately claimed `approve_core_schema_reconciliation()` validates full column coverage (live reproduction proved `headers=["totally_fake_column"]` unlocks `Customers`, `P1.5-005`).
6. **External Blockers Confirmed Open (`DB-003`, `DB-007`, `DB-008`):** Independent workspace search confirmed zero `.xlsx` files, zero live Apps Script `WebAppBridge.gs`/`doPost` files, and no `DBV5_FIELD_DICTIONARY_3074` export exist in the repository.

---

## 2. Independent Verification of Phase 1 Repairs (`DB-001` – `DB-006`)

### 2.1 `DB-001`: Schema Coverage Registry
- **Inspected:** `backend/app/schema_registry.py` (`WORKBOOK_TARGET_TAB_COUNT`, `get_schema_coverage_summary()`, `build_table_schema_registry()`, `DATABASE_GROUPS_15`), `backend/app/routers/v2_erp.py:386-425`, `src/types/index.ts:857-915`, `src/views/ErpOperationsHubView.tsx:1482-1620`.
- **Verified True:**
  - `WORKBOOK_TARGET_TAB_COUNT = 255`.
  - Live math verified: `15` groups, `91` group tab references (`0` duplicates), `67` `REQUIRED_TABS` (`891` columns), `66` `ID_PREFIXES` (`Settings` intentional no-ID key-value exception), `24` `EXTENDED_V2_TAB_CONTRACTS`, `91` unique catalogued tabs, `164` unmapped tabs remaining (`255 - 91 = 164`), `12` `CONFLICTING_CORE_SCHEMA_TABS`, `24` `PENDING_OWNER_MAPPING_TABS`, `36` `WRITE_BLOCKED_SCHEMA_TABS`, `coverage_complete = False`, `coverage_status = "INCOMPLETE_PENDING_AUTHORITATIVE_WORKBOOK_EXPORT"`.
  - No fabricated workbook tabs exist in code.
- **Discrepancies Found:**
  - **Group Status Badge Misalignment (`P1.5-006`):** `schema_registry.py:563` (Group `02`, containing conflicting `Suppliers`) and `schema_registry.py:638` (Group `10`, containing conflicting `Expenses`) declare `header_mapping_status: "VERIFIED_CORE"`, causing `ErpOperationsHubView.tsx:1522-1528` to display green `VERIFIED_CORE` badges for groups that contain write-blocked tables.
  - **Missing Summary Chips in UI (`P1.5-006`):** `ErpOperationsHubView.tsx:1493-1513` displays `total_catalogued_tabs` (`91`) and `status_counts`, but does not surface `unmapped_workbook_tabs_remaining` (`164`), `write_blocked_schema_tabs_count` (`36`), or `coverage_status`.

### 2.2 `DB-002`: Conflicting Core Schema Protection (12 Tables)
- **Actual 12 Conflicting Core Tables Verified in `backend/app/schema_registry.py:273-351` (`CONFLICTING_CORE_SCHEMA_TABS`):**
  1. `Suppliers` (2 missing: `payment_terms`, `opening_balance`)
  2. `CustomRoles` (2 missing: `deleted`, `active`)
  3. `SalaryIncentives` (12 missing)
  4. `RawMaterials` (8 missing)
  5. `Products` (1 missing: `recipe_id`)
  6. `Workers` (1 missing: `created_by`)
  7. `Customers` (1 missing: `notes`)
  8. `Sales` (3 missing)
  9. `ProductionBatches` (6 missing)
  10. `PackagingBatches` (4 missing)
  11. `Expenses` (1 missing: `post_accounting_journal`)
  12. `ShopVisits` (5 missing)
  *(Total: 46 declared missing fields.)*
- **Audit Finding on Prior Phase 1 Documentation (`P1.5-004`):** `PHASE1_MASTER_AUDIT_REPORT.md` Section 4 erroneously listed `ApprovalRequests`, `Attendance`, `DailyClosings`, `GoodsReceipts`, `MillingBatches`, `StockMovements`, and `SupplierBills` (7 wrong tables!).
- **Primary-Tab Blocking:** Verified **PASS** for all 12 tables—direct governed actions targeting each table fail closed with `HTTP 503`, `status="BLOCKED_PENDING_OWNER_SETUP"`, `error_code="CORE_SCHEMA_CONFLICT_UNRECONCILED"`, `retryable=False` before any network call or mutation. Read operations remain available.
- **Secondary-Tab Blocking:** **FAIL (`P1.5-001`)** — see Section 3 below and `PHASE1_5_SECURITY_AND_WRITE_PATH_AUDIT.md`.
- **Unlock Hardening (`P1.5-005`):** **PARTIAL / WEAK** — `approve_core_schema_reconciliation()` rejects empty approver, empty headers, duplicate headers, and non-conflicting tabs, **but** accepts arbitrary headers (e.g., `["totally_fake_column"]`) without verifying coverage of `REQUIRED_TABS[tab]` or `missing_from_required_tabs`. JSON-loaded approvals (`get_approved_core_schema_reconciliations()`) also skip duplicate-header validation and read `SALES_APPROVED_CORE_SCHEMA_RECONCILIATIONS_JSON` frozen at import time.

### 2.3 `DB-004` & `P1-NEW-02`: Legacy ID Prefixes & Collisions (`PKG`/`PKB`, `RCPT`, `SAL`)
- **All 10 `LEGACY_TO_LOCKED_ID_PREFIX_ALIASES` Verified in `schema_registry.py:164-245`:**
  | Table | Legacy Prefix | Locked Prefix | `allow_on_new_allocation` | `allow_on_read` | `validate_table_id_prefix` New Legacy | `validate_table_id_prefix` Read Legacy |
  |---|---|---|---|---|---|---|
  | `Customers` | `CUS` | `CUST` | `False` | `True` | `False` (Blocked) | `True` (Allowed) |
  | `JournalHeaders` | `JRN` | `JV` | `False` | `True` | `False` (Blocked) | `True` (Allowed) |
  | `JournalLines` | `JLN` | `JVL` | `False` | `True` | `False` (Blocked) | `True` (Allowed) |
  | `PackagingBatches` | `PKG` | `PKB` | `False` | `True` | `False` (Blocked) | `True` (Allowed) |
  | `Payments` | `PAY` | `RCPT` | `False` | `True` | `False` (Blocked) | `True` (Allowed) |
  | `ProductionBatches` | `PRB` | `PB` | `False` | `True` | `False` (Blocked) | `True` (Allowed) |
  | `ProductionStockLedger` | `PST` | `MOV` | `False` | `True` | `False` (Blocked) | `True` (Allowed) |
  | `RawMaterials` | `RWM` | `RM` | `False` | `True` | `False` (Blocked) | `True` (Allowed) |
  | `SaleItems` | `ITEM` | `INVI` | `False` | `True` | `False` (Blocked) | `True` (Allowed) |
  | `Sales` | `SALE` | `INV` | `False` | `True` | `False` (Blocked) | `True` (Allowed) |
- **`PKG`/`PKB` Separation:** Verified in `validate_table_id_prefix()` (`PackagingMaterials` accepts `PKG` only; `PackagingBatches` accepts `PKB` on new allocation and `PKB|PKG` on read).
- **CRITICAL/HIGH Runtime Enforcement Gaps Found (`P1.5-002`, `P1.5-007`):**
  1. **`SAL` Deadlock (`SalaryIncentives`):** `action_registry.py:1241` declares `locked_prefix="SAL"` on `CREATE_SALARY_INCENTIVE`, while `COLLIDING_LEGACY_PREFIX_TABS["SalaryIncentives"]` blocks `SAL` on new allocation -> **NO ID can ever pass `_validate_id_format()`** (live verified: `SAL-000001`, `INC-000001`, `SINC-000001` all return `False`).
  2. **`RCPT` Unenforced on `SalaryReceipts`:** `SalaryReceipts` is created as a child row of `RECORD_WORKFORCE_PAYMENT` (`action_registry.py:1219-1226`). `AppsScriptBridge` only runs `_validate_id_format()` on the primary `allocated_id` when `effective_locked_prefix` is truthy (`apps_script_bridge.py:844`); child-row IDs (`SalaryReceipts`, `SaleItems`, `JournalLines`) are never validated by the bridge.
  3. **Post-Write Validation Only (`P1.5-007`):** `_validate_id_format()` runs only *after* Apps Script returns `CONFIRMED` (`apps_script_bridge.py:844`), returning `HTTP 504 / PENDING_UNKNOWN` after the row may already be persisted; client-supplied payload IDs are not pre-validated by the bridge.

### 2.4 `DB-005`: 11 Creation Actions `locked_prefix` Verification Matrix
| # | Action | Target Tab | Declared `locked_prefix` | Canonical Valid (`PREFIX-000123`) | Legacy Rejected | Malformed Rejected | Wrong Table Prefix Rejected | Enforcement Location |
|---|---|---|---|---|---|---|---|---|
| 1 | `CREATE_CUSTOMER` | `Customers` | `CUST` | PASS | PASS (`CUS-000123`) | PASS (`CUST-12`) | PASS (`USR-000123`) | `action_registry.py:308` + `apps_script_bridge.py:844` |
| 2 | `CREATE_RAW_MATERIAL_MASTER` | `RawMaterials` | `RM` | PASS | PASS (`RWM-000123`) | PASS (`RM-12`) | PASS (`USR-000123`) | `action_registry.py:326` + `apps_script_bridge.py:844` |
| 3 | `ADJUST_FINISHED_GOODS_STOCK` | `ProductionStockLedger` | `MOV` | PASS | PASS (`PST-000123`) | PASS (`MOV-12`) | PASS (`USR-000123`) | `action_registry.py:472` + `apps_script_bridge.py:844` |
| 4 | `CREATE_PRODUCTION_BATCH` | `ProductionBatches` | `PB` | PASS | PASS (`PRB-000123`) | PASS (`PB-12`) | PASS (`USR-000123`) | `action_registry.py:495` + `apps_script_bridge.py:844` |
| 5 | `RECORD_PACKAGING_PENDING_REVIEW` | `PackagingBatches` | `PKB` | PASS | PASS (`PKG-000123`) | PASS (`PKB-12`) | PASS (`USR-000123`) | `action_registry.py:553` + `apps_script_bridge.py:844` |
| 6 | `RECORD_PACKAGING_BATCH` | `PackagingBatches` | `PKB` | PASS | PASS (`PKG-000123`) | PASS (`PKB-12`) | PASS (`USR-000123`) | `action_registry.py:570` + `apps_script_bridge.py:844` |
| 7 | `CREATE_SALE` | `Sales` | `INV` | PASS | PASS (`SALE-000123`) | PASS (`INV-12`) | PASS (`USR-000123`) | `action_registry.py:665` + `apps_script_bridge.py:844` |
| 8 | `CREATE_SALES_INVOICE` | `Sales` | `INV` | PASS | PASS (`SALE-000123`) | PASS (`INV-12`) | PASS (`USR-000123`) | `action_registry.py:678` + `apps_script_bridge.py:844` |
| 9 | `CREATE_LEGACY_SALES_ORDER` | `Sales` | `INV` | PASS | PASS (`SALE-000123`) | PASS (`INV-12`) | PASS (`USR-000123`) | `action_registry.py:699` + `apps_script_bridge.py:844` |
| 10 | `RECORD_SALE_PAYMENT` | `Payments` | `RCPT` | PASS | PASS (`PAY-000123`) | PASS (`RCPT-12`) | PASS (`USR-000123`) | `action_registry.py:757` + `apps_script_bridge.py:844` |
| 11 | `RECONCILE_FACTORY_STOCK` | `ProductionStockLedger` | `MOV` | PASS | PASS (`PST-000123`) | PASS (`MOV-12`) | PASS (`USR-000123`) | `action_registry.py:840` + `apps_script_bridge.py:844` |

*Note:* All 11 actions pass unit-level format validation, subject to `P1.5-007` (post-write-only check in bridge, and `apps_script_bridge.py:844` skips non-locked tables).

### 2.5 `DB-006`: `ProductLots` Ownership Audit
- **Repository-Wide Search Completed:** Found `ProductLots` across 22 files (`schema_registry.py`, `sheets.py`, `action_registry.py`, `routers/production.py`, `routers/quality.py`, `routers/v2_erp.py`, `src/services/api.ts`, `src/views/ErpOperationsHubView.tsx`, `src/views/QualityView.tsx`, tests, and docs).
- **Verified PASS:** `ProductLots` appears in `workbook_tabs` **exclusively** in Group `03` (`Inventory & Warehousing`, `schema_registry.py:570`), is listed solely under `referenced_tabs` in Group `05` (`Quality & Food Safety`, `schema_registry.py:595`), has canonical locked prefix `LOT` (`schema_registry.py:81`, `sheets.py:86`), and `duplicate_group_placements == {}`.

---

## 3. Summary of Independent Action Cross-Reference (Section 12)

Recalculated directly via AST across all `backend/app/**/*.py` files:
- `len(_SPECS)` = **127**, `len(GOVERNED_ACTION_REGISTRY)` = **127**, duplicate action names = **0**.
- Total `delegate_governed_write` / `execute_governed_write` call-sites = **132** (`131` static string actions covering `125` unique actions + `1` dynamic conditional call at `backend/app/user_service.py:1070` covering `'REACTIVATE_USER' if active else 'DEACTIVATE_USER'` -> **127/127** actions wired).
- Unregistered actions = **0**; `target_tab` mismatches = **0**; `id_field` mismatches = **0**.
- **CRITICAL Divergence from Phase 1 Claims:** While all 127 actions exist and match `target_tab`/`id_field`, **4 real call-sites** pass non-empty `invalidate_tabs` subsets that omit a write-blocked secondary tab (`purchasing.py:520` `RECEIVE_GOODS`, `v2_erp.py:1146` `RECORD_MILLING_BATCH`, `v2_erp.py:634` `RECORD_PACKAGING_BATCH`, `v2_erp.py:1172` `CREATE_PRODUCTION_BATCH`), causing **2 active `DB-002` bypasses today** (`P1.5-001`), and `CREATE_SALARY_INCENTIVE` has a conflicting `locked_prefix="SAL"` deadlock (`P1.5-002`).

---

## 4. Frontend Contract & Regression Audit (Sections 11 & 14)

- **Inspected:** `src/types/index.ts`, `src/views/ErpOperationsHubView.tsx`, `src/views/CustomersView.tsx`, `src/services/api.ts`.
- **Verified:**
  - Zero `@ts-ignore` or `@ts-expect-error` across all 4 inspected frontend files; `0` `any` types in `src/types/index.ts`, `ErpOperationsHubView.tsx`, `CustomersView.tsx` (`4` pre-existing `any` usages in `src/services/api.ts` at lines `651, 2008, 2016, 2023`).
  - `CustomersView.tsx:200` correctly passes `isLoading={isSubmitting}` to `<FormActions>`.
  - `ErpOperationsHubView.tsx:1539-1575` properly normalizes dict/array `tab_reconciliation_conflicts` and displays `conflicting_core_schema_tabs` and `pending_owner_mapping_tabs`.
- **Defects Found (`P1.5-006`):**
  1. `src/services/api.ts:677` reads `detailObj?.workflow_status` (backend actually sends `detail.status = "BLOCKED_PENDING_OWNER_SETUP"`), and `ErpOperationsHubView.tsx:294` checks `err.errorCode === 'BLOCKED_PENDING_OWNER_SETUP'` (backend sends `detail.error_code = "CORE_SCHEMA_CONFLICT_UNRECONCILED"` / `"PENDING_OWNER_MAPPING"` / `"APPS_SCRIPT_BRIDGE_UNCONFIGURED"`). Consequently, schema-blocked `HTTP 503` responses are misrouted to generic `NOT_SAVED` instead of the `BLOCKED_PENDING_OWNER_SETUP` banner.
  2. Group `02` and Group `10` render green `VERIFIED_CORE` badges despite containing conflicting tables `Suppliers` and `Expenses`.
- **Diff Completeness Notice (Section 14):** Because `.git` is absent from this workspace snapshot, automated before/after diff comparison against pre-Phase-1 source revisions could not be performed; regression review was conducted by direct full-file source inspection and static/runtime verification. No hardcoded production credentials, TODO bypasses, or weakened tests were observed in the modified files, though `test_db002_bridge_blocks_primary_and_secondary_conflicting_core_tabs` failed to test subset `invalidate_tabs=[primary_tab]`, allowing `P1.5-001` to slip through.

---

## 5. External Artifact Blockers (Section 16)

Independent repository scan confirmed all three external blockers remain genuinely **OPEN / BLOCKED**:
- **`DB-003`:** Zero `.xlsx` workbooks and zero `DBV5_FIELD_DICTIONARY_3074` exports exist in the workspace (`164/255` tabs remain unmapped).
- **`DB-007`:** Zero physical Row-1 Google Sheets header exports exist to verify the 55 core clean tables, reconcile the 12 conflicting core tables, or map the 24 extended / 164 unmapped tabs.
- **`DB-008`:** Zero `WebAppBridge.gs` / `function doPost` files exist in the repository (only 3 offline workforce maintenance scripts exist in `docs/`: `workforceDiagnosticReport.gs`, `workforceMigration.gs`, `workforceSchemaUpgrade_2026-11-03-v1.gs`).
