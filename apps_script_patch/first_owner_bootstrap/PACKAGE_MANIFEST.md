# First-Owner Secure Initialization — Isolated Apps Script Package Manifest (Reconciled Draft)

## Status
**ISOLATED SOURCE PACKAGE ONLY — NOT READY FOR LIVE MERGE OR DEPLOYMENT.**
`Kawad_Swad_Bound_Apps_Script_Source_READONLY.zip` (SHA-256 `68c80c8a0c9d64dfd80716bfe39a92c1d0541dbfcc3855a03ab1a994ea6b50d7`) is NOT present in this workspace. Exact line-level compatibility with the bound Apps Script project remains unverified until the raw archive is inspected.

## Package Contents
1. `BootstrapOwnerHandler.js` — Governed `BOOTSTRAP_FIRST_OWNER` write handler (`ksBootstrapFirstOwner_`) with zero `SafeWriter` or `AuditAndExceptions` fallback bypasses, strict `KS_OWNER_BOOTSTRAP_RECOVERY_REQUIRED` quarantine, and mandatory audit before completion latch.
2. `WebAppBridge_BootstrapIntegration.js` — Mandatory body-level HMAC-SHA256 verification (`ksVerifySignedBridgeEnvelope_`) over FastAPI's exact ASCII-escaped `canonical_envelope` string (`contract_version = "2.0"`, `signature_alg = "HMAC-SHA-256"`, `±300s` timestamp skew, outer-vs-signed tamper detection) + closed `BOOTSTRAP_FIRST_OWNER` routing (`ksRouteGovernedWriteWithBootstrap_`).

## Preserved Google Sheets Schema (Zero Column Changes)
- `Users` (25 columns, verified from `backend/app/sheets.py:128-133`):
  `user_id, full_name, username, role, mobile, email, active, created_at, notes, employment_type, designation, department, reporting_manager_id, joining_date, employment_status, salary_frequency, salary_structure_id, address, emergency_contact, bank_details, document_references, updated_at, created_by, effective_from, effective_to`
- `AuthUsers` (9 columns, verified from `backend/app/sheets.py:127`):
  `auth_id, user_id, username, password_hash, role, active, created_at, must_change_password, sessions_revoked_at`
- `IdAllocations` (5 columns, verified from `backend/app/sheets.py:124`):
  `allocation_id, tab_name, allocated_id, nonce, created_at`

## Required Script Properties (Names Only — Provisioned Out-of-Band by Owner)
1. Permanent bridge secret (per Mission 51B-1R-E2D §3.1):
   - `SALES_APPS_SCRIPT_SHARED_SECRET` (>= 32 chars; must match backend `SALES_APPS_SCRIPT_SHARED_SECRET`; never reused as bootstrap secret or JWT secret)
2. Temporary one-time bootstrap window (deleted automatically by `ksBootstrapFirstOwner_` upon confirmation or quarantine):
   - `KS_OWNER_BOOTSTRAP_TOKEN_HASH` (64-char lowercase hex SHA-256 of the one-time bootstrap secret)
   - `KS_OWNER_BOOTSTRAP_EXPIRES_AT` (ISO-8601 UTC timestamp, e.g. 30-minute window)
3. Permanent completion / quarantine state (managed automatically by `ksBootstrapFirstOwner_`):
   - `KS_OWNER_BOOTSTRAP_COMPLETED` (`true` only after Users + AuthUsers + read-back + mandatory AuditLog all succeed)
   - `KS_OWNER_BOOTSTRAP_RECOVERY_REQUIRED` (`true` if partial write, read-back failure, or audit failure occurs; blocks blind retries until Owner reconciles)
   - `KS_OWNER_BOOTSTRAP_RECOVERY_REASON`
   - `KS_OWNER_BOOTSTRAP_NONCE`
   - `KS_OWNER_BOOTSTRAP_PAYLOAD_HASH`
   - `KS_OWNER_BOOTSTRAP_USER_ID`
   - `KS_OWNER_BOOTSTRAP_COMPLETED_AT`

## Unresolved Pre-Merge Blockers
1. **Raw Bound Apps Script Archive Missing:** Inspect all raw files in `Kawad_Swad_Bound_Apps_Script_Source_READONLY.zip` before merging.
2. **`AuthUsers` Prefix Conflict (`AUTH` vs `AUT`):** Resolve against raw `IdAllocator.js` (and verify whether `AuthUsers` is registered in `IdAllocator.js` at all).
3. **Unverified Helper Signatures:** Confirm exact argument order and return types of `ksAllocateId` (`IdAllocator.js:6`), `ksAppendAndVerifyRow_` (`SafeWriter.js:44`), and `ksLogAudit_` (`AuditAndExceptions.js:60`).
4. **Unverified `WebAppBridge.js` Merge Boundaries:** Inspect raw `WebAppBridge.js` (`doPost`, `ksRouteGovernedWrite_`, `ksFindByNonce_`, `ksRecordIdAllocation_`, `ksWriteCanonicalRowByHeaders_`) to verify non-breaking merge for existing governed actions and close E2D C1/H1–H5.
5. **Apps Script HTTP 302 Redirect vs `_NoRedirectHandler`:** Verify during authorized staging testing how Google Apps Script's 302 redirect to `script.googleusercontent.com/macros/echo` interacts with `backend/app/apps_script_bridge.py:2844`.
6. **Authorized Testing & Out-of-Band Deployment Governance:** Offline unit tests, live staging tests, secret provisioning, and deployment reconciliation remain locked pending separate Owner authorization.
