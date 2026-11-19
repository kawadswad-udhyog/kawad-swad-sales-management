# KAWAD SWAD ERP — PHASE 1.5 SECURITY & WRITE PATH AUDIT
**Audit Mode:** Independent Read-Only Audit (Zero Source Edits; Zero Live Access)
**Audit Date:** 2026-11-19

---

## 1. Authentication & Authorization Security Audit (Sections 9 & 10)

### 1.1 `P1-NEW-06` Startup Fix Verification (`backend/app/routers/auth.py`)
- **Verified:** `require_sheets_connection` is imported from `app.auth` (`backend/app/routers/auth.py:17`) and wired into `@router.post("/api/auth/change-password", dependencies=[Depends(require_sheets_connection)])` (line 162).
- **Circular Import Check:** No circular import introduced (`auth.py` imports `app.config` and `app.permissions` at top level and lazily imports `app.sheets` and `app.apps_script_bridge` inside functions).
- **Startup Verification:** `from app import main` imports cleanly in isolated stdlib mode (`test_db001_app_main_and_v2_erp_import_startup` passes).

### 1.2 Fail-Closed Authentication & Authorization Controls — Live Probe Results

| Control | File / Line | Expected Behavior | Independently Verified Result | Status |
|---|---|---|---|---|
| Missing `Authorization` header | `backend/app/auth.py:249-254` | HTTP `401` | Live probe: `DENY 401 ('Missing Authorization header')` | **PASS** |
| Invalid / malformed JWT | `backend/app/auth.py:256-263` | HTTP `401` | Live probe: `DENY 401 ('Session expired or invalid token')` | **PASS** |
| Expired JWT | `backend/app/auth.py:80-84` | HTTP `401` (via `PyJWT` `exp` check) | **UNVERIFIED AT RUNTIME** — stdlib mock `jwt` in `backend/tests/__init__.py` ignores `exp` (`ALLOW` in mock harness); real `PyJWT` checks `exp` by default | **PARTIAL (ENV GAP)** |
| Password hashing | `backend/app/auth.py:36-65` | PBKDF2-SHA256 only (`100,000` iter, `hmac.compare_digest`), rejects legacy plaintext/SHA-256 | Verified in source (`verify_password` & `password_needs_reset`) | **PASS** |
| Missing `AuthUsers` / Sheets unreachable in `get_current_user` | `backend/app/auth.py:269-281` | Fail closed (`503` on sheet error, `401` on missing user) — no fallback to stale JWT claims | Verified in source | **PASS** |
| Deactivated user check (`active`) | `backend/app/auth.py:282` vs `backend/app/routers/auth.py:101` | Reject `false`, `0`, `no` consistently on login AND token validation | `get_current_user` rejects `active="0"` (`DENY 401`), **BUT** `routers/auth.py:101` only checks `== "false"`, allowing `active="0"`/`"no"` to mint a JWT at login | **DEFECT (`P1.5-003`)** |
| **Persisted `RevokedTokens` check on read error** | `backend/app/auth.py:216-226` | **Fail CLOSED** when `RevokedTokens` cannot be read | **LIVE-REPRODUCED FAIL-OPEN:** `except Exception: pass` returns `False`, allowing revoked token access during Sheets errors/429 (`ALLOW USR-SALES-001`) | **HIGH DEFECT (`P1.5-003`)** |
| **`RevokedTokens` & `AuthUsers` cache freshness** | `backend/app/auth.py:217, 236` | Fresh reads or short security TTL on revocation/deactivation | Both call `db.get_records(..., fresh=False)` -> up to **30-second stale cache window** after revocation/password change/deactivation across workers | **HIGH DEFECT (`P1.5-003`)** |
| **`sessions_revoked_at` parse failure** | `backend/app/auth.py:298-311` | Fail closed on unparseable revocation timestamp | `except (ValueError, TypeError): pass` -> **FAIL-OPEN** if Sheets reformats timestamp string | **DEFECT (`P1.5-003`)** |
| **Logout revocation persistence** | `backend/app/routers/auth.py:143-146` & `auth.py:94-145` | Report/handle failure clearly when revocation fails to persist | Calls `revoke_token(..., raise_on_failure=False)`; when Apps Script bridge is unconfigured, returns `{"ok": true, "persisted": false}` (in-memory only, lost on restart) | **MEDIUM (`P1.5-003`)** |
| `require_sheets_connection()` | `backend/app/auth.py:321-329` | Fail closed (`503`) if disconnected | Live probe: returns `True` (**FAIL-OPEN**) when `SALES_GOOGLE_SPREADSHEET_ID` is empty and `db.is_connected == False` (mitigated in prod by `assert_runtime_config()`) | **LOW (`P1.5-009`)** |
| Brute-force lockout | `backend/app/routers/auth.py:26-28, 70-77` | Persistent lockout matching user message | In-memory dict `_LOGIN_ATTEMPTS` only (bypassed on restart/multi-worker); window is `120s` (2 min) while error message claims `"5 minutes"` | **LOW (`P1.5-009`)** |
| Owner-only & RBAC backend enforcement | `backend/app/permissions.py:367-448` | Default-deny; `OWNER_ONLY_PERMISSIONS` cannot be granted by custom roles | Live probe: `require_owner(FIELD_SALESMAN)` -> `DENY 403`; `OWNER_ONLY_PERMISSIONS` enforced in `has_permission()` & `validate_custom_role_permissions()` | **PASS** |
| JWT secret fail-closed in production | `backend/app/config.py:44-63` | Raise `RuntimeError` in `SALES_ENV=production` if secret missing/insecure/`<32` chars | Verified in source (`assert_runtime_config()` calls `jwt_secret()`) | **PASS** |
| Frontend token storage | `src/services/api.ts:151-156` | Document XSS tradeoff of `localStorage` bearer token | Token stored in `localStorage` (`STORAGE_TOKEN_KEY`); cleared on 401/logout. Backend does not rely on frontend RBAC | **LOW (INFO/TRADEOFF)** |

---

## 2. CRITICAL Secondary-Tab Bypass Audit (Section 4 — `P1.5-001`)

### Root Cause in Source Code
In `backend/app/apps_script_bridge.py:556-564`:
```python
candidate_write_tabs: List[str] = [clean_tab]
secondary_tabs_to_check = requested_inv if requested_inv else sorted(spec.allowed_invalidate_tabs)
for sec_tab in secondary_tabs_to_check:
    if sec_tab not in candidate_write_tabs:
        candidate_write_tabs.append(sec_tab)
for child_check in spec.readback.child_checks:
    if child_check.tab not in candidate_write_tabs:
        candidate_write_tabs.append(child_check.tab)
```
**Defect:** Whenever a caller supplies a non-empty `invalidate_tabs` list that is a proper subset of `spec.allowed_invalidate_tabs`, `requested_inv` is truthy so `sorted(spec.allowed_invalidate_tabs)` is **never inspected**. Any conflicting secondary tab omitted from `invalidate_tabs` (and not present in `child_checks`) **completely bypasses `get_schema_write_block_reason()`**.

### Live-Reproduced Production Router Bypasses
1. **`backend/app/routers/purchasing.py:520-534` (`RECEIVE_GOODS`):**
   - Primary tab: `GoodsReceipts` (unblocked).
   - Registry `allowed_invalidate_tabs` includes **`RawMaterials`** (CONFLICTING).
   - Call-site passes `invalidate_tabs=["GoodsReceipts", "GoodsReceiptItems", "RawMaterialLedger", "PurchaseOrderItems"]` — **omits `RawMaterials`**.
   - **Result:** `DB-002` block on `RawMaterials` is **BYPASSED**!
2. **`backend/app/routers/v2_erp.py:1146-1164` (`RECORD_MILLING_BATCH`):**
   - Primary tab: `MillingBatches` (unblocked).
   - Registry `allowed_invalidate_tabs` includes **`RawMaterials`** (CONFLICTING).
   - Call-site passes `invalidate_tabs=["MillingBatches", "RawMaterialLedger", "JournalHeaders", "JournalLines"]` — **omits `RawMaterials`**.
   - **Result:** `DB-002` block on `RawMaterials` is **BYPASSED**!
3. **Latent Call-Site Bypasses (currently masked only while primary tab stays blocked):**
   - `backend/app/routers/v2_erp.py:634` (`RECORD_PACKAGING_BATCH` — omits conflicting `Products`).
   - `backend/app/routers/v2_erp.py:1172` (`CREATE_PRODUCTION_BATCH` — omits conflicting `RawMaterials`).

### Exhaustive Secondary-Tab Mapping Table (All 32 Governed Actions Touching Any Write-Blocked Tab; 63 Multi-Tab Actions Audited Total)

*(All 31 remaining multi-tab actions touch exclusively non-conflicting/unblocked core tables and are not blocked.)*

| Action | Primary Tab | Secondary Tabs (`allowed_invalidate_tabs` ∪ `child_checks`) | Guard Applied | Before Mutation | Bypass Found |
|---|---|---|---|---|---|
| `ADJUST_FINISHED_GOODS_STOCK` | `ProductionStockLedger` | `Products` *(CONFLICTING)* | Conditional (`if not requested_inv`) | Only if `inv` includes `Products` or is `None` | **YES — Bridge bypass if `inv=['ProductionStockLedger']`** |
| `ADJUST_RAW_MATERIAL_STOCK` | `RawMaterialLedger` | `RawMaterials` *(CONFLICTING)* | Conditional (`if not requested_inv`) | Only if `inv` includes `RawMaterials` or is `None` | **YES — Bridge bypass if `inv=['RawMaterialLedger']`** |
| `APPROVE_AND_EXECUTE_REQUEST` | `ApprovalRequests` | `AuthUsers`, `ProductionBatches` *(CONFLICTING)*, `Users` | Conditional (`if not requested_inv`) | Only if `inv` includes `ProductionBatches` or is `None` | **YES — Bridge bypass if `inv=['ApprovalRequests']`** |
| `ISSUE_RAW_MATERIALS` | `RawMaterialLedger` | `IncompleteTransactions`, `ProductionBatches` *(CONFLICTING, child)*, `RawMaterials` *(CONFLICTING)* | `ProductionBatches` via `child_checks`; `RawMaterials` conditional | `ProductionBatches` always; `RawMaterials` skipped if omitted | **PARTIAL — `RawMaterials` bypassed if `ProductionBatches` reconciled first & `inv` omits `RawMaterials`** |
| `RECEIVE_GOODS` | `GoodsReceipts` | `GoodsReceiptItems`, `PurchaseOrderItems`, `PurchaseOrders`, `RawMaterialLedger`, `RawMaterials` *(CONFLICTING)* | Conditional (`if not requested_inv`) | **NO** at live call-site | **YES (LIVE ROUTER BYPASS at `purchasing.py:520`)** |
| `RECEIVE_RAW_MATERIAL` | `RawMaterialLedger` | `RawMaterials` *(CONFLICTING)* | Conditional (`if not requested_inv`) | Only if `inv` includes `RawMaterials` or is `None` | **YES — Bridge bypass if `inv=['RawMaterialLedger']`** |
| `RECORD_MILLING_BATCH` | `MillingBatches` | `JournalHeaders`, `JournalLines`, `RawMaterialLedger`, `RawMaterials` *(CONFLICTING)* | Conditional (`if not requested_inv`) | **NO** at live call-site | **YES (LIVE ROUTER BYPASS at `v2_erp.py:1146`)** |
| `RECORD_SALE_PAYMENT` | `Payments` | `CashLedger`, `JournalHeaders`, `JournalLines`, `Sales` *(CONFLICTING)* | Conditional (`if not requested_inv`) | Only if `inv` includes `Sales` or is `None` | **YES — Bridge bypass if `inv=['Payments']`** |
| `RECOVER_MILLING_BATCH` | `RawMaterialLedger` | `MillingBatches`, `RawMaterials` *(CONFLICTING)* | Conditional (`if not requested_inv`) | Only if `inv` includes `RawMaterials` or is `None` | **YES — Bridge bypass if `inv=['RawMaterialLedger']`** |
| `REJECT_APPROVAL_REQUEST` | `ApprovalRequests` | `ProductionBatches` *(CONFLICTING)* | Conditional (`if not requested_inv`) | Only if `inv` includes `ProductionBatches` or is `None` | **YES — Bridge bypass if `inv=['ApprovalRequests']`** |
| `SUBMIT_DAILY_CLOSING` | `DailyClosing` | `Expenses` *(CONFLICTING)*, `JournalHeaders`, `JournalLines` | Conditional (`if not requested_inv`) | Only if `inv` includes `Expenses` or is `None` | **YES — Bridge bypass if `inv=['DailyClosing']`** |
| `VERIFY_RAW_MATERIAL_OPENING_STOCK` | `RawMaterialLedger` | `AuditLog`, `RawMaterials` *(CONFLICTING)* | Conditional (`if not requested_inv`) | Only if `inv` includes `RawMaterials` or is `None` | **YES — Bridge bypass if `inv=['RawMaterialLedger']`** |
| `APPROVE_PRODUCTION_BATCH` | `ProductionBatches` *(CONFLICTING)* | `ApprovalRequests`, `IncompleteTransactions`, `JournalHeaders`, `JournalLines`, `ProductionStockLedger`, `RawMaterialLedger`, `RawMaterials` *(CONFLICTING)* | Primary always; `RawMaterials` conditional | Primary YES | **LATENT — `RawMaterials` bypassed if primary unlocked first** |
| `CREATE_PRODUCTION_BATCH` | `ProductionBatches` *(CONFLICTING)* | `ApprovalRequests`, `ProductLots`, `ProductionStockLedger`, `RawMaterialLedger`, `RawMaterials` *(CONFLICTING)* | Primary always; `RawMaterials` conditional | Primary YES | **LATENT (LIVE CALL-SITE `v2_erp.py:1172` omits `RawMaterials`)** |
| `CREATE_SALES_INVOICE` | `Sales` *(CONFLICTING)* | `Customers` *(CONFLICTING)*, `JournalHeaders`, `JournalLines`, `ProductionStockLedger`, `SaleItems`, `SalesmanStockLedger` | Primary always; `Customers` conditional | Primary YES | **LATENT — `Customers` bypassed if primary unlocked first** |
| `RECORD_PACKAGING_BATCH` | `PackagingBatches` *(CONFLICTING)* | `JournalHeaders`, `JournalLines`, `ProductLots`, `ProductionStockLedger`, `Products` *(CONFLICTING)* | Primary always; `Products` conditional | Primary YES | **LATENT (LIVE CALL-SITE `v2_erp.py:634` omits `Products`)** |
| `APPROVE_PACKAGING_DISCREPANCY` | `PackagingBatches` *(CONFLICTING)* | `ApprovalRequests`, `AuditLog`, `ProductionStockLedger` | Primary always | YES | No |
| `CANCEL_SALE` | `Sales` *(CONFLICTING)* | `CashLedger`, `JournalHeaders`, `JournalLines`, `Payments`, `SalesmanStockLedger` | Primary always | YES | No |
| `CONFIRM_SALES_ORDER` | `Sales` *(CONFLICTING)* | `JournalHeaders`, `JournalLines`, `SalesmanStockLedger` | Primary always | YES | No |
| `CREATE_LEGACY_SALES_ORDER` | `Sales` *(CONFLICTING)* | `SaleItems` | Primary always | YES | No |
| `CREATE_SALE` | `Sales` *(CONFLICTING)* | `ApprovalRequests`, `CashLedger`, `JournalHeaders`, `JournalLines`, `Payments`, `SaleItems`, `SalesmanStockLedger` | Primary always | YES | No |
| `CREATE_SALES_ORDER` | `SalesOrders` *(PENDING)* | `SalesOrderItems` *(PENDING, child)* | Primary + child | YES | No |
| `DISBURSE_APPROVED_ADVANCE` | `EmployeeAdvances` *(PENDING)* | `JournalHeaders`, `JournalLines` | Primary always | YES | No |
| `PAY_SALARY_INCENTIVE` | `SalaryIncentives` *(CONFLICTING)* | `JournalHeaders`, `JournalLines` | Primary always | YES | No |
| `RECONCILE_PACKAGING_BATCH` | `PackagingBatches` *(CONFLICTING)* | `ProductionStockLedger` | Primary always | YES | No |
| `RECORD_MARKETPLACE_SETTLEMENT` | `MarketplaceSettlements` *(PENDING)* | `JournalHeaders`, `JournalLines` | Primary always | YES | No |
| `RECORD_PACKAGING_PENDING_REVIEW` | `PackagingBatches` *(CONFLICTING)* | `ApprovalRequests` | Primary always | YES | No |
| `RECOVER_PACKAGING` | `PackagingBatches` *(CONFLICTING)* | `IncompleteTransactions`, `ProductionStockLedger` | Primary always | YES | No |
| `REJECT_PRODUCTION_BATCH` | `ProductionBatches` *(CONFLICTING)* | `ApprovalRequests` | Primary always | YES | No |
| `RESOLVE_LEGACY_BATCH_COST` | `ProductionBatches` *(CONFLICTING)* | `ProductionStockLedger` | Primary always | YES | No |
| `RESUME_SALE` | `Sales` *(CONFLICTING)* | `CashLedger`, `Payments`, `SaleItems`, `SalesmanStockLedger` | Primary always | YES | No |
| `REVIEW_EXPENSE` | `Expenses` *(CONFLICTING)* | `JournalHeaders`, `JournalLines` | Primary always | YES | No |

---

## 3. Direct-Write Protection Audit (Section 13)

Exhaustive AST search across all `backend/app/**/*.py` and `backend/scripts/*.py` files for direct Google Sheets writes, alternative HTTP bridges, background mutations, and legacy write methods:

| Write Path | Location | Governed? | Protection | Risk |
|---|---|---|---|---|
| FastAPI routes & services (132 call-sites, 127 actions) | `backend/app/routers/*.py`, `backend/app/user_service.py`, `backend/app/auth.py`, `backend/app/accounting/{journal_engine,customer_ledger}.py` | **YES** (`AppsScriptBridge`) | Allowlist (`GOVERNED_ACTION_REGISTRY`), HMAC-SHA256, `_NoRedirectHandler`, echo validation, read-back verification | **CRITICAL** on secondary-tab subset bypass (`P1.5-001`); **CRITICAL** external blocker (`DB-008` Apps Script writer unaudited) |
| `SheetsDatabase.append_record / update_record / delete_record / generate_id / allocate_bill_number / _ensure_headers` | `backend/app/sheets.py:1115, 1450, 1568, 1706, 1785, 1816` | **BLOCKED AT RUNTIME** | `_assert_direct_mutation_allowed()` raises `RuntimeError("BLOCKED_PENDING_OWNER_SETUP...")` whenever connected to live Sheets OR `SALES_TESTING != 1`; zero callers left in `backend/app/routers/` or `accounting/` | **LOW** (defense-in-depth note: dead live-write code branches remain inside methods + service account still requests read-write OAuth scopes `spreadsheets` / `drive.file` at `sheets.py:676-677` — `P1.5-008`) |
| `SheetsDatabase.log_audit` (incl. `BackgroundTasks.add_task(db.log_audit, ...)`) | `backend/app/sheets.py:1848-1884` (called across routers) | **NO-OP TO SHEETS AT RUNTIME** | When connected or `SALES_TESTING != 1`, emits Python `logger.info(...)` only and returns without touching Google Sheets | **LOW** (no direct Sheets write; audit telemetry in FastAPI is log-only while authoritative `AuditLog` writes depend on unaudited Apps Script `DB-008`) |
| `workforce_migration.py` (`add_worksheet`, `del_worksheet`, `ws.clear`, `ws.update`) | `backend/app/workforce_migration.py:572, 578, 612, 916, 929, 932, 934` | **NO (Offline CLI Only)** | Not imported by `app.main` or any FastAPI router; imported only by `backend/scripts/migrate_workforce_stage3.py` and `test_workforce_migration_safety.py`; does **not** call `_assert_direct_mutation_allowed()` | **MEDIUM (`P1.5-008`)** — if invoked manually with live credentials, bypasses Single-Write-Owner |
| Offline CLI scripts (`bootstrap_owner.py`, `reset_password.py`, `migrate_workforce_stage3.py`, `run_staging_walkthrough.py`, `update_sheets_recipe_master.py`) | `backend/scripts/*.py` | **NO (Offline CLI)** | 4 scripts call `db.append_record`/`update_record` (blocked by `_assert_direct_mutation_allowed` when connected); `migrate_workforce_stage3.py` uses `workforce_migration.py` | **MEDIUM (`P1.5-008`)** — stale/incompatible with Single-Write-Owner if executed against live Sheets |
| Alternative HTTP clients (`urllib` / `requests` / `httpx`) | `backend/app/apps_script_bridge.py` ONLY | **YES** | Zero outbound HTTP calls exist anywhere else in `backend/app/` | **PASS (ZERO ROGUE BRIDGES)** |
| `allow_generated_nonce=True` | `backend/app/apps_script_bridge.py:937` | **YES** | Zero call-sites pass `allow_generated_nonce=True` across the entire codebase | **PASS** |
