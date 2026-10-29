"""
Kawad Swad ERP - Double-Entry General Ledger Accounting Test Suite
Verifies:
1. Chart of Accounts validation.
2. Debit/Credit balance enforcement (unbalanced entries strictly rejected).
3. Idempotent journal voucher creation.
4. Compensating reversals.
5. Event postings for Receipt, Milling, Production, Packaging, Sale, and Daily Closing.
6. Authoritative Trial Balance, P&L, and Balance Sheet reconciliation.
"""

import unittest
from decimal import Decimal

from app.sheets import db, REQUIRED_TABS
from app.accounting.chart_of_accounts import CHART_OF_ACCOUNTS, ACCOUNT_LOOKUP
from app.accounting.journal_engine import (
    validate_journal_lines,
    post_journal_voucher,
    reverse_journal_voucher,
    calculate_trial_balance,
    calculate_profit_and_loss,
    calculate_balance_sheet,
)
from app.accounting.postings import (
    post_receipt_journal,
    post_milling_journal,
    post_production_batch_journal,
    post_packaging_batch_journal,
    post_sale_journal,
    post_daily_closing_cash_remittance_journal,
)


class TestDoubleEntryAccounting(unittest.TestCase):
    def setUp(self):
        for tab in REQUIRED_TABS:
            db.memory_store[tab] = []

    def test_chart_of_accounts_structure(self):
        """Verify standard chart of accounts covers all asset, liability, equity, revenue, and expense types."""
        self.assertGreaterEqual(len(CHART_OF_ACCOUNTS), 20)
        types = {acc["account_type"] for acc in CHART_OF_ACCOUNTS}
        self.assertEqual(types, {"ASSET", "LIABILITY", "EQUITY", "REVENUE", "EXPENSE"})
        self.assertIn("1110", ACCOUNT_LOOKUP)  # Cash-in-Hand
        self.assertIn("1210", ACCOUNT_LOOKUP)  # Whole Dal
        self.assertIn("1220", ACCOUNT_LOOKUP)  # Flour
        self.assertIn("1230", ACCOUNT_LOOKUP)  # WIP Bulk
        self.assertIn("1240", ACCOUNT_LOOKUP)  # Finished Goods
        self.assertIn("4100", ACCOUNT_LOOKUP)  # Sales Revenue
        self.assertIn("5100", ACCOUNT_LOOKUP)  # COGS

    def test_unbalanced_voucher_strictly_rejected(self):
        """Verify any voucher where Total Debits != Total Credits is rejected with ValueError."""
        unbalanced_lines = [
            {"account_code": "1110", "debit_amount": 500.0, "credit_amount": 0.0},
            {"account_code": "4100", "debit_amount": 0.0, "credit_amount": 450.0},  # Discrepancy of Rs 50
        ]
        with self.assertRaises(ValueError) as ctx:
            validate_journal_lines(unbalanced_lines)
        self.assertIn("Unbalanced journal entry", str(ctx.exception))

    def test_unknown_account_rejected(self):
        """Verify voucher with unregistered account code is rejected."""
        invalid_lines = [
            {"account_code": "9999", "debit_amount": 100.0, "credit_amount": 0.0},
            {"account_code": "1110", "debit_amount": 0.0, "credit_amount": 100.0},
        ]
        with self.assertRaises(ValueError) as ctx:
            validate_journal_lines(invalid_lines)
        self.assertIn("Unknown or unregistered account code", str(ctx.exception))

    def test_idempotent_voucher_posting(self):
        """Verify posting with same reference_type and reference_id returns existing voucher without duplication."""
        lines = [
            {"account_code": "1110", "debit_amount": 1000.0, "credit_amount": 0.0},
            {"account_code": "3100", "debit_amount": 0.0, "credit_amount": 1000.0},
        ]
        v1 = post_journal_voucher("RECEIPT", "OWNER_CAPITAL", "CAP-001", "Owner capital introduction", lines, "USR-OWNER-01")
        self.assertFalse(v1["is_replay"])
        self.assertEqual(len(db.memory_store["JournalHeaders"]), 1)
        self.assertEqual(len(db.memory_store["JournalLines"]), 2)

        # Retry with identical reference
        v2 = post_journal_voucher("RECEIPT", "OWNER_CAPITAL", "CAP-001", "Owner capital introduction", lines, "USR-OWNER-01")
        self.assertTrue(v2["is_replay"])
        self.assertEqual(v2["journal_id"], v1["journal_id"])
        self.assertEqual(len(db.memory_store["JournalHeaders"]), 1)
        self.assertEqual(len(db.memory_store["JournalLines"]), 2)

    def test_compensating_reversal_voucher(self):
        """Verify reversal creates equal and opposite compensating voucher."""
        lines = [
            {"account_code": "5210", "debit_amount": 300.0, "credit_amount": 0.0},
            {"account_code": "1110", "debit_amount": 0.0, "credit_amount": 300.0},
        ]
        v = post_journal_voucher("PAYMENT", "PETROL_EXPENSE", "EXP-001", "Petrol reimbursement", lines, "USR-OWNER-01")
        jid = v["journal_id"]

        rev = reverse_journal_voucher(jid, "Duplicate expense entry", "USR-OWNER-01")
        self.assertEqual(rev["voucher_type"], "REVERSAL")
        self.assertEqual(rev["reference_id"], jid)

        # In original: 5210 was debit 300, 1110 was credit 300. In reversal: 1110 debit 300, 5210 credit 300.
        rev_lines = rev["lines"]
        line_5210 = next(l for l in rev_lines if l["account_code"] == "5210")
        line_1110 = next(l for l in rev_lines if l["account_code"] == "1110")
        self.assertEqual(line_5210["credit_amount"], 300.0)
        self.assertEqual(line_1110["debit_amount"], 300.0)

    def test_end_to_end_business_event_postings_and_trial_balance(self):
        """
        Verify the complete operational chain posts balanced vouchers:
        1. Owner Capital -> Cash Rs 50,000
        2. Raw Material Purchase -> 100 kg Dal @ Rs 110 + Rs 400 freight
        3. Dal Milling -> 100 kg Dal -> 98 kg Flour + Rs 300 milling exp
        4. Papad Production -> 10 kg Bulk Papad using flour (Rs 1,000)
        5. Packaging -> 50 Packets (Rs 1,000 bulk + Rs 150 packaging + Rs 100 labor)
        6. Sales Invoice -> 20 Packets @ Rs 55 = Rs 1,100 (COGS = 20 * Rs 25 = Rs 500)
        7. Daily Closing Cash Remittance -> Rs 1,100 to Safe
        8. Trial Balance must balance to 0.00 difference!
        """
        # 1. Capital
        post_journal_voucher("RECEIPT", "CAPITAL", "CAP-INITIAL", "Initial Capital", [
            {"account_code": "1110", "debit_amount": 50000.0, "credit_amount": 0.0},
            {"account_code": "3100", "debit_amount": 0.0, "credit_amount": 50000.0},
        ], "USR-OWNER-01")

        # 2. Raw Material Receipt
        rcv_v = post_receipt_journal({
            "raw_material_txn_id": "RML-001",
            "material_name": "Whole Moong Dal",
            "quantity": 100.0,
            "purchase_rate": 110.0,
            "freight_amount": 400.0,
            "gst_amount": 0.0,
            "supplier_name": "Kisan Agro",
        }, "USR-OWNER-01")
        self.assertEqual(rcv_v["total_debit"], 11400.0)
        self.assertEqual(rcv_v["total_credit"], 11400.0)

        # 3. Milling Conversion
        mill_v = post_milling_journal({
            "milling_batch_id": "MIL-001",
            "input_quantity_kg": 100.0,
            "flour_output_kg": 98.0,
            "source_unit_rate": 114.0,  # 11400 / 100
            "milling_expenses": 300.0,
        }, "USR-OWNER-01")
        self.assertEqual(mill_v["total_debit"], 11700.0)
        self.assertEqual(mill_v["total_credit"], 11700.0)

        # 4. Production Batch
        prod_v = post_production_batch_journal(
            {"production_id": "PRB-001", "net_quantity_kg": 10.0, "product_name_snapshot": "Moong Master Papad"},
            flour_cost=Decimal("1000.00"),
            spice_cost=Decimal("150.00"),
            labor_cost=Decimal("100.00"),
            actor="USR-OWNER-01",
        )
        self.assertEqual(prod_v["total_debit"], 1250.0)
        self.assertEqual(prod_v["total_credit"], 1250.0)

        # 5. Packaging Batch
        pack_v = post_packaging_batch_journal(
            {"packaging_id": "PKG-001", "total_packets": 50, "bulk_kg_used": 10.0, "product_name_snapshot": "Moong Master Papad"},
            bulk_cost=Decimal("1250.00"),
            packing_material_cost=Decimal("150.00"),
            packing_labor_cost=Decimal("100.00"),
            actor="USR-OWNER-01",
        )
        self.assertEqual(pack_v["total_debit"], 1500.0)
        self.assertEqual(pack_v["total_credit"], 1500.0)

        # 6. Sales Invoice
        sale_v = post_sale_journal(
            {"sale_id": "SALE-001", "bill_number": "BILL-101", "bill_total": 1100.0, "payment_method": "CASH", "customer_name_snapshot": "Adarsh Kirana"},
            estimated_cogs=Decimal("600.00"),  # 20 packets * Rs 30 cost
            actor="USR-SALES-01",
        )
        self.assertEqual(sale_v["total_debit"], 1700.0)
        self.assertEqual(sale_v["total_credit"], 1700.0)

        # 7. Daily Closing Remittance
        close_v = post_daily_closing_cash_remittance_journal(
            {"closing_id": "CLOSE-001", "physical_cash_returned": 1100.0, "salesman_user_id": "USR-SALES-01"},
            actor="USR-SALES-01",
        )
        self.assertEqual(close_v["total_debit"], 1100.0)
        self.assertEqual(close_v["total_credit"], 1100.0)

        # 8. Trial Balance Verification
        tb = calculate_trial_balance()
        self.assertTrue(tb["is_balanced"])
        self.assertEqual(tb["difference"], 0.0)
        self.assertGreater(tb["grand_total_debit"], 0.0)
        self.assertEqual(tb["grand_total_debit"], tb["grand_total_credit"])

        # 9. Profit & Loss Verification
        pnl = calculate_profit_and_loss()
        self.assertEqual(pnl["total_revenue"], 1100.0)
        self.assertEqual(pnl["total_cogs"], 600.0)
        self.assertEqual(pnl["gross_profit"], 500.0)
        self.assertEqual(pnl["net_operating_profit"], 500.0)

        # 10. Balance Sheet Verification
        bs = calculate_balance_sheet()
        self.assertTrue(bs["is_balanced"])
        self.assertEqual(bs["balance_difference"], 0.0)
        self.assertEqual(bs["total_assets"], bs["total_liabilities_and_equity"])


if __name__ == "__main__":
    unittest.main()
