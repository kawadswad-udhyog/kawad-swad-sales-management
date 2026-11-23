# MISSION 1.9R-1: FULL REGRESSION REPORT

**Baseline:** ZIP61 (`672` backend tests: `671 PASS, 1 SKIP, 0 FAIL`)  
**Post-Repair Suite:** `684` backend tests (`+12` new Mission 1.9R-1 tests)

---

## 1. Full Backend Regression Execution

**Command Executed:**
```bash
PYTHONDONTWRITEBYTECODE=1 SALES_TESTING=1 python3 -B -m unittest discover -s backend/tests -t backend
```

**Observed Result:**
- **Tests Discovered & Run:** `684` (across `64` test modules)
- **Passed:** `683`
- **Failed:** `0`
- **Errors:** `0`
- **Skipped:** `1` (pre-existing environment skip: `test_uvicorn_binds_and_serves_health_within_3s_when_sheets_hangs_over_5s` in `backend/tests/test_startup_port_bind_and_resilience.py` because `uvicorn`/`fastapi` are not installed in the local Python environment)
- **Duration:** `36.441s`

---

## 2. Existing Test Integrity & Modification Audit

- **Existing Tests Deleted:** `0`
- **Existing Tests Weakened or Skipped:** `0`
- **Existing Tests Modified:** `0`

### Notable Regression Discovery Caught & Resolved During Implementation
- During initial full-suite execution, implementing `SheetsDatabase.allow_in_memory_fallback` as a `@property` descriptor caused `unittest.mock.patch.object(sheets_mod.db, "allow_in_memory_fallback", False)` in `backend/tests/test_phase1_6_targeted_repairs.py:928` to leave `allow_in_memory_fallback` set to `False` across subsequent test modules (because `patch.object` checks `instance.__dict__` for local attribute restoration).
- Rather than modifying any existing test, `SheetsDatabase` was updated to store `allow_in_memory_fallback` as a real instance attribute guarded by fail-closed `__getattribute__` and `__setattr__` hooks.
- Re-running the full 684-test suite verified `683 PASS, 1 SKIP, 0 FAIL, 0 ERRORS` with zero edits to any pre-existing test file.

---

## 3. Existing Safeguards Re-Verified

- Startup resilience & post-bind Sheets scheduler (`backend/tests/test_startup_port_bind_and_resilience.py`): **PASS** (stdlib subprocess production test passes; real Uvicorn ASGI test skipped due to missing packages).
- Phase 1.8 duplicate-ID security (`backend/tests/test_phase1_8_duplicate_id_security.py`): **8/8 PASS**.
- Transaction durability & safety (`test_mission51b1_round2_integrity.py`, `test_mission51b1_round31_repairs.py`, `test_tx_final_*.py`): **PASS**.
- CORS & live audit configuration fail-closed tests (`test_cors_preflight.py`, `test_live_audit_fixes.py`, `test_phase1_6_targeted_repairs.py`): **PASS**.

---

## 4. Test Environment & Remaining Limitations

- **Runtime Environment:** Python `3.11.2` standard library (no `fastapi`, `uvicorn`, `pydantic`, `pyjwt`, `gspread`, `google.oauth2` installed).
- **Shim Dependency:** In-process backend tests run against `backend/tests/__init__.py` stdlib shims and `LocalAppsScriptSimulator` (`backend/tests/v2_test_harness.py`), except `test_01b` in `test_mission1_9r1_prod_test_isolation.py` which runs in an unshimmed subprocess.
- **Unverified External Gates:** `DB-003` (live Google Sheets), `DB-007` (live Render deployment), `DB-008` (live Apps Script `Code.gs`), and real ASGI runtime execution (`ASGI-RT`) remain `UNVERIFIED` by policy.
