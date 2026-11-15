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

from app.sheets import db, ID_PREFIXES, StorageIOError
from app.accounting.customer_ledger import reset_cross_process_state
from app.accounting.journal_engine import calculate_trial_balance
from app.routers.purchasing import (
    SupplierBillCreate,
    SupplierPaymentCreate,
    SupplierAdvanceApplyRequest,
    create_supplier_bill,
    record_supplier_payment,
    apply_supplier_advance_to_bill,
    list_supplier_payments,
    purchasing_summary,
)
from app.routers.accounting import get_supplier_outstanding_balances


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
        with self.assertRaises((RuntimeError, StorageIOError)):
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
        with self.assertRaises((RuntimeError, StorageIOError)):
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


if __name__ == "__main__":
    unittest.main()
