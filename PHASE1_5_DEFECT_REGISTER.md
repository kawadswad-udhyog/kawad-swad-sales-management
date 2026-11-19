# PHASE 1.5 INDEPENDENT DEFECT REGISTER

**Audit Date:** 2026-11-19  
**Audit Mode:** STRICT AUDIT MODE (Read-Only Independent Verification — Zero Source Code Edits)  
**Total Newly Discovered Code/Audit Defects:** **9** (`1` CRITICAL, `3` HIGH, `4` MEDIUM, `1` LOW)  
**Unresolved External Artifact Blockers:** **3** (`DB-003`, `DB-007`, `DB-008`)

---

## Summary Index

| Finding ID | Severity | Component | Summary | Status |
|---|---|---|---|---|
| `P1.5-001` | **CRITICAL** | Apps Script Bridge & Routers | Secondary-tab `DB-002` fail-closed bypass when callers pass non-empty subset `invalidate_tabs` (actively triggered on 2 live endpoints) | **OPEN — LIVE REPRODUCED** |
| `P1.5-002` | **HIGH** | Action Registry & Bridge ID Guard | `CREATE_SALARY_INCENTIVE` 100% ID validation deadlock (`SAL` vs `INC`/`SINC`) & unenforced `SalaryReceipts` (`RCPT`) collision | **OPEN — LIVE REPRODUCED** |
| `P1.5-003` | **HIGH** | Authentication & Session Revocation | Fail-open `RevokedTokens` exception handler, stale 30s cache (`fresh=False`), fail-open `sessions_revoked_at` parse, login `active="0"` mismatch, ignored logout persistence failure | **OPEN — LIVE REPRODUCED** |
| `P1.5-004` | **HIGH** | Phase 1 Audit Documentation | `PHASE1_MASTER_AUDIT_REPORT.md` misreported 7 of 12 conflicting core tables and overclaimed unlock column validation | **OPEN — VERIFIED** |
| `P1.5-005` | **MEDIUM** | Schema Registry Unlock Guard | `approve_core_schema_reconciliation()` unlocks blocked core tables with arbitrary 1-column fake headers without validating required columns | **OPEN — LIVE REPRODUCED** |
| `P1.5-006` | **MEDIUM** | Frontend API Client & Schema UI | Error-code contract mismatch hides `BLOCKED_PENDING_OWNER_SETUP` under generic `NOT_SAVED`; misleading green `VERIFIED_CORE` badges on Groups `02` & `10` | **OPEN — VERIFIED** |
| `P1.5-007` | **MEDIUM** | Apps Script Bridge ID Validation | Post-write-only `allocated_id` prefix validation (`HTTP 504` after write committed) and no pre-write validation of client-supplied IDs | **OPEN — VERIFIED** |
| `P1.5-008` | **MEDIUM** | Google Sheets Client & Offline Scripts | Over-privileged read-write OAuth scopes (`spreadsheets`, `drive.file`) and offline scripts bypassing `_assert_direct_mutation_allowed()` | **OPEN — VERIFIED** |
| `P1.5-009` | **LOW** | Auth / Test Harness / Lockout | Non-prod `require_sheets_connection()` fail-open, mock `jwt` ignores `exp`, in-memory login lockout mismatch (`120s` vs `"5 minutes"`), JWT in `localStorage` | **OPEN — VERIFIED** |
| `DB-003` | **BLOCKER (EXTERNAL)** | Workbook Blueprint Reconciliation | 164 of 255 workbook tabs unmapped; authoritative `.xlsx` & `DBV5_FIELD_DICTIONARY_3074` absent | **BLOCKED (EXTERNAL)** |
| `DB-007` | **BLOCKER (EXTERNAL)** | Physical Row-1 Header Export | 12 conflicting core tables & 24 unmapped blueprint tables lack live Row-1 header export | **BLOCKED (EXTERNAL)** |
| `DB-008` | **BLOCKER (EXTERNAL)** | Apps Script Writer Source | Live `WebAppBridge.gs` / `doPost` source absent from repository | **BLOCKED (EXTERNAL)** |

---

## Detailed Defect Entries (All 15 Mandatory Audit Fields)

---

### `P1.5-001` — Active Secondary-Tab `DB-002` Fail-Closed Schema Guard Bypass

- **Finding ID:** `P1.5-001`
- **Severity:** **CRITICAL**
- **Component:** `AppsScriptBridge` schema enforcement (`DB-002`) and router call-sites
- **File:** `backend/app/apps_script_bridge.py`, `backend/app/routers/purchasing.py`, `backend/app/routers/v2_erp.py`
- **Function or line:**
  - `backend/app/apps_script_bridge.py:557` (`AppsScriptBridge.execute_governed_write`)
  - `backend/app/routers/purchasing.py:520` (`RECEIVE_GOODS`)
  - `backend/app/routers/v2_erp.py:1146` (`RECORD_MILLING_BATCH`)
  - `backend/app/routers/v2_erp.py:634` (`RECORD_PACKAGING_BATCH` — latent)
  - `backend/app/routers/v2_erp.py:1172` (`CREATE_PRODUCTION_BATCH` — latent)
- **Description:** In `AppsScriptBridge.execute_governed_write()`, secondary tabs to check for `DB-002` schema write blocks are calculated as `secondary_tabs_to_check = requested_inv if requested_inv else sorted(spec.allowed_invalidate_tabs)`. Whenever a caller passes a non-empty subset `invalidate_tabs` list, the bridge completely drops all other secondary tabs listed in `spec.allowed_invalidate_tabs` from schema-block checking.
- **Evidence:**
  - `backend/app/apps_script_bridge.py:557` directly replaces `spec.allowed_invalidate_tabs` with `requested_inv` when truthy instead of computing their union.
  - AST call-site scan + live Python probe across all 63 multi-tab actions (32 touching write-blocked tabs) proved that **11 of 12** actions with an unblocked primary tab and a blocked secondary tab bypass `DB-002` when called with `invalidate_tabs=[primary_tab]`.
  - **2 live production endpoints actively trigger this bypass right now:**
    - `purchasing.py:520` calls `RECEIVE_GOODS` with `invalidate_tabs=["GoodsReceipts", "GoodsReceiptItems", "RawMaterialLedger", "PurchaseOrderItems"]`, omitting `"RawMaterials"` (which is in `CONFLICTING_CORE_SCHEMA_TABS`).
    - `v2_erp.py:1146` calls `RECORD_MILLING_BATCH` with `invalidate_tabs=["MillingBatches", "RawMaterialLedger", "JournalHeaders", "JournalLines"]`, omitting `"RawMaterials"`.
  - 2 additional endpoints (`v2_erp.py:634` `RECORD_PACKAGING_BATCH` omitting `"Products"`, and `v2_erp.py:1172` `CREATE_PRODUCTION_BATCH` omitting `"RawMaterials"`) are currently masked only because their primary tabs are also blocked, and will become active bypasses the moment their primary tabs are reconciled.
- **Reproduction steps:**
  1. Load `AppsScriptBridge` with `enabled=True`, dummy `webapp_url`/`shared_secret`, and mocked `_post_json` (or unconfigured bridge checking which `503` error code is returned first).
  2. Call `bridge.execute_governed_write("RECEIVE_GOODS", payload={...}, invalidate_tabs=["GoodsReceipts", "GoodsReceiptItems", "RawMaterialLedger", "PurchaseOrderItems"], ...)` (exact call pattern in `backend/app/routers/purchasing.py:520`) or `bridge.execute_governed_write("RECORD_MILLING_BATCH", payload={...}, invalidate_tabs=["MillingBatches", "RawMaterialLedger", "JournalHeaders", "JournalLines"], ...)` (exact call pattern in `backend/app/routers/v2_erp.py:1146`).
  3. Observe whether `HTTPException(503, CORE_SCHEMA_CONFLICT_UNRECONCILED)` is raised before bridge dispatch.
- **Actual behavior:** `DB-002` fails to trigger. The bridge proceeds past schema enforcement (returning `APPS_SCRIPT_BRIDGE_UNCONFIGURED` in isolated mode or dispatching to Apps Script when configured) even though `RawMaterials` is an unreconciled conflicting core table (`CONFLICTING_CORE_SCHEMA_TABS`).
- **Expected behavior:** `AppsScriptBridge.execute_governed_write()` must always inspect the full union `{clean_tab} | set(spec.allowed_invalidate_tabs) | set(requested_inv) | {c.tab for c in spec.readback.child_checks}` so no caller can suppress secondary-tab schema blocks by passing a partial `invalidate_tabs` list.
- **Business impact:** Goods receipts and dal milling batches can silently mutate `RawMaterials` inventory balances against an unreconciled schema mismatch, risking column-offset corruption, misallocated stock quantities, and corrupted raw-material valuations.
- **Security/integrity impact:** Direct, live-exploitable bypass of the primary Phase 1 `DB-002` fail-closed database integrity safeguard on core inventory data.
- **Recommended correction:**
  1. In `backend/app/apps_script_bridge.py:557`, compute `candidate_tabs = sorted({spec.target_tab} | set(spec.allowed_invalidate_tabs) | set(requested_inv))` (preserving primary tab first) for schema-block checks.
  2. Update the 4 router call-sites (`purchasing.py:520`, `v2_erp.py:634`, `v2_erp.py:1146`, `v2_erp.py:1172`) to include all mutated tabs in `invalidate_tabs` so cache invalidation is also accurate.
  3. Add regression tests specifically asserting `invalidate_tabs=[primary_tab]` still blocks on conflicting secondary tabs for `RECEIVE_GOODS`, `RECORD_MILLING_BATCH`, `RECORD_PACKAGING_BATCH`, and `CREATE_PRODUCTION_BATCH`.
- **Regression risk:** Low — unioning `spec.allowed_invalidate_tabs` only restores the intended fail-closed contract; may surface any router whose `invalidate_tabs` omits a blocked secondary tab (which is desirable).
- **Verification status:** **OPEN — Independently live-reproduced** (not fixed in Phase 1.5 due to Strict Audit Mode).

---

### `P1.5-002` — `CREATE_SALARY_INCENTIVE` Validation Deadlock & Unenforced `SalaryReceipts` (`RCPT`) Collision

- **Finding ID:** `P1.5-002`
- **Severity:** **HIGH**
- **Component:** `action_registry.py` / `schema_registry.py` / `apps_script_bridge.py` ID prefix governance (`DB-004` / `DB-005`)
- **File:** `backend/app/action_registry.py`, `backend/app/schema_registry.py`, `backend/app/apps_script_bridge.py`
- **Function or line:**
  - `backend/app/action_registry.py:1241` (`CREATE_SALARY_INCENTIVE` spec)
  - `backend/app/action_registry.py:1219-1226` (`RECORD_WORKFORCE_PAYMENT` spec)
  - `backend/app/schema_registry.py:256-260` (`COLLIDING_LEGACY_PREFIX_TABS`)
  - `backend/app/apps_script_bridge.py:843-844` (`_validate_id_format` invocation)
- **Description:** Two related ID governance defects break `DB-004` / `DB-005`:
  1. `CREATE_SALARY_INCENTIVE` (`target_tab="SalaryIncentives"`) specifies `locked_prefix="SAL"` in `action_registry.py:1241`, while `schema_registry.py:256-260` lists `SalaryIncentives` in `COLLIDING_LEGACY_PREFIX_TABS` (`canonical_prefixes=("SINC",)` / legacy `"INC"`, rejecting `"SAL"`). Because `_validate_id_format()` enforces both `locked_prefix` AND table collision policy, **no ID prefix on earth can pass validation** (`SAL-000001`, `INC-000001`, and `SINC-000001` all return `False`).
  2. `SalaryReceipts` is listed in `COLLIDING_LEGACY_PREFIX_TABS` for the `RCPT` collision with `Payments`, yet `SalaryReceipts` has no standalone action (`RECORD_WORKFORCE_PAYMENT` writes it as a child/secondary row with `target_tab="WorkerLedger"` and `locked_prefix=None`), and `apps_script_bridge.py:843-844` only calls `_validate_id_format()` when `if effective_locked_prefix:` is truthy. Consequently, `SalaryReceipts` collision policy is completely dead code at runtime.
- **Evidence:**
  - Live probe executed against `AppsScriptBridge._validate_id_format` for `CREATE_SALARY_INCENTIVE`:
    - `SAL-000001` -> `False`
    - `INC-000001` -> `False`
    - `SINC-000001` -> `False`
  - Direct inspection of `apps_script_bridge.py:843-844` confirms `if effective_locked_prefix:` skips validation completely when `locked_prefix` is `None` and ignores child-row IDs such as `receipt_id` in `RECORD_WORKFORCE_PAYMENT`.
- **Reproduction steps:**
  1. Look up `GOVERNED_ACTION_REGISTRY["CREATE_SALARY_INCENTIVE"]`.
  2. Invoke `AppsScriptBridge._validate_id_format(allocated_id, spec)` with `"SAL-000001"`, `"INC-000001"`, and `"SINC-000001"`.
  3. Inspect `apps_script_bridge.py:843-844` with `RECORD_WORKFORCE_PAYMENT` (`locked_prefix=None`) returning a `SalaryReceipts` `RCPT-*` ID.
- **Actual behavior:** Every `CREATE_SALARY_INCENTIVE` execution permanently fails ID validation (`HTTP 504 PENDING_UNKNOWN`) even after `SalaryIncentives` schema reconciliation; meanwhile `SalaryReceipts` `RCPT` collisions pass silently without validation.
- **Expected behavior:** `CREATE_SALARY_INCENTIVE` must use a single reconciled canonical prefix consistent between `action_registry.py` and `schema_registry.py`, and `AppsScriptBridge` must enforce collision policies for secondary/child table IDs (including `SalaryReceipts`).
- **Business impact:** Workforce salary incentives cannot be created once schema reconciliation is completed (complete feature outage with `504` ambiguous outcomes), and workforce salary receipt IDs can still collide with customer/supplier `Payments` `RCPT` IDs.
- **Security/integrity impact:** Cross-table ID collision (`SalaryReceipts` vs `Payments`) risks accounting reconciliation errors, audit-trail misattribution, and duplicate receipt references; deadlock forces operational workarounds.
- **Recommended correction:**
  1. Align `CREATE_SALARY_INCENTIVE.locked_prefix` with Owner-approved `SalaryIncentives` canonical prefix (`SINC` or `INC`) and remove the contradictory `"SAL"` lock.
  2. Validate response/child entity IDs for multi-table actions (especially `SalaryReceipts` inside `RECORD_WORKFORCE_PAYMENT`) even when `effective_locked_prefix` is `None`.
  3. Add unit tests verifying at least one canonical ID passes `_validate_id_format()` for **all 127** registered actions (deadlock guard test).
- **Regression risk:** Low — fixing contradictory prefix metadata unblocks a currently broken action; child-ID validation requires confirming the exact response field name emitted by Apps Script (`DB-008`).
- **Verification status:** **OPEN — Independently live-reproduced**.

---

### `P1.5-003` — Fail-Open Token Revocation, Stale 30s Auth Cache & Deactivation Check Gaps

- **Finding ID:** `P1.5-003`
- **Severity:** **HIGH**
- **Component:** Backend JWT Authentication & Session Revocation (`auth.py`, `routers/auth.py`)
- **File:** `backend/app/auth.py`, `backend/app/routers/auth.py`
- **Function or line:**
  - `backend/app/auth.py:216-226` (`is_token_revoked`)
  - `backend/app/auth.py:217, 236` (`fresh=False` reads on `RevokedTokens` and `AuthUsers`)
  - `backend/app/auth.py:310-311` (`sessions_revoked_at` timestamp parsing)
  - `backend/app/routers/auth.py:101` (`login` active-status check)
  - `backend/app/routers/auth.py:144` (`logout` revocation persistence handling)
- **Description:** Five authentication hardening defects were verified in the active auth path:
  1. `is_token_revoked()` wraps `db.get_records("RevokedTokens", fresh=False)` in `except Exception: pass` and returns `False` (**fail-open**). Any Sheets read failure or quota error allows revoked JWTs to authenticate.
  2. Both `RevokedTokens` (`auth.py:217`) and `AuthUsers` (`auth.py:236`) are read via `db.get_records(..., fresh=False)` (default 30s TTL cache), allowing logged-out tokens, revoked sessions, deactivated users, or demoted roles to remain valid for up to 30 seconds across workers.
  3. `sessions_revoked_at` comparison (`auth.py:310-311`) catches `(ValueError, TypeError): pass` and silently allows the token if the sheet timestamp was reformatted (e.g., Google Sheets locale date formatting).
  4. `routers/auth.py:101` checks only `str(user.get("active", "true")).strip().lower() == "false"`, allowing accounts marked `"0"` or `"no"` to log in (whereas `auth.py:282` rejects `"0"` and `"no"`).
  5. `routers/auth.py:144` ignores `revoke_token()` returning `False` when bridge persistence fails, returning `{"ok": true, "persisted": false}` without erroring or alerting multi-worker session invalidation failure.
- **Evidence:**
  - Live auth probe simulating a `RuntimeError` during `db.get_records("RevokedTokens", fresh=False)` confirmed `is_token_revoked()` returned `False` and `get_current_user()` returned `ALLOW`.
  - Live probe with `active="0"` confirmed `get_current_user` returns `401` while `routers/auth.py:101` only checks `== "false"`.
  - Live probe confirmed `revoke_token()` returns `False` when Apps Script bridge is unconfigured, leaving revocation only in single-process memory.
- **Reproduction steps:**
  1. Issue a valid JWT for an active user and revoke it in `RevokedTokens` (not in local process memory, simulating worker restart or second worker).
  2. Inject a read exception on `db.get_records("RevokedTokens", fresh=False)`.
  3. Call `get_current_user()` with that token -> request succeeds instead of failing closed (`401`/`503`).
- **Actual behavior:** Revoked tokens are accepted during transient `RevokedTokens` read failures or corrupted `sessions_revoked_at` formatting, and remain valid across workers for up to 30 seconds due to `fresh=False`.
- **Expected behavior:** Revocation checks must fail closed (`503` or `401`) on `RevokedTokens` read errors or unparseable `sessions_revoked_at` values; security-critical reads (`RevokedTokens`, `AuthUsers`) should bypass stale cache or use short/invalidated security cache; login active-state check must match `auth.py:282` (`not in {"false", "0", "no"}`).
- **Business impact:** Terminated employees, compromised tokens, or logged-out shared devices can continue executing ERP actions during Sheets quota hiccups or multi-worker cache windows.
- **Security/integrity impact:** High-severity authentication bypass / fail-open session revocation flaw.
- **Recommended correction:**
  1. Fail closed (`HTTP 503` or `HTTP 401`) in `is_token_revoked()` when `RevokedTokens` cannot be read in production.
  2. Fail closed when `sessions_revoked_at` is non-empty but unparseable.
  3. Use a shared active-boolean helper across `auth.py` and `routers/auth.py` rejecting `"false"`, `"0"`, `"no"`, `""`.
  4. Require `fresh=True` (or tightly bounded 3–5s security cache invalidated on auth mutations) for `RevokedTokens` and `AuthUsers` on mutation requests.
  5. Surface persistence failure explicitly on `/auth/logout` when `revoke_token()` fails in production.
- **Regression risk:** Medium — enabling `fresh=True` on every request increases Google Sheets read quota usage; must pair with quota-aware caching (e.g., short TTL + explicit cache bust on logout/deactivation/role change) so `test_sheets_quota_handling.py` stays green.
- **Verification status:** **OPEN — Independently live-reproduced**.

---

### `P1.5-004` — Prior Phase 1 Audit Report Material Inaccuracies (7 of 12 Conflicting Tables Misreported & Overclaimed Unlock Validation)

- **Finding ID:** `P1.5-004`
- **Severity:** **HIGH**
- **Component:** Phase 1 Governance & Audit Reporting (`PHASE1_MASTER_AUDIT_REPORT.md`)
- **File:** `PHASE1_MASTER_AUDIT_REPORT.md` (compared against `backend/app/schema_registry.py`)
- **Function or line:**
  - `PHASE1_MASTER_AUDIT_REPORT.md` Section 3 & Section 4
  - Ground truth: `backend/app/schema_registry.py` (`CONFLICTING_CORE_SCHEMA_TABS`, `approve_core_schema_reconciliation`)
- **Description:** Independent comparison of `PHASE1_MASTER_AUDIT_REPORT.md` against actual code in `backend/app/schema_registry.py` revealed two material factual inaccuracies that could mislead the Owner during schema reconciliation:
  1. Section 4 listed 7 wrong table names (`ApprovalRequests`, `Attendance`, `DailyClosings`, `GoodsReceipts`, `MillingBatches`, `StockMovements`, `SupplierBills`) with inaccurate field counts as part of the 12 conflicting core tables. The actual 12 tables in `CONFLICTING_CORE_SCHEMA_TABS` are: `Suppliers`, `CustomRoles`, `SalaryIncentives`, `RawMaterials`, `Products`, `Workers`, `Customers`, `Sales`, `ProductionBatches`, `PackagingBatches`, `Expenses`, and `ShopVisits`.
  2. Section 3 claimed `approve_core_schema_reconciliation()` validates full required and missing column coverage before unlocking a table, whereas the actual code only checks that `headers` is a non-empty list of strings (`P1.5-005`).
- **Evidence:** Direct file comparison of `PHASE1_MASTER_AUDIT_REPORT.md` against `backend/app/schema_registry.py:274-339` and `backend/app/schema_registry.py:733-794`.
- **Reproduction steps:**
  1. Inspect `CONFLICTING_CORE_SCHEMA_TABS.keys()` in `backend/app/schema_registry.py`.
  2. Compare against the 12-table list in `PHASE1_MASTER_AUDIT_REPORT.md` Section 4.
  3. Inspect `approve_core_schema_reconciliation()` in `backend/app/schema_registry.py:733-794`.
- **Actual behavior:** Governance report provides the Owner an incorrect checklist of tables to export Row-1 headers for (`DB-007`) and misrepresents the strength of the unlock guard.
- **Expected behavior:** Audit documentation must reflect the exact 12 `CONFLICTING_CORE_SCHEMA_TABS` in source code and accurately state validation behavior.
- **Business impact:** If the Owner follows the inaccurate Phase 1 report to prepare Row-1 header exports, 7 of the 12 actually blocked core tables (`Suppliers`, `CustomRoles`, `SalaryIncentives`, `Workers`, `PackagingBatches`, `Expenses`, `ShopVisits`) would be missed, delaying go-live.
- **Security/integrity impact:** Erodes audit-trail reliability and creates false assurance regarding schema unlock protections.
- **Recommended correction:** Supersede inaccurate sections via the verified Phase 1.5 reports (done in `PHASE1_5_INDEPENDENT_VERIFICATION_REPORT.md` and `PHASE1_5_REPAIR_VALIDATION_MATRIX.csv`) and issue a corrected Owner reconciliation checklist listing the exact 12 tables in `CONFLICTING_CORE_SCHEMA_TABS`.
- **Regression risk:** None (documentation correction).
- **Verification status:** **OPEN — Independently verified against source**.

---

### `P1.5-005` — Weak Schema Reconciliation Unlock Validation (Accepts Arbitrary 1-Column Headers)

- **Finding ID:** `P1.5-005`
- **Severity:** **MEDIUM**
- **Component:** Schema Registry Reconciliation Unlock (`DB-002` unlock mechanism)
- **File:** `backend/app/schema_registry.py`
- **Function or line:** `backend/app/schema_registry.py:733-794` (`approve_core_schema_reconciliation`, `get_approved_core_schema_reconciliations`)
- **Description:** `approve_core_schema_reconciliation()` and env-JSON approval loading (`SALES_APPROVED_CORE_SCHEMA_RECONCILIATIONS_JSON`) accept any non-empty list of strings as `headers` without verifying that all columns in `REQUIRED_TABS[tab]` (or expected missing columns) are present. Additionally, JSON-loaded approvals omit duplicate-header checks and capture the environment variable at import time rather than dynamically.
- **Evidence:** Live Python probe:
  ```python
  approve_core_schema_reconciliation("Customers", headers=["totally_fake_column"], approved_by="USR-OWNER-001")
  get_schema_write_block_reason("Customers")  # -> None (UNLOCKED!)
  ```
- **Reproduction steps:**
  1. Call `approve_core_schema_reconciliation("Customers", headers=["totally_fake_column"], approved_by="USR-OWNER-001")`.
  2. Call `get_schema_write_block_reason("Customers")`.
  3. Observe it returns `None`, removing the write block on `Customers`.
- **Actual behavior:** A typo, truncated paste, or accidental 1-column header list silently disables `DB-002` protection on a conflicting core table.
- **Expected behavior:** Unlock validation must require: (a) normalized unique non-empty header names, (b) full superset coverage of `REQUIRED_TABS[tab]` (or explicit Owner-signed column-diff acknowledgement), and (c) consistent validation for both programmatic and JSON-loaded approvals.
- **Business impact:** Operational mistake during Owner reconciliation setup can prematurely unlock a conflicting table and cause live data misalignment.
- **Security/integrity impact:** Weakens `DB-002` unlock boundary against malformed configuration.
- **Recommended correction:** Validate `set(REQUIRED_TABS[tab]).issubset(set(normalized_headers))`, reject duplicate headers in both runtime and JSON-loaded paths, and read/parse env JSON safely with validation logging.
- **Regression risk:** Low — only rejects malformed or incomplete header lists during Owner setup.
- **Verification status:** **OPEN — Independently live-reproduced**.

---

### `P1.5-006` — Frontend Blocked-Schema Error-Code Mismatch & Misleading Green `VERIFIED_CORE` Group Badges

- **Finding ID:** `P1.5-006`
- **Severity:** **MEDIUM**
- **Component:** Frontend API Error Handling & ERP Operations Hub Schema Governance View
- **File:** `src/services/api.ts`, `src/views/ErpOperationsHubView.tsx`, `backend/app/schema_registry.py`
- **Function or line:**
  - `src/services/api.ts:677`
  - `src/views/ErpOperationsHubView.tsx:294, 1522-1528`
  - `backend/app/apps_script_bridge.py:970-973`
  - `backend/app/schema_registry.py:563, 638`
- **Description:** Two cross-layer UI/API defects affect operator visibility of Phase 1 schema blocks:
  1. When `AppsScriptBridge` blocks a write (`HTTP 503`), it emits `detail.status = "BLOCKED_PENDING_OWNER_SETUP"` and `detail.error_code = "CORE_SCHEMA_CONFLICT_UNRECONCILED"` (or `PENDING_OWNER_MAPPING` / `APPS_SCRIPT_BRIDGE_UNCONFIGURED`). However, `src/services/api.ts:677` looks for `detailObj?.workflow_status` or `errorCode === 'BLOCKED_PENDING_OWNER_SETUP'`, and `ErpOperationsHubView.tsx:294` checks `err.errorCode === 'BLOCKED_PENDING_OWNER_SETUP'`. As a result, schema-blocked 503 responses fall through to a generic `NOT_SAVED` message instead of the dedicated `BLOCKED_PENDING_OWNER_SETUP` banner.
  2. `schema_registry.py:563` (Group `02`: `Suppliers`) and `schema_registry.py:638` (Group `10`: `Expenses`) declare `status = "VERIFIED_CORE"`, causing `ErpOperationsHubView.tsx:1522-1528` to display green verified badges even though both groups contain write-blocked `CONFLICTING_CORE_SCHEMA_TABS`. Top summary chips also omit `unmapped_workbook_tabs_remaining` (`164`) and `write_blocked_schema_tabs_count` (`36`).
- **Evidence:** Direct cross-file inspection of `apps_script_bridge.py:970-973`, `api.ts:677`, `ErpOperationsHubView.tsx:294, 1522-1528`, and `schema_registry.py:563, 638`.
- **Reproduction steps:**
  1. Trigger a `DB-002` `HTTP 503` response from `AppsScriptBridge`.
  2. Trace payload parsing through `src/services/api.ts:677` into `ErpOperationsHubView.tsx:294`.
  3. Inspect `SCHEMA_GROUP_METADATA` for Groups `02` and `10` rendered in `ErpOperationsHubView.tsx:1522-1528`.
- **Actual behavior:** Blocked schema writes render as generic `NOT_SAVED` errors; Groups `02` and `10` appear green/`VERIFIED_CORE` while blocked; `164` unmapped tabs and `36` write-blocked tabs are hidden from summary cards.
- **Expected behavior:** Frontend must recognize `detail.status === 'BLOCKED_PENDING_OWNER_SETUP'` and error codes `CORE_SCHEMA_CONFLICT_UNRECONCILED`, `PENDING_OWNER_MAPPING`, and `APPS_SCRIPT_BRIDGE_UNCONFIGURED`; Groups `02` and `10` must display conflict/blocked badges; summary metrics must display `164` unmapped and `36` blocked tabs.
- **Business impact:** Operators receive confusing generic errors instead of clear Owner-setup-required guidance, and admins viewing the Schema Governance tab receive false green signals on blocked groups.
- **Security/integrity impact:** Reduces operational transparency of fail-closed controls (no data bypass by itself).
- **Recommended correction:** Align `api.ts` error parsing with `detail.status` and explicit schema-block `error_code` values; update `schema_registry.py` group statuses for Groups `02` and `10` to reflect active conflicts; add summary counters for `unmapped_workbook_tabs_remaining` and `write_blocked_schema_tabs_count`.
- **Regression risk:** Low — UI/error-mapping adjustment only.
- **Verification status:** **OPEN — Independently verified**.

---

### `P1.5-007` — Post-Write-Only ID Prefix Validation & Missing Pre-Write Client ID Check

- **Finding ID:** `P1.5-007`
- **Severity:** **MEDIUM**
- **Component:** `AppsScriptBridge` ID Prefix Enforcement (`DB-005`)
- **File:** `backend/app/apps_script_bridge.py`
- **Function or line:** `backend/app/apps_script_bridge.py:843-863`
- **Description:** `AppsScriptBridge.execute_governed_write()` validates `allocated_id` against `_validate_id_format()` only **after** the HTTP POST to Google Apps Script has already executed and committed the row. If the prefix is invalid, the backend raises `HTTP 504 PENDING_UNKNOWN`, leaving the malformed ID written in Google Sheets. Furthermore, when a router or client supplies a pre-formed ID in `payload`, there is no pre-write prefix guard before calling Apps Script.
- **Evidence:** Direct inspection of `backend/app/apps_script_bridge.py:843-863` shows `_validate_id_format()` runs exclusively in the post-POST response verification block.
- **Reproduction steps:**
  1. Trace `AppsScriptBridge.execute_governed_write()` from payload preparation through HTTP POST to line 843.
  2. Observe that no `_validate_id_format()` check occurs before sending the HTTP POST.
- **Actual behavior:** Malformed client-supplied IDs are sent to Apps Script before validation; malformed Apps Script allocated IDs are only detected post-commit, returning `HTTP 504`.
- **Expected behavior:** Any client/router-supplied canonical ID field in `payload` should be pre-validated before `_post_json()`, while preserving post-write echo validation on Apps Script-allocated IDs (and pairing with server-side Apps Script enforcement once `DB-008` is audited).
- **Business impact:** Malformed or colliding IDs can be committed to Google Sheets before the backend notices, forcing manual spreadsheet cleanup.
- **Security/integrity impact:** Turns ID-prefix protection from preventative to detective-only (post-commit).
- **Recommended correction:** Add pre-write validation for known ID keys in `payload` when provided, and once `DB-008` Apps Script source is supplied, enforce identical prefix locks inside `WebAppBridge.gs` prior to `appendRow()`.
- **Regression risk:** Low — only rejects malformed pre-supplied IDs; must skip pre-check when ID is allocated server-side by Apps Script (empty/omitted in payload).
- **Verification status:** **OPEN — Independently verified**.

---

### `P1.5-008` — Over-Privileged Read-Write Google OAuth Scopes & Offline Direct-Write Scripts

- **Finding ID:** `P1.5-008`
- **Severity:** **MEDIUM**
- **Component:** `SheetsDB` OAuth Scopes & Offline Maintenance Scripts
- **File:** `backend/app/sheets.py`, `backend/app/workforce_migration.py`, `backend/scripts/*.py`
- **Function or line:**
  - `backend/app/sheets.py:675-678` (OAuth scope declaration)
  - `backend/app/workforce_migration.py` (offline migration utility — not mounted in FastAPI)
  - 5 legacy scripts in `backend/scripts/`
- **Description:**
  1. Despite Blueprint v2.1 Single-Write-Owner policy prohibiting the FastAPI backend from writing directly to Google Sheets, `backend/app/sheets.py:675-678` still requests read-write OAuth scopes (`https://www.googleapis.com/auth/spreadsheets` and `https://www.googleapis.com/auth/drive.file`) instead of `https://www.googleapis.com/auth/spreadsheets.readonly`.
  2. `backend/app/workforce_migration.py` (offline CLI module, verified not imported by FastAPI routes) invokes `spreadsheet.add_worksheet`, `del_worksheet`, `ws.clear`, and `ws.update` directly without calling `_assert_direct_mutation_allowed()`. Five offline scripts under `backend/scripts/` similarly contain pre-Single-Write-Owner direct mutation calls.
- **Evidence:** Direct inspection of `backend/app/sheets.py:675-678` and repo-wide grep across `backend/app/` and `backend/scripts/` (detailed in `PHASE1_5_SECURITY_AND_WRITE_PATH_AUDIT.md`).
- **Reproduction steps:**
  1. Inspect `SCOPES` at `backend/app/sheets.py:675-678`.
  2. Grep `backend/` for `.update(`, `.append_row(`, `.add_worksheet(`, `.del_worksheet(`, `.clear(`.
- **Actual behavior:** Backend service account credentials retain full read-write Sheets/Drive capability at the OAuth layer; offline scripts can bypass `_assert_direct_mutation_allowed()`.
- **Expected behavior:** Production FastAPI service account should use `spreadsheets.readonly` scope (defense-in-depth enforcing Single-Write-Owner at Google IAM/OAuth level), and offline migration scripts should require an explicit interactive/env maintenance gate (`ALLOW_OFFLINE_SHEETS_MIGRATION=1`) or be archived.
- **Business impact:** If any future code bug or compromised server process bypasses `_assert_direct_mutation_allowed()`, Google APIs will allow direct writes to the authoritative workbook.
- **Security/integrity impact:** Violates least-privilege defense-in-depth for Single-Write-Owner architecture.
- **Recommended correction:** Switch production `SheetsDB` scopes to `spreadsheets.readonly` (with separate offline-tool scope only when explicitly invoked under Owner migration), and guard or archive `workforce_migration.py` and `backend/scripts/` direct writers.
- **Regression risk:** Low for FastAPI runtime (already blocks all direct writes via `_assert_direct_mutation_allowed()`).
- **Verification status:** **OPEN — Independently verified**.

---

### `P1.5-009` — Non-Prod `require_sheets_connection()` Fail-Open, Mock JWT `exp` Gap, In-Memory Lockout Mismatch & `localStorage` JWT

- **Finding ID:** `P1.5-009`
- **Severity:** **LOW**
- **Component:** Auth Guards, Test Harness & Frontend Token Storage
- **File:** `backend/app/auth.py`, `backend/app/routers/auth.py`, `backend/tests/__init__.py`, `src/services/api.ts`
- **Function or line:**
  - `backend/app/auth.py:321-329` (`require_sheets_connection`)
  - `backend/tests/__init__.py` (stdlib mock `jwt`)
  - `backend/app/routers/auth.py:26-28, 76` (in-memory lockout)
  - `src/services/api.ts:153` (`localStorage` token storage)
- **Description:** Four minor security/test-fidelity items identified:
  1. `require_sheets_connection()` returns `True` when `SALES_GOOGLE_SPREADSHEET_ID` is empty and `db.is_connected == False` (mitigated in production by `assert_runtime_config()`).
  2. `backend/tests/__init__.py` mock `jwt.decode()` ignores `exp`, leaving expired-JWT rejection unverified in stdlib-only test runs.
  3. Login brute-force lockout (`routers/auth.py:26-28, 76`) is stored in single-process RAM (resets on restart / bypassable across workers) and returns error text `"5 minutes"` while enforcing `120` seconds (2 minutes).
  4. Frontend stores JWT in `localStorage` (`src/services/api.ts:153`), which is standard for SPAs but exposes tokens to XSS if any injection occurs.
- **Evidence:** Live probes on `require_sheets_connection()` (returned `True`) and expired JWT under mock `jwt` (returned `ALLOW`); direct inspection of `routers/auth.py:26-28, 76` and `src/services/api.ts:153`.
- **Reproduction steps:**
  1. Call `require_sheets_connection()` with `SALES_GOOGLE_SPREADSHEET_ID=""` and disconnected `db`.
  2. Pass an expired JWT (`exp = int(time.time()) - 3600`) to `decode_token()` under `backend/tests/__init__.py`.
  3. Inspect `LOCKOUT_SECONDS` (`120`) vs. error message (`"5 minutes"`) in `routers/auth.py:26-28, 76`.
- **Actual behavior:** Non-prod connectivity check passes when disconnected; mock `jwt` accepts expired tokens; lockout duration text contradicts code (`2 min` vs `5 min`).
- **Expected behavior:** Mock `jwt` should enforce `exp` so CI tests validate expiry; lockout message should match configured window (`120s` / 2 min or set to `300s` for 5 min); evaluate `HttpOnly` cookie or strict CSP for token security in Phase 2.
- **Business impact:** Low immediate impact in production (assuming `ENVIRONMENT=production` and real `PyJWT` installed on Render), but reduces confidence in local verification and error accuracy.
- **Security/integrity impact:** Minor defense-in-depth and test-coverage gaps.
- **Recommended correction:** Add `exp` validation to `backend/tests/__init__.py` mock `jwt`, align `LOCKOUT_SECONDS` and message in `routers/auth.py`, and evaluate shared/persistent rate limiting + CSP hardening during Phase 2.
- **Regression risk:** Minimal.
- **Verification status:** **OPEN — Independently verified**.

---

## Unresolved External Artifact Blockers (Cannot Be Resolved From Source Code Alone)

### `DB-003` — 164 of 255 Workbook Tabs Unmapped (Missing Authoritative `.xlsx` & `DBV5_FIELD_DICTIONARY_3074`)
- **Finding ID:** `DB-003`
- **Severity:** **EXTERNAL BLOCKER**
- **Component:** `backend/app/schema_registry.py` (`WORKBOOK_TARGET_TAB_COUNT = 255`)
- **File:** `backend/app/schema_registry.py`
- **Function or line:** `schema_registry.py` (`WORKBOOK_TARGET_TAB_COUNT`, `get_schema_coverage_summary()` — `91` catalogued: `67` `REQUIRED_TABS` + `24` `EXTENDED_V2_TAB_CONTRACTS`; `164` unmapped)
- **Description:** The authoritative 255-tab workbook (`.xlsx`) and `DBV5_FIELD_DICTIONARY_3074` are not present anywhere in the repository (`XLSX_FILES = []`). Therefore `164` workbook tabs remain unmapped.
- **Evidence:** Repository-wide filesystem scan confirmed `XLSX_FILES=[]` and `DBV5_FIELD_DICTIONARY_3074` appears only as a metadata note string in `backend/app/schema_registry.py`.
- **Reproduction steps:** Search workspace recursively for `*.xlsx`, `*.xls`, and `DBV5_FIELD_DICTIONARY_3074`.
- **Actual behavior:** `get_schema_coverage_summary()` accurately reports `164` unmapped tabs (`coverage_complete = False`, `DB-003` open).
- **Expected behavior:** All 255 authoritative workbook tabs reconciled from Owner-supplied workbook / field dictionary.
- **Business impact:** Full 255-tab governance coverage cannot be certified until Owner provides the authoritative workbook and field dictionary.
- **Security/integrity impact:** Prevents complete schema verification across unmapped tabs.
- **Recommended correction:** Owner must supply the authoritative 255-tab `.xlsx` workbook and `DBV5_FIELD_DICTIONARY_3074` export (or issue a written scoped waiver for non-ERP tabs).
- **Regression risk:** N/A (external artifact dependency).
- **Verification status:** **BLOCKED (EXTERNAL) — Confirmed genuinely absent**.

### `DB-007` — Missing Physical Row-1 Header Export for 12 Conflicting Core Tables & 24 Unmapped Blueprint Tabs
- **Finding ID:** `DB-007`
- **Severity:** **EXTERNAL BLOCKER**
- **Component:** `backend/app/schema_registry.py` (`CONFLICTING_CORE_SCHEMA_TABS`, `PENDING_OWNER_MAPPING_TABS`)
- **File:** `backend/app/schema_registry.py`
- **Function or line:** `CONFLICTING_CORE_SCHEMA_TABS` (`12` tables) & `PENDING_OWNER_MAPPING_TABS` (`24` tables)
- **Description:** Live physical Row-1 headers from the authoritative Google Sheet have not been exported into the repository, so none of the 12 conflicting core tables (`Suppliers`, `CustomRoles`, `SalaryIncentives`, `RawMaterials`, `Products`, `Workers`, `Customers`, `Sales`, `ProductionBatches`, `PackagingBatches`, `Expenses`, `ShopVisits`) or 24 unmapped blueprint tabs can be reconciled.
- **Evidence:** No physical Row-1 header JSON/CSV export exists in workspace; live Sheets access is strictly prohibited.
- **Reproduction steps:** Inspect workspace for Row-1 header export files and check `get_approved_core_schema_reconciliations()` (returns `{}`).
- **Actual behavior:** All 36 tables (`12` conflicting + `24` blueprint-only) remain write-blocked (except via active bypass `P1.5-001`!).
- **Expected behavior:** Owner supplies physical Row-1 header export from live Google Sheet so schemas can be verified and reconciled safely (after `P1.5-005` unlock validation is hardened).
- **Business impact:** Core ERP mutations touching the 12 conflicting tables cannot safely go live until reconciled.
- **Security/integrity impact:** Guessing headers without physical export would risk silent column misalignment.
- **Recommended correction:** Owner runs a read-only Row-1 header export script on the authoritative Google Sheet and provides the JSON output for reconciliation.
- **Regression risk:** N/A (external artifact dependency).
- **Verification status:** **BLOCKED (EXTERNAL) — Confirmed genuinely absent**.

### `DB-008` — Missing Live Apps Script `WebAppBridge.gs` / `doPost` Writer Source
- **Finding ID:** `DB-008`
- **Severity:** **EXTERNAL BLOCKER**
- **Component:** External Google Apps Script Single-Write-Owner Bridge
- **File:** Not present in repository (only 3 workforce `.gs` utilities exist in `docs/`)
- **Function or line:** N/A — source missing
- **Description:** The actual Google Apps Script `WebAppBridge.gs` / `doPost` implementation—the sole authoritative database writer under Blueprint v2.1—is completely absent from the repository.
- **Evidence:** Filesystem & grep scan: `GS_FILES=['docs/workforceDiagnosticReport.gs', 'docs/workforceMigration.gs', 'docs/workforceSchemaUpgrade_2026-11-03-v1.gs']`, `CODE_MATCHES['WebAppBridge']=[]`, `CODE_MATCHES['function doPost']=[]`.
- **Reproduction steps:** Search repository for `*.gs`, `WebAppBridge`, and `function doPost`.
- **Actual behavior:** Server-side Apps Script column mapping, lock/concurrency safety, idempotency deduplication, HMAC/secret verification, and ID prefix allocation cannot be audited.
- **Expected behavior:** Owner exports the live Apps Script project source (`WebAppBridge.gs` and supporting `.gs` files) for independent database-writer integrity audit.
- **Business impact:** Even after backend defects (`P1.5-001`–`P1.5-009`) are fixed, end-to-end write integrity cannot be certified while the sole database writer remains unaudited.
- **Security/integrity impact:** Unverified writer could still introduce column-offset writes, race conditions, or ID collisions (`PKG`/`PKB`, `RCPT`, `SAL`/`INC`).
- **Recommended correction:** Owner exports the live Apps Script writer source into the audit workspace for dedicated `DB-008` review.
- **Regression risk:** N/A (external artifact dependency).
- **Verification status:** **BLOCKED (EXTERNAL) — Confirmed genuinely absent**.
