# Kawad Swad ERP — Phase 1.8 External Database & Writer Blockers

## 1. Authoritative Database Posture (Google Sheets Remains Sole Authority)
- Google Sheets remains the sole authoritative business database.
- MongoDB is NOT used as an authoritative business database.
- `backend/app/sheets.py` enforces strictly read-only OAuth scope (`https://www.googleapis.com/auth/spreadsheets.readonly`).
- Direct Google Sheets mutation methods (`append_record`, `update_record`, `delete_record`) remain blocked fail-closed under Blueprint v2.1 Single-Write-Owner.
- Zero live Google Sheets reads/writes, zero Apps Script executions, and zero business data restorations occurred during Phase 1.8.

---

## 2. Programmatic Schema Registry Snapshot (`app.schema_registry.get_schema_coverage_summary()`)

| Registry Metric | Actual Verified Value |
|---|---:|
| `cleaned_tab_baseline` | **255** |
| `declared_database_groups` | **15** |
| `group_tab_references_total` | **91** |
| `core_required_tabs_count` | **67** |
| `extended_v2_contracts_count` | **24** |
| `unique_catalogued_workbook_tabs` | **91** |
| `unmapped_workbook_tabs_remaining` | **164** |
| `pending_owner_mapping_tabs_count` | **24** |
| `conflicting_core_schema_tabs_count` | **12** |
| `approved_core_schema_reconciliations_count` | **0** |
| `write_blocked_schema_tabs_count` | **36** |
| `duplicate_group_placements` | `{}` (0 duplicates) |
| `coverage_complete` | **`False`** |
| `coverage_status` | **`INCOMPLETE_PENDING_AUTHORITATIVE_WORKBOOK_EXPORT`** |

---

## 3. Open External Blockers Preventing `🟢 PHASE 1 COMPLETE`

### Blocker `DB-003` — Missing Authoritative 255-Tab Workbook Export & DBV5 Field Dictionary
- **Status:** **OPEN (External Artifact Required from Owner)**
- **Current Gap:** `91` of `255` cleaned baseline workbook tabs are catalogued (`67` core + `24` extended v2 contracts); **`164` workbook tabs remain unmapped**.
- **Protection Verified:** No missing tables or schemas were fabricated. All unknown/unmapped tables and all `24` pending-owner-mapping tables remain write-blocked fail-closed (`BLOCKED_PENDING_OWNER_SETUP`).
- **Required Owner Artifact to Close:** Authoritative exported workbook tab manifest + DBV5 field dictionary covering all `255` tabs.

### Blocker `DB-007` — Missing Physical Google Sheets Row-1 Headers for 12 Conflicting Core Tables
- **Status:** **OPEN (External Artifact Required from Owner)**
- **Conflicting Core Tables (`12`, all write-blocked fail-closed, `0` unlocked):**
  1. `CustomRoles`
  2. `Customers`
  3. `Expenses`
  4. `PackagingBatches`
  5. `ProductionBatches`
  6. `Products`
  7. `RawMaterials`
  8. `SalaryIncentives`
  9. `Sales`
  10. `ShopVisits`
  11. `Suppliers`
  12. `Workers`
- **Protection Verified:** Fabricated headers, unknown columns, and unordered columns are rejected by the strict schema reconciliation validator (`P1.5-005`). Zero conflicting tables have been falsely unlocked or marked `VERIFIED_CORE`.
- **Required Owner Artifact to Close:** Verified physical Row-1 column header dump exported from the authoritative Google Sheet for all `12` tables, followed by formal canonical schema reconciliation approval.

### Blocker `DB-008` — Missing Apps Script `WebAppBridge.gs` / `doPost` Writer Source
- **Status:** **OPEN (External Source Artifact Required from Owner)**
- **Current Gap:** The remote Google Apps Script writer (`WebAppBridge.gs` / `doPost`) is NOT present in this repository and has never been independently audited.
- **Honest Security Boundaries Maintained:**
  - This audit does **NOT** claim server-side atomic multi-tab commits inside Apps Script.
  - This audit does **NOT** claim distributed/multi-worker unique-ID enforcement inside Apps Script (only in-process serialization + fresh preflight verification inside the Python backend are verified).
  - This audit does **NOT** claim remote Apps Script HMAC/secret/role authorization is secure without inspecting the actual `.gs` source code.
- **Required Owner Artifact to Close:** Exact production `WebAppBridge.gs` (and any supporting `.gs` files + `appsscript.json` manifest) for independent security, locking (`LockService`), idempotency, and schema-write audit.

---

## 4. Non-Blocking Runtime Note
- **Real FastAPI/Uvicorn Virtualenv Check:** The local sandbox executed all 568 passing tests using the stdlib HTTP/FastAPI/HMAC-JWT test shims in `backend/tests/__init__.py` (with real HMAC-SHA256 signature and `exp` validation), leaving 1 pre-existing `@unittest.skipUnless` subprocess bind test (`test_uvicorn_binds_and_serves_health_within_3s_when_sheets_hangs_over_5s`) skipped until executed in a virtualenv containing `fastapi`, `uvicorn`, and `PyJWT`.
