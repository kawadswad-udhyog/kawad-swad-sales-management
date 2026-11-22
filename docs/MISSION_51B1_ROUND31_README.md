# Kawad Swad ERP — Mission 51B-1 Repair Round 3.1 README

## What Was Completed in Round 3.1

1. **`TX-AUDIT-07` — Regression Fixture Compatibility (Zero Weakening of Production Durability Rules):**
   - Added `backend/tests/_durability_test_helpers.py` (`make_nonvolatile_test_dir`, `nonexistent_nonvolatile_db_path`) so production durability tests (`test_mission51b1_round2_integrity.py` tests 08 & 09) and startup resilience subprocess tests (`test_startup_port_bind_and_resilience.py`) use genuinely non-volatile isolated directories even when the release archive is extracted under `/tmp/...`.
   - Production durability validation in `backend/app/transaction_safety.py` remains 100% strict: `/tmp`, `/var/tmp`, `/dev/shm`, `tempfile.gettempdir()`, and `:memory:` are ALWAYS rejected with `COORDINATOR_VOLATILE_PATH_IN_PRODUCTION` and result in 0 gateway writes.

2. **`TX-AUDIT-08` — Strict Type Validation for Transaction Identity Parameters:**
   - Replaced all `int(expected_version)` / `int(expected_attempt)` coercions in `backend/app/accounting/transaction_coordinator.py` with `_validate_strict_identity_int`, accepting ONLY genuine built-in positive integers (`type(v) is int and v >= 1`).
   - Strictly rejects `bool` (`True`/`False`), numeric strings (`"1"`, `"5"`, `"10"`), floats including integral floats (`1.0`, `5.0`, `10.0`, `NaN`, `±Inf`), `Decimal`, `None` when mandatory, and negative/zero values (`-1`, `0`) BEFORE any database mutation.

3. **`TX-AUDIT-04` & `TX-AUDIT-05` — Complete Failure-Injection Matrix (Cases A–Z):**
   - Preserved all 18 Round 3 lease-enforcement tests (Cases A–Q + 9-rule matrix sweep).
   - Added `backend/tests/test_mission51b1_round31_repairs.py` (11 tests covering Cases R–Z, 17-column byte-for-byte zero-mutation audits, TX-AUDIT-07 fixture/volatile checks, and TX-AUDIT-06 wrapper-folder rejection).

4. **`TX-AUDIT-06` — Exact Final Repository-Root Archive Identity:**
   - Updated `scripts/verify_package_hygiene.py` to enforce `REQUIRED_ROUND31_FILES` and `ROOT_LAYOUT=REPOSITORY_ROOT` (rejecting outer wrapper folders).
   - Built ONE finalized repository-root archive (`Kawad_Swad_Mission51B1_Round31_Audit_Package.zip`), verified and hashed strictly after finalization, and never modified afterward.

---

## Independent Verification Commands

```bash
# 1. Round 3.1 strict type validation, Cases R–Z, fixture & packaging suite (11 tests)
python3 -m unittest backend/tests/test_mission51b1_round31_repairs.py -v

# 2. Round 3 dedicated lease enforcement suite — Cases A–Q + 9-rule matrix sweep (18 tests)
python3 -m unittest backend/tests/test_mission51b1_round3_lease_enforcement.py -v

# 3. Round 2 state-integrity, durability, restart & hygiene suite (25 tests)
python3 -m unittest backend/tests/test_mission51b1_round2_integrity.py -v

# 4. Round 1 transaction safety suite (21 tests)
python3 -m unittest backend/tests/test_mission51b1_transaction_safety.py -v

# 5. Startup & resilience suite (12 tests; 11 pass + 1 uvicorn env skip if uvicorn absent)
python3 -m unittest backend/tests/test_startup_port_bind_and_resilience.py -v

# 6. Complete backend regression suite (655 discovered tests)
python3 -m unittest discover -s backend/tests -t backend

# 7. Frontend typecheck, transaction safety & contract checks
npx tsc --noEmit
npx --yes tsx scripts/test_mission51b1_frontend_transaction_safety.ts
npx --yes tsx scripts/test_phase1_6_frontend_contracts.ts

# 8. Frontend production build & lint
npm run build
npm run lint

# 9. Verify exact finalized release archive integrity, root layout, hygiene & SHA-256
python3 scripts/verify_package_hygiene.py Kawad_Swad_Mission51B1_Round31_Audit_Package.zip
sha256sum Kawad_Swad_Mission51B1_Round31_Audit_Package.zip
```

## Detailed Engineering Report

See `docs/MISSION_51B1_ROUND31_REPAIR_REPORT.md` for complete Sections A through O.
