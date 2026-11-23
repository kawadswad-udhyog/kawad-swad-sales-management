# KAWAD SWAD ERP — MISSION 1.9: FINAL RELEASE & PHASE 2 ENTRY GATE

**Repository Audited**: **ZIP61** (`/app/applet`)  
**Audit Scope**: Independent Verification of Phase 1.8 Code-Stability & Security Stabilization Claims (Read-Only Audit)

---

## FINAL GATE VERDICT

# `RED`

**Phase 2 Authorization**: **NOT APPROVED (BLOCKED PENDING REMEDIATION & EXTERNAL GATE VERIFICATION)**

---

## 1. Rationale for `RED` Verdict

Repository **ZIP61** demonstrates meaningful engineering progress in single-write-owner controls, SQLite transaction coordination, and canonical frontend transaction fingerprinting. However, it **does NOT satisfy** its reported Phase 1.8 code-stability and security stabilization claims due to **1 CRITICAL** and **7 HIGH** independently confirmed defects in the repository, **4 incomplete (`PARTIAL`) Phase 1.8 repairs**, and **4 unverified external/runtime gates**:

### Blocking Code & Security Defects Confirmed in ZIP61
1. **`M19-001` [CRITICAL] — Production Fail-Closed Bypass via `SALES_TESTING=1`**: Setting `SALES_TESTING=1` overrides `SALES_ENV=production` in `main.py:49-71`, `config.py:60-66`, `sheets.py:384`, and `transaction_safety.py:917, 930`—signing JWTs with a hardcoded public secret, skipping Google Sheets init, enabling volatile in-memory storage fallback, and disabling coordinator durability checks.
2. **`M19-002` [HIGH] — `FACTORY_WORKER` Privilege Escalation**: `CANONICAL_ROLE_V2_MAP["FACTORY_WORKER"] = "PRODUCTION"` takes precedence over `DEFAULT_ROLE_PERMISSIONS["FACTORY_WORKER"] = {"production": ["view"]}` in `permissions.py:492-500`, granting read-only factory workers full `PRODUCTION` write access.
3. **`M19-003` [HIGH] — False Quarantine on Committed `CREATE_SALE` (`BillNumbers` Collision)**: `apps_script_bridge.py:1751-1754, 2191-2192, 3576-3579, 3664-3667` fail to filter `tab_name != "BillNumbers"` in `IdAllocations` nonce lookups.
4. **`M19-004` [HIGH] — Split-Write Accounting Atomicity & Unquarantined GL Divergence**: Six non-Sales financial flows (`production.py`, `workforce.py`, `purchasing.py`, `quality.py`) post GL journals in a separate unquarantined bridge call; `receive_raw_material` replay (`production.py:1018-1056`) returns `ALREADY_RECORDED` without recovering a missing journal, and `WorkforcePayments.accounting_journal_ref` (`workforce.py:1683`) is never persisted to Google Sheets (`P1.8-009` PARTIAL).
5. **`M19-005` [HIGH] — Cross-User IDOR on `GET /api/v2/transactions/status/{nonce}`**: Any authenticated user can inspect other users' non-confidential transaction status, `allocated_id`, `tab_name`, and `transaction_id` (`v2_erp.py:1326-1353`).
6. **`M19-006` [HIGH] — `must_change_password` Unenforced Server-Side**: Temporary/reset credentials grant full direct API access without forcing password change (`auth.py:490`).
7. **`M19-007` [HIGH] — Missing Session Revocation on Approval-Executed Resets/Deactivations/Role Changes**: `routers/approvals.py:158-174, 232-250` omits `sessions_revoked_at` and `_USER_REVOKED_AT`.
8. **`M19-008` [HIGH] — Zero Real Backend Dependencies Tested**: All 671 passing backend tests ran under pure-stdlib `fastapi`/`pydantic`/`jwt` mock shims and `LocalAppsScriptSimulator`; the real Uvicorn ASGI test was skipped.

### Incomplete Phase 1.8 Repairs
- `P1.8-005` (`PARTIAL`): Random UUID CAS nonces break same-nonce idempotency on timeout/`UNKNOWN` retries (`M19-010`).
- `P1.8-007` (`PARTIAL`): 3 endpoints in `quality.py` (`198`, `464`, `531`) still overwrite domain `status` with bridge `"CONFIRMED"` (`M19-009`).
- `P1.8-009` (`PARTIAL`): `accounting_journal_ref` is not persisted to `WorkforcePayments` (`M19-004`).
- `P1.8-014` (`PARTIAL`): Missing journal recovery on `receive_raw_material` replay and missing leg-1/parent readback in `record_dal_milling_batch`.
- `P1.8-016` (`PARTIAL`): 671/672 pass only under mock shims with 1 skipped ASGI test (`M19-008`).

### Medium Frontend & Operational Defects Requiring Closure
- `M19-011` [MEDIUM]: `requireVerifiedRetry` is opt-in and enabled by zero production callers in `src/`.
- `M19-012` [MEDIUM]: All 5 mutating Employee Portal views (`src/employee/views/*.tsx`) omit `UnknownOutcomeBanner` and `useUnknownOutcomeGuard`, trapping employees in an unrecoverable `workforce_view` lock after any 504/timeout.
- `M19-013` [MEDIUM]: Logout revocation fails open to HTTP 200; login lockout is process-local, username-only, and unbounded.
- `M19-014` [MEDIUM]: `/api/v2/packaging` and `/api/v2/transactions` missing from `ENDPOINT_SCOPE_RULES`; hardcoded 5% GST in `create_customer_return` bypasses `PENDING_CA_APPROVAL`; cached read & float math in `closing.py`.

---

## 2. Mandatory Exit Criteria Before Phase 2 Re-Evaluation

1. **Close Critical & High Code Defects**: Remediate `M19-001` through `M19-007` and complete partial repairs `P1.8-005`, `P1.8-007`, `P1.8-009`, `P1.8-014` with targeted adversarial regression tests.
2. **Close Frontend Recovery Gaps**: Remediate `M19-011`, `M19-012`, and `M19-014` (`ENDPOINT_SCOPE_RULES`) so Employee Portal and v2 packaging/reconcile flows have full `UNKNOWN`-outcome recovery and status-verified retry enforcement.
3. **Execute Real-Dependency Backend Verification (`M19-008`)**: Install `backend/requirements.txt` in an isolated test venv and run real FastAPI `TestClient` + Pydantic + PyJWT + Uvicorn ASGI startup tests (0 skipped).
4. **Independently Verify External Production Gates**:
   - **`DB-008` (`UNVERIFIED`)**: Audit deployed Google Apps Script `Code.gs` for HMAC verification, `LockService` concurrency serialization, atomic multi-tab commits, and `IdAllocations` ordering.
   - **`DB-003` (`UNVERIFIED`)**: Verify live Google Sheet tabs, Row-1 headers, and reconciliation of all 12 core schema conflict tabs.
   - **`DB-007` (`UNVERIFIED`)**: Verify live Render deployment configuration (`SALES_ENV=production`, `SALES_TESTING` unset, single worker, persistent disk for `TRANSACTION_DB_PATH`, strict `SALES_CORS_ORIGINS`).
