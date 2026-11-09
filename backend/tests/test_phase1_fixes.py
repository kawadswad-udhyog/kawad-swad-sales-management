"""
Automated Regression Test Suite for Phase 1 Fixes in Kawad Swad ERP.

Covers:
1. SEC-01: Sales Cancellation Accounting Reversal & Idempotency
2. SEC-02: Payroll Monthly Sales Incentive Calculation & Filtering
3. BUG-01: Packaging Accounting Float/Decimal Normalization & Parity
4. ACC-01: Expense & Daily Closing Schema Synchronization & Single Deduction
"""

import os
import sys
import json
import asyncio
import unittest
from decimal import Decimal

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.sheets import db
from app.routers.sales import cancel_sale, SaleCancelRequest
from app.routers.workforce import calculate_payroll_run, PayrollRunCreate
from app.accounting.postings import post_sale_journal, post_packaging_batch_journal
from app.accounting.journal_engine import reverse_journal_voucher
from app.routers.closing import submit_daily_closing, DailyClosingCreate
from app.routers.expenses import submit_expense, review_expense, list_expenses, ExpenseCreate, ExpenseApproveRequest


class TestPhase1Fixes(unittest.TestCase):
    def setUp(self):
        # Reset memory store
        db.memory_store = {tab: [] for tab in db.memory_store}

        # Setup standard test users
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

    # =========================================================================
    # FIX 01: SEC-01 — Sales Cancellation Accounting Reversal
    # =========================================================================

    def test_sec_01_sales_cancellation_reverses_journal_voucher(self):
        """SEC-01: Sales cancellation locates original journal and generates compensating reversal."""
        sale_id = "SALE-101"
        bill_no = "BILL-101"

        db.append_record("Sales", {
            "sale_id": sale_id,
            "bill_number": bill_no,
            "sale_datetime": "2026-11-05T10:30:00",
            "customer_id": "CUST-001",
            "customer_name_snapshot": "Test Retailer",
            "salesman_user_id": self.salesman_user["user_id"],
            "bill_total": 5000.0,
            "final_amount": 5000.0,
            "payment_method": "CASH",
            "bill_status": "COMPLETED",
            "payment_status": "PAID",
            "delivery_status": "DELIVERED",
        })

        # Post original sales journal
        sale_data = {
            "sale_id": sale_id,
            "bill_number": bill_no,
            "bill_total": 5000.0,
            "customer_name_snapshot": "Test Retailer",
            "payment_method": "CASH",
            "sale_datetime": "2026-11-05",
        }
        orig_journal = post_sale_journal(sale_data, estimated_cogs=Decimal("3500.00"), actor=self.salesman_user["user_id"])
        orig_jid = orig_journal["journal_id"]

        # Verify original journal is POSTED
        headers = db.get_records("JournalHeaders")
        h_orig = next(h for h in headers if h["journal_id"] == orig_jid)
        self.assertEqual(h_orig["status"], "POSTED")

        # Cancel the sale
        cancel_req = SaleCancelRequest(reason="Customer requested order cancellation")
        res = asyncio.run(cancel_sale(sale_id, cancel_req, current_user=self.owner_user))
        self.assertTrue(res.get("ok"))

        # Verify original journal is now marked REVERSED
        headers_after = db.get_records("JournalHeaders")
        h_orig_after = next(h for h in headers_after if h["journal_id"] == orig_jid)
        self.assertEqual(h_orig_after["status"], "REVERSED")

        # Verify compensating reversal voucher exists
        rev_headers = [h for h in headers_after if h.get("voucher_type") == "REVERSAL" and h.get("reference_id") == orig_jid]
        self.assertEqual(len(rev_headers), 1)
        rev_h = rev_headers[0]
        self.assertEqual(rev_h["status"], "POSTED")

        # Verify lines are inverted
        orig_lines = [l for l in db.get_records("JournalLines") if l["journal_id"] == orig_jid]
        rev_lines = [l for l in db.get_records("JournalLines") if l["journal_id"] == rev_h["journal_id"]]
        self.assertEqual(len(orig_lines), len(rev_lines))
        self.assertEqual(Decimal(str(rev_h["total_debit"])), Decimal(str(h_orig["total_credit"])))
        self.assertEqual(Decimal(str(rev_h["total_credit"])), Decimal(str(h_orig["total_debit"])))

    def test_sec_01_sales_cancellation_idempotent_no_duplicate_reversal(self):
        """SEC-01: Retrying cancellation on an already cancelled sale does not create duplicate reversal vouchers."""
        sale_id = "SALE-102"
        bill_no = "BILL-102"

        db.append_record("Sales", {
            "sale_id": sale_id,
            "bill_number": bill_no,
            "sale_datetime": "2026-11-05T11:00:00",
            "salesman_user_id": self.salesman_user["user_id"],
            "bill_total": 2000.0,
            "bill_status": "COMPLETED",
        })

        sale_data = {
            "sale_id": sale_id,
            "bill_number": bill_no,
            "bill_total": 2000.0,
            "payment_method": "CASH",
            "sale_datetime": "2026-11-05",
        }
        orig_journal = post_sale_journal(sale_data, estimated_cogs=Decimal("1200.00"), actor=self.salesman_user["user_id"])
        orig_jid = orig_journal["journal_id"]

        # First cancellation
        cancel_req = SaleCancelRequest(reason="Accidental duplicate entry")
        res1 = asyncio.run(cancel_sale(sale_id, cancel_req, current_user=self.owner_user))
        self.assertTrue(res1.get("ok"))

        rev_count_1 = len([h for h in db.get_records("JournalHeaders") if h.get("voucher_type") == "REVERSAL" and h.get("reference_id") == orig_jid])
        self.assertEqual(rev_count_1, 1)

        # Second cancellation retry
        res2 = asyncio.run(cancel_sale(sale_id, cancel_req, current_user=self.owner_user))
        self.assertTrue(res2.get("ok"))
        self.assertTrue(res2.get("already_cancelled"))

        rev_count_2 = len([h for h in db.get_records("JournalHeaders") if h.get("voucher_type") == "REVERSAL" and h.get("reference_id") == orig_jid])
        self.assertEqual(rev_count_1, rev_count_2)

    # =========================================================================
    # FIX 02: SEC-02 — Payroll Sales Incentive Calculation
    # =========================================================================

    def test_sec_02_payroll_sales_incentive_calculation(self):
        """SEC-02: Payroll calculation recognizes sale_datetime and awards sales incentives."""
        emp_uid = self.salesman_user["user_id"]

        # Setup salary structure: basic 15000, 2% commission
        db.append_record("SalaryStructures", {
            "user_id": emp_uid,
            "employee_id": emp_uid,
            "basic_salary": 15000.0,
            "hra": 3000.0,
            "transport_allowance": 2000.0,
            "special_allowance": 0.0,
            "sales_commission_rate": 2.0,  # 2%
            "pf_deduction": 0.0,
            "tds_deduction": 0.0,
            "other_deductions": 0.0,
        })

        # Seed qualifying sales in November 2026
        db.append_record("Sales", {
            "sale_id": "SALE-NOV-01",
            "bill_number": "B-NOV-01",
            "salesman_user_id": emp_uid,
            "sale_datetime": "2026-11-04T14:30:00",
            "final_amount": 50000.0,
            "bill_total": 50000.0,
            "bill_status": "COMPLETED",
            "payment_status": "PAID",
            "delivery_status": "DELIVERED",
        })
        db.append_record("Sales", {
            "sale_id": "SALE-NOV-02",
            "bill_number": "B-NOV-02",
            "salesman_user_id": emp_uid,
            "sale_datetime": "2026-11-12T11:15:00",
            "final_amount": 30000.0,
            "bill_total": 30000.0,
            "bill_status": "COMPLETED",
            "payment_status": "PAID",
            "delivery_status": "DELIVERED",
        })

        # Seed a cancelled sale in November (must be excluded)
        db.append_record("Sales", {
            "sale_id": "SALE-NOV-CAN",
            "bill_number": "B-NOV-CAN",
            "salesman_user_id": emp_uid,
            "sale_datetime": "2026-11-15T09:00:00",
            "final_amount": 20000.0,
            "bill_total": 20000.0,
            "bill_status": "CANCELLED",
            "payment_status": "PAID",
            "delivery_status": "DELIVERED",
        })

        # Seed an October sale (must be excluded from Nov payroll)
        db.append_record("Sales", {
            "sale_id": "SALE-OCT-01",
            "bill_number": "B-OCT-01",
            "salesman_user_id": emp_uid,
            "sale_datetime": "2026-10-25T16:00:00",
            "final_amount": 40000.0,
            "bill_total": 40000.0,
            "bill_status": "COMPLETED",
            "payment_status": "PAID",
            "delivery_status": "DELIVERED",
        })

        # Calculate payroll for November 2026
        req = PayrollRunCreate(month="2026-11", days_in_month=30)
        res = asyncio.run(calculate_payroll_run(req, current_user=self.owner_user))

        items = res.get("items", [])
        emp_item = next(i for i in items if i["employee_id"] == emp_uid)

        # Expected sales = 50000 + 30000 = 80000. Commission @ 2% = 1600.00
        self.assertEqual(emp_item.get("incentive_amount"), 1600.0)
        self.assertEqual(emp_item.get("gross_amount"), 15000.0 + 3000.0 + 2000.0 + 1600.0)

    # =========================================================================
    # FIX 03: BUG-01 — Packaging Accounting Decimal/Float Parity
    # =========================================================================

    def test_bug_01_packaging_journal_float_decimal_multiplication(self):
        """BUG-01: Packaging batch journal accepts float inputs and computes balanced debits/credits without TypeError."""
        pack_id = "PKG-DEC-001"
        pack_data = {
            "packaging_id": pack_id,
            "product_name_snapshot": "Moong Special Papad",
            "bulk_kg_used": 50.0,
            "total_packets": 100,
            "packaging_date": "2026-11-08",
            "cost_status": "ACTUAL",
        }

        # Seed production batch and stock ledger for authoritative costing
        db.append_record("ProductionBatches", {
            "production_id": "PRB-001",
            "product_name_snapshot": "Moong Special Papad",
            "status": "APPROVED",
            "saleable_output_kg": 50.0,
            "total_batch_cost": 5000.0,
            "cost_per_saleable_kg": 100.0,
        })
        db.append_record("ProductionStockLedger", {
            "movement_id": "MVT-001",
            "movement_type": "BULK_PACKAGED",
            "reference_id": pack_id,
            "total_cost": 5000.0,
        })

        # Call with float costs as passed in runtime production router
        res = post_packaging_batch_journal(
            pack_data,
            bulk_cost=5000.0,
            packing_material_cost=250.50,
            packing_labor_cost=150.25,
            actor="USR-OWNER-01",
        )

        self.assertEqual(res["status"], "POSTED")
        total_dr = Decimal(str(res["total_debit"]))
        total_cr = Decimal(str(res["total_credit"]))
        self.assertEqual(total_dr, total_cr)
        self.assertEqual(total_dr, Decimal("5400.75"))

        # Replay should be idempotent
        replay_res = post_packaging_batch_journal(
            pack_data,
            bulk_cost=5000.0,
            packing_material_cost=250.50,
            packing_labor_cost=150.25,
            actor="USR-OWNER-01",
        )
        self.assertTrue(replay_res["is_replay"])
        all_pkg_headers = [h for h in db.get_records("JournalHeaders") if h.get("reference_id") == pack_id]
        self.assertEqual(len(all_pkg_headers), 1)

    # =========================================================================
    # FIX 04: ACC-01 — Expense & Daily Closing Schema Synchronization
    # =========================================================================

    def test_acc_01_approved_cash_reducing_expense_deducted_in_daily_closing(self):
        """ACC-01: Approved cash-reducing expense reduces expected cash and is stamped with related_closing_id."""
        salesman_id = self.salesman_user["user_id"]

        # 1. Submit and approve a cash-reducing operational expense
        exp_req = ExpenseCreate(
            category="Petrol / Travel",
            amount=450.0,
            description="Van diesel refuel",
            salesman_user_id=salesman_id,
            receipt_link_or_file_ref="https://example.com/receipt.jpg",
        )
        submitted = asyncio.run(submit_expense(exp_req, current_user=self.salesman_user))
        exp_id = submitted.expense_id

        # Approve expense
        appr_req = ExpenseApproveRequest(approved=True, notes="Approved fuel expense")
        asyncio.run(review_expense(exp_id, appr_req, current_user=self.owner_user))

        # Verify expense lists with legacy and canonical fields intact
        all_exp = asyncio.run(list_expenses(current_user=self.owner_user))
        target_exp = next(e for e in all_exp if e.expense_id == exp_id)
        self.assertTrue(target_exp.cash_reducing_expense)
        self.assertEqual(target_exp.receipt_link_or_file_ref, "https://example.com/receipt.jpg")

        # Seed a cash payment of 5000.0 for today
        from app.timeutil import now_iso
        db.append_record("Sales", {
            "sale_id": "SALE-TODAY-01",
            "salesman_user_id": salesman_id,
            "txn_status": "COMPLETE",
        })
        db.append_record("Payments", {
            "payment_id": "PAY-TODAY-01",
            "sale_id": "SALE-TODAY-01",
            "payment_datetime": now_iso(),
            "amount": 5000.0,
            "payment_method": "CASH",
        })

        # 2. Execute Daily Closing
        # Opening cash = 1000.0, Cash collected = 5000.0, Approved expense = 450.0
        # Expected cash = 1000.0 + 5000.0 - 450.0 = 5550.0
        closing_req = DailyClosingCreate(
            opening_cash=1000.0,
            physical_cash_returned=5550.0,
            idempotency_key="CLOSE-TEST-001",
        )
        closing_res = asyncio.run(submit_daily_closing(closing_req, current_user=self.salesman_user))

        self.assertEqual(closing_res.approved_cash_expenses, 450.0)
        self.assertEqual(closing_res.expected_cash_return, 5550.0)
        self.assertEqual(closing_res.cash_difference, 0.0)

        # 3. Verify expense is stamped with related_closing_id to prevent double deduction
        exp_records = db.get_records("Expenses", fresh=True)
        stamped_exp = next(e for e in exp_records if e["expense_id"] == exp_id)
        self.assertEqual(stamped_exp["related_closing_id"], closing_res.closing_id)

        # 4. Verify that the stamped expense cannot be claimed again
        # If another closing query runs, any expense with related_closing_id is skipped
        expense_records_after = db.get_records("Expenses", fresh=True)
        unclaimed_approved = [
            e for e in expense_records_after
            if str(e.get("salesman_user_id")) == salesman_id
            and str(e.get("approval_status", "")).upper() == "APPROVED"
            and str(e.get("cash_reducing_expense", "")).lower() == "true"
            and not str(e.get("related_closing_id", "")).strip()
        ]
        self.assertEqual(len(unclaimed_approved), 0)

    # =========================================================================
    # PHASE 1.1 RELIABILITY TESTS
    # =========================================================================

    def test_phase1_1_sales_cancellation_explicit_accounting_status(self):
        """Phase 1.1: Sales cancellation returns explicit accounting_status, reversal_journal_id, and preserves idempotency."""
        sale_id = "SALE-103"
        bill_no = "BILL-103"

        db.append_record("Sales", {
            "sale_id": sale_id,
            "bill_number": bill_no,
            "sale_datetime": "2026-11-06T10:00:00",
            "customer_id": "CUST-002",
            "customer_name_snapshot": "Test Mart",
            "salesman_user_id": self.salesman_user["user_id"],
            "bill_total": 4500.0,
            "payment_method": "CASH",
            "bill_status": "COMPLETED",
        })

        sale_data = {
            "sale_id": sale_id,
            "bill_number": bill_no,
            "bill_total": 4500.0,
            "customer_name_snapshot": "Test Mart",
            "payment_method": "CASH",
            "sale_datetime": "2026-11-06",
        }
        orig_journal = post_sale_journal(sale_data, estimated_cogs=Decimal("3000.00"), actor=self.salesman_user["user_id"])
        orig_jid = orig_journal["journal_id"]

        # Cancel sale and assert explicit accounting fields in response
        cancel_req = SaleCancelRequest(reason="Customer returned goods")
        res1 = asyncio.run(cancel_sale(sale_id, cancel_req, current_user=self.owner_user))

        self.assertTrue(res1.get("ok"))
        self.assertEqual(res1.get("accounting_status"), "REVERSED")
        self.assertTrue(bool(res1.get("reversal_journal_id")))
        self.assertIsNone(res1.get("accounting_error"))
        self.assertIn("Accounting voucher reversed", res1.get("message", ""))

        # Retry cancellation (idempotent replay)
        res2 = asyncio.run(cancel_sale(sale_id, cancel_req, current_user=self.owner_user))
        self.assertTrue(res2.get("ok"))
        self.assertTrue(res2.get("already_cancelled"))
        self.assertEqual(res2.get("accounting_status"), "ALREADY_REVERSED")
        self.assertEqual(res2.get("reversal_journal_id"), res1.get("reversal_journal_id"))
        self.assertIsNone(res2.get("accounting_error"))

    def test_phase1_1_daily_closing_expense_stamping_failure_recovery(self):
        """Phase 1.1: If expense stamping fails during closing, it is recorded in IncompleteTransactions and recovered on retry."""
        salesman_id = self.salesman_user["user_id"]
        from app.timeutil import now_iso

        # 1. Create approved cash-reducing expense
        exp_req = ExpenseCreate(
            category="Travel",
            amount=250.0,
            description="Taxi to market",
            salesman_user_id=salesman_id,
        )
        exp_res = asyncio.run(submit_expense(exp_req, current_user=self.salesman_user))
        exp_id = exp_res.expense_id
        asyncio.run(review_expense(exp_id, ExpenseApproveRequest(approved=True, cash_reducing=True), current_user=self.owner_user))

        # Seed payment
        db.append_record("Sales", {"sale_id": "SALE-TODAY-02", "salesman_user_id": salesman_id, "txn_status": "COMPLETE"})
        db.append_record("Payments", {
            "payment_id": "PAY-TODAY-02",
            "sale_id": "SALE-TODAY-02",
            "payment_datetime": now_iso(),
            "amount": 2000.0,
            "payment_method": "CASH",
        })

        # Intercept update_record to simulate partial failure on stamping this expense
        orig_update = db.update_record
        fail_target = exp_id

        def mock_update(tab, key_col, key_val, updates, **kwargs):
            if tab == "Expenses" and key_val == fail_target and "related_closing_id" in updates:
                return False  # Simulate storage failure on expense stamping
            return orig_update(tab, key_col, key_val, updates, **kwargs)

        db.update_record = mock_update

        try:
            closing_req = DailyClosingCreate(
                opening_cash=500.0,
                physical_cash_returned=2250.0,  # 500 + 2000 - 250 = 2250
                idempotency_key="CLOSE-FAIL-RECOVER-01",
            )
            closing = asyncio.run(submit_daily_closing(closing_req, current_user=self.salesman_user))
            self.assertEqual(closing.approved_cash_expenses, 250.0)
            self.assertIn("EXPENSE_LINK_PENDING", closing.notes)

            # Verify IncompleteTransactions has recorded the failure
            incomp = db.get_records("IncompleteTransactions", fresh=True)
            pending_stamp = next((t for t in incomp if t.get("transaction_type") == "CLOSING_EXPENSE_LINK_PENDING"), None)
            self.assertIsNotNone(pending_stamp)
            self.assertEqual(pending_stamp.get("status"), "LINK_FAILED")
        finally:
            db.update_record = orig_update

        # Retry with the same idempotency key (simulating network or client retry after recovery)
        retry_res = asyncio.run(submit_daily_closing(closing_req, current_user=self.salesman_user))
        self.assertEqual(retry_res.closing_id, closing.closing_id)

        # Verify expense is now stamped
        exp_after = next(e for e in db.get_records("Expenses", fresh=True) if e["expense_id"] == exp_id)
        self.assertEqual(exp_after.get("related_closing_id"), closing.closing_id)

        # Verify IncompleteTransactions record is RESOLVED
        incomp_after = db.get_records("IncompleteTransactions", fresh=True)
        resolved_stamp = next((t for t in incomp_after if t.get("transaction_type") == "CLOSING_EXPENSE_LINK_PENDING"), None)
        self.assertEqual(resolved_stamp.get("status"), "RESOLVED")


if __name__ == "__main__":
    unittest.main()

