# PHASE 1.5 FINAL GATE DECISION

**Audit Date:** 2026-11-19  
**Auditor Role:** Independent Verification & Integrity Auditor  
**Audit Scope:** Independent verification of Phase 1 database integrity repairs (`DB-001`–`DB-008`, `P1-NEW-01`–`P1-NEW-06`) and ERP source code integrity  
**Audit Mode:** STRICT AUDIT MODE (Read-Only — Zero Edits to Source Code, Tests, Configs, or Live Systems)

---

## 1. Official Phase 1.5 Gate Verdict

# **FAIL**

Phase 1.5 **DOES NOT PASS**. While several foundational Phase 1 repairs are genuinely implemented (`DB-001` `get_schema_coverage_summary()`, `DB-005` 11-action prefix locks, `DB-006` `ProductLots` single Group `03` ownership, `127/127` action registry completeness, `112/112` `py_compile`, and clean frontend `npm run lint` + `npm run build`), independent code inspection and live local bypass testing uncovered **1 CRITICAL live safeguard bypass**, **3 HIGH defects**, **4 MEDIUM defects**, and **1 LOW defect** — in addition to the **3 unresolved external artifact blockers (`DB-003`, `DB-007`, `DB-008`)**.

---

## 2. Gate Failure Drivers (Evidence-Based)

### 2.1 Critical & High Code / Governance Defects Discovered in Phase 1.5
1. **`P1.5-001` (CRITICAL — Active Live `DB-002` Bypass):** `backend/app/apps_script_bridge.py:557` replaces `spec.allowed_invalidate_tabs` whenever a caller passes a non-empty `invalidate_tabs` list. Live reproduction proved **11 of 12** secondary-tab actions bypass `DB-002` when called with `invalidate_tabs=[primary_tab]`, and **2 live production endpoints actively trigger this bypass right now**: `purchasing.py:520` (`RECEIVE_GOODS` omitting `RawMaterials`) and `v2_erp.py:1146` (`RECORD_MILLING_BATCH` omitting `RawMaterials`). Two more endpoints (`v2_erp.py:634`, `v2_erp.py:1172`) are latent bypasses.
2. **`P1.5-002` (HIGH — ID Prefix Validation Deadlock & Unenforced Collision):** `CREATE_SALARY_INCENTIVE` (`action_registry.py:1241`, `locked_prefix="SAL"`) contradicts `COLLIDING_LEGACY_PREFIX_TABS["SalaryIncentives"]` (`schema_registry.py:256-260`), causing `_validate_id_format()` to reject every possible ID (`SAL-*`, `INC-*`, `SINC-*` all return `False`). Separately, `SalaryReceipts` (`RCPT` collision) is written as a child of `RECORD_WORKFORCE_PAYMENT` (`locked_prefix=None`) and is never validated at runtime by `apps_script_bridge.py:843-844`.
3. **`P1.5-003` (HIGH — Fail-Open Auth Revocation & Stale Security Cache):** `backend/app/auth.py:216-226` catches `except Exception: pass` on `RevokedTokens` read and returns `False` (live-reproduced **fail-open**); both `RevokedTokens` and `AuthUsers` read with `fresh=False` (30s stale window); `sessions_revoked_at` fails open on parse error (`auth.py:310-311`); `routers/auth.py:101` misses `active="0"`/`"no"` at login; `routers/auth.py:144` ignores logout persistence failures.
4. **`P1.5-004` (HIGH — Prior Phase 1 Report Materially Inaccurate):** `PHASE1_MASTER_AUDIT_REPORT.md` Section 4 misreported **7 of 12** conflicting core tables and Section 3 overclaimed unlock column validation, making the prior handover report unsafe to use directly as an Owner reconciliation checklist.

### 2.2 Medium & Low Findings Requiring Remediation
- **`P1.5-005` (MEDIUM):** `approve_core_schema_reconciliation()` unlocked `Customers` in a live probe using `headers=["totally_fake_column"]` (no required-column verification; JSON-loaded path skips duplicate checks).
- **`P1.5-006` (MEDIUM):** Frontend `api.ts:677` / `ErpOperationsHubView.tsx:294` error-code mismatch drops `BLOCKED_PENDING_OWNER_SETUP` into generic `NOT_SAVED`; Groups `02` (`Suppliers`) and `10` (`Expenses`) render misleading green `VERIFIED_CORE` badges while blocked; summary cards omit `164` unmapped and `36` blocked tab counts.
- **`P1.5-007` (MEDIUM):** ID prefix validation in `apps_script_bridge.py:843-863` executes only **post-write** (`HTTP 504 PENDING_UNKNOWN` after commit) and does not pre-validate client-supplied IDs.
- **`P1.5-008` (MEDIUM):** `sheets.py:675-678` retains read-write OAuth scopes (`spreadsheets`, `drive.file`) instead of `spreadsheets.readonly`; offline `workforce_migration.py` and 5 scripts in `backend/scripts/` bypass `_assert_direct_mutation_allowed()`.
- **`P1.5-009` (LOW):** Non-prod `require_sheets_connection()` fail-open (`auth.py:321-329`), mock `jwt` ignoring `exp` (`backend/tests/__init__.py`), in-memory login lockout mismatch (`120s` vs `"5 minutes"` in `routers/auth.py:26-28, 76`), and `localStorage` JWT tradeoff (`src/services/api.ts:153`).

### 2.3 Unresolved External Artifact Blockers (Still Open)
- **`DB-003`:** `164` of `255` workbook tabs remain unmapped (authoritative `.xlsx` and `DBV5_FIELD_DICTIONARY_3074` confirmed absent).
- **`DB-007`:** Live physical Row-1 header export for the 12 conflicting core tables (`Suppliers`, `CustomRoles`, `SalaryIncentives`, `RawMaterials`, `Products`, `Workers`, `Customers`, `Sales`, `ProductionBatches`, `PackagingBatches`, `Expenses`, `ShopVisits`) and 24 unmapped blueprint tabs confirmed absent.
- **`DB-008`:** Live Google Apps Script `WebAppBridge.gs` / `doPost` writer source confirmed absent.

---

## 3. Phase 2 Readiness Decision

### **HOLD — DO NOT START PHASE 2 YET**

Proceeding directly to Phase 2 (API & Permission Audit / further ERP changes) on top of an active `DB-002` secondary-tab bypass (`P1.5-001`), an unworkable `CREATE_SALARY_INCENTIVE` deadlock (`P1.5-002`), and a fail-open token-revocation handler (`P1.5-003`) would build Phase 2 verification on an unsound Phase 1 foundation.

---

## 4. Exact Entry Criteria to Re-Test & Pass Phase 1.5 (and Unlock Phase 2)

### Step A — Mandatory Targeted Remediation Pass (Phase 1.6 Repair)
Execute an Owner-authorized, tightly scoped repair pass fixing **only** the verified Phase 1.5 defects (no feature additions or redesign):
1. **Fix `P1.5-001` (CRITICAL):** Union `{clean_tab} | set(spec.allowed_invalidate_tabs) | set(requested_inv) | {c.tab for c in spec.readback.child_checks}` in `AppsScriptBridge.execute_governed_write()`, update the 4 router call-sites (`purchasing.py:520`, `v2_erp.py:634`, `v2_erp.py:1146`, `v2_erp.py:1172`), and add subset-`invalidate_tabs` regression tests.
2. **Fix `P1.5-002` (HIGH):** Resolve `CREATE_SALARY_INCENTIVE` prefix contradiction (`action_registry.py:1241` vs `schema_registry.py:256-260`), enforce `SalaryReceipts` child-row collision validation, and add an automated test verifying all `127` actions accept at least one canonical ID (zero deadlocks).
3. **Fix `P1.5-003` (HIGH):** Make `is_token_revoked()` and `sessions_revoked_at` fail closed, align `routers/auth.py:101` active-user check with `auth.py:282`, handle logout persistence failure cleanly, and harden `RevokedTokens`/`AuthUsers` cache freshness.
4. **Fix `P1.5-005` & `P1.5-006` (MEDIUM):** Enforce required-column + duplicate-header validation inside `approve_core_schema_reconciliation()` and JSON approval loader; align frontend blocked-schema error handling (`api.ts:677`, `ErpOperationsHubView.tsx:294`) and Group `02`/`10` badge statuses + unmapped/blocked summary counters.
5. **Address `P1.5-007`, `P1.5-008`, `P1.5-009` (MEDIUM/LOW):** Add pre-write validation for client-supplied IDs, downgrade production `SheetsDB` OAuth scopes to `spreadsheets.readonly`, gate offline direct-write scripts, add `exp` enforcement to `backend/tests/__init__.py` mock `jwt`, and align lockout message (`120s` vs `"5 minutes"`).
6. **Re-run Phase 1.5 verification probes** to confirm all 9 findings transition to `VERIFIED_FIXED` with zero regressions.

### Step B — External Artifact Resolution (Required for Full Phase 1 Closure)
- Owner supplies:
  1. Authoritative 255-tab `.xlsx` workbook and `DBV5_FIELD_DICTIONARY_3074` (`DB-003`),
  2. Live physical Row-1 header export for the exact **12** conflicting core tables (`Suppliers`, `CustomRoles`, `SalaryIncentives`, `RawMaterials`, `Products`, `Workers`, `Customers`, `Sales`, `ProductionBatches`, `PackagingBatches`, `Expenses`, `ShopVisits`) and **24** unmapped blueprint tabs (`DB-007`), and
  3. Live Google Apps Script `WebAppBridge.gs` / `doPost` writer source (`DB-008`).
- *(Alternative for Phase 2 start only, NOT production go-live)*: After **Step A** passes re-verification, the Owner may issue a written scoped waiver allowing Phase 2 API/RBAC audit to proceed in parallel while `DB-003`/`DB-007`/`DB-008` remain strictly write-blocked for production deployment.

---

## 5. Live System Safety Attestation

- **Zero live Google Sheets read/write operations** were executed.
- **Zero live Google Apps Script calls or deployments** were executed.
- **Zero Render deployments, env var changes, or credential accesses** were executed.
- **Zero edits** were made to any existing source code, test file, schema, configuration, or dependency during Phase 1.5.
