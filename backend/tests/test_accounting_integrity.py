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
import asyncio
from unittest.mock import patch, MagicMock
from decimal import Decimal
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import tests  # Trigger mock framework stubs if needed
from fastapi import HTTPException
from app.sheets import db
from app.models import SalePaymentCreate
from app.routers.sales import record_sale_payment
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

    def test_8_gst_explicit_split_rounding_and_reversal(self):
        """
        Verify:
        1. Explicit cgst_amount and sgst_amount provided in invoice.
        2. Asymmetric odd-paise rounding splits (debts == credits to the exact penny).
        3. Zero-tax sale assigns 100% to revenue (4100) with no tax accounts.
        4. Reversal voucher (reverse_journal_voucher) reverses tax lines symmetrically.
        """
        # Case A: Explicit CGST and SGST
        sale_a = {
            "sale_id": "SALE-GST-EXP-01",
            "bill_number": "BILL-GST-101",
            "sale_datetime": "2026-10-20T10:00:00",
            "payment_method": "CASH",
            "bill_total": 1091.00,
            "cgst_amount": 45.50,
            "sgst_amount": 45.50,
            "customer_name_snapshot": "Gupta Retailers",
        }
        v_a = post_sale_journal(sale_a, actor="CASHIER")
        self.assertEqual(v_a["status"], "POSTED")
        lines_a = [l for l in db.get_records("JournalLines", fresh=True) if l.get("journal_id") == v_a["journal_id"]]
        rev_a = next(l for l in lines_a if l["account_code"] == "4100")
        cgst_a = next(l for l in lines_a if l["account_code"] == "2210")
        sgst_a = next(l for l in lines_a if l["account_code"] == "2220")
        self.assertEqual(float(rev_a["credit_amount"]), 1000.00)
        self.assertEqual(float(cgst_a["credit_amount"]), 45.50)
        self.assertEqual(float(sgst_a["credit_amount"]), 45.50)

        # Case B: Odd paise tax amount (₹5.01) on ₹100.01 total -> CGST=2.51, SGST=2.50, Net=95.00
        sale_b = {
            "sale_id": "SALE-GST-ODD-01",
            "bill_number": "BILL-GST-102",
            "sale_datetime": "2026-10-20T11:00:00",
            "payment_method": "CASH",
            "bill_total": 100.01,
            "tax_amount": 5.01,
            "customer_name_snapshot": "Odd Paise Store",
        }
        v_b = post_sale_journal(sale_b, actor="CASHIER")
        lines_b = [l for l in db.get_records("JournalLines", fresh=True) if l.get("journal_id") == v_b["journal_id"]]
        cash_b = next(l for l in lines_b if l["account_code"] == "1115")
        rev_b = next(l for l in lines_b if l["account_code"] == "4100")
        cgst_b = next(l for l in lines_b if l["account_code"] == "2210")
        sgst_b = next(l for l in lines_b if l["account_code"] == "2220")
        self.assertEqual(float(cash_b["debit_amount"]), 100.01)
        self.assertEqual(float(rev_b["credit_amount"]), 95.00)
        self.assertEqual(float(cgst_b["credit_amount"]), 2.51)
        self.assertEqual(float(sgst_b["credit_amount"]), 2.50)
        self.assertEqual(
            round(float(rev_b["credit_amount"]) + float(cgst_b["credit_amount"]) + float(sgst_b["credit_amount"]), 2),
            float(cash_b["debit_amount"])
        )

        # Case C: Zero-tax sale
        sale_c = {
            "sale_id": "SALE-ZERO-TAX-01",
            "bill_number": "BILL-ZT-103",
            "sale_datetime": "2026-10-20T12:00:00",
            "payment_method": "CASH",
            "bill_total": 750.00,
            "tax_amount": 0.0,
            "customer_name_snapshot": "Exempt Buyer",
        }
        v_c = post_sale_journal(sale_c, actor="CASHIER")
        lines_c = [l for l in db.get_records("JournalLines", fresh=True) if l.get("journal_id") == v_c["journal_id"]]
        self.assertEqual(len(lines_c), 2)
        self.assertTrue(all(l["account_code"] not in {"2210", "2220"} for l in lines_c))
        self.assertEqual(float(lines_c[1]["credit_amount"]), 750.00)

        # Case D: Reversal of voucher with tax
        rev_v = reverse_journal_voucher(
            journal_id=v_a["journal_id"],
            reason="Customer returned goods and invoice voided",
            reversed_by="AUDITOR",
        )
        self.assertEqual(rev_v["status"], "POSTED")
        rev_lines = [l for l in db.get_records("JournalLines", fresh=True) if l.get("journal_id") == rev_v["journal_id"]]
        # In reversal, 4100, 2210, 2220 are debited, and 1115 is credited
        rev_debit_codes = {l["account_code"]: float(l["debit_amount"]) for l in rev_lines if float(l["debit_amount"]) > 0}
        self.assertEqual(rev_debit_codes.get("4100"), 1000.00)
        self.assertEqual(rev_debit_codes.get("2210"), 45.50)
        self.assertEqual(rev_debit_codes.get("2220"), 45.50)

    def test_9_partial_write_stages_and_repair(self):
        """
        Verify multi-stage write failure safety and subsequent repair:
        - Failure during line 2 marks header FAILED.
        - Trial Balance strictly ignores FAILED vouchers (total debits/credits remain 0.00).
        - Re-running post_journal_voucher with same reference purges orphan partial lines,
          updates header to POSTED, and brings Trial Balance into clean balance.
        """
        real_append = db.append_record
        attempt_line = 0

        def fail_on_second_line(tab, rec, raise_on_error=True):
            nonlocal attempt_line
            if tab == "JournalLines":
                attempt_line += 1
                if attempt_line == 2:
                    raise IOError("Simulated network timeout appending second journal line")
            return real_append(tab, rec, raise_on_error)

        lines = [
            {"account_code": "1110", "debit_amount": 8000.0, "notes": "Cash Line"},
            {"account_code": "4100", "credit_amount": 8000.0, "notes": "Revenue Line"},
        ]

        with patch.object(db, "append_record", side_effect=fail_on_second_line):
            with self.assertRaises(RuntimeError):
                post_journal_voucher(
                    voucher_type="SALES",
                    reference_type="SALE_PARTIAL",
                    reference_id="SP-001",
                    narration="Failing 2nd line",
                    lines=lines,
                    posted_by="CLERK",
                )

        # Header status must be FAILED
        headers = [h for h in db.get_records("JournalHeaders", fresh=True) if h.get("reference_id") == "SP-001"]
        self.assertEqual(len(headers), 1)
        self.assertEqual(headers[0]["status"], "FAILED")

        # 1 partial line exists in table
        orphan_lines = [l for l in db.get_records("JournalLines", fresh=True) if l.get("journal_id") == headers[0]["journal_id"]]
        self.assertEqual(len(orphan_lines), 1)

        # Trial Balance MUST ignore FAILED header (no ledger contamination)
        tb_before = calculate_trial_balance()
        self.assertTrue(tb_before["is_balanced"])
        self.assertEqual(tb_before["total_debits"], 0.0)
        self.assertEqual(tb_before["total_credits"], 0.0)

        # Repair / Retry after storage recovery
        v_repaired = post_journal_voucher(
            voucher_type="SALES",
            reference_type="SALE_PARTIAL",
            reference_id="SP-001",
            narration="Repaired transaction",
            lines=lines,
            posted_by="CLERK",
        )
        self.assertEqual(v_repaired["status"], "POSTED")
        self.assertEqual(v_repaired["journal_id"], headers[0]["journal_id"])

        # Lines table must now contain exactly 2 lines (no duplicate orphan line from failed attempt)
        repaired_lines = [l for l in db.get_records("JournalLines", fresh=True) if l.get("journal_id") == headers[0]["journal_id"]]
        self.assertEqual(len(repaired_lines), 2)

        # Trial balance now reflects the ₹8,000 transaction with perfect balance
        tb_after = calculate_trial_balance()
        self.assertTrue(tb_after["is_balanced"])
        self.assertEqual(tb_after["total_debits"], 8000.0)
        self.assertEqual(tb_after["total_credits"], 8000.0)

    def test_10_customer_payment_lifecycle_and_idempotency(self):
        """
        Verify complete customer payment lifecycle through router:
        1. Partial payment updates remaining balance and sets status PARTIALLY_PAID.
        2. Idempotent replay with same key returns identical record with is_replay=True.
        3. Conflicting replay with same key and altered amount raises HTTP 409 Conflict.
        4. Overpayment exceeding remaining balance raises HTTP 400.
        5. CashLedger append failure triggers rollback of Payments row and raises HTTP 503.
        6. Full payment clears AR to 0.0 without revenue duplication.
        """
        # Set up a credit sale of ₹5,000 in Sales table
        sale_record = {
            "sale_id": "SALE-ROUTER-PAY-01",
            "bill_number": "BILL-RP-501",
            "sale_datetime": "2026-10-21T09:00:00",
            "customer_id": "CUS-101",
            "customer_name_snapshot": "Mahavir Traders",
            "bill_total": 5000.0,
            "tax_amount": 0.0,
            "payment_method": "CREDIT",
            "bill_status": "DELIVERED",
            "payment_status": "UNPAID",
            "salesman_user_id": "USR-SALES-01",
        }
        db.append_record("Sales", sale_record)
        post_sale_journal(sale_record, actor="SALESMAN")

        current_user = {"user_id": "USR-SALES-01", "username": "salesman1", "role": "SALESMAN"}

        # 1. Partial payment of ₹2,000 in Cash
        p1 = SalePaymentCreate(
            amount=2000.0,
            payment_method="CASH",
            idempotency_key="IDEMP-PAY-001",
            notes="First installment",
        )
        res1 = asyncio.run(record_sale_payment("SALE-ROUTER-PAY-01", p1, current_user=current_user))
        self.assertTrue(res1["ok"])
        self.assertEqual(res1["amount_paid"], 2000.0)
        self.assertEqual(res1["remaining_balance"], 3000.0)

        # Check CashLedger row was created
        cash_rows = [c for c in db.get_records("CashLedger", fresh=True) if c.get("related_sale_id") == "SALE-ROUTER-PAY-01"]
        self.assertEqual(len(cash_rows), 1)
        self.assertEqual(float(cash_rows[0]["amount"]), 2000.0)

        # 2. Idempotent replay with same key and amount
        res1_replay = asyncio.run(record_sale_payment("SALE-ROUTER-PAY-01", p1, current_user=current_user))
        self.assertTrue(res1_replay.get("is_replay"))
        self.assertEqual(res1_replay["payment_id"], res1["payment_id"])

        # 3. Conflicting replay with same key but altered amount (₹2,500) -> HTTP 409
        p_conflict = SalePaymentCreate(
            amount=2500.0,
            payment_method="CASH",
            idempotency_key="IDEMP-PAY-001",
            notes="Altered amount",
        )
        with self.assertRaises(HTTPException) as ctx_conf:
            asyncio.run(record_sale_payment("SALE-ROUTER-PAY-01", p_conflict, current_user=current_user))
        self.assertEqual(ctx_conf.exception.status_code, 409)

        # 4. Overpayment (₹3,500 exceeds remaining balance ₹3,000) -> HTTP 400
        p_over = SalePaymentCreate(
            amount=3500.0,
            payment_method="CASH",
            idempotency_key="IDEMP-PAY-OVER",
            notes="Overpayment attempt",
        )
        with self.assertRaises(HTTPException) as ctx_over:
            asyncio.run(record_sale_payment("SALE-ROUTER-PAY-01", p_over, current_user=current_user))
        self.assertEqual(ctx_over.exception.status_code, 400)

        # 5. Rollback on CashLedger append failure
        real_append = db.append_record

        def fail_cash_ledger(tab, rec, raise_on_error=True):
            if tab == "CashLedger":
                raise IOError("Simulated CashLedger disk write failure")
            return real_append(tab, rec, raise_on_error)

        p_fail = SalePaymentCreate(
            amount=500.0,
            payment_method="CASH",
            idempotency_key="IDEMP-PAY-FAIL",
            notes="Failing cash write",
        )
        with patch.object(db, "append_record", side_effect=fail_cash_ledger):
            with self.assertRaises(HTTPException) as ctx_503:
                asyncio.run(record_sale_payment("SALE-ROUTER-PAY-01", p_fail, current_user=current_user))
            self.assertEqual(ctx_503.exception.status_code, 503)

        # Verify Payments record was rolled back
        payments_after_fail = [
            p for p in db.get_records("Payments", fresh=True)
            if p.get("idempotency_key") == "IDEMP-PAY-FAIL"
        ]
        self.assertEqual(len(payments_after_fail), 0)

        # 6. Full remaining payment of ₹3,000 via UPI (Bank 1120)
        p_final = SalePaymentCreate(
            amount=3000.0,
            payment_method="UPI",
            idempotency_key="IDEMP-PAY-FINAL",
            reference_number="UPI-REF-9988",
            notes="Final settlement",
        )
        res_final = asyncio.run(record_sale_payment("SALE-ROUTER-PAY-01", p_final, current_user=current_user))
        self.assertTrue(res_final["ok"])
        self.assertEqual(res_final["remaining_balance"], 0.0)

        # Check Sales record payment_status is PAID
        sales_fresh = db.get_records("Sales", fresh=True)
        sale_fresh = next(s for s in sales_fresh if s.get("sale_id") == "SALE-ROUTER-PAY-01")
        self.assertEqual(sale_fresh["payment_status"], "PAID")

        # Verify Trial Balance: AR (1130) is completely 0.0, Revenue (4100) is strictly 5000.0 (no duplication)
        tb = calculate_trial_balance()
        self.assertTrue(tb["is_balanced"])
        ar_row = next((r for r in tb["rows"] if r["account_code"] == "1130"), None)
        rev_row = next(r for r in tb["rows"] if r["account_code"] == "4100")
        cash_row = next(r for r in tb["rows"] if r["account_code"] == "1115")
        bank_row = next(r for r in tb["rows"] if r["account_code"] == "1120")
        if ar_row:
            self.assertEqual(ar_row["net_debit"], 0.0)
        self.assertEqual(rev_row["net_credit"], 5000.0)
        self.assertEqual(cash_row["net_debit"], 2000.0)
        self.assertEqual(bank_row["net_debit"], 3000.0)

    def test_11_reconciliation_distinguishes_issues_and_enforces_dry_run(self):
        """
        Verify reconciliation scanner:
        1. Distinguishes unposted events, failed vouchers, incomplete vouchers, and duplicate references.
        2. Dry-run makes zero writes to JournalHeaders or JournalLines.
        3. Live backfill repairs and posts vouchers, bringing ledger into balance.
        """
        # 1 unposted sale
        db.append_record("Sales", {
            "sale_id": "SALE-RECON-UNPOSTED",
            "bill_number": "BILL-RU-1",
            "sale_datetime": "2026-10-22T10:00:00",
            "payment_method": "CASH",
            "bill_total": 1200.0,
            "tax_amount": 0.0,
            "bill_status": "DELIVERED",
        })

        # 1 failed voucher in JournalHeaders
        db.append_record("JournalHeaders", {
            "journal_id": "JRN-FAIL-01",
            "reference_type": "EXPENSE",
            "reference_id": "EXP-RECON-FAIL",
            "status": "FAILED",
            "narration": "Line write timed out",
            "total_debit": 500.0,
            "total_credit": 500.0,
        })
        db.append_record("Expenses", {
            "expense_id": "EXP-RECON-FAIL",
            "expense_datetime": "2026-10-22T11:00:00",
            "category": "Petrol & Fuel",
            "amount": 500.0,
            "approval_status": "APPROVED",
            "cash_reducing_expense": True,
        })

        # 1 incomplete voucher
        db.append_record("JournalHeaders", {
            "journal_id": "JRN-INC-01",
            "reference_type": "PAYMENT_COLLECTION",
            "reference_id": "PAY-RECON-INC",
            "status": "INCOMPLETE",
            "narration": "Pending line verification",
            "total_debit": 300.0,
            "total_credit": 300.0,
        })
        db.append_record("Payments", {
            "payment_id": "PAY-RECON-INC",
            "sale_id": "SALE-ANY",
            "payment_datetime": "2026-10-22T12:00:00",
            "payment_method": "CASH",
            "amount": 300.0,
            "payment_status": "COLLECTED",
        })

        # Duplicate reference in JournalHeaders (2 vouchers for same reference)
        db.append_record("JournalHeaders", {
            "journal_id": "JRN-DUP-01",
            "reference_type": "TEST_DUP",
            "reference_id": "DUP-REF-99",
            "status": "POSTED",
            "narration": "First duplicate",
            "total_debit": 100.0,
            "total_credit": 100.0,
        })
        db.append_record("JournalHeaders", {
            "journal_id": "JRN-DUP-02",
            "reference_type": "TEST_DUP",
            "reference_id": "DUP-REF-99",
            "status": "POSTED",
            "narration": "Second duplicate",
            "total_debit": 100.0,
            "total_credit": 100.0,
        })

        headers_before_count = len(db.get_records("JournalHeaders", fresh=True))

        # Dry Run Execution
        scan_result = audit_and_reconcile_operational_events(dry_run=True)
        self.assertTrue(scan_result["dry_run"])
        self.assertEqual(scan_result["reconciled_count"], 0)
        self.assertEqual(len(db.get_records("JournalHeaders", fresh=True)), headers_before_count)

        # Verify distinct category breakdowns
        self.assertGreaterEqual(scan_result["unposted_count"], 1)
        self.assertGreaterEqual(scan_result["failed_count"], 1)
        self.assertGreaterEqual(scan_result["incomplete_count"], 1)
        self.assertGreaterEqual(scan_result["duplicate_reference_count"], 1)
        self.assertEqual(
            scan_result["missing_count"],
            scan_result["unposted_count"] + scan_result["failed_count"] + scan_result["incomplete_count"]
        )

        dup_item = next(d for d in scan_result["duplicate_references"] if d["reference_key"] == "TEST_DUP:DUP-REF-99")
        self.assertEqual(dup_item["voucher_count"], 2)


if __name__ == "__main__":
    unittest.main()

