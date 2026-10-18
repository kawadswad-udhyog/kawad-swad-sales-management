"""Tests for Kawad Swad Papad Formula Master Version 2.0 & Production Integration."""
import os
os.environ.setdefault("SALES_TESTING", "1")
os.environ.setdefault("SALES_JWT_SECRET", "test-only-secret-do-not-use-for-deployment-32")

import sys
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import asyncio
import unittest
import types

if "fastapi" not in sys.modules:
    class MockFastAPIModule(types.ModuleType):
        class APIRouter:
            def __init__(self, *args, **kwargs):
                self.routes = []
            def post(self, path="", **kwargs):
                return lambda f: f
            def get(self, path="", **kwargs):
                return lambda f: f
            def put(self, path="", **kwargs):
                return lambda f: f
            def patch(self, path="", **kwargs):
                return lambda f: f
            def delete(self, path="", **kwargs):
                return lambda f: f
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
        @staticmethod
        def Depends(f): return f
        @staticmethod
        def Header(default=None, alias=None): return default

    sys.modules["fastapi"] = MockFastAPIModule("fastapi")
    sys.modules["fastapi.security"] = types.ModuleType("security")
    sys.modules["fastapi.security"].HTTPBearer = lambda **kwargs: None
    sys.modules["fastapi.security"].HTTPAuthorizationCredentials = None

if "pydantic" not in sys.modules:
    class MockBaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
        def dict(self):
            return self.__dict__
        def model_dump(self):
            return self.__dict__

    sys.modules["pydantic"] = types.ModuleType("pydantic")
    sys.modules["pydantic"].BaseModel = MockBaseModel
    sys.modules["pydantic"].Field = lambda *args, **kwargs: kwargs.get("default", args[0] if args else None)

if "jwt" not in sys.modules:
    sys.modules["jwt"] = types.ModuleType("jwt")
    sys.modules["jwt"].encode = lambda payload, secret, algorithm="HS256": "mock-jwt"
    sys.modules["jwt"].decode = lambda token, secret, algorithms=["HS256"]: {"sub": "USR-000001", "role": "SALESMAN"}

from fastapi import HTTPException
from app.sheets import db
from app.routers import production as prod
from app.recipes_master import (
    MASTER_RECIPES_DEFINITION,
    RAW_MATERIALS_SEED,
    calculate_recipe_cost,
)

class TestRecipeMasterV2(unittest.TestCase):
    def setUp(self):
        db.is_connected = False
        for key in list(db.memory_store):
            db.memory_store[key] = []
        db.memory_store.update({
            "Products": [
                {"product_id": "PRD-MOONG-MASTER", "sku": "KS-MM-200", "product_name": "Moong Master Papad", "active": "true", "pack_weight_g": 200},
                {"product_id": "PRD-CHANA-CHOTU", "sku": "KS-CC-200", "product_name": "Chana Chotu Papad", "active": "true", "pack_weight_g": 200},
                {"product_id": "PRD-URAD-GURU", "sku": "KS-UG-200", "product_name": "Urad Guru Papad", "active": "true", "pack_weight_g": 200},
            ],
            "RawMaterials": [],
            "Workers": [],
            "Recipes": [],
            "ProductionBatches": [],
            "PackagingBatches": [],
            "ProductionStockLedger": [],
            "ProductionDispatches": [],
            "RawMaterialLedger": [],
            "AuditLog": [],
        })
        self.owner = {"user_id": "USR-OWNER", "role": "OWNER"}
        self.pa = {"user_id": "USR-PA", "role": "PA"}
        self.salesman = {"user_id": "USR-SALES", "role": "SALESMAN"}

    def test_moong_master_formula_exact_cost_and_yield(self):
        """Moong Master: exactly 1000g Moong flour, no sabudana/urad, ₹153.63/batch, ₹128.03/kg at 1.2kg yield."""
        moong_master = next(m for m in MASTER_RECIPES_DEFINITION if m["recipe_id"] == "RCP-MOONG-MASTER-V2")
        self.assertEqual(moong_master["product_name_snapshot"], "Moong Master Papad")
        self.assertEqual(moong_master["expected_yield_kg"], 1.2)
        self.assertTrue(moong_master["approved"])

        # Check ingredients: no sabudana, no urad
        mat_names = [i["material_name"] for i in moong_master["items"]]
        self.assertIn("Moong Dal Flour", mat_names)
        self.assertNotIn("Sabudana Flour", mat_names)
        self.assertNotIn("Urad Dal Flour", mat_names)

        # Flour must be exactly 1000g
        flour_item = next(i for i in moong_master["items"] if i["material_name"] == "Moong Dal Flour")
        self.assertEqual(flour_item["quantity"], 1000)

        # Calculate cost
        cost_calc = calculate_recipe_cost(moong_master["items"], moong_master["expected_yield_kg"])
        self.assertEqual(cost_calc["cost_status"], "COMPLETE")
        self.assertEqual(cost_calc["cost_per_batch"], 153.63)
        self.assertEqual(cost_calc["cost_per_kg"], 128.03)

    def test_chana_flour_ratio_and_proposed_smos(self):
        """Chana variants must use 750g Chana : 250g Urad, SMOS proposed, unconfirmed status."""
        chana_chotu = next(m for m in MASTER_RECIPES_DEFINITION if m["recipe_id"] == "RCP-CHANA-CHOTU-V2")
        self.assertFalse(chana_chotu["approved"])
        self.assertEqual(chana_chotu["status"], "DRAFT")

        chana_flour = next(i for i in chana_chotu["items"] if i["material_name"] == "Chana Dal Flour")
        urad_flour = next(i for i in chana_chotu["items"] if i["material_name"] == "Urad Dal Flour")
        self.assertEqual(chana_flour["quantity"], 750)
        self.assertEqual(urad_flour["quantity"], 250)

        smos_item = next(i for i in chana_chotu["items"] if i["material_name"] == "SMOS")
        self.assertEqual(smos_item["quantity"], 1)

    def test_urad_flour_ratio_and_proposed_smos(self):
        """Urad variants must use 850g Urad : 150g Sabudana, SMOS proposed, unconfirmed status."""
        urad_guru = next(m for m in MASTER_RECIPES_DEFINITION if m["recipe_id"] == "RCP-URAD-GURU-V2")
        self.assertFalse(urad_guru["approved"])
        self.assertEqual(urad_guru["status"], "DRAFT")

        urad_flour = next(i for i in urad_guru["items"] if i["material_name"] == "Urad Dal Flour")
        sabudana_flour = next(i for i in urad_guru["items"] if i["material_name"] == "Sabudana Flour")
        self.assertEqual(urad_flour["quantity"], 850)
        self.assertEqual(sabudana_flour["quantity"], 150)

    def test_pending_rates_do_not_produce_false_total(self):
        """Ingredients with pending rates (e.g. Tomato Powder, Sweetener) must return PENDING_RATES."""
        chana_tomato = next(m for m in MASTER_RECIPES_DEFINITION if m["recipe_id"] == "RCP-CHANA-TOMATO-V2")
        cost_calc = calculate_recipe_cost(chana_tomato["items"], chana_tomato["expected_yield_kg"])
        self.assertEqual(cost_calc["cost_status"], "PENDING_RATES")
        self.assertIsNone(cost_calc["cost_per_batch"])
        self.assertIsNone(cost_calc["cost_per_kg"])
        self.assertIn("Tomato Powder", cost_calc["pending_ingredients"])

    def test_master_recipes_api_endpoints_and_bootstrap(self):
        """Test GET /recipes/master and POST /recipes/master/bootstrap."""
        # Get master recipes
        recipes = asyncio.run(prod.get_master_recipes(self.owner))
        self.assertEqual(len(recipes), 15)

        # Bootstrap into Sheets store
        res = asyncio.run(prod.bootstrap_master_recipes(self.owner))
        self.assertEqual(res["status"], "success")
        self.assertGreater(res["added_materials"], 0)
        self.assertGreater(res["added_recipes"], 0)

        # Check stored RawMaterials
        raw_rows = db.get_records("RawMaterials")
        self.assertTrue(any(r["material_name"] == "Moong Dal Flour" for r in raw_rows))

        # Check stored Recipes
        recipe_rows = db.get_records("Recipes")
        self.assertTrue(any(r["recipe_id"] == "RCP-MOONG-MASTER-V2" for r in recipe_rows))

    def test_owner_confirmation_mechanism(self):
        """Only owner can confirm or adjust proposed recipes."""
        # Salesman cannot confirm
        with self.assertRaises(HTTPException):
            asyncio.run(prod.confirm_master_recipe("RCP-CHANA-CHOTU-V2", prod.RecipeConfirmRequest(approved=True), self.salesman))

        # PA cannot confirm (only OWNER)
        with self.assertRaises(HTTPException):
            asyncio.run(prod.confirm_master_recipe("RCP-CHANA-CHOTU-V2", prod.RecipeConfirmRequest(approved=True), self.pa))

        # Owner can confirm
        res = asyncio.run(prod.confirm_master_recipe(
            "RCP-CHANA-CHOTU-V2",
            prod.RecipeConfirmRequest(approved=True, expected_yield_kg=1.22, change_notes="Confirmed after trial batch"),
            self.owner,
        ))
        self.assertTrue(res["approved"])
        self.assertEqual(res["expected_yield_kg"], 1.22)

    def test_production_batch_yield_benchmark_comparison(self):
        """Production batch records flour base used, actual yield, benchmark yield, and variance."""
        batch = asyncio.run(prod.create_batch(
            prod.ProductionCreate(
                product_id="PRD-MOONG-MASTER",
                production_date="2026-10-17",
                quantity_kg=12.2,
                wastage_kg=0.2,
                flour_base_used_kg=10.0, # 10 kg flour base
                notes="Shift 1 batch",
            ),
            self.owner,
        ))
        self.assertEqual(batch["net_quantity_kg"], 12.0)
        self.assertEqual(batch["benchmark_yield_kg"], 12.0) # 10.0 * 1.2 benchmark yield
        self.assertEqual(batch["yield_variance_kg"], 0.0)
        self.assertEqual(batch["actual_yield_ratio"], 1.2)

if __name__ == "__main__":
    unittest.main()
