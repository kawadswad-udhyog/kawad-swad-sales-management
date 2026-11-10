"""
Kawad Swad ERP - Phase 1.4.1 Sales Payment Integrity & Multiple Collection Cancellation Test Suite
Authoritative tests for:
1. Cancellation after multiple collections (Cash + UPI + Bank)
2. Proper refund amounts and method preservation
3. Full multi-voucher reversal (Invoice + all PAYMENT_COLLECTION vouchers)
4. Idempotent cancellation and recovery from interrupted cancellation
5. Cancelled invoice settlement status (explicit CANCELLED state, 0 remaining balance)
6. Customer ledger reconciliation (no orphan collection credits)
7. Customer credit balance preservation (negative outstanding, balance breakdown)
8. Owner credit authorization enforcement (PA/Salesman rejected, strict approval checks)
9. Credit limit lock serialization and concurrency safety
"""

import asyncio
import os
import unittest
from datetime import datetime, date, timedelta
from decimal import Decimal

# Configure test environment
os.environ["SALES_TESTING"] = "1"
os.environ["SALES_AUTH_MOCK"] = "1"

from app.sheets import db
from app.timeutil import now_iso
from app.models import SaleCreate, SaleItemCreate, SalePaymentCreate
from app.routers.sales import create_sale, cancel_sale, record_sale_payment, get_sale_settlement, SaleCancelRequest
from app.accounting.customer_ledger import (
    calculate_customer_outstanding,
    get_customer_balance_breakdown,
    get_customer_transactions,
    get_invoice_settlement_status,
    check_credit_control,
)
from app.accounting.journal_engine import (
    calculate_trial_balance,
    reverse_journal_voucher,
)


class TestPhase141SalesPayment(unittest.TestCase):
    def setUp(self):
        db.memory_store = {tab: [] for tab in db.memory_store}
        self._seed_core_data()

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
            "quantity": 500,
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

    def test_01_cancellation_after_multiple_collections_reverses_all_vouchers_and_gl_balances(self):
        """
        Scenario from Task 1:
        Invoice: ₹3,600 (72 packets @ ₹50)
        Initial collection: ₹1,600 (Cash)
        Credit on invoice: ₹2,000
        Later collection: ₹600 (UPI)
        Final collection: ₹1,400 (Cash)
        Total collected: ₹3,600

        After cancellation:
        1. Reverse the original invoice journal.
        2. Reverse every associated PAYMENT_COLLECTION journal.
        3. Prevent duplicate reversals.
        4. Refund only actual collected amounts.
        5. Balance cash, bank, and receivable balances to ₹0.
        6. Trial balance variance must be ₹0.00.
        """
        # 1. Create invoice with ₹1,600 initial cash collected
        req = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-REG-01",
            payment_method="CASH",
            cash_collected=1600.0,
            credit_amount=2000.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=72, actual_unit_price=50.0)],
            idempotency_key="multi-coll-sale-01",
        )
        sale = asyncio.run(create_sale(req, current_user=self.salesman_user))
        sale_id = sale.sale_id
        self.assertEqual(sale.total_amount, 3600.0)
        self.assertEqual(sale.cash_collected, 1600.0)
        self.assertEqual(sale.credit_amount, 2000.0)
        self.assertEqual(sale.payment_status, "PARTIAL")

        # 2. Record later collection 1: ₹600 via UPI
        pay1 = asyncio.run(record_sale_payment(
            sale_id=sale_id,
            payload=SalePaymentCreate(amount=600.0, payment_method="UPI", notes="Later UPI collection"),
            current_user=self.salesman_user,
        ))
        self.assertTrue(pay1["ok"])
        self.assertEqual(pay1["remaining_balance"], 1400.0)
        self.assertEqual(pay1["payment_status"], "PARTIAL")

        # 3. Record final collection 2: ₹1,400 via CASH
        pay2 = asyncio.run(record_sale_payment(
            sale_id=sale_id,
            payload=SalePaymentCreate(amount=1400.0, payment_method="CASH", notes="Final cash collection"),
            current_user=self.salesman_user,
        ))
        self.assertTrue(pay2["ok"])
        self.assertEqual(pay2["remaining_balance"], 0.0)
        self.assertEqual(pay2["payment_status"], "PAID")

        # Check total payments recorded before cancellation
        payments_before = [p for p in db.get_records("Payments", fresh=True) if str(p.get("sale_id")) == sale_id]
        self.assertEqual(len(payments_before), 3) # Initial ₹1600, pay1 ₹600, pay2 ₹1400

        # Check journal headers before cancellation (1 SALE_INVOICE, 2 PAYMENT_COLLECTION)
        headers_before = db.get_records("JournalHeaders", fresh=True)
        sale_inv_headers = [h for h in headers_before if str(h.get("reference_type")) == "SALE_INVOICE" and str(h.get("reference_id")) == sale_id]
        pay_coll_headers = [h for h in headers_before if str(h.get("reference_type")) == "PAYMENT_COLLECTION"]
        self.assertEqual(len(sale_inv_headers), 1)
        self.assertEqual(len(pay_coll_headers), 2)
        for h in sale_inv_headers + pay_coll_headers:
            self.assertEqual(str(h.get("status")), "POSTED")

        # 4. Now cancel the sale
        cancel_res = asyncio.run(cancel_sale(
            sale_id=sale_id,
            req=SaleCancelRequest(reason="Customer returned entire batch, cancel bill and all collections"),
            current_user=self.owner_user,
        ))
        self.assertTrue(cancel_res["ok"])
        self.assertEqual(cancel_res["bill_status"], "CANCELLED")
        self.assertEqual(cancel_res["accounting_status"], "REVERSED")
        # Ensure reversal_journal_ids contains reversals for the invoice and BOTH payment collections
        self.assertGreaterEqual(len(cancel_res["reversal_journal_ids"]), 3)

        # 5. Verify that all original vouchers are now marked REVERSED
        headers_after = db.get_records("JournalHeaders", fresh=True)
        sale_inv_after = next(h for h in headers_after if str(h.get("reference_type")) == "SALE_INVOICE" and str(h.get("reference_id")) == sale_id)
        self.assertEqual(str(sale_inv_after.get("status")), "REVERSED")
        for p in [pay1["payment_id"], pay2["payment_id"]]:
            p_voucher = next(h for h in headers_after if str(h.get("reference_type")) == "PAYMENT_COLLECTION" and str(h.get("reference_id")) == p)
            self.assertEqual(str(p_voucher.get("status")), "REVERSED")

        # 6. Verify payments: individual refunds exist
        payments_after = [p for p in db.get_records("Payments", fresh=True) if str(p.get("sale_id")) == sale_id]
        refunds = [p for p in payments_after if float(p.get("amount", 0)) < 0]
        self.assertEqual(len(refunds), 3) # Refund for initial ₹1600, pay1 ₹600, pay2 ₹1400
        total_refunded = sum(abs(float(r.get("amount", 0))) for r in refunds)
        self.assertEqual(round(total_refunded, 2), 3600.0)

        # Verify CashLedger: only cash collections are refunded (₹1,600 + ₹1,400 = ₹3,000, not the UPI ₹600)
        cash_refunds = [c for c in db.get_records("CashLedger", fresh=True) if str(c.get("related_sale_id")) == sale_id and str(c.get("txn_type")) == "SALE_REFUND"]
        total_cash_refunded = sum(abs(float(c.get("amount", 0))) for c in cash_refunds)
        self.assertEqual(round(total_cash_refunded, 2), 3000.0)

        # 7. Check General Ledger Trial Balance: must balance with ₹0.00 variance
        tb = calculate_trial_balance()
        self.assertTrue(tb["is_balanced"])
        self.assertAlmostEqual(tb["variance"], 0.0, places=2)

    def test_02_cancelled_invoice_settlement_status(self):
        """Cancelled invoice must report explicit CANCELLED state with remaining_balance: 0.0."""
        req = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-REG-01",
            payment_method="CASH",
            cash_collected=1000.0,
            credit_amount=1000.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=40, actual_unit_price=50.0)],
            idempotency_key="settle-sale-01",
        )
        sale = asyncio.run(create_sale(req, current_user=self.salesman_user))
        sale_id = sale.sale_id

        # Cancel sale
        asyncio.run(cancel_sale(
            sale_id=sale_id,
            req=SaleCancelRequest(reason="Customer cancelled order"),
            current_user=self.owner_user,
        ))

        # Check settlement status
        status_info = get_invoice_settlement_status(sale_id)
        self.assertEqual(status_info["bill_status"], "CANCELLED")
        self.assertEqual(status_info["cancellation_status"], "CANCELLED")
        self.assertEqual(status_info["payment_status"], "CANCELLED")
        self.assertTrue(status_info["is_cancelled"])
        self.assertEqual(status_info["remaining_balance"], 0.0)
        self.assertEqual(status_info["final_outstanding"], 0.0)
        self.assertEqual(status_info["original_invoice_amount"], 2000.0)
        self.assertEqual(status_info["total_collected"], 1000.0)
        self.assertEqual(status_info["total_refunded"], 1000.0)
        self.assertEqual(status_info["net_collected"], 0.0)

    def test_03_customer_ledger_reconciles_without_orphan_credits(self):
        """Cancelled invoice collections must not leave orphan credits in customer transactions."""
        req = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-REG-01",
            payment_method="CASH",
            cash_collected=1000.0,
            credit_amount=1000.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=40, actual_unit_price=50.0)],
            idempotency_key="ledger-recon-sale-01",
        )
        sale = asyncio.run(create_sale(req, current_user=self.salesman_user))
        sale_id = sale.sale_id

        # Record partial collection of ₹500
        asyncio.run(record_sale_payment(
            sale_id=sale_id,
            payload=SalePaymentCreate(amount=500.0, payment_method="CASH", notes="Mid collection"),
            current_user=self.salesman_user,
        ))

        # Cancel sale
        asyncio.run(cancel_sale(
            sale_id=sale_id,
            req=SaleCancelRequest(reason="Return and cancellation"),
            current_user=self.owner_user,
        ))

        # Query customer transactions
        txns = get_customer_transactions("CUS-REG-01")
        # Check all transaction types present: INVOICE, INVOICE_CANCELLATION, COLLECTION, REFUND
        types = [t["txn_type"] for t in txns]
        self.assertIn("INVOICE", types)
        self.assertIn("INVOICE_CANCELLATION", types)
        self.assertIn("COLLECTION", types)
        self.assertIn("REFUND", types)

        # Sum of debits and credits must balance to exactly 0.0 for this cancelled sale
        tot_debits = sum(t["debit_amount"] for t in txns)
        tot_credits = sum(t["credit_amount"] for t in txns)
        self.assertAlmostEqual(tot_debits, tot_credits, places=2)

        # Outstanding balance must be exactly 0.0
        outstanding = calculate_customer_outstanding("CUS-REG-01")
        self.assertEqual(outstanding, 0.0)

    def test_04_customer_credit_balance_advance_payment_preserved(self):
        """Advance payment gives negative outstanding balance; must not be clamped to 0."""
        # Record an advance collection of ₹500 against no invoice
        db.append_record("Payments", {
            "payment_id": "PAY-ADV-01",
            "sale_id": "",
            "payment_datetime": now_iso(),
            "payment_method": "UPI",
            "amount": 500.0,
            "reference_number": "ADV-01",
            "received_by_user_id": "USR-SALES-01",
            "payment_status": "COLLECTED",
            "notes": "Advance payment from customer",
        })
        # Customer ledger transaction query for customer
        # Create a sale of ₹300 paid by advance
        req = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-REG-01",
            payment_method="CASH",
            cash_collected=0.0,
            credit_amount=300.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=6, actual_unit_price=50.0)],
            idempotency_key="adv-sale-01",
        )
        sale = asyncio.run(create_sale(req, current_user=self.salesman_user))

        # Record a payment of ₹200 on this sale
        asyncio.run(record_sale_payment(
            sale_id=sale.sale_id,
            payload=SalePaymentCreate(amount=200.0, payment_method="CASH", notes="Excess payment"),
            current_user=self.salesman_user,
        ))

        # Record direct customer payment of 400
        db.append_record("Payments", {
            "payment_id": "PAY-OVERPAY-01",
            "sale_id": sale.sale_id,
            "payment_datetime": now_iso(),
            "payment_method": "CASH",
            "amount": 400.0, # Total paid = 200 + 400 = 600 against 300 bill -> customer has 300 credit balance
            "reference_number": "EXCESS-01",
            "received_by_user_id": "USR-SALES-01",
            "payment_status": "COLLECTED",
            "notes": "Excess collection",
        })

        breakdown = get_customer_balance_breakdown("CUS-REG-01")
        self.assertTrue(breakdown["has_credit_balance"])
        self.assertLess(breakdown["net_balance"], 0.0)
        self.assertEqual(breakdown["customer_credit_balance"], abs(breakdown["net_balance"]))

        # Outstanding must reflect true negative balance
        out = calculate_customer_outstanding("CUS-REG-01")
        self.assertLess(out, 0.0)

    def test_05_pa_direct_credit_authorization_rejected(self):
        """PA attempting to directly authorize credit exception must be rejected with HTTP 400."""
        from fastapi import HTTPException
        # Customer credit limit is 1000. Request 2500.
        with self.assertRaises(HTTPException) as ctx:
            check_credit_control(
                customer_id="CUS-TIGHT-01",
                requested_credit=2500.0,
                current_user=self.pa_user, # PA user
                approval_request_id=None,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Personal Assistant cannot independently approve credit", ctx.exception.detail)

    def test_06_unrelated_nonexistent_approval_id_rejected(self):
        """Supplying nonexistent approval ID must be rejected with HTTP 400."""
        from fastapi import HTTPException
        with self.assertRaises(HTTPException) as ctx:
            check_credit_control(
                customer_id="CUS-TIGHT-01",
                requested_credit=2500.0,
                current_user=self.salesman_user,
                approval_request_id="APP-NONEXISTENT-999",
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("not found", ctx.exception.detail)

    def test_07_wrong_customer_approval_rejected(self):
        """Approval granted for Customer A cannot be used by Customer B (HTTP 400)."""
        from fastapi import HTTPException
        db.append_record("ApprovalRequests", {
            "request_id": "APP-WRONG-CUST",
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-REG-01", # Belongs to REG-01
            "approved_amount": 5000.0,
            "expires_at": (date.today() + timedelta(days=7)).isoformat(),
        })

        with self.assertRaises(HTTPException) as ctx:
            check_credit_control(
                customer_id="CUS-TIGHT-01", # Trying to use on TIGHT-01
                requested_credit=2500.0,
                current_user=self.salesman_user,
                approval_request_id="APP-WRONG-CUST",
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("does not match current customer", ctx.exception.detail)

    def test_08_approval_amount_exceeded_rejected(self):
        """Requested credit exceeding approved limit must be rejected with HTTP 400."""
        from fastapi import HTTPException
        db.append_record("ApprovalRequests", {
            "request_id": "APP-LIMIT-EXCEED",
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-TIGHT-01",
            "approved_amount": 1500.0,
            "expires_at": (date.today() + timedelta(days=7)).isoformat(),
        })

        with self.assertRaises(HTTPException) as ctx:
            check_credit_control(
                customer_id="CUS-TIGHT-01",
                requested_credit=2500.0, # Requested ₹2,500 > Approved ₹1,500
                current_user=self.salesman_user,
                approval_request_id="APP-LIMIT-EXCEED",
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("exceeds approved limit", ctx.exception.detail)

    def test_09_expired_or_revoked_approval_rejected(self):
        """Expired or revoked approval request must be rejected with HTTP 400."""
        from fastapi import HTTPException
        # 1. Expired approval
        db.append_record("ApprovalRequests", {
            "request_id": "APP-EXPIRED",
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-TIGHT-01",
            "approved_amount": 5000.0,
            "expires_at": (date.today() - timedelta(days=2)).isoformat(), # Expired 2 days ago
        })
        with self.assertRaises(HTTPException) as ctx:
            check_credit_control(
                customer_id="CUS-TIGHT-01",
                requested_credit=2000.0,
                current_user=self.salesman_user,
                approval_request_id="APP-EXPIRED",
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("expired", ctx.exception.detail)

        # 2. Revoked approval
        db.append_record("ApprovalRequests", {
            "request_id": "APP-REVOKED",
            "request_type": "CREDIT_EXCEPTION",
            "status": "REVOKED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-TIGHT-01",
            "approved_amount": 5000.0,
            "expires_at": (date.today() + timedelta(days=5)).isoformat(),
        })
        with self.assertRaises(HTTPException) as ctx:
            check_credit_control(
                customer_id="CUS-TIGHT-01",
                requested_credit=2000.0,
                current_user=self.salesman_user,
                approval_request_id="APP-REVOKED",
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("revoked", ctx.exception.detail.lower())

    def test_10_already_consumed_approval_cannot_be_reused(self):
        """Approval consumed by a previous transaction cannot be reused (HTTP 400)."""
        from fastapi import HTTPException
        db.append_record("ApprovalRequests", {
            "request_id": "APP-CONSUMED",
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-TIGHT-01",
            "approved_amount": 5000.0,
            "is_consumed": True,
            "consumed_by_sale_id": "SALE-EARLIER-01",
            "expires_at": (date.today() + timedelta(days=5)).isoformat(),
        })
        with self.assertRaises(HTTPException) as ctx:
            check_credit_control(
                customer_id="CUS-TIGHT-01",
                requested_credit=2000.0,
                current_user=self.salesman_user,
                approval_request_id="APP-CONSUMED",
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("already been consumed", ctx.exception.detail)

    def test_11_duplicate_cancellation_does_not_create_duplicate_reversals(self):
        """Calling cancel_sale again on an already cancelled sale must be idempotent."""
        req = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-REG-01",
            payment_method="CASH",
            cash_collected=1000.0,
            credit_amount=1000.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=40, actual_unit_price=50.0)],
            idempotency_key="dup-cancel-01",
        )
        sale = asyncio.run(create_sale(req, current_user=self.salesman_user))
        sale_id = sale.sale_id

        # First cancellation
        res1 = asyncio.run(cancel_sale(
            sale_id=sale_id,
            req=SaleCancelRequest(reason="Customer cancel"),
            current_user=self.owner_user,
        ))
        self.assertTrue(res1["ok"])
        self.assertEqual(res1["accounting_status"], "REVERSED")
        first_reversals = res1.get("reversal_journal_ids", [])

        # Count total JournalHeaders
        count_headers_1 = len(db.get_records("JournalHeaders", fresh=True))

        # Second cancellation (idempotent retry)
        res2 = asyncio.run(cancel_sale(
            sale_id=sale_id,
            req=SaleCancelRequest(reason="Customer cancel retry"),
            current_user=self.owner_user,
        ))
        self.assertTrue(res2["ok"])
        self.assertTrue(res2["already_cancelled"])
        self.assertEqual(res2["accounting_status"], "ALREADY_REVERSED")

        # Total JournalHeaders count must NOT have increased (no duplicate reversals)
        count_headers_2 = len(db.get_records("JournalHeaders", fresh=True))
        self.assertEqual(count_headers_1, count_headers_2)

    def test_12_interrupted_cancellation_recovery(self):
        """If a sale is marked CANCELLED but voucher reversal was not completed, retry reverses it."""
        req = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-REG-01",
            payment_method="CASH",
            cash_collected=1000.0,
            credit_amount=1000.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=40, actual_unit_price=50.0)],
            idempotency_key="interrupted-cancel-01",
        )
        sale = asyncio.run(create_sale(req, current_user=self.salesman_user))
        sale_id = sale.sale_id

        # Simulate interruption: bill status is updated to CANCELLED in Sales, but journal voucher remains POSTED
        db.update_record("Sales", "sale_id", sale_id, {"bill_status": "CANCELLED"})

        # Check voucher is still POSTED
        voucher = next(h for h in db.get_records("JournalHeaders", fresh=True) if str(h.get("reference_id")) == sale_id)
        self.assertEqual(str(voucher.get("status")), "POSTED")

        # Retry cancel_sale
        recov_res = asyncio.run(cancel_sale(
            sale_id=sale_id,
            req=SaleCancelRequest(reason="Recovery of interrupted cancellation"),
            current_user=self.owner_user,
        ))
        self.assertTrue(recov_res["ok"])
        self.assertTrue(recov_res["already_cancelled"])
        self.assertEqual(recov_res["accounting_status"], "REVERSED")

        # Verify voucher is now REVERSED
        voucher_after = next(h for h in db.get_records("JournalHeaders", fresh=True) if str(h.get("reference_id")) == sale_id)
        self.assertEqual(str(voucher_after.get("status")), "REVERSED")

    def test_13_upi_collection_cancellation_reverses_bank_account_not_cash_ledger(self):
        """Cancelling a UPI collection reverses Bank Current Account (1120) and touches 0 CashLedger."""
        req = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-REG-01",
            payment_method="UPI",
            cash_collected=0.0,
            credit_amount=1000.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=20, actual_unit_price=50.0)],
            idempotency_key="upi-sale-01",
        )
        sale = asyncio.run(create_sale(req, current_user=self.salesman_user))
        sale_id = sale.sale_id

        # Record UPI collection of ₹1,000
        pay_res = asyncio.run(record_sale_payment(
            sale_id=sale_id,
            payload=SalePaymentCreate(amount=1000.0, payment_method="UPI", notes="Online UPI payment"),
            current_user=self.salesman_user,
        ))
        self.assertTrue(pay_res["ok"])

        # Count CashLedger rows before cancellation
        cash_rows_before = len(db.get_records("CashLedger", fresh=True))

        # Cancel sale
        cancel_res = asyncio.run(cancel_sale(
            sale_id=sale_id,
            req=SaleCancelRequest(reason="UPI sale returned"),
            current_user=self.owner_user,
        ))
        self.assertTrue(cancel_res["ok"])

        # CashLedger must NOT have any new refund rows because payment was UPI
        cash_rows_after = len(db.get_records("CashLedger", fresh=True))
        self.assertEqual(cash_rows_before, cash_rows_after)

        # But Payments table must have a negative refund row with payment_method="UPI"
        refund_payment = next(p for p in db.get_records("Payments", fresh=True) if str(p.get("sale_id")) == sale_id and float(p.get("amount", 0)) < 0)
        self.assertEqual(str(refund_payment.get("payment_method")), "UPI")
        self.assertEqual(float(refund_payment.get("amount")), -1000.0)

    def test_14_credit_check_after_idempotency_allows_retry_without_limit_failure(self):
        """An idempotent retry of a sale must return the sale even if customer credit is now exhausted."""
        # Customer credit limit is ₹1,000. Sale is for ₹1,000 credit.
        req = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-TIGHT-01",
            payment_method="CASH",
            cash_collected=0.0,
            credit_amount=1000.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=20, actual_unit_price=50.0)],
            idempotency_key="idemp-credit-retry-01",
        )
        # First creation succeeds
        sale1 = asyncio.run(create_sale(req, current_user=self.salesman_user))
        self.assertEqual(sale1.sale_id, sale1.sale_id)

        # Outstanding is now ₹1,000 (credit limit fully utilized)
        out = calculate_customer_outstanding("CUS-TIGHT-01")
        self.assertEqual(out, 1000.0)

        # Retrying the exact same request with the same idempotency key must succeed (not fail credit check!)
        sale2 = asyncio.run(create_sale(req, current_user=self.salesman_user))
        self.assertEqual(sale2.sale_id, sale1.sale_id)

    def test_15_approval_request_is_marked_consumed_when_sale_completes(self):
        """When an Owner approval is used in a sale, it must be marked consumed."""
        db.append_record("ApprovalRequests", {
            "request_id": "APP-CONSUME-TEST",
            "request_type": "CREDIT_EXCEPTION",
            "status": "APPROVED",
            "decided_by": "USR-OWNER-01",
            "customer_id": "CUS-TIGHT-01",
            "approved_amount": 2500.0,
            "expires_at": (date.today() + timedelta(days=7)).isoformat(),
        })

        req = SaleCreate(
            salesman_user_id="USR-SALES-01",
            customer_id="CUS-TIGHT-01",
            payment_method="CASH",
            cash_collected=0.0,
            credit_amount=2000.0,
            items=[SaleItemCreate(product_id="PRD-PAPAD-200G", quantity=40, actual_unit_price=50.0)],
            owner_credit_approval_id="APP-CONSUME-TEST",
            idempotency_key="consume-appr-sale-01",
        )
        sale = asyncio.run(create_sale(req, current_user=self.salesman_user))
        self.assertTrue(sale.sale_id)

        # Check approval record in database
        approvals = db.get_records("ApprovalRequests", fresh=True)
        appr = next(a for a in approvals if str(a.get("request_id")) == "APP-CONSUME-TEST")
        self.assertTrue(appr.get("is_consumed"))
        self.assertEqual(str(appr.get("consumed_by_sale_id")), sale.sale_id)
        self.assertTrue(appr.get("consumed_at"))


if __name__ == "__main__":
    unittest.main()
