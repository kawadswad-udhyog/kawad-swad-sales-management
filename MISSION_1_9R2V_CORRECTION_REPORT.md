# KAWAD SWAD ERP — MISSION 1.9R-2V CORRECTION REPORT

**Mission:** MISSION 1.9R-2V — Test Repair & Baseline Restoration  
**Starting Baseline:** ZIP63 (post-Mission 1.9R-2 state)  
**Date:** 2026-11-23  
**Scope:** Narrow corrective repair of Pydantic request payloads and guard-reach assertions in `backend/tests/test_mission1_9r2_factory_worker_rbac.py`, plus baseline lockfile verification and clean flat-root archive generation. Zero RBAC implementation changes; zero external system access.

---

## 1. RBAC Implementation Integrity Confirmation

No RBAC implementation files were modified during Mission 1.9R-2V. Testing uncovered zero source-code defects in the Mission 1.9R-2 RBAC repair. Byte-for-byte SHA-256 parity against ZIP63 is preserved across all RBAC files:

| File | ZIP63 SHA-256 | Current SHA-256 | Status |
| --- | --- | --- | --- |
| `backend/app/permissions.py` | `304622273a20d46ff7f0dbabdff10781751404f9c7a047d564f9f4486d7ca218` | `304622273a20d46ff7f0dbabdff10781751404f9c7a047d564f9f4486d7ca218` | **UNCHANGED** |
| `backend/app/routers/production.py` | `7a5a344dfcc6665ffcf57de68e4666648df4d224cd310e29c97d7826abd17c7e` | `7a5a344dfcc6665ffcf57de68e4666648df4d224cd310e29c97d7826abd17c7e` | **UNCHANGED** |
| `backend/app/routers/v2_erp.py` | `7189e1937389a45f8339ddf4e502b57e037f7b4c8aaf0850d26e5c9eb40ff279` | `7189e1937389a45f8339ddf4e502b57e037f7b4c8aaf0850d26e5c9eb40ff279` | **UNCHANGED** |
| `src/utils/permissions.ts` | `eb3607938cd3acfa0e7a5f7795c25c6759af3b6af3444883546bd35381a36223` | `eb3607938cd3acfa0e7a5f7795c25c6759af3b6af3444883546bd35381a36223` | **UNCHANGED** |
| `src/views/QualityView.tsx` | `f10dde393a7f5a5bc866097e7efc5b8430887cf8a1080ce8bbba4e01ff50f28f` | `f10dde393a7f5a5bc866097e7efc5b8430887cf8a1080ce8bbba4e01ff50f28f` | **UNCHANGED** |

---

## 2. Exact Diff Summary (`backend/tests/test_mission1_9r2_factory_worker_rbac.py`)

Only one code/test file was modified: `backend/tests/test_mission1_9r2_factory_worker_rbac.py`  
- **Before (ZIP63) SHA-256:** `a37244c30a52462381fc654bb4814ff836a5784a9636cb24e48f8edab84c4fdd`  
- **After (1.9R-2V) SHA-256:** `b03f878da5845c572e5fe26044cf34ce2918e6761dc6ed82f4f347f8419b821b`

### 2.1 Three Required Failing Pydantic Request Payloads Fixed

1. **`RecipeSave` (`test_02_factory_worker_cannot_create_production_records`):**
   - **Previous (invalid under real Pydantic):** `RecipeSave(product_id="PRD-M-200", base_output_kg=10, ingredients=[{"raw_material_id": "RM-MOONG", "quantity": 10, "unit": "kg"}])`
   - **Corrected (exact schema match to `production.py:199-223`):**
     ```python
     recipe_item = self._build_validated(
         prod_mod.RecipeItemInput,
         material_name="Moong Flour",
         quantity_per_kg=1.0,
         unit="kg",
     )
     recipe_req = self._build_validated(
         prod_mod.RecipeSave,
         product_id="PRD-M-200",
         items=[recipe_item],
         expected_yield_kg=10.0,
     )
     ```
2. **`DalMillingCreate` (`test_03_factory_worker_cannot_edit_production_records`):**
   - **Previous (invalid under real Pydantic):** `DalMillingCreate(raw_dal_id="RM-WHOLE-MOONG-DAL", raw_dal_input_kg=10, flour_output_kg=9)`
   - **Corrected (exact schema match to `production.py:418-432`):**
     ```python
     mill_req = self._build_validated(
         prod_mod.DalMillingCreate,
         source_material_id="RM-WHOLE-MOONG-DAL",
         input_quantity_kg=10.0,
         flour_output_kg=9.0,
     )
     ```
3. **`GigWorkSubmitRequest` (`test_05_factory_worker_denied_on_alternate_privileged_routes`):**
   - **Previous (invalid under real Pydantic):** `GigWorkSubmitRequest(labour_id="LAB-1", work_date="2026-11-01", quantity_kg=10, rate_per_kg=15, nonce="fw-gig-nonce-1")`
   - **Corrected (exact schema match to `v2_erp.py:146-155`):**
     ```python
     gig_req = self._build_validated(
         v2_erp_mod.GigWorkSubmitRequest,
         nonce="fw-gig-nonce-1",
         worker_id="LAB-1",
         work_date="2026-11-01",
         activity_name="Papad Rolling",
         units_completed=Decimal("10"),
         unit_of_measure="KG",
         piece_rate=Decimal("15"),
     )
     ```

### 2.2 Additional Schema Mismatches Caught & Fixed During Full Payload Audit

Auditing every single Pydantic model instantiated in `test_mission1_9r2_factory_worker_rbac.py` caught five additional schema mismatches (including `LabourWorkEntryCreate`, which was hidden behind `GigWorkSubmitRequest` in `test_05` and would also have raised `ValidationError` under real Pydantic):

| Model | File | Previous Fields | Corrected Fields |
| --- | --- | --- | --- |
| `LabourWorkEntryCreate` | `models.py:741` | `labour_id`, `work_date`, `task_type`, `quantity`, `rate` (missing required `entry_date`, `activity_name`) | `labour_id="LAB-1"`, `entry_date="2026-11-01"`, `activity_name="ROLLING"`, `units_completed=5.0`, `unit_of_measure="KG"`, `piece_rate=10.0` |
| `RawMaterialReceiveRequest` | `production.py:331` | `rate_per_unit=90` | `purchase_rate=90.0` |
| `PackagingCreate` | `production.py:277` | `bulk_used_kg=5` | `bulk_kg_used=5.0` |
| `RecipeConfirmRequest` | `production.py:254` | `notes="unauthorized confirm"` | `approved=True`, `change_notes="unauthorized confirm"` |
| `QualityCheckCreate` | `quality.py:55` | `result="PASS"` | `decision="PASS"` |
| `GovernedProductionBatchRequest` & `GovernedMillingBatchRequest` | `v2_erp.py:205,216` | `int` literals for `Decimal` fields | Explicit `Decimal(...)` values |

### 2.3 Guard-Reach & Non-Masking Enforcement Added

- **`_build_validated(model_cls, **kwargs)`:** Constructs every request payload **outside** `with self.assertRaises(HTTPException)` blocks so schema validation failures can never be masked by `assertRaises`. Also verifies declared-field membership (zero unknown kwargs) and required-field presence against model annotations even under the stdlib compatibility shim.
- **`_assert_guard_403(guard_target, guard_attr, call_fn)`:** Spies on the actual route authorization guard (`prod_mod.require_production_access`, `prod_mod.require_owner`, `v2_erp_mod.require_module_action`, `v2_erp_mod.require_roles`, `quality_mod.require_roles`, `workforce_mod.require_roles`) via `patch.object(..., wraps=...)`, asserting `guard_spy.call_count >= 1`, `status_code == 403`, and non-empty denial detail.
- **Zero weakened assertions:** All 12 test methods and all original security assertions are preserved intact.
