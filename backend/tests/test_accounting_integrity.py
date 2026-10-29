"""
Comprehensive Accounting Integrity Regression Test Suite for Kawad Swad ERP
Verifies:
1. Replay conflict detection on modified transaction totals.
2. 2-stage commit partial write protection (failed lines mark header FAILED; excluded from trial balance).
3. Credit sale debtor lifecycle (Sale -> AR -> partial collection -> full collection, no revenue duplication).
4. Sales GST separation (Output CGST 2210 / Output SGST 2220 split vs net revenue 4100).
5. Period date boundary isolation in Trial Balance & Profit and Loss.
6. Authoritative reconciliation scanner (dry-run detection and safe idempotent backfill).
7. Read-only opening balance proposal mathematical balance (Assets = Liabilities + Equity).
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock
from decimal import Decimal

os.environ["SALES_TESTING"] = "1"
os.environ.setdefault("SALES_JWT_SECRET", "test-only-secret-do-not-use-for-deployment-32")

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import tests  # Trigger mock framework stubs if needed
from app.sheets import db
from app.accounting.journal_engine import (
    post_journal_voucher,
    reverse_journal_voucher,
    calculate_trial_balance,
    calculate_profit_and_loss,
    calculate_balance_sheet,
)
from app.accounting.postings import (
    post_receipt_journal,
    post_sale_journal,
    post_payment_collection_journal,
    post_production_batch_journal,
)
from app.accounting.reconciliation import (
    audit_and_reconcile_operational_events,
    propose_opening_balances,
)


class TestAccountingIntegrityReview(unittest.TestCase):
    def setUp(self):
        for k in list(db.memory_store.keys()):
            db.memory_store[k] = []

    def tearDown(self):
        for k in list(db.memory_store.keys()):
            db.memory_store[k] = []

    def test_1_conflict_rejection_on_altered_replay(self):
        """Verify replaying an existing reference with different financial total raises ValueError."""
        # Initial post of a voucher for Rs 5,000
        lines1 = [
            {"account_code": "1110", "debit_amount": 5000.0, "notes": "Cash"},
            {"account_code": "4100", "credit_amount": 5000.0, "notes": "Sales"},
        ]
        v1 = post_journal_voucher(
            voucher_type="SALES",
            reference_type="TEST_SALE",
            reference_id="TS-001",
            narration="Initial Sale",
            lines=lines1,
            posted_by="AUDITOR",
        )
        self.assertEqual(v1["status"], "POSTED")
        self.assertEqual(float(v1["total_debit"]), 5000.0)

        # Idempotent replay with IDENTICAL amount returns existing voucher safely
        v1_replay = post_journal_voucher(
            voucher_type="SALES",
            reference_type="TEST_SALE",
            reference_id="TS-001",
            narration="Initial Sale",
            lines=lines1,
            posted_by="AUDITOR",
        )
        self.assertEqual(v1_replay["journal_id"], v1["journal_id"])

        # Conflicting replay with ALTERED amount (Rs 6,000) MUST be rejected with ValueError
        conflicting_lines = [
            {"account_code": "1110", "debit_amount": 6000.0, "notes": "Altered Cash"},
            {"account_code": "4100", "credit_amount": 6000.0, "notes": "Altered Sales"},
        ]
        with self.assertRaises(ValueError) as ctx:
            post_journal_voucher(
                voucher_type="SALES",
                reference_type="TEST_SALE",
                reference_id="TS-001",
                narration="Conflicting Sale",
                lines=conflicting_lines,
                posted_by="AUDITOR",
            )
        self.assertIn("Conflict: Reference TEST_SALE:TS-001 already exists", str(ctx.exception))
        self.assertIn("5000.00", str(ctx.exception))
        self.assertIn("6000.00", str(ctx.exception))

    def test_2_partial_journal_write_failure_protection(self):
        """Verify failure during line write marks header FAILED and excludes it from Trial Balance."""
        real_append = db.append_record

        def failing_append(tab, rec, raise_on_error=True):
            if tab == "JournalLines":
                raise IOError("Simulated network failure appending JournalLines")
            return real_append(tab, rec, raise_on_error)

        with patch.object(db, "append_record", side_effect=failing_append):
            lines = [
                {"account_code": "1110", "debit_amount": 2500.0, "notes": "Cash"},
                {"account_code": "4100", "credit_amount": 2500.0, "notes": "Sales"},
            ]
            with self.assertRaises(RuntimeError):
                post_journal_voucher(
                    voucher_type="SALES",
                    reference_type="TEST_FAIL",
                    reference_id="TF-001",
                    narration="Failing transaction",
                    lines=lines,
                    posted_by="AUDITOR",
                )

        # Inspect headers: Voucher header exists but status MUST be 'FAILED'
        headers = db.get_records("JournalHeaders", fresh=True)
        self.assertEqual(len(headers), 1)
        self.assertEqual(headers[0]["status"], "FAILED")
        self.assertIn("Simulated network failure", headers[0]["narration"])

        # Lines table must have 0 rows
        lines_stored = db.get_records("JournalLines", fresh=True)
        self.assertEqual(len(lines_stored), 0)

        # Trial balance must completely exclude FAILED vouchers, preserving $0.00 ledger balance
        tb = calculate_trial_balance()
        self.assertTrue(tb["is_balanced"])
        self.assertEqual(tb["total_debits"], 0.0)
        self.assertEqual(tb["total_credits"], 0.0)

    def test_3_credit_sale_and_subsequent_collections(self):
        """
        Verify complete debtor lifecycle:
        1. Credit Sale creates Accounts Receivable (1130) balance.
        2. Partial customer payment debits Cash (1115) and credits AR (1130).
        3. Full remaining payment clears AR to 0.0.
        4. Zero duplicate revenue is recognized on collections.
        """
        # Step 1: Credit Sale of ₹10,000 (inclusive of ₹500 GST)
        sale_row = {
            "sale_id": "SALE-CREDIT-01",
            "bill_number": "BILL-1001",
            "sale_datetime": "2026-10-15T10:00:00",
            "payment_method": "CREDIT",
            "bill_total": 10000.0,
            "tax_amount": 500.0,
            "customer_id": "CUS-001",
            "customer_name_snapshot": "Shree Ram Stores",
        }
        db.append_record("Sales", sale_row)
        post_sale_journal(sale_row, actor="SALESMAN_1")

        # Trial Balance check: AR (1130) has 10,000; Revenue (4100) has 9,500; Output CGST (2210) 250; SGST (2220) 250
        tb1 = calculate_trial_balance()
        self.assertTrue(tb1["is_balanced"])
        ar_row = next(r for r in tb1["rows"] if r["account_code"] == "1130")
        rev_row = next(r for r in tb1["rows"] if r["account_code"] == "4100")
        self.assertEqual(ar_row["net_debit"], 10000.0)
        self.assertEqual(rev_row["net_credit"], 9500.0)

        # Step 2: Partial collection of ₹4,000 in Cash
        pay1 = {
            "payment_id": "PAY-001",
            "sale_id": "SALE-CREDIT-01",
            "payment_datetime": "2026-10-16T11:00:00",
            "payment_method": "CASH",
            "amount": 4000.0,
        }
        db.append_record("Payments", pay1)
        post_payment_collection_journal(pay1, actor="SALESMAN_1")

        tb2 = calculate_trial_balance()
        self.assertTrue(tb2["is_balanced"])
        ar_row2 = next(r for r in tb2["rows"] if r["account_code"] == "1130")
        cash_row2 = next(r for r in tb2["rows"] if r["account_code"] == "1115")
        rev_row2 = next(r for r in tb2["rows"] if r["account_code"] == "4100")
        self.assertEqual(ar_row2["net_debit"], 6000.0)  # 10,000 - 4,000 = 6,000
        self.assertEqual(cash_row2["net_debit"], 4000.0)
        self.assertEqual(rev_row2["net_credit"], 9500.0)  # Revenue NOT duplicated

        # Step 3: Full remaining collection of ₹6,000 via UPI (Bank 1120)
        pay2 = {
            "payment_id": "PAY-002",
            "sale_id": "SALE-CREDIT-01",
            "payment_datetime": "2026-10-17T12:00:00",
            "payment_method": "UPI",
            "amount": 6000.0,
        }
        db.append_record("Payments", pay2)
        post_payment_collection_journal(pay2, actor="SALESMAN_1")

        tb3 = calculate_trial_balance()
        self.assertTrue(tb3["is_balanced"])
        ar_row3 = next(r for r in tb3["rows"] if r["account_code"] == "1130")
        bank_row3 = next(r for r in tb3["rows"] if r["account_code"] == "1120")
        rev_row3 = next(r for r in tb3["rows"] if r["account_code"] == "4100")
        self.assertEqual(ar_row3["net_debit"], 0.0)  # Debtor completely cleared
        self.assertEqual(bank_row3["net_debit"], 6000.0)
        self.assertEqual(rev_row3["net_credit"], 9500.0)  # Revenue strictly preserved at 9,500

    def test_4_sales_tax_separation(self):
        """Verify sales invoice separates gross bill total into net revenue (4100) and Output GST (2210/2220)."""
        sale_data = {
            "sale_id": "SALE-GST-01",
            "bill_number": "BILL-2001",
            "sale_datetime": "2026-10-18T14:00:00",
            "payment_method": "CASH",
            "bill_total": 2100.0,
            "tax_amount": 100.0,
            "customer_name_snapshot": "Patel Grocers",
        }
        v = post_sale_journal(sale_data, actor="CASHIER")
        self.assertEqual(v["status"], "POSTED")
        self.assertEqual(float(v["total_debit"]), 2100.0)
        self.assertEqual(float(v["total_credit"]), 2100.0)

        # Retrieve voucher lines from db
        lines = [l for l in db.get_records("JournalLines", fresh=True) if l.get("journal_id") == v["journal_id"]]
        cash_line = next(l for l in lines if l["account_code"] == "1115")
        rev_line = next(l for l in lines if l["account_code"] == "4100")
        cgst_line = next(l for l in lines if l["account_code"] == "2210")
        sgst_line = next(l for l in lines if l["account_code"] == "2220")

        self.assertEqual(float(cash_line["debit_amount"]), 2100.0)
        self.assertEqual(float(rev_line["credit_amount"]), 2000.0)  # 2100 - 100
        self.assertEqual(float(cgst_line["credit_amount"]), 50.0)
        self.assertEqual(float(sgst_line["credit_amount"]), 50.0)

    def test_5_period_date_boundary_filtering(self):
        """Verify strict start_date and end_date filtering isolates period financial statements."""
        # Voucher in September 2026 (Revenue 15,000)
        post_journal_voucher(
            voucher_type="SALES",
            reference_type="SALE_INVOICE",
            reference_id="SALE-SEP",
            narration="September Sale",
            journal_date="2026-09-15",
            lines=[
                {"account_code": "1110", "debit_amount": 15000.0},
                {"account_code": "4100", "credit_amount": 15000.0},
            ],
            posted_by="AUDITOR",
        )

        # Voucher in October 2026 (Revenue 25,000, Expense 5,000)
        post_journal_voucher(
            voucher_type="SALES",
            reference_type="SALE_INVOICE",
            reference_id="SALE-OCT",
            narration="October Sale",
            journal_date="2026-10-10",
            lines=[
                {"account_code": "1110", "debit_amount": 25000.0},
                {"account_code": "4100", "credit_amount": 25000.0},
            ],
            posted_by="AUDITOR",
        )
        post_journal_voucher(
            voucher_type="PAYMENT",
            reference_type="EXPENSE",
            reference_id="EXP-OCT",
            narration="October Fuel",
            journal_date="2026-10-12",
            lines=[
                {"account_code": "5210", "debit_amount": 5000.0},
                {"account_code": "1110", "credit_amount": 5000.0},
            ],
            posted_by="AUDITOR",
        )

        # Query P&L for October 2026 ONLY
        oct_pnl = calculate_profit_and_loss(start_date="2026-10-01", end_date="2026-10-31")
        self.assertEqual(oct_pnl["total_revenue"], 25000.0)  # Excludes September 15,000
        self.assertEqual(oct_pnl["total_operating_expenses"], 5000.0)
        self.assertEqual(oct_pnl["net_profit"], 20000.0)

        # Query P&L for Full Period (Sep 1 to Oct 31)
        full_pnl = calculate_profit_and_loss(start_date="2026-09-01", end_date="2026-10-31")
        self.assertEqual(full_pnl["total_revenue"], 40000.0)  # 15,000 + 25,000
        self.assertEqual(full_pnl["net_profit"], 35000.0)

    def test_6_reconciliation_scanner_and_idempotent_backfill(self):
        """Verify reconciliation scanner finds unposted operational events and backfills them safely."""
        # Insert raw operational records WITHOUT posting journal vouchers
        db.append_record("RawMaterialLedger", {
            "raw_material_txn_id": "RML-RECON-01",
            "txn_datetime": "2026-10-01T08:00:00",
            "material_name_snapshot": "Moong Dal",
            "category": "Whole Dal",
            "quantity_kg": 500.0,
            "unit_price_inr": 110.0,
            "tax_amount": 2750.0,
            "itc_eligible": True,
            "txn_type": "RECEIVE",
        })
        db.append_record("Sales", {
            "sale_id": "SALE-RECON-01",
            "bill_number": "BILL-RECON-1",
            "sale_datetime": "2026-10-02T15:00:00",
            "payment_method": "CASH",
            "bill_total": 4500.0,
            "tax_amount": 0.0,
            "bill_status": "DELIVERED",
        })

        # 1. Dry-run scan: must detect both unposted events without creating vouchers
        audit_res = audit_and_reconcile_operational_events(dry_run=True)
        self.assertEqual(audit_res["missing_count"], 2)
        self.assertEqual(audit_res["reconciled_count"], 0)
        self.assertEqual(len(db.get_records("JournalHeaders", fresh=True)), 0)

        # 2. Backfill execution (dry_run=False): must safely post vouchers
        backfill_res = audit_and_reconcile_operational_events(dry_run=False, actor="RECON_TEST")
        self.assertEqual(backfill_res["missing_count"], 2)
        self.assertEqual(backfill_res["reconciled_count"], 2)
        self.assertEqual(backfill_res["error_count"], 0)

        # 3. Verify ledger is balanced
        tb = calculate_trial_balance()
        self.assertTrue(tb["is_balanced"])

        # 4. Repeat scan: must find ZERO unposted events (idempotent)
        repeat_scan = audit_and_reconcile_operational_events(dry_run=True)
        self.assertEqual(repeat_scan["missing_count"], 0)

    def test_7_opening_balance_proposal_mathematical_balance(self):
        """Verify opening balance proposal derives balanced Assets = Liabilities + Equity."""
        # Add some sample operational stock and cash
        db.append_record("RawMaterialLedger", {
            "raw_material_txn_id": "RML-INIT-01",
            "category": "Whole Dal",
            "quantity_kg": 1000.0,
            "unit_price_inr": 100.0,
            "txn_type": "RECEIVE",
        })
        db.append_record("PackagingBatches", {
            "packaging_batch_id": "PKG-INIT-01",
            "packet_count": 200,
            "status": "APPROVED",
        })
        db.append_record("CashLedger", {
            "cash_txn_id": "CSH-INIT-01",
            "amount": 25000.0,
        })

        proposal = propose_opening_balances()
        self.assertEqual(proposal["status"], "PROPOSED")
        self.assertEqual(proposal["balance_check"], "BALANCED")
        self.assertAlmostEqual(proposal["total_debits"], proposal["total_credits"], places=2)
        self.assertEqual(
            round(proposal["total_assets"], 2),
            round(proposal["total_liabilities"] + proposal["owner_equity"], 2),
        )


if __name__ == "__main__":
    unittest.main()
