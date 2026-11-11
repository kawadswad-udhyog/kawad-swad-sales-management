# backend/tests/test_phase1_4_1_failure_injection.py
"""
Kawad Swad ERP - Phase 1.4.1 Failure-Injection Test Suite
Verifies mandatory credit approval validation, fail-closed approval consumption,
CAS / multi-worker credit protection, and resilient journal reversal recovery.
"""

import asyncio
import builtins
import multiprocessing
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from datetime import date, timedelta
from unittest.mock import patch
from fastapi import HTTPException

# Configure path and spawn environment
tests_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(tests_dir, ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
if tests_dir not in sys.path:
    sys.path.insert(0, tests_dir)
os.environ["PYTHONPATH"] = f"{backend_dir}:{tests_dir}:{os.environ.get('PYTHONPATH', '')}"

# Configure test environment
os.environ["SALES_TESTING"] = "1"
os.environ["SALES_AUTH_MOCK"] = "1"

from app.sheets import db, StorageCorruptionError, StorageIOError
from unittest.mock import patch
from app.timeutil import now_iso
from app.models import SaleCreate, SaleItemCreate, SalePaymentCreate
from app.routers.sales import (
    create_sale,
    cancel_sale,
    record_sale_payment,
    SaleCancelRequest,
)
from app.accounting.journal_engine import (
    calculate_trial_balance,
)
import app.accounting.journal_engine as je
import app.accounting.customer_ledger as cl
from app.accounting.customer_ledger import (
    reserve_credit_approval,
    consume_credit_approval,
    release_credit_approval,
    reset_cross_process_state,
)


def _mp_credit_sale_worker(req_dict, user_dict, shared_dir, barrier, out_q):
    os.environ["SALES_TESTING"] = "1"
    os.environ["SALES_AUTH_MOCK"] = "1"
    os.environ["SALES_SHARED_TEST_DIR"] = shared_dir
    from app.sheets import db
    db.enable_shared_file_store(shared_dir)
    from app.routers.sales import create_sale
    from app.models import SaleCreate, SaleItemCreate

    items = [SaleItemCreate(**it) for it in req_dict["items"]]
    req = SaleCreate(
        salesman_user_id=req_dict["salesman_user_id"],
        customer_id=req_dict["customer_id"],
        payment_method=req_dict["payment_method"],
        cash_collected=req_dict["cash_collected"],
        credit_amount=req_dict["credit_amount"],
        items=items,
        idempotency_key=req_dict.get("idempotency_key"),
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        barrier.wait(timeout=5)
        res = loop.run_until_complete(create_sale(req, current_user=user_dict))
        out_q.put(("SUCCESS", res.sale_id, float(res.credit_amount)))
    except HTTPException as exc:
        out_q.put(("HTTP_ERR", exc.status_code, str(exc.detail)))
    except Exception as exc:
        out_q.put(("ERR", str(exc)))
    finally:
        loop.close()


def _mp_idemp_sale_worker(req_dict, user_dict, shared_dir, barrier, out_q):
    os.environ["SALES_TESTING"] = "1"
    os.environ["SALES_AUTH_MOCK"] = "1"
    os.environ["SALES_SHARED_TEST_DIR"] = shared_dir
    from app.sheets import db
    db.enable_shared_file_store(shared_dir)
    from app.routers.sales import create_sale
    from app.models import SaleCreate, SaleItemCreate

    items = [SaleItemCreate(**it) for it in req_dict["items"]]
    req = SaleCreate(
        salesman_user_id=req_dict["salesman_user_id"],
        customer_id=req_dict["customer_id"],
        payment_method=req_dict["payment_method"],
        cash_collected=req_dict["cash_collected"],
        credit_amount=req_dict["credit_amount"],
        items=items,
        idempotency_key=req_dict["idempotency_key"],
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        barrier.wait(timeout=5)
        res = loop.run_until_complete(create_sale(req, current_user=user_dict))
        out_q.put(("SUCCESS", res.sale_id, res.bill_number))
    except HTTPException as exc:
        out_q.put(("HTTP_ERR", exc.status_code, str(exc.detail)))
    except Exception as exc:
        out_q.put(("ERR", str(exc)))
    finally:
        loop.close()


def _mp_reservation_worker(approval_id, sale_id, customer_id, credit_amt, shared_dir, barrier, out_q):
    os.environ["SALES_TESTING"] = "1"
    os.environ["SALES_AUTH_MOCK"] = "1"
    if shared_dir:
        os.environ["SALES_SHARED_TEST_DIR"] = shared_dir
        from app.sheets import db
        db.enable_shared_file_store(shared_dir)
    try:
        barrier.wait(timeout=5)
        ok = reserve_credit_approval(approval_id, sale_id, customer_id, credit_amt)
        out_q.put(("SUCCESS", approval_id, sale_id))
    except HTTPException as exc:
        out_q.put(("HTTP_ERR", exc.status_code, str(exc.detail)))
    except Exception as exc:
        out_q.put(("ERR", str(exc)))


class TestPhase141FailureInjection(unittest.TestCase):
    def setUp(self):
        db.disable_shared_file_store()
        db.memory_store = {tab: [] for tab in db.memory_store}
        reset_cross_process_state()
        self._seed_core_data()

    def tearDown(self):
        db.disable_shared_file_store()
        reset_cross_process_state()

    def _seed_core_data(self):
        # Users
        db.append_record("Users", {
            "user_id": "USR-OWNER-01",
            "username": "owner_ramesh",
            "role": "OWNER",
            "active": "TRUE",
        })
        db.append_record("Users", {
            "user_id": "USR-PA-01",
            "username": "pa_suresh",
            "role": "PA",
            "active": "TRUE",
        })
        db.append_record("Users", {
            "user_id": "USR-SALES-01",
            "username": "sales_vikram",
            "role": "SALESMAN",
            "active": "TRUE",
        })

        # Customers
        db.append_record("Customers", {
            "customer_id": "CUS-REG-01",
            "shop_name": "Sharma Kirana",
            "credit_limit": 5000.0,
            "max_overdue_days": 30,
            "active": "TRUE",
        })
        db.append_record("Customers", {
            "customer_id": "CUS-TIGHT-01",
            "shop_name": "Verma Store",
            "credit_limit": 1000.0,
            "max_overdue_days": 15,
            "active": "TRUE",
        })

        # Products
        db.append_record("Products", {
            "product_id": "PRD-PAPAD-200G",
            "product_name": "Moong Papad 200g",
            "sku": "MP-200G",
            "unit": "PACKET",
            "base_unit_price": 50.0,
            "active": "TRUE",
        })

        # Stock for salesman
        db.append_record("SalesmanStockLedger", {
            "stock_txn_id": "STK-INIT-01",
            "txn_datetime": now_iso(),
            "salesman_user_id": "USR-SALES-01",
            "product_id": "PRD-PAPAD-200G",
            "sku_snapshot": "MP-200G",
            "txn_type": "ISSUE_TO_SALESMAN",
            "quantity": 1000,
            "unit": "PACKET",
            "pack_weight_g": 200,
            "related_sale_id": "",
            "issued_by_user_id": "USR-OWNER-01",
            "received_by_user_id": "USR-SALES-01",
            "confirmed_by_user_id": "USR-SALES-01",
            "reference_id": "INIT-01",
            "notes": "Initial inventory loading",
        })

        self.owner_user = {"user_id": "USR-OWNER-01", "username": "owner_ramesh", "role": "OWNER"}
        self.pa_user = {"user_id": "USR-PA-01", "username": "pa_suresh", "role": "PA"}
        self.salesman_user = {"user_id": "USR-SALES-01", "username": "sales_vikram", "role": "SALESMAN"}

    def test_01_approval_missing_customer_id_raises_400(self):
        """Failure Injection 1: Approval request with missing customer_id must be rejected with HTTP 400."""
        db.append_record("ApprovalRequests", {
            "request_id": "APP-FAIL-01",
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "",  # Missing customer ID
            "approved_amount": 2000.0,
            "expires_at": (date.today() + timedelta(days=7)).isoformat(),
        })

        req = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-TIGHT-01",
            payment_method="CASH",
            cash_collected=0.0,
            credit_amount=1500.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=30, actual_unit_price=50.0)],
            owner_credit_approval_id="APP-FAIL-01",
            idempotency_key="fail-01-key",
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_sale(req, current_user=self.salesman_user))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("missing customer id", ctx.exception.detail.lower())

    def test_02_approval_missing_approved_amount_raises_400(self):
        """Failure Injection 2: Approval request with missing approved_amount must be rejected with HTTP 400."""
        db.append_record("ApprovalRequests", {
            "request_id": "APP-FAIL-02",
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-TIGHT-01",
            "approved_amount": "",  # Missing amount
            "expires_at": (date.today() + timedelta(days=7)).isoformat(),
        })

        req = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-TIGHT-01",
            payment_method="CASH",
            cash_collected=0.0,
            credit_amount=1500.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=30, actual_unit_price=50.0)],
            owner_credit_approval_id="APP-FAIL-02",
            idempotency_key="fail-02-key",
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_sale(req, current_user=self.salesman_user))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("missing approved amount", ctx.exception.detail.lower())

    def test_03_approval_zero_or_invalid_approved_amount_raises_400(self):
        """Failure Injection 3: Approval request with zero or non-numeric amount must be rejected with HTTP 400."""
        db.append_record("ApprovalRequests", {
            "request_id": "APP-FAIL-03",
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-TIGHT-01",
            "approved_amount": 0.0,  # Zero amount
            "expires_at": (date.today() + timedelta(days=7)).isoformat(),
        })

        req = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-TIGHT-01",
            payment_method="CASH",
            cash_collected=0.0,
            credit_amount=1500.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=30, actual_unit_price=50.0)],
            owner_credit_approval_id="APP-FAIL-03",
            idempotency_key="fail-03-key",
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_sale(req, current_user=self.salesman_user))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("must be > 0", ctx.exception.detail.lower())

    def test_04_approval_missing_expiry_date_raises_400(self):
        """Failure Injection 4: Approval request with missing expiry date must be rejected with HTTP 400."""
        db.append_record("ApprovalRequests", {
            "request_id": "APP-FAIL-04",
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-TIGHT-01",
            "approved_amount": 2000.0,
            "expires_at": "",  # Missing expiry
        })

        req = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-TIGHT-01",
            payment_method="CASH",
            cash_collected=0.0,
            credit_amount=1500.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=30, actual_unit_price=50.0)],
            owner_credit_approval_id="APP-FAIL-04",
            idempotency_key="fail-04-key",
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_sale(req, current_user=self.salesman_user))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("missing expiry date", ctx.exception.detail.lower())

    def test_05_approval_malformed_expiry_date_raises_400(self):
        """Failure Injection 5: Approval request with malformed expiry date must be rejected with HTTP 400."""
        db.append_record("ApprovalRequests", {
            "request_id": "APP-FAIL-05",
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-TIGHT-01",
            "approved_amount": 2000.0,
            "expires_at": "invalid-date-string",  # Malformed date
        })

        req = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-TIGHT-01",
            payment_method="CASH",
            cash_collected=0.0,
            credit_amount=1500.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=30, actual_unit_price=50.0)],
            owner_credit_approval_id="APP-FAIL-05",
            idempotency_key="fail-05-key",
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_sale(req, current_user=self.salesman_user))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("malformed expiry date", ctx.exception.detail.lower())

    def test_06_approval_wrong_customer_raises_400(self):
        """Failure Injection 6: Approval granted for Customer A cannot be used by Customer B (HTTP 400)."""
        db.append_record("ApprovalRequests", {
            "request_id": "APP-FAIL-06",
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-REG-01",  # Issued for CUS-REG-01
            "approved_amount": 2000.0,
            "expires_at": (date.today() + timedelta(days=7)).isoformat(),
        })

        # Attempt to use on CUS-TIGHT-01
        req = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-TIGHT-01",
            payment_method="CASH",
            cash_collected=0.0,
            credit_amount=1500.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=30, actual_unit_price=50.0)],
            owner_credit_approval_id="APP-FAIL-06",
            idempotency_key="fail-06-key",
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_sale(req, current_user=self.salesman_user))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("does not match current customer", ctx.exception.detail.lower())

    def test_07_approval_amount_exceeded_raises_400(self):
        """Failure Injection 7: Requested credit exceeding the approved limit must be rejected with HTTP 400."""
        db.append_record("ApprovalRequests", {
            "request_id": "APP-FAIL-07",
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-TIGHT-01",
            "approved_amount": 1200.0,  # Approved for ₹1,200
            "expires_at": (date.today() + timedelta(days=7)).isoformat(),
        })

        # Requesting ₹1,500 credit
        req = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-TIGHT-01",
            payment_method="CASH",
            cash_collected=0.0,
            credit_amount=1500.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=30, actual_unit_price=50.0)],
            owner_credit_approval_id="APP-FAIL-07",
            idempotency_key="fail-07-key",
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_sale(req, current_user=self.salesman_user))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("exceeds approved limit", ctx.exception.detail.lower())

    def test_08_approval_expired_raises_400(self):
        """Failure Injection 8: Expired approval request must be rejected with HTTP 400."""
        db.append_record("ApprovalRequests", {
            "request_id": "APP-FAIL-08",
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-TIGHT-01",
            "approved_amount": 2000.0,
            "expires_at": (date.today() - timedelta(days=1)).isoformat(),  # Yesterday
        })

        req = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-TIGHT-01",
            payment_method="CASH",
            cash_collected=0.0,
            credit_amount=1500.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=30, actual_unit_price=50.0)],
            owner_credit_approval_id="APP-FAIL-08",
            idempotency_key="fail-08-key",
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_sale(req, current_user=self.salesman_user))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("expired", ctx.exception.detail.lower())

    def test_09_approval_revoked_raises_400(self):
        """Failure Injection 9: Revoked approval request must be rejected with HTTP 400."""
        db.append_record("ApprovalRequests", {
            "request_id": "APP-FAIL-09",
            "request_type": "CREDIT_EXCEPTION",
            "status": "REVOKED",  # Revoked status
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-TIGHT-01",
            "approved_amount": 2000.0,
            "expires_at": (date.today() + timedelta(days=7)).isoformat(),
            "revoked": True,
        })

        req = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-TIGHT-01",
            payment_method="CASH",
            cash_collected=0.0,
            credit_amount=1500.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=30, actual_unit_price=50.0)],
            owner_credit_approval_id="APP-FAIL-09",
            idempotency_key="fail-09-key",
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_sale(req, current_user=self.salesman_user))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("revoked", ctx.exception.detail.lower())

    def test_10_approval_already_consumed_raises_400(self):
        """Failure Injection 10: Already consumed approval request must be rejected with HTTP 400."""
        db.append_record("ApprovalRequests", {
            "request_id": "APP-FAIL-10",
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-TIGHT-01",
            "approved_amount": 2000.0,
            "expires_at": (date.today() + timedelta(days=7)).isoformat(),
            "is_consumed": True,
            "consumed_by_sale_id": "SAL-PREV-01",
            "consumed_at": now_iso(),
        })

        req = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-TIGHT-01",
            payment_method="CASH",
            cash_collected=0.0,
            credit_amount=1500.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=30, actual_unit_price=50.0)],
            owner_credit_approval_id="APP-FAIL-10",
            idempotency_key="fail-10-key",
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_sale(req, current_user=self.salesman_user))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("consumed", ctx.exception.detail.lower())

    def test_11_approval_consumption_update_failure_fails_closed(self):
        """
        Failure Injection 11:
        If writing the approval consumption update fails when finalizing sale:
        - Must fail closed with HTTP 503.
        - Must log to IncompleteTransactions with type APPROVAL_CONSUMPTION_PENDING.
        - Sales record must NOT be marked COMPLETE (remains INCOMPLETE).
        - Approval remains reserved for this sale ID.
        """
        db.append_record("ApprovalRequests", {
            "request_id": "APP-FAIL-11",
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-TIGHT-01",
            "approved_amount": 2000.0,
            "expires_at": (date.today() + timedelta(days=7)).isoformat(),
            "is_consumed": False,
            "reserved_by_sale_id": "",
        })

        orig_update = db.update_record

        # Simulate update_record failing specifically when marking approval as consumed
        def mock_update_record(*args, **kwargs):
            tab = args[0] if len(args) > 0 else (kwargs.get("tab_name") or kwargs.get("table"))
            upds = args[3] if len(args) > 3 else (kwargs.get("updates") or kwargs.get("fields") or {})
            if str(tab) == "ApprovalRequests" and isinstance(upds, dict) and upds.get("is_consumed") is True:
                return False
            return orig_update(*args, **kwargs)

        db.update_record = mock_update_record

        req = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-TIGHT-01",
            payment_method="CASH",
            cash_collected=0.0,
            credit_amount=1500.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=30, actual_unit_price=50.0)],
            owner_credit_approval_id="APP-FAIL-11",
            idempotency_key="fail-11-idemp",
        )

        try:
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(create_sale(req, current_user=self.salesman_user))
            self.assertEqual(ctx.exception.status_code, 503)
            self.assertIn("credit approval consumption could not be saved", ctx.exception.detail)

            # Check Sales record status: must remain INCOMPLETE
            sales = db.get_records("Sales", fresh=True)
            self.assertEqual(len(sales), 1)
            created_sale = sales[0]
            self.assertEqual(str(created_sale.get("txn_status")), "INCOMPLETE")

            # Check IncompleteTransactions entry
            inc_records = db.get_records("IncompleteTransactions", fresh=True)
            inc_cons = [
                r for r in inc_records
                if str(r.get("transaction_type")) == "APPROVAL_CONSUMPTION_PENDING"
                and str(r.get("status")) == "CONSUMPTION_FAILED"
            ]
            self.assertEqual(len(inc_cons), 1)
            self.assertEqual(str(inc_cons[0].get("idempotency_key")), f"appr-cons-{created_sale.get('sale_id')}")

            # Check ApprovalRequest: must remain reserved by this sale ID and NOT marked consumed
            approvals = db.get_records("ApprovalRequests", fresh=True)
            appr = next(a for a in approvals if str(a.get("request_id")) == "APP-FAIL-11")
            self.assertFalse(appr.get("is_consumed"))
            self.assertEqual(str(appr.get("reserved_by_sale_id")), str(created_sale.get("sale_id")))

        finally:
            db.update_record = orig_update

    def test_12_sale_retry_after_approval_reservation_succeeds_idempotently(self):
        """
        Failure Injection 12:
        A retry with the same idempotency key resumes an incomplete sale where
        the approval was already reserved, completes approval consumption,
        marks the sale COMPLETE, and resolves IncompleteTransactions.
        """
        db.append_record("ApprovalRequests", {
            "request_id": "APP-FAIL-12",
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-TIGHT-01",
            "approved_amount": 2000.0,
            "expires_at": (date.today() + timedelta(days=7)).isoformat(),
            "is_consumed": False,
            "reserved_by_sale_id": "",
        })

        orig_update = db.update_record
        fail_appr = True

        def conditional_update(*args, **kwargs):
            tab = args[0] if len(args) > 0 else (kwargs.get("tab_name") or kwargs.get("table"))
            upds = args[3] if len(args) > 3 else (kwargs.get("updates") or kwargs.get("fields") or {})
            if str(tab) == "ApprovalRequests" and isinstance(upds, dict) and upds.get("is_consumed") is True and fail_appr:
                return False
            return orig_update(*args, **kwargs)

        db.update_record = conditional_update

        req = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-TIGHT-01",
            payment_method="CASH",
            cash_collected=0.0,
            credit_amount=1500.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=30, actual_unit_price=50.0)],
            owner_credit_approval_id="APP-FAIL-12",
            idempotency_key="idemp-12-retry",
        )

        try:
            with self.assertRaises(HTTPException):
                asyncio.run(create_sale(req, current_user=self.salesman_user))

            # Now allow database update to succeed
            fail_appr = False

            # Retry exact same request with same idempotency key
            resumed_sale = asyncio.run(create_sale(req, current_user=self.salesman_user))
            self.assertIsNotNone(resumed_sale)
            self.assertEqual(resumed_sale.txn_status, "COMPLETE")

            # Verify ApprovalRequest is now consumed
            appr = next(a for a in db.get_records("ApprovalRequests", fresh=True) if str(a.get("request_id")) == "APP-FAIL-12")
            self.assertTrue(appr.get("is_consumed"))
            self.assertEqual(str(appr.get("consumed_by_sale_id")), resumed_sale.sale_id)

            # Verify IncompleteTransactions entry is now RESOLVED
            inc_records = db.get_records("IncompleteTransactions", fresh=True)
            inc = next(r for r in inc_records if str(r.get("idempotency_key")) == f"appr-cons-{resumed_sale.sale_id}")
            self.assertEqual(str(inc.get("status")), "RESOLVED")

        finally:
            db.update_record = orig_update

    def test_13_two_simultaneous_requests_attempting_same_approval_barrier_synchronized(self):
        """
        Failure Injection 13 (Concurrent Execution):
        Two simultaneous requests attempting to reserve/use the same approval.
        Uses a threading.Barrier to ensure genuine simultaneous invocation.
        Verifies that exactly one succeeds and the other is rejected with HTTP 400.
        """
        db.append_record("ApprovalRequests", {
            "request_id": "APP-CONC-13",
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-TIGHT-01",
            "approved_amount": 2000.0,
            "expires_at": (date.today() + timedelta(days=7)).isoformat(),
            "is_consumed": False,
            "reserved_by_sale_id": "",
        })

        req1 = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-TIGHT-01",
            payment_method="CASH",
            cash_collected=0.0,
            credit_amount=1500.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=30, actual_unit_price=50.0)],
            owner_credit_approval_id="APP-CONC-13",
            idempotency_key="conc-13-sale-1",
        )
        req2 = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-TIGHT-01",
            payment_method="CASH",
            cash_collected=0.0,
            credit_amount=1500.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=30, actual_unit_price=50.0)],
            owner_credit_approval_id="APP-CONC-13",
            idempotency_key="conc-13-sale-2",
        )

        barrier = threading.Barrier(2)
        results = []
        errors = []

        def worker(req):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                barrier.wait(timeout=5)
                res = loop.run_until_complete(create_sale(req, current_user=self.salesman_user))
                results.append(res)
            except Exception as e:
                errors.append(e)
            finally:
                loop.close()

        t1 = threading.Thread(target=worker, args=(req1,))
        t2 = threading.Thread(target=worker, args=(req2,))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        # Exactly one must succeed and one must be rejected
        self.assertEqual(len(results), 1, f"Expected exactly 1 success, got {len(results)}")
        self.assertEqual(len(errors), 1, f"Expected exactly 1 error, got {len(errors)}")
        self.assertIsInstance(errors[0], HTTPException)
        self.assertEqual(errors[0].status_code, 400)
        self.assertTrue(
            "consumed" in errors[0].detail.lower() or "reserved" in errors[0].detail.lower(),
            f"Expected consumed/reserved in detail, got: {errors[0].detail}"
        )

        # In database: approval must be consumed by the winning sale
        winning_sale_id = results[0].sale_id
        appr = next(a for a in db.get_records("ApprovalRequests", fresh=True) if str(a.get("request_id")) == "APP-CONC-13")
        self.assertTrue(appr.get("is_consumed"))
        self.assertEqual(str(appr.get("consumed_by_sale_id")), winning_sale_id)

    def test_14_cancellation_interrupted_between_multiple_journal_reversals(self):
        """
        Failure Injection 14:
        Cancellation with multiple vouchers (invoice + collection) is interrupted
        during the second reversal.
        - Must log ACCOUNTING_REVERSAL_PENDING to IncompleteTransactions.
        - Must return accounting_status = 'FAILED'.
        """
        # Create sale with partial credit and immediate collection
        req = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-REG-01",
            payment_method="CASH",
            cash_collected=1000.0,
            credit_amount=1000.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=40, actual_unit_price=50.0)],
            idempotency_key="interrupted-rev-14",
        )
        sale = asyncio.run(create_sale(req, current_user=self.salesman_user))
        sale_id = sale.sale_id

        # Record a second collection so we have multiple vouchers (invoice + 2 payments)
        pay_res = asyncio.run(record_sale_payment(
            sale_id=sale_id,
            payload=SalePaymentCreate(amount=500.0, payment_method="CASH", notes="Second cash instalment"),
            current_user=self.salesman_user,
        ))
        self.assertTrue(pay_res["ok"])

        # Count active vouchers
        headers = db.get_records("JournalHeaders", fresh=True)
        active_vouchers = [
            h for h in headers
            if str(h.get("status", "")).upper() in {"POSTED", "PROVISIONAL"}
        ]
        self.assertGreaterEqual(len(active_vouchers), 2)

        # Mock reverse_journal_voucher to fail on the 2nd reversal call
        orig_reverse = je.reverse_journal_voucher
        rev_calls = 0

        def fail_second_reversal(*args, **kwargs):
            nonlocal rev_calls
            rev_calls += 1
            if rev_calls >= 2:
                raise RuntimeError("GL network failure during multi-voucher reversal")
            return orig_reverse(*args, **kwargs)

        je.reverse_journal_voucher = fail_second_reversal

        try:
            cancel_res = asyncio.run(cancel_sale(
                sale_id=sale_id,
                req=SaleCancelRequest(reason="Customer return with partial failure injection"),
                current_user=self.owner_user,
            ))
            self.assertTrue(cancel_res["ok"])
            self.assertEqual(cancel_res["accounting_status"], "FAILED")
            self.assertIn("GL network failure", cancel_res["accounting_error"])

            # Verify IncompleteTransactions logged ACCOUNTING_REVERSAL_PENDING
            inc_records = db.get_records("IncompleteTransactions", fresh=True)
            inc_rev = [
                r for r in inc_records
                if str(r.get("transaction_type")) == "ACCOUNTING_REVERSAL_PENDING"
                and str(r.get("idempotency_key")) == f"acct-rev-sale-{sale_id}"
                and str(r.get("status")) == "REVERSAL_FAILED"
            ]
            self.assertEqual(len(inc_rev), 1)

        finally:
            je.reverse_journal_voucher = orig_reverse

    def test_15_retry_after_cancellation_interruption_completes_reversal_and_balances_gl(self):
        """
        Failure Injection 15:
        Retry after interrupted cancellation:
        - Reverses remaining active vouchers without duplicating already reversed vouchers.
        - Does not create duplicate refunds or stock movements.
        - Resolves ACCOUNTING_REVERSAL_PENDING in IncompleteTransactions.
        - Trial balance is balanced (total variance = ₹0.00).
        """
        # First execute test 14 to leave the sale in partially reversed state
        req = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-REG-01",
            payment_method="CASH",
            cash_collected=1000.0,
            credit_amount=1000.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=40, actual_unit_price=50.0)],
            idempotency_key="interrupted-rev-15",
        )
        sale = asyncio.run(create_sale(req, current_user=self.salesman_user))
        sale_id = sale.sale_id

        pay_res = asyncio.run(record_sale_payment(
            sale_id=sale_id,
            payload=SalePaymentCreate(amount=500.0, payment_method="CASH", notes="Second cash instalment"),
            current_user=self.salesman_user,
        ))
        self.assertTrue(pay_res["ok"])

        # Interrupt on 2nd reversal
        orig_reverse = je.reverse_journal_voucher
        rev_calls = 0

        def fail_second_reversal(*args, **kwargs):
            nonlocal rev_calls
            rev_calls += 1
            if rev_calls >= 2:
                raise RuntimeError("GL network failure during multi-voucher reversal")
            return orig_reverse(*args, **kwargs)

        je.reverse_journal_voucher = fail_second_reversal

        try:
            cancel_res_1 = asyncio.run(cancel_sale(
                sale_id=sale_id,
                req=SaleCancelRequest(reason="Customer return interrupted"),
                current_user=self.owner_user,
            ))
            self.assertEqual(cancel_res_1["accounting_status"], "FAILED")
        finally:
            je.reverse_journal_voucher = orig_reverse

        # Check that stock and payment refunds exist before retry
        stock_revs_before = [r for r in db.get_records("SalesmanStockLedger", fresh=True) if str(r.get("related_sale_id")) == sale_id and str(r.get("txn_type")) == "RETURN_FROM_SALESMAN"]
        pay_revs_before = [r for r in db.get_records("Payments", fresh=True) if str(r.get("sale_id")) == sale_id and float(r.get("amount", 0)) < 0]

        # RETRY CANCELLATION (with original functional reverse_journal_voucher)
        cancel_res_2 = asyncio.run(cancel_sale(
            sale_id=sale_id,
            req=SaleCancelRequest(reason="Retry of interrupted cancellation"),
            current_user=self.owner_user,
        ))

        self.assertTrue(cancel_res_2["ok"])
        self.assertTrue(cancel_res_2["already_cancelled"])
        self.assertEqual(cancel_res_2["accounting_status"], "REVERSED")

        # 1. Check no duplicate stock movements or payment refunds were created
        stock_revs_after = [r for r in db.get_records("SalesmanStockLedger", fresh=True) if str(r.get("related_sale_id")) == sale_id and str(r.get("txn_type")) == "RETURN_FROM_SALESMAN"]
        pay_revs_after = [r for r in db.get_records("Payments", fresh=True) if str(r.get("sale_id")) == sale_id and float(r.get("amount", 0)) < 0]
        self.assertEqual(len(stock_revs_before), len(stock_revs_after))
        self.assertEqual(len(pay_revs_before), len(pay_revs_after))

        # 2. Check all vouchers associated with this sale are now REVERSED
        sale_payments = [p for p in db.get_records("Payments", fresh=True) if str(p.get("sale_id", "")).strip() == sale_id]
        sale_payment_ids = {str(p.get("payment_id", "")).strip() for p in sale_payments}
        sale_vouchers = [
            h for h in db.get_records("JournalHeaders", fresh=True)
            if (str(h.get("reference_id", "")).strip() == sale_id and str(h.get("reference_type", "")).strip().upper() in {"SALE_INVOICE", "SALE"})
            or (str(h.get("reference_id", "")).strip() in sale_payment_ids and str(h.get("reference_type", "")).strip().upper() == "PAYMENT_COLLECTION")
        ]
        self.assertTrue(all(str(v.get("status")).upper() == "REVERSED" for v in sale_vouchers))

        # 3. Check IncompleteTransactions entry is resolved
        inc = next((r for r in db.get_records("IncompleteTransactions", fresh=True) if str(r.get("idempotency_key")) == f"acct-rev-sale-{sale_id}"), None)
        if inc:
            self.assertEqual(str(inc.get("status")), "RESOLVED")

        # 4. Verify General Ledger trial balance is balanced (total variance = ₹0.00)
        tb = calculate_trial_balance()
        self.assertEqual(float(tb.get("variance", 0)), 0.0)

    def test_16_two_separate_processes_attempting_same_approval(self):
        """
        Failure Injection 16:
        Two separate OS processes attempting to reserve the same approval request.
        Uses multiprocessing.Barrier(2) to synchronize both processes at the exact same moment.
        Verifies that cross-process filesystem locking ensures exactly one process reserves
        the approval, the other is rejected with HTTP 400, the reservation registry records
        the winner, and the filesystem lock was actually created and exercised.
        """
        db.append_record("ApprovalRequests", {
            "request_id": "APP-PROC-16",
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-TIGHT-01",
            "approved_amount": 2000.0,
            "expires_at": (date.today() + timedelta(days=7)).isoformat(),
            "is_consumed": False,
            "reserved_by_sale_id": "",
        })

        barrier = multiprocessing.Barrier(2)
        q = multiprocessing.Queue()

        def process_worker(appr_id, sale_id, b, out_q):
            try:
                b.wait(timeout=5)
                ok = reserve_credit_approval(appr_id, sale_id, "CUS-TIGHT-01", 1500.0)
                out_q.put(("SUCCESS", sale_id))
            except HTTPException as exc:
                out_q.put(("HTTP_ERR", exc.status_code, str(exc.detail)))
            except Exception as e:
                out_q.put(("ERR", str(e)))

        p1 = multiprocessing.Process(target=process_worker, args=("APP-PROC-16", "SALE-P1", barrier, q))
        p2 = multiprocessing.Process(target=process_worker, args=("APP-PROC-16", "SALE-P2", barrier, q))
        p1.start()
        p2.start()
        p1.join(timeout=10)
        p2.join(timeout=10)

        out1 = q.get(timeout=5)
        out2 = q.get(timeout=5)
        outcomes = [out1, out2]
        successes = [o for o in outcomes if o[0] == "SUCCESS"]
        http_errors = [o for o in outcomes if o[0] == "HTTP_ERR"]

        # 1. Exactly one process must succeed, one must fail with 400
        self.assertEqual(len(successes), 1, f"Expected 1 process to succeed, got: {outcomes}")
        self.assertEqual(len(http_errors), 1, f"Expected 1 process to fail with HTTP error, got: {outcomes}")
        self.assertEqual(http_errors[0][1], 400)
        self.assertIn("reserved", http_errors[0][2].lower())

        # 2. Verify the final reservation belongs to the successful sale
        winning_sale_id = successes[0][1]
        xp_res = cl.get_cross_process_reservation("APP-PROC-16")
        self.assertIsNotNone(xp_res, "Cross-process reservation state must exist")
        self.assertEqual(str(xp_res.get("reserved_by_sale_id")), winning_sale_id)

        # 3. Verify the test actually exercised the shared filesystem lock
        lock_file = os.path.join(cl._LOCK_DIR, "approval_APP-PROC-16.lock")
        self.assertTrue(os.path.exists(lock_file), f"Expected filesystem lock file {lock_file} to exist")

    def test_17_two_simultaneous_sales_attempting_to_exceed_customer_credit_limit(self):
        """
        Failure Injection 17:
        Customer has credit limit of ₹1000.00.
        Two concurrent sales simultaneously request ₹700.00 credit (total ₹1400.00).
        Uses threading.Barrier to ensure simultaneous invocation.
        Verifies that exactly one succeeds, and the other is rejected with HTTP 400.
        """
        req1 = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-TIGHT-01",
            payment_method="CASH",
            cash_collected=0.0,
            credit_amount=700.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=14, actual_unit_price=50.0)],
            idempotency_key="credit-limit-race-1",
        )
        req2 = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-TIGHT-01",
            payment_method="CASH",
            cash_collected=0.0,
            credit_amount=700.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=14, actual_unit_price=50.0)],
            idempotency_key="credit-limit-race-2",
        )

        barrier = threading.Barrier(2)
        results = []
        errors = []

        def worker(req):
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                barrier.wait(timeout=5)
                res = loop.run_until_complete(create_sale(req, current_user=self.salesman_user))
                results.append(res)
            except Exception as e:
                errors.append(e)
            finally:
                loop.close()

        t1 = threading.Thread(target=worker, args=(req1,))
        t2 = threading.Thread(target=worker, args=(req2,))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        self.assertEqual(len(results), 1, f"Expected exactly 1 success, got {len(results)}")
        self.assertEqual(len(errors), 1, f"Expected exactly 1 error, got {len(errors)}")
        self.assertIsInstance(errors[0], HTTPException)
        self.assertEqual(errors[0].status_code, 400)
        self.assertIn("credit", errors[0].detail.lower())

    def test_18_approval_consumption_attempted_by_sale_not_owning_reservation(self):
        """
        Failure Injection 18:
        Approval is reserved by SALE-LEGIT-18.
        Attempting to consume the approval by a different sale SALE-UNOWNED-99 must fail.
        Only the reserving sale can consume the approval.
        """
        db.append_record("ApprovalRequests", {
            "request_id": "APP-OWN-18",
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-TIGHT-01",
            "approved_amount": 2000.0,
            "expires_at": (date.today() + timedelta(days=7)).isoformat(),
            "is_consumed": False,
            "reserved_by_sale_id": "",
        })

        # Reserve by SALE-LEGIT-18
        ok = reserve_credit_approval("APP-OWN-18", "SALE-LEGIT-18", "CUS-TIGHT-01", 1000.0)
        self.assertTrue(ok)

        # Attempt consumption by unauthorized sale SALE-UNOWNED-99
        consumed_unowned = consume_credit_approval("APP-OWN-18", "SALE-UNOWNED-99")
        self.assertFalse(consumed_unowned, "Unauthorized sale must NOT be allowed to consume reservation")

        # Approval must still be unconsumed
        appr = next(a for a in db.get_records("ApprovalRequests", fresh=True) if str(a.get("request_id")) == "APP-OWN-18")
        self.assertFalse(appr.get("is_consumed"))
        self.assertEqual(str(appr.get("reserved_by_sale_id")), "SALE-LEGIT-18")

        # Legitimate sale consumes successfully
        consumed_legit = consume_credit_approval("APP-OWN-18", "SALE-LEGIT-18")
        self.assertTrue(consumed_legit)
        appr_after = next(a for a in db.get_records("ApprovalRequests", fresh=True) if str(a.get("request_id")) == "APP-OWN-18")
        self.assertTrue(appr_after.get("is_consumed"))

    def test_19_approval_release_attempted_by_sale_not_owning_reservation(self):
        """
        Failure Injection 19:
        Approval is reserved by SALE-LEGIT-19.
        Attempting to release the reservation by SALE-UNOWNED-99 must fail.
        Only the owning sale can release it.
        A consumed approval can NEVER be released.
        """
        db.append_record("ApprovalRequests", {
            "request_id": "APP-OWN-19",
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-TIGHT-01",
            "approved_amount": 2000.0,
            "expires_at": (date.today() + timedelta(days=7)).isoformat(),
            "is_consumed": False,
            "reserved_by_sale_id": "",
        })

        ok = reserve_credit_approval("APP-OWN-19", "SALE-LEGIT-19", "CUS-TIGHT-01", 1000.0)
        self.assertTrue(ok)

        # Attempt release by unauthorized sale
        released_unowned = release_credit_approval("APP-OWN-19", "SALE-UNOWNED-99")
        self.assertFalse(released_unowned)

        # Reservation remains held by SALE-LEGIT-19
        appr = next(a for a in db.get_records("ApprovalRequests", fresh=True) if str(a.get("request_id")) == "APP-OWN-19")
        self.assertEqual(str(appr.get("reserved_by_sale_id")), "SALE-LEGIT-19")

        # Legitimate sale releases it
        released_legit = release_credit_approval("APP-OWN-19", "SALE-LEGIT-19")
        self.assertTrue(released_legit)
        appr_after = next(a for a in db.get_records("ApprovalRequests", fresh=True) if str(a.get("request_id")) == "APP-OWN-19")
        self.assertEqual(str(appr_after.get("reserved_by_sale_id")), "")

        # Re-reserve and consume, then verify a consumed approval can NEVER be released
        reserve_credit_approval("APP-OWN-19", "SALE-LEGIT-19", "CUS-TIGHT-01", 1000.0)
        consume_credit_approval("APP-OWN-19", "SALE-LEGIT-19")
        released_consumed = release_credit_approval("APP-OWN-19", "SALE-LEGIT-19")
        self.assertFalse(released_consumed, "A consumed approval must NEVER be released")

    def test_20_retry_of_sale_after_successful_reservation_but_failed_sale_persistence(self):
        """
        Failure Injection 20:
        Sale successfully reserves approval, but database write fails during sale header write.
        The reservation must be released.
        Subsequent retry with the same (or new) request must succeed and complete cleanly.
        """
        db.append_record("ApprovalRequests", {
            "request_id": "APP-FAIL-20",
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-TIGHT-01",
            "approved_amount": 2000.0,
            "expires_at": (date.today() + timedelta(days=7)).isoformat(),
            "is_consumed": False,
            "reserved_by_sale_id": "",
        })

        req = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-TIGHT-01",
            payment_method="CASH",
            cash_collected=0.0,
            credit_amount=1500.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=30, actual_unit_price=50.0)],
            owner_credit_approval_id="APP-FAIL-20",
            idempotency_key="fail-persist-20",
        )

        # Inject single failure on Sales tab
        db.inject_failure_once("Sales")

        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_sale(req, current_user=self.salesman_user))
        self.assertEqual(ctx.exception.status_code, 503)

        # Approval must be cleanly released
        appr = next(a for a in db.get_records("ApprovalRequests", fresh=True) if str(a.get("request_id")) == "APP-FAIL-20")
        self.assertFalse(appr.get("is_consumed"))
        self.assertEqual(str(appr.get("reserved_by_sale_id", "")).strip(), "")

        # Retry with the same request
        retried_sale = asyncio.run(create_sale(req, current_user=self.salesman_user))
        self.assertEqual(retried_sale.txn_status, "COMPLETE")

        # Now approval is consumed
        appr_after = next(a for a in db.get_records("ApprovalRequests", fresh=True) if str(a.get("request_id")) == "APP-FAIL-20")
        self.assertTrue(appr_after.get("is_consumed"))
        self.assertEqual(str(appr_after.get("consumed_by_sale_id")), retried_sale.sale_id)

    def test_21_retry_of_sale_after_successful_persistence_but_failed_consumption(self):
        """
        Failure Injection 21:
        Sale header and lines are written, but approval consumption fails.
        Sale is left INCOMPLETE, logging APPROVAL_CONSUMPTION_PENDING.
        Retry of the same sale (with same idempotency key) consumes approval and completes sale.
        """
        db.append_record("ApprovalRequests", {
            "request_id": "APP-FAIL-21",
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-TIGHT-01",
            "approved_amount": 2000.0,
            "expires_at": (date.today() + timedelta(days=7)).isoformat(),
            "is_consumed": False,
            "reserved_by_sale_id": "",
        })

        req = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-TIGHT-01",
            payment_method="CASH",
            cash_collected=0.0,
            credit_amount=1500.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=30, actual_unit_price=50.0)],
            owner_credit_approval_id="APP-FAIL-21",
            idempotency_key="fail-consume-21",
        )

        orig_consume = cl.consume_credit_approval
        fail_consume = True

        def failing_consume(appr_id, s_id):
            if fail_consume and appr_id == "APP-FAIL-21":
                return False
            return orig_consume(appr_id, s_id)

        cl.consume_credit_approval = failing_consume

        try:
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(create_sale(req, current_user=self.salesman_user))
            self.assertEqual(ctx.exception.status_code, 503)

            # Check IncompleteTransactions
            inc_records = db.get_records("IncompleteTransactions", fresh=True)
            inc = next(r for r in inc_records if "APP-FAIL-21" in str(r.get("payload_json", "")))
            self.assertEqual(str(inc.get("status")), "CONSUMPTION_FAILED")

            # Now allow consumption to succeed
            fail_consume = False

            # Retry exact same request
            retried = asyncio.run(create_sale(req, current_user=self.salesman_user))
            self.assertEqual(retried.txn_status, "COMPLETE")

            # Approval is now consumed
            appr = next(a for a in db.get_records("ApprovalRequests", fresh=True) if str(a.get("request_id")) == "APP-FAIL-21")
            self.assertTrue(appr.get("is_consumed"))

            # IncompleteTransactions entry is resolved
            inc_after = next(r for r in db.get_records("IncompleteTransactions", fresh=True) if str(r.get("transaction_id")) == inc.get("transaction_id"))
            self.assertEqual(str(inc_after.get("status")), "RESOLVED")
        finally:
            cl.consume_credit_approval = orig_consume

    def test_22_concurrent_idempotent_retries_of_the_same_sale(self):
        """
        Failure Injection 22:
        Two simultaneous requests submitted with the exact same idempotency_key.
        Both threads must succeed and return the exact same sale_id.
        No duplicate rows in Sales, SaleItems, Payments, or SalesmanStockLedger.
        """
        req = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-REG-01",
            payment_method="CASH",
            cash_collected=1000.0,
            credit_amount=0.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=20, actual_unit_price=50.0)],
            idempotency_key="concurrent-idemp-22",
        )

        barrier = threading.Barrier(2)
        results = []
        errors = []

        def worker():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                barrier.wait(timeout=5)
                res = loop.run_until_complete(create_sale(req, current_user=self.salesman_user))
                results.append(res)
            except Exception as e:
                errors.append(e)
            finally:
                loop.close()

        t1 = threading.Thread(target=worker)
        t2 = threading.Thread(target=worker)
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        self.assertEqual(len(errors), 0, f"Expected 0 errors under idempotency serialization, got: {errors}")
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].sale_id, results[1].sale_id, "Both requests must return the identical sale_id")

        # Verify no duplicate entries in storage
        sale_rows = [s for s in db.get_records("Sales", fresh=True) if str(s.get("idempotency_key")) == "concurrent-idemp-22"]
        self.assertEqual(len(sale_rows), 1, "Exactly one Sales row must exist")

        item_rows = [i for i in db.get_records("SaleItems", fresh=True) if str(i.get("sale_id")) == results[0].sale_id]
        self.assertEqual(len(item_rows), 1, "Exactly one line item must exist")

        stock_rows = [m for m in db.get_records("SalesmanStockLedger", fresh=True) if str(m.get("related_sale_id")) == results[0].sale_id]
        self.assertEqual(len(stock_rows), 1, "Exactly one stock deduction must exist")

    def test_23_non_finite_approved_amounts_rejected(self):
        """
        Failure Injection 23:
        Non-finite values (NaN, Infinity, -Infinity) in approved amounts or settlement amounts
        must be strictly rejected with HTTP 400 or HTTP 422.
        """
        # 1. NaN in approved_amount
        db.append_record("ApprovalRequests", {
            "request_id": "APP-NAN-23",
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-TIGHT-01",
            "approved_amount": float("nan"),
            "expires_at": (date.today() + timedelta(days=7)).isoformat(),
        })

        req_nan = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-TIGHT-01",
            payment_method="CASH",
            cash_collected=0.0,
            credit_amount=1500.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=30, actual_unit_price=50.0)],
            owner_credit_approval_id="APP-NAN-23",
            idempotency_key="nan-test-23",
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_sale(req_nan, current_user=self.salesman_user))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("non-finite", ctx.exception.detail.lower())

        # 2. Infinity in approved_amount
        db.append_record("ApprovalRequests", {
            "request_id": "APP-INF-23",
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-TIGHT-01",
            "approved_amount": float("inf"),
            "expires_at": (date.today() + timedelta(days=7)).isoformat(),
        })
        req_inf = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-TIGHT-01",
            payment_method="CASH",
            cash_collected=0.0,
            credit_amount=1500.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=30, actual_unit_price=50.0)],
            owner_credit_approval_id="APP-INF-23",
            idempotency_key="inf-test-23",
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(create_sale(req_inf, current_user=self.salesman_user))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("non-finite", ctx.exception.detail.lower())

    def test_24_approval_revocation_while_reservation_is_pending(self):
        """
        Failure Injection 24:
        Approval is approved and reserved by SALE-PEND-24.
        Owner revokes the approval while reservation is pending.
        Subsequent consumption must be rejected.
        Credit extension must fail closed.
        """
        db.append_record("ApprovalRequests", {
            "request_id": "APP-REV-24",
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-TIGHT-01",
            "approved_amount": 2000.0,
            "expires_at": (date.today() + timedelta(days=7)).isoformat(),
            "is_consumed": False,
            "reserved_by_sale_id": "",
        })

        # Reserve approval
        ok = reserve_credit_approval("APP-REV-24", "SALE-PEND-24", "CUS-TIGHT-01", 1500.0)
        self.assertTrue(ok)

        # While reservation is pending, Owner revokes approval
        db.update_record("ApprovalRequests", "request_id", "APP-REV-24", {
            "status": "REVOKED",
            "revoked": True,
        })

        # Now attempt to consume the revoked approval
        consumed = consume_credit_approval("APP-REV-24", "SALE-PEND-24")
        self.assertFalse(consumed, "Revoked approval must NOT be consumable")

        # Verify approval is NOT marked consumed
        appr = next(a for a in db.get_records("ApprovalRequests", fresh=True) if str(a.get("request_id")) == "APP-REV-24")
        self.assertFalse(appr.get("is_consumed"))

    def test_25_cross_process_lock_directory_creation_failure_raises_503(self):
        """
        Failure Injection 25:
        Lock directory creation failure must fail closed with HTTP 503.
        Never silently continue without acquiring a required lock.
        """
        with patch("os.makedirs", side_effect=PermissionError("Permission denied creating lock dir")):
            with self.assertRaises(HTTPException) as ctx:
                with cl.CrossProcessLock("approval", "APP-DIR-25"):
                    pass
            self.assertEqual(ctx.exception.status_code, 503)
            self.assertIn("Lock directory creation failure", ctx.exception.detail)

    def test_26_cross_process_lock_file_open_failure_raises_503(self):
        """
        Failure Injection 26:
        Lock file opening failure must fail closed with HTTP 503.
        Never silently continue without acquiring a required lock.
        """
        orig_open = builtins.open
        def mock_open(*args, **kwargs):
            path_str = str(args[0]) if args else ""
            if path_str.endswith("approval_APP-FILE-26.lock"):
                raise PermissionError("Permission denied opening lock file")
            return orig_open(*args, **kwargs)

        with patch("builtins.open", side_effect=mock_open):
            with self.assertRaises(HTTPException) as ctx:
                with cl.CrossProcessLock("approval", "APP-FILE-26"):
                    pass
            self.assertEqual(ctx.exception.status_code, 503)
            self.assertIn("Lock file open failure", ctx.exception.detail)

    def test_27_cross_process_lock_acquisition_timeout_raises_503(self):
        """
        Failure Injection 27:
        Lock acquisition timeout when another process holds the lock must fail closed with HTTP 503.
        Never silently continue without acquiring a required lock.
        """
        import fcntl
        lock_path = os.path.join(cl._LOCK_DIR, "approval_APP-TIMEOUT-27.lock")
        os.makedirs(cl._LOCK_DIR, exist_ok=True)
        with open(lock_path, "w+") as fd:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                with self.assertRaises(HTTPException) as ctx:
                    with cl.CrossProcessLock("approval", "APP-TIMEOUT-27", timeout=0.05):
                        pass
                self.assertEqual(ctx.exception.status_code, 503)
                self.assertIn("Lock timeout", ctx.exception.detail)
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)

    def test_28_cross_process_lock_fcntl_unavailable_raises_503(self):
        """
        Failure Injection 28:
        When fcntl is unavailable, operations requiring cross-process protection must fail closed with HTTP 503.
        No-op resource locks are permitted to continue.
        """
        with patch.object(cl, "HAS_FCNTL", False):
            with self.assertRaises(HTTPException) as ctx:
                with cl.CrossProcessLock("approval", "APP-NOFCNTL-28"):
                    pass
            self.assertEqual(ctx.exception.status_code, 503)
            self.assertIn("fcntl missing", ctx.exception.detail)

            # No-op resource lock should not raise
            with cl.CrossProcessLock("noop", "none") as lock:
                self.assertIsNotNone(lock)

    def test_29_reservation_state_write_failure_raises_503_and_rolls_back(self):
        """
        Failure Injection 29:
        Reservation state write failure during credit approval reservation:
        - Must fail closed with HTTP 503.
        - Must roll back the database reservation to prevent dangling lock state.
        - Approval remains available/unreserved for subsequent valid transactions.
        """
        db.append_record("ApprovalRequests", {
            "request_id": "APP-FAIL-29",
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-TIGHT-01",
            "approved_amount": 2000.0,
            "expires_at": (date.today() + timedelta(days=7)).isoformat(),
            "is_consumed": False,
            "reserved_by_sale_id": "",
        })

        with patch.object(cl, "set_cross_process_reservation", side_effect=RuntimeError("Simulated disk I/O failure")):
            with self.assertRaises(HTTPException) as ctx:
                reserve_credit_approval("APP-FAIL-29", "SALE-FAIL-29", "CUS-TIGHT-01", 1500.0)
            self.assertEqual(ctx.exception.status_code, 503)
            self.assertIn("Failed to persist cross-process reservation", ctx.exception.detail)

        # Database rollback verification: ApprovalRequest must NOT remain reserved by SALE-FAIL-29
        appr = next(a for a in db.get_records("ApprovalRequests", fresh=True) if str(a.get("request_id")) == "APP-FAIL-29")
        self.assertEqual(str(appr.get("reserved_by_sale_id", "")), "")
        self.assertFalse(appr.get("is_consumed"))

    def test_30_customer_credit_limit_competition_across_separate_processes(self):
        """
        Failure Injection 30:
        Actual customer credit concurrency test across separate OS processes.
        - Customer credit limit: ₹1,000.
        - Two independent processes simultaneously attempt credit sales of ₹700 each.
        - Both execute the actual credit-control validation in create_sale().
        - Both use shared persistent test storage (JSON file store).
        - Exactly one sale may be completed.
        - Final outstanding must be ₹700, never ₹1,400.
        - Verify no duplicate payment or journal records.
        """
        temp_dir = tempfile.mkdtemp(prefix="ks_erp_credit_shared_")
        try:
            db.append_record("Customers", {
                "customer_id": "CUS-CONC-30",
                "shop_name": "Agrawal Concurrency Kirana",
                "credit_limit": 1000.0,
                "max_overdue_days": 30,
                "active": "TRUE",
            })
            db.enable_shared_file_store(temp_dir)

            req1_dict = {
                "salesman_user_id": "USR-SALES-01",
                "customer_id": "CUS-CONC-30",
                "payment_method": "CREDIT",
                "cash_collected": 0.0,
                "credit_amount": 700.0,
                "items": [{"product_id": "PRD-PAPAD-200G", "quantity": 14, "actual_unit_price": 50.0}],
                "idempotency_key": "credit-race-sale-1",
            }
            req2_dict = {
                "salesman_user_id": "USR-SALES-01",
                "customer_id": "CUS-CONC-30",
                "payment_method": "CREDIT",
                "cash_collected": 0.0,
                "credit_amount": 700.0,
                "items": [{"product_id": "PRD-PAPAD-200G", "quantity": 14, "actual_unit_price": 50.0}],
                "idempotency_key": "credit-race-sale-2",
            }

            ctx = multiprocessing.get_context("fork")
            barrier = ctx.Barrier(2)
            q = ctx.Queue()

            p1 = ctx.Process(
                target=_mp_credit_sale_worker,
                args=(req1_dict, self.salesman_user, temp_dir, barrier, q),
            )
            p2 = ctx.Process(
                target=_mp_credit_sale_worker,
                args=(req2_dict, self.salesman_user, temp_dir, barrier, q),
            )
            p1.start()
            p2.start()
            p1.join(timeout=10)
            p2.join(timeout=10)
            if p1.is_alive():
                p1.terminate()
                p1.join(timeout=2)
            if p2.is_alive():
                p2.terminate()
                p2.join(timeout=2)

            results = []
            while not q.empty():
                results.append(q.get())

            successes = [r for r in results if r[0] == "SUCCESS"]
            http_errors = [r for r in results if r[0] == "HTTP_ERR"]

            # 1. Exactly one sale completed
            self.assertEqual(len(successes), 1, f"Expected exactly 1 sale to complete, got: {results}")
            self.assertEqual(len(http_errors), 1, f"Expected exactly 1 sale to be rejected, got: {results}")
            self.assertEqual(http_errors[0][1], 400)
            self.assertTrue(
                "credit limit" in http_errors[0][2].lower() or "limit exceeded" in http_errors[0][2].lower(),
                f"Expected credit limit exceeded in detail, got: {http_errors[0][2]}"
            )

            winning_sale_id = successes[0][1]

            # 2. Exactly one sale record exists in shared storage
            sales = [
                s for s in db.get_records("Sales", fresh=True)
                if str(s.get("customer_id")) == "CUS-CONC-30" and str(s.get("txn_status")).upper() == "COMPLETE"
            ]
            self.assertEqual(len(sales), 1, "Exactly one completed sale record must exist in Sales storage")
            self.assertEqual(str(sales[0].get("sale_id")), winning_sale_id)

            # 3. Final outstanding must be ₹700, NEVER ₹1,400
            outstanding = cl.calculate_customer_outstanding("CUS-CONC-30")
            self.assertEqual(float(outstanding), 700.0)
            self.assertNotEqual(float(outstanding), 1400.0)

            # 4. Stock deducted only once (14 packets, not 28)
            stock_deductions = [
                r for r in db.get_records("SalesmanStockLedger", fresh=True)
                if str(r.get("txn_type")) == "SOLD_DELIVERY" and str(r.get("related_sale_id")) == winning_sale_id
            ]
            self.assertEqual(len(stock_deductions), 1, "Salesman stock must be deducted exactly once")
            self.assertEqual(float(stock_deductions[0].get("quantity")), -14.0)

            # 5. Verify no duplicate journal records (exactly 1 journal for the sale)
            journals = [
                j for j in db.get_records("JournalHeaders", fresh=True)
                if str(j.get("reference_id")) == winning_sale_id
            ]
            self.assertEqual(len(journals), 1, "Exactly one journal voucher must be created")

            # 6. Verify no duplicate payment records
            payments = [
                p for p in db.get_records("Payments", fresh=True)
                if str(p.get("sale_id")) == winning_sale_id
            ]
            self.assertEqual(len(payments), 0)

        finally:
            db.disable_shared_file_store()
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_31_idempotent_sale_requests_across_separate_processes(self):
        """
        Failure Injection 31:
        Actual idempotency concurrency test across separate OS processes.
        Two simultaneous sale requests with the same idempotency key using shared persistent test storage.
        Verify:
        - Exactly one sale record exists.
        - Both successful retries return the same sale ID.
        - Stock is deducted only once.
        - Payments are recorded only once.
        - Journal vouchers are created only once.
        """
        temp_dir = tempfile.mkdtemp(prefix="ks_erp_idemp_shared_")
        try:
            db.append_record("Customers", {
                "customer_id": "CUS-IDEMP-31",
                "shop_name": "Gupta Idempotent Store",
                "credit_limit": 5000.0,
                "max_overdue_days": 30,
                "active": "TRUE",
            })
            db.enable_shared_file_store(temp_dir)

            req_dict = {
                "salesman_user_id": "USR-SALES-01",
                "customer_id": "CUS-IDEMP-31",
                "payment_method": "CASH",
                "cash_collected": 500.0,
                "credit_amount": 0.0,
                "items": [{"product_id": "PRD-PAPAD-200G", "quantity": 10, "actual_unit_price": 50.0}],
                "idempotency_key": "idemp-race-shared-key-31",
            }

            ctx = multiprocessing.get_context("fork")
            barrier = ctx.Barrier(2)
            q = ctx.Queue()

            p1 = ctx.Process(
                target=_mp_idemp_sale_worker,
                args=(req_dict, self.salesman_user, temp_dir, barrier, q),
            )
            p2 = ctx.Process(
                target=_mp_idemp_sale_worker,
                args=(req_dict, self.salesman_user, temp_dir, barrier, q),
            )
            p1.start()
            p2.start()
            p1.join(timeout=10)
            p2.join(timeout=10)
            if p1.is_alive():
                p1.terminate()
                p1.join(timeout=2)
            if p2.is_alive():
                p2.terminate()
                p2.join(timeout=2)

            results = []
            while not q.empty():
                results.append(q.get())

            successes = [r for r in results if r[0] == "SUCCESS"]
            self.assertEqual(len(successes), 2, f"Expected both idempotent retries to succeed, got: {results}")

            # Both successful retries return the same sale ID
            sale_id_1 = successes[0][1]
            sale_id_2 = successes[1][1]
            self.assertEqual(sale_id_1, sale_id_2, "Both concurrent retries must return the exact same sale ID")

            winning_sale_id = sale_id_1

            # Exactly one sale record exists
            sales = [
                s for s in db.get_records("Sales", fresh=True)
                if str(s.get("idempotency_key")) == "idemp-race-shared-key-31"
            ]
            self.assertEqual(len(sales), 1, "Exactly one sale record must exist for this idempotency key")
            self.assertEqual(str(sales[0].get("sale_id")), winning_sale_id)

            # Stock is deducted only once (10 packets)
            stock_records = [
                r for r in db.get_records("SalesmanStockLedger", fresh=True)
                if str(r.get("txn_type")) == "SOLD_DELIVERY" and str(r.get("related_sale_id")) == winning_sale_id
            ]
            self.assertEqual(len(stock_records), 1, "Stock must be deducted exactly once")
            self.assertEqual(float(stock_records[0].get("quantity")), -10.0)

            # Payments are recorded only once
            payments = [
                p for p in db.get_records("Payments", fresh=True)
                if str(p.get("sale_id")) == winning_sale_id
            ]
            self.assertEqual(len(payments), 1, "Payment must be recorded exactly once")
            self.assertEqual(float(payments[0].get("amount")), 500.0)

            # Journal vouchers are created only once
            journals = [
                j for j in db.get_records("JournalHeaders", fresh=True)
                if str(j.get("reference_id")) == winning_sale_id
            ]
            self.assertEqual(len(journals), 1, "Journal voucher must be created exactly once")

        finally:
            db.disable_shared_file_store()
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_32_concurrent_reservations_for_different_approvals_both_survive_in_registry(self):
        """
        Failure Injection 32:
        Protect global reservation registry.
        Different approval IDs use different approval locks while writing the same registry file.
        Dedicated global cross-process registry lock ensures that simultaneous read-modify-write
        operations do not clobber each other.
        Verifies that when different processes reserve different approval IDs simultaneously,
        both entries survive intact in the global reservation registry.
        """
        temp_dir = tempfile.mkdtemp(prefix="ks_erp_res_shared_")
        try:
            db.append_record("ApprovalRequests", {
                "request_id": "APP-SURVIVE-32A",
                "request_type": "CREDIT_EXCEPTION",
                "status": "APPROVED",
                "decided_by": "USR-OWNER-01",
                "customer_id": "CUS-REG-01",
                "approved_amount": 2000.0,
                "expires_at": (date.today() + timedelta(days=7)).isoformat(),
                "is_consumed": False,
                "reserved_by_sale_id": "",
            })
            db.append_record("ApprovalRequests", {
                "request_id": "APP-SURVIVE-32B",
                "request_type": "CREDIT_EXCEPTION",
                "status": "APPROVED",
                "decided_by": "USR-OWNER-01",
                "customer_id": "CUS-TIGHT-01",
                "approved_amount": 2000.0,
                "expires_at": (date.today() + timedelta(days=7)).isoformat(),
                "is_consumed": False,
                "reserved_by_sale_id": "",
            })
            db.enable_shared_file_store(temp_dir)

            ctx = multiprocessing.get_context("fork")
            barrier = ctx.Barrier(2)
            q = ctx.Queue()

            p1 = ctx.Process(
                target=_mp_reservation_worker,
                args=("APP-SURVIVE-32A", "SALE-32A", "CUS-REG-01", 1000.0, temp_dir, barrier, q),
            )
            p2 = ctx.Process(
                target=_mp_reservation_worker,
                args=("APP-SURVIVE-32B", "SALE-32B", "CUS-TIGHT-01", 1000.0, temp_dir, barrier, q),
            )
            p1.start()
            p2.start()
            p1.join(timeout=10)
            p2.join(timeout=10)
            if p1.is_alive():
                p1.terminate()
                p1.join(timeout=2)
            if p2.is_alive():
                p2.terminate()
                p2.join(timeout=2)

            results = []
            while not q.empty():
                results.append(q.get())

            successes = [r for r in results if r[0] == "SUCCESS"]
            self.assertEqual(len(successes), 2, f"Expected both reservations to succeed, got: {results}")

            # Verify BOTH entries survive in the global reservation registry
            res_a = cl.get_cross_process_reservation("APP-SURVIVE-32A")
            res_b = cl.get_cross_process_reservation("APP-SURVIVE-32B")

            self.assertIsNotNone(res_a, "APP-SURVIVE-32A must survive in registry")
            self.assertEqual(str(res_a.get("reserved_by_sale_id")), "SALE-32A")

            self.assertIsNotNone(res_b, "APP-SURVIVE-32B must survive in registry")
            self.assertEqual(str(res_b.get("reserved_by_sale_id")), "SALE-32B")
        finally:
            db.disable_shared_file_store()
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_33_shared_storage_missing_file_initializes_as_empty_table(self):
        """Failure Injection 33: Genuinely missing file initializes cleanly as an empty table."""
        temp_dir = tempfile.mkdtemp(prefix="ks_erp_store_missing_")
        try:
            db.memory_store["IncompleteTransactions"] = []
            db.enable_shared_file_store(temp_dir)
            missing_tab_file = os.path.join(temp_dir, "IncompleteTransactions.json")
            self.assertFalse(os.path.exists(missing_tab_file))
            rows = db.get_records("IncompleteTransactions")
            self.assertEqual(rows, [])
        finally:
            db.disable_shared_file_store()
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_34_shared_storage_corrupted_json_raises_storage_corruption_error(self):
        """Failure Injection 34: Corrupted JSON file raises explicit StorageCorruptionError and never overwrites data."""
        temp_dir = tempfile.mkdtemp(prefix="ks_erp_store_corrupt_")
        try:
            db.enable_shared_file_store(temp_dir)
            corrupt_file = os.path.join(temp_dir, "Customers.json")
            with open(corrupt_file, "w", encoding="utf-8") as f:
                f.write("{corrupt_json: [invalid syntax")

            # 1. get_records raises StorageCorruptionError
            with self.assertRaises(StorageCorruptionError):
                db.get_records("Customers")

            # 2. append_record with raise_on_error=True raises StorageCorruptionError
            with self.assertRaises(StorageCorruptionError):
                db.append_record("Customers", {"customer_id": "CUS-BAD"}, raise_on_error=True)

            # 3. File content is preserved; never replaced with an empty table
            with open(corrupt_file, "r", encoding="utf-8") as f:
                content = f.read()
            self.assertEqual(content, "{corrupt_json: [invalid syntax")
        finally:
            db.disable_shared_file_store()
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_35_shared_storage_permission_denied_raises_storage_io_error(self):
        """Failure Injection 35: Permission denied during read raises explicit StorageIOError."""
        temp_dir = tempfile.mkdtemp(prefix="ks_erp_store_perm_")
        try:
            db.enable_shared_file_store(temp_dir)
            db.append_record("Customers", {"customer_id": "CUS-PERM-01", "shop_name": "Perm Shop"})

            with patch("builtins.open", side_effect=PermissionError("Permission denied [Errno 13]")):
                with self.assertRaises(StorageIOError):
                    db._read_shared_records("Customers")
        finally:
            db.disable_shared_file_store()
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_36_shared_storage_failed_temp_file_write_preserves_original_file(self):
        """Failure Injection 36: Failed temporary-file write cleans up temp file and preserves original data."""
        temp_dir = tempfile.mkdtemp(prefix="ks_erp_store_tempfail_")
        try:
            db.memory_store = {tab: [] for tab in db.memory_store}
            db.enable_shared_file_store(temp_dir)
            db.append_record("Customers", {"customer_id": "CUS-ORIG-01", "shop_name": "Original Store"})

            # Invalidate write by simulating disk full / I/O error on json.dump
            with patch("json.dump", side_effect=OSError(28, "No space left on device")):
                with self.assertRaises(StorageIOError):
                    db.append_record("Customers", {"customer_id": "CUS-FAIL-01"}, raise_on_error=True)

            # Original records remain completely intact
            records = db.get_records("Customers")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["customer_id"], "CUS-ORIG-01")

            # Verify no orphan .tmp.* files remain in storage directory
            tmp_files = [f for f in os.listdir(temp_dir) if ".tmp." in f]
            self.assertEqual(len(tmp_files), 0, f"Found orphan temp files: {tmp_files}")
        finally:
            db.disable_shared_file_store()
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_37_shared_storage_failed_atomic_replacement_cleans_up_temp_file(self):
        """Failure Injection 37: Failed atomic replacement (os.replace) raises StorageIOError, cleans up, and preserves data."""
        temp_dir = tempfile.mkdtemp(prefix="ks_erp_store_replacefail_")
        try:
            db.memory_store = {tab: [] for tab in db.memory_store}
            db.enable_shared_file_store(temp_dir)
            db.append_record("Customers", {"customer_id": "CUS-ORIG-02", "shop_name": "Original Store 2"})

            with patch("os.replace", side_effect=OSError(18, "Invalid cross-device link")):
                with self.assertRaises(StorageIOError):
                    db.append_record("Customers", {"customer_id": "CUS-FAIL-02"}, raise_on_error=True)

            # Original file remains completely intact
            records = db.get_records("Customers")
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]["customer_id"], "CUS-ORIG-02")

            # Verify no orphan .tmp.* files left behind
            tmp_files = [f for f in os.listdir(temp_dir) if ".tmp." in f]
            self.assertEqual(len(tmp_files), 0, f"Found orphan temp files: {tmp_files}")
        finally:
            db.disable_shared_file_store()
            shutil.rmtree(temp_dir, ignore_errors=True)

    def test_38_shared_storage_recovery_after_failed_write(self):
        """Failure Injection 38: Subsequent writes succeed cleanly following a failed write attempt."""
        temp_dir = tempfile.mkdtemp(prefix="ks_erp_store_recov_")
        try:
            db.memory_store = {tab: [] for tab in db.memory_store}
            db.enable_shared_file_store(temp_dir)
            db.append_record("Customers", {"customer_id": "CUS-REC-01", "shop_name": "Recovery Store 1"})

            # Injected failure
            with patch("os.replace", side_effect=OSError(5, "Input/output error")):
                with self.assertRaises(StorageIOError):
                    db.append_record("Customers", {"customer_id": "CUS-FAIL-03"}, raise_on_error=True)

            # Subsequent write recovers and succeeds cleanly
            ok = db.append_record("Customers", {"customer_id": "CUS-REC-02", "shop_name": "Recovery Store 2"}, raise_on_error=True)
            self.assertTrue(ok)

            records = db.get_records("Customers")
            self.assertEqual(len(records), 2)
            self.assertEqual(records[0]["customer_id"], "CUS-REC-01")
            self.assertEqual(records[1]["customer_id"], "CUS-REC-02")
        finally:
            db.disable_shared_file_store()
            shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
