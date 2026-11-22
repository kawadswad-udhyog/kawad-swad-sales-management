"""
Mission 51B-1R — TX-FINAL-08 Regression Suite: Incomplete Transaction Readback Verification.

Verifies `check_transaction_status()` and `_verify_readback()`:
- Allocation match alone, AuditLog match alone, or BillNumbers allocation alone NEVER returns CONFIRMED_RECORDED.
- CREATE_SALE requires Sales row + SaleItems (matching total) + SalesmanStockLedger + posted balanced SALES journal.
- RECORD_SALE_PAYMENT requires Payments row + posted balanced RECEIPT journal.
- POST_JOURNAL_VOUCHER requires JournalHeaders row + >=2 balanced JournalLines matching header totals.
- Complete valid records return CONFIRMED_RECORDED; incomplete/mismatched records return RECOVERY_REQUIRED.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import tests  # noqa: F401 - activates offline fastapi shim

from app import apps_script_bridge as bridge_mod
from app.accounting.transaction_coordinator import TransactionCoordinator
from app.apps_script_bridge import AppsScriptBridge


def _complete_sale_tables(nonce: str):
    return {
        "IdAllocations": [
            {"nonce": nonce, "tab_name": "Sales", "allocated_id": "SAL-000100", "created_at": "2026-11-21T11:00:00+05:30"},
        ],
        "AuditLog": [
            {"audit_id": "AUD-100", "action": "CREATE_SALE", "entity_type": "Sales", "entity_id": "SAL-000100", "related_record_id": nonce},
        ],
        "Sales": [
            {"sale_id": "SAL-000100", "subtotal": 2000.0, "bill_total": 2000.0, "payment_mode": "CASH", "payment_status": "PAID"},
        ],
        "SaleItems": [
            {"sale_item_id": "SI-1", "sale_id": "SAL-000100", "product_id": "PRD-1", "quantity": 20, "line_total": 2000.0},
        ],
        "SalesmanStockLedger": [
            {"ledger_id": "SL-1", "related_sale_id": "SAL-000100", "product_id": "PRD-1", "quantity_change": -20},
        ],
        "JournalHeaders": [
            {
                "journal_id": "JV-000100",
                "voucher_type": "SALES",
                "reference_type": "SALE_INVOICE",
                "reference_id": "SAL-000100",
                "status": "POSTED",
                "total_debit": 2000.0,
                "total_credit": 2000.0,
            }
        ],
        "JournalLines": [
            {"line_id": "JL-1", "journal_id": "JV-000100", "account_code": "1115", "debit_amount": 2000.0, "credit_amount": 0.0},
            {"line_id": "JL-2", "journal_id": "JV-000100", "account_code": "4100", "debit_amount": 0.0, "credit_amount": 2000.0},
        ],
    }


def _complete_payment_tables(nonce: str):
    return {
        "IdAllocations": [
            {"nonce": nonce, "tab_name": "Payments", "allocated_id": "RCPT-000200", "created_at": "2026-11-21T11:10:00+05:30"},
        ],
        "AuditLog": [
            {"audit_id": "AUD-200", "action": "RECORD_SALE_PAYMENT", "entity_type": "Payments", "entity_id": "RCPT-000200", "related_record_id": nonce},
        ],
        "Payments": [
            {"payment_id": "RCPT-000200", "sale_id": "SAL-000100", "amount": 1200.0, "payment_mode": "UPI"},
        ],
        "JournalHeaders": [
            {
                "journal_id": "JV-000200",
                "voucher_type": "RECEIPT",
                "reference_type": "PAYMENT_COLLECTION",
                "reference_id": "RCPT-000200",
                "status": "POSTED",
                "total_debit": 1200.0,
                "total_credit": 1200.0,
            }
        ],
        "JournalLines": [
            {"line_id": "JL-10", "journal_id": "JV-000200", "account_code": "1120", "debit_amount": 1200.0, "credit_amount": 0.0},
            {"line_id": "JL-11", "journal_id": "JV-000200", "account_code": "1130", "debit_amount": 0.0, "credit_amount": 1200.0},
        ],
    }


def _complete_journal_tables(nonce: str):
    return {
        "IdAllocations": [
            {"nonce": nonce, "tab_name": "JournalHeaders", "allocated_id": "JV-000300", "created_at": "2026-11-21T11:20:00+05:30"},
        ],
        "AuditLog": [
            {"audit_id": "AUD-300", "action": "POST_JOURNAL_VOUCHER", "entity_type": "JournalHeaders", "entity_id": "JV-000300", "related_record_id": nonce},
        ],
        "JournalHeaders": [
            {
                "journal_id": "JV-000300",
                "voucher_type": "JOURNAL",
                "status": "POSTED",
                "total_debit": 500.0,
                "total_credit": 500.0,
            }
        ],
        "JournalLines": [
            {"line_id": "JL-20", "journal_id": "JV-000300", "account_code": "1115", "debit_amount": 500.0, "credit_amount": 0.0},
            {"line_id": "JL-21", "journal_id": "JV-000300", "account_code": "4100", "debit_amount": 0.0, "credit_amount": 500.0},
        ],
    }


class TestTxFinal08ReadbackCompleteness(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="ks_tx08_")
        self.db_path = os.path.join(self.tmp_dir, "coord_tx08.db")
        self.coord = TransactionCoordinator(
            db_path=self.db_path,
            testing=True,
            auto_recover_stale_leases=False,
        )
        self.bridge = AppsScriptBridge()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _check_status(self, nonce: str, tables: dict):
        with (
            patch.object(bridge_mod, "tx_coordinator", self.coord),
            patch.object(bridge_mod.db, "get_records", side_effect=lambda tab, fresh=False: list(tables.get(tab, []))),
            patch.object(bridge_mod.db, "invalidate_tab_cache", return_value=None),
        ):
            return self.bridge.check_transaction_status(nonce=nonce, actor_is_owner=True)

    def test_allocation_audit_or_billnumber_alone_never_confirms(self):
        # 1. IdAllocations match alone with no Sales row
        st1 = self._check_status(
            "NONCE-ALLOC-ONLY",
            {
                "IdAllocations": [{"nonce": "NONCE-ALLOC-ONLY", "tab_name": "Sales", "allocated_id": "SAL-999"}],
                "AuditLog": [],
                "Sales": [],
            },
        )
        self.assertEqual(st1["status"], "RECOVERY_REQUIRED")
        self.assertFalse(st1["safe_to_retry_same_nonce"])

        # 2. AuditLog match alone with no primary row
        st2 = self._check_status(
            "NONCE-AUDIT-ONLY",
            {
                "IdAllocations": [],
                "AuditLog": [{"action": "CREATE_SALE", "entity_type": "Sales", "entity_id": "SAL-998", "related_record_id": "NONCE-AUDIT-ONLY"}],
                "Sales": [],
            },
        )
        self.assertEqual(st2["status"], "RECOVERY_REQUIRED")
        self.assertFalse(st2["safe_to_retry_same_nonce"])

        # 3. BillNumbers allocation alone without resolvable target tab
        st3 = self._check_status(
            "NONCE-BILLNO-ONLY",
            {
                "IdAllocations": [{"nonce": "NONCE-BILLNO-ONLY", "tab_name": "BillNumbers", "allocated_id": "KS-2026-0001"}],
                "AuditLog": [],
            },
        )
        self.assertEqual(st3["status"], "RECOVERY_REQUIRED")
        self.assertFalse(st3["safe_to_retry_same_nonce"])

    def test_create_sale_readback_rejects_partial_and_confirms_complete(self):
        nonce = "NONCE-SALE-RB"
        # Complete valid sale -> CONFIRMED_RECORDED
        ok = self._check_status(nonce, _complete_sale_tables(nonce))
        self.assertEqual(ok["status"], "CONFIRMED_RECORDED")

        # Missing SaleItems / Missing SalesmanStockLedger / Mismatched line_total / Malformed line_total / Missing journal / Imbalanced journal
        defects = [
            ("missing_sale_items", lambda t: t["SaleItems"].clear()),
            ("missing_stock_ledger", lambda t: t["SalesmanStockLedger"].clear()),
            ("mismatched_line_total", lambda t: t["SaleItems"][0].update({"line_total": 1500.0})),
            ("malformed_line_total", lambda t: t["SaleItems"][0].update({"line_total": "NOT_A_NUM"})),
            ("missing_journal", lambda t: t["JournalHeaders"].clear()),
            ("imbalanced_journal", lambda t: t["JournalLines"][1].update({"credit_amount": 1800.0})),
        ]
        for label, mutator in defects:
            with self.subTest(defect=label):
                tables = _complete_sale_tables(nonce)
                mutator(tables)
                res = self._check_status(nonce, tables)
                self.assertEqual(res["status"], "RECOVERY_REQUIRED", f"{label} must NOT confirm")
                self.assertFalse(res["safe_to_retry_same_nonce"])

    def test_record_sale_payment_and_journal_voucher_readback_completeness(self):
        pay_nonce = "NONCE-PAY-RB"
        self.assertEqual(self._check_status(pay_nonce, _complete_payment_tables(pay_nonce))["status"], "CONFIRMED_RECORDED")

        bad_pay = _complete_payment_tables(pay_nonce)
        bad_pay["JournalHeaders"].clear()
        self.assertEqual(self._check_status(pay_nonce, bad_pay)["status"], "RECOVERY_REQUIRED")

        jv_nonce = "NONCE-JV-RB"
        self.assertEqual(self._check_status(jv_nonce, _complete_journal_tables(jv_nonce))["status"], "CONFIRMED_RECORDED")

        jv_defects = [
            ("single_line", lambda t: t["JournalLines"].pop()),
            ("unbalanced_lines", lambda t: t["JournalLines"][1].update({"credit_amount": 400.0})),
            ("header_total_mismatch", lambda t: t["JournalHeaders"][0].update({"total_debit": 600.0, "total_credit": 600.0})),
        ]
        for label, mutator in jv_defects:
            with self.subTest(defect=label):
                tables = _complete_journal_tables(jv_nonce)
                mutator(tables)
                res = self._check_status(jv_nonce, tables)
                self.assertEqual(res["status"], "RECOVERY_REQUIRED", f"{label} must return RECOVERY_REQUIRED")


if __name__ == "__main__":
    unittest.main()
