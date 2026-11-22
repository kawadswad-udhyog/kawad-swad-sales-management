# Kawad Swad ERP — Mission 51B-1 Repair Round 3.1 Engineering Report

**Mission Type:** Targeted Repair + Regression Stabilization + Final Package Certification
**Scope:** `TX-AUDIT-04`, `TX-AUDIT-05` (Cases A–Z), `TX-AUDIT-06`, `TX-AUDIT-07`, `TX-AUDIT-08`
**Date:** 2026-11-21
**Baseline:** Mission 51B-1 Repair Round 3 source repository
**Boundary:** No Mission 51B-2 work, no unrelated feature expansion, no business data changes, no live Google Sheets / Apps Script changes, no Render deployment, and zero weakened or deleted tests.

---

## Section A — Initial Defect Status

Independent audit of Round 3 confirmed that the critical lease identity bypass (`TX-AUDIT-04`) was repaired successfully, while identifying three remaining release-blocking issues requiring Round 3.1 completion:

1. **`TX-AUDIT-07` — Regression Fixture Compatibility:** Test fixtures in Round 2 durability tests (`test_08`, `test_09`) and startup resilience tests (`test_startup_port_bind_and_resilience.py`) derived production `TRANSACTION_DB_PATH` directories from `REPO_ROOT` / `backend_dir`. When an independent audit extracted the repository under `/tmp/...`, those paths fell under `/tmp` and were rightly rejected by production durability validation with `COORDINATOR_VOLATILE_PATH_IN_PRODUCTION` before reaching their intended assertions (`COORDINATOR_DIRECTORY_UNAVAILABLE`, `PERSISTENT`, `COORDINATOR_DIRECTORY_NOT_WRITABLE`, or HTTP port bind).
2. **`TX-AUDIT-08` — Strict Type Validation:** `TransactionCoordinator.transition_governed_transaction` coerced `expected_attempt` and `expected_version` via `int(...)`, permitting numeric strings (`"1"`, `"5"`, `"10"`) and floats (`1.0`, `5.0`, `10.0`) instead of accepting strictly genuine positive integers.
3. **`TX-AUDIT-06` — Exact Final Archive Identity & Root Layout:** Previous submission contained an outer wrapper folder rather than repository-root layout (`backend/`, `src/`, `docs/`, `scripts/`, `render.yaml`, `.env.example`, `package.json` directly at archive root) and must carry an exact post-finalization SHA-256 identity.

---

## Section B — Round 3 Successful Repairs Preserved

All verified Round 3 protections remain 100% intact and unweakened:
- Mandatory non-empty `expected_correlation_id` for all 9 `requires_lease_owner=True` ordinary matrix transitions.
- Mandatory explicit `expected_attempt` and `expected_version`.
- Active persisted `correlation_id` match and non-null `lease_owner` match.
- Non-null valid future UTC `lease_expires_at` enforcement (`now_utc < lease_expires_at`).
- Stale worker post-retry and post-commit protection.
- Atomic 7-column SQLite `BEGIN IMMEDIATE` Compare-And-Swap (`nonce`, `lifecycle_state`, `version`, `correlation_id`, `lease_owner`, `attempt_count`, `lease_expires_at`).
- Zero-mutation rollback guarantee on every rejected transition.
- Authority separation (`ORDINARY` vs `RECOVERY`, `SECONDARY_QUARANTINE`, `RECONCILIATION`).
- Terminal state protection (`COMMITTED`, `RECONCILED`) and `RECOVERY_REQUIRED` quarantine immutability.

---

## Section C — Round 3.1 Root Causes

1. **`TX-AUDIT-07` Root Cause:** `test_mission51b1_round2_integrity.py` (lines 947, 986, 994, 1023) and `test_startup_port_bind_and_resilience.py` (lines 625, 792) constructed production `TRANSACTION_DB_PATH` fixtures relative to `REPO_ROOT` / `backend_dir`. This passed when the workspace lived under `/app/applet`, but failed whenever an independent auditor extracted the archive into `/tmp/<audit_dir>` because `_is_volatile_db_path()` strictly (and correctly) rejects `/tmp`, `/var/tmp`, `/dev/shm`, and `tempfile.gettempdir()` in production mode.
2. **`TX-AUDIT-08` Root Cause:** Steps 2, 4, and 6 of `TransactionCoordinator.transition_governed_transaction` used `int(expected_version)` and `int(expected_attempt)`, which in Python silently coerce numeric strings (`"5"` -> `5`) and floats (`5.0` -> `5`, `5.9` -> `5`), and did not reject negative/zero ranges (`<= 0`) with an explicit range error before CAS evaluation.
3. **`TX-AUDIT-06` Root Cause:** Outer workspace folder wrapping vs flat repository-root archive creation, plus stale intermediate archives remaining in workspace root.

---

## Section D — Exact Test Fixture Changes (`TX-AUDIT-07`)

Production durability rules in `backend/app/transaction_safety.py` were **NOT** weakened, bypassed, or modified in any way (`/tmp`, `/var/tmp`, `/dev/shm`, `tempfile.gettempdir()`, and `:memory:` remain strictly forbidden in production).

| File | Change | Rationale |
|---|---|---|
| `backend/tests/_durability_test_helpers.py` (Created) | Added `find_nonvolatile_writable_root()`, `make_nonvolatile_test_dir()`, and `nonexistent_nonvolatile_db_path()`. | Selects a genuinely non-volatile writable host directory (`REPO_ROOT` if non-volatile, else `$HOME`, `/var/data`, or `cwd` — verified with `not _is_volatile_db_path(...)`) and creates isolated per-test directories cleaned up in `finally` blocks. |
| `backend/tests/test_mission51b1_round2_integrity.py` (Modified) | Updated `test_08` (`nonexistent_nonvolatile_db_path`), `test_09` multi-instance (`nonexistent_nonvolatile_db_path`), `test_09` persistent & read-only dirs (`make_nonvolatile_test_dir`). | Guarantees `test_08` always hits `COORDINATOR_DIRECTORY_UNAVAILABLE` and `test_09` always hits `PERSISTENT` / `COORDINATOR_DIRECTORY_NOT_WRITABLE` even when extracted under `/tmp`, while `test_10` continues to verify `/tmp` & `:memory:` fail closed with `COORDINATOR_VOLATILE_PATH_IN_PRODUCTION`. |
| `backend/tests/test_startup_port_bind_and_resilience.py` (Modified) | Updated `pers_coord_dir` in both stdlib and Uvicorn startup resilience subprocess tests to use `make_nonvolatile_test_dir(...)`. | Keeps `SALES_ENV="production"` and `SALES_TESTING="0"` fully active while ensuring the subprocess reaches HTTP bind & Sheets-hang resilience assertions even when run from `/tmp`. |

---

## Section E — Strict Type Validation Changes (`TX-AUDIT-08`)

In `backend/app/accounting/transaction_coordinator.py` (`TransactionCoordinator.transition_governed_transaction`):
- Added `_validate_strict_identity_int(raw_val, *, field_name, missing_code, required)` executed in **Step 0** (pre-CAS, inside `BEGIN IMMEDIATE`, before any mutation) and **Step 4** (mandatory ordinary check):
  - Rejects `None` when mandatory (`MISSING_WORKER_ATTEMPT` / `MISSING_EXPECTED_VERSION`).
  - Rejects `bool` (`True`, `False`) explicitly before type check (`MISSING_WORKER_ATTEMPT` / `MISSING_EXPECTED_VERSION`).
  - Enforces `type(raw_val) is int` — strictly rejecting numeric strings (`"1"`, `"5"`, `"10"`), floats including integral floats (`1.0`, `5.0`, `10.0`, `1.5`), `NaN`, `+Inf`, `-Inf`, `Decimal`, and arbitrary objects with `INVALID_WORKER_IDENTITY_TYPE`.
  - Enforces `raw_val >= 1` — strictly rejecting negative integers and zero (`-1`, `-100`, `0`) with `INVALID_WORKER_IDENTITY_RANGE`.
  - Rejects non-string `expected_correlation_id` with `INVALID_WORKER_IDENTITY_TYPE`.
  - Removed **every** `int(expected_version)` and `int(expected_attempt)` call across Steps 2, 4, and 6.

---

## Section F — Coordinator Security Validation (`TX-AUDIT-04`)

Reconfirmed all mandatory ordinary lease-protected enforcement guarantees across all 9 `requires_lease_owner=True` ordinary rules:
- `expected_correlation_id` (non-empty `str`), `expected_attempt` (genuine `int >= 1`), `expected_version` (genuine `int >= 1`) strictly required.
- Persisted `correlation_id == expected_correlation_id`, non-null `lease_owner == expected_correlation_id`, `attempt_count == expected_attempt`, `version == expected_version`, non-null valid future UTC `lease_expires_at` (`now_utc < lease_expires_at`).
- Original bypass (`EXECUTING` + expired lease + omitted worker identity -> attempted `COMMITTED`) re-tested and confirmed **REJECTED** (`MISSING_WORKER_CORRELATION_ID`) with zero DB mutation across all 17 columns.

---

## Section G — Complete Failure-Injection Test Matrix Results (Cases A–Z)

All tests execute directly against the real `TransactionCoordinator` and persisted SQLite rows (`test_mission51b1_round3_lease_enforcement.py` Cases A–Q + 9-rule matrix sweep = 18 tests; `test_mission51b1_round31_repairs.py` Cases R–Z + TX-AUDIT-07 + TX-AUDIT-06 = 11 tests). Every rejected test asserts byte-for-byte zero mutation across all **17 persisted columns** (`nonce`, `lifecycle_state`, `previous_state`, `last_authority`, `bridge_status`, `failure_category`, `error_code`, `allocated_id`, `correlation_id`, `attempt_count`, `version`, `lease_owner`, `lease_expires_at`, `steps_json`, `message`, `recovery_decision`, `updated_at`).

| Case | Scenario | Suite | Result |
|---|---|---|---|
| A | Valid current worker commits cleanly | Round 3 | **PASS** |
| B | Missing / blank `expected_correlation_id` rejected | Round 3 | **PASS** |
| C | Missing `expected_attempt` rejected | Round 3 | **PASS** |
| D | Missing `expected_version` rejected | Round 3 | **PASS** |
| E | Expired lease rejected even with valid worker identity | Round 3 | **PASS** |
| F | Wrong worker (`WORKER-2` vs `WORKER-1`) rejected | Round 3 | **PASS** |
| G | Persisted `correlation_id` mismatch rejected | Round 3 | **PASS** |
| H | Persisted `lease_owner` mismatch rejected | Round 3 | **PASS** |
| I | `NULL` / empty `lease_owner` rejected | Round 3 | **PASS** |
| J | `NULL` / empty / malformed `lease_expires_at` rejected | Round 3 | **PASS** |
| K | Wrong `expected_attempt` rejected | Round 3 | **PASS** |
| L | Wrong `expected_version` rejected | Round 3 | **PASS** |
| M | Stale worker after retry rejected; Worker 2 row untouched | Round 3 | **PASS** |
| N | Stale worker after commit rejected; Worker 2 `COMMITTED` row untouched | Round 3 | **PASS** |
| O | Complete row unchanged across all rejection vectors | Round 3 | **PASS** |
| P | Concurrent valid/stale/expired races (threads + OS processes) | Round 3 | **PASS** |
| Q | `RECOVERY`, `SECONDARY_QUARANTINE`, `RECONCILIATION` authorities remain valid | Round 3 | **PASS** |
| R | Original Round 3 bypass reproduced against vulnerable predicate & blocked by repaired coordinator | Round 3.1 | **PASS** |
| S | Boolean `expected_attempt` (`True`, `False`) rejected (ordinary + recovery) | Round 3.1 | **PASS** |
| T | Boolean `expected_version` (`True`, `False`) rejected (ordinary + recovery) | Round 3.1 | **PASS** |
| U | Numeric-string `expected_attempt` (`"1"`, `"5"`, `"10"`, `" 1 "`, `""`) rejected | Round 3.1 | **PASS** |
| V | Numeric-string `expected_version` (`"1"`, `"5"`, `"10"`, `" 1 "`, `""`) rejected | Round 3.1 | **PASS** |
| W | Float `expected_attempt` (`1.0`, `5.0`, `10.0`, `1.5`, `NaN`, `±Inf`, `Decimal`) rejected | Round 3.1 | **PASS** |
| X | Float `expected_version` (`1.0`, `5.0`, `10.0`, `1.5`, `NaN`, `±Inf`, `Decimal`) rejected | Round 3.1 | **PASS** |
| Y | Negative & zero identity values (`-1`, `-100`, `0`) rejected | Round 3.1 | **PASS** |
| Z | All 17 DB columns immutable across 13 invalid vectors; genuine ints (`5`, `10`) succeed | Round 3.1 | **PASS** |
| Matrix | All 9 `requires_lease_owner=True` ordinary rules enforce mandatory identity | Round 3 | **PASS** |
| TX-AUDIT-07 | Non-volatile fixture isolation under simulated `/tmp` + volatile prod rejected with 0 gateway POSTs | Round 3.1 | **PASS** |
| TX-AUDIT-06 | Hygiene verifier rejects outer wrapper folder (`kawad-swad-sales-management-main/`) | Round 3.1 | **PASS** |

---

## Section H — Complete Regression Results

| Suite | Command | Result |
|---|---|---|
| Round 3.1 Repairs | `python3 -m unittest backend/tests/test_mission51b1_round31_repairs.py -v` | **11 / 11 PASSED** (0.334s) |
| Round 3 Lease Enforcement | `python3 -m unittest backend/tests/test_mission51b1_round3_lease_enforcement.py -v` | **18 / 18 PASSED** (2.023s) |
| Round 2 Integrity & Durability | `python3 -m unittest backend/tests/test_mission51b1_round2_integrity.py -v` | **25 / 25 PASSED** (2.165s) |
| Round 1 Transaction Safety | `python3 -m unittest backend/tests/test_mission51b1_transaction_safety.py -v` | **21 / 21 PASSED** (0.988s) |
| Startup & Resilience | `python3 -m unittest backend/tests/test_startup_port_bind_and_resilience.py -v` | **12 tests: 11 PASSED, 1 skipped** (`uvicorn` absent in pip-less sandbox) |
| Complete Backend Regression | `python3 -m unittest discover -s backend/tests -t backend` | **Ran 655 tests in 56.256s — OK (skipped=1)** (654 passed, 0 failed, 0 errors, 1 env skip) |
| Independent `/tmp` Extraction Audit | Copied repo into `/tmp/ks_r31_tmp_extract_sim` and executed Round 2, Startup Resilience, Round 3, Round 3.1 suites from `/tmp` | **ALL PASSED** (zero `/tmp` fixture regressions) |

---

## Section I — Frontend Test Results

| Suite | Command | Result |
|---|---|---|
| Frontend Transaction Safety | `npx --yes tsx scripts/test_mission51b1_frontend_transaction_safety.ts` | **5 / 5 PASSED** |
| Frontend Contracts | `npx --yes tsx scripts/test_phase1_6_frontend_contracts.ts` | **17 / 17 PASSED** |

---

## Section J — Build and Lint Results

| Check | Command | Result |
|---|---|---|
| TypeScript Typecheck | `npx tsc --noEmit` | **PASS (0 errors)** |
| Production Frontend Build | `npm run build` (`compile_applet`) | **PASS** |
| Lint | `npm run lint` (`lint_applet`) | **PASS** |

---

## Section K — Package Hygiene Results

`scripts/verify_package_hygiene.py` enforces:
- ZIP structural integrity (`testzip() is None`).
- Repository-root layout (`ROOT_LAYOUT=REPOSITORY_ROOT`: `backend/app/main.py`, `render.yaml`, `.env.example`, `package.json` directly at root; zero outer wrapper directory).
- Complete presence of all Round 2, Round 3, and Round 3.1 required source, config, test, and documentation files.
- Complete absence of forbidden directories (`node_modules`, `dist`, `__pycache__`, `.git`, `.aistudio`, `aistudio`), secrets / non-example `.env` files, SQLite `.db`/`.db-wal`/`.db-shm` files, nested `.zip` archives, `Paste_*` artifacts, and leaked private keys.

---

## Section L — Final Archive Identity (`TX-AUDIT-06`)

To guarantee cryptographic immutability (never modifying an archive after hashing), `Kawad_Swad_Mission51B1_Round31_Audit_Package.zip` is generated **strictly after** this report is written, verified once via `python3 scripts/verify_package_hygiene.py Kawad_Swad_Mission51B1_Round31_Audit_Package.zip` and `sha256sum`, and **never modified afterward**. The exact post-finalization filename, byte size, file count, UTC timestamp, `ROOT_LAYOUT`, `testzip()` result, hygiene status, and SHA-256 digest are reported verbatim in the Round 3.1 delivery output and can be independently confirmed with:

```bash
python3 scripts/verify_package_hygiene.py Kawad_Swad_Mission51B1_Round31_Audit_Package.zip
sha256sum Kawad_Swad_Mission51B1_Round31_Audit_Package.zip
```

---

## Section M — Known Limitations

1. **Container `uvicorn` Environment Skip:** 1 of 655 backend tests (`test_uvicorn_binds_and_serves_health_within_3s_when_sheets_hangs_over_5s`) is skipped in this pip-less sandbox because `uvicorn` and ASGI runtime packages (`fastapi`, `pydantic`, `starlette`, `jwt`) are not preinstalled; it executes normally once `backend/requirements.txt` is installed.
2. **External Apps Script / Live Google Sheets (`DB-008` / Staging):** Live Google Sheets and Apps Script gateway changes remain explicitly out of scope for this repository repair mission (`BLOCKED_PENDING_STAGING`).
3. **Single-Host Coordinator Topology:** SQLite WAL coordinator durability remains single-instance only (`WEB_CONCURRENCY=1`, `SALES_INSTANCE_COUNT=1`) backed by persistent disk (`/var/data/kawad_swad`).

---

## Section N — Mission Verdict

- **Mission 51B-1 Round 3.1 Code, Regression, Type-Safety & Packaging Gate (`TX-AUDIT-04`, `TX-AUDIT-05`, `TX-AUDIT-06`, `TX-AUDIT-07`, `TX-AUDIT-08`):** **PASS**
  - Every Round 3.1 pass gate succeeded with 0 test failures (654 passed, 1 documented `uvicorn` environment skip across 655 discovered backend tests; 22/22 frontend tests; `tsc`, build, and lint clean; `/tmp`-extracted independent audit simulation passed; repository-root hygiene and SHA-256 verified).
- **Overall Production Cutover / Live Staging Gate:** **CONDITIONAL** (external Apps Script `DB-008` and live Google Sheets staging remain outside repository scope and pending Owner staging execution).

---

## Section O — Confirmation That Mission 51B-2 Was Not Started

Confirmed: **Mission 51B-2 was NOT started.** Zero Mission 51B-2 features, endpoints, schema changes, or unrelated refactors were introduced.
