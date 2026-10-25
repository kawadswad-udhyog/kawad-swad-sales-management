"""
Comprehensive Failure-Injection, Recovery, and Idempotency Test Suite
for Raw-Material Issuance in Kawad Swad ERP.

Tests verify:
1. Normal material issue succeeds.
2. Repeating a successful issue does not add ledger rows (idempotency).
3. The second ledger append fails after the first succeeds (partial failure).
4. Retrying after a partial append completes only the missing work without duplicating.
5. All ledger rows succeed but the batch-status update fails.
6. Retrying after a status-update failure does not duplicate deductions.
7. Two simultaneous requests target the same batch (concurrency protection).
8. A recipe changes after an interrupted issue (reconciliation required / formulation lock).
9. A recipe contains duplicate lines for the same raw material (aggregation).
10. Insufficient stock causes no deductions (all-or-nothing pre-flight).
11. A referenced raw material is missing.
12. Mixed units (grams to kg, ml to L) are handled correctly.
13. Existing approval workflow integrates safely with issuance recovery.
"""

import os
import sys
import json
import unittest
import asyncio
from concurrent.futures import ThreadPoolExecutor

os.environ["SALES_TESTING"] = "1"
os.environ["SALES_JWT_SECRET"] = "test-only-secret-do-not-use-for-deployment-32"

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

if "fastapi" not in sys.modules:
    import types
    class MockFastAPIModule(types.ModuleType):
        class APIRouter:
            def __init__(self, *args, **kwargs): self.routes = []
            def post(self, path="", **kwargs): return lambda f: f
            def get(self, path="", **kwargs): return lambda f: f
            def put(self, path="", **kwargs): return lambda f: f
            def patch(self, path="", **kwargs): return lambda f: f
            def delete(self, path="", **kwargs): return lambda f: f
        class HTTPException(Exception):
            def __init__(self, status_code, detail=None, headers=None):
                super().__init__(detail)
                self.status_code = status_code
                self.detail = detail
                self.headers = headers
        class status:
            HTTP_400_BAD_REQUEST = 400
            HTTP_401_UNAUTHORIZED = 401
            HTTP_403_FORBIDDEN = 403
            HTTP_404_NOT_FOUND = 404
            HTTP_409_CONFLICT = 409
            HTTP_422_UNPROCESSABLE_ENTITY = 422
            HTTP_429_TOO_MANY_REQUESTS = 429
            HTTP_500_INTERNAL_SERVER_ERROR = 500
            HTTP_503_SERVICE_UNAVAILABLE = 503
        class FastAPI:
            def __init__(self, *args, **kwargs): self.middleware = []
            def add_middleware(self, mw, **kwargs): self.middleware.append((mw, kwargs))
            def include_router(self, *args, **kwargs): pass
            def on_event(self, *args, **kwargs): return lambda f: f
        class BackgroundTasks:
            def add_task(self, *args, **kwargs): pass
        @staticmethod
        def Depends(f): return f
        @staticmethod
        def Header(default=None, alias=None): return default
        @staticmethod
        def Query(default=None, **kwargs): return default

    mock_mod = MockFastAPIModule("fastapi")
    mock_mod.FastAPI = MockFastAPIModule.FastAPI
    mock_mod.BackgroundTasks = MockFastAPIModule.BackgroundTasks
    mock_mod.Query = MockFastAPIModule.Query
    mock_mod.APIRouter = MockFastAPIModule.APIRouter
    mock_mod.HTTPException = MockFastAPIModule.HTTPException
    mock_mod.status = MockFastAPIModule.status
    mock_mod.Depends = MockFastAPIModule.Depends
    mock_mod.Header = MockFastAPIModule.Header

    mock_mw = types.ModuleType("fastapi.middleware")
    mock_cors = types.ModuleType("fastapi.middleware.cors")
    mock_cors.CORSMiddleware = object
    sys.modules["fastapi"] = mock_mod
    sys.modules["fastapi.middleware"] = mock_mw
    sys.modules["fastapi.middleware.cors"] = mock_cors

if "fastapi.security" not in sys.modules:
    import types
    mock_sec = types.ModuleType("fastapi.security")
    mock_sec.HTTPBearer = lambda **kwargs: None
    class MockCredentials:
        def __init__(self, scheme="Bearer", credentials=""):
            self.scheme = scheme
            self.credentials = credentials
    mock_sec.HTTPAuthorizationCredentials = MockCredentials
    sys.modules["fastapi.security"] = mock_sec

if "jwt" not in sys.modules:
    import types
    import base64
    class SmartMockJWT:
        @classmethod
        def encode(cls, payload, secret, algorithm="HS256"):
            return "tok_mock"
        @classmethod
        def decode(cls, token, secret, algorithms=None):
            return {"sub": "USR-OWNER-01", "role": "OWNER"}
    mock_jwt = types.ModuleType("jwt")
    mock_jwt.encode = SmartMockJWT.encode
    mock_jwt.decode = SmartMockJWT.decode
    sys.modules["jwt"] = mock_jwt

if "pydantic" not in sys.modules:
    import types
    class MockBaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items(): setattr(self, k, v)
        def model_dump(self, *args, **kwargs): return self.__dict__
        def dict(self, *args, **kwargs): return self.__dict__
    def MockField(default=None, **kwargs): return default

    mock_pyd = types.ModuleType("pydantic")
    mock_pyd.BaseModel = MockBaseModel
    mock_pyd.Field = MockField
    sys.modules["pydantic"] = mock_pyd

from fastapi import HTTPException
from app.sheets import db, REQUIRED_TABS, ID_PREFIXES
from app.routers import production as prod


class TestRawMaterialIssuanceRecovery(unittest.TestCase):
    def setUp(self):
        db.is_connected = False
        db._fail_once.clear()
        for k in list(REQUIRED_TABS.keys()):
            db.memory_store[k] = []
        for k in list(ID_PREFIXES.keys()):
            db.memory_store.setdefault(k, [])

        db.memory_store.update({
            "Users": [
                {"user_id": "USR-OWNER-01", "username": "owner", "role": "OWNER", "active": "true"},
                {"user_id": "USR-PA-01", "username": "pa_user", "role": "PA", "active": "true"},
            ],
            "Products": [
                {
                    "product_id": "PRD-TEST-PAPAD",
                    "sku": "KS-TP-500",
                    "product_name": "Test Papad",
                    "category": "Papad",
                    "pack_weight_g": "500",
                    "active": "true",
                }
            ],
            "RawMaterials": [
                {"raw_material_id": "RM-MOONG", "material_name": "Moong Flour", "current_stock": 100.0, "unit": "kg"},
                {"raw_material_id": "RM-SALT", "material_name": "Salt", "current_stock": 20.0, "unit": "kg"},
                {"raw_material_id": "RM-HING", "material_name": "Hing", "current_stock": 5.0, "unit": "kg"},
                {"raw_material_id": "RM-OIL", "material_name": "Edible Oil", "current_stock": 50.0, "unit": "L"},
                {"raw_material_id": "RM-PEPPER", "material_name": "Black Pepper", "current_stock": 15.0, "unit": "kg"},
            ],
            "RawMaterialLedger": [],
            "Recipes": [
                {
                    "recipe_id": "RCP-TP-V1",
                    "product_id": "PRD-TEST-PAPAD",
                    "product_name_snapshot": "Test Papad",
                    "version": "1",
                    "approved": "true",
                    "expected_yield_kg": "1.0",
                    "items_json": json.dumps([
                        {"material_name": "Moong Flour", "quantity_per_kg": 0.8, "unit": "kg"},
                        {"material_name": "Salt", "quantity_per_kg": 0.04, "unit": "kg"},
                    ]),
                }
            ],
            "ProductionBatches": [],
            "PackagingBatches": [],
            "ProductionStockLedger": [],
            "ProductionDispatches": [],
            "IncompleteTransactions": [],
            "AuditLog": [],
            "ApprovalRequests": [],
        })

        self.owner_user = {"user_id": "USR-OWNER-01", "role": "OWNER", "username": "owner"}
        self.pa_user = {"user_id": "USR-PA-01", "role": "PA", "username": "pa_user"}

    def _create_test_batch(self, qty_kg=10.0, product_id="PRD-TEST-PAPAD"):
        req = prod.ProductionCreate(
            product_id=product_id,
            production_date="2026-10-25",
            quantity_kg=qty_kg,
            wastage_kg=0.0,
            recipe_id="RCP-TP-V1",
        )
        return asyncio.run(prod.create_batch(req, self.pa_user))

    # -------------------------------------------------------------------------
    # Case 1: Normal material issue succeeds
    # -------------------------------------------------------------------------
    def test_01_normal_material_issue_succeeds(self):
        batch = self._create_test_batch(qty_kg=10.0)
        p_id = batch["production_id"]

        res = asyncio.run(prod.issue_materials(p_id, self.pa_user))
        self.assertEqual(res["status"], "MATERIALS_ISSUED")
        self.assertEqual(res["total_items_issued"], 2)
        self.assertEqual(res["deductions_appended"], 2)

        # Verify ledger rows
        ledger = db.memory_store["RawMaterialLedger"]
        self.assertEqual(len(ledger), 2)
        moong_row = next(r for r in ledger if r["material_name"] == "Moong Flour")
        salt_row = next(r for r in ledger if r["material_name"] == "Salt")

        self.assertAlmostEqual(moong_row["quantity"], 8.0)
        self.assertEqual(moong_row["unit"], "kg")
        self.assertEqual(moong_row["production_id"], p_id)
        self.assertAlmostEqual(salt_row["quantity"], 0.4)
        self.assertEqual(salt_row["unit"], "kg")

        # Verify batch status in ProductionBatches
        batches = db.memory_store["ProductionBatches"]
        saved_batch = next(b for b in batches if b["production_id"] == p_id)
        self.assertEqual(saved_batch["materials_issued"], "true")
        self.assertTrue(saved_batch["material_issue_txn_id"])

    # -------------------------------------------------------------------------
    # Case 2: Repeating a successful issue does not add ledger rows
    # -------------------------------------------------------------------------
    def test_02_repeating_successful_issue_does_not_add_ledger_rows(self):
        batch = self._create_test_batch(qty_kg=10.0)
        p_id = batch["production_id"]

        # First issuance
        res1 = asyncio.run(prod.issue_materials(p_id, self.pa_user))
        self.assertEqual(res1["status"], "MATERIALS_ISSUED")
        ledger_count_1 = len(db.memory_store["RawMaterialLedger"])
        self.assertEqual(ledger_count_1, 2)

        # Second issuance (idempotent call)
        res2 = asyncio.run(prod.issue_materials(p_id, self.pa_user))
        self.assertEqual(res2["status"], "ALREADY_ISSUED")
        ledger_count_2 = len(db.memory_store["RawMaterialLedger"])
        self.assertEqual(ledger_count_2, 2, "No duplicate ledger rows should be appended on repeated request")

    # -------------------------------------------------------------------------
    # Case 3 & 4: Second append fails, retry completes only missing work
    # -------------------------------------------------------------------------
    def test_03_and_04_partial_append_failure_and_safe_recovery(self):
        batch = self._create_test_batch(qty_kg=10.0)
        p_id = batch["production_id"]

        # Configure append_record to fail on the 2nd append to RawMaterialLedger
        original_append = db.append_record
        append_count = 0

        def failing_append(tab_name, record, raise_on_error=False):
            nonlocal append_count
            if tab_name == "RawMaterialLedger":
                append_count += 1
                if append_count == 2:
                    raise RuntimeError("Injected 2nd ledger append failure")
            return original_append(tab_name, record, raise_on_error=raise_on_error)

        db.append_record = failing_append

        # First attempt: should fail on 2nd append
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(prod.issue_materials(p_id, self.pa_user))
        self.assertEqual(ctx.exception.status_code, 503)

        # Verify state after partial failure:
        # Only 1 ledger row (Moong Flour) exists
        ledger = db.memory_store["RawMaterialLedger"]
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0]["material_name"], "Moong Flour")
        self.assertAlmostEqual(ledger[0]["quantity"], 8.0)

        # Batch is NOT marked complete
        saved_batch = next(b for b in db.memory_store["ProductionBatches"] if b["production_id"] == p_id)
        self.assertEqual(saved_batch.get("materials_issued"), "false")

        # Restore normal append_record
        db.append_record = original_append

        # Retry issuance
        res_retry = asyncio.run(prod.issue_materials(p_id, self.pa_user))
        self.assertEqual(res_retry["status"], "MATERIALS_ISSUED")
        self.assertEqual(res_retry["deductions_appended"], 1, "Only the 1 missing item should be appended")

        # Verify ledger has exactly 2 rows (Moong Flour not duplicated, Salt added)
        ledger_after = db.memory_store["RawMaterialLedger"]
        self.assertEqual(len(ledger_after), 2)
        moong_rows = [r for r in ledger_after if r["material_name"] == "Moong Flour"]
        salt_rows = [r for r in ledger_after if r["material_name"] == "Salt"]
        self.assertEqual(len(moong_rows), 1, "Moong Flour must NOT be duplicated")
        self.assertEqual(len(salt_rows), 1, "Salt must be present")
        self.assertAlmostEqual(moong_rows[0]["quantity"], 8.0)
        self.assertAlmostEqual(salt_rows[0]["quantity"], 0.4)

        # Batch is now marked complete
        saved_batch = next(b for b in db.memory_store["ProductionBatches"] if b["production_id"] == p_id)
        self.assertEqual(saved_batch["materials_issued"], "true")

    # -------------------------------------------------------------------------
    # Case 5 & 6: Batch status update fails, retry does not duplicate
    # -------------------------------------------------------------------------
    def test_05_and_06_status_update_fails_and_retry_preserves_ledger(self):
        batch = self._create_test_batch(qty_kg=10.0)
        p_id = batch["production_id"]

        # Injected update failure on ProductionBatches
        db._fail_once["ProductionBatches"] = 1

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(prod.issue_materials(p_id, self.pa_user))
        self.assertEqual(ctx.exception.status_code, 503)

        # All 2 ledger rows were written successfully
        ledger = db.memory_store["RawMaterialLedger"]
        self.assertEqual(len(ledger), 2)

        # But batch was not updated
        saved_batch = next(b for b in db.memory_store["ProductionBatches"] if b["production_id"] == p_id)
        self.assertEqual(saved_batch.get("materials_issued"), "false")

        # Retry now that failure is cleared
        res_retry = asyncio.run(prod.issue_materials(p_id, self.pa_user))
        self.assertIn(res_retry["status"], ["MATERIALS_ISSUED", "ALREADY_ISSUED"])

        # Crucial assertion: Ledger count MUST STILL BE EXACTLY 2!
        ledger_after = db.memory_store["RawMaterialLedger"]
        self.assertEqual(len(ledger_after), 2, "Retry must not duplicate deductions when status update failed")

        saved_batch = next(b for b in db.memory_store["ProductionBatches"] if b["production_id"] == p_id)
        self.assertEqual(saved_batch["materials_issued"], "true")

    # -------------------------------------------------------------------------
    # Case 7: Two simultaneous requests target the same batch
    # -------------------------------------------------------------------------
    def test_07_concurrent_requests_target_same_batch(self):
        batch = self._create_test_batch(qty_kg=10.0)
        p_id = batch["production_id"]

        results = []
        errors = []

        def worker():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                res = loop.run_until_complete(prod.issue_materials(p_id, self.pa_user))
                results.append(res)
            except Exception as e:
                errors.append(e)
            finally:
                loop.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            f1 = executor.submit(worker)
            f2 = executor.submit(worker)
            f1.result()
            f2.result()

        self.assertEqual(len(errors), 0, f"Expected 0 errors under serialization, got: {errors}")
        self.assertEqual(len(results), 2)

        # Ledger must have exactly 2 rows, not 4
        ledger = db.memory_store["RawMaterialLedger"]
        self.assertEqual(len(ledger), 2, "Concurrent requests must not duplicate ledger rows")

        # One request issued, one received ALREADY_ISSUED (or both completed safely)
        statuses = {r["status"] for r in results}
        self.assertIn("MATERIALS_ISSUED", statuses)

    # -------------------------------------------------------------------------
    # Case 8: Recipe changes after interrupted issue requires reconciliation
    # -------------------------------------------------------------------------
    def test_08_recipe_changes_after_interrupted_issue_blocks_silent_drift(self):
        batch = self._create_test_batch(qty_kg=10.0)
        p_id = batch["production_id"]

        # Simulate partial deduction of 8 kg Moong Flour under Recipe RCP-TP-V1
        db.memory_store["RawMaterialLedger"].append({
            "raw_material_txn_id": f"RML-{p_id}-RMMOONG",
            "txn_datetime": "2026-10-25T10:00:00",
            "material_name": "Moong Flour",
            "raw_material_id": "RM-MOONG",
            "movement_type": "PRODUCTION_CONSUMPTION",
            "quantity": 8.0,
            "unit": "kg",
            "rate_per_unit": 120.0,
            "production_id": p_id,
            "issue_txn_id": f"RML-ISSUE-{p_id}",
            "created_by": "USR-PA-01",
            "notes": f"Batch {p_id} material issue under Recipe RCP-TP-V1 (v1)",
        })

        # Now approve a new recipe formulation (v2) with different items
        db.memory_store["Recipes"].append({
            "recipe_id": "RCP-TP-V2",
            "product_id": "PRD-TEST-PAPAD",
            "product_name_snapshot": "Test Papad",
            "version": "2",
            "approved": "true",
            "expected_yield_kg": "1.0",
            "items_json": json.dumps([
                {"material_name": "Moong Flour", "quantity_per_kg": 0.6, "unit": "kg"},
                {"material_name": "Black Pepper", "quantity_per_kg": 0.1, "unit": "kg"},
            ]),
        })

        # Retrying should detect the recipe version conflict and block silent mixing
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(prod.issue_materials(p_id, self.pa_user))

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("Recipe change detected", str(ctx.exception.detail))

        # Ledger remains uncorrupted: only the original row exists
        ledger = db.memory_store["RawMaterialLedger"]
        self.assertEqual(len(ledger), 1)

    # -------------------------------------------------------------------------
    # Case 9: Recipe contains duplicate lines for the same raw material
    # -------------------------------------------------------------------------
    def test_09_recipe_duplicate_lines_are_aggregated(self):
        # Create a recipe with duplicate lines for Moong Flour (0.5 kg + 0.3 kg = 0.8 kg)
        dup_recipe = {
            "recipe_id": "RCP-DUP-LINES",
            "product_id": "PRD-TEST-PAPAD",
            "product_name_snapshot": "Test Papad",
            "version": "1",
            "approved": "true",
            "expected_yield_kg": "1.0",
            "items_json": json.dumps([
                {"material_name": "Moong Flour", "quantity_per_kg": 0.5, "unit": "kg"},
                {"material_name": "Moong Flour", "quantity_per_kg": 0.3, "unit": "kg"},
                {"material_name": "Salt", "quantity_per_kg": 0.04, "unit": "kg"},
            ]),
        }
        db.memory_store["Recipes"] = [dup_recipe]

        batch = self._create_test_batch(qty_kg=10.0)
        p_id = batch["production_id"]

        res = asyncio.run(prod.issue_materials(p_id, self.pa_user))
        self.assertEqual(res["status"], "MATERIALS_ISSUED")

        # Ledger should have 2 rows total (1 for Moong Flour, 1 for Salt), NOT 3
        ledger = db.memory_store["RawMaterialLedger"]
        self.assertEqual(len(ledger), 2, "Duplicate lines in recipe must be aggregated into a single deduction")

        moong_row = next(r for r in ledger if r["material_name"] == "Moong Flour")
        self.assertAlmostEqual(moong_row["quantity"], 8.0)

    # -------------------------------------------------------------------------
    # Case 10: Insufficient stock causes no deductions (all-or-nothing)
    # -------------------------------------------------------------------------
    def test_10_insufficient_stock_causes_zero_deductions(self):
        # Set Salt stock to only 0.1 kg (need 0.4 kg for 10 kg papad)
        salt_master = next(r for r in db.memory_store["RawMaterials"] if r["material_name"] == "Salt")
        salt_master["current_stock"] = 0.1

        batch = self._create_test_batch(qty_kg=10.0)
        p_id = batch["production_id"]

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(prod.issue_materials(p_id, self.pa_user))

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Insufficient stock for Salt", str(ctx.exception.detail))

        # Crucial: ZERO rows must be added to RawMaterialLedger (Moong Flour must NOT be deducted)
        ledger = db.memory_store["RawMaterialLedger"]
        self.assertEqual(len(ledger), 0, "No raw materials should be deducted when any ingredient is insufficient")

    # -------------------------------------------------------------------------
    # Case 11: Referenced raw material is missing from master
    # -------------------------------------------------------------------------
    def test_11_referenced_raw_material_is_missing(self):
        missing_mat_recipe = {
            "recipe_id": "RCP-MISSING-MAT",
            "product_id": "PRD-TEST-PAPAD",
            "product_name_snapshot": "Test Papad",
            "version": "1",
            "approved": "true",
            "expected_yield_kg": "1.0",
            "items_json": json.dumps([
                {"material_name": "Moong Flour", "quantity_per_kg": 0.8, "unit": "kg"},
                {"material_name": "Exotic Saffron", "quantity_per_kg": 0.01, "unit": "kg"},
            ]),
        }
        db.memory_store["Recipes"] = [missing_mat_recipe]

        batch = self._create_test_batch(qty_kg=10.0)
        p_id = batch["production_id"]

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(prod.issue_materials(p_id, self.pa_user))

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("missing from RawMaterials master", str(ctx.exception.detail))

        ledger = db.memory_store["RawMaterialLedger"]
        self.assertEqual(len(ledger), 0)

    # -------------------------------------------------------------------------
    # Case 12: Mixed units are handled correctly (grams to kg, ml to L)
    # -------------------------------------------------------------------------
    def test_12_mixed_units_are_normalized_and_scaled(self):
        mixed_unit_recipe = {
            "recipe_id": "RCP-MIXED-UNITS",
            "product_id": "PRD-TEST-PAPAD",
            "product_name_snapshot": "Test Papad",
            "version": "1",
            "approved": "true",
            "expected_yield_kg": "1.0",
            "items_json": json.dumps([
                {"material_name": "Salt", "quantity_per_kg": 40.0, "unit": "g"},  # 40g per kg = 0.04 kg/kg
                {"material_name": "Edible Oil", "quantity_per_kg": 50.0, "unit": "ml"},  # 50ml per kg = 0.05 L/kg
            ]),
        }
        db.memory_store["Recipes"] = [mixed_unit_recipe]

        batch = self._create_test_batch(qty_kg=10.0)
        p_id = batch["production_id"]

        res = asyncio.run(prod.issue_materials(p_id, self.pa_user))
        self.assertEqual(res["status"], "MATERIALS_ISSUED")

        ledger = db.memory_store["RawMaterialLedger"]
        self.assertEqual(len(ledger), 2)

        salt_row = next(r for r in ledger if r["material_name"] == "Salt")
        oil_row = next(r for r in ledger if r["material_name"] == "Edible Oil")

        # 40g * 10kg = 400g = 0.4 kg
        self.assertAlmostEqual(salt_row["quantity"], 0.4)
        self.assertEqual(salt_row["unit"], "kg")

        # 50ml * 10kg = 500ml = 0.5 L
        self.assertAlmostEqual(oil_row["quantity"], 0.5)
        self.assertEqual(oil_row["unit"], "L")

    # -------------------------------------------------------------------------
    # Case 13: Approval flow integrates safely with issuance recovery
    # -------------------------------------------------------------------------
    def test_13_approval_flow_integrates_safely_with_recovery(self):
        batch = self._create_test_batch(qty_kg=10.0)
        p_id = batch["production_id"]

        # Call approve_batch directly (without prior issue_materials)
        app_res = asyncio.run(prod.approve_batch(
            p_id,
            prod.ApprovalRequest(approved=True, notes="Owner initial approval"),
            self.owner_user,
        ))
        self.assertEqual(app_res["status"], "APPROVED")

        # Both raw materials and bulk stock were posted
        raw_ledger = db.memory_store["RawMaterialLedger"]
        self.assertEqual(len(raw_ledger), 2)
        prod_ledger = db.memory_store["ProductionStockLedger"]
        bulk_entries = [m for m in prod_ledger if m["movement_type"] == "BULK_PRODUCED" and m["reference_id"] == p_id]
        self.assertEqual(len(bulk_entries), 1)
        self.assertAlmostEqual(bulk_entries[0]["quantity_kg"], 10.0)

        # Calling issue_materials after approval must be completely idempotent
        issue_again = asyncio.run(prod.issue_materials(p_id, self.pa_user))
        self.assertEqual(issue_again["status"], "ALREADY_ISSUED")
        self.assertEqual(len(db.memory_store["RawMaterialLedger"]), 2)


if __name__ == "__main__":
    unittest.main()
