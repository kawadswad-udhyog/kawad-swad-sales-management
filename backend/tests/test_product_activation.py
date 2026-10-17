#!/usr/bin/env python3
"""
Automated test suite verifying product catalogue operations,
specifically active/inactive status toggles, PATCH/PUT endpoints,
and robust boolean parsing.
"""

import sys
import types
import os
import unittest
import asyncio

# Setup test harness mocks for FastAPI/Pydantic/JWT if not globally installed
if "fastapi" not in sys.modules:
    class MockFastAPIModule(types.ModuleType):
        class APIRouter:
            def __init__(self, *args, **kwargs):
                self.routes = []
            def post(self, path="", **kwargs): return lambda f: f
            def get(self, path="", **kwargs): return lambda f: f
            def put(self, path="", **kwargs): return lambda f: f
            def patch(self, path="", **kwargs): return lambda f: f
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
    sys.modules["jwt"] = types.ModuleType("jwt")
    sys.modules["jwt"].encode = lambda payload, secret, algorithm="HS256": "mock-jwt"
    sys.modules["jwt"].decode = lambda token, secret, algorithms=["HS256"]: {"sub": "USR-000001", "role": "OWNER"}

    class MockBaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
        def dict(self):
            return self.__dict__

    sys.modules["pydantic"] = types.ModuleType("pydantic")
    sys.modules["pydantic"].BaseModel = MockBaseModel
    sys.modules["pydantic"].Field = lambda *args, **kwargs: kwargs.get("default", args[0] if args else None)

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.sheets import db
from app.models import Product, ProductCreate, ProductUpdate
import app.routers.products as products_router


class TestProductActivation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        db.memory_store["Products"] = [
            {
                "product_id": "PRD-000001",
                "sku": "KS-MMP-200",
                "product_name": "Moong Masala Papad 200g",
                "category": "Papad",
                "variant": "Spicy",
                "pack_weight_g": 200,
                "selling_unit": "PACKET",
                "retail_pack_only": "false",
                "active": "false",
                "notes": "Sample test product",
            }
        ]
        db.memory_store["AuditLog"] = []
        self.owner_user = {
            "user_id": "USR-OWNER-01",
            "full_name": "Test Owner",
            "role": "OWNER",
        }
        self.salesman_user = {
            "user_id": "USR-SALES-01",
            "full_name": "Test Salesman",
            "role": "SALESMAN",
        }

    def tearDown(self):
        self.setUp()

    async def test_01_toggle_product_active_via_patch(self):
        """Manager can activate an inactive product via PATCH /api/products/{id}."""
        # 1. Verify initially inactive
        prods = await products_router.list_products(current_user=self.owner_user)
        self.assertEqual(len(prods), 1)
        self.assertFalse(prods[0].active)

        # 2. Activate product via PATCH with active=True
        req = ProductUpdate(active=True)
        updated = await products_router.update_product("PRD-000001", req, current_user=self.owner_user)

        self.assertTrue(updated.active)
        self.assertEqual(updated.sku, "KS-MMP-200")
        self.assertEqual(updated.product_name, "Moong Masala Papad 200g")

        # 3. Verify in memory store and subsequent list_products
        prods_after = await products_router.list_products(current_user=self.owner_user)
        self.assertTrue(prods_after[0].active)
        self.assertEqual(db.memory_store["Products"][0]["active"], "true")

    async def test_02_toggle_product_inactive_via_patch(self):
        """Manager can deactivate an active product."""
        # Activate first
        await products_router.update_product("PRD-000001", ProductUpdate(active=True), current_user=self.owner_user)
        self.assertEqual(db.memory_store["Products"][0]["active"], "true")

        # Now deactivate
        updated = await products_router.update_product("PRD-000001", ProductUpdate(active=False), current_user=self.owner_user)
        self.assertFalse(updated.active)
        self.assertEqual(db.memory_store["Products"][0]["active"], "false")

    async def test_03_salesman_forbidden_from_updating_product(self):
        """Salesman role cannot update or activate/deactivate products."""
        with self.assertRaises(Exception) as ctx:
            await products_router.update_product("PRD-000001", ProductUpdate(active=True), current_user=self.salesman_user)
        self.assertIn("Only Owner or PA", str(ctx.exception))

    async def test_04_boolean_parsing_handles_various_sheet_formats(self):
        """Boolean parsing handles TRUE, true, 1, FALSE, false, 0 cleanly."""
        db.memory_store["Products"] = [
            {"product_id": "P1", "sku": "S1", "product_name": "P1", "active": "TRUE"},
            {"product_id": "P2", "sku": "S2", "product_name": "P2", "active": "false"},
            {"product_id": "P3", "sku": "S3", "product_name": "P3", "active": 1},
            {"product_id": "P4", "sku": "S4", "product_name": "P4", "active": 0},
            {"product_id": "P5", "sku": "S5", "product_name": "P5", "Active": "true"},
        ]
        prods = await products_router.list_products(current_user=self.owner_user)
        self.assertEqual(len(prods), 5)
        self.assertTrue(prods[0].active)
        self.assertFalse(prods[1].active)
        self.assertTrue(prods[2].active)
        self.assertFalse(prods[3].active)
        self.assertTrue(prods[4].active)


if __name__ == "__main__":
    unittest.main()
