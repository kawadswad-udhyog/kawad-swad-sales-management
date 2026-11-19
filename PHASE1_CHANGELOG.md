# KAWAD SWAD ERP — PHASE 1 CHANGELOG
**Phase:** Phase 1 — Database Integrity, Repair Review, Verification & Closure
**Date:** 2026-11-19

---

## 1. Summary of Original Phase 1 Repairs (`DB-001`, `DB-002`, `DB-004`, `DB-005`, `DB-006`)

1. **`DB-001` — Implemented `get_schema_coverage_summary()`**: Restored missing function imported by `v2_erp.py` and exposed live coverage metrics (`255` baseline, `91` catalogued, `164` unmapped, `12` conflicting core, `24` extended pending, `36` write-blocked, `coverage_complete=False`).
2. **`DB-002` — Fail-Closed Core Schema Conflict Gate**: Added `CONFLICTING_CORE_SCHEMA_TABS` (all 12 conflicting core tables), `WRITE_BLOCKED_SCHEMA_TABS` (36 tabs), `SALES_APPROVED_CORE_SCHEMA_RECONCILIATIONS_JSON` (default `""`), strict `approve_core_schema_reconciliation()` validation, and fail-closed `HTTP 503 / CORE_SCHEMA_CONFLICT_UNRECONCILED` enforcement in `AppsScriptBridge`.
3. **`DB-004` — Centralized ID-Prefix Validation & `PKG`/`PKB` Separation**: Implemented `get_locked_prefix_for_tab()`, `get_allowed_id_prefixes_for_tab()`, and `validate_table_id_prefix()`; cleanly separated `PackagingMaterials` (`PKG`) from `PackagingBatches` (`PKB` new / `PKB|PKG` historical read).
4. **`DB-005` — Explicit `locked_prefix` on All 11 Creation Actions**: Added explicit `locked_prefix` declarations across all 11 affected creation actions in `action_registry.py` and wired centralized validation with `_effective_locked_prefix()` fallback in `AppsScriptBridge._validate_id_format()`.
5. **`DB-006` — Resolved `ProductLots` Duplicate Group Placement**: Retained `ProductLots` exclusively under Group `03` (`Inventory & Warehousing`), removed it from Group `05` (`Quality & Food Safety`) `workbook_tabs`, and recorded it under Group `05` `referenced_tabs`.

---

## 2. New Hardening & Defect Fixes Applied During Phase 1 Review (`P1-NEW-01` – `P1-NEW-06`)

1. **`P1-NEW-01` (CRITICAL — Closed Secondary-Tab `DB-002` Bypass)**: Hardened `AppsScriptBridge.execute_governed_write()` to check `get_schema_write_block_reason()` across `clean_tab` (primary), every tab in `requested_inv` (or `spec.allowed_invalidate_tabs` when `requested_inv` is omitted), and every `child.tab` in `spec.readback.child_checks`. Closes bypasses on all 12 secondary-tab governed actions.
2. **`P1-NEW-02` (HIGH — Hardened Legacy Prefix Allocation & Cross-Table Collisions)**: Set `allow_on_new_allocation: False` and `allow_on_read: True` on all 10 `LEGACY_TO_LOCKED_ID_PREFIX_ALIASES` entries; added `COLLIDING_LEGACY_PREFIX_TABS` and `TAB_RECONCILIATION_CONFLICTS` entries guarding `SalaryReceipts` (`RCPT` collides with `Payments`) and `SalaryIncentives` (`SAL` collides with `SalaryPayments`).
3. **`P1-NEW-03` (MEDIUM — Synchronized Schema Registry Frontend/Backend Contract)**: Updated `SchemaRegistryPayload` in `src/types/index.ts` and normalized dict/array `tab_reconciliation_conflicts` plus rendered `conflicting_core_schema_tabs` in `src/views/ErpOperationsHubView.tsx`.
4. **`P1-NEW-04` (MEDIUM — Fixed Frontend TypeScript Build Errors)**: Fixed `<FormActions isLoading={isSubmitting} />` in `src/views/CustomersView.tsx`, imported `ApiOutcomeUnknownError`, narrowed `unknown` errors, and removed unreachable `PENDING_UNKNOWN` branches in `src/views/ErpOperationsHubView.tsx`.
5. **`P1-NEW-05` (LOW — Stdlib Test Harness `fastapi.Request` Stub)**: Added `class Request` to `MockFastAPIModule` in `backend/tests/__init__.py` so Blueprint v2.1 routers import cleanly in isolated Python stdlib test runs.
6. **`P1-NEW-06` (CRITICAL — Fixed Backend Startup `NameError` in Auth Router)**: Imported missing `require_sheets_connection` from `app.auth` in `backend/app/routers/auth.py` (line 161 decorator crash preventing `app.main` import).

---

## 3. Complete List of Files Modified / Added

### Backend Source Files Modified
| File | Reason |
|---|---|
| `backend/app/config.py` | Added fail-closed `SALES_APPROVED_CORE_SCHEMA_RECONCILIATIONS_JSON` env setting (`DB-002`) |
| `backend/app/schema_registry.py` | Implemented `get_schema_coverage_summary()` (`DB-001`), 12 conflicting core tab fail-closed guards & strict unlock API (`DB-002`), hardened all 10 legacy aliases + `PKG`/`PKB` + `RCPT`/`SAL` collision guards (`DB-004`, `P1-NEW-02`), and single canonical Group `03` placement for `ProductLots` (`DB-006`) |
| `backend/app/apps_script_bridge.py` | Enforced fail-closed schema conflict gate across primary, secondary invalidation, and readback child tabs (`DB-002`, `P1-NEW-01`) and centralized `_validate_id_format()` / `_effective_locked_prefix()` (`DB-004`, `DB-005`) |
| `backend/app/action_registry.py` | Added explicit `locked_prefix` to all 11 affected creation actions (`DB-005`) |
| `backend/app/routers/v2_erp.py` | Exposed full `get_schema_coverage_summary()`, `CONFLICTING_CORE_SCHEMA_TABS`, `LEGACY_TO_LOCKED_ID_PREFIX_ALIASES`, and `SCHEMA_HEADER_VARIANCES` in `GET /api/v2/meta/schema-registry` (`DB-001`, `DB-002`) |
| `backend/app/routers/auth.py` | Imported missing `require_sheets_connection` from `app.auth` to fix startup `NameError` (`P1-NEW-06`) |

### Frontend Source Files Modified
| File | Reason |
|---|---|
| `src/types/index.ts` | Aligned `SchemaRegistryPayload` with backend dict `tab_reconciliation_conflicts` and Phase 1 schema-coverage fields (`P1-NEW-03`) |
| `src/views/ErpOperationsHubView.tsx` | Normalized dict/array `tab_reconciliation_conflicts`, displayed `conflicting_core_schema_tabs`, imported `ApiOutcomeUnknownError`, narrowed `unknown` catch errors, and removed dead branches (`P1-NEW-03`, `P1-NEW-04`) |
| `src/views/CustomersView.tsx` | Fixed `<FormActions isLoading={isSubmitting} />` TypeScript prop mismatch (`P1-NEW-04`) |

### Regression Tests Added / Updated
| File | Reason |
|---|---|
| `backend/tests/__init__.py` | Added `Request` stub to `MockFastAPIModule` for isolated stdlib testing (`P1-NEW-05`) |
| `backend/tests/test_phase1_database_schema_guards.py` | Added 8 comprehensive Phase 1 regression tests covering `DB-001`, `DB-002`, `DB-004`, `DB-005`, `DB-006`, `P1-NEW-01`, `P1-NEW-02`, `P1-NEW-06`, full `app.main` startup, and `GET /api/v2/meta/schema-registry` live contract |

### Audit & Governance Deliverables Added
| File | Purpose |
|---|---|
| `PHASE1_MASTER_AUDIT_REPORT.md` | Complete Phase 1 audit report and closure evaluation |
| `PHASE1_DEFECT_REGISTER.md` | Unified defect register (`DB-001`–`DB-008` and `P1-NEW-01`–`P1-NEW-06`) |
| `PHASE1_DATABASE_RECONCILIATION.csv` | Machine-readable reconciliation ledger (91 catalogued tables + 1 explicit unmapped-164 row = 255 baseline) |
| `PHASE1_VERIFICATION_RESULTS.md` | Complete isolated test & build command ledger and 50-suite backend breakdown |
| `PHASE1_CHANGELOG.md` | This changelog |
| `PHASE1_FINAL_GATE.md` | Formal Phase 1 closure decision and Owner unlock criteria |
| `docs/PHASE1_DATABASE_REPAIR_AND_APPS_SCRIPT_AUDIT_REPORT.md` | Detailed technical appendix on Phase 1 repairs and Apps Script audit status |

---

## 4. Migration Impact

- **Live Google Sheets / Production Data Impact:** **NONE** — Zero live spreadsheet reads, writes, header modifications, or ID conversions were executed.
- **Backward Compatibility:** Historical records carrying legacy ID prefixes (`CUS`, `JRN`, `JLN`, `PKG`, `PAY`, `PRB`, `PST`, `RWM`, `ITEM`, `SALE`) remain readable (`allow_on_read=True`) with zero destructive data migration required. New allocations strictly enforce canonical `LOCKED_32_ID_PREFIXES`.
- **Operational Write Posture:** All 12 conflicting core tables and 24 extended pending tables (`36` tabs total) remain fail-closed (`HTTP 503`) until the Owner supplies confirmed physical workbook Row-1 headers and sets `SALES_APPROVED_CORE_SCHEMA_RECONCILIATIONS_JSON` (or completes workbook header alignment via Apps Script).
