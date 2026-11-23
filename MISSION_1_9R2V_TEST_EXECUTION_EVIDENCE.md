# KAWAD SWAD ERP — MISSION 1.9R-2V TEST EXECUTION EVIDENCE

**Mission:** MISSION 1.9R-2V — Test Repair & Baseline Restoration  
**Date:** 2026-11-23

---

## 1. Execution Environment & Dependency Inventory

| Component | Observed Status / Version |
| --- | --- |
| Operating System / Runtime | Linux container (`/app/applet`) |
| Python | `3.11.2 (main, Oct 7 2026, 12:35:07) [GCC 12.2.0]` (`/usr/bin/python3`) |
| Node.js / npm | Node `v22.23.2` / npm `10.9.8` |
| `fastapi` | **MISSING** (`ModuleNotFoundError`) — repository stdlib shim active (`backend/tests/__init__.py`) |
| `pydantic` | **MISSING** (`ModuleNotFoundError`) — repository stdlib shim active (`backend/tests/__init__.py`) |
| `uvicorn` | **MISSING** (`ModuleNotFoundError`) |
| `pyjwt` (`jwt`) | **MISSING** (`ModuleNotFoundError`) — repository stdlib HS256 shim active |
| `httpx` | **MISSING** (`ModuleNotFoundError`) |
| `starlette` | **MISSING** (`ModuleNotFoundError`) |
| `pytest` | **MISSING** (`ModuleNotFoundError`) — executed via stdlib `python3 -B -m unittest` |
| `gspread` / `google.oauth2` | **MISSING** (`ModuleNotFoundError`) |

> **Honest Environment Disclosure:** Real third-party Python packages (`fastapi`, `pydantic`, `uvicorn`, `pyjwt`, `pytest`) are NOT installed in this container. To ensure schema validation errors cannot hide behind the stdlib mock shim, **two** targeted executions were performed: (A) standard `unittest` run using the repository harness, and (B) an in-memory **strict Pydantic `Field`-constraint validator run** enforcing required fields, zero extra/unknown fields, `min_length`, `max_length`, `gt`, `ge`, `Literal`, and `Decimal` types across every model instantiated by the test suite.

---

## 2. Targeted Mission 1.9R-2 Security Test Suite Results

### 2.1 Standard Execution
- **Command:**
  ```bash
  PYTHONDONTWRITEBYTECODE=1 SALES_TESTING=1 python3 -B -m unittest backend/tests/test_mission1_9r2_factory_worker_rbac.py -v
  ```
- **Totals:** `12` tests run | **`12` PASSED** | `0` FAILED | `0` ERRORS | `0` SKIPPED | Elapsed: `0.231s`

### 2.2 Strict Pydantic Schema & `Field`-Constraint Enforcement Audit
- **Method:** Injected a strict `pydantic` module enforcing declared field membership (no unknown kwargs), required fields (`Field(...)` / uninitialized annotations), `min_length`, `max_length`, `gt`, `ge`, `Literal`, and `Decimal` before loading `tests.test_mission1_9r2_factory_worker_rbac`.
- **Totals:** `12` tests run | **`12` PASSED** | `0` FAILED | `0` ERRORS | `0` SKIPPED | Elapsed: `0.126s`

### 2.3 Per-Test & Authorization-Guard Reach Matrix

Every single route-level security-denial test constructed its validated request payload **outside** `assertRaises(HTTPException)` and verified via `patch.object(..., wraps=...)` that the real authorization guard executed (`guard_spy.call_count >= 1`) and raised HTTP `403`:

| # | Test Method | Guards Explicitly Verified Reached (`call_count >= 1` -> HTTP `403`) | Result |
| --- | --- | --- | --- |
| 1 | `test_01_factory_worker_can_view_production_resources` | Positive view-only read checks (`prod.summary`, `prod.recipes`, `prod.batches`, `v2_erp.get_erp_capabilities`) | **PASS** |
| 2 | `test_02_factory_worker_cannot_create_production_records` | `prod_mod.require_production_access` (`create_batch`, `save_recipe`, `receive_raw_material`, `create_packaging`); `v2_erp_mod.require_module_action` (`create_v2_production_batch`, `create_v2_milling_batch`) | **PASS** |
| 3 | `test_03_factory_worker_cannot_edit_production_records` | `prod_mod.require_production_access` (`update_attendance`, `issue_materials`, `record_dal_milling_batch`, `dispatch`) | **PASS** |
| 4 | `test_04_factory_worker_cannot_approve_production_mutations` | `prod_mod.require_owner` (`approve_batch`, `confirm_master_recipe`) | **PASS** |
| 5 | `test_05_factory_worker_denied_on_alternate_privileged_routes` | `perms.require_production_access`, `perms.require_module_action`, `perms.require_roles`; `quality_mod.require_roles` (`create_quality_check`); `v2_erp_mod.require_roles` (`submit_gig_worker_entry`); `workforce_mod.require_roles` (`save_labour_attendance_bulk`, `create_labour_work_entry`) | **PASS** |
| 6 | `test_06_canonical_role_mapping_does_not_elevate_factory_worker` | Canonical mapping + `/api/auth/me` role preservation (`FACTORY_WORKER`) | **PASS** |
| 7 | `test_07_legacy_aliases_cannot_elevate_to_production` | For all 5 legacy/case/whitespace tokens: `prod_mod.require_production_access`, `v2_erp_mod.require_module_action`, `quality_mod.require_roles` | **PASS** |
| 8 | `test_08_role_normalization_cannot_widen_least_privilege_rules` | `prod_mod.require_production_access` for `AUDITOR` and forged-JWT `FACTORY_WORKER`; `perms.require_production_access` under simulated map override; `DISPATCH` non-escalation | **PASS** |
| 9 | `test_09_authorized_production_roles_retain_legitimate_access` | Positive access for `PRODUCTION`, `PACKAGING`, `PA`; `prod_mod.require_owner` -> `403` on PA batch approval | **PASS** |
| 10 | `test_10_owner_admin_retains_full_access_and_approvals` | Positive read/create/approval for `OWNER_ADMIN` and legacy `OWNER` | **PASS** |
| 11 | `test_11_route_level_backend_enforcement_end_to_end` | Positive `PRODUCTION` create vs `prod_mod.require_production_access` -> `403` for `FACTORY_WORKER`; capabilities check | **PASS** |
| 12 | `test_12_negative_authorization_returns_http_403_with_clear_detail` | Direct guard calls across `permissions.py` and `production.py` returning HTTP `403` with clear detail | **PASS** |

**Did all security-denial tests reach the authorization guards?** **YES** — 100% of route-level denial assertions verified `guard_spy.call_count >= 1` on the real backend guard after independent schema construction.

---

## 3. Full Backend Regression Suite

- **Command:**
  ```bash
  PYTHONDONTWRITEBYTECODE=1 SALES_TESTING=1 python3 -B -m unittest discover -s backend/tests -t backend
  ```
- **Totals:** `696` tests run | **`695` PASSED** | `1` SKIPPED (pre-existing environment skip) | `0` FAILED | `0` ERRORS | Elapsed: `35.715s`
- **Bytecode Hygiene:** `0` `__pycache__` directories or `.pyc` files in `backend/`.
