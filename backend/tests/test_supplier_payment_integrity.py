"""
Kawad Swad ERP - Supplier Payment Integrity, Advance Reconciliation & Reference Integrity Suite
Tests:
 1. Bill-linked full payment
 2. Partial bill payment
 3. Multiple payments closing one bill
 4. General / On-Account advance payment without bill_id
 5. Advance payment reconciled against a subsequent bill (single payment, no double accounting)
 6. Invalid supplier rejection
 7. Invalid bill rejection
 8. Bill belonging to another supplier rejection
 9. Overpayment exceeding bill balance rejection
10. Zero and negative payment amounts rejection
11. Idempotent retry without duplicate payment / bill deduction / journal
12. Conflicting payload on same idempotency_key rejected (409)
13. Retry after injected SupplierBills and JournalHeaders failures
14. Creditor / Purchasing summary balance accuracy across advances, partial & reconciled bills
15. Accounting journal debit == credit correctness & trial balance zero variance
16. Reference integrity (CASH optional blank, non-cash external ref required, verbatim replay, no PAY-xxxxxx)
"""

import asyncio
import os
import sys
import threading
import unittest
from fastapi import HTTPException

tests_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.abspath(os.path.join(tests_dir, ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)
if tests_dir not in sys.path:
    sys.path.insert(0, tests_dir)

os.environ["SALES_TESTING"] = "1"
os.environ["SALES_AUTH_MOCK"] = "1"

import tests
from app.sheets import db, ID_PREFIXES, StorageIOError
from app.accounting.customer_ledger import reset_cross_process_state
from app.accounting.journal_engine import calculate_trial_balance
from app.routers.purchasing import (
    SupplierBillCreate,
    SupplierPaymentCreate,
    SupplierAdvanceApplyRequest,
    create_supplier_bill as _raw_create_supplier_bill,
    record_supplier_payment as _raw_record_supplier_payment,
    apply_supplier_advance_to_bill as _raw_apply_supplier_advance_to_bill,
    list_supplier_payments,
    purchasing_summary,
)
from app.routers.accounting import get_supplier_outstanding_balances
from tests.v2_test_harness import LocalAppsScriptSimulator, make_test_request


async def create_supplier_bill(req, request=None, user=None):
    return await _raw_create_supplier_bill(req, request=request or make_test_request(), user=user)


async def record_supplier_payment(req, request=None, user=None):
    nonce = getattr(req, "idempotency_key", None) or None
    return await _raw_record_supplier_payment(req, request=request or make_test_request(nonce=nonce), user=user)


async def apply_supplier_advance_to_bill(payment_id, req, request=None, user=None):
    nonce = getattr(req, "idempotency_key", None) or None
    return await _raw_apply_supplier_advance_to_bill(payment_id, req, request=request or make_test_request(nonce=nonce), user=user)


class TestSupplierPaymentIntegrity(unittest.TestCase):
    def setUp(self):
        self._orig_connected = db.is_connected
        self._orig_fallback = db.allow_in_memory_fallback
        db.is_connected = False
        db.allow_in_memory_fallback = True
        db._records_cache.clear()
        db._worksheets.clear()
        db._fail_once.clear()
        reset_cross_process_state()
        db.memory_store = {name: [] for name in list(ID_PREFIXES) + ["Settings"]}
        self._sim = LocalAppsScriptSimulator().start()

        db.append_record("Suppliers", {
            "supplier_id": "SUP-001",
            "supplier_name": "Bikaner Pulse Traders",
            "contact_person": "Ramlal",
            "mobile": "9829011111",
            "email": "ramlal@bikanerpulse.example",
            "city": "Bikaner",
            "active": "true",
        })
        db.append_record("Suppliers", {
            "supplier_id": "SUP-002",
            "supplier_name": "Indore Spice Mills",
            "contact_person": "Mahesh",
            "mobile": "9826022222",
            "email": "sales@indorespice.example",
            "city": "Indore",
            "active": "true",
        })

        self.owner_user = {"user_id": "USR-OWNER-01", "username": "owner_ramesh", "role": "OWNER"}
        self.pa_user = {"user_id": "USR-PA-01", "username": "pa_suresh", "role": "PA"}

    def tearDown(self):
        self._sim.stop()
        reset_cross_process_state()
        db._fail_once.clear()
        db._records_cache.clear()
        db._worksheets.clear()
        db.is_connected = self._orig_connected
        db.allow_in_memory_fallback = self._orig_fallback

    def _create_bill(self, supplier_id: str, bill_number: str, total_amount: float) -> dict:
        return asyncio.run(
            create_supplier_bill(
                SupplierBillCreate(
                    supplier_id=supplier_id,
                    bill_number=bill_number,
                    bill_date="2026-11-10",
                    due_date="2026-11-25",
                    subtotal=total_amount,
                    tax_amount=0.0,
                    total_amount=total_amount,
                ),
                user=self.owner_user,
            )
        )

    def test_01_bill_linked_full_payment(self):
        bill = self._create_bill("SUP-001", "INV-1001", 12500.0)
        res = asyncio.run(
            record_supplier_payment(
                SupplierPaymentCreate(
                    supplier_id="SUP-001",
                    bill_id=bill["bill_id"],
                    amount=12500.0,
                    payment_method="BANK_TRANSFER",
                    reference_number="UTR-FULL-1001",
                    idempotency_key="spay-full-1",
                ),
                user=self.owner_user,
            )
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["bill_status"], "PAID")
        self.assertEqual(res["remaining_balance"], 0.0)
        self.assertEqual(res["payment"]["payment_type"], "BILL_PAYMENT")
        self.assertEqual(res["payment"]["allocated_amount"], 12500.0)
        self.assertEqual(res["payment"]["unallocated_amount"], 0.0)

        bills = db.get_records("SupplierBills", fresh=True)
        self.assertEqual(bills[0]["payment_status"], "PAID")
        self.assertEqual(float(bills[0]["paid_amount"]), 12500.0)
        self.assertEqual(float(bills[0]["balance_amount"]), 0.0)

    def test_02_partial_bill_payment(self):
        bill = self._create_bill("SUP-001", "INV-1002", 10000.0)
        res = asyncio.run(
            record_supplier_payment(
                SupplierPaymentCreate(
                    supplier_id="SUP-001",
                    bill_id=bill["bill_id"],
                    amount=4000.0,
                    payment_method="UPI",
                    reference_number="UPI-PART-4000",
                    idempotency_key="spay-part-1",
                ),
                user=self.owner_user,
            )
        )
        self.assertEqual(res["bill_status"], "PARTIALLY_PAID")
        self.assertEqual(res["remaining_balance"], 6000.0)

        bills = db.get_records("SupplierBills", fresh=True)
        self.assertEqual(float(bills[0]["paid_amount"]), 4000.0)
        self.assertEqual(float(bills[0]["balance_amount"]), 6000.0)
        self.assertEqual(bills[0]["payment_status"], "PARTIALLY_PAID")

    def test_03_multiple_payments_closing_one_bill(self):
        bill = self._create_bill("SUP-001", "INV-1003", 10000.0)
        r1 = asyncio.run(
            record_supplier_payment(
                SupplierPaymentCreate(
                    supplier_id="SUP-001",
                    bill_id=bill["bill_id"],
                    amount=4000.0,
                    payment_method="CASH",
                    reference_number="",
                    idempotency_key="spay-multi-1",
                ),
                user=self.owner_user,
            )
        )
        self.assertEqual(r1["remaining_balance"], 6000.0)

        r2 = asyncio.run(
            record_supplier_payment(
                SupplierPaymentCreate(
                    supplier_id="SUP-001",
                    bill_id=bill["bill_id"],
                    amount=6000.0,
                    payment_method="NEFT",
                    reference_number="NEFT-FINAL-6000",
                    idempotency_key="spay-multi-2",
                ),
                user=self.owner_user,
            )
        )
        self.assertEqual(r2["bill_status"], "PAID")
        self.assertEqual(r2["remaining_balance"], 0.0)

        # Further payment on closed bill must be rejected
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                record_supplier_payment(
                    SupplierPaymentCreate(
                        supplier_id="SUP-001",
                        bill_id=bill["bill_id"],
                        amount=100.0,
                        payment_method="CASH",
                        idempotency_key="spay-multi-over",
                    ),
                    user=self.owner_user,
                )
            )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_04_on_account_advance_without_bill(self):
        res = asyncio.run(
            record_supplier_payment(
                SupplierPaymentCreate(
                    supplier_id="SUP-001",
                    bill_id="",
                    amount=5000.0,
                    payment_method="BANK_TRANSFER",
                    reference_number="UTR-ADV-5000",
                    idempotency_key="spay-adv-1",
                ),
                user=self.owner_user,
            )
        )
        self.assertTrue(res["ok"])
        self.assertEqual(res["payment_type"], "ON_ACCOUNT")
        self.assertEqual(res["bill_status"], "ON_ACCOUNT")
        self.assertEqual(res["payment"]["bill_id"], "")
        self.assertEqual(res["payment"]["allocated_amount"], 0.0)
        self.assertEqual(res["payment"]["unallocated_amount"], 5000.0)

        headers = db.get_records("JournalHeaders", fresh=True)
        self.assertEqual(len(headers), 1)
        self.assertIn("[On-Account]", headers[0]["narration"])

    def test_05_advance_reconciled_to_subsequent_bill_without_double_posting(self):
        # 1. Advance ₹5,000 paid first
        adv = asyncio.run(
            record_supplier_payment(
                SupplierPaymentCreate(
                    supplier_id="SUP-001",
                    bill_id=None,
                    amount=5000.0,
                    payment_method="UPI",
                    reference_number="UPI-ADV-9001",
                    idempotency_key="spay-adv-rec-1",
                ),
                user=self.owner_user,
            )
        )
        pay_id = adv["payment"]["payment_id"]

        # 2. Bill ₹8,000 booked later
        bill = self._create_bill("SUP-001", "INV-LATER-8000", 8000.0)

        # 3. Reconcile ₹5,000 advance onto the ₹8,000 bill
        applied = asyncio.run(
            apply_supplier_advance_to_bill(
                payment_id=pay_id,
                req=SupplierAdvanceApplyRequest(
                    bill_id=bill["bill_id"],
                    amount=5000.0,
                    idempotency_key="alloc-1",
                ),
                user=self.owner_user,
            )
        )
        self.assertTrue(applied["ok"])
        self.assertFalse(applied["is_replay"])
        self.assertEqual(applied["applied_amount"], 5000.0)
        self.assertEqual(applied["remaining_advance"], 0.0)
        self.assertEqual(float(applied["bill"]["paid_amount"]), 5000.0)
        self.assertEqual(float(applied["bill"]["balance_amount"]), 3000.0)
        self.assertEqual(applied["bill"]["payment_status"], "PARTIALLY_PAID")

        # 4. Must NOT create duplicate payment row or duplicate GL voucher!
        self.assertEqual(len(db.get_records("SupplierPayments", fresh=True)), 1)
        self.assertEqual(len(db.get_records("JournalHeaders", fresh=True)), 1)

        # 5. Replaying same allocation idempotency_key is idempotent
        replay = asyncio.run(
            apply_supplier_advance_to_bill(
                payment_id=pay_id,
                req=SupplierAdvanceApplyRequest(
                    bill_id=bill["bill_id"],
                    amount=5000.0,
                    idempotency_key="alloc-1",
                ),
                user=self.owner_user,
            )
        )
        self.assertTrue(replay["is_replay"])
        bills = db.get_records("SupplierBills", fresh=True)
        self.assertEqual(float(bills[0]["balance_amount"]), 3000.0)

        # 6. Trying to re-apply exhausted advance fails
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                apply_supplier_advance_to_bill(
                    payment_id=pay_id,
                    req=SupplierAdvanceApplyRequest(
                        bill_id=bill["bill_id"],
                        amount=100.0,
                        idempotency_key="alloc-2",
                    ),
                    user=self.owner_user,
                )
            )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_06_invalid_supplier_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                record_supplier_payment(
                    SupplierPaymentCreate(
                        supplier_id="SUP-DOES-NOT-EXIST",
                        bill_id="",
                        amount=1000.0,
                        payment_method="CASH",
                    ),
                    user=self.owner_user,
                )
            )
        self.assertEqual(ctx.exception.status_code, 404)

    def test_07_invalid_bill_rejected(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                record_supplier_payment(
                    SupplierPaymentCreate(
                        supplier_id="SUP-001",
                        bill_id="SBILL-MISSING",
                        amount=1000.0,
                        payment_method="CASH",
                    ),
                    user=self.owner_user,
                )
            )
        self.assertEqual(ctx.exception.status_code, 404)

    def test_08_bill_belonging_to_other_supplier_rejected(self):
        other_bill = self._create_bill("SUP-002", "INV-OTHER-2", 5000.0)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                record_supplier_payment(
                    SupplierPaymentCreate(
                        supplier_id="SUP-001",
                        bill_id=other_bill["bill_id"],
                        amount=1000.0,
                        payment_method="CASH",
                    ),
                    user=self.owner_user,
                )
            )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_09_overpayment_rejected(self):
        bill = self._create_bill("SUP-001", "INV-OVER-1", 3000.0)
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(
                record_supplier_payment(
                    SupplierPaymentCreate(
                        supplier_id="SUP-001",
                        bill_id=bill["bill_id"],
                        amount=3500.0,
                        payment_method="UPI",
                        reference_number="UPI-OVER-3500",
                    ),
                    user=self.owner_user,
                )
            )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_10_zero_and_negative_amounts_rejected(self):
        import pydantic
        ValidationError = getattr(pydantic, "ValidationError", ValueError)
        for bad_amt in (0.0, -250.0):
            with self.assertRaises((ValidationError, ValueError, HTTPException)):
                payload = SupplierPaymentCreate(
                    supplier_id="SUP-001",
                    bill_id="",
                    amount=bad_amt,
                    payment_method="CASH",
                )
                asyncio.run(record_supplier_payment(payload, user=self.owner_user))

    def test_11_idempotent_retry_prevents_duplicates(self):
        bill = self._create_bill("SUP-001", "INV-IDEMP-1", 7000.0)
        req = SupplierPaymentCreate(
            supplier_id="SUP-001",
            bill_id=bill["bill_id"],
            amount=3000.0,
            payment_method="UPI",
            reference_number="UPI-IDEMP-3000",
            idempotency_key="retry-key-01",
        )
        first = asyncio.run(record_supplier_payment(req, user=self.owner_user))
        second = asyncio.run(record_supplier_payment(req, user=self.owner_user))
        self.assertFalse(first["is_replay"])
        self.assertTrue(second["is_replay"])
        self.assertEqual(first["payment"]["payment_id"], second["payment"]["payment_id"])
        self.assertEqual(len(db.get_records("SupplierPayments", fresh=True)), 1)
        self.assertEqual(len(db.get_records("JournalHeaders", fresh=True)), 1)
        bills = db.get_records("SupplierBills", fresh=True)
        self.assertEqual(float(bills[0]["paid_amount"]), 3000.0)
        self.assertEqual(float(bills[0]["balance_amount"]), 4000.0)

    def test_12_idempotency_key_conflict_rejected_409(self):
        req1 = SupplierPaymentCreate(
            supplier_id="SUP-001",
            bill_id="",
            amount=2000.0,
            payment_method="CASH",
            idempotency_key="conflict-key-1",
        )
        asyncio.run(record_supplier_payment(req1, user=self.owner_user))

        req2 = SupplierPaymentCreate(
            supplier_id="SUP-001",
            bill_id="",
            amount=2500.0,  # Conflicting amount
            payment_method="CASH",
            idempotency_key="conflict-key-1",
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(record_supplier_payment(req2, user=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 409)

    def test_13_failure_injection_recovery_for_bill_update_and_journal_write(self):
        # Case A: Fail SupplierBills update after SupplierPayments row created INCOMPLETE
        bill_a = self._create_bill("SUP-001", "INV-FAIL-A", 6000.0)
        req_a = SupplierPaymentCreate(
            supplier_id="SUP-001",
            bill_id=bill_a["bill_id"],
            amount=2500.0,
            payment_method="BANK_TRANSFER",
            reference_number="UTR-FAIL-A",
            idempotency_key="fail-rec-a",
        )
        db.inject_failure_once("SupplierBills", 1)
        with self.assertRaises((RuntimeError, StorageIOError, HTTPException)):
            asyncio.run(record_supplier_payment(req_a, user=self.owner_user))

        payments_mid = db.get_records("SupplierPayments", fresh=True)
        self.assertEqual(len(payments_mid), 1)
        self.assertEqual(payments_mid[0]["status"], "INCOMPLETE")
        self.assertEqual(len(db.get_records("JournalHeaders", fresh=True)), 0)

        # Retry recovers cleanly
        rec_a = asyncio.run(record_supplier_payment(req_a, user=self.owner_user))
        self.assertTrue(rec_a["ok"])
        self.assertEqual(rec_a["payment"]["status"], "PAID")
        self.assertEqual(len(db.get_records("SupplierPayments", fresh=True)), 1)
        self.assertEqual(len(db.get_records("JournalHeaders", fresh=True)), 1)
        b_a_after = next(b for b in db.get_records("SupplierBills", fresh=True) if b["bill_id"] == bill_a["bill_id"])
        self.assertEqual(float(b_a_after["paid_amount"]), 2500.0)
        self.assertEqual(float(b_a_after["balance_amount"]), 3500.0)

        # Case B: Fail JournalHeaders write AFTER SupplierBills already deducted
        bill_b = self._create_bill("SUP-002", "INV-FAIL-B", 9000.0)
        req_b = SupplierPaymentCreate(
            supplier_id="SUP-002",
            bill_id=bill_b["bill_id"],
            amount=4000.0,
            payment_method="UPI",
            reference_number="UPI-FAIL-B",
            idempotency_key="fail-rec-b",
        )
        db.inject_failure_once("JournalHeaders", 1)
        with self.assertRaises((RuntimeError, StorageIOError, HTTPException)):
            asyncio.run(record_supplier_payment(req_b, user=self.owner_user))

        # Bill was already updated once; payment is still INCOMPLETE
        b_b_mid = next(b for b in db.get_records("SupplierBills", fresh=True) if b["bill_id"] == bill_b["bill_id"])
        self.assertEqual(float(b_b_mid["paid_amount"]), 4000.0)
        self.assertEqual(float(b_b_mid["balance_amount"]), 5000.0)

        # Retry MUST NOT deduct SupplierBills a second time, and MUST post journal & mark PAID
        rec_b = asyncio.run(record_supplier_payment(req_b, user=self.owner_user))
        self.assertTrue(rec_b["ok"])
        self.assertEqual(rec_b["payment"]["status"], "PAID")
        b_b_after = next(b for b in db.get_records("SupplierBills", fresh=True) if b["bill_id"] == bill_b["bill_id"])
        self.assertEqual(float(b_b_after["paid_amount"]), 4000.0)
        self.assertEqual(float(b_b_after["balance_amount"]), 5000.0)
        self.assertEqual(len(db.get_records("JournalHeaders", fresh=True)), 2)

    def test_14_creditor_and_purchasing_summary_balance_accuracy(self):
        # SUP-001: Advance ₹5,000 before any bill
        adv = asyncio.run(
            record_supplier_payment(
                SupplierPaymentCreate(
                    supplier_id="SUP-001",
                    bill_id="",
                    amount=5000.0,
                    payment_method="BANK_TRANSFER",
                    reference_number="UTR-CRED-ADV",
                    idempotency_key="cred-adv-1",
                ),
                user=self.owner_user,
            )
        )
        creditors_1 = asyncio.run(get_supplier_outstanding_balances(user=self.owner_user))
        sup1 = next(c for c in creditors_1 if c["supplier_id"] == "SUP-001")
        self.assertEqual(sup1["total_billed"], 0.0)
        self.assertEqual(sup1["total_paid"], 5000.0)
        self.assertEqual(sup1["advance_balance"], 5000.0)
        self.assertEqual(sup1["outstanding_payable"], -5000.0)
        self.assertEqual(sup1["net_payable"], 0.0)

        # Book Bill ₹8,000 for SUP-001 (net payable should now be ₹3,000 before formal apply, still ₹3,000 after apply!)
        bill = self._create_bill("SUP-001", "INV-CRED-1", 8000.0)
        creditors_2 = asyncio.run(get_supplier_outstanding_balances(user=self.owner_user))
        sup1_2 = next(c for c in creditors_2 if c["supplier_id"] == "SUP-001")
        self.assertEqual(sup1_2["total_billed"], 8000.0)
        self.assertEqual(sup1_2["total_paid"], 5000.0)
        self.assertEqual(sup1_2["advance_balance"], 5000.0)
        self.assertEqual(sup1_2["outstanding_payable"], 3000.0)
        self.assertEqual(sup1_2["net_payable"], 3000.0)

        summary_pre = asyncio.run(purchasing_summary(user=self.owner_user))
        self.assertEqual(summary_pre["total_billed"], 8000.0)
        self.assertEqual(summary_pre["total_paid"], 5000.0)
        self.assertEqual(summary_pre["total_advances"], 5000.0)
        self.assertEqual(summary_pre["net_payable"], 3000.0)
        self.assertEqual(summary_pre["total_payables"], 3000.0)

        # Reconcile advance -> advance_balance becomes 0, bill paid becomes 5000, net_payable remains 3000
        asyncio.run(
            apply_supplier_advance_to_bill(
                payment_id=adv["payment"]["payment_id"],
                req=SupplierAdvanceApplyRequest(bill_id=bill["bill_id"], amount=5000.0),
                user=self.owner_user,
            )
        )
        creditors_3 = asyncio.run(get_supplier_outstanding_balances(user=self.owner_user))
        sup1_3 = next(c for c in creditors_3 if c["supplier_id"] == "SUP-001")
        self.assertEqual(sup1_3["total_billed"], 8000.0)
        self.assertEqual(sup1_3["total_paid"], 5000.0)
        self.assertEqual(sup1_3["advance_balance"], 0.0)
        self.assertEqual(sup1_3["outstanding_payable"], 3000.0)

    def test_15_accounting_journal_balance_and_trial_balance(self):
        bill = self._create_bill("SUP-001", "INV-GL-1", 10000.0)
        asyncio.run(
            record_supplier_payment(
                SupplierPaymentCreate(
                    supplier_id="SUP-001",
                    bill_id=bill["bill_id"],
                    amount=4500.0,
                    payment_method="CASH",
                    reference_number="",
                    idempotency_key="gl-cash-1",
                ),
                user=self.owner_user,
            )
        )
        asyncio.run(
            record_supplier_payment(
                SupplierPaymentCreate(
                    supplier_id="SUP-001",
                    bill_id="",
                    amount=2500.0,
                    payment_method="BANK_TRANSFER",
                    reference_number="UTR-GL-2500",
                    idempotency_key="gl-bank-1",
                ),
                user=self.owner_user,
            )
        )

        lines = db.get_records("JournalLines", fresh=True)
        ap_debit = sum(float(l.get("debit_amount", 0) or 0) for l in lines if l.get("account_code") == "2100")
        cash_credit = sum(float(l.get("credit_amount", 0) or 0) for l in lines if l.get("account_code") == "1110")
        bank_credit = sum(float(l.get("credit_amount", 0) or 0) for l in lines if l.get("account_code") == "1120")

        self.assertEqual(ap_debit, 7000.0)
        self.assertEqual(cash_credit, 4500.0)
        self.assertEqual(bank_credit, 2500.0)

        tb = calculate_trial_balance()
        self.assertTrue(tb["is_balanced"])
        self.assertAlmostEqual(tb["variance"], 0.0, places=2)

    def test_16_reference_integrity_cash_vs_noncash_and_no_synthetic_prefix(self):
        # 1. CASH allows blank reference and does NOT generate PAY-xxxxxx
        cash_res = asyncio.run(
            record_supplier_payment(
                SupplierPaymentCreate(
                    supplier_id="SUP-001",
                    bill_id="",
                    amount=1200.0,
                    payment_method="CASH",
                    reference_number="",
                    idempotency_key="ref-cash-1",
                ),
                user=self.owner_user,
            )
        )
        self.assertEqual(cash_res["payment"]["reference_number"], "")
        self.assertTrue(str(cash_res["payment"]["payment_id"]).startswith("SPAY-"))

        # 2. Non-cash requires valid external reference
        for method in ("UPI", "BANK_TRANSFER", "NEFT", "CHEQUE"):
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(
                    record_supplier_payment(
                        SupplierPaymentCreate(
                            supplier_id="SUP-001",
                            bill_id="",
                            amount=1000.0,
                            payment_method=method,
                            reference_number=" ",
                            idempotency_key=f"ref-bad-{method}",
                        ),
                        user=self.owner_user,
                    )
                )
            self.assertEqual(ctx.exception.status_code, 400)

        # 3. Verbatim external reference preserved across retries
        ext_ref = "UTR-HDFC-20261115-778899"
        upi_req = SupplierPaymentCreate(
            supplier_id="SUP-001",
            bill_id="",
            amount=1500.0,
            payment_method="UPI",
            reference_number=ext_ref,
            idempotency_key="ref-upi-exact",
        )
        r_first = asyncio.run(record_supplier_payment(upi_req, user=self.owner_user))
        r_retry = asyncio.run(record_supplier_payment(upi_req, user=self.owner_user))
        self.assertEqual(r_first["payment"]["reference_number"], ext_ref)
        self.assertEqual(r_retry["payment"]["reference_number"], ext_ref)

        # 4. Ensure frontend api.ts does not synthesize PAY- reference numbers
        api_ts_path = os.path.abspath(os.path.join(backend_dir, "..", "src", "services", "api.ts"))
        with open(api_ts_path, "r", encoding="utf-8") as f:
            api_src = f.read()
        self.assertNotIn("PAY-${Date.now()", api_src)

    def _snapshot_supplier_payment_state(self, supplier_id: str, pay_id: str):
        payments = [dict(p) for p in db.get_records("SupplierPayments", fresh=True)]
        orig = next(p for p in payments if p["payment_id"] == pay_id)
        journals = [dict(j) for j in db.get_records("JournalHeaders", fresh=True)]
        creditors = asyncio.run(get_supplier_outstanding_balances(user=self.owner_user))
        supp_bal = next((c["outstanding_payable"] for c in creditors if c["supplier_id"] == supplier_id), 0.0)
        return {
            "orig": orig,
            "payment_count": len(payments),
            "journal_count": len(journals),
            "outstanding_payable": supp_bal,
        }

    def _assert_conflict_preserves_state(self, conflict_req: SupplierPaymentCreate, supplier_id: str, pay_id: str, before: dict):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(record_supplier_payment(conflict_req, user=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 409)

        after = self._snapshot_supplier_payment_state(supplier_id, pay_id)
        self.assertEqual(after["payment_count"], before["payment_count"])
        self.assertEqual(after["journal_count"], before["journal_count"])
        self.assertEqual(after["outstanding_payable"], before["outstanding_payable"])
        for k in ("supplier_id", "bill_id", "amount", "payment_method", "reference_number", "payment_date", "payment_type", "status"):
            self.assertEqual(after["orig"].get(k), before["orig"].get(k))
        audits = db.get_records("AuditLog", fresh=True)
        self.assertTrue(
            any(
                a.get("action") == "SUPPLIER_PAYMENT_IDEMPOTENCY_CONFLICT" and a.get("entity_id") == pay_id
                for a in audits
            )
        )

    def test_17_upi_followed_by_identical_upi_retry(self):
        bill = self._create_bill("SUP-001", "INV-IDM-17", 2000.0)
        req = SupplierPaymentCreate(
            supplier_id="SUP-001",
            bill_id=bill["bill_id"],
            amount=500.0,
            payment_method="UPI",
            reference_number="REF-123",
            payment_date="2026-11-15",
            idempotency_key="idem-17-upi",
        )
        first = asyncio.run(record_supplier_payment(req, user=self.owner_user))
        retry = asyncio.run(record_supplier_payment(req, user=self.owner_user))
        self.assertFalse(first["is_replay"])
        self.assertTrue(retry["is_replay"])
        self.assertEqual(first["payment"]["payment_id"], retry["payment"]["payment_id"])
        self.assertEqual(len(db.get_records("SupplierPayments", fresh=True)), 1)
        self.assertEqual(len(db.get_records("JournalHeaders", fresh=True)), 1)
        creditors = asyncio.run(get_supplier_outstanding_balances(user=self.owner_user))
        sup1 = next(c for c in creditors if c["supplier_id"] == "SUP-001")
        self.assertEqual(sup1["outstanding_payable"], 1500.0)

    def test_18_upi_followed_by_cash_same_key_rejected_409(self):
        # Exact reproduction from audit report
        first = asyncio.run(
            record_supplier_payment(
                SupplierPaymentCreate(
                    supplier_id="SUP-001",
                    bill_id="",
                    amount=500.0,
                    payment_method="UPI",
                    reference_number="REF-123",
                    payment_date="2026-11-15",
                    idempotency_key="same-key",
                ),
                user=self.owner_user,
            )
        )
        pay_id = first["payment"]["payment_id"]
        before = self._snapshot_supplier_payment_state("SUP-001", pay_id)

        conflict = SupplierPaymentCreate(
            supplier_id="SUP-001",
            bill_id="",
            amount=500.0,
            payment_method="CASH",
            reference_number="REF-123",
            payment_date="2026-11-15",
            idempotency_key="same-key",
        )
        self._assert_conflict_preserves_state(conflict, "SUP-001", pay_id, before)

        # Bank (1120) must remain credited, Cash (1110) must NOT be touched
        lines = db.get_records("JournalLines", fresh=True)
        self.assertEqual(len([l for l in lines if l["account_code"] == "1120"]), 1)
        self.assertEqual(len([l for l in lines if l["account_code"] == "1110"]), 0)

    def test_19_cash_followed_by_upi_same_key_rejected_409(self):
        first = asyncio.run(
            record_supplier_payment(
                SupplierPaymentCreate(
                    supplier_id="SUP-001",
                    bill_id="",
                    amount=500.0,
                    payment_method="CASH",
                    reference_number="",
                    payment_date="2026-11-15",
                    idempotency_key="idem-19-cash-upi",
                ),
                user=self.owner_user,
            )
        )
        pay_id = first["payment"]["payment_id"]
        before = self._snapshot_supplier_payment_state("SUP-001", pay_id)

        for ref in ("", "UPI-RETRY-19"):
            conflict = SupplierPaymentCreate(
                supplier_id="SUP-001",
                bill_id="",
                amount=500.0,
                payment_method="UPI",
                reference_number=ref,
                payment_date="2026-11-15",
                idempotency_key="idem-19-cash-upi",
            )
            self._assert_conflict_preserves_state(conflict, "SUP-001", pay_id, before)

    def test_20_bank_transfer_followed_by_neft_same_key_rejected_409(self):
        first = asyncio.run(
            record_supplier_payment(
                SupplierPaymentCreate(
                    supplier_id="SUP-001",
                    bill_id="",
                    amount=1500.0,
                    payment_method="BANK_TRANSFER",
                    reference_number="UTR-BANK-20",
                    payment_date="2026-11-15",
                    idempotency_key="idem-20-bank-neft",
                ),
                user=self.owner_user,
            )
        )
        pay_id = first["payment"]["payment_id"]
        before = self._snapshot_supplier_payment_state("SUP-001", pay_id)

        # Alias BANK -> BANK_TRANSFER must still replay cleanly
        alias_retry = asyncio.run(
            record_supplier_payment(
                SupplierPaymentCreate(
                    supplier_id="SUP-001",
                    bill_id="",
                    amount=1500.0,
                    payment_method="BANK",
                    reference_number="UTR-BANK-20",
                    payment_date="2026-11-15",
                    idempotency_key="idem-20-bank-neft",
                ),
                user=self.owner_user,
            )
        )
        self.assertTrue(alias_retry["is_replay"])
        self.assertEqual(alias_retry["payment"]["payment_id"], pay_id)

        # Distinct NEFT channel must be rejected 409
        conflict = SupplierPaymentCreate(
            supplier_id="SUP-001",
            bill_id="",
            amount=1500.0,
            payment_method="NEFT",
            reference_number="UTR-BANK-20",
            payment_date="2026-11-15",
            idempotency_key="idem-20-bank-neft",
        )
        self._assert_conflict_preserves_state(conflict, "SUP-001", pay_id, before)

    def test_21_same_key_different_amount_including_sub_rupee_rejected_409(self):
        first = asyncio.run(
            record_supplier_payment(
                SupplierPaymentCreate(
                    supplier_id="SUP-001",
                    bill_id="",
                    amount=500.00,
                    payment_method="UPI",
                    reference_number="UTR-AMT-21",
                    payment_date="2026-11-15",
                    idempotency_key="idem-21-amt",
                ),
                user=self.owner_user,
            )
        )
        pay_id = first["payment"]["payment_id"]
        before = self._snapshot_supplier_payment_state("SUP-001", pay_id)

        for bad_amt in (500.01, 600.00):
            conflict = SupplierPaymentCreate(
                supplier_id="SUP-001",
                bill_id="",
                amount=bad_amt,
                payment_method="UPI",
                reference_number="UTR-AMT-21",
                payment_date="2026-11-15",
                idempotency_key="idem-21-amt",
            )
            self._assert_conflict_preserves_state(conflict, "SUP-001", pay_id, before)

    def test_22_same_key_different_supplier_rejected_409(self):
        first = asyncio.run(
            record_supplier_payment(
                SupplierPaymentCreate(
                    supplier_id="SUP-001",
                    bill_id="",
                    amount=800.0,
                    payment_method="UPI",
                    reference_number="UTR-SUPP-22",
                    payment_date="2026-11-15",
                    idempotency_key="idem-22-supp",
                ),
                user=self.owner_user,
            )
        )
        pay_id = first["payment"]["payment_id"]
        before = self._snapshot_supplier_payment_state("SUP-001", pay_id)

        conflict = SupplierPaymentCreate(
            supplier_id="SUP-002",
            bill_id="",
            amount=800.0,
            payment_method="UPI",
            reference_number="UTR-SUPP-22",
            payment_date="2026-11-15",
            idempotency_key="idem-22-supp",
        )
        self._assert_conflict_preserves_state(conflict, "SUP-001", pay_id, before)

    def test_23_same_key_different_or_absent_bill_id_rejected_409(self):
        bill_1 = self._create_bill("SUP-001", "INV-23A", 4000.0)
        bill_2 = self._create_bill("SUP-001", "INV-23B", 4000.0)
        first = asyncio.run(
            record_supplier_payment(
                SupplierPaymentCreate(
                    supplier_id="SUP-001",
                    bill_id=bill_1["bill_id"],
                    amount=1000.0,
                    payment_method="UPI",
                    reference_number="UTR-BILL-23",
                    payment_date="2026-11-15",
                    idempotency_key="idem-23-bill",
                ),
                user=self.owner_user,
            )
        )
        pay_id = first["payment"]["payment_id"]
        before = self._snapshot_supplier_payment_state("SUP-001", pay_id)

        # Different bill_id -> 409
        conflict_other_bill = SupplierPaymentCreate(
            supplier_id="SUP-001",
            bill_id=bill_2["bill_id"],
            amount=1000.0,
            payment_method="UPI",
            reference_number="UTR-BILL-23",
            payment_date="2026-11-15",
            idempotency_key="idem-23-bill",
        )
        self._assert_conflict_preserves_state(conflict_other_bill, "SUP-001", pay_id, before)

        # Absent bill_id -> 409
        conflict_absent_bill = SupplierPaymentCreate(
            supplier_id="SUP-001",
            bill_id="",
            amount=1000.0,
            payment_method="UPI",
            reference_number="UTR-BILL-23",
            payment_date="2026-11-15",
            idempotency_key="idem-23-bill",
        )
        self._assert_conflict_preserves_state(conflict_absent_bill, "SUP-001", pay_id, before)

    def test_24_same_key_different_external_reference_rejected_409(self):
        first = asyncio.run(
            record_supplier_payment(
                SupplierPaymentCreate(
                    supplier_id="SUP-001",
                    bill_id="",
                    amount=900.0,
                    payment_method="UPI",
                    reference_number="REF-ORIG-24",
                    payment_date="2026-11-15",
                    idempotency_key="idem-24-ref",
                ),
                user=self.owner_user,
            )
        )
        pay_id = first["payment"]["payment_id"]
        before = self._snapshot_supplier_payment_state("SUP-001", pay_id)

        for changed_ref in ("REF-OTHER-24", "ref-orig-24"):
            conflict = SupplierPaymentCreate(
                supplier_id="SUP-001",
                bill_id="",
                amount=900.0,
                payment_method="UPI",
                reference_number=changed_ref,
                payment_date="2026-11-15",
                idempotency_key="idem-24-ref",
            )
            self._assert_conflict_preserves_state(conflict, "SUP-001", pay_id, before)

    def test_25_same_key_different_payment_date_rejected_409(self):
        first = asyncio.run(
            record_supplier_payment(
                SupplierPaymentCreate(
                    supplier_id="SUP-001",
                    bill_id="",
                    amount=750.0,
                    payment_method="UPI",
                    reference_number="UTR-DATE-25",
                    payment_date="2026-11-14",
                    idempotency_key="idem-25-date",
                ),
                user=self.owner_user,
            )
        )
        pay_id = first["payment"]["payment_id"]
        before = self._snapshot_supplier_payment_state("SUP-001", pay_id)

        conflict = SupplierPaymentCreate(
            supplier_id="SUP-001",
            bill_id="",
            amount=750.0,
            payment_method="UPI",
            reference_number="UTR-DATE-25",
            payment_date="2026-11-15",
            idempotency_key="idem-25-date",
        )
        self._assert_conflict_preserves_state(conflict, "SUP-001", pay_id, before)

    def test_26_same_key_different_payment_type_rejected_409(self):
        first = asyncio.run(
            record_supplier_payment(
                SupplierPaymentCreate(
                    supplier_id="SUP-001",
                    bill_id="",
                    amount=1100.0,
                    payment_method="UPI",
                    reference_number="UTR-TYPE-26",
                    payment_date="2026-11-15",
                    payment_type="ON_ACCOUNT",
                    idempotency_key="idem-26-type",
                ),
                user=self.owner_user,
            )
        )
        pay_id = first["payment"]["payment_id"]
        before = self._snapshot_supplier_payment_state("SUP-001", pay_id)

        for other_type in ("ADVANCE", "BILL_PAYMENT"):
            conflict = SupplierPaymentCreate(
                supplier_id="SUP-001",
                bill_id="",
                amount=1100.0,
                payment_method="UPI",
                reference_number="UTR-TYPE-26",
                payment_date="2026-11-15",
                payment_type=other_type,
                idempotency_key="idem-26-type",
            )
            self._assert_conflict_preserves_state(conflict, "SUP-001", pay_id, before)

    def test_27_two_legitimate_payments_different_keys_succeed(self):
        bill = self._create_bill("SUP-001", "INV-27", 3000.0)
        p1 = asyncio.run(
            record_supplier_payment(
                SupplierPaymentCreate(
                    supplier_id="SUP-001",
                    bill_id=bill["bill_id"],
                    amount=500.0,
                    payment_method="UPI",
                    reference_number="REF-LEGIT-1",
                    payment_date="2026-11-15",
                    idempotency_key="legit-key-1",
                ),
                user=self.owner_user,
            )
        )
        p2 = asyncio.run(
            record_supplier_payment(
                SupplierPaymentCreate(
                    supplier_id="SUP-001",
                    bill_id=bill["bill_id"],
                    amount=500.0,
                    payment_method="CASH",
                    reference_number="",
                    payment_date="2026-11-15",
                    idempotency_key="legit-key-2",
                ),
                user=self.owner_user,
            )
        )
        self.assertNotEqual(p1["payment"]["payment_id"], p2["payment"]["payment_id"])
        self.assertEqual(len(db.get_records("SupplierPayments", fresh=True)), 2)
        self.assertEqual(len(db.get_records("JournalHeaders", fresh=True)), 2)
        creditors = asyncio.run(get_supplier_outstanding_balances(user=self.owner_user))
        sup1 = next(c for c in creditors if c["supplier_id"] == "SUP-001")
        self.assertEqual(sup1["outstanding_payable"], 2000.0)

    def test_28_concurrent_identical_requests_create_single_payment(self):
        bill = self._create_bill("SUP-001", "INV-28-CONC", 5000.0)
        barrier = threading.Barrier(4)
        results = []
        errors = []
        lock = threading.Lock()

        def worker():
            req = SupplierPaymentCreate(
                supplier_id="SUP-001",
                bill_id=bill["bill_id"],
                amount=1200.0,
                payment_method="UPI",
                reference_number="UTR-CONC-28",
                payment_date="2026-11-15",
                idempotency_key="conc-identical-28",
            )
            barrier.wait(timeout=5)
            try:
                res = asyncio.run(record_supplier_payment(req, user=self.owner_user))
                with lock:
                    results.append(res)
            except Exception as exc:
                with lock:
                    errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 4)
        pay_ids = {r["payment"]["payment_id"] for r in results}
        self.assertEqual(len(pay_ids), 1)
        self.assertEqual(sum(1 for r in results if not r["is_replay"]), 1)
        self.assertEqual(sum(1 for r in results if r["is_replay"]), 3)
        self.assertEqual(len(db.get_records("SupplierPayments", fresh=True)), 1)
        self.assertEqual(len(db.get_records("JournalHeaders", fresh=True)), 1)
        creditors = asyncio.run(get_supplier_outstanding_balances(user=self.owner_user))
        sup1 = next(c for c in creditors if c["supplier_id"] == "SUP-001")
        self.assertEqual(sup1["outstanding_payable"], 3800.0)

    def test_29_concurrent_conflicting_requests_one_wins_other_409(self):
        self._create_bill("SUP-001", "INV-29A", 5000.0)
        self._create_bill("SUP-002", "INV-29B", 5000.0)
        barrier = threading.Barrier(2)
        outcomes = []
        lock = threading.Lock()

        req_upi = SupplierPaymentCreate(
            supplier_id="SUP-001",
            bill_id="",
            amount=500.0,
            payment_method="UPI",
            reference_number="REF-CONC-29",
            payment_date="2026-11-15",
            idempotency_key="conc-conflict-29",
        )
        req_cash_other_supp = SupplierPaymentCreate(
            supplier_id="SUP-002",
            bill_id="",
            amount=500.0,
            payment_method="CASH",
            reference_number="REF-CONC-29",
            payment_date="2026-11-15",
            idempotency_key="conc-conflict-29",
        )

        def run_req(payload):
            barrier.wait(timeout=5)
            try:
                res = asyncio.run(record_supplier_payment(payload, user=self.owner_user))
                with lock:
                    outcomes.append(("OK", res))
            except HTTPException as exc:
                with lock:
                    outcomes.append(("HTTP", exc.status_code))

        t1 = threading.Thread(target=run_req, args=(req_upi,))
        t2 = threading.Thread(target=run_req, args=(req_cash_other_supp,))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        statuses = sorted([o[0] for o in outcomes])
        self.assertEqual(statuses, ["HTTP", "OK"])
        http_err = next(o[1] for o in outcomes if o[0] == "HTTP")
        self.assertEqual(http_err, 409)
        self.assertEqual(len(db.get_records("SupplierPayments", fresh=True)), 1)
        self.assertEqual(len(db.get_records("JournalHeaders", fresh=True)), 1)

    def test_30_retry_after_persistence_failure_and_conflicting_retry_409(self):
        bill = self._create_bill("SUP-001", "INV-30-PERSIST", 4000.0)
        req = SupplierPaymentCreate(
            supplier_id="SUP-001",
            bill_id=bill["bill_id"],
            amount=1000.0,
            payment_method="UPI",
            reference_number="UTR-30-OK",
            payment_date="2026-11-15",
            idempotency_key="idem-30-persist",
        )
        db.inject_failure_once("SupplierBills", 1)
        with self.assertRaises((RuntimeError, StorageIOError, HTTPException)):
            asyncio.run(record_supplier_payment(req, user=self.owner_user))

        # Even while INCOMPLETE, a conflicting payload with the same key must still return 409
        conflicting_req = SupplierPaymentCreate(
            supplier_id="SUP-001",
            bill_id=bill["bill_id"],
            amount=1000.0,
            payment_method="CASH",
            reference_number="UTR-30-OK",
            payment_date="2026-11-15",
            idempotency_key="idem-30-persist",
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(record_supplier_payment(conflicting_req, user=self.owner_user))
        self.assertEqual(ctx.exception.status_code, 409)

        # Identical retry recovers cleanly
        rec = asyncio.run(record_supplier_payment(req, user=self.owner_user))
        self.assertTrue(rec["ok"])
        self.assertEqual(rec["payment"]["status"], "PAID")
        self.assertEqual(len(db.get_records("SupplierPayments", fresh=True)), 1)
        self.assertEqual(len(db.get_records("JournalHeaders", fresh=True)), 1)
        creditors = asyncio.run(get_supplier_outstanding_balances(user=self.owner_user))
        sup1 = next(c for c in creditors if c["supplier_id"] == "SUP-001")
        self.assertEqual(sup1["outstanding_payable"], 3000.0)

    def test_31_retry_after_accounting_posting_failure_recovers_without_double_charge(self):
        bill = self._create_bill("SUP-001", "INV-31-ACCT", 4500.0)
        req = SupplierPaymentCreate(
            supplier_id="SUP-001",
            bill_id=bill["bill_id"],
            amount=1500.0,
            payment_method="BANK_TRANSFER",
            reference_number="UTR-31-ACCT",
            payment_date="2026-11-15",
            idempotency_key="idem-31-acct",
        )
        db.inject_failure_once("JournalHeaders", 1)
        with self.assertRaises((RuntimeError, StorageIOError, HTTPException)):
            asyncio.run(record_supplier_payment(req, user=self.owner_user))

        self.assertEqual(len(db.get_records("JournalHeaders", fresh=True)), 0)
        rec = asyncio.run(record_supplier_payment(req, user=self.owner_user))
        self.assertTrue(rec["ok"])
        self.assertEqual(rec["payment"]["status"], "PAID")
        self.assertEqual(len(db.get_records("SupplierPayments", fresh=True)), 1)
        self.assertEqual(len(db.get_records("JournalHeaders", fresh=True)), 1)
        bills = db.get_records("SupplierBills", fresh=True)
        self.assertEqual(float(bills[0]["paid_amount"]), 1500.0)
        self.assertEqual(float(bills[0]["balance_amount"]), 3000.0)
        tb = calculate_trial_balance()
        self.assertTrue(tb["is_balanced"])
        self.assertAlmostEqual(tb["variance"], 0.0, places=2)


if __name__ == "__main__":
    unittest.main()
