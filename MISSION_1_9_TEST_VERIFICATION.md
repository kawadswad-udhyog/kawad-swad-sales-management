# KAWAD SWAD ERP — MISSION 1.9: INDEPENDENT TEST VERIFICATION REPORT

**Baseline**: Repository **ZIP61** (`/app/applet`)  
**Execution Policy**: Strictly local, isolated, non-production tests only (`PYTHONDONTWRITEBYTECODE=1`, no live Google Sheets, no Apps Script, no Render, no `dist/` build artifacts written).

---

## 1. Execution Environment & Isolation Verification

- **Python**: `3.11.2`
- **Live Cloud Credentials / Env Vars**: All live Sheets/Apps Script environment variables unset; `/etc/secrets/sales-service-account.json` does not exist.
- **Installed Python Runtime Dependencies Audit**:
  - `fastapi`: **NOT INSTALLED** (pure-stdlib mock shim in `backend/tests/__init__.py` activates)
  - `pydantic`: **NOT INSTALLED** (pure-stdlib `MockBaseModel` shim activates — zero schema/field validation)
  - `jwt` (`PyJWT`): **NOT INSTALLED** (pure-stdlib `mock_jwt` shim activates)
  - `gspread`: **NOT INSTALLED**
  - `google.oauth2`: **NOT INSTALLED**
  - `pytest`: **NOT INSTALLED**
- **Frontend Toolchain**: Node.js + `npx tsc` + `npx tsx` available and isolated.

---

## 2. Classification of Test Evidence

This report strictly separates:
1. **Personally Executed in Isolation (against ZIP61)**
2. **Inspected Only (Not Executed)**
3. **Claimed in Prior Phase 1.8 Reports (and Reconciliation Against ZIP61)**

### A. Personally Executed Tests (Local Isolated Run on ZIP61)

| Suite / Command | Scope | Executed Result | Duration | Runtime Fidelity Caveat |
|---|---|---|---:|---|
| `PYTHONDONTWRITEBYTECODE=1 SALES_TESTING=1 python3 -B -m unittest backend/tests/test_phase1_8_duplicate_id_security.py -v` | Phase 1.8 fail-closed duplicate-ID preflight & concurrency guard (`P1.8-001`, `P1.8-015`) | **8 PASS / 0 FAIL / 0 SKIP** | 0.067s | Runs under stdlib shims + `_FakeWorksheet` / mocked `build_opener` |
| `PYTHONDONTWRITEBYTECODE=1 SALES_TESTING=1 python3 -B -m unittest discover -s backend/tests -p 'test_tx_final_*.py' -t backend -v` | Post-1.8 transaction-safety closure (`TX-FINAL-01`, `02`, `05`, `06`, `07`, `08`) | **17 PASS / 0 FAIL / 0 SKIP** | 0.608s | Runs under stdlib shims + `LocalAppsScriptSimulator` + real SQLite temp DBs |
| `PYTHONDONTWRITEBYTECODE=1 SALES_TESTING=1 python3 -B -m unittest discover -s backend/tests -t backend` | Full backend test discovery across all **63** `backend/tests/test_*.py` files (**672** test methods) | **671 PASS / 0 FAIL / 1 SKIP** | 45.454s | **All 671 tests run under stdlib shims (`fastapi`/`pydantic`/`jwt` absent) + `LocalAppsScriptSimulator`**; 1 skipped (`test_uvicorn_binds_and_serves_health_within_3s_when_sheets_hangs_over_5s`, line 735 of `test_startup_port_bind_and_resilience.py`, skipped because `uvicorn`/`fastapi` are not installed) |
| `npx tsc --noEmit` | Full TypeScript strict typecheck of frontend `src/` and `scripts/` | **PASS (0 errors)** | ~9s | Static type check only (no build artifacts emitted) |
| `npx tsx scripts/test_phase1_6_frontend_contracts.ts` | Frontend API/RBAC/workspace contracts | **17/17 PASS** | <2s | Node/tsx harness with mocked `fetch` |
| `npx tsx scripts/test_mission51b1_frontend_transaction_safety.ts` | Frontend 504/timeout & non-retry mutation rules | **5/5 PASS** | <2s | Node/tsx harness with mocked `fetch` |
| `npx tsx scripts/test_tx_final_04_frontend_unknown_safety.ts` | Frontend `UNKNOWN` lock & status verification flow | **6/6 PASS** | <2s | Node/tsx harness with mocked `fetch` |
| `npx tsx scripts/test_mission51b1rf_persistence_and_fingerprint.ts` | Lock persistence degradation, readback integrity & SHA-256 payload fingerprinting | **18/18 PASS** | <2s | Node/tsx harness with mocked `sessionStorage`/`fetch` + static view scan (covers `src/views/`, misses `src/employee/views/`) |
| `npx tsx scripts/test_mission51b1rf2_transaction_identity_closure.ts` | Bound method + endpoint + query + payload fingerprint & status response validation | **39/39 PASS** | <2s | Node/tsx harness with mocked `sessionStorage`/`fetch` |

**Personally Executed Totals**:
- Backend Python unit tests: **671 passed, 1 skipped, 0 failed** (across 63 files; 8 Phase 1.8 security tests + 17 `test_tx_final_*` tests are subsets of these 672).
- Frontend TypeScript check + safety suites: **`tsc --noEmit` 0 errors** + **85/85 checks passed** across all 5 TS test scripts.

### B. Inspected Only (Not Executed)

| Artifact / Target | Why Not Executed | Inspection Outcome |
|---|---|---|
| `test_uvicorn_binds_and_serves_health_within_3s_when_sheets_hangs_over_5s` (`backend/tests/test_startup_port_bind_and_resilience.py:735-740`) | Automatically skipped (`@unittest.skipUnless(_has_real_uvicorn_and_fastapi())`) because `uvicorn` and `fastapi` are not installed | Real ASGI server binding & FastAPI startup lifecycle remain **UNVERIFIED** in this environment. |
| Production `npm run build` (`vite build`) | Prohibited by audit-only read-only rule (would write `dist/` build artifacts) | TypeScript types verified via `npx tsc --noEmit` (0 errors); bundler output not executed. |
| Browser/Playwright E2E UI verification | No live backend/browser harness permitted in isolated audit-only mode | Frontend lock and banner logic inspected statically and verified via Node `tsx` harnesses. |
| Live Google Sheets / Apps Script / Render staging & walkthrough scripts (`backend/scripts/run_staging_walkthrough.py`, etc.) | Explicitly prohibited by audit-only isolation rules | Inspected statically only; external systems (`DB-008`, `DB-003`, `DB-007`) classified `UNVERIFIED`. |

### C. Reconciliation Against Prior Phase 1.8 Report Claims

| Prior Phase 1.8 Claim | Independent Verification Against ZIP61 | Discrepancy / Risk |
|---|---|---|
| "550/550 backend tests passing" | ZIP61 has grown (via post-1.8 Mission 51B-1R/RF additions) to **672** tests: **671 PASS, 1 SKIP, 0 FAIL** | Prior claim omitted the critical caveat that **zero real `fastapi`/`pydantic`/`jwt`/`gspread` packages are installed**, and 1 real ASGI startup test is skipped. |
| "All 14 Phase 1.8 repairs verified" | **10 PASS, 4 PARTIAL** (`P1.8-005`, `P1.8-007`, `P1.8-009`, `P1.8-014`) | Prior tests missed 3 `quality.py` status overwrites (`P1.8-007`), unpersisted `WorkforcePayments.accounting_journal_ref` (`P1.8-009`), non-idempotent random CAS nonces on retry (`P1.8-005`), and missing journal replay recovery on `receive_raw_material` (`P1.8-014`). |

---

## 3. Test Integrity Audit Findings

1. **Mock Divergence — Stdlib Shims Mask Framework Bugs (`M19-008` — HIGH)**:
   - `backend/tests/__init__.py:157-169` replaces `pydantic.BaseModel` with `MockBaseModel`, which accepts arbitrary kwargs without validating types, `min_length`, `gt=0`, `ge=0`, `Literal`, or required fields.
   - `backend/tests/__init__.py:17-92` replaces `fastapi` with pass-through decorators (`lambda f: f`), so calling router functions directly bypasses FastAPI's `Depends(require_sheets_connection)`, `Depends(get_current_user)`, and query/body parsing.
2. **Transport & Schema Auto-Bypass in `LocalAppsScriptSimulator` (`backend/tests/v2_test_harness.py:72-180, 402-493`)**:
   - `LocalAppsScriptSimulator.start()` automatically calls `schema_reg.approve_core_schema_reconciliation(...)` for all 12 conflicting core schema tabs, preventing tests from experiencing real unapproved-schema blocks unless explicitly configured with `reconcile_core_tables=False`.
   - `V2RouterProxy` silently injects a synthetic `X-KS-Idempotency-Key` header whenever a test omits `request`, masking callers that might forget to pass request context.
   - Multi-tab atomicity (e.g., `CREATE_SALE`, `POST_JOURNAL_VOUCHER`, `REVIEW_STOCK_DISCREPANCY`) is simulated by checking `_check_injected_failure` in Python memory before writing to `db.memory_store`—it provides **zero** proof that live Apps Script `Code.gs` (`DB-008`) implements the same atomic rollback or `IdAllocations` row ordering.
3. **Blind Spots Confirmed by Newly Discovered Defects**:
   - **Zero** tests caught `SALES_TESTING=1` overriding `SALES_ENV=production` (`M19-001`) because `__init__.py:10` forces `os.environ["SALES_TESTING"] = "1"` globally.
   - **Zero** tests caught `FACTORY_WORKER` privilege escalation (`M19-002`), cross-user IDOR on `/api/v2/transactions/status/{nonce}` (`M19-005`), unenforced `must_change_password` (`M19-006`), or missing session revocation on approval-executed resets (`M19-007`).
   - **Zero** frontend tests caught missing `UnknownOutcomeBanner` / `useUnknownOutcomeGuard` in `src/employee/views/*.tsx` (`M19-012`) because `test_mission51b1rf_persistence_and_fingerprint.ts` test #18 only inspects `src/views/*.tsx`, nor did they catch that zero production callers pass `requireVerifiedRetry: true` (`M19-011`).
4. **Swallowed Exceptions & Skips Check**:
   - Scan across all 63 backend test files found **0** `except: pass` swallowed-assertion blocks and **1** explicit `@unittest.skipUnless` (the real Uvicorn ASGI test). Test assertions themselves are generally substantive, but the mocked execution layer significantly limits their real-world production guarantee.
