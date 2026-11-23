# MISSION 1.9R-1: IMPLEMENTATION REPORT
## Critical Production Test-Mode Isolation Repair (`M19-001`)

**Baseline:** ZIP61  
**Target Defect:** `M19-001 [CRITICAL]` — `SALES_TESTING=1` combined with `SALES_ENV=production` bypassed production safety guards  
**Scope:** Strictly targeted local source-code repair across `backend/app/config.py`, `backend/app/main.py`, `backend/app/sheets.py`, `backend/app/transaction_safety.py`, plus new regression test suite `backend/tests/test_mission1_9r1_prod_test_isolation.py`

---

## 1. Root Cause Analysis

Prior to Mission 1.9R-1, four independent backend modules evaluated `os.getenv("SALES_TESTING", "").strip() == "1"` **before** checking whether `SALES_ENV == "production"`, with no centralized production/test-mode conflict rejection:

1. **JWT Secret Bypass (`backend/app/config.py`)**
   - `jwt_secret()` checked `if testing and not secret: return "test-only-secret-do-not-use-for-deployment-32"` before enforcing `SALES_ENV == "production"`.
   - `"test-only-secret-do-not-use-for-deployment-32"` was absent from `_INSECURE_SECRETS`, meaning even explicit configuration of the public test secret in production passed length checks (`len == 44 >= 32`).
   - `assert_runtime_config()` did not reject simultaneous `SALES_ENV=production` + `SALES_TESTING=1` and forwarded `testing=testing` to `validate_coordinator_durability()`.
   - `SALES_ENV` was only read at module import time without fail-closed resolution against live environment values.

2. **Startup & Google Sheets Initialization Bypass (`backend/app/main.py`)**
   - `_check_configuration()` returned immediately whenever `SALES_TESTING == "1"`, skipping `assert_runtime_config()` even in production.
   - `_schedule_post_bind_sheets_init()` returned immediately whenever `SALES_TESTING == "1"`, silently suppressing authoritative Google Sheets initialization in production.
   - `from fastapi import ...` executed before `from app.config import ...`, allowing framework imports prior to configuration conflict enforcement.

3. **Volatile Storage Fallback Activation (`backend/app/sheets.py`)**
   - `SheetsDatabase.__init__()` set `self.allow_in_memory_fallback = os.getenv("SALES_TESTING", "").strip() == "1"` regardless of `SALES_ENV=production`, allowing in-memory reads and direct writes (`_assert_direct_mutation_allowed`) while disconnected.
   - `self.shared_file_dir` and `os.getenv("SALES_SHARED_TEST_DIR")` were consulted in `get_records`, `get_verified_tab_headers`, `append_record`, `update_record`, and `delete_record` without blocking production mode.

4. **Transaction Coordinator Durability Bypass (`backend/app/transaction_safety.py`)**
   - `validate_coordinator_durability()` gated multi-instance scaling (`raw_instances > 1 and not is_testing`) and production persistent path checks (`resolved_env == "production" and not is_testing`) on `not is_testing`, allowing `SALES_TESTING=1` in production to silently fall back to volatile `/tmp` or `:memory:` storage and skip multi-instance guards.

---

## 2. Exact Repair Implemented

### 2.1 Centralized Production/Test Isolation (`backend/app/config.py`)
- Added `TEST_ONLY_JWT_SECRET = "test-only-secret-do-not-use-for-deployment-32"` and added it to `_INSECURE_SECRETS`.
- Added `_TRUTHY_TESTING_VALUES = frozenset({"1", "true", "yes", "on"})`.
- Added `ProductionTestModeConflictError(RuntimeError)` with `error_code = "PRODUCTION_TEST_MODE_CONFLICT"`.
- Added centralized fail-closed helpers:
  - `get_effective_env(env=None)` — resolves `"production"` whenever either module-level `SALES_ENV` or live `os.getenv("SALES_ENV")` is `"production"` (unless an explicit non-`None` `env` override is passed).
  - `is_production_env(env=None)` — returns `get_effective_env(env=env) == "production"`.
  - `is_testing_flag_enabled(testing=None)` — evaluates explicit boolean override or truthy `SALES_TESTING` values (`1`, `true`, `yes`, `on`).
  - `assert_production_test_isolation(env=None, testing=None)` — raises `ProductionTestModeConflictError` deterministically whenever production and testing mode are simultaneously active.
  - `is_isolated_testing_mode(env=None, testing=None)` — invokes `assert_production_test_isolation()` first, then returns `True` only in isolated non-production test environments.
- Hardened `jwt_secret()`:
  - Calls `assert_production_test_isolation()` first.
  - In production (`is_production_env()`), strictly requires a configured `SALES_JWT_SECRET` of at least 32 characters not in `_INSECURE_SECRETS` (which includes `TEST_ONLY_JWT_SECRET`); never returns the test secret or ephemeral secret and never exposes any secret value in error messages or logs.
  - Preserves `TEST_ONLY_JWT_SECRET` exclusively when `is_isolated_testing_mode()` is `True` (non-production) and preserves `_EPHEMERAL_SECRET` fallback in non-testing development.
- Hardened `assert_runtime_config()`:
  - Calls `assert_production_test_isolation()` first, then `jwt_secret()`, then validates production CORS, Spreadsheet ID, service account credentials, and coordinator durability under `is_production_env()`.
- Enforced import-time startup ordering by executing `assert_production_test_isolation()` at the end of `backend/app/config.py`.

### 2.2 Startup Ordering & Sheets Scheduler Enforcement (`backend/app/main.py`)
- Moved `from app.config import (...)` and an explicit `assert_production_test_isolation()` call to the top of `backend/app/main.py` immediately after stdlib imports — **before** FastAPI, CORSMiddleware, `app.sheets`, `app.auth`, routers, or coordinator initialization.
- Updated `_check_configuration()` to invoke `assert_production_test_isolation()` first, return early only when `is_isolated_testing_mode()` is `True` (non-production), run `assert_runtime_config()`, and re-raise unconditionally when `is_production_env()` is `True`.
- Updated `_schedule_post_bind_sheets_init()` to invoke `assert_production_test_isolation()` first and skip background Sheets initialization only when `is_isolated_testing_mode()` is `True` (non-production).
- Updated CORS production checks to use `is_production_env()`.

### 2.3 Storage Fallback & Single-Write-Owner Isolation (`backend/app/sheets.py`)
- Updated `SheetsDatabase.__init__()` to invoke `assert_production_test_isolation()`, initialize `self.allow_in_memory_fallback = is_isolated_testing_mode()`, and force `self.shared_file_dir = None` in production.
- Guarded `allow_in_memory_fallback` via `__getattribute__` and `__setattr__` on `SheetsDatabase`:
  - Any read or write of `allow_in_memory_fallback` invokes `assert_production_test_isolation()`.
  - Reading `allow_in_memory_fallback` in production always returns `False`.
  - Setting `allow_in_memory_fallback = True` in production raises `RuntimeError`.
  - Preserves normal instance-attribute semantics in `self.__dict__` so existing `unittest.mock.patch.object` tests remain cleanly compatible without modification.
- Added `_get_effective_shared_test_dir()` (always returns `None` in production and raises on production+testing conflict) and updated `get_records`, `get_verified_tab_headers`, `append_record`, `update_record`, and `delete_record` to use it.
- Hardened `enable_shared_file_store()`, `start_background_init()`, `init_connection()`, `_assert_direct_mutation_allowed()`, and quota backoff sleep timing to enforce `assert_production_test_isolation()` / `is_production_env()` / `is_isolated_testing_mode()`.

### 2.4 Transaction Coordinator Durability Isolation (`backend/app/transaction_safety.py`)
- Updated `validate_coordinator_durability()` to resolve `resolved_env = get_effective_env(env=env)` and `is_testing = is_testing_flag_enabled(testing=testing)`.
- Added fail-closed conflict rejection at the top of `validate_coordinator_durability()`: when `resolved_env == "production"` and `is_testing` is `True`, invokes `assert_production_test_isolation(...)` and raises `CoordinatorDurabilityError(..., error_code="PRODUCTION_TEST_MODE_CONFLICT", mode=CoordinatorDurabilityMode.MISCONFIGURED)`.
- Removed the `and not is_testing` bypass from both the multi-instance scaling guard (`raw_instances > 1`) and the production persistent path validation block (`if resolved_env == "production":`), ensuring neither `SALES_TESTING=1` nor `SALES_TX_ALLOW_VOLATILE_COORD=true` can bypass production durability or topology enforcement.

---

## 3. Security Behavior: Before vs. After

| Security Vector | Before (ZIP61) | After (Mission 1.9R-1) |
|---|---|---|
| `SALES_ENV=production` + `SALES_TESTING=1` startup | Silently skipped `_check_configuration()` and started API | Fails closed at `app.config` / `app.main` import time and in `lifespan()` with `ProductionTestModeConflictError` before storage, auth, coordinator, or API initialize |
| `jwt_secret()` in production with `SALES_TESTING=1` | Returned public `test-only-secret-do-not-use-for-deployment-32` | Raises `ProductionTestModeConflictError`; `create_access_token` fails closed and `decode_access_token` rejects all tokens |
| `jwt_secret()` in production with `SALES_TESTING=0` + explicit test secret | Accepted public test secret because length >= 32 | Raises `RuntimeError` because `TEST_ONLY_JWT_SECRET` is in `_INSECURE_SECRETS`; no secret exposed in error text |
| Google Sheets init in production with `SALES_TESTING=1` | `_schedule_post_bind_sheets_init()` returned early, bypassing Sheets | Raises `ProductionTestModeConflictError` in `_schedule_post_bind_sheets_init()`, `start_background_init()`, and `init_connection()` |
| In-memory / shared-file storage fallback in production | `allow_in_memory_fallback` became `True`; `SALES_SHARED_TEST_DIR` active | Raises `ProductionTestModeConflictError` under `SALES_TESTING=1`; unconditionally `False`/`None` under production with `SALES_TESTING=0`; disconnected reads/writes fail closed |
| Transaction coordinator durability in production with `SALES_TESTING=1` | Skipped persistent disk and multi-instance checks; fell back to `/tmp` (`VOLATILE_TEST`) | Raises `CoordinatorDurabilityError` (`PRODUCTION_TEST_MODE_CONFLICT`); deferred instances fail closed on `assert_writable_coordinator()` |
| Isolated non-prod testing (`SALES_ENV=development` + `SALES_TESTING=1`) | Supported | Preserved identically |
| Normal development (`SALES_ENV=development` + `SALES_TESTING=0`) | Supported | Preserved identically (plus public test secret no longer treated as strong non-test secret) |

---

## 4. Prohibited External Systems & Deployment Confirmation

- **Google Sheets:** NOT accessed.
- **Google Apps Script:** NOT executed.
- **Production credentials / Render:** NOT accessed.
- **Deployment / live systems / database resets / schema changes:** NONE performed.
- **External gates (`DB-003`, `DB-007`, `DB-008`):** Intentionally NOT touched and remain `UNVERIFIED`.
