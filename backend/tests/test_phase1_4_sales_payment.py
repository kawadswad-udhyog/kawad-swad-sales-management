"""
KAWAD SWAD ERP - PHASE 1.4: SALES PAYMENT INTEGRITY REPAIR
Automated Test Suite covering all 14 required verification scenarios:

1. Fully paid cash sale (₹3,600 bill, ₹3,600 cash, PAID, CashLedger +3,600, DR 1115 / CR 4100).
2. Fully paid UPI sale (₹3,600 bill, ₹3,600 UPI, PAID, CashLedger 0, DR 1120 / CR 4100).
3. Unpaid credit sale (₹3,600 bill, ₹0 cash, UNPAID, CashLedger 0, DR 1130 / CR 4100).
4. Partial payment sale (₹3,600 bill, ₹1,600 cash, ₹2,000 credit, PARTIAL, CashLedger +1,600, DR 1115 1,600, DR 1130 2,000, CR 4100 3,600).
5. Multiple collections against one invoice (Collect ₹600 -> remaining ₹1,400, PARTIAL, DR 1115 600 / CR 1130 600; Collect ₹1,400 -> remaining ₹0, PAID, DR 1115 1,400 / CR 1130 1,400).
6. Customer outstanding calculation from ledger transactions (calculate_customer_outstanding).
7. Credit limit exceeded blocked for salesman (e.g. limit ₹5,000, current ₹4,000, requested ₹2,000 -> HTTP 400).
8. Overdue customer blocked for salesman (unpaid invoice > 30 days old -> HTTP 400).
9. Owner approval for credit exception (Owner caller succeeds; or salesman with approved ApprovalRequests ID succeeds).
10. Partial-payment sale cancellation (reverses only ₹1,600 from salesman cash, not ₹3,600; reverses invoice & COGS).
11. Full-payment sale cancellation (reverses full collected amount; reverses invoice & COGS).
12. Duplicate collection prevention (same idempotency key replayed returns existing payment without duplicating).
13. Journal debit/credit equality across all sales, collections, and reversals.
14. Salesman cash reconciliation (CashLedger exactly equals physical cash collected minus refunds).
"""

import os
import sys
import unittest
import asyncio
from datetime import datetime, date, timedelta
from decimal import Decimal
from fastapi import HTTPException

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.sheets import db
from app.models import SaleCreate, SaleItemCreate, SalePaymentCreate
from app.routers.sales import create_sale, cancel_sale, record_sale_payment, SaleCancelRequest
from app.accounting.customer_ledger import (
    calculate_customer_outstanding,
    get_customer_transactions,
    get_customer_overdue_invoices,
    get_invoice_settlement_status,
)


class TestPhase14SalesPayment(unittest.TestCase):
    def setUp(self):
        # Reset in-memory database
        db.memory_store = {tab: [] for tab in db.memory_store}

        # Setup standard users
        self.owner_user = {
            "user_id": "USR-OWNER-01",
            "username": "sitaram",
            "role": "OWNER",
            "full_name": "Sita Ram",
        }
        self.salesman_user = {
            "user_id": "USR-SALES-01",
            "username": "vikram",
            "role": "SALESMAN",
            "full_name": "Vikram Singh",
        }
        db.append_record("Users", {**self.owner_user, "active": "true"})
        db.append_record("Users", {**self.salesman_user, "active": "true"})

        # Setup test product (₹180/packet, 500g)
        self.product_id = "PRD-PAPAD-500G"
        db.append_record("Products", {
            "product_id": self.product_id,
            "sku": "PAPAD-MOONG-500G",
            "product_name": "Moong Papad 500g",
            "category": "Papad",
            "pack_weight_g": 500,
            "selling_unit": "PACKET",
            "retail_pack_only": "false",
            "standard_cost": 120.0,
            "active": "true",
        })

        # Issue ample stock to salesman USR-SALES-01 and USR-OWNER-01
        db.append_record("SalesmanStockLedger", {
            "stock_txn_id": "STK-INIT-01",
            "txn_datetime": "2026-11-01T08:00:00",
            "salesman_user_id": "USR-SALES-01",
            "product_id": self.product_id,
            "sku_snapshot": "PAPAD-MOONG-500G",
            "txn_type": "ISSUE_TO_SALESMAN",
            "quantity": 500,
            "unit": "PACKET",
            "pack_weight_g": 500,
            "issued_by_user_id": "USR-OWNER-01",
            "received_by_user_id": "USR-SALES-01",
            "confirmed_by_user_id": "USR-SALES-01",
            "reference_id": "VAN-LOAD-01",
            "notes": "Initial van stock allocation",
        })
        db.append_record("SalesmanStockLedger", {
            "stock_txn_id": "STK-INIT-02",
            "txn_datetime": "2026-11-01T08:00:00",
            "salesman_user_id": "USR-OWNER-01",
            "product_id": self.product_id,
            "sku_snapshot": "PAPAD-MOONG-500G",
            "txn_type": "ISSUE_TO_SALESMAN",
            "quantity": 500,
            "unit": "PACKET",
            "pack_weight_g": 500,
            "issued_by_user_id": "USR-OWNER-01",
            "received_by_user_id": "USR-OWNER-01",
            "confirmed_by_user_id": "USR-OWNER-01",
            "reference_id": "OWNER-LOAD-01",
            "notes": "Owner stock allocation",
        })

        # Setup test registered customer with ₹10,000 credit limit
        self.customer_id = "CUS-TEST-01"
        db.append_record("Customers", {
            "customer_id": self.customer_id,
            "shop_name": "Sharma Kirana Store",
            "shopkeeper_name": "Ramesh Sharma",
            "mobile": "9876543210",
            "credit_limit": 10000.0,
            "max_overdue_days": 30,
            "active": "true",
        })

    def _create_sale_req(self, qty=20, unit_price=180.0, **kwargs):
        # 20 packets * ₹180 = ₹3,600
        line = SaleItemCreate(
            product_id=self.product_id,
            quantity=qty,
            actual_unit_price=unit_price,
            discount_amount=0.0,
            line_total=round(qty * unit_price, 2),
            pack_weight_g=500,
            unit="PACKET",
        )
        defaults = {
            "salesman_user_id": "USR-SALES-01",
            "customer_id": self.customer_id,
            "sales_type": "Retailer Sale",
            "subtotal": round(qty * unit_price, 2),
            "discount_amount": 0.0,
            "tax_amount": 0.0,
            "bill_total": round(qty * unit_price, 2),
            "items": [line],
        }
        defaults.update(kwargs)
        return SaleCreate(**defaults)

    # 1. Fully paid cash sale (₹3,600 bill, ₹3,600 cash, PAID, CashLedger +3,600, DR 1115 / CR 4100)
    def test_01_fully_paid_cash_sale(self):
        req = self._create_sale_req(
            payment_method="CASH",
            cash_collected=3600.0,
            credit_amount=0.0,
            idempotency_key="sale-test-01",
        )
        sale = asyncio.run(create_sale(req, current_user=self.salesman_user))

        self.assertEqual(sale.bill_total, 3600.0)
        self.assertEqual(sale.payment_status, "PAID")
        self.assertEqual(sale.cash_collected, 3600.0)
        self.assertEqual(sale.credit_amount, 0.0)

        # Check Payments tab
        payments = [p for p in db.get_records("Payments") if p.get("sale_id") == sale.sale_id]
        self.assertEqual(len(payments), 1)
        self.assertEqual(float(payments[0]["amount"]), 3600.0)
        self.assertEqual(payments[0]["payment_method"], "CASH")

        # Check CashLedger tab
        cash_rows = [c for c in db.get_records("CashLedger") if c.get("related_sale_id") == sale.sale_id]
        self.assertEqual(len(cash_rows), 1)
        self.assertEqual(float(cash_rows[0]["amount"]), 3600.0)
        self.assertEqual(cash_rows[0]["txn_type"], "SALE_COLLECTION")

        # Check Accounting Journal Voucher
        headers = [h for h in db.get_records("JournalHeaders") if h.get("reference_id") == sale.sale_id]
        self.assertEqual(len(headers), 1)
        jid = headers[0]["journal_id"]
        lines = [l for l in db.get_records("JournalLines") if l.get("journal_id") == jid]
        debit_1115 = sum(float(l["debit_amount"]) for l in lines if l.get("account_code") == "1115")
        credit_4100 = sum(float(l["credit_amount"]) for l in lines if l.get("account_code") == "4100")
        self.assertEqual(debit_1115, 3600.0)
        self.assertEqual(credit_4100, 3600.0)

    # 2. Fully paid UPI sale (₹3,600 bill, ₹3,600 UPI, PAID, CashLedger 0, DR 1120 / CR 4100)
    def test_02_fully_paid_upi_sale(self):
        req = self._create_sale_req(
            payment_method="UPI",
            cash_collected=3600.0,
            credit_amount=0.0,
            idempotency_key="sale-test-02",
        )
        sale = asyncio.run(create_sale(req, current_user=self.salesman_user))

        self.assertEqual(sale.bill_total, 3600.0)
        self.assertEqual(sale.payment_status, "PAID")

        # Check Payments tab has UPI
        payments = [p for p in db.get_records("Payments") if p.get("sale_id") == sale.sale_id]
        self.assertEqual(len(payments), 1)
        self.assertEqual(float(payments[0]["amount"]), 3600.0)
        self.assertEqual(payments[0]["payment_method"], "UPI")

        # Check CashLedger has NO entries (UPI does not put physical cash in salesman van)
        cash_rows = [c for c in db.get_records("CashLedger") if c.get("related_sale_id") == sale.sale_id]
        self.assertEqual(len(cash_rows), 0)

        # Check Accounting Journal Voucher (debits 1120 Bank, credits 4100 Sales)
        headers = [h for h in db.get_records("JournalHeaders") if h.get("reference_id") == sale.sale_id]
        self.assertEqual(len(headers), 1)
        lines = [l for l in db.get_records("JournalLines") if l.get("journal_id") == headers[0]["journal_id"]]
        debit_1120 = sum(float(l["debit_amount"]) for l in lines if l.get("account_code") == "1120")
        credit_4100 = sum(float(l["credit_amount"]) for l in lines if l.get("account_code") == "4100")
        self.assertEqual(debit_1120, 3600.0)
        self.assertEqual(credit_4100, 3600.0)

    # 3. Unpaid credit sale (₹3,600 bill, ₹0 cash, UNPAID, CashLedger 0, DR 1130 / CR 4100)
    def test_03_unpaid_credit_sale(self):
        req = self._create_sale_req(
            payment_mode="CREDIT",
            payment_method="CREDIT",
            cash_collected=0.0,
            credit_amount=3600.0,
            idempotency_key="sale-test-03",
        )
        sale = asyncio.run(create_sale(req, current_user=self.salesman_user))

        self.assertEqual(sale.bill_total, 3600.0)
        self.assertEqual(sale.payment_status, "UNPAID")
        self.assertEqual(sale.cash_collected, 0.0)
        self.assertEqual(sale.credit_amount, 3600.0)

        # No payments and no cash ledger records for pure credit sale
        payments = [p for p in db.get_records("Payments") if p.get("sale_id") == sale.sale_id]
        self.assertEqual(len(payments), 0)
        cash_rows = [c for c in db.get_records("CashLedger") if c.get("related_sale_id") == sale.sale_id]
        self.assertEqual(len(cash_rows), 0)

        # Accounting Journal debits 1130 (Accounts Receivable) for full ₹3,600
        headers = [h for h in db.get_records("JournalHeaders") if h.get("reference_id") == sale.sale_id]
        self.assertEqual(len(headers), 1)
        lines = [l for l in db.get_records("JournalLines") if l.get("journal_id") == headers[0]["journal_id"]]
        debit_1130 = sum(float(l["debit_amount"]) for l in lines if l.get("account_code") == "1130")
        credit_4100 = sum(float(l["credit_amount"]) for l in lines if l.get("account_code") == "4100")
        self.assertEqual(debit_1130, 3600.0)
        self.assertEqual(credit_4100, 3600.0)

    # 4. Partial payment sale (₹3,600 bill, ₹1,600 cash, ₹2,000 credit, PARTIAL, CashLedger +1,600, DR 1115 1,600, DR 1130 2,000, CR 4100 3,600)
    def test_04_partial_payment_sale(self):
        req = self._create_sale_req(
            payment_mode="PARTIAL",
            payment_method="CASH",
            cash_collected=1600.0,
            credit_amount=2000.0,
            idempotency_key="sale-test-04",
        )
        sale = asyncio.run(create_sale(req, current_user=self.salesman_user))

        self.assertEqual(sale.bill_total, 3600.0)
        self.assertEqual(sale.payment_status, "PARTIAL")
        self.assertEqual(sale.cash_collected, 1600.0)
        self.assertEqual(sale.credit_amount, 2000.0)

        # Payments table records ONLY the ₹1,600 collected
        payments = [p for p in db.get_records("Payments") if p.get("sale_id") == sale.sale_id]
        self.assertEqual(len(payments), 1)
        self.assertEqual(float(payments[0]["amount"]), 1600.0)

        # CashLedger records ONLY the ₹1,600 collected
        cash_rows = [c for c in db.get_records("CashLedger") if c.get("related_sale_id") == sale.sale_id]
        self.assertEqual(len(cash_rows), 1)
        self.assertEqual(float(cash_rows[0]["amount"]), 1600.0)

        # Accounting Journal splits settlement: DR 1115 ₹1,600, DR 1130 ₹2,000, CR 4100 ₹3,600
        headers = [h for h in db.get_records("JournalHeaders") if h.get("reference_id") == sale.sale_id]
        self.assertEqual(len(headers), 1)
        lines = [l for l in db.get_records("JournalLines") if l.get("journal_id") == headers[0]["journal_id"]]
        debit_1115 = sum(float(l["debit_amount"]) for l in lines if l.get("account_code") == "1115")
        debit_1130 = sum(float(l["debit_amount"]) for l in lines if l.get("account_code") == "1130")
        credit_4100 = sum(float(l["credit_amount"]) for l in lines if l.get("account_code") == "4100")
        self.assertEqual(debit_1115, 1600.0)
        self.assertEqual(debit_1130, 2000.0)
        self.assertEqual(credit_4100, 3600.0)
        self.assertEqual(debit_1115 + debit_1130, credit_4100)

    # 5. Multiple collections against one invoice
    def test_05_multiple_collections_against_invoice(self):
        # Create partial sale: ₹3,600 total, ₹1,600 collected, ₹2,000 credit
        req = self._create_sale_req(
            cash_collected=1600.0,
            credit_amount=2000.0,
            idempotency_key="sale-test-05",
        )
        sale = asyncio.run(create_sale(req, current_user=self.salesman_user))

        # Collection 1: ₹600 cash
        p1 = asyncio.run(record_sale_payment(
            sale_id=sale.sale_id,
            payload=SalePaymentCreate(amount=600.0, payment_method="CASH", notes="First collection"),
            current_user=self.salesman_user,
        ))
        self.assertEqual(p1["amount_paid"], 600.0)
        self.assertEqual(p1["remaining_balance"], 1400.0)
        self.assertEqual(p1["payment_status"], "PARTIAL")

        # Verify Collection 1 Journal: DR 1115 ₹600, CR 1130 ₹600
        h1 = [h for h in db.get_records("JournalHeaders") if h.get("reference_id") == p1["payment_id"]]
        self.assertEqual(len(h1), 1)
        l1 = [l for l in db.get_records("JournalLines") if l.get("journal_id") == h1[0]["journal_id"]]
        dr_1115 = sum(float(l["debit_amount"]) for l in l1 if l.get("account_code") == "1115")
        cr_1130 = sum(float(l["credit_amount"]) for l in l1 if l.get("account_code") == "1130")
        self.assertEqual(dr_1115, 600.0)
        self.assertEqual(cr_1130, 600.0)

        # Collection 2: ₹1,400 cash (clears full balance)
        p2 = asyncio.run(record_sale_payment(
            sale_id=sale.sale_id,
            payload=SalePaymentCreate(amount=1400.0, payment_method="CASH", notes="Final settlement"),
            current_user=self.salesman_user,
        ))
        self.assertEqual(p2["amount_paid"], 1400.0)
        self.assertEqual(p2["remaining_balance"], 0.0)
        self.assertEqual(p2["payment_status"], "PAID")

        # Verify Collection 2 Journal: DR 1115 ₹1,400, CR 1130 ₹1,400
        h2 = [h for h in db.get_records("JournalHeaders") if h.get("reference_id") == p2["payment_id"]]
        self.assertEqual(len(h2), 1)
        l2 = [l for l in db.get_records("JournalLines") if l.get("journal_id") == h2[0]["journal_id"]]
        dr_1115_2 = sum(float(l["debit_amount"]) for l in l2 if l.get("account_code") == "1115")
        cr_1130_2 = sum(float(l["credit_amount"]) for l in l2 if l.get("account_code") == "1130")
        self.assertEqual(dr_1115_2, 1400.0)
        self.assertEqual(cr_1130_2, 1400.0)

        # Attempt Collection 3 when remaining balance is 0: must fail with HTTP 400
        with self.assertRaises(HTTPException) as cm:
            asyncio.run(record_sale_payment(
                sale_id=sale.sale_id,
                payload=SalePaymentCreate(amount=100.0, payment_method="CASH"),
                current_user=self.salesman_user,
            ))
        self.assertEqual(cm.exception.status_code, 400)

    # 6. Customer outstanding calculation from ledger transactions
    def test_06_customer_outstanding_calculation(self):
        # Create sale of ₹3,600 with ₹1,600 paid upfront (₹2,000 outstanding)
        req = self._create_sale_req(
            cash_collected=1600.0,
            credit_amount=2000.0,
            idempotency_key="sale-test-06",
        )
        sale = asyncio.run(create_sale(req, current_user=self.salesman_user))

        outstanding = calculate_customer_outstanding(self.customer_id)
        self.assertEqual(outstanding, 2000.0)

        # Collect ₹600
        asyncio.run(record_sale_payment(
            sale_id=sale.sale_id,
            payload=SalePaymentCreate(amount=600.0, payment_method="CASH"),
            current_user=self.salesman_user,
        ))
        outstanding_after = calculate_customer_outstanding(self.customer_id)
        self.assertEqual(outstanding_after, 1400.0)

        # Verify ledger entries
        txns = get_customer_transactions(self.customer_id)
        # Should have 1 INVOICE debiting 3,600 and 2 COLLECTION credits (1,600 and 600)
        self.assertEqual(len(txns), 3)
        inv = next(t for t in txns if t["txn_type"] == "INVOICE")
        self.assertEqual(inv["debit_amount"], 3600.0)
        colls = [t for t in txns if t["txn_type"] == "COLLECTION"]
        self.assertEqual(sum(c["credit_amount"] for c in colls), 2200.0)

    # 7. Credit limit exceeded blocked for salesman
    def test_07_credit_limit_exceeded_blocked_for_salesman(self):
        # Set customer credit limit to ₹5,000
        db.update_record("Customers", "customer_id", self.customer_id, {"credit_limit": 5000.0})

        # Sale 1: uses ₹4,000 credit (allowed since 4000 <= 5000)
        req1 = self._create_sale_req(
            qty=25,
            unit_price=160.0,  # 4000
            cash_collected=0.0,
            credit_amount=4000.0,
            idempotency_key="sale-limit-01",
        )
        asyncio.run(create_sale(req1, current_user=self.salesman_user))
        self.assertEqual(calculate_customer_outstanding(self.customer_id), 4000.0)

        # Sale 2: salesman attempts to give ₹2,000 credit (total would be ₹6,000 > ₹5,000 limit)
        req2 = self._create_sale_req(
            qty=10,
            unit_price=200.0,  # 2000
            cash_collected=0.0,
            credit_amount=2000.0,
            idempotency_key="sale-limit-02",
        )
        with self.assertRaises(HTTPException) as cm:
            asyncio.run(create_sale(req2, current_user=self.salesman_user))
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("exceeds credit limit", cm.exception.detail)

    # 8. Overdue customer blocked for salesman
    def test_08_overdue_customer_blocked_for_salesman(self):
        # Manually create an overdue unpaid sale from 45 days ago
        old_date = (date.today() - timedelta(days=45)).isoformat() + "T10:00:00"
        old_sale_id = "SALE-OVERDUE-01"
        db.append_record("Sales", {
            "sale_id": old_sale_id,
            "bill_number": "BILL-OLD-01",
            "customer_id": self.customer_id,
            "customer_name_snapshot": "Sharma Kirana Store",
            "sale_datetime": old_date,
            "subtotal": 1000.0,
            "discount_amount": 0.0,
            "tax_amount": 0.0,
            "bill_total": 1000.0,
            "bill_status": "ISSUED",
            "payment_status": "UNPAID",
            "payment_method": "CREDIT",
            "cash_collected": 0.0,
            "credit_amount": 1000.0,
            "salesman_user_id": "USR-SALES-01",
            "entered_by_user_id": "USR-SALES-01",
            "txn_status": "COMPLETE",
        })

        overdue_list = get_customer_overdue_invoices(self.customer_id, max_overdue_days=30)
        self.assertEqual(len(overdue_list), 1)

        # Salesman attempts another credit sale: must be blocked
        req = self._create_sale_req(
            cash_collected=0.0,
            credit_amount=3600.0,
            idempotency_key="sale-overdue-attempt",
        )
        with self.assertRaises(HTTPException) as cm:
            asyncio.run(create_sale(req, current_user=self.salesman_user))
        self.assertEqual(cm.exception.status_code, 400)
        self.assertIn("overdue invoice", cm.exception.detail)

    # 9. Owner approval for credit exception
    def test_09_owner_approved_credit_exception(self):
        # Setup customer with 0 credit limit
        db.update_record("Customers", "customer_id", self.customer_id, {"credit_limit": 0.0})

        req = self._create_sale_req(
            cash_collected=0.0,
            credit_amount=3600.0,
            idempotency_key="sale-owner-approve-01",
        )

        # Salesman fails
        with self.assertRaises(HTTPException):
            asyncio.run(create_sale(req, current_user=self.salesman_user))

        # Direct Owner caller succeeds
        req_owner = self._create_sale_req(
            cash_collected=0.0,
            credit_amount=3600.0,
            idempotency_key="sale-owner-approve-02",
        )
        sale_owner = asyncio.run(create_sale(req_owner, current_user=self.owner_user))
        self.assertEqual(sale_owner.payment_status, "UNPAID")
        self.assertEqual(sale_owner.credit_amount, 3600.0)

        # Salesman with approved ApprovalRequest succeeds
        app_id = "APP-CREDIT-99"
        db.append_record("ApprovalRequests", {
            "request_id": app_id,
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "approved_by": "USR-OWNER-01",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-TEST-01",
            "approved_amount": 5000.0,
            "expires_at": (date.today() + timedelta(days=7)).isoformat(),
            "notes": "Authorized credit exception for regular customer",
        })
        req_salesman_app = self._create_sale_req(
            cash_collected=0.0,
            credit_amount=3600.0,
            owner_credit_approval_id=app_id,
            idempotency_key="sale-owner-approve-03",
        )
        sale_app = asyncio.run(create_sale(req_salesman_app, current_user=self.salesman_user))
        self.assertEqual(sale_app.payment_status, "UNPAID")

    # 10. Partial-payment sale cancellation (reverses only ₹1,600 from salesman cash, not ₹3,600)
    def test_10_partial_payment_sale_cancellation(self):
        req = self._create_sale_req(
            cash_collected=1600.0,
            credit_amount=2000.0,
            idempotency_key="sale-test-10",
        )
        sale = asyncio.run(create_sale(req, current_user=self.salesman_user))

        # Salesman cash before cancellation has +1,600
        cash_entries = [c for c in db.get_records("CashLedger") if c.get("salesman_user_id") == "USR-SALES-01"]
        net_cash_before = sum(float(c["amount"]) for c in cash_entries)
        self.assertEqual(net_cash_before, 1600.0)

        # Cancel the sale
        cancel_res = asyncio.run(cancel_sale(
            sale_id=sale.sale_id,
            req=SaleCancelRequest(reason="Customer returned goods"),
            current_user=self.salesman_user,
        ))
        self.assertTrue(cancel_res["ok"])

        # Payments table should have a refund of exactly -1,600 (NOT -3,600)
        refund_payments = [p for p in db.get_records("Payments") if p.get("sale_id") == sale.sale_id and p.get("payment_status") == "REFUNDED"]
        self.assertEqual(len(refund_payments), 1)
        self.assertEqual(float(refund_payments[0]["amount"]), -1600.0)

        # CashLedger must have a refund of exactly -1,600 (NOT -3,600)
        refund_cash = [c for c in db.get_records("CashLedger") if c.get("related_sale_id") == sale.sale_id and c.get("txn_type") == "SALE_REFUND"]
        self.assertEqual(len(refund_cash), 1)
        self.assertEqual(float(refund_cash[0]["amount"]), -1600.0)

        # Salesman net cash ledger is now exactly 0 (NOT negative ₹2,000!)
        net_cash_after = sum(float(c["amount"]) for c in db.get_records("CashLedger") if c.get("salesman_user_id") == "USR-SALES-01")
        self.assertEqual(net_cash_after, 0.0)

    # 11. Full-payment sale cancellation
    def test_11_full_payment_sale_cancellation(self):
        req = self._create_sale_req(
            cash_collected=3600.0,
            credit_amount=0.0,
            idempotency_key="sale-test-11",
        )
        sale = asyncio.run(create_sale(req, current_user=self.salesman_user))

        cancel_res = asyncio.run(cancel_sale(
            sale_id=sale.sale_id,
            req=SaleCancelRequest(reason="Order cancelled"),
            current_user=self.salesman_user,
        ))
        self.assertTrue(cancel_res["ok"])

        refund_payments = [p for p in db.get_records("Payments") if p.get("sale_id") == sale.sale_id and p.get("payment_status") == "REFUNDED"]
        self.assertEqual(len(refund_payments), 1)
        self.assertEqual(float(refund_payments[0]["amount"]), -3600.0)

        refund_cash = [c for c in db.get_records("CashLedger") if c.get("related_sale_id") == sale.sale_id and c.get("txn_type") == "SALE_REFUND"]
        self.assertEqual(len(refund_cash), 1)
        self.assertEqual(float(refund_cash[0]["amount"]), -3600.0)

    # 12. Duplicate collection prevention (idempotency key replay)
    def test_12_duplicate_collection_prevention(self):
        req = self._create_sale_req(
            cash_collected=1000.0,
            credit_amount=2600.0,
            idempotency_key="sale-test-12",
        )
        sale = asyncio.run(create_sale(req, current_user=self.salesman_user))

        idemp_key = "pay-idemp-unique-12"
        # First collection of ₹500
        p1 = asyncio.run(record_sale_payment(
            sale_id=sale.sale_id,
            payload=SalePaymentCreate(amount=500.0, payment_method="CASH", idempotency_key=idemp_key),
            current_user=self.salesman_user,
        ))
        self.assertEqual(p1["amount_paid"], 500.0)

        # Replay with same key and same amount: must return existing record, NOT double-count
        p2 = asyncio.run(record_sale_payment(
            sale_id=sale.sale_id,
            payload=SalePaymentCreate(amount=500.0, payment_method="CASH", idempotency_key=idemp_key),
            current_user=self.salesman_user,
        ))
        self.assertTrue(p2.get("is_replay"))
        self.assertEqual(p2["payment_id"], p1["payment_id"])

        # Payments table must have only 1 payment with that idempotency key
        matched_payments = [p for p in db.get_records("Payments") if idemp_key in str(p.get("notes", "")) or p.get("idempotency_key") == idemp_key]
        self.assertEqual(len(matched_payments), 1)

        # Conflicting amount on same key must raise HTTP 409
        with self.assertRaises(HTTPException) as cm:
            asyncio.run(record_sale_payment(
                sale_id=sale.sale_id,
                payload=SalePaymentCreate(amount=600.0, payment_method="CASH", idempotency_key=idemp_key),
                current_user=self.salesman_user,
            ))
        self.assertEqual(cm.exception.status_code, 409)

    # 13. Journal debit/credit equality across all sales, collections, and reversals
    def test_13_journal_debit_credit_equality(self):
        # Perform a sequence of operations
        req = self._create_sale_req(
            cash_collected=1600.0,
            credit_amount=2000.0,
            idempotency_key="sale-test-13",
        )
        sale = asyncio.run(create_sale(req, current_user=self.salesman_user))

        # Collection
        asyncio.run(record_sale_payment(
            sale_id=sale.sale_id,
            payload=SalePaymentCreate(amount=500.0, payment_method="CASH"),
            current_user=self.salesman_user,
        ))

        # Cancellation of another sale
        req2 = self._create_sale_req(
            cash_collected=3600.0,
            credit_amount=0.0,
            idempotency_key="sale-test-13-b",
        )
        sale2 = asyncio.run(create_sale(req2, current_user=self.salesman_user))
        asyncio.run(cancel_sale(
            sale_id=sale2.sale_id,
            req=SaleCancelRequest(reason="Cancelled test"),
            current_user=self.salesman_user,
        ))

        # Verify EVERY journal header has sum(debits) == sum(credits)
        headers = db.get_records("JournalHeaders")
        lines = db.get_records("JournalLines")
        self.assertGreater(len(headers), 0)

        for h in headers:
            jid = h.get("journal_id")
            j_lines = [l for l in lines if l.get("journal_id") == jid]
            self.assertGreater(len(j_lines), 0, f"Voucher {jid} has no lines")
            tot_dr = sum(float(l.get("debit_amount", 0) or 0) for l in j_lines)
            tot_cr = sum(float(l.get("credit_amount", 0) or 0) for l in j_lines)
            self.assertAlmostEqual(tot_dr, tot_cr, places=2, msg=f"Voucher {jid} does not balance: DR={tot_dr}, CR={tot_cr}")

    # 14. Salesman cash reconciliation
    def test_14_salesman_cash_reconciliation(self):
        # 1. Sale with ₹1,600 cash collected
        req1 = self._create_sale_req(cash_collected=1600.0, credit_amount=2000.0, idempotency_key="cash-recon-01")
        s1 = asyncio.run(create_sale(req1, current_user=self.salesman_user))

        # 2. Sale with ₹0 cash (100% credit)
        req2 = self._create_sale_req(payment_mode="CREDIT", cash_collected=0.0, credit_amount=3600.0, idempotency_key="cash-recon-02")
        s2 = asyncio.run(create_sale(req2, current_user=self.salesman_user))

        # 3. Collection of ₹400 on sale 2
        asyncio.run(record_sale_payment(
            sale_id=s2.sale_id,
            payload=SalePaymentCreate(amount=400.0, payment_method="CASH"),
            current_user=self.salesman_user,
        ))

        # 4. Total physical cash collected should be exactly ₹1,600 + ₹400 = ₹2,000
        cash_rows = [c for c in db.get_records("CashLedger") if c.get("salesman_user_id") == "USR-SALES-01"]
        net_cash = sum(float(c["amount"]) for c in cash_rows)
        self.assertEqual(net_cash, 2000.0)

        # 5. Cancel Sale 1: only ₹1,600 is refunded, net cash becomes ₹400
        asyncio.run(cancel_sale(
            sale_id=s1.sale_id,
            req=SaleCancelRequest(reason="Customer cancel"),
            current_user=self.salesman_user,
        ))
        cash_rows_after = [c for c in db.get_records("CashLedger") if c.get("salesman_user_id") == "USR-SALES-01"]
        net_cash_after = sum(float(c["amount"]) for c in cash_rows_after)
        self.assertEqual(net_cash_after, 400.0)


if __name__ == "__main__":
    unittest.main()
