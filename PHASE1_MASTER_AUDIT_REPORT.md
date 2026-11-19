# KAWAD SWAD ERP — PHASE 1 MASTER AUDIT REPORT
**Phase:** Phase 1 — Database Integrity, Repair Review, Verification & Closure
**Repository:** `kawadswad-udhyog/kawad-swad-sales-management` (local workspace snapshot)
**Audit Date:** 2026-11-19
**Audit Basis:** `Kawad_Swad_Phase1_Database_Audit_ZIP38.txt` (`DB-001` through `DB-008`), live workspace source inspection, static AST analysis, isolated local backend verification, and frontend TypeScript/Vite build verification.
**Live System Safety:** **ZERO LIVE IMPACT** — Google Sheets NOT accessed or modified; Apps Script NOT deployed; Render NOT deployed; production environment variables/credentials NOT present or modified; no live migrations executed.

---

## 1. Executive Summary

Phase 1 audited the database schema governance layer, ID-allocation contract, governed write bridge (`AppsScriptBridge`), governed action registry (`GOVERNED_ACTION_REGISTRY`), schema metadata API (`GET /api/v2/meta/schema-registry`), frontend operations hub contract, and startup integrity of Kawad Swad ERP.

**Code-Side Phase 1 Integrity Repairs — VERIFIED PASS:**
- All 5 code-addressable original findings (**`DB-001`**, **`DB-002`**, **`DB-004`**, **`DB-005`**, **`DB-006`**) were audited, hardened beyond their initial patches, and verified with automated regression tests (`8/8 PASS` in `tests.test_phase1_database_schema_guards`).
- Six additional defects discovered during this Phase 1 verification pass (**`P1-NEW-01`** through **`P1-NEW-06`**) — including a **CRITICAL secondary-tab write-block bypass across 12 governed actions (`P1-NEW-01`)**, a **CRITICAL backend startup `NameError` in `backend/app/routers/auth.py` (`P1-NEW-06`)**, a **HIGH legacy-prefix new-allocation gap on 9 of 10 aliases plus cross-table `RCPT`/`SAL` collisions (`P1-NEW-02`)**, a **MEDIUM frontend/backend schema-registry dict-vs-array contract mismatch (`P1-NEW-03`)**, **MEDIUM frontend TypeScript build failures (`P1-NEW-04`)**, and a **LOW stdlib test-harness stub gap (`P1-NEW-05`)** — were fixed and locally verified.
- All **112/112** backend `.py` files pass `py_compile`; all **127/127** governed actions cross-reference cleanly with zero unregistered call-sites and zero missing `locked_prefix` declarations; frontend `npm run lint` (`tsc --noEmit`) and `npm run build` (`tsc && vite build`) pass with **exit code 0** (`2,325` modules transformed).

**External Artifact Blockers — GENUINELY BLOCKED (NOT FABRICATED):**
- Three external-evidence findings (**`DB-003`**, **`DB-007`**, **`DB-008`**) remain **BLOCKED** because the authoritative external artifacts are absent from the repository workspace:
  1. Authoritative 255-tab Google Sheets workbook export (`.xlsx` / CSV header dump) and `DBV5_FIELD_DICTIONARY_3074` — required to map the remaining **164 unmapped tabs** (`DB-003`) and verify physical Row-1 headers for all **255 tabs** including the **12 conflicting core tables** (`DB-007`).
  2. Live Google Apps Script single-write-owner source (`WebAppBridge.gs` / `doPost` / 16-file Apps Script project) — required to audit the actual database writer, locking, validation, and ID generation (`DB-008`).

**Official Phase 1 Gate Decision:** **`BLOCKED` (Code Repairs Verified Pass; Phase 1 Closure Held Pending External Owner Artifacts or Written Scope-Limitation Sign-Off)** — see `PHASE1_FINAL_GATE.md`.

---

## 2. Original Audit Findings (`DB-001` – `DB-008`) Status Matrix

| Finding ID | Summary | Original Severity | Current Status | Verification Summary |
|---|---|---|---|---|
| **DB-001** | Missing `get_schema_coverage_summary()` crashed `v2_erp` / `app.main` startup | CRITICAL | **FIXED & VERIFIED** | Implemented in `backend/app/schema_registry.py`; `app.main` and `GET /api/v2/meta/schema-registry` verified live in `test_db001_app_main_and_v2_erp_import_startup` (after also fixing `P1-NEW-06`). |
| **DB-002** | 12 conflicting core schemas lacked fail-closed write protection | CRITICAL | **FIXED, HARDENED & VERIFIED** | Fail-closed `CONFLICTING_CORE_SCHEMA_TABS` gate enforced on **primary**, **secondary invalidation**, AND **read-back child** tabs in `AppsScriptBridge.execute_governed_write()` (closing `P1-NEW-01`). All 12 core tables and 12 secondary-tab bypass actions verified blocked (`HTTP 503`, `CORE_SCHEMA_CONFLICT_UNRECONCILED`). |
| **DB-003** | Incomplete 255-tab blueprint coverage (91 catalogued / 164 unmapped) | HIGH | **BLOCKED (EXTERNAL ARTIFACT)** | Registry reports honest live counts (`91` catalogued, `164` remaining, `coverage_complete: false`). Authoritative workbook export and `DBV5_FIELD_DICTIONARY_3074` are absent from workspace; zero tabs fabricated. |
| **DB-004** | Legacy ID mappings & `PKG`/`PKB` collision (plus `RCPT`/`SAL` collisions) | HIGH | **FIXED, HARDENED & VERIFIED** | Hardened all 10 `LEGACY_TO_LOCKED_ID_PREFIX_ALIASES` to `allow_on_new_allocation=False`, `allow_on_read=True` (`P1-NEW-02`); separated `PackagingMaterials` (`PKG`) vs `PackagingBatches` (`PKB` new / `PKB|PKG` read); added `COLLIDING_LEGACY_PREFIX_TABS` blocking `RCPT` on `SalaryReceipts` and `SAL` on `SalaryIncentives`. |
| **DB-005** | 11 affected creation actions missing `locked_prefix` enforcement | HIGH | **FIXED & VERIFIED** | Explicit `locked_prefix` added to all 11 actions in `backend/app/action_registry.py`, plus centralized `validate_table_id_prefix()` & `_effective_locked_prefix()` fallback in `AppsScriptBridge._validate_id_format()`. Verified across all 11 actions. |
| **DB-006** | `ProductLots` duplicated across Group `03` and Group `05` | MEDIUM | **FIXED & VERIFIED** | Canonical ownership pinned to Group `03` (`Inventory & Warehousing`); removed from Group `05` `workbook_tabs` and tracked under `referenced_tabs: ["ProductLots"]`. `duplicate_group_placements == {}`. |
| **DB-007** | Physical Row-1 workbook headers unverified (55 clean + 12 conflicting + 24 extended + 164 unmapped) | HIGH | **BLOCKED (EXTERNAL ARTIFACT)** | No physical workbook export in repository. Code-side `REQUIRED_TABS` (67 tables, 891 columns) verified internally consistent; 12 conflicting core tables remain write-blocked fail-closed until Owner supplies physical Row-1 headers and explicit reconciliation approval. |
| **DB-008** | Google Apps Script database writer (`doPost` / `WebAppBridge.gs`) unaudited | CRITICAL | **BLOCKED (EXTERNAL ARTIFACT)** | Exhaustive workspace scan confirmed live Apps Script project is absent (only 3 offline workforce `.gs` scripts in `docs/`). Backend bridge enforces client-side pre-checks and read-back verification, but server-side Apps Script `LockService`, sheet-write atomicity, and ID-counter monotonicity remain unaudited. |

---

## 3. Repair Review & Hardening Audit

Each Phase 1 repair was independently re-audited line by line:

1. **`backend/app/config.py`**:
   - Added `SALES_APPROVED_CORE_SCHEMA_RECONCILIATIONS_JSON` (default `""`, strictly fail-closed).
   - Malformed JSON or incomplete approval entries fail closed without crashing startup.
2. **`backend/app/schema_registry.py`**:
   - `WORKBOOK_TARGET_TAB_COUNT = 255` and `get_schema_coverage_summary()` dynamically compute all counts directly from `DATABASE_GROUPS_15`, `REQUIRED_TABS`, `EXTENDED_V2_TAB_CONTRACTS`, `CONFLICTING_CORE_SCHEMA_TABS`, and `PENDING_OWNER_MAPPING_TABS`.
   - `approve_core_schema_reconciliation()` (hardened in Phase 1.6 for `P1.5-005`) validates non-empty `approved_by`, target membership in `CONFLICTING_CORE_SCHEMA_TABS`, unique non-blank strings matching trusted `REQUIRED_TABS[tab]` (in exact leading canonical order) plus all declared `missing_from_required_tabs` variance fields with zero unexpected columns, and exact physical Row-1 match when `physical_headers` is supplied.
   - `LEGACY_TO_LOCKED_ID_PREFIX_ALIASES` hardened so **10/10** entries set `allow_on_new_allocation: False` and `allow_on_read: True`.
   - `COLLIDING_LEGACY_PREFIX_TABS` explicitly flags `SalaryReceipts` (`RCPT` collides with canonical `Payments`) and `SalaryIncentives` (`SAL` collides with canonical `SalaryPayments`), preventing ambiguous prefix reuse.
   - `validate_table_id_prefix()` enforces `^([A-Z]{2,6})-[A-Z0-9_-]{3,}$` on new allocations, permits historical legacy aliases only when `for_new_allocation=False`, and rejects cross-table colliding prefixes.
3. **`backend/app/apps_script_bridge.py`**:
   - **Closed `P1-NEW-01` & `P1.5-001` (Secondary-Tab Bypass):** `execute_governed_write()` inspects the full union of `clean_tab` (primary), ALL `spec.allowed_invalidate_tabs`, any allowlisted `requested_inv`, and every `child.tab` in `spec.readback.child_checks`. Any tab returning a block reason from `get_schema_write_block_reason()` fails closed with `HTTP 503` (`CORE_SCHEMA_CONFLICT_UNRECONCILED` or `PENDING_OWNER_MAPPING`).
   - Replaced the legacy 6-table `if/elif` prefix check in `_validate_id_format()` with `validate_table_id_prefix(..., for_new_allocation=True, explicit_locked_prefix=effective_prefix)` and `_effective_locked_prefix(spec)`.
4. **`backend/app/action_registry.py`**:
   - All 11 affected creation actions declare explicit `locked_prefix`:
     - `CREATE_CUSTOMER` -> `CUST`
     - `CREATE_RAW_MATERIAL_MASTER` -> `RM`
     - `ADJUST_FINISHED_GOODS_STOCK` -> `MOV`
     - `CREATE_PRODUCTION_BATCH` -> `PB`
     - `RECORD_PACKAGING_PENDING_REVIEW` -> `PKB`
     - `RECORD_PACKAGING_BATCH` -> `PKB`
     - `CREATE_SALE` -> `INV`
     - `CREATE_SALES_INVOICE` -> `INV`
     - `CREATE_LEGACY_SALES_ORDER` -> `INV`
     - `RECORD_SALE_PAYMENT` -> `RCPT`
     - `RECONCILE_FACTORY_STOCK` -> `MOV`
   - Cross-reference scan verified **127/127** governed actions wired (`0` unregistered actions, `0` target_tab mismatches, `0` id_field mismatches, `0` unknown invalidation tabs).
5. **`backend/app/routers/auth.py`**:
   - **Closed `P1-NEW-06` (Critical Startup Crash):** Imported missing `require_sheets_connection` from `app.auth`, resolving `NameError` at line 161 (`@router.post("/api/auth/change-password", dependencies=[Depends(require_sheets_connection)])`) that prevented `app.main` from importing.
6. **`backend/app/routers/v2_erp.py`, `src/types/index.ts`, `src/views/ErpOperationsHubView.tsx`, `src/views/CustomersView.tsx`**:
   - Synchronized `GET /api/v2/meta/schema-registry` response and TypeScript `SchemaRegistryPayload` contract (`P1-NEW-03`), fixed dict-vs-array normalization in `ErpOperationsHubView.tsx`, and resolved remaining TypeScript compile errors (`P1-NEW-04`).

---

## 4. Database Inventory & Blueprint Coverage

Recalculated directly from `backend/app/schema_registry.py` and `backend/app/sheets.py` (exact inventory exported to `PHASE1_DATABASE_RECONCILIATION.csv`):

| Metric | Verified Count | Notes |
|---|---:|---|
| Cleaned Workbook Target Baseline | **255** | Post-cleanup authoritative tab count (46 scratch tabs permanently retired) |
| Declared Database Groups | **15** | Groups `00` through `14` |
| Group Tab References Total | **91** | `0` duplicate group placements (`ProductLots` fixed under Group `03`) |
| Core `REQUIRED_TABS` | **67** | `891` total columns; `0` blank or duplicate column names |
| Core `ID_PREFIXES` | **66** | `Settings` is the sole intentional key-value no-ID exception |
| Core Non-Conflicting Tables (Code Contract Complete) | **55** | Writes allowed via Apps Script bridge (pending physical workbook confirmation) |
| Core Conflicting Schema Tables (`DB-002`) | **12** | `46` declared missing fields; **WRITE-BLOCKED FAIL-CLOSED** |
| Extended v2.1 Contract Tables | **24** | `21` `PENDING_OWNER_MAPPING`, `2` `CONFLICT_RECONCILIATION_REQUIRED`, `1` `RECONCILED_TO_EXCEPTION_REGISTER`; **ALL 24 WRITE-BLOCKED** |
| Total Unique Catalogued Workbook Tabs | **91** | `67` core + `24` extended = `91` (`35.69%` of 255) |
| Total Write-Blocked Catalogued Tabs | **36** | `12` conflicting core + `24` extended pending = `36` |
| Unmapped Workbook Tabs Remaining (`DB-003`) | **164** | `64.31%` of 255 — absent from repo, **NOT fabricated**, fail-closed |
| Locked Canonical ID Prefixes | **32** | Enforced via `LOCKED_32_ID_PREFIXES` |

### The 12 Conflicting Core Tables (Reconstructed Directly From `backend/app/schema_registry.py:273-351` — Corrected in Phase 1.6 for `P1.5-004`)

*(Note: All 12 conflicts remain UNRESOLVED pending physical Google Sheets Row-1 header export `DB-007` and remain write-blocked fail-closed by `DB-002`.)*

| # | Table / Tab Name | Source Definition | Declared Missing Fields (`missing_from_required_tabs`) | Count | Resolved? |
|---|---|---|---|---:|---|
| 1 | `Suppliers` | `schema_registry.py:273-283`, `sheets.py` `REQUIRED_TABS['Suppliers']`, `routers/purchasing.py` | `payment_terms`, `opening_balance` | 2 | No (Write-Blocked) |
| 2 | `CustomRoles` | `schema_registry.py:284-288`, `sheets.py` `REQUIRED_TABS['CustomRoles']`, `routers/users.py` | `deleted`, `active` | 2 | No (Write-Blocked) |
| 3 | `SalaryIncentives` | `schema_registry.py:289-297`, `sheets.py` `REQUIRED_TABS['SalaryIncentives']`, `routers/salary.py` | `record_id`, `period_start`, `period_end`, `record_type`, `eligible_kg`, `completed_100kg_blocks`, `rate`, `calculated_amount`, `approved_amount`, `approval_status`, `paid_datetime`, `payment_reference` | 12 | No (Write-Blocked) |
| 4 | `RawMaterials` | `schema_registry.py:298-305`, `sheets.py` `REQUIRED_TABS['RawMaterials']`, `routers/production.py` | `active`, `notes`, `opening_stock`, `opening_stock_verified`, `verification_status`, `verified_physical_stock`, `verified_by`, `verified_at` | 8 | No (Write-Blocked) |
| 5 | `Products` | `schema_registry.py:306-310`, `sheets.py` `REQUIRED_TABS['Products']`, `routers/products.py` | `recipe_id` | 1 | No (Write-Blocked) |
| 6 | `Workers` | `schema_registry.py:311-315`, `sheets.py` `REQUIRED_TABS['Workers']`, `routers/production.py` | `created_by` | 1 | No (Write-Blocked) |
| 7 | `Customers` | `schema_registry.py:316-320`, `sheets.py` `REQUIRED_TABS['Customers']`, `routers/customers.py` | `notes` | 1 | No (Write-Blocked) |
| 8 | `Sales` | `schema_registry.py:321-325`, `sheets.py` `REQUIRED_TABS['Sales']`, `routers/sales.py` | `cash_collected`, `credit_amount`, `owner_credit_approval_id` | 3 | No (Write-Blocked) |
| 9 | `ProductionBatches` | `schema_registry.py:326-333`, `sheets.py` `REQUIRED_TABS['ProductionBatches']`, `routers/production.py` | `gross_output_kg`, `process_loss_kg`, `loss_reason`, `saleable_output_kg`, `unexplained_variance_kg`, `ingredients` | 6 | No (Write-Blocked) |
| 10 | `PackagingBatches` | `schema_registry.py:334-340`, `sheets.py` `REQUIRED_TABS['PackagingBatches']`, `routers/production.py` | `recipe_id`, `bulk_batch_id`, `bulk_product_key`, `bulk_quantity_consumed_kg` | 4 | No (Write-Blocked) |
| 11 | `Expenses` | `schema_registry.py:341-345`, `sheets.py` `REQUIRED_TABS['Expenses']`, `routers/expenses.py` | `post_accounting_journal` | 1 | No (Write-Blocked) |
| 12 | `ShopVisits` | `schema_registry.py:346-350`, `sheets.py` `REQUIRED_TABS['ShopVisits']`, `routers/visits.py` | `shop_name_snapshot`, `visit_outcome`, `order_taken`, `follow_up_date`, `next_action` | 5 | No (Write-Blocked) |

*(Total declared missing fields across the 12 conflicting core tables: **46**. Prior report erroneously listed `ApprovalRequests`, `Attendance`, `DailyClosings`, `GoodsReceipts`, `MillingBatches`, `StockMovements`, and `SupplierBills`, which are NOT in `CONFLICTING_CORE_SCHEMA_TABS`.)*

---

## 5. ID Prefix Audit (`DB-004` & `DB-005`)

- **Canonical-Only New Allocations:** All 10 legacy prefix mappings (`Customers`/`CUS`->`CUST`, `JournalHeaders`/`JRN`->`JV`, `JournalLines`/`JLN`->`JVL`, `PackagingBatches`/`PKG`->`PKB`, `Payments`/`PAY`->`RCPT`, `ProductionBatches`/`PRB`->`PB`, `ProductionStockLedger`/`PST`->`MOV`, `RawMaterials`/`RWM`->`RM`, `SaleItems`/`ITEM`->`INVI`, `Sales`/`SALE`->`INV`) reject legacy prefixes on new allocations (`allow_on_new_allocation: False`) while preserving historical read compatibility (`allow_on_read: True`).
- **`PKG` / `PKB` Separation:** `PackagingMaterials` exclusively allocates/validates `PKG`; `PackagingBatches` allocates `PKB` on new writes and accepts `PKB` or historical `PKG` on reads.
- **Cross-Table Collisions Blocked:** `SalaryReceipts` (`RCPT`, colliding with `Payments`) and `SalaryIncentives` (`SAL`, colliding with `SalaryPayments`) are explicitly registered in `COLLIDING_LEGACY_PREFIX_TABS` and `TAB_RECONCILIATION_CONFLICTS` so colliding prefixes cannot be allocated on new writes.
- **11 Creation Actions Enforced:** Every creation action targeting a locked-prefix table declares explicit `locked_prefix` in `action_registry.py` and passes `AppsScriptBridge._validate_id_format()` as well as pre-write `_preflight_validate_payload_ids()` (added in Phase 1.6 for `P1.5-007`).

---

## 6. Apps Script Writer Audit (`DB-008`)

Workspace search confirmed **only 3 offline maintenance scripts** exist in the repository:
- `docs/workforceDiagnosticReport.gs`
- `docs/workforceMigration.gs`
- `docs/workforceSchemaUpgrade_2026-11-03-v1.gs`

The live single-write-owner Apps Script project (`WebAppBridge.gs`, `doPost()`, locking, HMAC/token validation, ID sequence generator, and atomic multi-tab row writers) is **not present in the repository**. Therefore:
- Backend pre-write enforcement (`AppsScriptBridge`), nonce/idempotency headers, response echo validation, and read-back verification contracts are audited and verified.
- Server-side Apps Script implementation (`DB-008`) **cannot be certified** until the Owner provides the actual Apps Script project source files.

---

## 7. API Contract & Frontend Alignment Audit

- `GET /api/v2/meta/schema-registry` verified live via `v2_erp.get_schema_registry_metadata()` returning `cleaned_tab_baseline: 255`, `conflicting_core_schema_tabs` (12-item sorted list), `tab_reconciliation_conflicts` (dict), and `table_registry_summary` (`total_catalogued_tabs: 91`, `unmapped_workbook_tabs_remaining: 164`, `write_blocked_schema_tabs_count: 36`, `coverage_complete: False`).
- `src/types/index.ts` and `src/views/ErpOperationsHubView.tsx` now match this contract accurately (previously `tab_reconciliation_conflicts.length` evaluated to `undefined` on the backend dict).
- `src/views/CustomersView.tsx` fixed invalid `isSubmitting` prop on `<FormActions>` to `isLoading`.
- Frontend `npm run lint` (`tsc --noEmit`) and `npm run build` (`tsc && vite build`) both passed with **exit code 0**.

---

## 8. Verification Summary

Full command-by-command records are documented in `PHASE1_VERIFICATION_RESULTS.md`. Key highlights:
- **Isolation Confirmed:** `SALES_TESTING=1`, `SALES_ENV=development`, `SALES_GOOGLE_SPREADSHEET_ID=""`, `SALES_GOOGLE_SERVICE_ACCOUNT_JSON=""`, `SALES_APPS_SCRIPT_ENABLED=false`; `db.is_connected == False`.
- **Backend Syntax (`py_compile`):** **112/112 PASS** (`0` errors).
- **Backend AST Undefined-Name & Action-Registry Cross-Reference:** **PASS** (`127/127` actions wired, `0` undefined module-level names after fixing `auth.py`).
- **Phase 1 Guard Suite (`tests.test_phase1_database_schema_guards`):** **8/8 PASS** (exit 0, 0.058s) — covers `DB-001`, `DB-002`, `DB-004`, `DB-005`, `DB-006`, `P1-NEW-01`, `P1-NEW-02`, `P1-NEW-06`.
- **Isolated Backend Stdlib Regression Sweep (50 test files total):**
  - **8 suites / 59 tests PASS (100%)**: `test_phase1_database_schema_guards` (8), `test_alias_adapter` (5), `test_cors_preflight` (8), `test_health_diagnostics_security_and_quota` (8), `test_owner_setup` (1), `test_production_backend_routing` (5), `test_sheets_quota_handling` (3), `test_workforce_migration_safety` (21).
  - **42 legacy pre-v2.1 test files FAIL due to pre-existing Blueprint v2.1 architectural changes (ZERO Phase 1 regressions)**: ~34 files invoke write endpoints without the Blueprint v2.1 `request: Request` parameter; ~8 files intentionally hit Blueprint v2.1 `BLOCKED_PENDING_OWNER_SETUP` direct-write / unconfigured-bridge protections (`POL-021`/`POL-024`).
  - **Environment Limitation Noted Honestly:** Container runs Python 3.11.2 stdlib without `pip`/`fastapi`/`pydantic`/`gspread` installed; backend execution uses the repository's stdlib mock harness (`backend/tests/__init__.py`). Full ASGI `TestClient` runtime tests remain `BLOCKED` on container dependency availability.
- **Frontend Verification:** `npm run lint` (`LINT_EXIT=0`) and `npm run build` (`BUILD_EXIT=0`, `2,325` modules transformed in `15.89s`).

---

## 9. Security & Data-Integrity Implications

1. **Zero Silent Data Corruption on Unreconciled Schemas:** All 36 write-blocked tabs (12 conflicting core + 24 extended pending) fail closed on primary, secondary invalidation, and read-back child paths (`HTTP 503`).
2. **No Bypass via Secondary Multi-Tab Writes (`P1-NEW-01` & `P1.5-001`):** Actions targeting clean primary tables (`RawMaterialLedger`, `GoodsReceipts`, `MillingBatches`, `ProductionStockLedger`, `Payments`, `DailyClosing`, `ApprovalRequests`) can no longer implicitly mutate conflicting core tables (`RawMaterials`, `Products`, `Sales`, `Expenses`, `ProductionBatches`) even when callers pass a partial `invalidate_tabs` list.
3. **No Silent Legacy Prefix Contamination (`P1-NEW-02`):** New writes strictly require canonical `LOCKED_32_ID_PREFIXES`; historical legacy rows remain readable without destructive conversion.
4. **Startup Integrity Restored (`P1-NEW-06`):** `app.main` boots cleanly without crashing on `auth.py`.
5. **Remaining Operational Risk:** Until `DB-007` and `DB-008` are resolved with physical workbook headers and Apps Script writer source, production writes to the 12 conflicting core business tables remain intentionally halted (safe, fail-closed, but non-operational for those 12 tables).

---

## 10. Remaining Blockers & Phase 1 Closure Decision

- **Remaining Blockers:** `DB-003` (164 unmapped tabs), `DB-007` (physical Row-1 headers for 255 tabs & reconciliation of 12 conflicting core tables), `DB-008` (Apps Script `doPost` writer source audit), and container-level full ASGI `pytest`/FastAPI runtime execution.
- **Phase 1 Closure Decision:** **`BLOCKED`** (not artificially closed). All code-side Phase 1 integrity repairs (`DB-001`, `DB-002`, `DB-004`, `DB-005`, `DB-006`, `P1-NEW-01`–`P1-NEW-06`) are complete and verified. Phase 1 closes upon either (a) Owner delivery of the authoritative workbook export, `DBV5_FIELD_DICTIONARY_3074`, and Apps Script writer source for final reconciliation, or (b) explicit written Owner acceptance of `DB-003`/`DB-007`/`DB-008` as scoped limitations to authorize entry into **Phase 2: API & Permission Audit** while keeping the 36 unresolved tables fail-closed.
