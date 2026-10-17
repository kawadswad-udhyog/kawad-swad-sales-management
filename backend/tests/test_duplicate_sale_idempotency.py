#!/usr/bin/env python3
"""
Automated test suite verifying duplicate-sale protection and request idempotency
in Kawad Swad Sales Management.
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
            def post(self, path="", **kwargs):
                return lambda f: f
            def get(self, path="", **kwargs):
                return lambda f: f
            def put(self, path="", **kwargs):
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
    sys.modules["jwt"].decode = lambda token, secret, algorithms=["HS256"]: {"sub": "USR-000001", "role": "SALESMAN"}

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
from app.models import SaleCreate, SaleItemCreate
import app.routers.sales as sales_router


class TestDuplicateSaleIdempotency(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Reset in-memory database store
        db.memory_store["Customers"] = [
            {
                "customer_id": "CUS-000001",
                "customer_type": "RETAILER",
                "shop_name": "Shree Ram Kirana Store",
                "mobile": "9876543210",
                "city": "Bhilwara",
                "active": True,
            }
        ]
        db.memory_store["Sales"] = []
        db.memory_store["SaleItems"] = []
        db.memory_store["Payments"] = []
        db.memory_store["CashLedger"] = []
        db.memory_store["SalesmanStockLedger"] = []
        db.memory_store["AuditLog"] = []
        db.memory_store["Products"] = [
            {
                "product_id": "PRD-000001",
                "sku": "PAPAD-MOONG-500G",
                "product_name": "Moong Special Papad",
                "pack_weight_g": 500,
                "selling_unit": "PACKET",
            }
        ]
        self.mock_user = {
            "user_id": "USR-000001",
            "full_name": "Ramesh Salesman",
            "role": "SALESMAN",
        }

    def tearDown(self):
        self.setUp()

    async def test_01_idempotent_retry_returns_original_sale_without_duplication(self):
        """Re-submitting the exact same idempotency_key returns original sale and prevents duplicate financial/stock writes."""
        idemp_key = "IDEMP-TEST-KEY-001"
        req = SaleCreate(
            idempotency_key=idemp_key,
            sales_type="Retailer Sale",
            customer_id="CUS-000001",
            customer_name_snapshot="Shree Ram Kirana Store",
            payment_method="CASH",
            items=[
                SaleItemCreate(
                    product_id="PRD-000001",
                    quantity=5,
                    actual_unit_price=120.0,
                    line_total=600.0,
                )
            ],
            bill_total=600.0,
        )

        # 1. First execution
        first_sale = await sales_router.create_sale(req, current_user=self.mock_user)
        self.assertIsNotNone(first_sale.sale_id)
        self.assertEqual(first_sale.idempotency_key, idemp_key)
        self.assertEqual(len(db.memory_store["Sales"]), 1)
        self.assertEqual(len(db.memory_store["SaleItems"]), 1)
        self.assertEqual(len(db.memory_store["Payments"]), 1)
        self.assertEqual(len(db.memory_store["CashLedger"]), 1)
        self.assertEqual(len(db.memory_store["SalesmanStockLedger"]), 1)

        # 2. Replayed execution with SAME idempotency key (simulating retry after timeout)
        second_sale = await sales_router.create_sale(req, current_user=self.mock_user)

        # Must return the identical sale ID and bill number
        self.assertEqual(second_sale.sale_id, first_sale.sale_id)
        self.assertEqual(second_sale.bill_number, first_sale.bill_number)
        self.assertEqual(second_sale.bill_total, first_sale.bill_total)

        # No duplicate records created in any store!
        self.assertEqual(len(db.memory_store["Sales"]), 1, "Sales table must NOT have duplicate records")
        self.assertEqual(len(db.memory_store["SaleItems"]), 1, "SaleItems must NOT have duplicate line items")
        self.assertEqual(len(db.memory_store["Payments"]), 1, "Payments must NOT be charged twice")
        self.assertEqual(len(db.memory_store["CashLedger"]), 1, "CashLedger must NOT have duplicate entries")
        self.assertEqual(len(db.memory_store["SalesmanStockLedger"]), 1, "Stock ledger must NOT deduct stock twice")

    async def test_02_legitimate_sales_with_different_keys_are_both_accepted(self):
        """Two legitimate sales with identical customer, salesman, product and total are both accepted with different keys."""
        req1 = SaleCreate(
            idempotency_key="KEY-A-111",
            sales_type="Retailer Sale",
            customer_id="CUS-000001",
            customer_name_snapshot="Shree Ram Kirana Store",
            payment_method="CASH",
            items=[
                SaleItemCreate(
                    product_id="PRD-000001",
                    quantity=2,
                    actual_unit_price=100.0,
                    line_total=200.0,
                )
            ],
            bill_total=200.0,
        )
        sale1 = await sales_router.create_sale(req1, current_user=self.mock_user)

        # Immediate second sale for same customer and same total, but different legitimate key
        req2 = SaleCreate(
            idempotency_key="KEY-B-222",
            sales_type="Retailer Sale",
            customer_id="CUS-000001",
            customer_name_snapshot="Shree Ram Kirana Store",
            payment_method="CASH",
            items=[
                SaleItemCreate(
                    product_id="PRD-000001",
                    quantity=2,
                    actual_unit_price=100.0,
                    line_total=200.0,
                )
            ],
            bill_total=200.0,
        )
        sale2 = await sales_router.create_sale(req2, current_user=self.mock_user)

        self.assertNotEqual(sale1.sale_id, sale2.sale_id)
        self.assertNotEqual(sale1.bill_number, sale2.bill_number)
        self.assertEqual(len(db.memory_store["Sales"]), 2, "Both legitimate sales must be recorded")
        self.assertEqual(len(db.memory_store["Payments"]), 2, "Both payments must be recorded")
        self.assertEqual(len(db.memory_store["SalesmanStockLedger"]), 2, "Both stock deductions must be recorded")

    async def test_03_malformed_and_oversized_keys_rejected(self):
        """idempotency_key exceeding 120 chars or containing control characters must be rejected."""
        long_key = "K" * 121
        req_long = SaleCreate(
            idempotency_key=long_key,
            customer_id="CUS-000001",
            items=[SaleItemCreate(product_id="PRD-000001", actual_unit_price=100.0, quantity=1)],
        )
        with self.assertRaises(Exception) as ctx:
            await sales_router.create_sale(req_long, current_user=self.mock_user)
        self.assertIn("120 characters", str(ctx.exception))

        req_ctrl = SaleCreate(
            idempotency_key="INVALID\nKEY",
            customer_id="CUS-000001",
            items=[SaleItemCreate(product_id="PRD-000001", actual_unit_price=100.0, quantity=1)],
        )
        with self.assertRaises(Exception) as ctx:
            await sales_router.create_sale(req_ctrl, current_user=self.mock_user)
        self.assertIn("invalid control characters", str(ctx.exception))

    async def test_04_concurrent_requests_with_same_key_serialize_safely(self):
        """Concurrent calls with the same key serialize under lock without duplicate creation."""
        idemp_key = "CONCURRENT-KEY-999"
        req = SaleCreate(
            idempotency_key=idemp_key,
            sales_type="Retailer Sale",
            customer_id="CUS-000001",
            payment_method="CASH",
            items=[
                SaleItemCreate(
                    product_id="PRD-000001",
                    quantity=3,
                    actual_unit_price=150.0,
                    line_total=450.0,
                )
            ],
            bill_total=450.0,
        )

        results = await asyncio.gather(
            sales_router.create_sale(req, current_user=self.mock_user),
            sales_router.create_sale(req, current_user=self.mock_user),
            sales_router.create_sale(req, current_user=self.mock_user),
        )

        # All results should have the exact same sale_id
        sale_ids = {s.sale_id for s in results}
        self.assertEqual(len(sale_ids), 1, "Concurrent idempotent calls must resolve to a single sale")

        # Database tables must only contain 1 entry
        self.assertEqual(len(db.memory_store["Sales"]), 1)
        self.assertEqual(len(db.memory_store["SaleItems"]), 1)
        self.assertEqual(len(db.memory_store["Payments"]), 1)
        self.assertEqual(len(db.memory_store["SalesmanStockLedger"]), 1)


if __name__ == "__main__":
    unittest.main()
