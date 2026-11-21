# Kawad Swad ERP — Mission 51B-1: Critical Transaction & Write Safety Repair

**Mission Status:** `CONDITIONAL` (All local backend, frontend, failure-injection, concurrency, recovery, and build/lint gates PASSED; live Google Sheets & Apps Script `WebAppBridge.gs` `DB-008` staging validation remains `BLOCKED_PENDING_STAGING`.)

---

## 1. Purpose & Scope

Mission 51B-1 repairs critical transaction-safety, idempotency, concurrency, partial-write detection, read-back verification, recovery, audit, and frontend mutation-safety weaknesses across the Kawad Swad ERP codebase while strictly preserving:

- **Google Sheets** as the authoritative business database.
- **Google Apps Script (`WebAppBridge.gs`)** as the governed Single Write Owner via `backend/app/apps_script_bridge.py`.
- All existing schema write blocks (`DB-003` / `DB-007`), governed action allowlist (`backend/app/action_registry.py`), RBAC role guards, and fail-closed security invariants.
- **Clean empty target database policy** (zero historical data restoration; zero live Google Sheets/Apps Script writes; zero GitHub push or Render deployment).

Out-of-scope missions (`51B-2` Schema/Contracts, `51B-3` Security/RBAC, `51B-4` Accounting/Period Locks, `51B-5` Food Safety/Lots, `51B-6` Sales/Procurement/Inventory Lifecycle, `51B-7` Workforce/Payroll, `51B-8` Reports, `51B-9` Frontend/CI/Deploy, `51B-10` Independent Re-Audit) were **not** implemented.

---

## 2. Architecture Summary

1. **Canonical Transaction Lifecycle & Failure Taxonomy (`backend/app/transaction_safety.py`)**
   - Defines 9 canonical states (`TransactionState`): `INITIATED`, `VALIDATING`, `PENDING`, `EXECUTING`, `COMMITTED`, `FAILED`, `UNKNOWN`, `RECOVERY_REQUIRED`, `RECONCILED`.
   - Defines 11 actionable failure categories (`FailureCategory`): `VALIDATION_ERROR`, `AUTHORIZATION_ERROR`, `DUPLICATE_REQUEST`, `IDEMPOTENCY_CONFLICT`, `DEPENDENCY_UNAVAILABLE`, `WRITE_REJECTED`, `WRITE_FAILED_CONFIRMED`, `WRITE_OUTCOME_UNKNOWN`, `VERIFICATION_FAILED`, `RECOVERY_REQUIRED`, `INTERNAL_ERROR`.
   - Provides deterministic payload canonicalization & SHA-256 fingerprinting (`compute_deterministic_payload_hash`) that preserves integer trailing zeroes (`10` vs `100`), normalizes equivalent decimals (`10`, `10.0`, `"10.00"`), handles embedded JSON strings (`notes`, `allocations_json`), and excludes strictly volatile per-attempt timestamps.
   - Separates definite pre-transmission failures (`ConnectionRefusedError`, `socket.gaierror` -> `FAILED` / `DEPENDENCY_UNAVAILABLE` / HTTP 503) from ambiguous post-transmission failures (`TimeoutError`, `socket.timeout`, `RemoteDisconnected`, `ConnectionResetError`, malformed JSON -> `UNKNOWN` / `WRITE_OUTCOME_UNKNOWN` / HTTP 504).
   - Redacts secrets, tokens, passwords, bank accounts, and PII before structured transaction audit logging (`sanitize_audit_metadata`).

2. **Durable Local Transaction Coordinator (`backend/app/accounting/transaction_coordinator.py`)**
   - Adds SQLite WAL table `governed_transactions` with `BEGIN IMMEDIATE` atomic compare-and-swap transitions (`begin_governed_transaction`, `transition_governed_transaction`, `get_governed_transaction`, `list_unresolved_transactions`, `mark_transaction_reconciled`).
   - Enforces single-execution leases, stale-lease expiry recovery (`STALE_EXECUTION_LEASE`), cross-action conflict rejection (HTTP 409 `IDEMPOTENCY_ACTION_CONFLICT`), payload conflict rejection (HTTP 409 `IDEMPOTENCY_PAYLOAD_CONFLICT`), and controlled Owner reconciliation.
   - **Honest distributed boundary**: SQLite WAL + POSIX `fcntl.flock` locks provide strong mutual exclusion across threads and worker processes **on the same host**, but are **not** a global distributed lock across multiple Render instances without external Apps Script `LockService` verification (`DB-008`).

3. **Governed Write Gateway, Verification & Recovery (`backend/app/apps_script_bridge.py`)**
   - Integrates coordinator idempotency/concurrency gating before every remote POST.
   - Adds evidence-based `recover_transaction()` inspecting authoritative Google Sheets (`IdAllocations`, `AuditLog`, target tab, and child tabs) before permitting any retry of an `UNKNOWN`, `RECOVERY_REQUIRED`, or stale-lease transaction.
   - Distinguishes transient read-back lookup errors (`_ReadBackFailure` -> `PENDING_UNKNOWN`) from confirmed partial/corrupt/duplicate side effects (`_PartialSideEffectFailure` -> `RECOVERY_REQUIRED`, HTTP 409, `retryable=False`).
   - Detects duplicate primary rows (`len(matched_rows) > 1`), missing child rows, imbalanced `JournalLines`, and `SaleItems` line-total vs `Sales.subtotal` (or `bill_total + discount_amount - tax_amount`) mismatches.
   - Fixes `check_transaction_status()` fail-open bug (`if alloc_error or audit_error:`) and orphan `IdAllocations` false-positive bug (verifies primary record existence & uniqueness).

4. **Router & ID Allocation Repairs**
   - `backend/app/sheets.py`: Serializes `generate_id()` and `allocate_bill_number()` under `CrossProcessLock`; scans `IdAllocations` in `allocate_bill_number()` so deleted/missing `Sales` rows cannot recycle bill numbers; adds secret-redacted `log_transaction_audit()`.
   - `backend/app/routers/closing.py`: Serializes `submit_daily_closing` under `CrossProcessLock("daily_closing", ...)` and validates replay payload consistency (HTTP 409 `IDEMPOTENCY_PAYLOAD_CONFLICT`).
   - `backend/app/routers/sales.py`: Scans all `Payments` rows for cross-sale idempotency key reuse and `payment_method` mismatch (HTTP 409); quarantines primary sale/payment transactions into `RECOVERY_REQUIRED` with structured audit logs if secondary journal posting (`post_sale_journal` / `post_payment_collection_journal`) fails.
   - `backend/app/routers/purchasing.py` & `backend/app/routers/production.py`: Fixes real forward-recovery nonce collision bugs where `APPLY_SUPPLIER_ADVANCE` and `RECOVER_MILLING_BATCH` reused the original primary action's nonce.
   - `backend/app/routers/v2_erp.py`: Exposes canonical transaction fields in `_handle_bridge_result()` and adds Owner-only `GET /api/v2/transactions/unresolved` and `POST /api/v2/transactions/{nonce}/reconcile`.

5. **Frontend Mutation Safety (`src/services/api.ts`, `src/components/common/UnknownOutcomeBanner.tsx`, `src/context/StoreContext.tsx`)**
   - Restricts Vite proxy auto-retry strictly to read-only HTTP methods (`GET`, `HEAD`, `OPTIONS`) — mutations never auto-replay silently across URLs.
   - Adds synchronous in-flight mutation deduplication (`inflightMutationKeys`) to block double-clicks immediately with HTTP 409 `CONCURRENT_DUPLICATE_REQUEST`.
   - Raises `ApiOutcomeUnknownError` (`status: 'PENDING_UNKNOWN'`, `transactionState: 'UNKNOWN'`) when a business mutation fails with an ambiguous network drop/timeout instead of a misleading generic failure.
   - Gates `UnknownOutcomeBanner` `"Retry Safely (Same Nonce)"` strictly behind server-verified `NOT_FOUND_SAFE_TO_RETRY_SAME_NONCE` (`safe_to_retry_same_nonce === true`), disables retry permanently on `CONFIRMED_RECORDED` / `RECONCILED` / `RECOVERY_REQUIRED`, and adds a 2-second status-check cooldown.
   - Removes optimistic `setProducts(...)` mutation in `StoreContext.toggleProductActive()` so UI updates only on confirmed backend success.

---

## 3. Exact Local Verification Commands

Run all commands from the repository root:

```bash
# 1. Mission 51B-1 Backend Transaction Safety & Failure Injection Suite (21 tests)
python3 -m unittest backend/tests/test_mission51b1_transaction_safety.py -v

# 2. Full Backend Regression Suite (601 discovered tests)
python3 -m unittest discover -s backend/tests -t backend

# 3. Frontend TypeScript Type Check
npx tsc --noEmit

# 4. Mission 51B-1 Frontend Transaction Safety Tests (5 tests)
npx --yes tsx scripts/test_mission51b1_frontend_transaction_safety.ts

# 5. Existing Frontend Contract & Safety Suite (17 tests)
npx --yes tsx scripts/test_phase1_6_frontend_contracts.ts

# 6. Production Frontend Build
npm run build
```

---

## 4. Blocked Staging / Live Validation (`BLOCKED_PENDING_STAGING`)

The following validations were intentionally **not** executed against live systems and require an isolated staging Google Sheet + Apps Script deployment:

1. **Apps Script `WebAppBridge.gs` Concurrency & Cross-Tab Atomicity (`DB-008`)**: Live verification of `LockService.getScriptLock()`, `IdAllocations` uniqueness under parallel Google Sheets requests, and multi-tab rollback behavior when a child-tab write fails inside Apps Script.
2. **Multi-Instance Distributed Concurrency**: Concurrent mutation testing across 2+ independent Render containers sharing only Google Sheets / Apps Script (without shared host filesystem/SQLite).
3. **Live Google Sheets API Quota & Read-Back Latency**: Real-world 429 quota backoff and read-after-write visibility latency against Google Sheets v4 API.
4. **Uvicorn Live Subprocess Startup Test**: `test_uvicorn_binds_and_serves_health_within_3s_when_sheets_hangs_over_5s` is cleanly skipped in pip-less offline containers lacking `uvicorn`/`fastapi` wheels; run in full Python staging/CI environment with `requirements.txt` installed.

---

## 5. Full Evidence & Audit Report

See `docs/MISSION_51B1_AUDIT_REPORT.md` for Deliverables A through H (Before/After Architecture, Critical Repair Register, Transaction Lifecycle Map, 14-Operation Safety Matrix, Failure Injection Report, Complete Test Report, Unresolved Risks, and Exact Change Manifest).
