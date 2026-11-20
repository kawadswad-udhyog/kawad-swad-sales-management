# Kawad Swad ERP — Phase 1.8 Security Re-Audit & Duplicate-ID Hardening Report

## 1. Re-Audit Scope & Evidence Basis
All nine Phase 1.5 security defects (`P1.5-001` through `P1.5-009`), the critical Phase E duplicate-ID lookup security hardening (`P1.8-001`), Single-Write-Owner enforcement, OAuth scopes, and static code hygiene were re-verified directly against current source code and automated adversarial tests.

- **Security Suite Result:** `72/72 PASS` (`1.292s`) across:
  - `tests.test_phase1_6_targeted_repairs` (32 tests)
  - `tests.test_phase1_8_duplicate_id_security` (8 adversarial duplicate-ID tests)
  - `tests.test_phase4_2a_security_guards` (12 tests)
  - `tests.test_phase1_database_schema_guards` (8 tests)
  - `tests.test_health_diagnostics_security_and_quota` (8 tests)
  - `tests.test_master_plan_phase1_integrity` (4 tests)
- **Static Security Hygiene Scan (`backend/app`, `src`):**
  - Hardcoded private keys / API keys: **0 hits**
  - Disabled-guard flags (`SKIP_SCHEMA`, `DISABLE_SINGLE_WRITE`, `BYPASS_AUTH`): **0 hits**
  - Debug breakpoints (`pdb.set_trace`, `breakpoint()`): **0 hits**
  - OAuth scope in `backend/app/sheets.py`: strictly `https://www.googleapis.com/auth/spreadsheets.readonly`

---

## 2. Phase E: Duplicate-ID Lookup Security Re-Audit (`P1.8-001` — CRITICAL)

| Control | Implementation Verified | Adversarial Test Coverage (`test_phase1_8_duplicate_id_security.py`) | Result |
|---|---|---|---|
| **E1. Mandatory Fresh Reads** | `_check_id_exists_authoritative()` calls `db.get_records(tab, fresh=True)` unconditionally; stale cached empty lists cannot bypass duplicate detection. | `test_stale_cache_cannot_hide_existing_duplicate_id_fresh_true_enforced` | **PASS** |
| **E2. Fail-Closed on All Outages** | Disconnected storage, timeouts, HTTP 429 quota exhaustion, HTTP 500, HTTP 503, and 401 auth errors all raise fail-closed HTTP 503 (`DUPLICATE_CHECK_UNAVAILABLE`). | `test_storage_outages_timeout_429_500_503_auth_fail_closed_zero_remote_calls`, `test_direct_id_exists_wrapper_raises_instead_of_failing_open` | **PASS** |
| **E2b. Malformed Payloads Fail Closed** | `None`, `dict`, `str`, `int`, or lists containing non-`dict` rows are rejected fail-closed with HTTP 503. | `test_malformed_record_payloads_fail_closed_zero_remote_calls` | **PASS** |
| **E2c. Cross-Table & Child Outages** | Outages reading `SalaryReceipts`, `Payments`, or child tables (`JournalLines`) fail closed with zero remote bridge HTTP calls. | `test_cross_table_and_child_lookup_outages_fail_closed_zero_remote_calls` | **PASS** |
| **E3. Identifier-Column Header Evidence** | `db.get_verified_tab_headers(tab)` verifies authoritative Row-1 headers and requires the expected ID column to exist before accepting empty row lists. Missing/wrong/unreadable headers fail closed. | `test_missing_wrong_or_unverified_headers_fail_closed_even_when_rows_empty` | **PASS** |
| **E4. Legitimate Empty Table** | An empty table passes preflight ONLY when Row-1 headers are authoritatively verified and include the expected ID column(s). | `test_legitimate_empty_table_with_verified_headers_passes_preflight` | **PASS** |
| **E5. Zero Remote Calls on Preflight Failure** | Every failing duplicate-ID preflight asserts `mock_post.call_count == 0` (zero HTTP calls to Apps Script, zero mutations). | Verified across all 8 adversarial test methods | **PASS** |
| **E6. Concurrency Protection & Honest Boundary** | `_INFLIGHT_ID_LOCK` + `_INFLIGHT_IDS` serialize concurrent same-ID writes within the backend process and cleanly release reservations in `finally` blocks even on timeout. **Honest Distributed Limitation:** Because Apps Script `WebAppBridge.gs`/`doPost` source (`DB-008`) is still unavailable, server-side multi-worker / cross-instance atomic uniqueness inside Apps Script CANNOT be independently certified until `DB-008` is supplied and audited. | `test_concurrent_in_process_duplicate_id_writes_allow_only_one_and_release_lock` | **PASS (In-process verified; remote Apps Script remains `DB-008` OPEN)** |

---

## 3. Independent Revalidation of All Nine Phase 1.5 Security Defects

| Finding ID | Security Domain | Re-Verified Behavior | Status |
|---|---|---|---|
| **P1.5-001** | Secondary-Tab Schema Bypass | Primary target tab, mandatory secondary tabs, and child-check tabs are unconditionally validated regardless of caller-supplied `invalidate_tabs` (`None`, `[]`, partial, unknown, duplicate). Conflicting tables block with HTTP 503 and zero remote HTTP POSTs. | **VERIFIED PASS** |
| **P1.5-002** | Salary Incentive ID Allocation & Cross-Table Collisions | `SalaryIncentives` ID allocation no longer deadlocks; prefix enforcement, `SAL` collision handling, `Payments`/`SalaryReceipts` `RCPT` uniqueness, `SalaryIncentives`/`SalaryPayments` cross-table collisions, and same-request duplicate child IDs are all enforced both pre-write and post-write. | **VERIFIED PASS** |
| **P1.5-003** | Token Revocation Fail-Open | `RevokedTokens` read outages, malformed records, and corrupted `sessions_revoked_at` timestamps all fail closed (deny access, zero bridge calls, no secret leakage). | **VERIFIED PASS** |
| **P1.5-004** | Schema Conflict Audit Accuracy | Programmatic inspection of `app.schema_registry.get_schema_coverage_summary()` confirms exact alignment: `255` cleaned baseline tabs, `91` unique catalogued tabs (`67` core + `24` extended v2), `164` unmapped remaining, `12` conflicting core tabs (`0` approved reconciliations), `24` pending owner-mapping tabs, `36` total write-blocked tabs, `coverage_complete=False`. | **VERIFIED PASS** |
| **P1.5-005** | Unsafe Schema Reconciliation Unlock | Fabricated headers, unknown columns, and wrong column ordering cannot unlock conflicting tables; environment-based unlocks pass through the exact same strict validator; `approved_core_schema_reconciliations_count == 0`. | **VERIFIED PASS** |
| **P1.5-006** | Frontend Blocked-State Handling | `npx tsx scripts/test_phase1_6_frontend_contracts.ts` passes `14/14`: `BLOCKED_PENDING_OWNER_SETUP`, `CONFLICT`, `UNKNOWN`, `PENDING OWNER SETUP`, loading state, and HTTP `401`/`403`/`409`/`422`/`503` never render green or false success. | **VERIFIED PASS** |
| **P1.5-007** | Pre-Write ID Validation | IDs, prefixes, blank update keys, duplicate primary/child IDs, same-request duplicates, and cross-table collisions are validated before bridge dispatch and re-verified post-write (re-confirmed live when `SALE-` prefix guard caught `SAL-LEGACY-01` during Phase 1.8 testing). | **VERIFIED PASS** |
| **P1.5-008** | Single-Write-Owner & OAuth Scope | `backend/app/sheets.py` enforces strictly `spreadsheets.readonly` OAuth scope and blocks direct Sheets mutations (`append_record`, `update_record`, `delete_record`) under Single-Write-Owner; legacy scripts fail closed in production. | **VERIFIED PASS** |
| **P1.5-009** | Authentication Hardening | HMAC-SHA256 JWT signature validation, expiration (`exp`), lockout threshold/duration, account deactivation, and fail-closed production Sheets config all pass under both security tests and user-system tests. | **VERIFIED PASS** |

---

## 4. Additional Security/Integrity Guards Verified During Phase 1.8
- **RBAC Preserved:** No `request: Request` parameter, `Depends(...)` guard, or V2.1 RBAC check was removed or weakened (`FACTORY_WORKER` maps to `PRODUCTION` read view while remaining strictly blocked `403` on Owner-only `approve_batch`).
- **AuditLog Fail-Closed (`P1.8-011`):** `review_stock_discrepancy` now fails closed with HTTP `503` if `AuditLog` write fails instead of silently succeeding without an audit trail.
- **Post-Write Fresh Readback (`P1.8-014`):** `receive_raw_material` and `record_dal_milling_batch` now fail closed with HTTP `503` if a newly committed `RawMaterialLedger` row is absent on fresh readback.
- **Note on Verification Independence:** All checks in this report were executed locally by the repair engineer. Independent third-party verification has not yet been performed.
