# Kawad Swad ERP — Phase 1.6 Security Changes Summary

This document summarizes every security hardening change implemented during Phase 1.6 to close verified security defects from Phase 1.5 without modifying live infrastructure or introducing new dependencies.

---

## 1. Fail-Closed Schema Write Gating (`P1.5-001`, `P1.5-005`)
- **Closed Secondary-Tab Bypass (`backend/app/apps_script_bridge.py`):** `execute_governed_write()` no longer permits caller-supplied `invalidate_tabs` subsets to shrink schema validation coverage. Every governed write validates the complete union of `target_tab`, all `spec.allowed_invalidate_tabs`, allowlisted `requested_inv`, and all `spec.readback.child_checks` tabs before dispatching any request.
- **Hardened Owner Reconciliation Unlock (`backend/app/schema_registry.py`):** Both runtime `approve_core_schema_reconciliation()` and env-var `SALES_APPROVED_CORE_SCHEMA_RECONCILIATIONS_JSON` now enforce strict canonical header validation (`validate_reconciliation_headers()`) against `REQUIRED_TABS` (exact leading column order), all declared `missing_from_required_tabs` variance fields, zero unexpected columns, and exact `physical_headers` equality when supplied. Arbitrary fake headers can no longer unlock blocked core tables.

## 2. Authentication & Session Revocation Hardening (`P1.5-003`, `P1.5-009`)
- **Fail-Closed Token Revocation (`backend/app/auth.py`):** Replaced fail-open `except Exception: return False` with `check_token_revocation()` and `RevocationVerificationError`. Any missing `RevokedTokens` sheet, read exception, or malformed (non-list / non-dict) payload denies access fail-closed with `HTTP 503` (`REVOCATION_STORE_UNAVAILABLE` or `REVOCATION_DATA_MALFORMED`).
- **Fail-Closed User Session Timestamp (`backend/app/auth.py`):** Unparseable/corrupted `sessions_revoked_at` values on `AuthUsers` now fail closed with `HTTP 401` instead of silently passing.
- **Unified Account Deactivation Enforcement (`backend/app/auth.py`, `backend/app/routers/auth.py`):** Shared `is_account_deactivated()` consistently rejects `"false"`, `"0"`, `"no"`, and `""` across both `/login` (`HTTP 403`) and `get_current_user()` (`HTTP 401`).
- **Sanitized Auth Error Responses & Explicit Logout Persistence Warning (`backend/app/routers/auth.py`):** Removed raw exception text from `HTTP 503` login responses and returned `persisted: False` + explicit `warning` on `/logout` when Apps Script persistence does not confirm.
- **Configurable Brute-Force Lockout & Production Connection Guard (`backend/app/config.py`, `backend/app/routers/auth.py`, `backend/app/auth.py`):** Made lockout threshold (`SALES_LOGIN_MAX_ATTEMPTS`) and window (`SALES_LOGIN_LOCKOUT_SECONDS`) configurable with dynamically formatted lockout messages; hardened `require_sheets_connection()` to fail closed (`HTTP 503`) if `SALES_ENV == "production"` and `SALES_GOOGLE_SPREADSHEET_ID` is empty.
- **Test JWT Fidelity (`backend/tests/__init__.py`):** Mock `jwt.decode` fallback now verifies HMAC-SHA256 signatures via `hmac.compare_digest` and rejects expired tokens (`exp`).

## 3. Pre-Write Identifier & Cross-Table Collision Enforcement (`P1.5-002`, `P1.5-007`)
- **Pre-Write Rejection Before Mutation (`backend/app/apps_script_bridge.py`):** Added `_preflight_validate_payload_ids()` running BEFORE `is_configured()` and HTTP POST. Blocks invalid prefixes (`422`), blank target keys on single-key updates (`422`), duplicate primary IDs (`409`), cross-table `Payments`/`SalaryReceipts` and `SalaryIncentives`/`SalaryPayments` collisions (`409`), and invalid/duplicate child row IDs (`SalaryReceipts`, `SaleItems`, `JournalLines`, `SalesOrderItems`) with zero bridge requests emitted.
- **Non-Locked Table Prefix Guard (`backend/app/apps_script_bridge.py`, `backend/app/action_registry.py`):** Removed the `if not effective_prefix: return True` short-circuit in `_validate_id_format()` so `COLLIDING_LEGACY_PREFIX_TABS` (`SalaryIncentives`, `SalaryReceipts`) and cross-table `LOCKED_32_ID_PREFIXES` collisions are always enforced while eliminating the `CREATE_SALARY_INCENTIVE` deadlock.

## 4. Least-Privilege Google Sheets OAuth Scope & Offline Write-Path Lockdown (`P1.5-008`)
- **Read-Only Sheets OAuth Scope (`backend/app/sheets.py`):** Replaced read-write `spreadsheets` and `drive.file` OAuth scopes with `SHEETS_OAUTH_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]`, enforcing Single-Write-Owner at the OAuth credential boundary.
- **Fail-Closed Offline Migration & Legacy Scripts (`backend/app/workforce_migration.py`, `backend/scripts/*.py`):** Gated `execute_workforce_migration()` (non-dry-run) and `rollback_workforce_migration()` behind explicit `SALES_ALLOW_OFFLINE_SHEETS_MIGRATION=1` (with `SALES_TESTING=1` allowed for isolated mock unit tests). Marked `bootstrap_owner.py`, `reset_password.py`, and `update_sheets_recipe_master.py` as `LEGACY_DIRECT_WRITE_DISABLED` failing closed by default unless explicitly opted in for offline maintenance.

## 5. Honest Frontend Fail-Closed UX (`P1.5-006`)
- **Blocked State Normalization (`src/services/api.ts`, `src/views/ErpOperationsHubView.tsx`):** Backend `BLOCKED_PENDING_OWNER_SETUP` and all 5 blocked error codes always normalize to non-retryable blocked UI states (`retryable=false`), bare `503` never maps to success, and unrecognized/blocked/pending schema statuses can never fall back to green verified badges.
