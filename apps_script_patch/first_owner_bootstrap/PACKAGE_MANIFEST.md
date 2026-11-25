# First-Owner Secure Initialization — Isolated Apps Script Package Manifest (Lock-Hardened)

## Status
**ISOLATED SOURCE PACKAGE — ALL 4 SOURCE-INTEGRATION BLOCKERS + SCRIPTLOCK OWNERSHIP HARDENING RESOLVED.**
**NOT YET MERGED, TESTED, PROVISIONED, OR DEPLOYED** (strictly awaiting Owner merge & testing authorization).

Reconciled against:
- Workspace file: `/public/assets/aistudio/Kawad_Swad_Bound_Apps_Script_Source_COMPLETE_VERBATIM_EXPORT_c019c467.txt` (1,601,506 bytes, 14,747 lines, 43/43 verbatim sections)
- Referenced original ZIP SHA-256: `68c80c8a0c9d64dfd80716bfe39a92c1d0541dbfcc3855a03ab1a994ea6b50d7`
- Embedded manifest (`SOURCE_INVENTORY_AND_SHA256.txt`, export lines 13855–13909): 40 `.js`, 1 `.html` (`ErpSidebar.html`), `appsscript.json`, plus `SOURCE_INVENTORY_AND_SHA256.txt` (43 total archive entries).

## Package Contents (5 Isolated Files)
1. `Config_AuthUsersPrefixPatch.js` — **Mandatory** 2-line surgical patch spec for bound `Config.js` registering `AUTH_USERS: 'AuthUsers'` inside `TABS: Object.freeze({...})` and `AuthUsers: 'AUTH'` inside `ID_PREFIXES: Object.freeze({...})`. Preserves 100% of `KS_CONFIG`'s existing frozen immutability structure.
2. `IdAllocator_LockOwnershipPatch.js` — **Mandatory** backward-compatible lock-ownership refactor for bound `IdAllocator.js`:
   - Extracts `ksAllocateIdLocked_(targetTabName, nonce)` which asserts `LockService.getScriptLock().hasLock() === true` and **never acquires or releases `ScriptLock`**.
   - Preserves `ksAllocateId(targetTabName, nonce, opts)` with 100% identical behavior for all existing 2-arg callers, while supporting optional `{ callerHoldsLock: true }`.
3. `AuditAndExceptions_LockOwnershipPatch.js` — **Mandatory** backward-compatible lock-ownership & fail-closed audit patch for bound `AuditAndExceptions.js`:
   - Introduces `ksLogAuditStrictLocked_(action, entityType, entityId, opts)` which asserts `hasLock() === true`, calls `ksAllocateIdLocked_` (never drops `ScriptLock`), persists via `SafeWriter.js`, and **throws on any error** (never swallows missing-tab or write exceptions like legacy `ksLogAudit_`).
   - Preserves existing `ksLogAudit_` 100% backward-compatible for all existing callers.
4. `BootstrapOwnerHandler.js` — Governed `BOOTSTRAP_FIRST_OWNER` handler (`ksBootstrapFirstOwner_`) executing under **one uninterrupted `ScriptLock`** from entry through completion latch (zero lock release/reacquire), calling `ksAllocateIdLocked_`, `ksAppendAndVerifyRow_` (5-arg), and `ksLogAuditStrictLocked_` + independent `AuditLog` read-back verification, plus durable `KS_OWNER_BOOTSTRAP_IN_PROGRESS` write-ahead crash-recovery quarantine.
5. `WebAppBridge_BootstrapIntegration.js` — Mandatory body-level HMAC-SHA256 verification (`ksVerifySignedBridgeEnvelope_`) using verified Script Property `SALES_APPS_SCRIPT_SHARED_SECRET` (`WebAppBridge.js:22`), plus pre-lock `ksDispatchBootstrapFirstOwner_` hook inserted strictly BEFORE `WebAppBridge.js:71` (`lock.waitLock` / `ksFindByNonce_`).

## Uninterrupted ScriptLock Ownership & Crash-Recovery Guarantees
- **Single Lock Owner:** `ksBootstrapFirstOwner_` acquires `ScriptLock` ONCE via `lock.tryLock(30000)` and releases it ONCE in its single outer `finally` block.
- **Zero Lock Drops:** Neither `ksAllocateIdLocked_` (called for `Users`, `AuthUsers`, and nested inside `ksLogAuditStrictLocked_` for `AuditLog`) nor `ksAppendAndVerifyRow_` ever calls `lock.releaseLock()`. Every stage asserts `lock.hasLock() === true`.
- **Simultaneous Request Serialization:** Two concurrent bootstrap requests cannot both pass the empty-state check or allocate competing Owner IDs; the second request blocks on `tryLock(30000)` until the first completes (or quarantines) and releases the lock, then observes `KS_OWNER_BOOTSTRAP_COMPLETED = "true"` (or `RECOVERY_REQUIRED`).
- **Mid-Transaction Crash Detection (`KS_OWNER_BOOTSTRAP_IN_PROGRESS`):** Written to Script Properties strictly BEFORE the first ID allocation and cleared ONLY on completion or quarantine. If Apps Script terminates the process abruptly after writing `Users` (or `AuthUsers`) and before writing `AuditLog` or setting `COMPLETED`, the next request holding `ScriptLock` observes `IN_PROGRESS === "true"` (and/or asymmetric `Users`/`AuthUsers` row counts), immediately quarantines into `KS_OWNER_BOOTSTRAP_RECOVERY_REQUIRED = "true"` (`BOOTSTRAP_CRASHED_MID_TRANSACTION`), captures any orphaned `user_id`, burns the one-time token, and returns `RECOVERY_REQUIRED` (HTTP 409, `retryable: false`).
- **Fail-Closed Mandatory Audit:** `ksLogAuditStrictLocked_` throws on any failure AND `ksBootstrapWriteAndVerifyAuditLocked_` reads back `AuditLog` confirming `audit_id`, `action`, `entity_type`, `entity_id`, and `related_record_id === nonce` BEFORE setting `KS_OWNER_BOOTSTRAP_COMPLETED = "true"`.

## Required Script Properties (Names Only — Provisioned Out-of-Band by Owner)
1. Permanent bridge secret (`WebAppBridge.js:22`):
   - `SALES_APPS_SCRIPT_SHARED_SECRET` (>= 32 chars; never reused as bootstrap secret or JWT secret)
2. Temporary one-time bootstrap window (deleted automatically upon confirmation or quarantine):
   - `KS_OWNER_BOOTSTRAP_TOKEN_HASH` (64-char lowercase hex SHA-256)
   - `KS_OWNER_BOOTSTRAP_EXPIRES_AT` (ISO-8601 UTC timestamp)
3. Automatic state/recovery properties (managed by `ksBootstrapFirstOwner_`):
   - `KS_OWNER_BOOTSTRAP_COMPLETED`, `KS_OWNER_BOOTSTRAP_RECOVERY_REQUIRED`, `KS_OWNER_BOOTSTRAP_RECOVERY_REASON`, `KS_OWNER_BOOTSTRAP_IN_PROGRESS`, `KS_OWNER_BOOTSTRAP_IN_PROGRESS_NONCE`, `KS_OWNER_BOOTSTRAP_IN_PROGRESS_PAYLOAD_HASH`, `KS_OWNER_BOOTSTRAP_IN_PROGRESS_STARTED_AT`, `KS_OWNER_BOOTSTRAP_NONCE`, `KS_OWNER_BOOTSTRAP_PAYLOAD_HASH`, `KS_OWNER_BOOTSTRAP_USER_ID`, `KS_OWNER_BOOTSTRAP_COMPLETED_AT`

## Remaining Non-Source / Operational Blockers (Out of Current Scope — Still Locked)
1. **Authorized Merge:** Apply the 3 surgical patches (`Config.js`, `IdAllocator.js`, `AuditAndExceptions.js`), the `doPost(e)` hook (`WebAppBridge.js`), and add `BootstrapOwnerHandler.js` + `WebAppBridge_BootstrapIntegration.js` in an Owner-authorized merge step.
2. **Apps Script HTTP 302 Redirect vs `_NoRedirectHandler`:** Verify during Owner-authorized staging testing how Google Apps Script's HTTP 302 redirect interacts with `backend/app/apps_script_bridge.py:2844`.
3. **Separate Mission 51B-1R-E2G Hardening for Non-Bootstrap Actions:** Pre-existing E2G defects on ordinary `WebAppBridge.js:71-124` routes remain governed under the separate E2G workstream.
4. **Authorized Testing & Out-of-Band Secret Provisioning:** Strictly locked pending Owner authorization.
