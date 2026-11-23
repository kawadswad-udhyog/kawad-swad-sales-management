# KAWAD SWAD ERP — MISSION 1.9: INDEPENDENT PHASE 1.8 VERIFICATION AUDIT REPORT

**Audit Baseline**: Repository **ZIP61** (`/app/applet`)  
**Audit Authority**: Strictly Read-Only Independent Verification (AUDIT ONLY — zero source, test, or config files modified)  
**Audit Date**: 2026-11-22  
**Overall Phase 1.8 Claim Verdict**: **FAIL (`RED`)** — Phase 2 **NOT APPROVED**

---

## 1. Executive Summary

This report presents an independent, source-level audit of repository **ZIP61** against the Phase 1.8 code-stability and security stabilization claims (14 production repairs `P1.8-001`–`P1.8-014` plus 2 test claims `P1.8-015`–`P1.8-016`) and the full ERP mutation, transaction-safety, security, frontend, and test architecture.

Every claim was verified directly against ZIP61 source code and isolated local test execution—prior audit summaries were treated strictly as unverified hypotheses.

### High-Level Verdict Summary
- **Phase 1.8 Production Repairs (14 items)**: **10 PASS**, **4 PARTIAL** (`P1.8-005`, `P1.8-007`, `P1.8-009`, `P1.8-014`), **0 FAIL**.
- **Phase 1.8 Test Claims (2 items)**: **1 PASS** (`P1.8-015`), **1 PARTIAL** (`P1.8-016` — 671/672 pass with 1 skip, but zero real `fastapi`/`pydantic`/`jwt`/`gspread` packages are installed, so 100% of backend tests run on pure-stdlib mock shims and an in-memory Apps Script simulator).
- **New Defects Identified**: **15 independent findings** (**1 CRITICAL**, **7 HIGH**, **6 MEDIUM**, **1 LOW**).
- **External Production Gates (`UNVERIFIED`)**:
  - **`DB-008` (UNVERIFIED)**: Live Google Apps Script Single-Write-Owner Web App (`Code.gs`) source, HMAC verification, server-side `LockService`/duplicate-ID enforcement, and atomic multi-tab commits are external to ZIP61 and cannot be verified in this repository.
  - **`DB-003` (UNVERIFIED)**: Live Google Sheets workbook tabs, Row-1 schema headers, and historical data reconciliation cannot be verified in isolated read-only audit mode.
  - **`DB-007` (UNVERIFIED)**: Live Render deployment topology (single-worker guarantee, persistent disk mount for SQLite coordinator, production environment variables, and CORS allowlist) is external and unverified.

---

## 2. Workstream A — Independent Verification of All 14 Phase 1.8 Repairs

Full tabular matrix is recorded in `MISSION_1_9_REPAIR_VERIFICATION_MATRIX.csv`. Summary of source verification:

| Repair ID | Reported Fix | Verdict | Source Location & Evidence |
|---|---|---|---|
| **P1.8-001** | Fail-closed duplicate-ID preflight (`fresh=True`, Row-1 header verification, in-process concurrency guard) | **PASS** | `backend/app/sheets.py:1393-1435` (`get_verified_tab_headers`), `backend/app/apps_script_bridge.py:371-886` (`_check_id_exists_authoritative`, `_INFLIGHT_ID_LOCK`, `_INFLIGHT_IDS`). Returns HTTP 503 on read outage, malformed payload, or missing/wrong Row-1 headers with zero bridge HTTP calls; releases in-flight reservation in `finally`. Verified with 8/8 passing tests in `test_phase1_8_duplicate_id_security.py`. *(Note: cross-worker / Apps Script enforcement remains external `UNVERIFIED` [`DB-008`]; `SALES_TESTING=1` guard flaw tracked separately as `M19-001`.)* |
| **P1.8-002** | `reverse_journal_voucher` returns complete journal response contract | **PASS** | `backend/app/accounting/journal_engine.py:222-293`. Returns `journal_id`, `reference_type`, `reference_id`, `total_debit`, `total_credit`, `"status": "POSTED"`, and `"bridge_status": bridge_res.get("status")`. |
| **P1.8-003** | `post_journal_voucher` preserves domain `"status": "POSTED"` after `**bridge_res` | **PASS** | `backend/app/accounting/journal_engine.py:66-180` (return dict at lines 163-179 places `"status": "POSTED"` after `**bridge_res` and exposes `"bridge_status"`). |
| **P1.8-004** | `create_customer` defaults blank/whitespace `city` to `"Bhilwara"` | **PASS** | `backend/app/routers/customers.py:62` (`(req.city or "Bhilwara").strip() or "Bhilwara"`). *(Minor note: `update_customer` at line 124 strips `req.city` without defaulting blank back to `"Bhilwara"`.)* |
| **P1.8-005** | Unique CAS nonces for credit-approval reserve/release | **PARTIAL** | `backend/app/accounting/customer_ledger.py:987, 1014, 1163`. Appending `-{uuid.uuid4().hex[:8]}` prevents release-then-re-reserve nonce collision, **but** generating a fresh random UUID on every call breaks deterministic same-nonce retry after timeout/`UNKNOWN` (`M19-010`). (`consume_credit_approval` at line 1094 remains deterministic `CONSUME-{clean_id}-{clean_sale_id}`.) |
| **P1.8-006** | `create_packaging` defers zero-cost journal vouchers cleanly | **PASS** | `backend/app/routers/production.py:3965-3974`. Checks `if total_fin_cost > Decimal("0"):` before calling `post_packaging_batch_journal`; otherwise logs warning and sets `saved["accounting_status"] = "DEFERRED_PENDING_COST_VALUATION"`. |
| **P1.8-007** | Domain `status` preserved after `**res` in stock & quality routers | **PARTIAL** | Fixed in `backend/app/routers/stock.py:290, 511` and `backend/app/routers/quality.py:564`. **Bypassed/missed in 3 other `quality.py` endpoints**: `create_quality_check` (`quality.py:177, 198`), `create_customer_return` (`quality.py:427, 464`), and `create_complaint_or_recall` (`quality.py:509, 531`), all of which still place `**res` last and overwrite `"COMPLETED"`, `"APPROVED"`, and `"OPEN"` with bridge `"CONFIRMED"` (`M19-009`). |
| **P1.8-008** | `calculate_payroll_run` returns Apps-Script-allocated `item_id`s | **PASS** | `backend/app/routers/workforce.py:1384-1403`. Re-reads `PayrollItems` with `fresh=True` filtered by `payroll_run_id` (falling back to `bridge_res.get("data", {}).get("items")` or `items_to_save`). |
| **P1.8-009** | `record_workforce_payment` propagates `accounting_journal_ref` | **PARTIAL** | `backend/app/routers/workforce.py:1669-1683`. Sets `saved_payment = {**saved_payment, "accounting_journal_ref": journal_ref}` ONLY on the returned HTTP response dict; **never persists `accounting_journal_ref` back to `WorkforcePayments`**, so subsequent `GET` reads return an empty reference. Also executes journal posting as an unquarantined second bridge call (`M19-004`). |
| **P1.8-010** | `record_workforce_payment` populates `receipt_id` & `receipt_number` from fresh `SalaryReceipts` readback | **PASS** | `backend/app/routers/workforce.py:1687-1715`. Freshly queries `SalaryReceipts`, matches by `payment_id`, and returns authoritative `receipt_id` and `receipt_number`. |
| **P1.8-011** | `review_stock_discrepancy` embeds atomic `audit_event` and catches 503 audit failure | **PASS** | `backend/app/routers/stock.py:435-511`. Pre-checks `AuditLog` readability, embeds `audit_event` in `review_payload`, and handles HTTP 503 with `"audit"` message. *(Actual atomic commit inside Apps Script remains `UNVERIFIED` [`DB-008`].)* |
| **P1.8-012** | `record_supplier_payment` recovers missing `SUPPLIER_PAYMENT` journal on `PAID` idempotent replay | **PASS** | `backend/app/routers/purchasing.py:864-893`. Queries `JournalHeaders` (`fresh=True`) for active `SUPPLIER_PAYMENT` journal matching `existing_pid` and posts if missing before returning replay. |
| **P1.8-013** | `record_supplier_payment` advance recovery via `APPLY_SUPPLIER_ADVANCE` with `[spay:{id}]` guard | **PASS** | `backend/app/routers/purchasing.py:929-1014`. Reuses `existing_pid`, checks `[spay:{id}]` marker against `SupplierBills` to prevent double deduction, and uses deterministic recovery nonce `f"{clean_idemp_key}::APPLY_ADVANCE::{existing_pid}"`. |
| **P1.8-014** | `receive_raw_material` `IncompleteTransactions` `line_key` check & post-write fresh readback checks in `production.py` | **PARTIAL** | `backend/app/routers/production.py:987-1008, 1118-1126, 1577-1585`. Enforces `INV:{invoice}:L:{line}` conflict detection and post-write HTTP 503 readback checks. **Gaps**: (1) on `receive_raw_material` replay (`production.py:1018-1056`), returns `ALREADY_RECORDED` without checking/recovering a missing `RAW_MATERIAL_RECEIPT` journal if `post_receipt_journal` failed at line 1151 (`M19-004`); (2) `record_dal_milling_batch` readback (`production.py:1577-1585`) checks only `output_txn_id` (leg 2) and never verifies `input_txn_id` (leg 1) or the `MillingBatches` parent row. |

---

## 3. Workstream B — Single Write Owner Architecture Audit

### Verified Strengths
1. **Read-Only Backend OAuth Scope**: `backend/app/sheets.py:33` locks `SHEETS_OAUTH_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]`.
2. **Direct-Write Block Enforcement**: `backend/app/sheets.py:1501-1511` (`_assert_direct_mutation_allowed`) raises `RuntimeError` on `append_record`, `update_record`, `delete_record`, `generate_id`, `allocate_bill_number`, and `_ensure_headers` whenever `self.is_connected and self.spreadsheet` OR `not self.allow_in_memory_fallback`.
3. **Governed Apps Script Bridge**: All production operational mutations in `backend/app/routers/*.py` delegate through `apps_script_bridge.execute_governed_write` / `delegate_governed_write` with HMAC-SHA256 signing, action allowlisting (`GOVERNED_ACTION_REGISTRY`), and core-schema reconciliation gates.
4. **Legacy Script Hardening**: `backend/scripts/bootstrap_owner.py`, `reset_password.py`, `update_sheets_recipe_master.py`, `migrate_workforce_stage3.py`, and `audit_users.py` all contain production guards blocking direct live writes.

### Confirmed Defects & Unverified External Boundaries
- **[CRITICAL — M19-001] `SALES_TESTING=1` Overrides `SALES_ENV=production`**: Across `main.py:49-71`, `config.py:60-66`, `sheets.py:384`, and `transaction_safety.py:917, 930`, setting `SALES_TESTING=1` silently disables `assert_runtime_config()`, skips Google Sheets initialization, signs JWTs with the hardcoded public string `"test-only-secret-do-not-use-for-deployment-32"`, sets `allow_in_memory_fallback = True` (re-enabling direct in-memory `append_record`/`update_record`/`delete_record`), and bypasses production SQLite durability & multi-instance guards—even when `SALES_ENV=production`.
- **[LOW — M19-015] Negative Production Check in `workforce_migration.py` & Import-Time Env Mutation in `run_staging_walkthrough.py`**: `backend/app/workforce_migration.py:109-122` only blocks offline writes when `SALES_ENV == "production"` (while `config.py:17` defaults `SALES_ENV` to `"development"`). Separately, `backend/scripts/run_staging_walkthrough.py:20` unconditionally executes `os.environ["SALES_TESTING"] = "1"` at module import time.
- **[UNVERIFIED — DB-008] External Apps Script Writer**: The deployed Apps Script Web App (`Code.gs`) is not in ZIP61; its actual atomicity, HMAC verification, server-side `LockService`, and ID allocation cannot be certified from this repository.

---

## 4. Workstream C — Transaction Identity & Idempotency Audit

### Verified Strengths
- **Fail-Closed Coordinator & CAS Lifecycle**: `backend/app/accounting/transaction_coordinator.py` implements an explicit SQLite-backed state machine (`INITIATED -> VALIDATING -> PENDING -> EXECUTING -> COMMITTED / FAILED / UNKNOWN / RECOVERY_REQUIRED -> RECONCILED`), mandatory worker correlation-ID lease ownership checks, lease expiration enforcement, and fail-closed SQLite corruption handling (`test_tx_final_05` & `test_tx_final_06` pass).
- **Authoritative Pre-Write Nonce Lookup**: `_find_existing_sheets_allocation_for_nonce` (`apps_script_bridge.py:2174-2206`) raises fail-closed on storage outages or malformed data (`test_tx_final_02` passes).
- **Duplicate-ID & Cross-Table Uniqueness**: `_check_id_exists_authoritative` verifies Row-1 headers and checks cross-table uniqueness (`Payments`/`SalaryReceipts`, child `JournalLines`, etc.) fail-closed with `fresh=True`.

### Confirmed Defects
- **[HIGH — M19-003] `BillNumbers` Row Not Filtered in 3 `IdAllocations` Lookups**: While `apps_script_bridge.py:1255` filters `str(r.get("tab_name", "")).strip() != "BillNumbers"`, three other lookups omit this filter: `recover_transaction` (`apps_script_bridge.py:1751-1754`), `_find_existing_sheets_allocation_for_nonce` (`2191-2192`), and `check_transaction_status` (`3576-3579`, plus `3664-3667` using `alloc_match["allocated_id"]` even when `alloc_tab == "BillNumbers"`). If `BillNumbers` precedes `Sales` for a `CREATE_SALE` nonce in `IdAllocations`, recovery/status checks extract `KS-BILL-...` instead of `SALE-...` and falsely quarantine a committed sale as `ALLOCATION_ID_MISMATCH` or `ORPHAN_ID_ALLOCATION_DETECTED`.
- **[HIGH — M19-004] Split-Write Accounting Atomicity & Missing Secondary Quarantine**: Only `CREATE_SALE` (`routers/sales.py:570-619`) and `RECORD_SALE_PAYMENT` are covered by `_verify_required_accounting_journal` (`apps_script_bridge.py:1023-1035`) and secondary quarantine. Five other financial flows execute a second unquarantined `POST_JOURNAL_VOUCHER` bridge call after the primary write commits: `receive_raw_material` (`production.py:1151`), `record_dal_milling_batch` (`production.py:1603`), `create_packaging` (`production.py:3966`), `record_workforce_payment` (`workforce.py:1671`), `record_supplier_payment` (`purchasing.py:1025`), and `create_customer_return` (`quality.py:461`). Failure in the journal call leaves operational/subledger rows committed without GL postings and without `RECOVERY_REQUIRED` quarantine; in `receive_raw_material`, retrying hits `if existing_line:` (`production.py:1018-1056`) and returns `ALREADY_RECORDED` without posting the missing journal.
- **[MEDIUM — M19-010] Random Nonce Suffixes on Credit-Approval CAS**: `accounting/customer_ledger.py:987, 1014, 1163` appends random `uuid4().hex[:8]` on every call to `reserve_credit_approval` / `release_credit_approval`, breaking same-nonce idempotency on timeout/`UNKNOWN` retries.
- **Multi-Worker Limits**: `AppsScriptBridge._INFLIGHT_IDS` (`apps_script_bridge.py:371`) and `_APPROVAL_EXECUTION_LOCK` (`routers/approvals.py:23`) are process-local locks. Production relies on single-worker Render deployment (`DB-007`, `UNVERIFIED`) plus coordinator SQLite durability checks (which `M19-001` bypasses if `SALES_TESTING=1`).

---

## 5. Workstream D — UNKNOWN Outcome Safety Audit

### Verified Strengths
- **Response Mismatch & Timeout Classification**: `apps_script_bridge.py` classifies timeouts, network disconnects, malformed payloads, and action/table mismatches as `UNKNOWN` (HTTP 504), refusing to mark `FAILED` or auto-retry (`test_tx_final_07` passes).
- **Readback Completeness Verification**: `check_transaction_status` and `_verify_readback` refuse to confirm from `IdAllocations` or `AuditLog` alone without verifying the primary row, child rows, and balanced `JournalLines` (`test_tx_final_08` passes).
- **Concurrent Recovery CAS Serialization**: Concurrent retries on `UNKNOWN` serialize safely via SQLite CAS lease acquisition (`test_tx_final_06` passes).

### Confirmed Defects
- **[HIGH — M19-003]** False `RECOVERY_REQUIRED` on `CREATE_SALE` when `BillNumbers` appears first in `IdAllocations` (see Section 4).
- **[HIGH — M19-005]** Unscoped `GET /api/v2/transactions/status/{nonce}` exposes other users' transaction metadata (see Section 6).
- **[MEDIUM — M19-011]** Frontend `requireVerifiedRetry` is opt-in and never enabled by production callers (see Section 7).
- **[MEDIUM — M19-012]** Employee Portal views lack `UnknownOutcomeBanner` and `useUnknownOutcomeGuard` (see Section 7).

---

## 6. Workstream E — Backend Security & Authorization Audit

An AST scan across all 20 router modules (`backend/app/routers/*.py`) and `backend/app/main.py` audited every route decorator for authentication, RBAC, `require_sheets_connection`, confidentiality filtering, and session revocation.

### Verified Strengths
- **No Unintended Unauthenticated Routes**: Only `/api/auth/login` (`/auth/login`), `/health` (`/api/health`), and `/` are unauthenticated.
- **Fail-Closed Active/Role Evaluation**: `auth.py` validates authoritative roles against `AuthUsers` (`fresh=True`), rejects duplicate `user_id`/`username` rows fail-closed (403/409), and denies inactive or legacy-password accounts.
- **Confidential Redaction on Core Admin Endpoints**: `list_users` (`users.py:110-124`), `list_employee_advances` (`v2_erp.py:921`), `list_v2_audit_logs` (`v2_erp.py:1520-1538`), and `list_approval_requests` (`approvals.py:119-132`) redact confidential PII/payroll fields for non-Owner roles.

### Confirmed Security Defects
1. **[CRITICAL — M19-001] `SALES_TESTING=1` Production Security Bypass**: Disables `assert_runtime_config()`, allows hardcoded JWT secret `"test-only-secret-do-not-use-for-deployment-32"` (`config.py:60-66`), disables Sheets connection (`main.py:49-71`), and enables volatile in-memory storage fallback (`sheets.py:384`) even when `SALES_ENV=production`.
2. **[HIGH — M19-002] `FACTORY_WORKER` Role Privilege Escalation**: `backend/app/permissions.py:82` maps `"FACTORY_WORKER": "PRODUCTION"` in `CANONICAL_ROLE_V2_MAP`, while `DEFAULT_ROLE_PERMISSIONS["FACTORY_WORKER"]` (`permissions.py:395`) restricts it to `{"production": ["view"]}`. Because `has_permission()` (`permissions.py:492-500`) evaluates `v2_role` FIRST in `(v2_role, c_role, raw_role)`, any `FACTORY_WORKER` receives full `PRODUCTION` write permissions (`create`, `record_consumption`, `record_output`, `record_loss`, `record_gig_work`, `quality:submit_qc`).
3. **[HIGH — M19-005] Cross-User IDOR on `GET /api/v2/transactions/status/{nonce}`**: `backend/app/routers/v2_erp.py:1326-1353` passes only `actor_is_owner=is_owner(current_user)` to `check_transaction_status`, performing no ownership or module-RBAC check against `local_tx["actor_user_id"]` or `target_tab`. Any authenticated low-privilege user can query any nonce and read `allocated_id`, `tab_name`, `transaction_id`, `correlation_id`, and `recorded_at` for all non-confidential tabs (`Sales`, `SupplierPayments`, `JournalHeaders`, `Customers`, etc.).
4. **[HIGH — M19-006] `must_change_password` Not Enforced Server-Side**: `backend/app/auth.py:490` attaches `must_change_password` to the authenticated user payload, and `routers/auth.py:62-78, 202-209` returns it to the frontend, but **zero** backend endpoints or `get_current_user` checks block API calls when `must_change_password=True`. Any user holding a temporary or reset-required credential can execute arbitrary authorized ERP reads/writes via direct API calls without ever changing their password.
5. **[HIGH — M19-007] Approval-Executed Password Reset / Deactivation / Role Change Does Not Revoke Sessions**: In `backend/app/routers/approvals.py:158-174, 232-250`, `_build_approval_execution_payload` omits `sessions_revoked_at` for `RESET_PASSWORD`, `DEACTIVATE_USER`, and role-changing `UPDATE_USER`, and `decide_approval_request` never updates `_USER_REVOKED_AT`. Existing JWTs for affected users remain valid after Owner approval.
6. **[MEDIUM — M19-013] Fail-Open Logout Revocation & Process-Local Username-Only Login Lockout**:
   - `backend/app/routers/auth.py:181-197` calls `revoke_token(..., raise_on_failure=False)` and returns HTTP 200 `{ok: True, persisted: False}` when persistent `RevokedTokens` bridge write fails, allowing revoked tokens to survive process restart or multi-worker routing.
   - `backend/app/routers/auth.py:31-33, 88-97` stores `_LOGIN_ATTEMPTS` in an unbounded process-local dict keyed only by `username` (no IP rate limit, lost on restart, memory-growth risk on random-username spraying).

---

## 7. Workstream F — Frontend Mutation Safety Audit

### Verified Strengths
- **Zero Raw `fetch()` Bypasses**: Exhaustive grep across `src/` confirmed every HTTP request flows through `apiFetch` or `apiRequest` in `src/services/api.ts` (zero direct `fetch(` calls in views or components).
- **Canonical Bound Transaction Fingerprinting**: `src/utils/unknownOutcomeLock.ts` implements pure synchronous FIPS 180-4 SHA-256 over canonicalized payloads plus method, normalized endpoint (including sorted query parameters), and transaction scope, failing closed (`PayloadFingerprintError`) on circular refs, `NaN`/`Infinity`, invalid `Date`, or malformed JSON.
- **Verified SessionStorage Persistence & Safety-Degraded Mode**: `persistUnknownOutcome` performs immediate read-back verification, classifies `STORAGE_UNAVAILABLE`/`ACCESS_DENIED`/`QUOTA_EXCEEDED`/`CORRUPTED_DATA`/`READBACK_MISMATCH`, and keeps an authoritative in-memory lock (`reloadSafe: false`) on storage failure rather than silently dropping locks.
- **Authoritative Status Response Validation**: `validateAuthoritativeStatusResponse` (`unknownOutcomeLock.ts:1927-2065`) validates response object shape, nonce/idempotency_key match, `transaction_id` match, status enum, and boolean retry flag fail-closed.
- **No Auto-Retry on Mutations**: `src/services/api.ts:1322` strictly restricts Vite-proxy fallback retries to `isReadOnlyMethod` (`GET`/`HEAD`/`OPTIONS`).
- **Primary Admin Views Covered**: All 17 mutating admin/operations views under `src/views/*.tsx` integrate `useUnknownOutcomeGuard` and `UnknownOutcomeBanner`.

### Confirmed Frontend Defects
1. **[MEDIUM — M19-011] `requireVerifiedRetry` Is Opt-In and Passed by Zero Production Callers**: `src/utils/unknownOutcomeLock.ts:2489` only enforces authoritative `NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE` verification before allowing a same-nonce retry when `params.requireVerifiedRetry` is truthy. Both `apiFetch` (`src/services/api.ts:411`) and `apiRequest` (`src/services/api.ts:1172`) pass `options.requireVerifiedRetry` (defaulting to `undefined`), and grep across all of `src/` confirmed **0 callers pass `requireVerifiedRetry: true`**. Thus, transport-level protection blocks payload/endpoint/method mismatches and fresh-nonce bypasses, but does NOT block an unverified same-nonce retry prior to status verification.
2. **[MEDIUM — M19-012] Employee Portal Views Missing `UnknownOutcomeBanner` / `useUnknownOutcomeGuard` + Unconditional Nonce Reset**: All 5 mutating Employee Portal views (`src/employee/views/EmployeeOverviewView.tsx`, `MyAttendanceView.tsx`, `MyProfileView.tsx`, `MyProjectsView.tsx`, `MyTasksView.tsx`) execute mutations via `apiFetch('/api/workforce/...')` without `useUnknownOutcomeGuard` or `UnknownOutcomeBanner`. On any timeout/504, `apiFetch` persists a lock on scope `workforce_view`, trapping the employee with no UI status-check or unlock path; additionally, `MyProjectsView.tsx:217, 255, 310` and `MyTasksView.tsx:232, 263, 321` unconditionally reset `setSubmitNonce('')` when modals open/close, guaranteeing subsequent submissions hit `UNKNOWN_OUTCOME_LOCK_ACTIVE` (`409`).
3. **[MEDIUM — M19-014] Missing `ENDPOINT_SCOPE_RULES` Entries for `/api/v2/packaging` and `/api/v2/transactions`**: `src/utils/unknownOutcomeLock.ts:517-549` omits prefixes `/api/v2/packaging` and `/api/v2/transactions` (e.g., `POST /api/v2/packaging/batches` and `POST /api/v2/transactions/{nonce}/reconcile`). Any mutation to those endpoints without an explicit `lockScope` fails closed with `AMBIGUOUS_TRANSACTION_SCOPE`.

---

## 8. Workstream G — Test Integrity Audit Summary

Full execution details are in `MISSION_1_9_TEST_VERIFICATION.md`.

### Executed Isolated Checks (Personally Run Against ZIP61)
- `backend/tests/test_phase1_8_duplicate_id_security.py`: **8/8 PASS** (0.067s)
- `backend/tests/test_tx_final_*.py`: **17/17 PASS** (0.608s)
- Full backend `unittest discover -s backend/tests -t backend` (63 files): **671 PASS, 1 SKIP, 0 FAIL** (45.454s)
- `npx tsc --noEmit`: **PASS (0 errors)**
- All 5 frontend TypeScript suites (`scripts/test_*.ts`): **85/85 PASS** (17 + 5 + 6 + 18 + 39)

### Critical Test-Integrity Finding (`M19-008` — HIGH)
- **Zero Production Runtime Dependencies Installed in Python Environment**: `fastapi`, `pydantic`, `jwt`, `gspread`, `google.oauth2`, and `pytest` are **all absent** from Python 3.11.2.
- Consequently, **100% of the 671 passing backend tests** executed via pure-stdlib mock shims in `backend/tests/__init__.py:17-169` and `LocalAppsScriptSimulator` in `backend/tests/v2_test_harness.py:150-493`:
  - `MockBaseModel` (`__init__.py:158-163`) performs **zero** Pydantic schema, type, range (`gt=0`, `min_length`), or `Literal` validation.
  - `MockFastAPIModule` (`__init__.py:18-92`) turns route decorators into identity pass-throughs, bypassing FastAPI `Depends(require_sheets_connection)` and `Depends(get_current_user)` execution chains on direct function invocations.
  - `V2RouterProxy` (`v2_test_harness.py:72-133`) silently injects synthetic `X-KS-Idempotency-Key` headers when tests omit them.
  - `LocalAppsScriptSimulator.start()` (`v2_test_harness.py:172-180`) auto-approves all 12 core conflicting schema tables and simulates multi-tab atomicity in Python memory (`db.memory_store`), masking any divergence from the real external Apps Script (`Code.gs`, `DB-008`).
  - The sole real ASGI/Uvicorn startup test (`test_startup_port_bind_and_resilience.py:735-740`) was **SKIPPED** due to missing `uvicorn`/`fastapi`.
- **Conclusion**: Passing counts (671/672) demonstrate internal Python business-logic consistency under mocks, **not** end-to-end production FastAPI/Pydantic/JWT/Google-Sheets/Apps-Script safety.

---

## 9. Workstream H — Additional Consistency & Regression Findings

Beyond the defects above, independent inspection identified:
- **Hardcoded 5% GST in Customer Returns Bypassing Pending CA Policy (`M19-014`)**: `backend/app/routers/quality.py:456` computes `"tax_amount": float(total_refund * Decimal("0.05"))` unconditionally, without checking `assert_ca_policy_approved("hsn_gst_tax_rates")` (unlike `v2_erp.py:775`).
- **Cached Write-Path Lookup & Float Arithmetic in Daily Closing (`M19-014`)**: `backend/app/routers/closing.py:210` (`review_daily_closing`) reads `db.get_records("DailyClosing")` without `fresh=True` before issuing a governed update, and `closing.py:105, 141-142` computes cash totals and cash variance with IEEE-754 `float` instead of `Decimal`.
- **Incomplete Readback in Milling (`P1.8-014` / `M19-004`)**: `backend/app/routers/production.py:1577-1585` verifies only `output_txn_id` in `RawMaterialLedger` and never verifies `input_txn_id` or the `MillingBatches` header row.

---

## 10. Unverified External Production Gates (Explicit Classification)

| Gate ID | Scope | Status | Reason |
|---|---|---|---|
| **DB-008** | Live Google Apps Script Web App (`Code.gs`) single write owner, HMAC verification, `LockService`, atomic multi-tab commits, `IdAllocations` ordering | **UNVERIFIED** | External Apps Script deployment source is not present in ZIP61 and live execution is prohibited in audit-only mode. |
| **DB-003** | Live Google Sheets workbook tabs, Row-1 headers, core schema reconciliation, historical data integrity | **UNVERIFIED** | Isolated read-only audit with no live Google Sheets credentials or connectivity. |
| **DB-007** | Live Render deployment: single Uvicorn worker, persistent disk for `TRANSACTION_DB_PATH`, `SALES_ENV=production` with `SALES_TESTING` unset, `SALES_CORS_ORIGINS` | **UNVERIFIED** | External Render infrastructure and environment configuration are not inspectable from ZIP61. |
| **ASGI-RT** | Real FastAPI + Pydantic + PyJWT + Uvicorn + gspread dependency execution | **UNVERIFIED** | None of these packages are installed in the local audit Python environment (`test_uvicorn_binds_and_serves_health_within_3s_when_sheets_hangs_over_5s` skipped). |
