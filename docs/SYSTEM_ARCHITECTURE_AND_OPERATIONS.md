# Kawad Swad ERP — System Architecture, Integration & Operations Guide

This document reflects the actual verified implementation of the Kawad Swad ERP repository.

---

## 1. System Topology

```
[ React 18 + TS + Vite Frontend (src/) ]
          |  HTTPS JSON + Bearer JWT + X-Idempotency-Key / X-Correlation-Id
          v
[ FastAPI Backend (backend/app/main.py — 20 routers, 206 /api/* endpoints) ]
     |                                            |
     | Read-Only (spreadsheets.readonly)          | Governed Write Envelope (HMAC-SHA256)
     v                                            v
[ Google Sheets Workbook ]  <============  [ Google Apps Script Gateway (WebAppBridge.gs) ]
  (Authoritative Business DB)                (Single-Write-Owner — LockService + ID Allocator)
```

### Core Architectural Invariants
1. **Single-Write-Owner:** All business writes from FastAPI routers pass exclusively through `apps_script_bridge.delegate_governed_write(...)`. The backend service account requests strictly `https://www.googleapis.com/auth/spreadsheets.readonly` scope.
2. **Fail-Closed Everywhere:**
   - Missing or conflicting schemas block writes before any remote HTTP POST (`503 SCHEMA_CONFLICT_BLOCKED` / `OWNER_SETUP_REQUIRED`).
   - Duplicate-ID preflight checks (`_check_id_exists_authoritative`) force `fresh=True`, verify authoritative Row-1 ID headers via `get_verified_tab_headers()`, serialize in-flight allocations with `_INFLIGHT_ID_LOCK`, and fail closed (`503`) on any outage or malformed response.
   - Token revocation (`RevokedTokens`) and account status (`AuthUsers`) are in `NO_CACHE_TABS`, never fall back to stale cache on HTTP `429`, and fail closed on missing/None/corrupted timestamps or active flags (`AUTH-03`).
   - Post-write read-back verification (`action_registry.py`) confirms committed records via fresh Sheets reads and returns structured `504 READ_BACK_UNCONFIRMED` (`retryable=True`) if unconfirmed.

---

## 2. Backend Module & Router Map (`backend/app/routers/`)

| Router | Prefix | Core Capabilities |
|---|---|---|
| `auth.py` | `/api/auth` | Login, `/me`, logout (persistent `RevokedTokens`), password change, brute-force lockout |
| `users.py` | `/api/users` | User creation, update, activation/deactivation (with session revocation), password reset |
| `approvals.py` | `/api/approvals` | Centralized Maker-Checker approval queue & Owner decisions |
| `products.py` | `/api/products` | Product SKU master, pack weights, pricing, activation/deactivation |
| `customers.py` | `/api/customers` | Customer master, credit limits, credit approvals, ledger & aging |
| `sales.py` | `/api/sales` | Multi-item sales, idempotency, credit/cash/bank payments, returns, cancellations |
| `stock.py` | `/api/stock` | Warehouse & salesman stock ledger, van loading passes, discrepancy reports & review |
| `purchasing.py` | `/api/purchasing` | Suppliers, POs, GRNs, supplier bills, supplier payments, advance reconciliation, returns |
| `production.py` | `/api/production` | Raw materials, receiving, dal milling, recipes v2, batches, packaging, dispatch, legacy cost resolution |
| `accounting.py` | `/api/accounting` | Chart of accounts, manual & automated journals, reversals, trial balance, P&L, balance sheet |
| `expenses.py` | `/api/expenses` | Expense submission, Owner/PA review & approval, cash-reducing expense tracking |
| `closing.py` | `/api/closing` | Daily salesman cash closing, variance flagging, manager reconciliation |
| `visits.py` | `/api/visits` | Shop visits, outcomes, follow-ups |
| `workforce.py` | `/api/workforce` | Employee attendance, tasks, freelancer projects/milestones, labour register/wages, salary structures, payroll runs, disbursements & receipts |
| `salary.py` | `/api/salary` | Legacy/stage-10 salary & incentive views |
| `workspace.py` | `/api/workspace` | Role-scoped self-service employee/salesman workspace |
| `quality.py` | `/api/quality` | Product lots, lot movements, QC checks & status transitions |
| `dashboard.py` | `/api/dashboard` | Live ledger-derived KPIs, alerts, operational summaries |
| `audit.py` | `/api/audit` | Read-only AuditLog queries (Owner-restricted) |
| `v2_erp.py` | `/api/v2` | Schema governance status, CA policy registry, write-block diagnostics |
| `main.py` | `/health`, `/api/health*` | Liveness, authenticated diagnostics (secret-redacted), tab/schema verification, Owner backup export |

---

## 3. Google Apps Script Gateway Integration Contract

The backend sends signed POST envelopes to `SALES_APPS_SCRIPT_WEBAPP_URL` via `backend/app/apps_script_bridge.py`:

- **Headers / Auth:** HMAC-SHA256 signature computed using `SALES_APPS_SCRIPT_SHARED_SECRET` over canonical request metadata (`action`, `target_tab`, `nonce`, `correlation_id`, `timestamp`, payload digest).
- **Centralized Action Registry:** `backend/app/action_registry.py` defines every allowed governed action, its allowed target tabs, ID allocation requirements, and post-write read-back verification contract.
- **Response Echo Validation:** Every gateway response must echo `action`, `target_tab`, `nonce`, and `correlation_id` and return confirmed status; mismatches fail closed.
- **External Dependency (`DB-008`):** The remote `WebAppBridge.gs` implementation is hosted outside this repository. Local testing verifies the complete client-side envelope, preflight guards, action allowlist, response echo validation, and read-back verification via `backend/tests/v2_test_harness.py` (`LocalAppsScriptSimulator`). Remote Apps Script `LockService` atomicity and live `doPost` behavior must be audited when `WebAppBridge.gs` is provided.

---

## 4. Security Controls Summary

- **Passwords:** PBKDF2-SHA256 (100,000 iterations, random 16-byte salt, constant-time comparison). Plaintext and legacy SHA-256 hashes are rejected.
- **Tokens & Revocation:** HS256 JWT with `jti`, `iat`, `exp`. Every authenticated request checks both `RevokedTokens` and `AuthUsers.sessions_revoked_at` with `fresh=True` (no cache fallback).
- **Account Status (`AUTH-03`):** `is_account_active()` returns `True` strictly for explicit active values (`True`, `1`, `"true"`, `"1"`, `"yes"`, `"active"`). `None`, blank, `False`, `0`, `"inactive"`, `"suspended"`, or malformed values fail closed.
- **Diagnostic Sanitization:** `_sanitize_diagnostic_error()` redacts `SALES_GOOGLE_SPREADSHEET_ID`, `SALES_GOOGLE_SERVICE_ACCOUNT_FILE`, `SALES_JWT_SECRET`, `SALES_APPS_SCRIPT_SHARED_SECRET`, `SALES_APPS_SCRIPT_WEBAPP_URL`, PEM private keys, service account emails, and `/etc/secrets/*.json` paths before returning any diagnostic payload.
- **Production Startup Guard:** `assert_runtime_config()` refuses to start in `SALES_ENV=production` if `SALES_JWT_SECRET` is missing/weak (<32 chars), CORS contains `*`, or Google Sheets ID/credentials are missing.
- **RBAC:** Enforced strictly on backend endpoints (`require_owner`, `require_manager`, `require_purchasing_*`, `require_production_*`, `_reject_auditor`).

---

## 5. Troubleshooting & Operational Health Checks

| Endpoint | Auth | Purpose |
|---|---|---|
| `GET /health` or `GET /api/health` | Public | Liveness & Sheets connection summary (minimal, zero secret leakage) |
| `GET /api/health/details` | Owner / PA | Storage configuration status & redacted diagnostics |
| `POST /api/health/reconnect` | Owner / PA | Re-establish Google Sheets read-only client connection |
| `GET /api/health/verify-tabs` | Owner / PA | Verify accessibility of all required tabs |
| `GET /api/health/schema-compatibility` | Owner / PA | Inspect live Row-1 headers against registered schema expectations |
| `GET /api/health/backup` | Owner only | Read-only JSON export of all managed tabs (credential fields stripped) |

### Common Fail-Closed States
- **`503 STORAGE_DISCONNECTED`:** Google Sheets credentials or Spreadsheet ID missing/unreachable. Check `/api/health/details`.
- **`503 APPS_SCRIPT_DISABLED` / `APPS_SCRIPT_UNCONFIGURED`:** `SALES_APPS_SCRIPT_ENABLED=true`, `SALES_APPS_SCRIPT_WEBAPP_URL`, or `SALES_APPS_SCRIPT_SHARED_SECRET` not set.
- **`503 SCHEMA_CONFLICT_BLOCKED` (`DB-007`):** Target table is one of the 12 conflicting core tabs awaiting Owner Row-1 header verification via `SALES_APPROVED_CORE_SCHEMA_RECONCILIATIONS_JSON`.
- **`504 READ_BACK_UNCONFIRMED`:** Gateway returned success, but fresh Sheets read-back did not confirm the committed record. Safe to retry with the same `X-Idempotency-Key` / nonce.
