#!/usr/bin/env python3
"""
Automated test suite verifying duplicate-sale protection and request idempotency
in Kawad Swad Sales Management.
"""

import sys
import os
import unittest
import asyncio

os.environ.setdefault("SALES_TESTING", "1")
os.environ.setdefault("SALES_JWT_SECRET", "test-only-secret-do-not-use-for-deployment-32")

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import tests
from app.sheets import db
from app.models import SaleCreate, SaleItemCreate
import app.routers.sales as sales_router
from tests.v2_test_harness import LocalAppsScriptSimulator, make_test_request


class TestDuplicateSaleIdempotency(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._sim = LocalAppsScriptSimulator().start()
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
        db.memory_store["SalesmanStockLedger"] = [{
            "stock_txn_id": "STK-SEED",
            "salesman_user_id": "USR-000001",
            "product_id": "PRD-000001",
            "txn_type": "SALESMAN_POSITIVE_ADJUSTMENT",
            "quantity": 1000,
        }]
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
        db.memory_store["JournalHeaders"] = []
        db.memory_store["JournalLines"] = []
        self.mock_user = {
            "user_id": "USR-000001",
            "full_name": "Ramesh Salesman",
            "role": "SALESMAN",
        }

    def tearDown(self):
        self._sim.stop()

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
        first_sale = await sales_router.create_sale(req, request=make_test_request(nonce=idemp_key), current_user=self.mock_user)
        self.assertIsNotNone(first_sale.sale_id)
        self.assertEqual(first_sale.idempotency_key, idemp_key)
        self.assertEqual(len(db.memory_store["Sales"]), 1)
        self.assertEqual(len(db.memory_store["SaleItems"]), 1)
        self.assertEqual(len(db.memory_store["Payments"]), 1)
        self.assertEqual(len(db.memory_store["CashLedger"]), 1)
        self.assertEqual(len([r for r in db.memory_store["SalesmanStockLedger"] if r.get("txn_type") == "SOLD_DELIVERY"]), 1)

        # 2. Replayed execution with SAME idempotency key (simulating retry after timeout)
        second_sale = await sales_router.create_sale(req, request=make_test_request(nonce=idemp_key), current_user=self.mock_user)

        # Must return the identical sale ID and bill number
        self.assertEqual(second_sale.sale_id, first_sale.sale_id)
        self.assertEqual(second_sale.bill_number, first_sale.bill_number)
        self.assertEqual(second_sale.bill_total, first_sale.bill_total)

        # No duplicate records created in any store!
        self.assertEqual(len(db.memory_store["Sales"]), 1, "Sales table must NOT have duplicate records")
        self.assertEqual(len(db.memory_store["SaleItems"]), 1, "SaleItems must NOT have duplicate line items")
        self.assertEqual(len(db.memory_store["Payments"]), 1, "Payments must NOT be charged twice")
        self.assertEqual(len(db.memory_store["CashLedger"]), 1, "CashLedger must NOT have duplicate entries")
        sold = [r for r in db.memory_store["SalesmanStockLedger"] if r.get("txn_type") == "SOLD_DELIVERY"]
        self.assertEqual(len(sold), 1, "Stock ledger must NOT deduct stock twice")

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
        sale1 = await sales_router.create_sale(req1, request=make_test_request(nonce=req1.idempotency_key), current_user=self.mock_user)

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
        sale2 = await sales_router.create_sale(req2, request=make_test_request(nonce=req2.idempotency_key), current_user=self.mock_user)

        self.assertNotEqual(sale1.sale_id, sale2.sale_id)
        self.assertNotEqual(sale1.bill_number, sale2.bill_number)
        self.assertEqual(len(db.memory_store["Sales"]), 2, "Both legitimate sales must be recorded")
        self.assertEqual(len(db.memory_store["Payments"]), 2, "Both payments must be recorded")
        sold = [r for r in db.memory_store["SalesmanStockLedger"] if r.get("txn_type") == "SOLD_DELIVERY"]
        self.assertEqual(len(sold), 2, "Both stock deductions must be recorded")

    async def test_03_malformed_and_oversized_keys_rejected(self):
        """idempotency_key exceeding 120 chars or containing control characters must be rejected."""
        long_key = "K" * 121
        req_long = SaleCreate(
            idempotency_key=long_key,
            customer_id="CUS-000001",
            items=[SaleItemCreate(product_id="PRD-000001", actual_unit_price=100.0, quantity=1)],
        )
        with self.assertRaises(Exception) as ctx:
            await sales_router.create_sale(req_long, request=make_test_request(nonce=long_key), current_user=self.mock_user)
        self.assertIn("120 characters", str(ctx.exception))

        req_ctrl = SaleCreate(
            idempotency_key="INVALID\nKEY",
            customer_id="CUS-000001",
            items=[SaleItemCreate(product_id="PRD-000001", actual_unit_price=100.0, quantity=1)],
        )
        with self.assertRaises(Exception) as ctx:
            await sales_router.create_sale(req_ctrl, request=make_test_request(nonce="INVALID\nKEY"), current_user=self.mock_user)
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
            sales_router.create_sale(req, request=make_test_request(nonce=idemp_key), current_user=self.mock_user),
            sales_router.create_sale(req, request=make_test_request(nonce=idemp_key), current_user=self.mock_user),
            sales_router.create_sale(req, request=make_test_request(nonce=idemp_key), current_user=self.mock_user),
        )

        # All results should have the exact same sale_id
        sale_ids = {s.sale_id for s in results}
        self.assertEqual(len(sale_ids), 1, "Concurrent idempotent calls must resolve to a single sale")

        # Database tables must only contain 1 entry
        self.assertEqual(len(db.memory_store["Sales"]), 1)
        self.assertEqual(len(db.memory_store["SaleItems"]), 1)
        self.assertEqual(len(db.memory_store["Payments"]), 1)
        self.assertEqual(len([r for r in db.memory_store["SalesmanStockLedger"] if r.get("txn_type") == "SOLD_DELIVERY"]), 1)


if __name__ == "__main__":
    unittest.main()
