"""Regression tests for sale recovery, stock, auth, closing, and production permissions."""
import os
os.environ.setdefault("SALES_TESTING", "1")
os.environ.setdefault("SALES_JWT_SECRET", "test-only-secret-do-not-use-for-deployment-32")

import unittest
import tests
from fastapi import HTTPException

from app.auth import hash_password, verify_password, password_needs_reset
from app.sheets import db, REQUIRED_TABS, ID_PREFIXES
from app.models import SaleCreate, SaleItemCreate
import app.routers.sales as _sales_mod
import app.routers.auth as _auth_mod
import app.routers.users as _users_mod
import app.routers.closing as _closing_mod
from app.models import DailyClosingCreate, UserCreate
from tests.v2_test_harness import LocalAppsScriptSimulator, V2RouterProxy

sales_router = V2RouterProxy(_sales_mod)
auth_router = V2RouterProxy(_auth_mod)
users_router = V2RouterProxy(_users_mod)
closing_router = V2RouterProxy(_closing_mod)


def _stock(user="USR-000001", product="PRD-000001", qty=50):
    return {
        "stock_txn_id": "STK-SEED",
        "salesman_user_id": user,
        "product_id": product,
        "txn_type": "SALESMAN_POSITIVE_ADJUSTMENT",
        "quantity": qty,
    }


class IntegrityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._orig_connected = db.is_connected
        self._orig_fallback = db.allow_in_memory_fallback
        db.is_connected = False
        db.allow_in_memory_fallback = True
        db._records_cache.clear()
        db._worksheets.clear()
        db._fail_once.clear()
        for key in list(REQUIRED_TABS.keys()) + list(ID_PREFIXES.keys()):
            db.memory_store[key] = []
        self._sim = LocalAppsScriptSimulator().start()
        db.memory_store["Products"] = [{
            "product_id": "PRD-000001", "sku": "PAPAD-500", "product_name": "Moong Papad",
            "pack_weight_g": 500, "selling_unit": "PACKET", "active": "true",
        }]
        db.memory_store["SalesmanStockLedger"] = [_stock()]
        db.memory_store["AuthUsers"] = [{
            "auth_id": "AUTH-000001", "user_id": "USR-000001", "username": "ramesh",
            "password_hash": hash_password("correct-horse"), "role": "SALESMAN",
            "active": "true", "must_change_password": "false",
        }]
        self.user = {"user_id": "USR-000001", "role": "SALESMAN", "full_name": "Ramesh"}

    def tearDown(self):
        if hasattr(self, "_sim"):
            self._sim.stop()
        db.is_connected = self._orig_connected
        db.allow_in_memory_fallback = self._orig_fallback
        db._records_cache.clear()
        db._worksheets.clear()
        db._fail_once.clear()

    def _sale(self, key="KEY-1", qty=2, total=None, price=100.0):
        line_total = qty * price
        return SaleCreate(
            idempotency_key=key,
            sales_type="Retailer Sale",
            payment_method="UPI",
            payment_reference="UPI123",
            items=[SaleItemCreate(product_id="PRD-000001", quantity=qty, actual_unit_price=price, line_total=line_total)],
            bill_total=total if total is not None else line_total,
        )

    async def test_payment_reference_and_no_cash_for_upi(self):
        sale = await sales_router.create_sale(self._sale(), self.user)
        self.assertEqual(sale.payment_method, "UPI")
        self.assertEqual(sale.payment_reference, "UPI123")
        self.assertEqual(db.memory_store["Payments"][0]["reference_number"], "UPI123")
        self.assertEqual(db.memory_store["CashLedger"], [])
        self.assertEqual(len(sale.lines or []), 1)

    async def test_rejects_client_total_and_inactive_and_oversell(self):
        with self.assertRaises(HTTPException) as ctx:
            await sales_router.create_sale(self._sale(total=1), self.user)
        self.assertEqual(ctx.exception.status_code, 422)
        db.memory_store["Products"][0]["active"] = "false"
        with self.assertRaises(HTTPException):
            await sales_router.create_sale(self._sale(key="KEY-2"), self.user)
        db.memory_store["Products"][0]["active"] = "true"
        with self.assertRaises(HTTPException) as ctx:
            await sales_router.create_sale(self._sale(key="KEY-3", qty=999), self.user)
        self.assertIn("Insufficient stock", ctx.exception.detail)

    async def test_retry_repairs_payment_without_duplicate_stock(self):
        # 1. Under V2.1 Single-Write-Owner, CREATE_SALE fails atomically if Payments fails
        #    (no orphan INCOMPLETE Sales row or premature SOLD_DELIVERY deduction).
        db._fail_once["Payments"] = 1
        with self.assertRaises(HTTPException):
            await sales_router.create_sale(self._sale(key="RECOVER"), self.user)
        self.assertEqual(len(db.memory_store["Sales"]), 0)
        self.assertEqual(len([r for r in db.memory_store["SalesmanStockLedger"] if r.get("txn_type") == "SOLD_DELIVERY"]), 0)
        self.assertEqual(db.memory_store["Payments"], [])
        sale = await sales_router.create_sale(self._sale(key="RECOVER"), self.user)
        self.assertEqual(sale.txn_status, "COMPLETE")
        self.assertEqual(len(db.memory_store["Sales"]), 1)
        self.assertEqual(len(db.memory_store["Payments"]), 1)
        self.assertEqual(len([r for r in db.memory_store["SalesmanStockLedger"] if r.get("txn_type") == "SOLD_DELIVERY"]), 1)
        self.assertEqual(len(db.memory_store["SaleItems"]), 1)

        # 2. Legacy INCOMPLETE sale recovery via RESUME_SALE must complete missing payment
        #    without duplicating existing SaleItems or SOLD_DELIVERY stock rows.
        db.memory_store["Sales"].append({
            "sale_id": "SALE-999001",
            "bill_number": "BILL-999001",
            "sale_datetime": "2026-04-12T10:00:00Z",
            "salesman_user_id": "USR-000001",
            "sales_type": "Retailer Sale",
            "payment_method": "UPI",
            "payment_reference": "UPI123",
            "payment_status": "PAID",
            "cash_collected": 200.0,
            "bill_total": 200.0,
            "txn_status": "INCOMPLETE",
            "idempotency_key": "RECOVER-LEGACY",
            "notes": "[idemp:RECOVER-LEGACY] [txn:INCOMPLETE]",
        })
        db.memory_store["SaleItems"].append({
            "sale_item_id": "SIT-999001",
            "sale_id": "SALE-999001",
            "product_id": "PRD-000001",
            "quantity_packets": 2,
            "actual_unit_price": 100.0,
            "line_total": 200.0,
            "notes": "[line:0]",
        })
        db.memory_store["SalesmanStockLedger"].append({
            "stock_txn_id": "STK-999001",
            "salesman_user_id": "USR-000001",
            "product_id": "PRD-000001",
            "txn_type": "SOLD_DELIVERY",
            "quantity": -2,
            "related_sale_id": "SALE-999001",
            "reference_id": "BILL-999001#0",
            "notes": "[line:0] Sale delivery against bill",
        })
        resumed = await sales_router.create_sale(self._sale(key="RECOVER-LEGACY"), self.user)
        self.assertEqual(resumed.txn_status, "COMPLETE")
        legacy_stock = [r for r in db.memory_store["SalesmanStockLedger"] if r.get("related_sale_id") == "SALE-999001" and r.get("txn_type") == "SOLD_DELIVERY"]
        legacy_items = [r for r in db.memory_store["SaleItems"] if r.get("sale_id") == "SALE-999001"]
        legacy_payments = [r for r in db.memory_store["Payments"] if r.get("sale_id") == "SALE-999001"]
        self.assertEqual(len(legacy_stock), 1)
        self.assertEqual(len(legacy_items), 1)
        self.assertEqual(len(legacy_payments), 1)

    async def test_salesman_cannot_bill_as_someone_else(self):
        req = self._sale()
        req.salesman_user_id = "USR-OTHER"
        with self.assertRaises(HTTPException) as ctx:
            await sales_router.create_sale(req, self.user)
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_password_rejects_plaintext_and_empty_auth(self):
        self.assertTrue(verify_password("correct-horse", db.memory_store["AuthUsers"][0]["password_hash"]))
        self.assertFalse(verify_password("correct-horse", "correct-horse"))
        self.assertTrue(password_needs_reset("correct-horse"))
        db.memory_store["AuthUsers"] = []
        with self.assertRaises(HTTPException) as ctx:
            await auth_router.login(type("R", (), {"username": "ramesh", "password": "x"})(), background_tasks=type("B", (), {"add_task": lambda *a, **k: None})())
        self.assertEqual(ctx.exception.status_code, 401)

    async def test_pa_cannot_create_owner(self):
        with self.assertRaises(HTTPException) as ctx:
            await users_router.create_user(
                UserCreate(username="boss", full_name="Boss", role="OWNER", password="long-password"),
                {"user_id": "USR-PA", "role": "PA"},
            )
        self.assertEqual(ctx.exception.status_code, 403)

    async def test_duplicate_closing_and_stock_difference(self):
        user = {"user_id": "USR-000001", "role": "SALESMAN"}
        first = await closing_router.submit_daily_closing(
            DailyClosingCreate(opening_cash=100, physical_cash_returned=100, physical_stock=[{"product_id": "PRD-000001", "quantity": 1}]),
            user,
        )
        self.assertTrue(first.stock_discrepancy_flag)
        with self.assertRaises(HTTPException) as ctx:
            await closing_router.submit_daily_closing(DailyClosingCreate(opening_cash=100, physical_cash_returned=100), user)
        self.assertEqual(ctx.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
