"""Tests for Finished Goods Stock Register, Packaging Validation, and Physical Reconciliation."""
import os
os.environ.setdefault("SALES_TESTING", "1")
os.environ.setdefault("SALES_JWT_SECRET", "test-only-secret-do-not-use-for-deployment-32")

import sys
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import types

if "fastapi" not in sys.modules:
    mock_fastapi = types.ModuleType("fastapi")
    class MockAPIRouter:
        def __init__(self, *args, **kwargs): pass
        def post(self, *args, **kwargs): return lambda f: f
        def get(self, *args, **kwargs): return lambda f: f
        def put(self, *args, **kwargs): return lambda f: f
        def patch(self, *args, **kwargs): return lambda f: f
        def delete(self, *args, **kwargs): return lambda f: f
    class MockHTTPException(Exception):
        def __init__(self, status_code, detail=None, headers=None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail
    mock_fastapi.APIRouter = MockAPIRouter
    mock_fastapi.HTTPException = MockHTTPException
    mock_fastapi.Depends = lambda f: f
    mock_fastapi.status = types.ModuleType("status")
    sys.modules["fastapi"] = mock_fastapi
    mock_sec = types.ModuleType("fastapi.security")
    mock_sec.HTTPBearer = lambda **kwargs: None
    mock_sec.HTTPAuthorizationCredentials = None
    sys.modules["fastapi.security"] = mock_sec

if "pydantic" not in sys.modules:
    class MockBaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
        def dict(self):
            return self.__dict__
    mock_pydantic = types.ModuleType("pydantic")
    mock_pydantic.BaseModel = MockBaseModel
    mock_pydantic.Field = lambda *args, **kwargs: None
    sys.modules["pydantic"] = mock_pydantic

if "jwt" not in sys.modules:
    mock_jwt = types.ModuleType("jwt")
    mock_jwt.encode = lambda *args, **kwargs: "mock-jwt"
    mock_jwt.decode = lambda *args, **kwargs: {"sub": "USR-OWNER-01", "role": "OWNER"}
    sys.modules["jwt"] = mock_jwt

import asyncio
import unittest
from fastapi import HTTPException
from app.sheets import db
from app.calculations import calculate_consolidated_finished_goods_register
from app.routers import production as prod
from app.routers import stock as stock_router


class TestFinishedGoodsInventory(unittest.TestCase):
    def setUp(self):
        db.is_connected = False
        for key in list(db.memory_store):
            db.memory_store[key] = []
        db.memory_store.update({
            "Products": [
                {
                    "product_id": "PRD-MP-200",
                    "sku": "KS-MP-200",
                    "product_name": "Moong Master Papad",
                    "category": "Papad",
                    "variant": "Master",
                    "pack_weight_g": 200,
                    "selling_unit": "PACKET",
                    "active": "true",
                },
                {
                    "product_id": "PRD-MP-500",
                    "sku": "KS-MP-500",
                    "product_name": "Moong Master Papad",
                    "category": "Papad",
                    "variant": "Master",
                    "pack_weight_g": 500,
                    "selling_unit": "PACKET",
                    "active": "true",
                },
                {
                    "product_id": "PRD-CP-500",
                    "sku": "KS-CP-500",
                    "product_name": "Chana Masala Papad",
                    "category": "Papad",
                    "variant": "Masala",
                    "pack_weight_g": 500,
                    "selling_unit": "PACKET",
                    "active": "true",
                },
            ],
            "Users": [
                {"user_id": "USR-OWNER-01", "full_name": "Owner Admin", "role": "OWNER", "active": "true"},
                {"user_id": "USR-SALES-01", "full_name": "Ramesh Kumar", "role": "SALESMAN", "active": "true"},
            ],
            "ProductionStockLedger": [],
            "PackagingBatches": [],
            "ProductionDispatches": [],
            "SalesmanStockLedger": [],
            "SaleItems": [],
            "AuditLog": [],
        })

    def test_consolidated_register_includes_zero_stock_active_skus(self):
        """Active SKUs with no movements must appear with 0 stock rather than being omitted."""
        result = calculate_consolidated_finished_goods_register(
            products_master=db.memory_store["Products"],
            production_stock_ledger=db.memory_store["ProductionStockLedger"],
            salesman_stock_ledger=db.memory_store["SalesmanStockLedger"],
            users_master=db.memory_store["Users"],
            sale_items_records=db.memory_store["SaleItems"],
        )

        skus = [r["sku"] for r in result["register"]]
        self.assertIn("KS-MP-200", skus)
        self.assertIn("KS-MP-500", skus)
        self.assertIn("KS-CP-500", skus)
        self.assertEqual(len(result["register"]), 3)

        # All start with 0 stock
        for r in result["register"]:
            self.assertEqual(r["factory_stock"], 0)
            self.assertEqual(r["warehouse_stock"], 0)
            self.assertEqual(r["salesmen_stock"], 0)
            self.assertEqual(r["total_internal_on_hand"], 0)
            self.assertEqual(r["status"], "ZERO_STOCK")

    def test_packaging_validates_skus_before_saving_batch(self):
        """Packaging must check that active SKU products exist BEFORE appending to PackagingBatches."""
        # Setup bulk stock
        db.memory_store["ProductionStockLedger"].append({
            "movement_id": "MVT-BULK-01",
            "movement_type": "BULK_PRODUCED",
            "quantity_kg": 50.0,
            "quantity_packets": 0,
            "channel": "FACTORY_BULK",
            "product_id": "PRD-CP-500",
            "bulk_product_key": "chana masala papad",
            "product_name_snapshot": "Chana Masala Papad",
        })

        # Request packaging with 1000g packets (for which no 1000g SKU exists)
        req = prod.PackagingCreate(
            product_id="PRD-CP-500",
            packaging_date="2026-10-22",
            bulk_kg_used=10.0,
            packets_200g=0,
            packets_500g=10,
            packets_1000g=5,  # Missing 1000g SKU
            packing_loss_kg=0.0,
            notes="Test missing SKU",
        )

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(prod.create_packaging(req, {"user_id": "USR-OWNER-01", "role": "OWNER"}))

        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("No active 1000 g SKU product found", ctx.exception.detail)
        # CRITICAL: No PackagingBatches row should have been created!
        self.assertEqual(len(db.memory_store["PackagingBatches"]), 0)

    def test_factory_dispatch_to_warehouse_reconciles_both_ledgers(self):
        """Dispatching to WAREHOUSE must reduce factory stock and increase company warehouse stock."""
        # 1. Add finished stock to factory (100 packets of KS-MP-500)
        db.memory_store["ProductionStockLedger"].append({
            "movement_id": "MVT-PKG-01",
            "movement_type": "PACKETS_PACKAGED",
            "quantity_kg": 0,
            "quantity_packets": 100,
            "channel": "FACTORY_FINISHED",
            "product_id": "PRD-MP-500",
            "bulk_product_key": "moong master papad",
            "product_name_snapshot": "Moong Master Papad",
            "sku_snapshot": "KS-MP-500",
            "pack_weight_g": 500,
        })

        # Register before dispatch: Factory = 100, Warehouse = 0, Total = 100
        reg1 = calculate_consolidated_finished_goods_register(
            products_master=db.memory_store["Products"],
            production_stock_ledger=db.memory_store["ProductionStockLedger"],
            salesman_stock_ledger=db.memory_store["SalesmanStockLedger"],
        )
        mp500_1 = next(r for r in reg1["register"] if r["sku"] == "KS-MP-500")
        self.assertEqual(mp500_1["factory_stock"], 100)
        self.assertEqual(mp500_1["warehouse_stock"], 0)
        self.assertEqual(mp500_1["total_internal_on_hand"], 100)

        # 2. Dispatch 40 packets to Central Warehouse
        disp_req = prod.DispatchCreate(
            product_id="PRD-MP-500",
            channel="WAREHOUSE",
            destination="Central Warehouse",
            quantity_packets=40,
            reference="DISP-WH-001",
            notes="Factory to Warehouse transfer",
        )
        res = asyncio.run(prod.dispatch(disp_req, {"user_id": "USR-OWNER-01", "role": "OWNER"}))
        self.assertEqual(res["status"], "DISPATCHED_NOT_SALE")

        # 3. Register after dispatch: Factory = 60, Warehouse = 40, Total = 100 (No packets lost or duplicated!)
        reg2 = calculate_consolidated_finished_goods_register(
            products_master=db.memory_store["Products"],
            production_stock_ledger=db.memory_store["ProductionStockLedger"],
            salesman_stock_ledger=db.memory_store["SalesmanStockLedger"],
        )
        mp500_2 = next(r for r in reg2["register"] if r["sku"] == "KS-MP-500")
        self.assertEqual(mp500_2["factory_stock"], 60)
        self.assertEqual(mp500_2["warehouse_stock"], 40)
        self.assertEqual(mp500_2["total_internal_on_hand"], 100)

    def test_physical_stock_reconciliation(self):
        """Owner can reconcile physical stock differences with audit record."""
        # Reconcile factory stock of KS-MP-200 to 50 packets (was 0)
        rec_req = stock_router.PhysicalStockReconcile(
            product_id="PRD-MP-200",
            location="FACTORY",
            physical_count=50,
            reason="Opening physical inventory count verified",
            notes="Counted by Owner",
        )
        res = asyncio.run(stock_router.reconcile_physical_stock(rec_req, {"user_id": "USR-OWNER-01", "role": "OWNER"}))
        self.assertTrue(res["ok"])
        self.assertEqual(res["adjustment"], 50)
        self.assertEqual(res["new_stock"], 50)

        # Reconcile warehouse stock of KS-MP-500 to 30 packets (was 0)
        wh_rec = stock_router.PhysicalStockReconcile(
            product_id="PRD-MP-500",
            location="WAREHOUSE",
            physical_count=30,
            reason="Opening warehouse count",
        )
        res_wh = asyncio.run(stock_router.reconcile_physical_stock(wh_rec, {"user_id": "USR-OWNER-01", "role": "OWNER"}))
        self.assertTrue(res_wh["ok"])
        self.assertEqual(res_wh["adjustment"], 30)

        # Verify register reflects opening stock
        reg = calculate_consolidated_finished_goods_register(
            products_master=db.memory_store["Products"],
            production_stock_ledger=db.memory_store["ProductionStockLedger"],
            salesman_stock_ledger=db.memory_store["SalesmanStockLedger"],
        )
        mp200 = next(r for r in reg["register"] if r["sku"] == "KS-MP-200")
        mp500 = next(r for r in reg["register"] if r["sku"] == "KS-MP-500")
        self.assertEqual(mp200["factory_stock"], 50)
        self.assertEqual(mp500["warehouse_stock"], 30)


if __name__ == "__main__":
    unittest.main()
