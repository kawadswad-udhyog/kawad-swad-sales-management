# Kawad Swad ERP — Mission 51B-1 Repair Round 2 Report
## Transaction State Integrity, Coordinator Durability & Package Integrity

**Mission:** Mission 51B-1 — Repair Round 2  
**Baseline Archive:** `Kawad_Swad_Mission51B1_Audit_Package.zip` (298 files, 3,342,243 bytes, `testzip()=None`, SHA-256 `0e8fb9242e664fd550fd6e62b5b7822f6b1c3b0f1cd94763398b995f860bea86`)  
**Verdict:** `CONDITIONAL` (All three Round 2 repository/code defects `TX-AUDIT-01`, `TX-AUDIT-02`, and `TX-AUDIT-03` are fully repaired and verified by automated tests; live Google Sheets / external Apps Script `DB-008` staging execution remains `BLOCKED_PENDING_STAGING` and is outside repository scope.)

---

## Deliverable A — Pre-Fix Defect Verification (Reproduced Before Repair)

### 1. `TX-AUDIT-01` — Illegal `COMMITTED -> FAILED` Transition Overwrite
- **Pre-fix reproduction:** Running `begin_governed_transaction` -> `transition_governed_transaction(lifecycle_state="COMMITTED")` -> `transition_governed_transaction(lifecycle_state="FAILED")` on Round 1's `TransactionCoordinator` produced verbatim output:
  - `BEGUN: ACQUIRED EXECUTING`
  - `AFTER COMMIT: COMMITTED`
  - `REPRODUCED TX-AUDIT-01 (COMMITTED->FAILED): FAILED`
- **Root cause:** Round 1 `transition_governed_transaction()` issued an unconditional `UPDATE governed_transactions SET lifecycle_state = ? ... WHERE nonce = ?` without enforcing a state-transition matrix, terminal-state protection, optimistic version CAS, expected source state, or worker lease ownership.

### 2. `TX-AUDIT-02` — Volatile `/tmp` Coordinator Fallback & Missing Durability Gates
- **Pre-fix reproduction:**
  - `DEFAULT_DB_PATH` defaulted silently to `/tmp/kawad_swad_tx_coord.db`.
  - `render.yaml` configured `SALES_ENV=production` with no persistent `disk:` mount and no `TRANSACTION_DB_PATH`.
  - `assert_runtime_config()` did not validate coordinator durability, mount existence, writability, or single-instance scaling constraints.
  - `execute_governed_write()` did not inspect authoritative Google Sheets `IdAllocations` when a nonce was absent from local SQLite after local DB loss.

### 3. `TX-AUDIT-03` — Accidental Prompt Artifact & Round 1 SHA-256 Mismatch Root Cause
- **Pre-fix inspection:**
  - `public/assets/aistudio/Paste_November_21__2026_-_11_52PM_b5cb8f2f` existed in the workspace root (`AISTUDIO_FILE_EXISTS: True`).
  - Repository-wide search across `src/`, `backend/`, `scripts/`, `index.html`, `vite.config.ts`, `package.json`, and `render.yaml` confirmed **0 references** (purely an accidental AI Studio prompt attachment).
  - **Exact cause of Round 1 SHA-256 mismatch (`0e8fb924...` vs `6b2f7439...`):** The generated Round 1 archive `Kawad_Swad_Mission51B1_Audit_Package.zip` (`0e8fb9242e664fd550fd6e62b5b7822f6b1c3b0f1cd94763398b995f860bea86`, 298 files, `AISTUDIO_IN_ZIP=[]`) excluded `public/assets/aistudio/`, whereas the archive uploaded externally for independent audit (`6b2f7439...`) was the raw AI Studio workspace export containing `public/assets/aistudio/Paste_November_21__2026_-_11_52PM_b5cb8f2f`.
- **Remediation:** Deleted `public/assets/aistudio/Paste_November_21__2026_-_11_52PM_b5cb8f2f`, removed the empty `public/assets/aistudio/` and `public/assets/` directories, removed the superseded Round 1 ZIP, and added automated archive verification via `scripts/verify_package_hygiene.py`.

---

## Deliverable B — Authoritative Legal Transaction State-Transition Matrix (`TX-AUDIT-01`)

Single source of truth: `LEGAL_TRANSITION_MATRIX` and `validate_state_transition()` in `backend/app/transaction_safety.py`, atomically enforced inside SQLite `BEGIN IMMEDIATE` transactions with Compare-And-Swap (`WHERE nonce = ? AND lifecycle_state = ? AND version = ? [AND correlation_id = ?] [AND attempt_count = ?]`) in `backend/app/accounting/transaction_coordinator.py`.

### Transition Authorities
- `ORDINARY`: Normal in-flight worker execution holding the active execution lease (`correlation_id` + `attempt_count` + non-expired `lease_expires_at`).
- `RETRY`: Controlled retry acquisition from definitively confirmed non-committed states (`FAILED` or `PENDING`) with incremented `attempt_count` and fresh lease.
- `RECOVERY`: Evidence-based Google Sheets recovery (`recover_transaction`, startup stale-lease sweep, or post-coordinator-loss registration).
- `SECONDARY_QUARANTINE`: Constrained post-commit quarantine when primary Google Sheets record committed cleanly, but a mandatory secondary side effect (e.g. accounting journal posting in `sales.py`) failed. Requires explicit `actor` + `reason`/`evidence`.
- `RECONCILIATION`: Owner-only manual resolution (`POST /api/v2/transactions/{nonce}/reconcile`) requiring explicit `actor` + `resolution_notes`.

### Complete Legal Transition Matrix (24 Explicit Rules)

| # | From State | To State | Allowed Authorities | CAS | Evidence / Reason | Lease Owner | Dest Terminal | Purpose |
|---|---|---|---|---|---|---|---|---|
| 1 | `INITIATED` | `VALIDATING` | `ORDINARY` | Yes | No | Yes | No | Initial validation begins |
| 2 | `INITIATED` | `EXECUTING` | `ORDINARY` | Yes | No | Yes | No | Direct transition to execution |
| 3 | `INITIATED` | `FAILED` | `ORDINARY` | Yes | No | Yes | No | Pre-execution rejection |
| 4 | `INITIATED` | `UNKNOWN` | `RECOVERY` | Yes | Yes | No | No | Stale lease expired in `INITIATED` |
| 5 | `VALIDATING` | `EXECUTING` | `ORDINARY` | Yes | No | Yes | No | Validation passed; begin governed write |
| 6 | `VALIDATING` | `FAILED` | `ORDINARY` | Yes | No | Yes | No | Validation rejected before gateway POST |
| 7 | `VALIDATING` | `UNKNOWN` | `RECOVERY` | Yes | Yes | No | No | Stale lease expired in `VALIDATING` |
| 8 | `PENDING` | `EXECUTING` | `RETRY` | Yes | No | No | No | Controlled retry after Sheets verified zero side effects |
| 9 | `PENDING` | `FAILED` | `ORDINARY`, `RECOVERY` | Yes | No | No | No | Pending intent aborted cleanly before remote write |
| 10 | `PENDING` | `RECOVERY_REQUIRED` | `RECOVERY` | Yes | Yes | No | No | Evidence revealed partial side effects for pending intent |
| 11 | `PENDING` | `RECONCILED` | `RECONCILIATION` | Yes | Yes | No | Yes | Owner manually reconciled pending intent |
| 12 | `EXECUTING` | `COMMITTED` | `ORDINARY` | Yes | No | Yes | Yes | Gateway confirmed write + read-back verification succeeded |
| 13 | `EXECUTING` | `FAILED` | `ORDINARY` | Yes | No | Yes | No | Definitive pre-transmission failure or explicit 4xx/redirect rejection |
| 14 | `EXECUTING` | `UNKNOWN` | `ORDINARY`, `RECOVERY` | Yes | No | Yes | No | Ambiguous timeout/drop/malformed response or stale lease expiry |
| 15 | `EXECUTING` | `RECOVERY_REQUIRED` | `ORDINARY`, `RECOVERY` | Yes | Yes | Yes | No | Partial, imbalanced, or duplicate side effects detected on read-back |
| 16 | `FAILED` | `EXECUTING` | `RETRY` | Yes | No | No | No | Explicit controlled retry with incremented `attempt_count` |
| 17 | `UNKNOWN` | `COMMITTED` | `RECOVERY` | Yes | Yes | No | Yes | Evidence-based Sheets inspection verified complete commit |
| 18 | `UNKNOWN` | `PENDING` | `RECOVERY` | Yes | Yes | No | No | Evidence-based Sheets inspection confirmed zero side effects |
| 19 | `UNKNOWN` | `RECOVERY_REQUIRED` | `RECOVERY` | Yes | Yes | No | No | Evidence-based Sheets inspection detected orphan/partial/duplicate write |
| 20 | `UNKNOWN` | `UNKNOWN` | `RECOVERY` | Yes | Yes | No | No | Recovery deferred because Sheets status tables are unreachable |
| 21 | `UNKNOWN` | `RECONCILED` | `RECONCILIATION` | Yes | Yes | No | Yes | Owner manually reconciled unknown-outcome transaction |
| 22 | `RECOVERY_REQUIRED` | `COMMITTED` | `RECOVERY` | Yes | Yes | No | Yes | Evidence-based Sheets inspection verified all required rows intact |
| 23 | `RECOVERY_REQUIRED` | `RECONCILED` | `RECONCILIATION` | Yes | Yes | No | Yes | Owner manually reconciled quarantined transaction with audit trail |
| 24 | `COMMITTED` | `RECOVERY_REQUIRED` | `SECONDARY_QUARANTINE` | Yes | Yes (actor + evidence) | No | No | Constrained post-commit quarantine when mandatory secondary journal fails |

### Explicitly Forbidden Transitions (Guaranteed Rejected With Zero DB Mutation)
- `COMMITTED -> FAILED`, `COMMITTED -> INITIATED`, `COMMITTED -> VALIDATING`, `COMMITTED -> PENDING`, `COMMITTED -> EXECUTING`, `COMMITTED -> UNKNOWN`, `COMMITTED -> RECONCILED`, `COMMITTED -> COMMITTED` (always rejected with `TERMINAL_STATE_PROTECTED` / `CAS_STATE_MISMATCH`).
- `RECONCILED -> *` (strictly immutable; ZERO outgoing transitions under any authority; always rejected with `TERMINAL_STATE_IMMUTABLE`).
- `RECOVERY_REQUIRED -> EXECUTING`, `RECOVERY_REQUIRED -> PENDING`, `RECOVERY_REQUIRED -> FAILED`, `RECOVERY_REQUIRED -> UNKNOWN` (quarantine cannot be bypassed by ordinary retry or downgraded).
- Any rejected transition executes `ROLLBACK` and raises `InvalidStateTransitionError` with zero mutation to `lifecycle_state`, `message`, `error_code`, `allocated_id`, `version`, `updated_at`, or `steps_json`.

---

## Deliverable C — Coordinator Durability & Restart-Safety Architecture (`TX-AUDIT-02`)

1. **No Silent `/tmp` Fallback in Production:**
   - Removed silent `/tmp/kawad_swad_tx_coord.db` fallback from `DEFAULT_DB_PATH` in `transaction_coordinator.py`.
   - `validate_coordinator_durability()` in `transaction_safety.py` classifies durability explicitly (`PERSISTENT`, `VOLATILE_TEST`, `DEV_LOCAL`, `MISCONFIGURED`, `UNAVAILABLE`).
   - When `SALES_ENV=production` (and `SALES_TESTING != 1`), startup (`config.assert_runtime_config()` -> `main._check_configuration()`) and every governed write (`apps_script_bridge.execute_governed_write()`) fail closed if:
     - `TRANSACTION_DB_PATH` is empty (`COORDINATOR_PATH_UNCONFIGURED`),
     - `TRANSACTION_DB_PATH` points to `/tmp`, `/var/tmp`, `/dev/shm`, or `:memory:` (`COORDINATOR_VOLATILE_PATH_IN_PRODUCTION`),
     - the parent directory is missing/unmounted (`COORDINATOR_DIRECTORY_UNAVAILABLE`),
     - the parent directory is not writable (`COORDINATOR_DIRECTORY_NOT_WRITABLE`),
     - horizontal scaling is configured (`SALES_INSTANCE_COUNT` or `RENDER_INSTANCE_COUNT > 1` -> `COORDINATOR_MULTI_INSTANCE_UNSUPPORTED`).
2. **Persistent Disk Deployment Configuration (`render.yaml` & `.env.example`):**
   - Configured a persistent Render disk (`name: kawad-swad-tx-coord-disk`, `mountPath: /var/data/kawad_swad`, `sizeGB: 1`) on `kawad-swad-sales-dev`.
   - Configured `TRANSACTION_DB_PATH=/var/data/kawad_swad/kawad_swad_tx_coord.db`, `KS_ERP_LOCK_DIR=/var/data/kawad_swad/locks`, `KS_ERP_STATE_DIR=/var/data/kawad_swad/state`, `SALES_TX_LEASE_SECONDS=90`, `WEB_CONCURRENCY=1`, and `SALES_INSTANCE_COUNT=1`.
3. **SQLite WAL Durability & Startup Recovery:**
   - Enabled `PRAGMA journal_mode=WAL;`, `PRAGMA synchronous=FULL;`, `PRAGMA foreign_keys=ON;`, `PRAGMA busy_timeout=15000;`.
   - Added non-destructive schema migration (`previous_state`, `last_authority`, `version`, `lease_owner`, and index `idx_gov_tx_state_updated`).
   - `recover_stale_leases_on_startup()` runs on coordinator startup to atomically CAS-transition expired `INITIATED`/`VALIDATING`/`EXECUTING` leases to `UNKNOWN` so crashed workers never stay permanently stuck in `EXECUTING`.
4. **Post-Coordinator-Loss Protection (Authoritative Google Sheets Check):**
   - If the local SQLite coordinator DB is lost/wiped and a client retries a previously committed nonce, `execute_governed_write()` sees `prior_tx is None`, queries authoritative Google Sheets `IdAllocations` (`fresh=True`), registers an external recovery intent (`register_external_recovery_intent()`), and runs `recover_transaction()` BEFORE transmitting any gateway HTTP POST.
   - Result: previously committed transactions recover cleanly (`CONFIRMED`, `is_replay=True`, **0 duplicate gateway POSTs**), and orphan allocations quarantine safely (`RECOVERY_REQUIRED`, HTTP 409, **0 duplicate gateway POSTs**).
5. **Honest Distributed Scaling Boundary:**
   - Host-local SQLite WAL + `fcntl.flock` is explicitly single-host / single-container (`WEB_CONCURRENCY=1`, `SALES_INSTANCE_COUNT=1`). Multi-container concurrency and Google Sheets cross-tab atomicity remain gated on external Apps Script `LockService` (`DB-008`, `BLOCKED_PENDING_STAGING`).

---

## Deliverable D — Round 2 Change Manifest

### Modified Files
1. `backend/app/transaction_safety.py` — Added `TransitionAuthority`, `TransitionRule`, `TERMINAL_STATES`, `PROTECTED_STATES`, `InvalidStateTransitionError`, `LEGAL_TRANSITION_MATRIX` (24 rules), `validate_state_transition()`, `get_legal_transition_matrix_summary()`, `CoordinatorDurabilityMode`, `CoordinatorDurabilityError`, and `validate_coordinator_durability()`.
2. `backend/app/accounting/transaction_coordinator.py` — Removed silent `/tmp` default; integrated `validate_coordinator_durability()` & `assert_writable_coordinator()`; upgraded to `PRAGMA synchronous=FULL`; added schema columns (`previous_state`, `last_authority`, `version`, `lease_owner`); added `recover_stale_leases_on_startup()` and `register_external_recovery_intent()`; rewrote `begin_governed_transaction()`, `transition_governed_transaction()`, and `mark_transaction_reconciled()` with authoritative matrix validation and atomic SQL CAS.
3. `backend/app/apps_script_bridge.py` — Added fail-closed `CoordinatorDurabilityError` HTTP 503 handling; added post-coordinator-loss Google Sheets `IdAllocations` safeguard (`_find_existing_sheets_allocation_for_nonce()`); updated all `recover_transaction()` and `execute_governed_write()` transitions to pass explicit `TransitionAuthority`, `expected_from_state`, `expected_correlation_id`, `expected_attempt`, actor, and evidence, handling `InvalidStateTransitionError` cleanly without overwriting authoritative DB state.
4. `backend/app/routers/sales.py` — Updated both post-commit secondary journal failure quarantine transitions (`CREATE_SALE`, `RECORD_SALE_PAYMENT`) to pass `authority="SECONDARY_QUARANTINE"`, `expected_from_state="COMMITTED"`, `actor=user_id`, `reason`, and `evidence`.
5. `backend/app/routers/v2_erp.py` — Added explicit HTTP 409 (`InvalidStateTransitionError`) and HTTP 503 (`CoordinatorDurabilityError`) handling on `/transactions/unresolved` and `/transactions/{nonce}/reconcile`.
6. `backend/app/config.py` — Added `validate_coordinator_durability(env=SALES_ENV, testing=testing)` inside `assert_runtime_config()` for production startup fail-closed enforcement.
7. `backend/tests/test_startup_port_bind_and_resilience.py` — Supplied temporary non-volatile `TRANSACTION_DB_PATH` directories (cleaned up in `finally`) to the two simulated `SALES_ENV=production` subprocess tests so they comply with `TX-AUDIT-02`.
8. `render.yaml` — Added Render persistent disk mount (`/var/data/kawad_swad`) and durable coordinator environment variables (`TRANSACTION_DB_PATH`, `KS_ERP_LOCK_DIR`, `KS_ERP_STATE_DIR`, `SALES_TX_LEASE_SECONDS`, `SALES_INSTANCE_COUNT=1`, `WEB_CONCURRENCY=1`).
9. `.env.example` — Documented coordinator durability and single-instance environment variables.

### Added Files
1. `backend/tests/test_mission51b1_round2_integrity.py` — 25 new Round 2 regression & failure-injection tests covering TX-AUDIT-01 Tests A–M, TX-AUDIT-02 Tests 1–14, and TX-AUDIT-03 hygiene verification.
2. `scripts/verify_package_hygiene.py` — Standalone ZIP structural integrity, forbidden-artifact hygiene, leaked-key scan, required-file, and SHA-256 verification script.
3. `docs/MISSION_51B1_ROUND2_REPAIR_REPORT.md` — This Round 2 engineering report (Deliverables A–H).
4. `docs/MISSION_51B1_ROUND2_README.md` — Concise Round 2 overview and verification runbook.

### Deleted Files
1. `public/assets/aistudio/Paste_November_21__2026_-_11_52PM_b5cb8f2f` (plus empty parent dirs `public/assets/aistudio/` and `public/assets/`) — Removed unused accidental AI Studio prompt attachment (`TX-AUDIT-03`).
2. `Kawad_Swad_Mission51B1_Audit_Package.zip` — Removed superseded Round 1 archive before generating clean Round 2 archive.

---

## Deliverable E — Verified Test Execution Report

| Verification Suite | Command | Result |
|---|---|---|
| Round 2 Integrity, Durability & Hygiene Suite | `python3 -m unittest backend/tests/test_mission51b1_round2_integrity.py -v` | **25/25 PASSED** (0 failed, 0 skipped, 1.22s) |
| Round 1 Transaction Safety Suite | `python3 -m unittest backend/tests/test_mission51b1_transaction_safety.py -v` | **21/21 PASSED** (0 failed, 0 skipped, 0.35s) |
| Startup Port-Bind & Resilience Suite | `python3 -m unittest backend/tests/test_startup_port_bind_and_resilience.py -v` | **11/12 PASSED, 1 SKIPPED** (uvicorn not installed in offline container; stdlib HTTP subprocess resilience test passed) |
| Complete Backend Test Discovery | `python3 -m unittest discover -s backend/tests -t backend` | **626 discovered: 625 PASSED, 0 FAILED, 0 ERRORS, 1 SKIPPED** (34.72s) |
| TypeScript Typecheck | `npx tsc --noEmit` | **PASSED (0 errors)** |
| Frontend Transaction Safety Tests | `npx --yes tsx scripts/test_mission51b1_frontend_transaction_safety.ts` | **5/5 PASSED** |
| Frontend Contract Tests | `npx --yes tsx scripts/test_phase1_6_frontend_contracts.ts` | **17/17 PASSED** |
| Production Frontend Build & Lint | `npm run build` & `npm run lint` | **PASSED (0 errors)** |

---

## Deliverable F — Failure-Injection Verification Matrix

### TX-AUDIT-01 (State Integrity Tests A–M)
- **Test A (`EXECUTING -> COMMITTED`):** Verified actual SQLite row `lifecycle_state=COMMITTED`, `previous_state=EXECUTING`, `version=2`, `lease_expires_at=NULL`, `lease_owner=NULL`. **PASS**
- **Test B (`COMMITTED -> FAILED`):** Tested across every `TransitionAuthority`; every attempt raised `InvalidStateTransitionError(code="TERMINAL_STATE_PROTECTED")`; DB row remained bit-for-bit identical. **PASS**
- **Test C (`COMMITTED -> EXECUTING`):** Rejected across all authorities; DB unchanged. **PASS**
- **Test D (`COMMITTED -> INITIATED/VALIDATING/PENDING/UNKNOWN/RECONCILED/COMMITTED`):** All 8 forbidden targets rejected; DB unchanged. **PASS**
- **Test E (`RECONCILED` immutability):** All `9 states × 5 authorities = 45` transitions rejected with `TERMINAL_STATE_IMMUTABLE`; `begin_governed_transaction` returns `ALREADY_COMMITTED`. **PASS**
- **Test F (`RECOVERY_REQUIRED` protection):** `begin_governed_transaction` returns `RECOVERY_CHECK_REQUIRED` (never `RETRY_ACQUIRED`); ordinary/retry transitions rejected; DB unchanged. **PASS**
- **Test G (Concurrent worker transitions):** Two threads raced `EXECUTING -> COMMITTED` vs `EXECUTING -> FAILED` across a `threading.Barrier(2)`; atomic CAS permitted exactly 1 winner (`version=2`) and rejected the loser. **PASS**
- **Test H (Stale worker late failure):** Stale worker with old `correlation_id` and `attempt_count=1` rejected both after newer worker committed AND while newer worker was executing (`STALE_WORKER_CORRELATION_MISMATCH`). **PASS**
- **Test I (CAS `expected_from_state` & `expected_version`):** Mismatched state (`CAS_STATE_MISMATCH`) and mismatched version (`CAS_VERSION_MISMATCH`) both rejected cleanly. **PASS**
- **Test J (Constrained `SECONDARY_QUARANTINE` & `RECONCILIATION`):** Missing authority, missing actor (`TRANSITION_ACTOR_REQUIRED`), and missing evidence (`TRANSITION_EVIDENCE_REQUIRED`) rejected; valid `SECONDARY_QUARANTINE` -> `RECOVERY_REQUIRED` -> Owner `RECONCILED` succeeded and recorded audit trail. **PASS**
- **Test K (Zero DB mutation on rejection):** Verified `message`, `error_code`, `allocated_id`, `version`, `updated_at`, and `steps_json` remained byte-for-byte identical after rejected overwrite. **PASS**
- **Test L (Repeated invalid transitions):** 15 repeated invalid attempts caused zero growth or corruption in `steps_json` and zero `version` increment. **PASS**
- **Test M (Terminal protection across restart):** Fresh `TransactionCoordinator` instance on same SQLite file rejected overwrites of both `COMMITTED` and `RECONCILED` rows. **PASS**

### TX-AUDIT-02 (Durability & Restart Tests 1–14)
- **Tests 1–5 (Restart persistence):** Fresh coordinator instance after restart preserved transaction state, idempotency replay (`ALREADY_COMMITTED`), payload hash conflict (`PAYLOAD_CONFLICT`), and terminal state protection. **PASS**
- **Test 6 (Stale lease recovery on restart):** Startup sweep automatically transitioned expired `EXECUTING` row to `UNKNOWN` (`STALE_EXECUTION_LEASE`) and cleared lease ownership. **PASS**
- **Test 7 (Missing production path):** `COORDINATOR_PATH_UNCONFIGURED` raised fail-closed. **PASS**
- **Test 8 (Unavailable directory):** Startup raised `COORDINATOR_DIRECTORY_UNAVAILABLE`; runtime vanished directory blocked `execute_governed_write()` with HTTP 503 and **0 gateway POSTs**. **PASS**
- **Test 9 (Misconfigured path & multi-instance):** `instance_count=2` raised `COORDINATOR_MULTI_INSTANCE_UNSUPPORTED`; `assert_runtime_config()` failed closed on volatile `/tmp` in production; read-only dir checked fail-closed. **PASS**
- **Test 10 (Volatile `/tmp` / `:memory:` in production):** All 4 volatile paths rejected with `COORDINATOR_VOLATILE_PATH_IN_PRODUCTION`. **PASS**
- **Test 11 (Two separate OS processes via `multiprocessing` spawn):** Concurrent acquisition and concurrent CAS transition across 2 OS processes permitted exactly 1 winner each. **PASS**
- **Test 12 (Bridge-level stale worker resume):** Slow Worker 1 woke up after lease expiry and Worker 2's commit; bridge rejected Worker 1 cleanly (HTTP 409) and DB stayed `COMMITTED` with Worker 2's `JV-WINNER-12`. **PASS**
- **Tests 13–14 (Coordinator DB loss + Sheets recovery):** Deleted SQLite `.db`/`.db-wal`/`.db-shm` files completely; retrying same nonce inspected `IdAllocations` and recovered `CONFIRMED` (`AUTO_CONFIRMED_FROM_SHEETS`) with **0 duplicate POSTs**; orphan allocation quarantined to `RECOVERY_REQUIRED` (HTTP 409) with **0 duplicate POSTs**. **PASS**

---

## Deliverable G — Remaining Risks & External Dependencies (Honest Status)

1. **`DB-008` — External Apps Script LockService & Staging Verification (`BLOCKED_PENDING_STAGING`):** The Google Apps Script Web App source and live Google Sheets workbook are external to this repository and were not modified or executed in this mission. Cross-tab Google Sheets write atomicity and multi-host distributed locking remain dependent on deploying and staging-verifying Apps Script `LockService` + idempotency ledger.
2. **Single-Host Coordinator Topology:** Host-local SQLite WAL on Render persistent disk (`/var/data/kawad_swad`) guarantees crash/restart persistence and cross-process ACID safety ONLY for single-instance deployment (`WEB_CONCURRENCY=1`, `SALES_INSTANCE_COUNT=1`). Scaling horizontally to >1 Render instance is intentionally blocked fail-closed until a shared external coordinator or verified Apps Script distributed lock is deployed.
3. **Offline Container ASGI Runtime:** Full Uvicorn ASGI subprocess test (`test_uvicorn_binds_and_serves_health_within_3s_when_sheets_hangs_over_5s`) is skipped only when `uvicorn`/`fastapi` are not installed (pip-less container); the deterministic stdlib HTTP subprocess test passes in all environments, and the Uvicorn test will pass once `pip install -r backend/requirements.txt` is present.

---

## Deliverable H — Package Integrity & Verification Procedure (`TX-AUDIT-03`)

To prevent self-referential SHA-256 staleness (embedding an archive's own hash inside a file archived within the same ZIP), the final Round 2 archive `Kawad_Swad_Mission51B1_Round2_Audit_Package.zip` is generated **after** this report and all source/test changes are finalized, and verified immediately afterward using:

```bash
python3 scripts/verify_package_hygiene.py Kawad_Swad_Mission51B1_Round2_Audit_Package.zip
```

The exact finalized archive name, byte size, file count, UTC timestamp, `testzip()=None` verification, and final SHA-256 digest are reported verbatim in the Mission 51B-1 Round 2 delivery summary (Section 15) and must never be mutated after hash calculation.
