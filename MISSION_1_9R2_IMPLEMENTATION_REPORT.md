# KAWAD SWAD ERP — MISSION 1.9R-2 IMPLEMENTATION REPORT

**Mission:** MISSION 1.9R-2 — FACTORY_WORKER Privilege Escalation Repair (`M19-002`)  
**Baseline:** ZIP62 (`/app/applet`, post-Mission 1.9R-1 baseline)  
**Date:** 2026-11-23  
**Scope:** Targeted RBAC authorization repair for `FACTORY_WORKER` and legacy factory-worker aliases (`PRODUCTION_WORKER`, `WORKER`), plus least-privilege permission precedence hardening. No Google Sheets access, no Apps Script execution, no deployment, no database/schema mutations, and no dependency changes.

---

## 1. Pre-Mission Housekeeping Status (`package-lock.json`)

- **Requested action:** Restore `package-lock.json` verbatim to its ZIP61 baseline and verify SHA-256 parity.
- **Observed container state:**
  - `/app/applet` is not a Git repository (`.git` absent) and no ZIP61 archive or backup `package-lock.json` exists anywhere in the container filesystem (inspected `/app/applet`, `/app`, `/tmp`, and artifact storage).
  - Current `package-lock.json` on disk: `52,108` bytes, SHA-256 `51a92fff4a509bc5fe213ed9e99322b8c7d50108dce5cc01ae70c8272f575861` (contains ZIP62's prior diff lacking `resolved`/`integrity` entries).
- **Action taken:** `package-lock.json` was left **strictly untouched** (`npm install` was NOT run) to honor the prohibition against unrelated dependency changes and avoid fabricating a false ZIP61 match. Restoring `package-lock.json` verbatim from the external ZIP61 archive is recorded as a mandatory release-packaging precondition in `MISSION_1_9R2_FINAL_GATE.md`.

---

## 2. Phase A — Complete Root-Cause Analysis (Authorization Path Trace)

Inspection of the full authorization pipeline across `backend/app/permissions.py`, `backend/app/auth.py`, `backend/app/routers/auth.py`, `backend/app/routers/production.py`, `backend/app/routers/v2_erp.py`, `backend/app/routers/quality.py`, `backend/app/routers/workforce.py`, and frontend role utilities revealed **four compounding elevation mechanisms**:

1. **Overbroad Canonical Role Normalization (`backend/app/permissions.py:82-84, 88`):**
   - `CANONICAL_ROLE_V2_MAP` mapped `"FACTORY_WORKER"`, `"PRODUCTION_WORKER"`, and `"WORKER"` directly to `"PRODUCTION"`.
   - As a result, `canonical_role_v2()`, `role_v2_of()`, and `resolve_authorized_role()` silently elevated every factory worker to `"PRODUCTION"`.
   - An analogous legacy-alias conflict existed for `"DISPATCH"`, which `CANONICAL_ROLE_V2_MAP` mapped to `"SALES"` while `DEFAULT_ROLE_PERMISSIONS["DISPATCH"]` intentionally scoped it to `V2_ROLE_PERMISSIONS["STORE"]`.

2. **Broad-First OR-Union Evaluation in `has_permission()` (`backend/app/permissions.py:492-499`):**
   - `has_permission()` iterated `for candidate in (v2_role, c_role, raw_role):` and returned `True` if **any** candidate granted `(module, action)`.
   - Because `v2_role` was evaluated first and unioned with `c_role`/`raw_role`, broad canonical role mappings unconditionally overrode explicit least-privilege entries in `DEFAULT_ROLE_PERMISSIONS` (e.g., `DEFAULT_ROLE_PERMISSIONS["FACTORY_WORKER"] = {"production": ["view"]}`).

3. **Downstream Route-Guard and Role-Disclosure Exposure:**
   - `backend/app/permissions.py:require_production_access()` and `backend/app/routers/production.py:require_production_access()` checked `role_v2_of(user) in {"PRODUCTION", "PACKAGING"}`, unintentionally granting `FACTORY_WORKER` write access to **12 production mutation endpoints** (`receive_raw_material`, `record_dal_milling_batch`, `add_worker`, `record_attendance`, `record_bulk_attendance`, `update_attendance`, `save_recipe`, `create_batch`, `issue_materials`, `create_packaging`, `recover_packaging`, `dispatch`).
   - `backend/app/routers/v2_erp.py` write endpoints (`POST /api/v2/milling/batches`, `POST /api/v2/production/batches`, `POST /api/v2/workforce/gig-entries`), `backend/app/routers/quality.py` (`POST /api/quality/checks`), and `backend/app/routers/workforce.py` (`POST /api/workforce/labour/attendance/bulk`, `POST /api/workforce/labour/work-entries`) authorized `"PRODUCTION"`, indirectly admitting `FACTORY_WORKER` through `role_v2_of()`.
   - `backend/app/permissions.py:ui_role()` returned `"PRODUCTION"` for `FACTORY_WORKERS`, causing `/api/auth/login` and `/api/auth/me` to advertise `"role": "PRODUCTION"` to the client.
   - `GET /api/v2/meta/capabilities` (`backend/app/routers/v2_erp.py:382`) looked up `V2_ROLE_PERMISSIONS.get(v2_role, {})`, which would either expose full `PRODUCTION` permissions (before fix) or an empty `{}` map (after fix) unless resolved via effective permissions.

4. **Frontend UI Alignment Gaps (`src/utils/permissions.ts`, `src/views/QualityView.tsx`):**
   - `DESIGNATIONS.production_worker` (`defaultRole: 'FACTORY_WORKER'`) had `canEditProduction: true`.
   - `QualityView.tsx` derived `canSubmitCheck` from `resolveCanonical12Role(currentUser?.role) === 'PRODUCTION'`, which mapped `FACTORY_WORKER` to `'PRODUCTION'` and displayed QC submission controls that the backend rejects with HTTP 403.

5. **Verified Non-Vulnerable Link (`backend/app/auth.py`):**
   - `get_current_user()` already discards JWT role claims and reloads the authoritative `role` fresh from `AuthUsers`, validating it against `KNOWN_SYSTEM_ROLES`. No change to JWT decoding was required.

---

## 3. Phase B & C — Targeted Changes Implemented

### 3.1 `backend/app/permissions.py`
- **Stopped broad elevation in `CANONICAL_ROLE_V2_MAP`:**
  - Mapped `"FACTORY_WORKER"`, `"PRODUCTION_WORKER"`, and `"WORKER"` to `"FACTORY_WORKER"` (never `"PRODUCTION"`).
  - Aligned `"DISPATCH"` to `"STORE"` (matching `DEFAULT_ROLE_PERMISSIONS["DISPATCH"] = V2_ROLE_PERMISSIONS["STORE"]`) so `DISPATCH` cannot escalate to `SALES`.
- **Enforced strict least-privilege precedence in `has_permission()`:**
  - Added `_resolve_builtin_permission_matrix(user)` resolving in strict specificity order `(raw_role, canonical_legacy_role, canonical_v2_role)` and **stopping at the first matched matrix** (`DEFAULT_ROLE_PERMISSIONS` checked before `V2_ROLE_PERMISSIONS`). No OR-union with broader fallback roles is possible.
  - Added `effective_permissions_for(user, custom_roles=None)` returning the exact effective permission dictionary for a user.
- **Added defense-in-depth denial in `require_production_access(user)`:**
  - Explicitly rejects `is_factory_worker(user)` with HTTP `403` before checking `PRODUCTION`/`PACKAGING`.
- **Aligned `ui_role(role)`:**
  - Returns `"FACTORY_WORKER"` for all `FACTORY_WORKERS` aliases (`FACTORY_WORKER`, `PRODUCTION_WORKER`, `WORKER`) and `"STORE"` for `"DISPATCH"`.

### 3.2 `backend/app/routers/production.py`
- Added `"FACTORY_WORKER"` to `PRODUCTION_READ_ROLES` so `FACTORY_WORKER` retains intended view-only access to production read routes (`summary`, `recipes`, `batches`, `raw-materials`, `milling`, `packaging`, `dispatches`, `costing`).
- Kept `PRODUCTION_ROLES` strictly free of `"FACTORY_WORKER"`.
- Added explicit `if is_factory_worker(user): raise HTTPException(status_code=403, ...)` guard in `require_production_access(user)` as defense-in-depth.

### 3.3 `backend/app/routers/v2_erp.py`
- Updated `GET /api/v2/meta/capabilities` to return `effective_permissions_for(current_user)` so `FACTORY_WORKER` receives `"role": "FACTORY_WORKER"` and `"module_permissions": {"production": ["view"]}`.

### 3.4 Frontend Alignment (`src/utils/permissions.ts`, `src/views/QualityView.tsx`)
- Added `isFactoryWorkerRole(role)` helper in `src/utils/permissions.ts` and updated `DESIGNATIONS.production_worker.canEditProduction` to `false`.
- Guarded `canSubmitCheck` in `src/views/QualityView.tsx` with `!isFactoryWorkerRole(currentUser?.role)` while keeping backend authorization strictly authoritative.

### 3.5 Security Test Suite (`backend/tests/test_mission1_9r2_factory_worker_rbac.py`)
- Added 12 dedicated security test methods verifying every required positive and negative RBAC boundary across permission helpers, role normalization, fresh `AuthUsers` resolution, and real route handlers in `production.py`, `v2_erp.py`, `quality.py`, `workforce.py`, and `routers/auth.py`.

---

## 4. Security Invariant Verification Summary

| Invariant | Status |
| --- | --- |
| `FACTORY_WORKER` retains view-only production access (`{"production": ["view"]}`) | **VERIFIED** |
| `FACTORY_WORKER` denied create/edit/approve on all production & alternate write routes (HTTP 403) | **VERIFIED** |
| Legacy aliases (`PRODUCTION_WORKER`, `WORKER`, case/whitespace variants) cannot elevate to `PRODUCTION` | **VERIFIED** |
| Explicit least-privilege matrices strictly precede broader canonical role mappings (no OR-union) | **VERIFIED** |
| `PRODUCTION`, `PACKAGING`, `PA`, and `OWNER_ADMIN` retain all legitimate permissions | **VERIFIED** |
| `DISPATCH` cannot escalate to `SALES`; `AUDITOR` remains read-only; forged JWT role claim overridden by `AuthUsers` | **VERIFIED** |
| Zero external system access, zero Apps Script calls, zero deployments, zero `__pycache__`/`.pyc` artifacts | **VERIFIED** |
