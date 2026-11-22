# Kawad Swad ERP — Mission 51B-1 Repair Round 3 README

## What Was Fixed in Round 3

1. **`TX-AUDIT-04` — Unconditional Worker Identity & Lease Enforcement:**
   - Closed the Round 2 critical bypass where an ordinary `EXECUTING -> COMMITTED` (or any other `requires_lease_owner=True` ordinary transition) bypassed lease ownership and expiration checks if `expected_correlation_id` was omitted.
   - `TransactionCoordinator.transition_governed_transaction` now unconditionally requires non-empty `expected_correlation_id`, explicit non-bool integer `expected_attempt`, and explicit non-bool integer `expected_version` for every `ORDINARY` transition whose `LEGAL_TRANSITION_MATRIX` rule has `requires_lease_owner=True` (all 9 rules).
   - Verifies non-null `lease_owner == expected_correlation_id`, `correlation_id == expected_correlation_id`, `attempt_count == expected_attempt`, `version == expected_version`, and non-null valid unexpired `lease_expires_at` (`now_utc < lease_expires_at`).
   - Guards the atomic SQL `UPDATE` inside `BEGIN IMMEDIATE` on all 7 columns (`nonce`, `lifecycle_state`, `version`, `correlation_id`, `lease_owner`, `attempt_count`, `lease_expires_at`) and rolls back with zero DB mutation on any violation.
   - Migrated `_worker_cas_transition` in `backend/app/apps_script_bridge.py` and legitimate test setup callers to supply explicit `expected_version`.
   - Preserved `RECOVERY`, `SECONDARY_QUARANTINE`, and `RECONCILIATION` authority paths under their evidence-based matrix rules.

2. **`TX-AUDIT-05` — Direct Coordinator Failure-Injection Tests (Cases A–Q):**
   - Added `backend/tests/test_mission51b1_round3_lease_enforcement.py` (18 SQLite-backed tests) verifying Cases A through Q, byte-for-byte 16-column zero-mutation guarantees on every rejection, threaded + cross-process (`multiprocessing`) CAS races, and all 9 ordinary lease-protected matrix rules.

3. **`TX-AUDIT-06` — Exact Final Release Archive Identity:**
   - Updated `scripts/verify_package_hygiene.py` to enforce `REQUIRED_ROUND3_FILES` and `ROOT_LAYOUT=REPOSITORY_ROOT` (no outer wrapper directory).
   - Built one clean repository-root archive (`Kawad_Swad_Mission51B1_Round3_Audit_Package.zip`), verified and hashed strictly after finalization, and never modified afterward.

---

## Independent Verification Commands

```bash
# 1. Mission 51B-1 Round 3 lease enforcement suite — Cases A–Q + 9-rule matrix sweep (18 tests)
python3 -m unittest backend/tests/test_mission51b1_round3_lease_enforcement.py -v

# 2. Mission 51B-1 Round 2 state-integrity, durability, restart & hygiene suite (25 tests)
python3 -m unittest backend/tests/test_mission51b1_round2_integrity.py -v

# 3. Mission 51B-1 Round 1 transaction safety suite (21 tests)
python3 -m unittest backend/tests/test_mission51b1_transaction_safety.py -v

# 4. Complete backend regression suite (644 discovered tests)
python3 -m unittest discover -s backend/tests -t backend

# 5. Frontend typecheck, transaction safety & contract checks
npx tsc --noEmit
npx --yes tsx scripts/test_mission51b1_frontend_transaction_safety.ts
npx --yes tsx scripts/test_phase1_6_frontend_contracts.ts

# 6. Frontend production build & lint
npm run build
npm run lint

# 7. Verify finalized release archive integrity, repository-root layout, hygiene & SHA-256
python3 scripts/verify_package_hygiene.py Kawad_Swad_Mission51B1_Round3_Audit_Package.zip
```

## Detailed Engineering Report

See `docs/MISSION_51B1_ROUND3_REPAIR_REPORT.md` for complete Sections A through N (defect reproduction, root cause, repair design, changed files, caller migration inventory, enforcement rules, test matrix A–Q, verification results, and honest gate verdict).
