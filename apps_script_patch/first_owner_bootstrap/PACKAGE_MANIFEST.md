# First-Owner Secure Initialization — Isolated Apps Script Package Manifest (Lock-Hardened)

## Status
**IMPLEMENTATION & OFFLINE/VM VERIFICATION COMPLETE — BLOCKERS B1 AND B2 RESOLVED.**
**6 READY-TO-DEPLOY MERGED BOUND APPS SCRIPT FILES ASSEMBLED IN `merged_bound_files/`.**
*(Production Google Apps Script upload, Render deployment, secret provisioning, and live Owner login remain external to this sandbox and must be executed in the Owner's production environment.)*

Reconciled against:
- Workspace file: `/public/assets/aistudio/Kawad_Swad_Bound_Apps_Script_Source_COMPLETE_VERBATIM_EXPORT_c019c467.txt` (1,601,506 bytes, 14,747 lines, 43/43 verbatim sections)
- Referenced original ZIP SHA-256: `68c80c8a0c9d64dfd80716bfe39a92c1d0541dbfcc3855a03ab1a994ea6b50d7`
- Embedded manifest (`SOURCE_INVENTORY_AND_SHA256.txt`, export lines 13855–13909): 40 `.js`, 1 `.html` (`ErpSidebar.html`), `appsscript.json`, plus `SOURCE_INVENTORY_AND_SHA256.txt` (43 total archive entries).

## Package Contents
### Ready-to-Deploy Merged Bound Files (`merged_bound_files/` — see `MERGED_SHA256_MANIFEST.md`)
1. `merged_bound_files/Config.js` — Byte-exact verbatim `Config.js` + `AUTH_USERS: 'AuthUsers'` and `AuthUsers: 'AUTH'` inside existing `Object.freeze` literals.
2. `merged_bound_files/IdAllocator.js` — Byte-exact verbatim `IdAllocator.js` + `ksAllocateIdLocked_` + backward-compatible `ksAllocateId(targetTabName, nonce, opts)`.
3. `merged_bound_files/AuditAndExceptions.js` — Byte-exact verbatim `AuditAndExceptions.js` + `ksLogAuditStrictLocked_` + backward-compatible `callerHoldsLock` forwarding in `ksLogAudit_`.
4. `merged_bound_files/BootstrapOwnerHandler.js` — Governed `BOOTSTRAP_FIRST_OWNER` handler with uninterrupted `ScriptLock`, outer post-mutation `try/catch` guaranteeing `RECOVERY_REQUIRED` (Blocker B1), replay `AuditLog` check (B3), and early-crash `IdAllocations` fallback (B4).
5. `merged_bound_files/WebAppBridge_BootstrapIntegration.js` — Mandatory HMAC-SHA256 + `contract_version="2.0"` + `±300s` skew verification + defensive `RECOVERY_REQUIRED` dispatch catch (Blocker B1).
6. `merged_bound_files/WebAppBridge.js` — Byte-exact verbatim `WebAppBridge.js` wired with `ksVerifySignedBridgeEnvelope_(e)` and pre-lock `BOOTSTRAP_FIRST_OWNER` route.

### Backend Transport Fix (Blocker B2 Resolved)
- `backend/app/apps_script_bridge.py`: Replaced `_NoRedirectHandler` with `_AppsScriptEchoRedirectHandler`, following ONLY a single `GET` hop to `https://script.googleusercontent.com/macros/echo` with all sensitive headers and POST body stripped, rejecting all other redirects fail-closed, and classifying post-redirect echo HTTP failures as `PENDING_UNKNOWN` / `UNKNOWN` (never `FAILED`).

## Verified Test Evidence
- `node backend/tests/test_apps_script_bootstrap_vm.mjs`: 7/7 merged Apps Script VM security suites PASS.
- `PYTHONPATH=backend SALES_TESTING=1 python3 -m unittest backend/tests/test_first_owner_bootstrap.py backend/tests/test_owner_setup.py backend/tests/test_user_system_phase2.py backend/tests/test_mission51b1_transaction_safety.py backend/tests/test_tx_final_07_response_mismatch.py backend/tests/test_tx_final_08_readback_completeness.py -v`: 52/52 PASS.
- Frontend TypeScript check (`tsc --noEmit`) & Vite production build: PASS.

## Required Script Properties (Provisioned Out-of-Band by Owner During Production Window)
1. Permanent bridge secret (`WebAppBridge.js`):
   - `SALES_APPS_SCRIPT_SHARED_SECRET` (>= 32 chars; never reused as bootstrap secret or JWT secret)
2. Temporary one-time bootstrap window (auto-deleted by Apps Script upon confirmation or quarantine):
   - `KS_OWNER_BOOTSTRAP_TOKEN_HASH` (64-char lowercase hex SHA-256 of `SALES_OWNER_BOOTSTRAP_SECRET`)
   - `KS_OWNER_BOOTSTRAP_EXPIRES_AT` (short ISO-8601 UTC timestamp)
3. Automatic state/recovery properties (managed by `ksBootstrapFirstOwner_`):
   - `KS_OWNER_BOOTSTRAP_COMPLETED`, `KS_OWNER_BOOTSTRAP_RECOVERY_REQUIRED`, `KS_OWNER_BOOTSTRAP_RECOVERY_REASON`, `KS_OWNER_BOOTSTRAP_IN_PROGRESS`, `KS_OWNER_BOOTSTRAP_IN_PROGRESS_NONCE`, `KS_OWNER_BOOTSTRAP_IN_PROGRESS_PAYLOAD_HASH`, `KS_OWNER_BOOTSTRAP_IN_PROGRESS_STARTED_AT`, `KS_OWNER_BOOTSTRAP_NONCE`, `KS_OWNER_BOOTSTRAP_PAYLOAD_HASH`, `KS_OWNER_BOOTSTRAP_USER_ID`, `KS_OWNER_BOOTSTRAP_COMPLETED_AT`

