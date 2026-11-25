# First-Owner Secure Initialization — Isolated Apps Script Package Manifest (Source-Reconciled)

## Status
**ISOLATED SOURCE PACKAGE — ALL 4 SOURCE-INTEGRATION BLOCKERS RESOLVED AGAINST VERBATIM 43-FILE EXPORT.**
**NOT YET MERGED, TESTED, PROVISIONED, OR DEPLOYED** (strictly awaiting Owner merge & testing authorization).

Reconciled against:
- Workspace file: `/public/assets/aistudio/Kawad_Swad_Bound_Apps_Script_Source_COMPLETE_VERBATIM_EXPORT_c019c467.txt` (1,601,506 bytes, 14,747 lines, 43/43 verbatim sections)
- Referenced original ZIP SHA-256: `68c80c8a0c9d64dfd80716bfe39a92c1d0541dbfcc3855a03ab1a994ea6b50d7`
- Embedded manifest (`SOURCE_INVENTORY_AND_SHA256.txt`, export lines 13855–13909): 40 `.js`, 1 `.html` (`ErpSidebar.html`), `appsscript.json`, plus `SOURCE_INVENTORY_AND_SHA256.txt` (43 total archive entries).

## Package Contents
1. `Config_AuthUsersPrefixPatch.js` — **Mandatory** 2-line surgical patch spec for bound `Config.js` registering `AUTH_USERS: 'AuthUsers'` in `KS_CONFIG.TABS` and `AuthUsers: 'AUTH'` in `KS_CONFIG.ID_PREFIXES` (required because `IdAllocator.js:7-9` rejects any table missing from frozen `KS_CONFIG.ID_PREFIXES`).
2. `BootstrapOwnerHandler.js` — Governed `BOOTSTRAP_FIRST_OWNER` write handler (`ksBootstrapFirstOwner_`) reconciled 100% to:
   - `ksAllocateId(targetTabName, nonce)` (`IdAllocator.js:7`, export line 4376) with `ScriptLock` re-acquisition after `IdAllocator.js:92` `lock.releaseLock()`,
   - 5-arg `ksAppendAndVerifyRow_(ss, tabName, recordObj, primaryKeyField, mandatoryFields)` (`SafeWriter.js:44`, export line 13395),
   - 4-arg `ksLogAudit_(action, entityType, entityId, opts)` (`AuditAndExceptions.js:60`, export line 344) plus mandatory `AuditLog` read-back verification (mitigating silent exception swallowing at `AuditAndExceptions.js:64,89-91`),
   - Exact `USR-` and `AUTH-` prefix validation,
   - Zero symbol collisions across all 40 bound `.js` files.
3. `WebAppBridge_BootstrapIntegration.js` — Mandatory body-level HMAC-SHA256 verification (`ksVerifySignedBridgeEnvelope_`) using verified Script Property `SALES_APPS_SCRIPT_SHARED_SECRET` (`WebAppBridge.js:22`), plus pre-lock `ksDispatchBootstrapFirstOwner_` hook inserted strictly BEFORE `WebAppBridge.js:71` (`lock.waitLock` / `ksFindByNonce_`) so bootstrap bypasses legacy `ksFindByNonce_`, duplicate `ksRecordIdAllocation_`, duplicate `ksLogAudit_`, and unconditional `CONFIRMED` wrapping without breaking existing governed actions.

## Resolved Source-Integration Blockers (All 4 Closed)
1. **Complete 43-File Source Inventory & Compatibility Check — RESOLVED:** All 43 verbatim sections inspected; zero symbol-name collisions; `Users` 25-column live headers confirmed via `KS_P3_MD_Header_Audit.js:25` (export line 5974); `AuthAndMenu.js:4-69` (`OWNER_ADMIN`, `active`, `email`) confirmed compatible.
2. **`AuthUsers` Prefix (`AUTH` vs `AUT`) — RESOLVED (`AUTH`):**
   - `Code.js:2129` (`KS_MASTER.ID_RULES`, export line 2877): `Users:['user_id','USR'], AuthUsers:['auth_id','AUTH']`.
   - `backend/app/sheets.py:63`: `"AuthUsers": "AUTH"`.
   - `Config.js:29-117` (export lines 3034–3122) currently omits `AuthUsers` from frozen `KS_CONFIG.ID_PREFIXES`, which would cause `IdAllocator.js:7-9` to throw; resolved by `Config_AuthUsersPrefixPatch.js` + upfront `KS_CONFIG.ID_PREFIXES.AuthUsers === 'AUTH'` pre-flight check in `BootstrapOwnerHandler.js`.
   - `"AUT"` appears ONLY in offline test-simulator helpers (`backend/tests/v2_test_harness.py:1009,1976,1987`), never in bound Apps Script or production FastAPI code.
   - `IdAllocator.js:65` format (`USR-YYYYMMDD-00001` / `AUTH-YYYYMMDD-00001`) matches FastAPI `backend/app/schema_registry.py:357` (`^([A-Z]{2,6})-[A-Z0-9_-]{3,}$`).
3. **Exact Helper Signatures & Return Contracts — RESOLVED:**
   - `ksAllocateId(targetTabName, nonce)` (`IdAllocator.js:7`, export line 4376) -> `{ status, allocation_id, allocated_id, tab_name, nonce }`. Caught and mitigated premature `ScriptLock` release at `IdAllocator.js:92`.
   - `ksAppendAndVerifyRow_(ss, tabName, recordObj, primaryKeyField, mandatoryFields)` (`SafeWriter.js:44`, export line 13395) -> `{ row, record }`. Fixed 3-arg draft bug to exact 5-arg call.
   - `ksLogAudit_(action, entityType, entityId, opts)` (`AuditAndExceptions.js:60`, export line 344) -> `undefined` (silently swallows missing tab & exceptions at lines 64, 89–91). Fixed 8-arg draft bug to exact 4-arg call AND added mandatory post-write `AuditLog` read-back verification.
4. **Exact `WebAppBridge.js` `doPost(e)` Integration Point — RESOLVED:**
   - Verified verbatim `WebAppBridge.js:6-124` (export lines 13921–14039).
   - Mandatory `ksVerifySignedBridgeEnvelope_(e)` replaces lines 9–50; `if (action === 'BOOTSTRAP_FIRST_OWNER') return ksBridgeJson_(ksDispatchBootstrapFirstOwner_(req));` inserts before line 71; existing governed actions on lines 71–124 remain non-breaking.

## Preserved Google Sheets Schema (Zero Column Changes)
- `Users` (25 columns, verified from `KS_P3_MD_Header_Audit.js:25` and `backend/app/sheets.py:128-133`):
  `user_id, full_name, role, mobile, email, active, created_at, notes, username, employment_type, designation, department, reporting_manager_id, joining_date, employment_status, salary_frequency, salary_structure_id, address, emergency_contact, bank_details, document_references, updated_at, created_by, effective_from, effective_to`
- `AuthUsers` (9 columns, verified from `backend/app/sheets.py:127`):
  `auth_id, user_id, username, password_hash, role, active, created_at, must_change_password, sessions_revoked_at`
- `IdAllocations` (5 columns, verified from `Config.js:121`):
  `allocation_id, tab_name, allocated_id, nonce, created_at`
- `AuditLog` (12 columns, verified from `Config.js:122-126`):
  `audit_id, event_datetime, actor_user_id, action, entity_type, entity_id, field_changed, old_value, new_value, reason, approved_by_user_id, related_record_id`

## Required Script Properties (Names Only — Provisioned Out-of-Band by Owner)
1. Permanent bridge secret (`WebAppBridge.js:22`):
   - `SALES_APPS_SCRIPT_SHARED_SECRET` (>= 32 chars; matches backend `SALES_APPS_SCRIPT_SHARED_SECRET`; never reused as bootstrap secret or JWT secret)
2. Temporary one-time bootstrap window (deleted automatically by `ksBootstrapFirstOwner_` upon confirmation or quarantine):
   - `KS_OWNER_BOOTSTRAP_TOKEN_HASH` (64-char lowercase hex SHA-256 of the one-time bootstrap secret)
   - `KS_OWNER_BOOTSTRAP_EXPIRES_AT` (ISO-8601 UTC timestamp, e.g. 30-minute window)
3. Permanent completion / quarantine state (managed automatically by `ksBootstrapFirstOwner_`):
   - `KS_OWNER_BOOTSTRAP_COMPLETED`, `KS_OWNER_BOOTSTRAP_RECOVERY_REQUIRED`, `KS_OWNER_BOOTSTRAP_RECOVERY_REASON`, `KS_OWNER_BOOTSTRAP_NONCE`, `KS_OWNER_BOOTSTRAP_PAYLOAD_HASH`, `KS_OWNER_BOOTSTRAP_USER_ID`, `KS_OWNER_BOOTSTRAP_COMPLETED_AT`

## Remaining Non-Source / Operational Blockers (Out of Current Scope — Still Locked)
1. **Authorized Merge of `Config.js` + `WebAppBridge.js` + New Modules:** Must apply `Config_AuthUsersPrefixPatch.js` to bound `Config.js`, apply the exact `doPost(e)` hook to bound `WebAppBridge.js`, and add `BootstrapOwnerHandler.js` + `WebAppBridge_BootstrapIntegration.js` in an Owner-authorized merge step.
2. **Apps Script HTTP 302 Redirect vs `_NoRedirectHandler`:** Verify during Owner-authorized staging testing how Google Apps Script's HTTP 302 redirect (`script.google.com/macros/s/.../exec` -> `script.googleusercontent.com/macros/echo`) interacts with `backend/app/apps_script_bridge.py:2844`.
3. **Separate Mission 51B-1R-E2G Hardening for Non-Bootstrap Actions:** Ordinary governed actions in `WebAppBridge.js:71-124` still carry pre-existing E2G defects (e.g., `ksFindByNonce_` H4, `ksWriteCanonicalRowByHeaders_` H2/H3, `ksRecordIdAllocation_` H5, mismatched engine names at `WebAppBridge.js:145,157,160`, and `IdAllocator.js:92` nested lock release); those remain governed under the separate E2G workstream.
4. **Authorized Testing & Out-of-Band Secret Provisioning:** Offline pytest execution, live staging verification, secret provisioning, and deployment remain strictly locked pending Owner authorization.
