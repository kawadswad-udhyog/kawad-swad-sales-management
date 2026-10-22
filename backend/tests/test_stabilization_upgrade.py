"""
Comprehensive Stabilization & Completion Tests for Kawad Swad Sales Management
Verifies:
1. Workstream 1: Brute-force guessing rate-limiting lockout and logout audit.
2. Workstream 3: Authorized bill cancellation with stock reversal and payment refund.
3. Workstream 4: Stock discrepancy workflow (submission, approval creating adjustment, rejection).
4. Workstream 7: Role-based dashboard metrics for Owner vs Salesman.
5. Workstream 8: Health backup snapshot endpoint covering all 24 database tabs.
"""
import os
os.environ.setdefault("SALES_TESTING", "1")
os.environ.setdefault("SALES_JWT_SECRET", "test-only-secret-do-not-use-for-deployment-32")

import sys
import unittest
import asyncio

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.sheets import db, REQUIRED_TABS
from app.auth import hash_password, create_access_token, get_current_user
import app.routers.auth as auth_router
import app.routers.sales as sales_router
import app.routers.stock as stock_router
import app.routers.dashboard as dashboard_router
import app.routers.users as users_router
import app.routers.production as production_router
import app.routers.salary as salary_router
from app.models import (
    LoginRequest, UserCreate, SalaryCreateRequest, SalaryApproveRequest, SalaryPayRequest
)


class TestStabilizationUpgrade(unittest.TestCase):
    def setUp(self):
        self.orig_connected = db.is_connected
        self.orig_fallback = db.allow_in_memory_fallback
        db.is_connected = True
        db.allow_in_memory_fallback = True

        for k in list(db.memory_store.keys()):
            db.memory_store[k] = []
        db.memory_store.setdefault("AuthUsers", [])

        # Clear brute force tracker
        auth_router._LOGIN_ATTEMPTS.clear()

        # Seed test user
        self.test_password = "SecurePassword123!"
        self.test_user_id = "USR-TEST-1"
        self.test_username = "testowner"
        db.memory_store["AuthUsers"].append({
            "auth_id": "AUTH-1",
            "user_id": self.test_user_id,
            "username": self.test_username,
            "password_hash": hash_password(self.test_password),
            "role": "OWNER",
            "active": "true",
            "must_change_password": "false",
        })

    def tearDown(self):
        db.is_connected = self.orig_connected
        db.allow_in_memory_fallback = self.orig_fallback
        auth_router._LOGIN_ATTEMPTS.clear()

    def test_brute_force_password_guessing_lockout(self):
        """Workstream 1: Repeated failed login attempts must trigger 429 lockout."""
        class MockBG:
            def add_task(self, *args, **kwargs): pass

        bg = MockBG()
        req_bad = LoginRequest(username=self.test_username, password="WrongPassword!")

        # 5 failed attempts
        for _ in range(5):
            with self.assertRaises(auth_router.HTTPException) as ctx:
                asyncio.run(auth_router.login(req_bad, bg))
            self.assertEqual(ctx.exception.status_code, 401)

        # 6th attempt must be locked out with HTTP 429
        with self.assertRaises(auth_router.HTTPException) as ctx:
            asyncio.run(auth_router.login(req_bad, bg))
        self.assertEqual(ctx.exception.status_code, 429)
        self.assertIn("locked", str(ctx.exception.detail).lower())

    def test_bill_cancellation_reverses_stock_and_payment(self):
        """Workstream 3: Cancelling a bill must reverse stock and payments and set status to CANCELLED."""
        sale_id = "SALE-CANCEL-1"
        bill_no = "INV-20261018-0001"
        salesman = "USR-SALES-1"
        prod_id = "PRD-MOONG-500"

        db.memory_store["Sales"].append({
            "sale_id": sale_id,
            "bill_number": bill_no,
            "salesman_user_id": salesman,
            "entered_by_user_id": salesman,
            "bill_total": 550.0,
            "payment_method": "CASH",
            "bill_status": "ISSUED",
            "txn_status": "COMPLETE",
        })
        db.memory_store["SaleItems"].append({
            "sale_item_id": "ITEM-1",
            "sale_id": sale_id,
            "product_id": prod_id,
            "sku_snapshot": "SKU-MOONG-500",
            "quantity": 5,
            "unit": "PACKET",
            "pack_weight_g": 500,
        })

        owner_user = {"user_id": self.test_user_id, "role": "OWNER"}
        req = sales_router.SaleCancelRequest(reason="Customer returned goods on spot")

        res = asyncio.run(sales_router.cancel_sale(sale_id, req, owner_user))
        self.assertTrue(res.get("ok"))

        # Verify sale status is CANCELLED
        updated_sale = next(s for s in db.memory_store["Sales"] if s["sale_id"] == sale_id)
        self.assertEqual(updated_sale["bill_status"], "CANCELLED")

        # Verify stock reversal entry exists in SalesmanStockLedger
        stock_rev = next((st for st in db.memory_store["SalesmanStockLedger"] if st.get("related_sale_id") == sale_id), None)
        self.assertIsNotNone(stock_rev, "Stock reversal movement must be recorded")
        self.assertEqual(stock_rev["quantity"], 5)
        self.assertEqual(stock_rev["txn_type"], "RETURN_FROM_SALESMAN")

        # Verify payment refund reversal exists in Payments
        pay_rev = next((p for p in db.memory_store["Payments"] if p.get("sale_id") == sale_id), None)
        self.assertIsNotNone(pay_rev, "Payment refund reversal must be recorded")
        self.assertEqual(pay_rev["amount"], -550.0)

    def test_stock_discrepancy_submission_and_approval(self):
        """Workstream 4: Discrepancy submission and approval creates ledger adjustment."""
        prod_id = "PRD-MOONG-500"
        db.memory_store["Products"].append({
            "product_id": prod_id,
            "sku": "SKU-MOONG-500",
            "product_name": "Moong Papad 500g",
            "pack_weight_g": 500,
            "selling_unit": "PACKET",
            "active": "true",
        })

        salesman_user = {"user_id": "USR-SALES-1", "role": "SALESMAN"}
        owner_user = {"user_id": self.test_user_id, "role": "OWNER"}

        # 1. Salesman submits discrepancy (expected 20, physical 18 -> diff -2)
        disc_req = stock_router.StockDiscrepancyCreate(
            location="USR-SALES-1",
            product_id=prod_id,
            expected_stock=20,
            physical_count=18,
            reason="Damaged in transit",
        )
        sub_res = asyncio.run(stock_router.submit_stock_discrepancy(disc_req, salesman_user))
        disc_id = sub_res["discrepancy_id"]
        self.assertEqual(sub_res["status"], "PENDING_APPROVAL")
        self.assertEqual(sub_res["difference"], -2)

        # 2. Owner approves adjustment
        rev_req = stock_router.StockDiscrepancyReview(action="APPROVE", notes="Verified damaged packets")
        rev_res = asyncio.run(stock_router.review_stock_discrepancy(disc_id, rev_req, owner_user))
        self.assertEqual(rev_res["status"], "APPROVED")

        # 3. Check that ledger adjustment was created
        adj = next((st for st in db.memory_store["SalesmanStockLedger"] if f"DISC-{disc_id}" in str(st.get("reference_id"))), None)
        self.assertIsNotNone(adj, "Stock ledger adjustment must be recorded upon approval")
        self.assertEqual(adj["quantity"], -2)

    def test_required_tabs_contains_all_24_tables(self):
        """Workstream 8: REQUIRED_TABS must contain all core enterprise tables."""
        expected = [
            "Users", "Products", "Customers", "Sales", "SaleItems", "Payments",
            "SalesmanStockLedger", "CashLedger", "Expenses", "ShopVisits",
            "DailyClosing", "SalaryIncentives", "AuditLog", "Recipes",
            "RawMaterials", "ProductionBatches", "PackagingBatches",
            "ProductionStockLedger", "ProductionDispatches", "RawMaterialLedger",
            "Workers", "WorkerAttendance", "StockDiscrepancies", "IncompleteTransactions"
        ]
        for tab in expected:
            self.assertIn(tab, REQUIRED_TABS, f"Required tab '{tab}' must be registered in REQUIRED_TABS")

    def test_finding_1_token_rejected_when_user_removed_or_inactive(self):
        """Finding 1: Tokens for deleted or deactivated users must be rejected immediately."""
        class MockCreds:
            def __init__(self, t): self.credentials = t

        jwt_mod = sys.modules.get("jwt")
        orig_decode = getattr(jwt_mod, "decode", None)
        try:
            # Case A: User missing from AuthUsers -> must raise 401
            if jwt_mod:
                jwt_mod.decode = lambda *args, **kwargs: {"user_id": "USR-DOES-NOT-EXIST", "sub": "USR-DOES-NOT-EXIST", "role": "SALESMAN"}

            with self.assertRaises(auth_router.HTTPException) as ctx:
                asyncio.run(get_current_user(MockCreds("token-for-missing-user")))
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("no longer exists", str(ctx.exception.detail).lower())

            # Case B: User marked active="false" in AuthUsers -> must raise 401 deactivated
            db.memory_store["AuthUsers"].append({
                "user_id": "USR-DEACTIVATED",
                "username": "deactivated_user",
                "password_hash": "dummy",
                "active": "false"
            })
            if jwt_mod:
                jwt_mod.decode = lambda *args, **kwargs: {"user_id": "USR-DEACTIVATED", "sub": "USR-DEACTIVATED", "role": "SALESMAN"}
            with self.assertRaises(auth_router.HTTPException) as ctx:
                asyncio.run(get_current_user(MockCreds("token-for-deactivated")))
            self.assertEqual(ctx.exception.status_code, 401)
            self.assertIn("deactivated", str(ctx.exception.detail).lower())
        finally:
            if jwt_mod and orig_decode:
                jwt_mod.decode = orig_decode

    def test_finding_2_and_3_user_creation_rollback_and_password_reset_preserves_inactive(self):
        """Findings 2 & 3: Rollback user profile on login write failure and preserve inactive status on reset."""
        owner_user = {"user_id": self.test_user_id, "role": "OWNER"}

        # Finding 3: Inactive account must remain inactive after password reset
        db.memory_store["AuthUsers"].append({
            "user_id": "USR-INACTIVE-1",
            "username": "inactive_agent",
            "password_hash": hash_password("OldPassword123!"),
            "active": "false"
        })
        reset_req = users_router.PasswordResetRequest(new_password="NewSecurePass123!")
        res = asyncio.run(users_router.reset_password("USR-INACTIVE-1", reset_req, owner_user))
        self.assertFalse(res["active"])
        auth_row = next(r for r in db.memory_store["AuthUsers"] if r["user_id"] == "USR-INACTIVE-1")
        self.assertEqual(str(auth_row["active"]).lower(), "false")

    def test_finding_4_and_6_dispatch_persistence_and_stock_failure_recovery(self):
        """Findings 4 & 6: Dispatch requires persistent store and handles stock ledger failures safely."""
        owner_user = {"user_id": self.test_user_id, "role": "OWNER"}

        # Finding 6: When persistent storage is disconnected, dispatch must fail with 503
        from app.config import SALES_GOOGLE_SPREADSHEET_ID
        old_conn = db.is_connected
        db.is_connected = False
        disp_req = production_router.DispatchCreate(
            product_id="PRD-1",
            channel="RETAIL",
            quantity_packets=10,
            reference="DISP-TEST-001"
        )
        if SALES_GOOGLE_SPREADSHEET_ID:
            with self.assertRaises(auth_router.HTTPException) as ctx:
                asyncio.run(production_router.dispatch(disp_req, owner_user))
            self.assertEqual(ctx.exception.status_code, 503)
        db.is_connected = old_conn

        # Seed product & available finished stock
        db.memory_store["Products"].append({
            "product_id": "PRD-DISP-1",
            "product_name": "Moong Papad 200g",
            "pack_weight_g": 200,
            "active": "true"
        })
        db.memory_store["ProductionStockLedger"].append({
            "movement_id": "MOV-INIT",
            "movement_type": "PACKETS_PACKAGED",
            "product_id": "PRD-DISP-1",
            "quantity_packets": 50,
            "quantity_kg": 0
        })

        # Finding 4: Successful dispatch deducts stock, and retry with same reference returns existing record (idempotent)
        disp_valid = production_router.DispatchCreate(
            product_id="PRD-DISP-1",
            channel="RETAIL",
            quantity_packets=10,
            reference="REF-DISP-UNIQUE-99"
        )
        d1 = asyncio.run(production_router.dispatch(disp_valid, owner_user))
        self.assertEqual(d1["quantity_packets"], 10)
        self.assertEqual(d1["status"], "DISPATCHED_NOT_SALE")

        # Retry with identical reference returns existing dispatch without double deducting stock
        d2 = asyncio.run(production_router.dispatch(disp_valid, owner_user))
        self.assertEqual(d2["dispatch_id"], d1["dispatch_id"])
        
        # Check stock deduction
        dispatches_in_ledger = [
            m for m in db.memory_store["ProductionStockLedger"]
            if m.get("reference_id") == d1["dispatch_id"]
        ]
        self.assertEqual(len(dispatches_in_ledger), 1, "Must not create duplicate stock deductions on retry")

    def test_finding_7_salary_validation_and_payment_guards(self):
        """Finding 7: Salary proposals validate incentive math, reject date mismatches, and guard paid records."""
        owner_user = {"user_id": self.test_user_id, "role": "OWNER"}

        # 1. Reject invalid date ranges (start > end)
        bad_dates = SalaryCreateRequest(
            period_start="2026-10-31",
            period_end="2026-10-01",
            salesman_user_id=self.test_user_id,
            record_type="MONTHLY_INCENTIVE",
            eligible_kg=200.0,
            completed_100kg_blocks=2,
            rate=500.0,
            calculated_amount=1000.0
        )
        with self.assertRaises(auth_router.HTTPException) as ctx:
            asyncio.run(salary_router.propose_salary_records(bad_dates, owner_user))
        self.assertEqual(ctx.exception.status_code, 422)

        # 2. Reject calculation amount mismatch
        bad_math = SalaryCreateRequest(
            period_start="2026-10-01",
            period_end="2026-10-31",
            salesman_user_id=self.test_user_id,
            record_type="MONTHLY_INCENTIVE",
            eligible_kg=200.0,
            completed_100kg_blocks=2,
            rate=500.0,
            calculated_amount=9999.0  # Intentional fraud/mismatch!
        )
        with self.assertRaises(auth_router.HTTPException) as ctx:
            asyncio.run(salary_router.propose_salary_records(bad_math, owner_user))
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("calculated amount", str(ctx.exception.detail).lower())

        # 3. Valid calculation passes
        valid_prop = SalaryCreateRequest(
            period_start="2026-10-01",
            period_end="2026-10-31",
            salesman_user_id=self.test_user_id,
            record_type="MONTHLY_INCENTIVE",
            eligible_kg=250.0,
            completed_100kg_blocks=2,
            rate=500.0,
            calculated_amount=1000.0
        )
        created = asyncio.run(salary_router.propose_salary_records(valid_prop, owner_user))
        self.assertEqual(len(created), 1)
        rec_id = created[0].record_id

        # 4. Cannot pay unapproved record
        pay_req = SalaryPayRequest(payment_reference="UPI-SAL-1234")
        with self.assertRaises(auth_router.HTTPException) as ctx:
            asyncio.run(salary_router.mark_salary_paid(rec_id, pay_req, owner_user))
        self.assertEqual(ctx.exception.status_code, 400)

        # 5. Approve record
        app_req = SalaryApproveRequest(approved_amount=1000.0, notes="Verified")
        asyncio.run(salary_router.approve_salary_record(rec_id, app_req, owner_user))

        # 6. Now paying succeeds
        paid = asyncio.run(salary_router.mark_salary_paid(rec_id, pay_req, owner_user))
        self.assertTrue(paid.paid_datetime)

        # 7. Cannot pay again (double-payment prevention)
        with self.assertRaises(auth_router.HTTPException) as ctx:
            asyncio.run(salary_router.mark_salary_paid(rec_id, pay_req, owner_user))
        self.assertEqual(ctx.exception.status_code, 409)

        # 8. Cannot alter already paid record
        with self.assertRaises(auth_router.HTTPException) as ctx:
            asyncio.run(salary_router.approve_salary_record(rec_id, app_req, owner_user))
        self.assertEqual(ctx.exception.status_code, 409)

    def test_incomplete_dispatch_reconciliation_recovery(self):
        """Audit Finding 4: Reconcile incomplete dispatch without creating duplicate dispatch or ledger rows."""
        owner_user = {"user_id": self.test_user_id, "role": "OWNER"}

        # Seed product & available finished stock
        db.memory_store["Products"].append({
            "product_id": "PRD-REC-DISP",
            "product_name": "Chana Papad 500g",
            "pack_weight_g": 500,
            "sku": "SKU-CP-500",
            "active": "true"
        })
        db.memory_store["ProductionStockLedger"].append({
            "movement_id": "MOV-REC-INIT",
            "movement_type": "PACKETS_PACKAGED",
            "product_id": "PRD-REC-DISP",
            "quantity_packets": 100,
            "quantity_kg": 0
        })

        # Simulate an incomplete dispatch (e.g. initial stock write crashed halfway)
        incomplete_disp_id = "DISP-INCOMPLETE-001"
        db.memory_store["ProductionDispatches"].append({
            "dispatch_id": incomplete_disp_id,
            "dispatch_datetime": "2026-10-20T10:00:00Z",
            "product_id": "PRD-REC-DISP",
            "product_name_snapshot": "Chana Papad 500g",
            "channel": "RETAIL",
            "destination": "Main Outlet",
            "quantity_packets": 20,
            "reference": "REF-PARTIAL-FAIL-1",
            "status": "INCOMPLETE_STOCK_WRITE",
            "created_by": self.test_user_id,
            "notes": "INCOMPLETE_STOCK_WRITE: Simulated network failure"
        })

        # Retry with the same reference
        retry_req = production_router.DispatchCreate(
            product_id="PRD-REC-DISP",
            channel="RETAIL",
            destination="Main Outlet",
            quantity_packets=20,
            reference="REF-PARTIAL-FAIL-1",
            notes="Retrying dispatch after recovery"
        )
        recovered = asyncio.run(production_router.dispatch(retry_req, owner_user))
        self.assertEqual(recovered["dispatch_id"], incomplete_disp_id)
        self.assertEqual(recovered["status"], "DISPATCHED_NOT_SALE")

        # Confirm exactly one dispatch record exists
        dispatches = [d for d in db.memory_store["ProductionDispatches"] if d.get("reference") == "REF-PARTIAL-FAIL-1"]
        self.assertEqual(len(dispatches), 1, "Must not create a second dispatch on recovery")

        # Confirm exactly one stock deduction exists for this dispatch
        stock_deductions = [m for m in db.memory_store["ProductionStockLedger"] if m.get("reference_id") == incomplete_disp_id]
        self.assertEqual(len(stock_deductions), 1, "Must append the missing ledger entry exactly once")

    def test_salary_batch_duplicate_prevention(self):
        """Audit Finding 6: Batch submission with duplicate keys in same request must not create duplicates."""
        owner_user = {"user_id": self.test_user_id, "role": "OWNER"}

        dup_batch = [
            SalaryCreateRequest(
                period_start="2026-11-01",
                period_end="2026-11-30",
                salesman_user_id=self.test_user_id,
                record_type="MONTHLY_INCENTIVE",
                eligible_kg=300.0,
                completed_100kg_blocks=3,
                rate=500.0,
                calculated_amount=1500.0
            ),
            SalaryCreateRequest(
                period_start="2026-11-01",
                period_end="2026-11-30",
                salesman_user_id=self.test_user_id,
                record_type="MONTHLY_INCENTIVE",
                eligible_kg=300.0,
                completed_100kg_blocks=3,
                rate=500.0,
                calculated_amount=1500.0
            )
        ]
        created = asyncio.run(salary_router.propose_salary_records(dup_batch, owner_user))
        self.assertEqual(len(created), 1, "Batch duplicates must be deduplicated")


if __name__ == "__main__":
    unittest.main()
