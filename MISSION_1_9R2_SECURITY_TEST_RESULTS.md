# KAWAD SWAD ERP — MISSION 1.9R-2 SECURITY TEST RESULTS

**Mission:** MISSION 1.9R-2 — FACTORY_WORKER Privilege Escalation Repair (`M19-002`)  
**Test Suite:** `backend/tests/test_mission1_9r2_factory_worker_rbac.py`  
**Command Executed:**
```bash
PYTHONDONTWRITEBYTECODE=1 SALES_TESTING=1 python3 -B -m unittest backend/tests/test_mission1_9r2_factory_worker_rbac.py -v
```
**Environment:** Python `3.11.2` (stdlib-only container runtime using repository test shims `backend/tests/__init__.py` and `backend/tests/v2_test_harness.py`)  
**Summary:** **12 / 12 PASSED** | **0 FAILED** | **0 ERRORS** | **0 SKIPPED** | Execution time: `0.130s`

---

## Scenario-by-Scenario Verification Matrix

| # | Test Method | Security Scenario Verified | Result |
| --- | --- | --- | --- |
| 1 | `test_01_factory_worker_can_view_production_resources` | `FACTORY_WORKER` passes `has_permission("production", "view")`, gets exact `effective_permissions_for == {"production": ["view"]}`, and succeeds on `GET /api/production/summary`, `GET /api/production/recipes`, `GET /api/production/batches`, and `GET /api/v2/meta/capabilities`. | **PASS** |
| 2 | `test_02_factory_worker_cannot_create_production_records` | `FACTORY_WORKER` fails `has_permission("production", "create")` and receives HTTP `403` on `POST /api/production/batches`, `POST /api/production/recipes`, `POST /api/production/raw-materials/receive`, `POST /api/production/packaging`, `POST /api/v2/production/batches`, and `POST /api/v2/milling/batches`. | **PASS** |
| 3 | `test_03_factory_worker_cannot_edit_production_records` | `FACTORY_WORKER` denied all production mutation actions (`update`, `edit`, `delete`, `record_consumption`, `record_output`, `record_loss`, `record_gig_work`, `costing`) and receives HTTP `403` on `PUT /api/production/attendance/{id}`, `POST /api/production/batches/{id}/issue-materials`, `POST /api/production/milling/record`, and `POST /api/production/dispatch`. | **PASS** |
| 4 | `test_04_factory_worker_cannot_approve_production_mutations` | `FACTORY_WORKER` denied `production:approve` and receives HTTP `403` on `POST /api/production/batches/{id}/approval` (with Owner-only denial detail) and `POST /api/production/recipes/master/{id}/confirm`. | **PASS** |
| 5 | `test_05_factory_worker_denied_on_alternate_privileged_routes` | `FACTORY_WORKER` receives HTTP `403` across alternate routes & guards: `permissions.require_production_access`, `require_module_action`, `require_roles({"OWNER_ADMIN", "PRODUCTION"})`, `POST /api/quality/checks`, `POST /api/v2/workforce/gig-entries`, `POST /api/workforce/labour/attendance/bulk`, and `POST /api/workforce/labour/work-entries`. | **PASS** |
| 6 | `test_06_canonical_role_mapping_does_not_elevate_factory_worker` | `CANONICAL_ROLE_V2_MAP["FACTORY_WORKER"]`, `canonical_role_v2`, `role_v2_of`, `resolve_authorized_role`, `ui_role`, and `GET /api/auth/me` all preserve `"FACTORY_WORKER"` and never elevate to `"PRODUCTION"`. | **PASS** |
| 7 | `test_07_legacy_aliases_cannot_elevate_to_production` | Legacy aliases (`PRODUCTION_WORKER`, `WORKER`) and case/whitespace variants (`factory_worker`, `"  production_worker  "`, `" worker "`) all normalize to `"FACTORY_WORKER"`, retain `prod.summary` view access, and receive HTTP `403` on `prod.create_batch`, `v2_erp.create_v2_production_batch`, and `quality.create_quality_check`. | **PASS** |
| 8 | `test_08_role_normalization_cannot_widen_least_privilege_rules` | Even under a simulated runtime patch mapping `FACTORY_WORKER -> PRODUCTION` in `CANONICAL_ROLE_V2_MAP`, explicit `DEFAULT_ROLE_PERMISSIONS["FACTORY_WORKER"]` takes strict precedence (no OR-union widening) and `require_production_access` still raises HTTP `403`. Also confirms `DISPATCH` maps to `STORE` without `SALES` escalation, `AUDITOR` stays read-only, forged JWT `"role": "PRODUCTION"` is overridden by fresh `AuthUsers` `"FACTORY_WORKER"`, and blank/unknown roles fail closed. | **PASS** |
| 9 | `test_09_authorized_production_roles_retain_legitimate_access` | `PRODUCTION` retains full operational production permissions and `POST /api/production/batches` (while still denied Owner-only approval); `PACKAGING` retains packaging & production access; `PA` retains batch creation while still denied Owner-only approval (HTTP `403`). | **PASS** |
| 10 | `test_10_owner_admin_retains_full_access_and_approvals` | `OWNER_ADMIN` and legacy `OWNER` retain full production read, create, and batch approval capabilities (`status == "APPROVED"`). | **PASS** |
| 11 | `test_11_route_level_backend_enforcement_end_to_end` | Direct end-to-end comparison on real router handlers confirming `PRODUCTION` can create batches and sees write capabilities while `FACTORY_WORKER` can read summary, receives HTTP `403` on batch creation, and sees `{"production": ["view"]}` from `/api/v2/meta/capabilities`. | **PASS** |
| 12 | `test_12_negative_authorization_returns_http_403_with_clear_detail` | Verifies all negative authorization guards across `permissions.py` and `production.py` consistently raise HTTP `403` with non-empty, clear denial detail messages. | **PASS** |

---

## Execution Environment Note

All 12 tests exercised the actual Python functions and FastAPI route handlers directly via the repository's `V2RouterProxy` and `LocalAppsScriptSimulator`. Because third-party Python packages (`fastapi`, `uvicorn`, `pydantic`, `pyjwt`) are not installed in this container's Python 3.11.2 stdlib-only environment, live ASGI HTTP transport over `uvicorn` was not executed here and should be included in CI/staging verification with `backend/requirements.txt` installed.
