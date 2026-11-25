# First-Owner Secure Initialization — Isolated Apps Script Package Manifest

## Package Contents
1. `BootstrapOwnerHandler.js` — Governed `BOOTSTRAP_FIRST_OWNER` write handler (`ksBootstrapFirstOwner_`).
2. `WebAppBridge_BootstrapIntegration.js` — Mandatory body-level HMAC-SHA256 verification (`ksVerifySignedBridgeEnvelope_`) over FastAPI's exact `canonical_envelope` string + closed route dispatcher (`ksRouteGovernedWriteWithBootstrap_`).

## Preserved Google Sheets Schema (Zero Column Changes)
- `Users` (25 columns, verified from `backend/app/sheets.py`):
  `user_id, full_name, username, role, mobile, email, active, created_at, notes, employment_type, designation, department, reporting_manager_id, joining_date, employment_status, salary_frequency, salary_structure_id, address, emergency_contact, bank_details, document_references, updated_at, created_by, effective_from, effective_to`
- `AuthUsers` (9 columns, verified from `backend/app/sheets.py`):
  `auth_id, user_id, username, password_hash, role, active, created_at, must_change_password, sessions_revoked_at`
- `IdAllocations` (5 columns, verified from `backend/app/sheets.py`):
  `allocation_id, tab_name, allocated_id, nonce, created_at`

## Required Script Properties (Names Only — Provisioned Out-of-Band by Owner)
1. Permanent bridge secret (pre-existing/Mission 51B-1R-E2G):
   - `KS_APPS_SCRIPT_SHARED_SECRET` (>= 32 chars; must match backend `SALES_APPS_SCRIPT_SHARED_SECRET`, never reused as bootstrap secret)
2. Temporary one-time bootstrap window (deleted automatically by `ksBootstrapFirstOwner_` upon confirmation):
   - `KS_OWNER_BOOTSTRAP_TOKEN_HASH` (64-char lowercase hex SHA-256 of the one-time bootstrap secret)
   - `KS_OWNER_BOOTSTRAP_EXPIRES_AT` (ISO-8601 UTC timestamp, e.g. 30-minute window)
3. Permanent completion latch (set automatically by `ksBootstrapFirstOwner_`; keep permanently):
   - `KS_OWNER_BOOTSTRAP_COMPLETED` = `true`
   - `KS_OWNER_BOOTSTRAP_NONCE`
   - `KS_OWNER_BOOTSTRAP_PAYLOAD_HASH`
   - `KS_OWNER_BOOTSTRAP_USER_ID`
   - `KS_OWNER_BOOTSTRAP_COMPLETED_AT`

## Pre-Merge Verification Checklist (Blocked Pending Raw Bound Apps Script ZIP)
Before pasting into the bound Google Apps Script project, inspect raw `Kawad_Swad_Bound_Apps_Script_Source_READONLY.zip` to confirm:
1. Exact parameter signature and return shape of `ksAllocateId(...)` in `IdAllocator.js`.
2. Exact table-prefix mapping for `AuthUsers` in `IdAllocator.js` (`AUTH` per `backend/app/sheets.py:63` vs `AUT` in legacy simulator `backend/tests/v2_test_harness.py:1840`).
3. Exact parameter signature of `ksAppendAndVerifyRow_(...)` in `SafeWriter.js`.
4. Exact parameter signature of `ksLogAudit_(...)` in `AuditAndExceptions.js`.
5. Exact Script Property key name used by the bound `WebAppBridge.js` for the HMAC shared secret and exact existing `doPost(e)` dispatcher function name.
6. Whether Google Apps Script's HTTP 302 redirect from `script.google.com/macros/s/.../exec` to `script.googleusercontent.com/macros/echo` conflicts with `_NoRedirectHandler` in `backend/app/apps_script_bridge.py:2844` during live staging testing.
