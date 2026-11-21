# Kawad Swad ERP — Mission 51B-1: Critical Transaction & Write Safety Audit & Evidence Report

**Mission:** Mission 51B-1 — Critical Transaction & Write Safety Repair  
**Date:** 2026-11-21  
**Mission Status:** `CONDITIONAL`  
**Scope:** Transaction lifecycle, idempotency, concurrency, failure classification, read-back verification, evidence-based recovery, structured transaction audit logging, and frontend mutation safety.  
**Non-Negotiable Constitution Preserved:** Google Sheets remains authoritative database; Apps Script (`WebAppBridge.gs`) remains Single Write Owner; zero live writes; zero historical data restoration; zero unrelated mission changes (`51B-2` through `51B-10`).

---

## Deliverable A: Transaction Architecture Before vs After

### A.1 Architecture Before Mission 51B-1

- **Write Path:** FastAPI routers called `apps_script_bridge.delegate_governed_write(...)` which signed HMAC-SHA256 envelopes, enforced action allowlists (`action_registry.py`) and schema reconciliation gates (`schema_registry.py`), posted to Apps Script, and ran `_verify_readback()`.
- **Existing Safety Mechanisms:**
  - Single-Write-Owner policy blocking direct Google Sheets mutations from backend (`sheets.py`).
  - Governed action-to-table registry (`action_registry.py`) and core schema conflict write-blocks (`DB-003`/`DB-007`).
  - In-process `AppsScriptBridge._INFLIGHT_IDS` set + `TransactionCoordinator` SQLite WAL lock table for accounting postings + POSIX `CrossProcessLock` for selected customer/approval paths.
  - `UnknownOutcomeBanner.tsx` for surfacing HTTP 504 `PENDING_UNKNOWN` responses.
- **Critical Weaknesses Identified Before Repair:**
  1. **No Unified Governed Transaction State Machine:** Bridge calls had no durable lifecycle ledger tracking `INITIATED -> VALIDATING -> PENDING -> EXECUTING -> COMMITTED | FAILED | UNKNOWN | RECOVERY_REQUIRED | RECONCILED`. Crashed workers or dropped responses left no local execution lease or reconciliation record.
  2. **Non-Deterministic Payload Hashing & Replay Gaps:** `compute_payload_hash()` did not strip volatile timestamps (`posted_at`, `verified_at`, etc.) or recursively normalize embedded JSON strings, and had no durable nonce-to-hash binding across processes.
  3. **Ambiguous vs Pre-Transmission Failure Conflation:** All transport exceptions fell into generic error paths without distinguishing definite pre-transmission refusals (`ConnectionRefusedError`, DNS `gaierror` -> safe `FAILED` / HTTP 503) from ambiguous post-transmission drops/timeouts/malformed JSON (`UNKNOWN` / HTTP 504).
  4. **No Evidence-Based Recovery Before Retry:** Retrying a timed-out or crashed transaction did not inspect Google Sheets (`IdAllocations`, `AuditLog`, target + child tabs) before re-posting, risking duplicate execution or corruption on partial commits.
  5. **Fail-Open `check_transaction_status()` Bug:** Status lookup returned `UNKNOWN_STORAGE_UNAVAILABLE` only when **both** `IdAllocations` AND `AuditLog` failed (`if alloc_error and audit_error:`). If only one failed while the other was empty, it falsely reported `NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE`. Furthermore, an `IdAllocations` hit was treated as `CONFIRMED_RECORDED` without checking whether the primary row actually existed or was duplicated.
  6. **Partial Side Effects Treated Identically to Transient Read-Back Misses:** Missing child rows (`JournalLines`, `SaleItems`), imbalanced journals, duplicate primary rows, or `SaleItems` vs `Sales` total mismatches were not quarantined as non-retryable `RECOVERY_REQUIRED` (HTTP 409).
  7. **Secondary Accounting Journal Failures Silently Left Partial Commits Unquarantined:** In `sales.py`, if `CREATE_SALE` or `RECORD_SALE_PAYMENT` committed to Sheets and subsequent `post_sale_journal()` / `post_payment_collection_journal()` failed, the primary transaction was never marked `RECOVERY_REQUIRED` or audited.
  8. **Forward-Recovery Nonce Collisions:** `purchasing.py` (`APPLY_SUPPLIER_ADVANCE`) and `production.py` (`RECOVER_MILLING_BATCH`) reused the exact same nonce already bound to `RECORD_SUPPLIER_PAYMENT` / `RECORD_MILLING_BATCH`, causing action-conflict errors under strict idempotency enforcement.
  9. **Unserialized Local ID & Daily Closing Paths:** `sheets.py` `generate_id()` and `allocate_bill_number()` lacked `CrossProcessLock`, and `allocate_bill_number()` did not inspect `IdAllocations`; `closing.py` `submit_daily_closing` lacked `CrossProcessLock` and payload-conflict checks on idempotency replay; `sales.py` `record_sale_payment` only scanned the target sale's payments for idempotency keys, missing cross-sale key reuse and payment-method mismatches.
  10. **Frontend Duplicate Mutation & Optimistic UI Risks:** `src/services/api.ts` auto-retried failed direct-URL requests via Vite proxy even for `POST`/`PUT`/`PATCH`/`DELETE` mutations, lacked synchronous in-flight mutation deduplication for double-clicks, and threw generic errors instead of `ApiOutcomeUnknownError` on dropped business writes. `UnknownOutcomeBanner.tsx` did not strictly gate retry on verified `NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE` or block retry on `RECOVERY_REQUIRED`/`RECONCILED`. `StoreContext.tsx` optimistically mutated product state in `toggleProductActive()` before server confirmation.

### A.2 Architecture After Mission 51B-1

- **Canonical Primitives (`backend/app/transaction_safety.py`):** Unified `TransactionState` (9 states), `FailureCategory` (11 categories), deterministic SHA-256 payload fingerprinting (`compute_deterministic_payload_hash`), secret-redacting audit sanitizer (`sanitize_audit_metadata`), and strict transport exception classifier (`classify_gateway_exception`).
- **Durable Host-Local Coordinator (`backend/app/accounting/transaction_coordinator.py`):** SQLite WAL `governed_transactions` table with `BEGIN IMMEDIATE` atomic CAS operations, execution leases, stale-lease transition to `UNKNOWN`, unresolved transaction listing, and controlled Owner reconciliation (`mark_transaction_reconciled`).
- **Evidence-Based Bridge & Recovery (`backend/app/apps_script_bridge.py`):** Every governed write passes through durable idempotency/conflict/concurrency gating, evidence-based `recover_transaction()` (inspecting Sheets before allowing retry), bounded read-back retry, duplicate-primary and financial-consistency detection (`_PartialSideEffectFailure` -> `RECOVERY_REQUIRED` HTTP 409), fail-closed `check_transaction_status()`, and namespaced structured transaction audit events (`TX_AUDIT:*`).
- **Hardened Routers & ID Allocation:** Serialized `generate_id()` / `allocate_bill_number()` (with `IdAllocations` scan), serialized `submit_daily_closing` with 409 conflict checks, cross-sale payment idempotency scanning + secondary journal failure quarantine in `sales.py`, distinct deterministic recovery nonces in `purchasing.py` and `production.py`, and Owner reconciliation endpoints (`GET /api/v2/transactions/unresolved`, `POST /api/v2/transactions/{nonce}/reconcile`) in `v2_erp.py`.
- **Safe Frontend Mutation Layer:** Read-only proxy retry restriction, synchronous in-flight mutation deduplication (`inflightMutationKeys`), `ApiOutcomeUnknownError` for dropped mutations, fail-closed `UnknownOutcomeBanner` retry gating with 2s cooldown, and removal of optimistic UI updates in `StoreContext.toggleProductActive()`.

### A.3 Remaining Architectural Limitations (Honest Boundary)

- **Host-Local vs Multi-Instance Concurrency:** SQLite WAL (`governed_transactions`) and POSIX `fcntl.flock` (`CrossProcessLock`) guarantee strict serialization across threads and worker processes **on the same host**, NOT across multiple horizontally scaled containers. Multi-instance concurrency safety depends on Apps Script `LockService` (`DB-008`), which is **UNVERIFIED / BLOCKED_PENDING_STAGING**.
- **External Apps Script Atomicity (`DB-008`):** Google Sheets does not provide native multi-tab ACID transactions. Backend read-back verification detects and quarantines partial writes into `RECOVERY_REQUIRED`, preventing blind duplicate retries, but cannot itself guarantee atomic rollback inside external `WebAppBridge.gs`.

---

## Deliverable B: Critical Transaction Repair Register

| ID | Defect | Severity | Repair | Files Changed | Test Evidence | Status |
|----|---------|----------|--------|---------------|---------------|--------|
| TX-001 | No canonical transaction lifecycle state machine or failure taxonomy across governed writes | CRITICAL | Added `TransactionState` (9 states), `FailureCategory` (11 categories), and `governed_transactions` SQLite WAL CAS ledger with execution leases | `backend/app/transaction_safety.py`, `backend/app/accounting/transaction_coordinator.py`, `backend/app/apps_script_bridge.py` | `test_mission51b1_transaction_safety.py` (`test_a2`, `test_b2`, `test_c1`, `test_d3`) | FIXED (Local Verified) |
| TX-002 | Non-deterministic payload fingerprinting across retries / volatile timestamps / embedded JSON strings / integer zero risk | HIGH | Implemented `normalize_scalar_canonical()`, `normalize_payload_for_fingerprint()` (including recursive JSON string normalization & volatile timestamp stripping), and `compute_deterministic_payload_hash()` | `backend/app/transaction_safety.py`, `backend/app/apps_script_bridge.py` | `test_a1`, `test_a2`, `test_a3`, `test_daily_operations_readiness.py::test_08`, `test_accounting_integrity.py::test_9` | FIXED (Local Verified) |
| TX-003 | Ambiguous post-transmission failures (timeout, connection drop, malformed JSON) conflated with definite pre-transmission failures | CRITICAL | Implemented `classify_gateway_exception()` strictly separating pre-transmission `FAILED`/`503` from ambiguous post-transmission `UNKNOWN`/`504` | `backend/app/transaction_safety.py`, `backend/app/apps_script_bridge.py` | `test_c1`, `test_c2`, `test_c3`, `test_c4`, `test_c9`, `test_phase1_8_duplicate_id_security.py` | FIXED (Local Verified) |
| TX-004 | No evidence-based Google Sheets inspection before retrying `UNKNOWN` or stale-lease transactions | CRITICAL | Added `recover_transaction()` inspecting `IdAllocations`, `AuditLog`, primary target tab, and child tabs; auto-confirms complete commits with 0 duplicate POSTs, quarantines partials, permits retry only when Sheets is healthy and empty | `backend/app/apps_script_bridge.py`, `backend/app/accounting/transaction_coordinator.py` | `test_c3`, `test_c4`, `test_c5`, `test_d3` | FIXED (Local Verified) |
| TX-005 | `check_transaction_status()` failed open when only one of `IdAllocations` or `AuditLog` errored, and falsely confirmed orphan `IdAllocations` | CRITICAL | Fixed condition to `if alloc_error or audit_error:`; verified primary row existence & uniqueness -> `RECOVERY_REQUIRED` on orphan allocation or duplicates; preserved confidential redaction | `backend/app/apps_script_bridge.py` | `test_d1`, `test_d2`, `test_d4` | FIXED (Local Verified) |
| TX-006 | Partial side effects (missing child rows, imbalanced journals, duplicate primary rows, `SaleItems` total mismatch) not quarantined as non-retryable `RECOVERY_REQUIRED` | CRITICAL | Separated `_PartialSideEffectFailure` (`RECOVERY_REQUIRED`, HTTP 409, `retryable=False`) from `_ReadBackFailure` (`PENDING_UNKNOWN`, HTTP 504); added duplicate primary detection and `SaleItems` vs `Sales.subtotal`/`bill_total + discount - tax` verification | `backend/app/apps_script_bridge.py` | `test_c5`, `test_c6`, `test_c7`, `test_c8`, `test_buyer_info_optional.py::test_11` | FIXED (Local Verified) |
| TX-007 | Secondary journal failures after committed Sale or Sale Payment left primary transaction unquarantined and unaudited | HIGH | Transition primary sale/payment transaction to `RECOVERY_REQUIRED` with `SECONDARY_JOURNAL_POSTING_FAILED`, log structured audit event, return HTTP 409 with recovery metadata | `backend/app/routers/sales.py` | `test_e1`, full `test_sales*` & `test_phase1_4_1_failure_injection.py` suites | FIXED (Local Verified) |
| TX-008 | `record_sale_payment` idempotency check only scanned target sale's rows, missing cross-sale key reuse and payment-method mismatch | HIGH | Scan all `Payments` rows (`fresh=True`), reject cross-sale key reuse or `payment_method` mismatch with HTTP 409 | `backend/app/routers/sales.py` | `test_e1`, `test_accounting_integrity.py::test_10` | FIXED (Local Verified) |
| TX-009 | `submit_daily_closing` lacked cross-process lock and idempotency payload conflict detection | HIGH | Wrapped in `CrossProcessLock("daily_closing", f"{user_id}_{today_str}")` and validated replay payload fields with HTTP 409 `IDEMPOTENCY_PAYLOAD_CONFLICT` | `backend/app/routers/closing.py` | `test_e1` + closing regression tests | FIXED (Local Verified) |
| TX-010 | Local ID generation (`generate_id`, `allocate_bill_number`) lacked cross-process locking and `IdAllocations` high-water scan | HIGH | Wrapped both in `CrossProcessLock`; added `IdAllocations` scan to `allocate_bill_number()` | `backend/app/sheets.py` | `test_b3` | FIXED (Local Verified) |
| TX-011 | Forward-recovery paths reused primary action nonces (`APPLY_SUPPLIER_ADVANCE` & `RECOVER_MILLING_BATCH`), causing strict idempotency action collisions | HIGH | Scoped deterministic recovery nonces (`{key}::APPLY_ADVANCE::{pid}` and `{key}::RECOVER::{batch_id}`) | `backend/app/routers/purchasing.py`, `backend/app/routers/production.py` | `test_supplier_payment_integrity.py` (31/31), `test_dal_milling_stage2.py` | FIXED (Local Verified) |
| TX-012 | Audit logging lacked secret/PII redaction and could crash or double-count domain audit rows | MEDIUM | Added `sanitize_audit_metadata()`, `db.log_transaction_audit() -> bool`, namespaced `TX_AUDIT:*` lifecycle events, and non-crashing `audit_logged` indicator | `backend/app/transaction_safety.py`, `backend/app/sheets.py`, `backend/app/apps_script_bridge.py` | `test_c10`, `test_daily_operations_readiness.py` (`test_06`, `test_08`, `test_10`, `test_12`) | FIXED (Local Verified) |
| TX-013 | No Owner-controlled reconciliation workflow for unresolved / `RECOVERY_REQUIRED` transactions | HIGH | Added Owner-only `GET /api/v2/transactions/unresolved` and `POST /api/v2/transactions/{nonce}/reconcile` with audit logging | `backend/app/routers/v2_erp.py`, `backend/app/accounting/transaction_coordinator.py` | `test_d4`, `test_e1` | FIXED (Local Verified) |
| TX-014 | Frontend auto-retried mutations across direct URL & Vite proxy, allowed double-click duplicate POSTs, misclassified dropped mutations, and performed optimistic product toggle | CRITICAL | Restricted proxy fallback to `GET`/`HEAD`/`OPTIONS`; added synchronous `inflightMutationKeys` dedup (409); raised `ApiOutcomeUnknownError` on dropped writes; gated `UnknownOutcomeBanner` retry behind verified `NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE` + 2s cooldown; removed optimistic `setProducts` in `toggleProductActive()` | `src/services/api.ts`, `src/components/common/UnknownOutcomeBanner.tsx`, `src/context/StoreContext.tsx` | `scripts/test_mission51b1_frontend_transaction_safety.ts` (5/5), `scripts/test_phase1_6_frontend_contracts.ts` (17/17) | FIXED (Local Verified) |
| TX-015 | External Apps Script `WebAppBridge.gs` `LockService` and cross-tab atomicity unverified in live Google Sheets | CRITICAL | Out-of-environment external dependency (`DB-008`); Apps Script is read-only/external and live writes prohibited in this mission | None (External) | `BLOCKED_PENDING_STAGING` | BLOCKED_PENDING_STAGING |

---

## Deliverable C: Transaction Lifecycle & State Transition Map

### C.1 Canonical End-to-End Execution Pipeline

```text
1. Client Request (Frontend api.ts)
   ├─ Synchronous in-flight mutation dedup (`inflightMutationKeys`) -> duplicate click blocked immediately (409 CONCURRENT_DUPLICATE_REQUEST)
   ├─ Stable `X-KS-Idempotency-Key` nonce attached (preserved across verified manual retries)
   └─ Direct-URL -> Vite proxy auto-retry DISABLED for POST/PUT/PATCH/DELETE

2. Router Validation & Authorization (FastAPI)
   ├─ JWT authentication & server-side RBAC check -> AUTHORIZATION_ERROR (401/403)
   ├─ Pydantic & domain validation -> VALIDATION_ERROR (400/422)
   └─ Resource-level host serialization (`CrossProcessLock` on daily closing, credit/approvals, ID allocation)

3. Governed Action, Schema & Idempotency Gate (`apps_script_bridge.execute_governed_write`)
   ├─ Action allowlist (`action_registry.py`) & schema write-block gate (`schema_registry.py` DB-003/DB-007) -> DEPENDENCY_UNAVAILABLE (503)
   ├─ Deterministic SHA-256 fingerprint (`compute_deterministic_payload_hash`)
   ├─ Pre-check + atomic SQLite WAL CAS (`tx_coordinator.begin_governed_transaction`):
   │   ├─ Action/tab mismatch -> FAILED / IDEMPOTENCY_CONFLICT (409)
   │   ├─ Payload hash mismatch (any non-FAILED state or allocated_id present) -> FAILED / IDEMPOTENCY_CONFLICT (409)
   │   ├─ Already COMMITTED or RECONCILED -> Replay verified outcome (`is_replay=True`, 0 remote POSTs)
   │   ├─ Active EXECUTING lease -> REJECTED / DUPLICATE_REQUEST (409 CONCURRENT_DUPLICATE_REQUEST)
   │   ├─ Expired EXECUTING lease / UNKNOWN / RECOVERY_REQUIRED -> Evidence-Based Recovery (`recover_transaction`)
   │   └─ New or confirmed-FAILED -> Record intent (`INITIATED -> VALIDATING -> EXECUTING`) with lease
   └─ Pre-flight ID prefix & duplicate-ID guard (`_preflight_validate_payload_ids`)

4. Gateway Execution (`WebAppBridge.gs` via HMAC-SHA256 POST)
   ├─ Pre-transmission refusal (`ConnectionRefusedError`, DNS `gaierror`) -> FAILED / DEPENDENCY_UNAVAILABLE (503, retryable=True)
   ├─ Explicit gateway rejection (4xx/502) -> FAILED / VALIDATION_ERROR | WRITE_REJECTED (retryable=False/conditional)
   └─ Timeout / Reset / Disconnect / Malformed JSON -> UNKNOWN / WRITE_OUTCOME_UNKNOWN (504, retryable=True after status check)

5. Read-Back Verification (`_verify_readback` with bounded 2-attempt fresh read retry)
   ├─ Primary row exists uniquely (`len == 1`), expected state assertions match, child rows meet count/balance/subtotal invariants -> COMMITTED (200)
   ├─ Transient Sheets read error or row not yet visible -> UNKNOWN / VERIFICATION_FAILED (504 PENDING_UNKNOWN)
   └─ Duplicate primary rows, missing child rows, imbalanced `JournalLines`, or `SaleItems` total mismatch -> RECOVERY_REQUIRED (409, retryable=False)

6. Structured Audit Logging (`TX_AUDIT:*`)
   ├─ Secret/PII sanitized via `sanitize_audit_metadata()`
   └─ Audit failure logged explicitly and surfaced via `audit_logged=False` without fabricating failure of an already-committed write

7. Evidence-Based Recovery & Controlled Reconciliation
   ├─ `GET /api/v2/transactions/{nonce}/status` (fail-closed across `IdAllocations` + `AuditLog` + primary tab)
   ├─ `recover_transaction()` on retry: auto-confirms complete commits, quarantines orphan/partial writes, allows retry ONLY if Sheets healthy & empty
   └─ Owner reconciliation: `GET /api/v2/transactions/unresolved` -> `POST /api/v2/transactions/{nonce}/reconcile` -> `RECONCILED`
```

### C.2 Allowed Canonical State Transitions

| From State | Allowed Next States | Trigger |
|---|---|---|
| `INITIATED` | `VALIDATING`, `FAILED` | Request received and validated |
| `VALIDATING` | `EXECUTING`, `FAILED` | Schema, allowlist, and pre-flight ID checks pass/fail |
| `EXECUTING` | `COMMITTED`, `FAILED`, `UNKNOWN`, `RECOVERY_REQUIRED` | Gateway response + read-back verification or lease expiry |
| `FAILED` | `EXECUTING` (same nonce retry) | Confirmed zero-effect failure retried cleanly |
| `UNKNOWN` | `COMMITTED`, `PENDING`, `RECOVERY_REQUIRED` | Evidence-based `recover_transaction()` against Google Sheets |
| `PENDING` | `EXECUTING` | Verified zero-effect in Sheets; safe same-nonce retry acquired |
| `RECOVERY_REQUIRED` | `RECONCILED` | Owner explicit reconciliation (`POST /api/v2/transactions/{nonce}/reconcile`) |
| `COMMITTED` | *(terminal; idempotent replay only)* | Replay returns cached/verified outcome without remote write |
| `RECONCILED` | *(terminal; retry permanently blocked)* | Status returns `RECONCILED`, `safe_to_retry_same_nonce=False` |

---

## Deliverable D: Operation Safety Matrix

*(Legend: `PASS (Local)` = verified via automated local tests/simulator; `PARTIAL` = host-local or schema-blocked; `BLOCKED_PENDING_STAGING` = requires live Apps Script/Sheets validation.)*

| Operation | Idempotent | Concurrent Safe | Partial Failure Recovery | Verified | Remaining Risk |
|-----------|-------------|----------------|-------------------------|----------|----------------|
| **Sales (`CREATE_SALE`)** | PASS (Local — nonce + deterministic hash + coordinator) | PARTIAL (Host-local `CrossProcessLock` + WAL CAS; multi-host needs `DB-008`) | PASS (Local — `SaleItems` total mismatch & secondary `post_sale_journal` failure quarantined as `RECOVERY_REQUIRED` 409) | PASS (Local — `test_c7`, `test_e1`, `test_sales*`, `test_buyer_info_optional`) | External Apps Script multi-tab atomicity (`DB-008`) unverified in live Sheets; `Sales` schema reconciliation (`51B-2`) |
| **Customer Payments (`RECORD_SALE_PAYMENT`)** | PASS (Local — cross-sale `Payments` scan + method mismatch 409 + bridge coordinator) | PARTIAL (Host-local WAL CAS + credit lock; multi-host needs `DB-008`) | PASS (Local — secondary `post_payment_collection_journal` failure quarantined as `RECOVERY_REQUIRED` 409) | PASS (Local — `test_e1`, `test_accounting_integrity::test_10`) | External Apps Script `CashLedger`/`Payments` atomicity (`DB-008`) |
| **Purchases / POs (`CREATE_PURCHASE_ORDER`)** | PASS (Local — bridge coordinator nonce + payload hash) | PARTIAL (Host-local WAL CAS) | PASS (Local — bridge read-back + `recover_transaction`) | PASS (Local — purchasing regression suite) | Live Apps Script lock verification (`DB-008`); schema blocks (`51B-2`) |
| **Supplier Payments (`RECORD_SUPPLIER_PAYMENT` / `APPLY_SUPPLIER_ADVANCE`)** | PASS (Local — distinct deterministic repair nonce + coordinator) | PARTIAL (Host-local locks + WAL CAS; verified in `test_supplier_payment_integrity` 31/31) | PASS (Local — forward recovery on bill update/journal failure verified) | PASS (Local — `test_supplier_payment_integrity.py` 31/31) | Multi-host concurrency (`DB-008`) |
| **Goods Receipts (`CREATE_GRN`)** | PASS (Local — bridge coordinator + read-back) | PARTIAL (Host-local WAL CAS) | PASS (Local — bridge read-back + `RECOVERY_REQUIRED` quarantine) | PASS (Local — procurement/inventory suites) | Multi-tab stock + bill atomicity inside external Apps Script (`DB-008`) |
| **Production (`CREATE_PRODUCTION_BATCH`, `ISSUE_MATERIALS`, `RECORD_MILLING_BATCH` / `RECOVER_MILLING_BATCH`)** | PASS (Local — distinct deterministic milling recovery nonce + coordinator) | PARTIAL (Host-local locks + WAL CAS) | PASS (Local — Leg-1/Leg-2 milling forward recovery verified) | PASS (Local — `test_dal_milling_stage2.py`, `test_daily_operations_readiness.py`) | External Apps Script `RawMaterialLedger` lock (`DB-008`) |
| **Packaging (`CREATE_PACKAGING_BATCH`, `APPROVE_PACKAGING_DISCREPANCY`)** | PASS (Local — coordinator + domain idempotency + audit dedup) | PARTIAL (Host-local cross-process lock verified across 2 PIDs) | PASS (Local — AuditLog recovery verified) | PASS (Local — `test_daily_operations_readiness::test_12`) | Multi-host concurrency (`DB-008`) |
| **Stock Movements (`VERIFY_RAW_MATERIAL_OPENING_STOCK`, Stock Adjustments)** | PASS (Local — JSON-string volatile timestamp stripping + coordinator) | PARTIAL (Host-local locks + WAL CAS) | PASS (Local — AuditLog failure recovery & replay verified) | PASS (Local — `test_daily_operations_readiness` `test_06`, `test_08`, `test_10`) | Live Sheets read-back latency & `DB-008` |
| **Stock Transfers (Factory -> Salesman)** | PASS (Local — bridge coordinator + read-back) | PARTIAL (Host-local WAL CAS) | PASS (Local — read-back verification & quarantine) | PASS (Local — stock/sales regression tests) | Multi-host concurrency (`DB-008`) |
| **Customer Returns** | PASS (Local — bridge coordinator + read-back) | PARTIAL (Host-local WAL CAS) | PASS (Local — read-back verification & quarantine) | PASS (Local — accounting/return regression tests) | External Apps Script rollback (`DB-008`) |
| **Expenses (`SUBMIT_EXPENSE`)** | PASS (Local — bridge coordinator + read-back; currently gated by `DB-003`/`DB-007` schema block) | PARTIAL (Host-local WAL CAS) | PASS (Local — fail-closed schema block + bridge recovery) | PASS (Local — schema gate & bridge tests) | Schema reconciliation belongs to Mission `51B-2` |
| **Daily Closing (`SUBMIT_DAILY_CLOSING`)** | PASS (Local — `idempotency_key` + HTTP 409 payload conflict + bridge coordinator) | PARTIAL (Host-local `CrossProcessLock("daily_closing", user_date)` + WAL CAS) | PASS (Local — bridge read-back + recovery) | PASS (Local — `test_e1` + closing tests) | Multi-host concurrency (`DB-008`) |
| **Journals (`POST_JOURNAL_VOUCHER`, `REVERSE_JOURNAL_VOUCHER`)** | PASS (Local — deterministic hash with `posted_at` excluded + coordinator) | PARTIAL (Host-local WAL CAS) | PASS (Local — missing `JournalLines`, debit/credit imbalance, duplicate primary headers quarantined as `RECOVERY_REQUIRED` 409) | PASS (Local — `test_a1`–`test_c6`, `test_accounting_integrity` 11/11) | External Apps Script `JournalHeaders`/`JournalLines` atomicity (`DB-008`) |
| **Approvals (`APPROVE_REQUEST`, `REJECT_REQUEST`)** | PASS (Local — approval lock + bridge coordinator) | PARTIAL (Host-local `CrossProcessLock` + WAL CAS) | PASS (Local — bridge read-back + recovery) | PASS (Local — approval & credit-limit tests) | Multi-host concurrency (`DB-008`) |

---

## Deliverable E: Failure Injection Report

| Scenario | Expected | Actual | Result | Evidence |
|-----------|----------|--------|--------|----------|
| **1. Gateway pre-transmission failure (`ConnectionRefusedError`, DNS `gaierror`)** | Classified as `FAILED` / `DEPENDENCY_UNAVAILABLE` (HTTP 503, `retryable=True`); same-nonce retry succeeds cleanly as attempt 2 | Returned `REJECTED`, HTTP 503, `FAILED`; retry succeeded with `attempt_number=2`, 1 committed row | PASS | `test_mission51b1_transaction_safety.py::test_c1`, `test_c2` |
| **2. Gateway timeout AFTER Apps Script committed to Sheets** | Attempt 1 returns `PENDING_UNKNOWN` / `UNKNOWN` (HTTP 504); retry inspects Sheets, detects complete commit, returns `CONFIRMED` (`is_replay=True`) with ZERO 2nd POST | Attempt 1 returned 504 `PENDING_UNKNOWN`; retry recovered `CONFIRMED` (`AUTO_CONFIRMED_FROM_SHEETS`), `len(opener.calls) == 1` | PASS | `test_mission51b1_transaction_safety.py::test_c3` |
| **3. Gateway connection drop BEFORE commit (`RemoteDisconnected`)** | Attempt 1 returns `PENDING_UNKNOWN` / `UNKNOWN` (HTTP 504); retry inspects healthy Sheets, verifies 0 side effects, safely re-executes same nonce and commits | Attempt 1 returned 504 `PENDING_UNKNOWN`; retry verified empty Sheets and committed on attempt 2 (`len(opener.calls) == 2`, 1 row) | PASS | `test_mission51b1_transaction_safety.py::test_c4` |
| **4. Gateway returns malformed JSON / HTTP 422 rejection** | Malformed JSON -> `UNKNOWN` / `WRITE_OUTCOME_UNKNOWN` (504); HTTP 422 -> `FAILED` / `VALIDATION_ERROR` (422, `retryable=False`) | Exact state, category, HTTP status, and retryability matched | PASS | `test_mission51b1_transaction_safety.py::test_c9` |
| **5. Partial write — Primary committed, child rows (`JournalLines`) missing** | Quarantined as `RECOVERY_REQUIRED` (HTTP 409, `retryable=False`); subsequent retry blocked permanently until Owner reconciliation | Returned 409 `RECOVERY_REQUIRED`; subsequent retry returned 409 with `len(opener.calls) == 1` (0 duplicate writes) | PASS | `test_mission51b1_transaction_safety.py::test_c5` |
| **6. Imbalanced `JournalLines` & duplicate primary rows (`len > 1`)** | Both quarantined immediately as `RECOVERY_REQUIRED` (HTTP 409, `retryable=False`) | Both quarantined as HTTP 409 `RECOVERY_REQUIRED` with explicit diagnostic message | PASS | `test_mission51b1_transaction_safety.py::test_c6` |
| **7. `SaleItems` line total mismatch vs `Sales` bill total (and discount-aware subtotal pass)** | Mismatch (200 vs 500) quarantined as `RECOVERY_REQUIRED` (HTTP 409); valid discounted bill (200 subtotal - 10 discount = 190 bill_total) passes | Mismatch quarantined 409; valid discounted sale confirmed cleanly | PASS | `test_mission51b1_transaction_safety.py::test_c7`, `test_buyer_info_optional.py::test_11` |
| **8. Transient read-back failure on 1st attempt, healthy on 2nd** | Bounded read-back retry succeeds without false `PENDING_UNKNOWN` | Confirmed cleanly on retry attempt 2 | PASS | `test_mission51b1_transaction_safety.py::test_c8` |
| **9. Audit log sink throws exception after commit + secret redaction** | Sensitive fields redacted (`[REDACTED]` / `[REDACTED_TOKEN]`); committed write still returns `CONFIRMED` with `audit_logged=False` explicitly surfaced | Redaction verified; committed write returned `CONFIRMED` with `audit_logged=False` | PASS | `test_mission51b1_transaction_safety.py::test_c10` |
| **10. Status check partial outage (ONLY `AuditLog` fails with 429)** | Must fail closed as `UNKNOWN_STORAGE_UNAVAILABLE` (`safe_to_retry_same_nonce=False`), never falsely safe-to-retry | Returned `UNKNOWN_STORAGE_UNAVAILABLE`, `safe_to_retry_same_nonce=False` | PASS | `test_mission51b1_transaction_safety.py::test_d2` |
| **11. Orphan `IdAllocations` row & duplicate primary rows on status check** | Must report `RECOVERY_REQUIRED` (`safe_to_retry_same_nonce=False`), never `CONFIRMED_RECORDED` | Returned `RECOVERY_REQUIRED` with `ORPHAN_ID_ALLOCATION_DETECTED` and `DUPLICATE_PRIMARY_ROWS_DETECTED` | PASS | `test_mission51b1_transaction_safety.py::test_d1` |
| **12. Worker crash / restart leaving stale `EXECUTING` lease** | Expired lease transitions to `UNKNOWN`, triggers `recover_transaction()`, auto-confirms existing commit with 0 duplicate POSTs | Auto-confirmed `JV-009300` (`AUTO_CONFIRMED_FROM_SHEETS`) with `len(opener.calls) == 0` | PASS | `test_mission51b1_transaction_safety.py::test_d3` |
| **13. Concurrent identical requests (threads + 2 independent SQLite coordinators)** | Exactly 1 executes remote write; concurrent duplicate gets 409 `CONCURRENT_DUPLICATE_REQUEST` or verified replay; conflicting payload gets 409 `PAYLOAD_CONFLICT` | Exactly 1 remote POST; atomic CAS enforced across two independent `TransactionCoordinator` instances | PASS | `test_mission51b1_transaction_safety.py::test_b1`, `test_b2` |
| **14. Frontend double-click, mutation proxy retry suppression, dropped write -> `ApiOutcomeUnknownError`, read-only GET proxy fallback** | Double-click blocked (409); POST never auto-retried via proxy; dropped POST throws `ApiOutcomeUnknownError`; GET recovers via proxy | All 5 assertions passed | PASS | `scripts/test_mission51b1_frontend_transaction_safety.ts` (5/5) |
| **15. Live Google Sheets / Apps Script `DB-008` multi-tab partial failure** | Requires staging Google Sheet + deployed `WebAppBridge.gs` | Not executed (live writes prohibited) | `BLOCKED_PENDING_STAGING` | External staging required |

---

## Deliverable F: Test Report

*(Exact verified execution results — zero fabricated numbers, zero weakened/deleted tests.)*

### F.1 Backend Automated Tests
- **Mission 51B-1 Dedicated Suite:**
  - Command: `python3 -m unittest backend/tests/test_mission51b1_transaction_safety.py -v`
  - Result: **21 run, 21 PASSED, 0 FAILED, 0 ERRORS, 0 SKIPPED** (Runtime: `0.335s`)
- **Full Backend Regression Suite:**
  - Command: `python3 -m unittest discover -s backend/tests -t backend`
  - Result: **601 discovered, 600 PASSED, 0 FAILED, 0 ERRORS, 1 SKIPPED** (Runtime: `31.531s`)
  - Skipped Test (1): `test_uvicorn_binds_and_serves_health_within_3s_when_sheets_hangs_over_5s` — cleanly skipped in offline pip-less container where `uvicorn`/`fastapi` wheels are not installed; verified in Mission 49 when full Python dependencies are present.

### F.2 Frontend Automated Tests & Build Verification
- **TypeScript Type Check & Lint:**
  - Command: `npx tsc --noEmit` / `npm run lint`
  - Result: **PASS (0 errors, 0 warnings)**
- **Mission 51B-1 Frontend Transaction Safety Suite:**
  - Command: `npx --yes tsx scripts/test_mission51b1_frontend_transaction_safety.ts`
  - Result: **5 run, 5 PASSED, 0 FAILED**
- **Existing Frontend Contract & Safety Suite:**
  - Command: `npx --yes tsx scripts/test_phase1_6_frontend_contracts.ts`
  - Result: **17 run, 17 PASSED, 0 FAILED**
- **Production Frontend Build:**
  - Command: `npm run build` (`vite build`)
  - Result: **PASS (Build succeeded cleanly)**

### F.3 Blocked External Tests (`BLOCKED_PENDING_STAGING`)
- Live Google Sheets API read-back & 429 quota stress tests
- Live Apps Script `WebAppBridge.gs` `LockService` concurrency & multi-tab rollback tests (`DB-008`)
- Multi-instance (2+ Render container) distributed concurrency tests
- Uvicorn live subprocess startup resilience test in full Python virtualenv with `requirements.txt`

---

## Deliverable G: Unresolved Risks & Status Classification

| Category | Item | Explanation & Required Next Action |
|---|---|---|
| **Fixed (Local Verified)** | Canonical lifecycle state machine, failure classification, deterministic payload fingerprinting, pre-tx vs unknown transport separation, evidence-based recovery, fail-closed status check, partial/duplicate read-back quarantine, secondary journal failure quarantine, daily closing/payment/ID locks, recovery nonce isolation, Owner reconciliation endpoints, frontend mutation safety & no-optimistic toggle | Fully implemented and verified across 600 passing backend tests + 22 passing frontend tests + clean Vite/TS build |
| **Partially Fixed** | Cross-process concurrency serialization | Guaranteed across threads and worker processes on the **same host** via SQLite WAL + `fcntl.flock`; **NOT** guaranteed across horizontally scaled multi-container deployments until Apps Script `LockService` (`DB-008`) is verified in staging |
| **Blocked by Missing Apps Script Source / Staging** | `DB-008`: External `WebAppBridge.gs` `LockService.getScriptLock()` and cross-tab rollback/atomicity | Apps Script source is external/read-only for this mission; requires dedicated Apps Script staging audit & deployment |
| **Requires Staging Validation** | Live Google Sheets API read-after-write visibility latency, real HTTP 429 quota backoff behavior, end-to-end staging transaction replay & recovery drills | Must run against an isolated clean staging spreadsheet + staging Apps Script Web App before production go-live |
| **Out-of-Scope (Preserved for Subsequent Missions)** | Schema write blocks (`DB-003`/`DB-007` — `51B-2`), RBAC/security hardening (`51B-3`), Accounting period locks (`51B-4`), Food safety & lot traceability (`51B-5`), Sales/Procurement/Inventory lifecycle (`51B-6`), Workforce/Payroll (`51B-7`), Reports (`51B-8`), Frontend/CI/Deploy hardening (`51B-9`), Full Independent Re-audit (`51B-10`) | Intentionally untouched to maintain strict Mission 51B-1 scope discipline |

---

## Deliverable H: Change Manifest

### Created Files (5)
1. `backend/app/transaction_safety.py` — Canonical `TransactionState` & `FailureCategory` enums, deterministic payload normalization & SHA-256 fingerprinting, secret-redacting audit sanitizer, and gateway transport exception classifier.
2. `backend/tests/test_mission51b1_transaction_safety.py` — 21 automated backend tests covering idempotency, concurrency, failure injection, recovery, reconciliation, confidential redaction, and router contract checks.
3. `scripts/test_mission51b1_frontend_transaction_safety.ts` — 5 automated frontend transaction safety tests covering double-click deduplication, mutation proxy-retry suppression, dropped write -> `ApiOutcomeUnknownError`, read-only GET proxy fallback, and error normalization.
4. `docs/MISSION_51B1_AUDIT_REPORT.md` — Complete Deliverables A–H audit, register, lifecycle map, safety matrix, failure injection report, test report, unresolved risks, and change manifest.
5. `docs/MISSION_51B1_README.md` — Mission 51B-1 summary, local verification commands, and staging validation checklist.

### Modified Files (13)
1. `backend/app/accounting/transaction_coordinator.py` — Added `governed_transactions` SQLite WAL table and atomic `BEGIN IMMEDIATE` CAS lifecycle methods (`begin_governed_transaction`, `transition_governed_transaction`, `get_governed_transaction`, `list_unresolved_transactions`, `mark_transaction_reconciled`), UTC-aware timestamps, and explicit error logging.
2. `backend/app/apps_script_bridge.py` — Integrated durable coordinator gate, evidence-based `recover_transaction()`, bounded read-back retry, `_PartialSideEffectFailure` (`RECOVERY_REQUIRED` 409) detection (duplicate primary rows, missing child rows, imbalanced journals, `SaleItems` subtotal/discount-aware total verification), fail-closed `check_transaction_status()`, enriched `BridgeResult`, and namespaced `TX_AUDIT:*` structured audit logging.
3. `backend/app/sheets.py` — Added `CrossProcessLock` around `generate_id()` and `allocate_bill_number()`, added `IdAllocations` scan to `allocate_bill_number()`, and added `log_transaction_audit()`.
4. `backend/app/routers/closing.py` — Added `CrossProcessLock("daily_closing", ...)` and HTTP 409 `IDEMPOTENCY_PAYLOAD_CONFLICT` validation on replay.
5. `backend/app/routers/sales.py` — Fixed cross-sale payment idempotency scanning and `payment_method` mismatch rejection (HTTP 409); added `RECOVERY_REQUIRED` quarantine + structured audit logging when secondary `post_sale_journal` or `post_payment_collection_journal` fails.
6. `backend/app/routers/purchasing.py` — Scoped deterministic forward-recovery nonce (`{key}::APPLY_ADVANCE::{pid}`) for `APPLY_SUPPLIER_ADVANCE` to prevent cross-action nonce collision.
7. `backend/app/routers/production.py` — Scoped deterministic forward-recovery nonce (`{key}::RECOVER::{batch_id}`) for `RECOVER_MILLING_BATCH` to prevent cross-action nonce collision.
8. `backend/app/routers/v2_erp.py` — Enriched `_handle_bridge_result()` with canonical transaction fields and added Owner-only `GET /api/v2/transactions/unresolved` and `POST /api/v2/transactions/{nonce}/reconcile`.
9. `backend/app/accounting/customer_ledger.py` — Updated `reset_cross_process_state()` test helper to also reset `tx_coordinator` for clean test isolation.
10. `backend/tests/v2_test_harness.py` — Updated `LocalAppsScriptSimulator.start()`/`stop()` to reset `tx_coordinator` between isolated test fixtures.
11. `src/services/api.ts` — Restricted dual-path proxy auto-retry strictly to read-only methods (`GET`/`HEAD`/`OPTIONS`); added synchronous `inflightMutationKeys` double-click deduplication (HTTP 409); added `TransactionLifecycleState`, `TransactionFailureCategory`, `ApiOutcomeUnknownError`, `isRecoveryRequiredError()`, and enriched `ApiHttpError`/`TransactionStatusResponse`.
12. `src/components/common/UnknownOutcomeBanner.tsx` — Gated `"Retry Safely (Same Nonce)"` strictly behind verified `NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE`, disabled retry permanently on `CONFIRMED_RECORDED`/`RECONCILED`/`RECOVERY_REQUIRED`, and added 2s status-check cooldown.
13. `src/context/StoreContext.tsx` — Removed optimistic `setProducts(...)` mutation in `toggleProductActive()` so UI updates only after confirmed server response.

### Removed Files (0)
- None. Zero files were deleted.
