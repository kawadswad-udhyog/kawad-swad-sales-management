# Kawad Swad ERP — Mission 51B-1 Repair Round 3 Engineering Report

**Scope:** Targeted repair of `TX-AUDIT-04` (Critical Lease Enforcement Bypass), `TX-AUDIT-05` (Direct Coordinator Failure-Injection Tests A–Q), and `TX-AUDIT-06` (Exact Final Release Archive Identity).
**Date:** 2026-11-21
**Baseline:** Mission 51B-1 Repair Round 2 repository source.
**Boundary:** No Mission 51B-2+ work, no live Google Sheets or Apps Script modifications, no Render deployment, no GitHub push, no accounting-logic refactoring, and zero weakened or deleted tests.

---

## Section A — Defect Reproduction (Pre-Fix vs Post-Fix)

### Independent Audit Defect (`TX-AUDIT-04`)
In Mission 51B-1 Round 2, an ordinary `EXECUTING -> COMMITTED` transition bypassed both lease ownership and lease expiration checks whenever the caller omitted `expected_correlation_id` (and/or `expected_attempt` / `expected_version`).

### Exact Reproduction Steps
1. Call `begin_governed_transaction(nonce="NONCE-REPRO-R3", ..., correlation_id="WORKER-1")` -> row enters `EXECUTING` with `lease_owner="WORKER-1"`, `version=1`, `attempt_count=1`.
2. Force `lease_expires_at` 120 seconds into the past via SQL `UPDATE governed_transactions SET lease_expires_at = ? WHERE nonce = ?`.
3. Call:
   ```python
   transition_governed_transaction(
       nonce="NONCE-REPRO-R3",
       lifecycle_state="COMMITTED",
       bridge_status="CONFIRMED",
       allocated_id="TEST-1",
       authority="ORDINARY",
   )
   ```

### Pre-Fix Observed Output (Round 2 Baseline)
```text
STEP1_BEGIN= ACQUIRED STATE= EXECUTING LEASE_OWNER= WORKER-1 VER= 1
REPRODUCED_BYPASS_STATE= COMMITTED ALLOCATED_ID= TEST-1 VERSION= 2
```
The expired transaction illegally transitioned to `COMMITTED`, wrote `allocated_id="TEST-1"`, and incremented `version` to `2`.

### Post-Fix Observed Output (Round 3 Repaired)
```text
STEP1_BEGIN= ACQUIRED STATE= EXECUTING LEASE_OWNER= WORKER-1 VER= 1
POSTFIX_REJECTED_CODE= MISSING_WORKER_CORRELATION_ID
POSTFIX_DB_STATE= EXECUTING ALLOCATED_ID= None VERSION= 1
```
Even when valid worker identity (`expected_correlation_id="WORKER-1"`, `expected_attempt=1`, `expected_version=1`) IS supplied against an expired lease, the coordinator rejects with `STALE_LEASE_EXPIRED` and leaves all 16 persisted columns byte-for-byte unchanged (verified in Case E).

---

## Section B — Root Cause Analysis

In Round 2 `backend/app/accounting/transaction_coordinator.py` (Step 4 of `transition_governed_transaction`), lease-owner and expiration checks were gated behind optional caller arguments and truthiness guards:
1. **Optional Caller Identity Gate:** `if clean_exp_corr is not None:` skipped `correlation_id`, `lease_owner`, and `lease_expires_at` checks entirely whenever `expected_correlation_id` was omitted or blank.
2. **Nullable DB Column Bypass:** `if rule.requires_lease_owner and current_lease_owner and ...` silently bypassed lease-owner validation whenever persisted `lease_owner` was `NULL` or empty; similarly, `if lease_dt is not None and now_dt >= lease_dt:` silently bypassed expiration whenever `lease_expires_at` was `NULL`, blank, or unparseable.
3. **Optional Attempt / Version CAS:** `expected_attempt` and `expected_version` were optional for ordinary lease-protected transitions, so the SQL `UPDATE ... WHERE` clause did not unconditionally bind `correlation_id`, `lease_owner`, `attempt_count`, and `lease_expires_at`.

---

## Section C — Repair Design (`TX-AUDIT-04`)

In `backend/app/accounting/transaction_coordinator.py` (`TransactionCoordinator.transition_governed_transaction`):
1. **Unconditional Detection:** Compute `is_ordinary_lease_transition = bool(rule.requires_lease_owner and auth_enum == TransitionAuthority.ORDINARY)` directly from the authoritative `LEGAL_TRANSITION_MATRIX` rule (covering all 9 ordinary lease-protected transitions).
2. **Fail-Closed Mandatory Arguments (Never Silently Defaulted):**
   - Non-empty `expected_correlation_id` -> else `ROLLBACK` + `InvalidStateTransitionError(code="MISSING_WORKER_CORRELATION_ID")`.
   - Explicit non-bool integer `expected_attempt` -> else `ROLLBACK` + `InvalidStateTransitionError(code="MISSING_WORKER_ATTEMPT")`.
   - Explicit non-bool integer `expected_version` -> else `ROLLBACK` + `InvalidStateTransitionError(code="MISSING_EXPECTED_VERSION")`.
   - Non-integer cast errors -> `ROLLBACK` + `InvalidStateTransitionError(code="INVALID_WORKER_IDENTITY_ARGUMENT")`.
3. **Strict Persisted Row & Active Lease Invariants:**
   - Persisted `correlation_id` must be non-empty and equal `expected_correlation_id` -> else `STALE_WORKER_CORRELATION_MISMATCH`.
   - Persisted `lease_owner` must be non-null/non-empty -> else `MISSING_ACTIVE_LEASE_OWNER`.
   - Persisted `lease_owner` must equal `expected_correlation_id` -> else `STALE_LEASE_OWNER`.
   - Persisted `attempt_count` must equal `expected_attempt` -> else `STALE_WORKER_ATTEMPT_MISMATCH`.
   - Persisted `version` must equal `expected_version` -> else `CAS_VERSION_MISMATCH`.
   - Persisted `lease_expires_at` must be non-null, non-empty, valid ISO-8601 UTC -> else `MISSING_OR_INVALID_LEASE_EXPIRATION`.
   - Current UTC time must be strictly less than `lease_expires_at` (`now_dt < lease_dt`) -> else `STALE_LEASE_EXPIRED`.
4. **Full-Row Atomic SQL CAS:** For `is_ordinary_lease_transition`, the single `UPDATE governed_transactions` executes inside `BEGIN IMMEDIATE` with:
   ```sql
   WHERE nonce = ?
     AND lifecycle_state = ?
     AND version = ?
     AND correlation_id = ?
     AND lease_owner = ?
     AND attempt_count = ?
     AND lease_expires_at = ?
   ```
   If `cur.rowcount != 1`, the transaction immediately executes `ROLLBACK;` and raises `CAS_ATOMIC_CONFLICT`.
5. **Non-Ordinary Authorities Preserved:** `RECOVERY`, `SECONDARY_QUARANTINE`, and `RECONCILIATION` continue to operate under their evidence/actor rules in `LEGAL_TRANSITION_MATRIX` without ordinary active-lease requirements, while still enforcing any explicitly supplied `expected_version`, `expected_correlation_id`, or `expected_attempt` CAS predicates.

---

## Section D — Changed Files Manifest

| File | Action | Purpose |
|---|---|---|
| `backend/app/accounting/transaction_coordinator.py` | Modified | Enforced unconditional worker identity (`expected_correlation_id`, `expected_attempt`, `expected_version`), active non-null lease ownership/expiration, strict type guards, and full atomic SQL CAS for ordinary lease-protected transitions (`TX-AUDIT-04`). |
| `backend/app/apps_script_bridge.py` | Modified | Captured `expected_ver = int(tx_rec.get("version") or 1)` from `begin_governed_transaction` and forwarded `expected_version=expected_ver` in `_worker_cas_transition`. |
| `backend/tests/test_mission51b1_transaction_safety.py` | Modified | Migrated 1 legitimate `ORDINARY` setup call in `test_d4_controlled_reconciliation_and_confidential_redaction` to pass explicit `expected_from_state`, `expected_version`, `expected_correlation_id`, and `expected_attempt`. |
| `backend/tests/test_mission51b1_round2_integrity.py` | Modified | Migrated 12 legitimate `ORDINARY` setup calls (plus `tx_h2_new["version"]` in `test_h` stale-worker isolation check) to supply explicit `expected_version`; zero assertions weakened or removed. |
| `backend/tests/test_mission51b1_round3_lease_enforcement.py` | Created | Dedicated SQLite-backed Round 3 test suite covering all mandatory Cases A–Q (`TX-AUDIT-05`) and all 9 `requires_lease_owner=True` matrix rules (18 tests). |
| `scripts/verify_package_hygiene.py` | Modified | Added `REQUIRED_ROUND3_FILES`, explicit repository-root layout verification (`ROOT_LAYOUT=REPOSITORY_ROOT`, rejecting wrapped outer folders), while preserving backward compatibility for Round 2 unit tests. |
| `docs/MISSION_51B1_ROUND3_REPAIR_REPORT.md` | Created | Complete Round 3 engineering report (Sections A–N). |
| `docs/MISSION_51B1_ROUND3_README.md` | Created | Concise Round 3 summary and independent verification commands. |

---

## Section E — Exhaustive Caller Migration Inventory

Complete repository scan (`grep -rn "transition_governed_transaction" backend/app --exclude-dir=__pycache__`):

| Caller Location | Function / Path | Authority | Migration Status |
|---|---|---|---|
| `backend/app/accounting/transaction_coordinator.py:1215` | `mark_transaction_reconciled` | `RECONCILIATION` | Unchanged (non-ordinary; passes actor + reason + evidence) |
| `backend/app/routers/sales.py:575` | `create_sale` secondary journal quarantine | `SECONDARY_QUARANTINE` | Unchanged (non-ordinary; passes actor + reason + evidence) |
| `backend/app/routers/sales.py:1272` | `create_sale_return` secondary journal quarantine | `SECONDARY_QUARANTINE` | Unchanged (non-ordinary; passes actor + reason + evidence) |
| `backend/app/apps_script_bridge.py:1364` | `recover_transaction` (confirmed) | `RECOVERY` | Unchanged (non-ordinary; passes actor + reason + evidence) |
| `backend/app/apps_script_bridge.py:1441` | `recover_transaction` (quarantine partial) | `RECOVERY` | Unchanged (non-ordinary; passes actor + reason + evidence) |
| `backend/app/apps_script_bridge.py:1491` | `recover_transaction` (quarantine orphan) | `RECOVERY` | Unchanged (non-ordinary; passes actor + reason + evidence) |
| `backend/app/apps_script_bridge.py:1551` | `recover_transaction` (confirmed absent -> `PENDING`) | `RECOVERY` | Unchanged (non-ordinary; passes actor + reason + evidence) |
| `backend/app/apps_script_bridge.py:1644` | `recover_transaction` (unknown fallback) | `RECOVERY` | Unchanged (non-ordinary; passes actor + reason + evidence) |
| `backend/app/apps_script_bridge.py:2283` | `execute_governed_write` -> `_worker_cas_transition` | `ORDINARY` | **Migrated**: now passes `expected_from_state=EXECUTING`, `expected_version=expected_ver`, `expected_correlation_id=correlation_id`, `expected_attempt=expected_attempt` |
| `backend/tests/test_mission51b1_transaction_safety.py:996` | `test_d4_controlled_reconciliation_and_confidential_redaction` | `ORDINARY` | **Migrated**: supplies `expected_from_state`, `expected_version`, `expected_correlation_id`, `expected_attempt` |
| `backend/tests/test_mission51b1_round2_integrity.py` (13 sites) | Legitimate setup transitions in `_mp_worker_race_acquire`, `test_b..f`, `test_h`, `test_j..m`, `test_01_to_05` | `ORDINARY` | **Migrated**: supplies explicit `expected_version` |

---

## Section F — Mandatory Worker Identity & Lease Enforcement Rules

Applies unconditionally whenever `rule.requires_lease_owner == True` AND `authority == TransitionAuthority.ORDINARY` (all 9 ordinary lease-protected matrix edges: `INITIATED -> VALIDATING`, `INITIATED -> EXECUTING`, `INITIATED -> FAILED`, `VALIDATING -> EXECUTING`, `VALIDATING -> FAILED`, `EXECUTING -> COMMITTED`, `EXECUTING -> FAILED`, `EXECUTING -> UNKNOWN`, `EXECUTING -> RECOVERY_REQUIRED`):

| Check | Enforcement Condition | Rejection Code | DB Mutation |
|---|---|---|---|
| 1 | `expected_correlation_id` non-null & non-blank string | `MISSING_WORKER_CORRELATION_ID` | Zero (ROLLBACK) |
| 2 | `expected_attempt` explicit non-bool integer | `MISSING_WORKER_ATTEMPT` / `INVALID_WORKER_IDENTITY_ARGUMENT` | Zero (ROLLBACK) |
| 3 | `expected_version` explicit non-bool integer | `MISSING_EXPECTED_VERSION` / `INVALID_WORKER_IDENTITY_ARGUMENT` | Zero (ROLLBACK) |
| 4 | Persisted `correlation_id == expected_correlation_id` | `STALE_WORKER_CORRELATION_MISMATCH` | Zero (ROLLBACK) |
| 5 | Persisted `lease_owner` non-null & non-empty | `MISSING_ACTIVE_LEASE_OWNER` | Zero (ROLLBACK) |
| 6 | Persisted `lease_owner == expected_correlation_id` | `STALE_LEASE_OWNER` | Zero (ROLLBACK) |
| 7 | Persisted `attempt_count == expected_attempt` | `STALE_WORKER_ATTEMPT_MISMATCH` | Zero (ROLLBACK) |
| 8 | Persisted `version == expected_version` | `CAS_VERSION_MISMATCH` | Zero (ROLLBACK) |
| 9 | Persisted `lease_expires_at` non-null, valid ISO-8601 UTC | `MISSING_OR_INVALID_LEASE_EXPIRATION` | Zero (ROLLBACK) |
| 10 | `now_utc < lease_expires_at` (strictly unexpired) | `STALE_LEASE_EXPIRED` | Zero (ROLLBACK) |
| 11 | Atomic SQL `UPDATE ... WHERE` matches all 7 CAS columns (`rowcount == 1`) | `CAS_ATOMIC_CONFLICT` | Zero (ROLLBACK) |

---

## Section G — Direct Coordinator Failure-Injection Test Matrix (`TX-AUDIT-05`, Cases A–Q)

All 18 tests in `backend/tests/test_mission51b1_round3_lease_enforcement.py` execute directly against real persisted SQLite rows (`sqlite3.connect(self.db_path)`):

| Case | Test Method | Verified Behavior | Result |
|---|---|---|---|
| A | `test_case_a_valid_current_worker_succeeds` | Valid worker with matching `correlation_id`, `lease_owner`, `attempt_count`, `version`, and unexpired `lease_expires_at` commits cleanly (`version=2`, leases cleared). | PASS |
| B | `test_case_b_missing_expected_correlation_id_rejected` | `None`, `""`, whitespace, and exact verbatim Round 2 expired-lease bypass repro rejected (`MISSING_WORKER_CORRELATION_ID`), 16 cols untouched. | PASS |
| C | `test_case_c_missing_expected_attempt_rejected` | `None`, `True`, `False` rejected (`MISSING_WORKER_ATTEMPT`), 16 cols untouched. | PASS |
| D | `test_case_d_missing_expected_version_rejected` | `None`, `True`, `False` rejected (`MISSING_EXPECTED_VERSION`), 16 cols untouched. | PASS |
| E | `test_case_e_expired_lease_rejected_even_with_valid_worker_identity` | Expired `lease_expires_at` rejected (`STALE_LEASE_EXPIRED`) across `COMMITTED`/`FAILED`/`UNKNOWN` even with valid worker identity, 16 cols untouched. | PASS |
| F | `test_case_f_wrong_worker_rejected` | `WORKER-2` against `WORKER-1` lease rejected (`STALE_WORKER_CORRELATION_MISMATCH`), 16 cols untouched. | PASS |
| G | `test_case_g_correlation_id_mismatch_rejected` | Skewed DB `correlation_id` rejected (`STALE_WORKER_CORRELATION_MISMATCH`) even when `lease_owner` matches caller, 16 cols untouched. | PASS |
| H | `test_case_h_lease_owner_mismatch_rejected` | Skewed DB `lease_owner` rejected (`STALE_LEASE_OWNER`) even when `correlation_id` matches caller, 16 cols untouched. | PASS |
| I | `test_case_i_null_and_empty_lease_owner_rejected` | `NULL`, `""`, `"   "` `lease_owner` rejected (`MISSING_ACTIVE_LEASE_OWNER`), 16 cols untouched. | PASS |
| J | `test_case_j_null_and_malformed_lease_expires_at_rejected` | `NULL`, `""`, `"   "`, `"NOT-A-TIMESTAMP"` rejected (`MISSING_OR_INVALID_LEASE_EXPIRATION`), 16 cols untouched. | PASS |
| K | `test_case_k_wrong_expected_attempt_rejected` | Wrong `expected_attempt=2` vs persisted `1` rejected (`STALE_WORKER_ATTEMPT_MISMATCH`), 16 cols untouched. | PASS |
| L | `test_case_l_wrong_expected_version_rejected` | Wrong `expected_version=99` vs persisted `1` rejected (`CAS_VERSION_MISMATCH`), 16 cols untouched. | PASS |
| M | `test_case_m_stale_worker_after_retry_rejected_worker2_untouched` | Stale Worker 1 after expiry + Worker 2 retry rejected; Worker 2's full 16-col active lease row untouched. | PASS |
| N | `test_case_n_stale_worker_after_commit_rejected` | Stale Worker 1 after Worker 2 commit rejected across `FAILED`/`UNKNOWN`/`COMMITTED`; Worker 2's `COMMITTED` row untouched. | PASS |
| O | `test_case_o_all_16_columns_strictly_immutable_on_every_rejection_vector` | Explicit 16-column byte-for-byte immutability check across 9 poisoned rejection vectors (`lifecycle_state`, `previous_state`, `last_authority`, `bridge_status`, `failure_category`, `error_code`, `allocated_id`, `correlation_id`, `attempt_count`, `version`, `lease_owner`, `lease_expires_at`, `steps_json`, `message`, `recovery_decision`, `updated_at`). | PASS |
| P | `test_case_p_concurrent_race_valid_vs_stale_and_expired_workers` | Threaded (`Barrier`) valid-vs-stale (1 valid winner), threaded expired race (0 winners, 0 mutations), and cross-process (`multiprocessing` spawn) valid-vs-stale (valid OS process wins). | PASS |
| Q | `test_case_q_legitimate_recovery_quarantine_and_reconciliation_still_work` | `RECOVERY` (`EXECUTING -> UNKNOWN -> COMMITTED` on expired lease), `SECONDARY_QUARANTINE` (`COMMITTED -> RECOVERY_REQUIRED`), and `RECONCILIATION` (`RECOVERY_REQUIRED -> RECONCILED`) all succeed cleanly. | PASS |
| Matrix | `test_all_requires_lease_owner_rules_enforce_mandatory_identity_under_ordinary` | Verifies all 9 `requires_lease_owner=True` ordinary rules reject omitted worker identity with zero DB mutation. | PASS |

---

## Section H — Targeted Mission 51B-1 Suite Results

| Suite | Command | Result |
|---|---|---|
| Round 3 Lease Enforcement | `python3 -m unittest backend/tests/test_mission51b1_round3_lease_enforcement.py -v` | **18 / 18 PASSED** (1.667s) |
| Round 2 Integrity & Durability | `python3 -m unittest backend/tests/test_mission51b1_round2_integrity.py -v` | **25 / 25 PASSED** (1.745s) |
| Round 1 Transaction Safety | `python3 -m unittest backend/tests/test_mission51b1_transaction_safety.py -v` | **21 / 21 PASSED** (0.585s) |

---

## Section I — Full Backend Regression Results

- **Command:** `python3 -m unittest discover -s backend/tests -t backend`
- **Result:** `Ran 644 tests in 55.292s — OK (skipped=1)`
  - Passed: **643**
  - Failed: **0**
  - Errors: **0**
  - Skipped: **1** (`test_uvicorn_binds_and_serves_health_within_3s_when_sheets_hangs_over_5s` — skipped in pip-less container because `uvicorn` is not installed; runs normally when `uvicorn` is installed via `requirements.txt`).

---

## Section J — Frontend Verification Results

| Check | Command | Result |
|---|---|---|
| Frontend Transaction Safety | `npx --yes tsx scripts/test_mission51b1_frontend_transaction_safety.ts` | **5 / 5 PASSED** |
| Frontend Contracts | `npx --yes tsx scripts/test_phase1_6_frontend_contracts.ts` | **17 / 17 PASSED** |
| TypeScript Typecheck | `npx tsc --noEmit` | **PASS (0 errors)** |
| Frontend Production Build | `npm run build` (`compile_applet`) | **PASS** |
| Frontend Lint | `npm run lint` (`lint_applet`) | **PASS** |

---

## Section K — Package Hygiene Verification

The release packaging workflow enforces:
1. Clean repository-root archive layout (`backend/`, `src/`, `docs/`, `scripts/`, `render.yaml`, `.env.example`, `package.json` directly at archive root — zero outer wrapper folder).
2. Complete exclusion of `node_modules/`, `dist/`, `__pycache__/`, `*.pyc`, `.git/`, `.aistudio/`, `.env` (non-example), `*.db*`, `*.sqlite*`, nested `*.zip`, and `public/assets/aistudio/Paste_*`.
3. Automated independent audit via `python3 scripts/verify_package_hygiene.py Kawad_Swad_Mission51B1_Round3_Audit_Package.zip` verifying `TESTZIP_BAD_MEMBER=None`, `ROOT_LAYOUT=REPOSITORY_ROOT`, all Round 2 + Round 3 required files present, zero leaked private keys, and `STATUS=PASS`.

---

## Section L — Exact Final Archive Identity (`TX-AUDIT-06`)

To avoid cryptographic self-reference (never modifying an archive after computing its SHA-256), `Kawad_Swad_Mission51B1_Round3_Audit_Package.zip` is generated **strictly after** this document is written, verified once via `python3 scripts/verify_package_hygiene.py Kawad_Swad_Mission51B1_Round3_Audit_Package.zip`, and **never modified afterward**. The exact post-finalization archive filename, file count, byte size, UTC timestamp, `testzip()` result, `ROOT_LAYOUT`, hygiene status, and SHA-256 digest are reported verbatim in the Round 3 delivery output and can be independently reproduced at any time by running:

```bash
python3 scripts/verify_package_hygiene.py Kawad_Swad_Mission51B1_Round3_Audit_Package.zip
```

---

## Section M — Known Limitations & External Dependencies

1. **External Apps Script / Live Google Sheets (`DB-008` / Staging):** Live Apps Script gateway updates and real Google Sheets staging transactions remain explicitly out-of-scope for this GitHub repository repair mission (`BLOCKED_PENDING_STAGING`).
2. **Container `uvicorn` Skip:** 1 of 644 backend tests (`test_uvicorn_binds_and_serves_health_within_3s_when_sheets_hangs_over_5s`) is skipped in the pip-less sandbox environment because `uvicorn` is absent; it executes in standard environments with `requirements.txt` installed.
3. **Single-Host Coordinator Topology:** As documented in Round 2, SQLite WAL coordinator durability requires single-instance deployment (`WEB_CONCURRENCY=1`, `SALES_INSTANCE_COUNT=1`) backed by Render persistent disk (`/var/data/kawad_swad`); horizontal scaling requires a shared database coordinator in a future phase.

---

## Section N — Mission Gate Verdict

| Gate | Verdict | Justification |
|---|---|---|
| **Round 3 Repair Scope (`TX-AUDIT-04`, `TX-AUDIT-05`, `TX-AUDIT-06`)** | **PASS** | Lease-enforcement bypass eliminated unconditionally for all 9 ordinary lease-protected matrix transitions; all 18 Round 3 tests (Cases A–Q + matrix sweep), 25 Round 2 tests, 21 Round 1 tests, 643/644 full backend tests (1 env skip, 0 failures), 22 frontend tests, `tsc`, build, lint, and repository-root package hygiene audit pass. |
| **Overall Mission 51B-1 Production Deployment Gate** | **CONDITIONAL** | External Apps Script `DB-008` deployment and live Google Sheets staging verification remain outside repository scope (`BLOCKED_PENDING_STAGING`); production cutover requires Owner staging validation on Render persistent disk + live Apps Script gateway. |
