#!/usr/bin/env python3
"""
Automated test suite verifying product catalogue operations,
specifically active/inactive status toggles, PATCH/PUT endpoints,
and robust boolean parsing.
"""

import sys
import os
import unittest

os.environ.setdefault("SALES_TESTING", "1")
os.environ.setdefault("SALES_JWT_SECRET", "test-only-secret-do-not-use-for-deployment-32")

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import tests
from app.sheets import db
from app.models import Product, ProductCreate, ProductUpdate
import app.routers.products as products_router
from tests.v2_test_harness import LocalAppsScriptSimulator, make_test_request


class TestProductActivation(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._sim = LocalAppsScriptSimulator().start()
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
        self._sim.stop()
        db.memory_store["Products"] = []
        db.memory_store["AuditLog"] = []

    async def test_01_toggle_product_active_via_patch(self):
        """Manager can activate an inactive product via PATCH /api/products/{id}."""
        # 1. Verify initially inactive
        prods = await products_router.list_products(current_user=self.owner_user)
        self.assertEqual(len(prods), 1)
        self.assertFalse(prods[0].active)

        # 2. Activate product via PATCH with active=True
        req = ProductUpdate(active=True)
        updated = await products_router.update_product("PRD-000001", req, request=make_test_request(), current_user=self.owner_user)

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
        await products_router.update_product("PRD-000001", ProductUpdate(active=True), request=make_test_request(), current_user=self.owner_user)
        self.assertEqual(db.memory_store["Products"][0]["active"], "true")

        # Now deactivate
        updated = await products_router.update_product("PRD-000001", ProductUpdate(active=False), request=make_test_request(), current_user=self.owner_user)
        self.assertFalse(updated.active)
        self.assertEqual(db.memory_store["Products"][0]["active"], "false")

    async def test_03_salesman_forbidden_from_updating_product(self):
        """Salesman role cannot update or activate/deactivate products."""
        with self.assertRaises(Exception) as ctx:
            await products_router.update_product("PRD-000001", ProductUpdate(active=True), request=make_test_request(), current_user=self.salesman_user)
        self.assertEqual(getattr(ctx.exception, "status_code", None), 403)
        self.assertIn("Permission denied", str(ctx.exception))

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
