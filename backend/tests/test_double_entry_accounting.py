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

    def test_scenario_a_purchase_and_milling(self):
        """Scenario A: Raw material purchase with landed costs and milling into flour."""
        # 1. Purchase consignment: 500 kg Whole Moong Dal @ ₹105 + ₹1,000 freight
        rcv = post_receipt_journal({
            "raw_material_txn_id": "RML-PUR-501",
            "material_name": "Whole Moong Dal",
            "quantity": 500.0,
            "purchase_rate": 105.0,
            "freight_amount": 1000.0,
            "gst_amount": 0.0,
            "supplier_name": "Agro Grain Traders",
            "invoice_number": "AGT-909",
        }, "USR-OWNER-01")
        self.assertEqual(rcv["voucher_type"], "PURCHASE")
        self.assertEqual(rcv["total_debit"], 53500.0)  # (500*105) + 1000
        self.assertEqual(rcv["total_credit"], 53500.0)

        # 2. Mill 500 kg into 490 kg flour with ₹1,200 grinding electricity/labor
        mill = post_milling_journal({
            "milling_batch_id": "MIL-501",
            "input_quantity_kg": 500.0,
            "flour_output_kg": 490.0,
            "source_unit_rate": 107.0,  # 53500 / 500
            "milling_expenses": 1200.0,
        }, "USR-OPERATOR-01")
        self.assertEqual(mill["voucher_type"], "MANUFACTURING")
        self.assertEqual(mill["total_debit"], 54700.0)  # 53500 dal + 1200 expense
        self.assertEqual(mill["total_credit"], 54700.0)

        tb = calculate_trial_balance()
        self.assertTrue(tb["is_balanced"])

    def test_scenario_b_production_and_packaging(self):
        """Scenario B: Papad dough bulk production and packet packaging."""
        # Seed flour & spices
        post_journal_voucher("OPENING", "OPENING_BALANCE", "OP-01", "Opening inventory", [
            {"account_code": "1220", "debit_amount": 10000.0, "credit_amount": 0.0},
            {"account_code": "1215", "debit_amount": 2000.0, "credit_amount": 0.0},
            {"account_code": "1250", "debit_amount": 1500.0, "credit_amount": 0.0},
            {"account_code": "3100", "debit_amount": 0.0, "credit_amount": 13500.0},
        ], "USR-OWNER-01")

        # 1. Produce 50 kg bulk papad
        prod = post_production_batch_journal(
            {"production_id": "PRB-B01", "net_quantity_kg": 50.0, "product_name_snapshot": "Moong Papad"},
            flour_cost=Decimal("5000.00"),
            spice_cost=Decimal("800.00"),
            labor_cost=Decimal("700.00"),
            actor="USR-OPERATOR-01",
        )
        self.assertEqual(prod["total_debit"], 6500.0)
        self.assertEqual(prod["total_credit"], 6500.0)

        # 2. Package 50 kg into 100 packets of 500g
        pack = post_packaging_batch_journal(
            {"packaging_id": "PKG-B01", "total_packets": 100, "bulk_kg_used": 50.0, "product_name_snapshot": "Moong Papad"},
            bulk_cost=Decimal("6500.00"),
            packing_material_cost=Decimal("500.00"),
            packing_labor_cost=Decimal("300.00"),
            actor="USR-OPERATOR-01",
        )
        self.assertEqual(pack["total_debit"], 7300.0)
        self.assertEqual(pack["total_credit"], 7300.0)

        tb = calculate_trial_balance()
        self.assertTrue(tb["is_balanced"])

    def test_scenario_c_cash_sale_and_settlement(self):
        """Scenario C: Cash sale on route and evening remittance to factory safe."""
        # Seed finished goods
        post_journal_voucher("OPENING", "OPENING_BALANCE", "OP-02", "Opening stock", [
            {"account_code": "1240", "debit_amount": 15000.0, "credit_amount": 0.0},
            {"account_code": "3100", "debit_amount": 0.0, "credit_amount": 15000.0},
        ], "USR-OWNER-01")

        # 1. Cash sale: ₹3,500 bill total, COGS = ₹2,100
        sale = post_sale_journal({
            "sale_id": "SALE-C01",
            "bill_number": "BILL-C01",
            "bill_total": 3500.0,
            "payment_method": "CASH",
            "customer_name_snapshot": "Shree Ram Store",
        }, estimated_cogs=Decimal("2100.00"), actor="USR-SALES-01")
        self.assertEqual(sale["total_debit"], 5600.0)  # 3500 van cash + 2100 cogs
        self.assertEqual(sale["total_credit"], 5600.0)  # 3500 revenue + 2100 finished goods

        # 2. Daily closing remittance of ₹3,500 to factory safe
        close = post_daily_closing_cash_remittance_journal({
            "closing_id": "CLOSE-C01",
            "physical_cash_returned": 3500.0,
            "salesman_user_id": "USR-SALES-01",
        }, actor="USR-SALES-01")
        self.assertEqual(close["total_debit"], 3500.0)
        self.assertEqual(close["total_credit"], 3500.0)

        tb = calculate_trial_balance()
        self.assertTrue(tb["is_balanced"])
        # Check that van float is now 0.0 and factory safe has ₹3,500
        lines = tb["lines"]
        safe_line = next(l for l in lines if l["account_code"] == "1110")
        van_line = next(l for l in lines if l["account_code"] == "1115")
        self.assertEqual(safe_line["net_debit"], 3500.0)
        self.assertEqual(van_line["net_debit"], 0.0)

    def test_scenario_d_credit_sale_and_debtor_collection(self):
        """Scenario D: Credit sale to retailer with later payment collection."""
        from app.accounting.postings import post_payment_collection_journal

        # Seed finished goods
        post_journal_voucher("OPENING", "OPENING_BALANCE", "OP-03", "Opening stock", [
            {"account_code": "1240", "debit_amount": 10000.0, "credit_amount": 0.0},
            {"account_code": "3100", "debit_amount": 0.0, "credit_amount": 10000.0},
        ], "USR-OWNER-01")

        # 1. Credit sale: ₹5,000 on credit (payment_method="CREDIT"), COGS = ₹3,000
        sale = post_sale_journal({
            "sale_id": "SALE-D01",
            "bill_number": "BILL-D01",
            "bill_total": 5000.0,
            "payment_method": "CREDIT",
            "customer_name_snapshot": "Gupta Kirana",
        }, estimated_cogs=Decimal("3000.00"), actor="USR-SALES-01")

        tb1 = calculate_trial_balance()
        self.assertTrue(tb1["is_balanced"])
        debtor_line = next(l for l in tb1["lines"] if l["account_code"] == "1130")
        self.assertEqual(debtor_line["net_debit"], 5000.0)

        # 2. Customer pays ₹5,000 via UPI (Bank 1120)
        pay = post_payment_collection_journal({
            "payment_id": "PAY-D01",
            "sale_id": "SALE-D01",
            "amount": 5000.0,
            "payment_method": "UPI",
        }, actor="USR-SALES-01")
        self.assertEqual(pay["total_debit"], 5000.0)
        self.assertEqual(pay["total_credit"], 5000.0)

        tb2 = calculate_trial_balance()
        self.assertTrue(tb2["is_balanced"])
        debtor_line_after = next(l for l in tb2["lines"] if l["account_code"] == "1130")
        bank_line = next(l for l in tb2["lines"] if l["account_code"] == "1120")
        self.assertEqual(debtor_line_after["net_debit"], 0.0)  # Fully cleared
        self.assertEqual(bank_line["net_debit"], 5000.0)

    def test_scenario_e_failure_and_idempotent_recovery(self):
        """Scenario E: Interrupted write simulation and idempotent recovery."""
        receipt_data = {
            "raw_material_txn_id": "RML-RETRY-01",
            "material_name": "Whole Urad Dal",
            "quantity": 200.0,
            "purchase_rate": 120.0,
            "freight_amount": 500.0,
            "supplier_name": "Shakti Agro",
        }
        # First attempt: posts journal voucher
        v1 = post_receipt_journal(receipt_data, "USR-OWNER-01")
        self.assertFalse(v1["is_replay"])
        headers_count = len(db.memory_store["JournalHeaders"])
        lines_count = len(db.memory_store["JournalLines"])

        # Second attempt (replay after network blip): returns identical voucher without creating duplicate lines
        v2 = post_receipt_journal(receipt_data, "USR-OWNER-01")
        self.assertTrue(v2["is_replay"])
        self.assertEqual(v2["journal_id"], v1["journal_id"])
        self.assertEqual(len(db.memory_store["JournalHeaders"]), headers_count)
        self.assertEqual(len(db.memory_store["JournalLines"]), lines_count)

    def test_scenario_f_reversal_voucher_traceability(self):
        """Scenario F: Cancellation of sale invoice generates balanced compensating reversal voucher."""
        # 1. Post initial sale
        sale = post_sale_journal({
            "sale_id": "SALE-REV-01",
            "bill_number": "BILL-REV-01",
            "bill_total": 2000.0,
            "payment_method": "CASH",
            "customer_name_snapshot": "Kalyan Store",
        }, estimated_cogs=Decimal("1200.00"), actor="USR-SALES-01")

        # 2. Reverse sale voucher
        rev = reverse_journal_voucher(
            journal_id=sale["journal_id"],
            reason="Customer returned goods / bill cancelled",
            reversed_by="USR-OWNER-01",
        )
        self.assertEqual(rev["voucher_type"], "REVERSAL")
        self.assertEqual(rev["reference_id"], sale["journal_id"])

        # 3. Check trial balance after reversal: net revenue and net cogs must be 0
        tb = calculate_trial_balance()
        self.assertTrue(tb["is_balanced"])
        pnl = calculate_profit_and_loss()
        self.assertEqual(pnl["total_revenue"], 0.0)
        self.assertEqual(pnl["total_cogs"], 0.0)
        self.assertEqual(pnl["net_operating_profit"], 0.0)

    def test_scenario_g_financial_reporting_integrity(self):
        """Scenario G: Comprehensive financial reporting verification (Trial Balance, P&L, Balance Sheet)."""
        # Post Capital
        post_journal_voucher("RECEIPT", "CAPITAL", "CAP-G01", "Owner capital", [
            {"account_code": "1110", "debit_amount": 100000.0, "credit_amount": 0.0},
            {"account_code": "3100", "debit_amount": 0.0, "credit_amount": 100000.0},
        ], "USR-OWNER-01")

        # Post Inventory Purchase
        post_receipt_journal({
            "raw_material_txn_id": "RML-G01",
            "material_name": "Whole Moong Dal",
            "quantity": 100.0,
            "purchase_rate": 110.0,
            "freight_amount": 0.0,
            "supplier_name": "Vendor A",
        }, "USR-OWNER-01")

        # Post Sale
        post_sale_journal({
            "sale_id": "SALE-G01",
            "bill_number": "BILL-G01",
            "bill_total": 5000.0,
            "payment_method": "CASH",
            "customer_name_snapshot": "Customer G",
        }, estimated_cogs=Decimal("3000.00"), actor="USR-SALES-01")

        # Post Approved Expense
        from app.accounting.postings import post_expense_journal
        post_expense_journal({
            "expense_id": "EXP-G01",
            "amount": 500.0,
            "category": "Petrol / Travel",
            "description": "Sales route petrol",
            "cash_reducing_expense": "true",
            "salesman_user_id": "USR-SALES-01",
        }, "USR-OWNER-01")

        # 1. Trial Balance Check
        tb = calculate_trial_balance()
        self.assertTrue(tb["is_balanced"])
        self.assertEqual(tb["difference"], 0.0)

        # 2. Profit & Loss Check
        # Revenue = ₹5,000, COGS = ₹3,000, Expense = ₹500 -> Net Profit = ₹1,500
        pnl = calculate_profit_and_loss()
        self.assertEqual(pnl["total_revenue"], 5000.0)
        self.assertEqual(pnl["total_cogs"], 3000.0)
        self.assertEqual(pnl["total_operating_expenses"], 500.0)
        self.assertEqual(pnl["net_operating_profit"], 1500.0)

        # 3. Balance Sheet Check
        # Assets == Liabilities + Equity (including Net Profit)
        bs = calculate_balance_sheet()
        self.assertTrue(bs["is_balanced"])
        self.assertEqual(bs["balance_difference"], 0.0)
        self.assertEqual(bs["total_assets"], bs["total_liabilities_and_equity"])


if __name__ == "__main__":
    unittest.main()

