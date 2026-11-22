"""
Mission 51B-1R — TX-FINAL-01 Regression Suite: Accounting Journal Quarantine Bypass.

Verifies against the authoritative accounting contract in `app.accounting.postings`:
- CREATE_SALE requires a posted, balanced SALES / SALE_INVOICE journal in JournalHeaders + JournalLines.
- RECORD_SALE_PAYMENT requires a posted, balanced RECEIPT / PAYMENT_COLLECTION journal in JournalHeaders + JournalLines.
- RECOVERY_REQUIRED MUST NOT transition to COMMITTED or return HTTP 200 CONFIRMED on same-nonce replay
  when required accounting journal records are missing, incomplete, imbalanced, non-POSTED, duplicate,
  wrong voucher_type, or have header/line mismatch or Sheets read failure.
- When both primary/child records AND valid balanced accounting journal records are present,
  recovery cleanly transitions to COMMITTED with zero duplicate gateway POSTs.
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

import tests  # noqa: F401 - activates offline fastapi shim when fastapi is absent

from app import apps_script_bridge as bridge_mod
from app.accounting.transaction_coordinator import TransactionCoordinator
from app.apps_script_bridge import AppsScriptBridge
from app.transaction_safety import (
    TransactionState,
    TransitionAuthority,
    compute_deterministic_payload_hash,
)


def _make_sale_payload():
    return {
        "sale": {
            "customer_id": "CUST-000001",
            "salesman_user_id": "USR-SM-001",
            "payment_mode": "CASH",
            "subtotal": 1000.0,
            "discount_amount": 0.0,
            "tax_amount": 0.0,
            "bill_total": 1000.0,
            "paid_amount": 1000.0,
            "balance_due": 0.0,
            "payment_status": "PAID",
        },
        "items": [
            {
                "product_id": "PRD-000001",
                "quantity": 10,
                "unit_price": 100.0,
                "line_total": 1000.0,
            }
        ],
    }


def _make_payment_payload():
    return {
        "payment": {
            "sale_id": "SAL-000001",
            "customer_id": "CUST-000001",
            "amount": 500.0,
            "payment_mode": "UPI",
        }
    }


def _valid_sale_tables(nonce: str, sale_id: str = "SAL-000001", journal_id: str = "JV-000001"):
    return {
        "IdAllocations": [
            {"nonce": nonce, "tab_name": "Sales", "allocated_id": sale_id, "created_at": "2026-11-21T10:00:00+05:30"},
        ],
        "AuditLog": [
            {"audit_id": "AUD-1", "action": "CREATE_SALE", "entity_type": "Sales", "entity_id": sale_id, "related_record_id": nonce},
        ],
        "Sales": [
            {
                "sale_id": sale_id,
                "customer_id": "CUST-000001",
                "salesman_user_id": "USR-SM-001",
                "payment_mode": "CASH",
                "subtotal": 1000.0,
                "discount_amount": 0.0,
                "tax_amount": 0.0,
                "bill_total": 1000.0,
                "paid_amount": 1000.0,
                "balance_due": 0.0,
                "payment_status": "PAID",
            }
        ],
        "SaleItems": [
            {"sale_item_id": "SI-000001", "sale_id": sale_id, "product_id": "PRD-000001", "quantity": 10, "unit_price": 100.0, "line_total": 1000.0},
        ],
        "SalesmanStockLedger": [
            {"ledger_id": "SL-000001", "related_sale_id": sale_id, "product_id": "PRD-000001", "quantity_change": -10},
        ],
        "JournalHeaders": [
            {
                "journal_id": journal_id,
                "voucher_type": "SALES",
                "reference_type": "SALE_INVOICE",
                "reference_id": sale_id,
                "status": "POSTED",
                "total_debit": 1000.0,
                "total_credit": 1000.0,
            }
        ],
        "JournalLines": [
            {"line_id": "JL-000001", "journal_id": journal_id, "account_code": "1115", "debit_amount": 1000.0, "credit_amount": 0.0},
            {"line_id": "JL-000002", "journal_id": journal_id, "account_code": "4100", "debit_amount": 0.0, "credit_amount": 1000.0},
        ],
    }


def _valid_payment_tables(nonce: str, payment_id: str = "RCPT-000001", journal_id: str = "JV-000002"):
    return {
        "IdAllocations": [
            {"nonce": nonce, "tab_name": "Payments", "allocated_id": payment_id, "created_at": "2026-11-21T10:05:00+05:30"},
        ],
        "AuditLog": [
            {"audit_id": "AUD-2", "action": "RECORD_SALE_PAYMENT", "entity_type": "Payments", "entity_id": payment_id, "related_record_id": nonce},
        ],
        "Payments": [
            {
                "payment_id": payment_id,
                "sale_id": "SAL-000001",
                "customer_id": "CUST-000001",
                "amount": 500.0,
                "payment_mode": "UPI",
            }
        ],
        "JournalHeaders": [
            {
                "journal_id": journal_id,
                "voucher_type": "RECEIPT",
                "reference_type": "PAYMENT_COLLECTION",
                "reference_id": payment_id,
                "status": "POSTED",
                "total_debit": 500.0,
                "total_credit": 500.0,
            }
        ],
        "JournalLines": [
            {"line_id": "JL-000010", "journal_id": journal_id, "account_code": "1120", "debit_amount": 500.0, "credit_amount": 0.0},
            {"line_id": "JL-000011", "journal_id": journal_id, "account_code": "1130", "debit_amount": 0.0, "credit_amount": 500.0},
        ],
    }


class TestTxFinal01AccountingQuarantine(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="ks_tx01_")
        self.db_path = os.path.join(self.tmp_dir, "coord_tx01.db")
        self.coord = TransactionCoordinator(
            db_path=self.db_path,
            testing=True,
            auto_recover_stale_leases=False,
        )
        self.bridge = AppsScriptBridge()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _seed_quarantined_tx(self, *, nonce: str, action: str, target_tab: str, payload: dict, allocated_id: str):
        p_hash = compute_deterministic_payload_hash(
            action=action,
            target_tab=target_tab,
            actor_user_id="USR-OWNER-001",
            actor_role="OWNER_ADMIN",
            payload=payload,
        )
        st, _ = self.coord.begin_governed_transaction(
            nonce=nonce,
            action=action,
            target_tab=target_tab,
            actor_user_id="USR-OWNER-001",
            payload_hash=p_hash,
            correlation_id="CORR-SEED-01",
        )
        self.assertEqual(st, "ACQUIRED")
        self.coord.transition_governed_transaction(
            nonce=nonce,
            lifecycle_state=TransactionState.RECOVERY_REQUIRED.value,
            bridge_status="RECOVERY_REQUIRED",
            failure_category="RECOVERY_REQUIRED",
            error_code="PARTIAL_SIDE_EFFECT_RECOVERY_REQUIRED",
            allocated_id=allocated_id,
            message="Quarantined pending accounting journal verification",
            clear_lease=True,
            authority=TransitionAuthority.ORDINARY,
            expected_from_state=TransactionState.EXECUTING,
            expected_version=1,
            expected_correlation_id="CORR-SEED-01",
            expected_attempt=1,
        )

    def _run_same_nonce_replay(self, *, nonce: str, action: str, target_tab: str, id_field: str, payload: dict, tables: dict, fail_tab: str = ""):
        def _fake_get_records(tab_name, fresh=False):
            if fail_tab and tab_name == fail_tab:
                raise TimeoutError(f"Simulated timeout reading {tab_name}")
            return list(tables.get(tab_name, []))

        with (
            patch.object(bridge_mod, "tx_coordinator", self.coord),
            patch.object(bridge_mod, "SALES_APPS_SCRIPT_ENABLED", True),
            patch.object(bridge_mod, "SALES_APPS_SCRIPT_WEBAPP_URL", "https://script.google.com/macros/s/test/exec"),
            patch.object(bridge_mod, "SALES_APPS_SCRIPT_SHARED_SECRET", "s" * 40),
            patch.object(bridge_mod, "get_schema_write_block_reason", return_value=None),
            patch.object(bridge_mod.db, "get_records", side_effect=_fake_get_records),
            patch.object(bridge_mod.db, "invalidate_tab_cache", return_value=None),
            patch.object(bridge_mod.db, "log_audit", return_value=True),
            patch.object(bridge_mod.urllib.request, "build_opener") as mock_opener,
        ):
            res = self.bridge.execute_governed_write(
                action=action,
                target_tab=target_tab,
                payload=payload,
                nonce=nonce,
                actor_user_id="USR-OWNER-001",
                actor_role="OWNER_ADMIN",
                id_field=id_field,
            )
            self.assertEqual(mock_opener.call_count, 0, "Quarantined recovery MUST NOT issue a new gateway POST")
            return res

    def test_create_sale_quarantine_not_bypassed_for_invalid_journals(self):
        invalid_scenarios = [
            ("missing_journal_header", lambda t: t["JournalHeaders"].clear()),
            ("single_journal_line", lambda t: t["JournalLines"].pop()),
            ("unbalanced_journal_lines", lambda t: t["JournalLines"][1].update({"credit_amount": 900.0})),
            ("header_line_debit_mismatch", lambda t: t["JournalHeaders"][0].update({"total_debit": 1100.0, "total_credit": 1100.0})),
            ("wrong_voucher_type", lambda t: t["JournalHeaders"][0].update({"voucher_type": "RECEIPT"})),
            ("draft_not_posted", lambda t: t["JournalHeaders"][0].update({"status": "DRAFT"})),
            (
                "duplicate_active_headers",
                lambda t: t["JournalHeaders"].append({**t["JournalHeaders"][0], "journal_id": "JV-000099"}),
            ),
            ("unknown_account_code", lambda t: t["JournalLines"][0].update({"account_code": "9999"})),
            (
                "mismatched_allocation_id",
                lambda t: t["IdAllocations"][0].update({"allocated_id": "SAL-999999"}),
            ),
        ]

        for idx, (label, mutator) in enumerate(invalid_scenarios):
            with self.subTest(scenario=label):
                nonce = f"NONCE-TX01-SALE-BAD-{idx}"
                payload = _make_sale_payload()
                self._seed_quarantined_tx(
                    nonce=nonce,
                    action="CREATE_SALE",
                    target_tab="Sales",
                    payload=payload,
                    allocated_id="SAL-000001",
                )
                tables = _valid_sale_tables(nonce)
                mutator(tables)

                res = self._run_same_nonce_replay(
                    nonce=nonce,
                    action="CREATE_SALE",
                    target_tab="Sales",
                    id_field="sale_id",
                    payload=payload,
                    tables=tables,
                )
                self.assertEqual(res.status, "RECOVERY_REQUIRED", f"{label}: must remain RECOVERY_REQUIRED")
                self.assertEqual(res.http_status, 409, f"{label}: must NOT return HTTP 200")
                self.assertFalse(res.retryable)
                persisted = self.coord.get_governed_transaction(nonce)
                self.assertEqual(persisted["lifecycle_state"], TransactionState.RECOVERY_REQUIRED.value)

    def test_create_sale_quarantine_recovers_only_with_complete_balanced_journal(self):
        nonce = "NONCE-TX01-SALE-OK"
        payload = _make_sale_payload()
        self._seed_quarantined_tx(
            nonce=nonce,
            action="CREATE_SALE",
            target_tab="Sales",
            payload=payload,
            allocated_id="SAL-000001",
        )
        tables = _valid_sale_tables(nonce)

        res = self._run_same_nonce_replay(
            nonce=nonce,
            action="CREATE_SALE",
            target_tab="Sales",
            id_field="sale_id",
            payload=payload,
            tables=tables,
        )
        self.assertEqual(res.status, "CONFIRMED")
        self.assertEqual(res.http_status, 200)
        self.assertEqual(res.allocated_id, "SAL-000001")
        persisted = self.coord.get_governed_transaction(nonce)
        self.assertEqual(persisted["lifecycle_state"], TransactionState.COMMITTED.value)

    def test_record_sale_payment_quarantine_blocks_incomplete_and_confirms_complete_journal(self):
        bad_scenarios = [
            ("missing_payment_journal", lambda t: t["JournalHeaders"].clear()),
            ("imbalanced_payment_journal", lambda t: t["JournalLines"][0].update({"debit_amount": 400.0})),
            ("wrong_voucher_type_payment", lambda t: t["JournalHeaders"][0].update({"voucher_type": "SALES"})),
            ("duplicate_payment_headers", lambda t: t["JournalHeaders"].append({**t["JournalHeaders"][0], "journal_id": "JV-DUP"})),
        ]
        for idx, (label, mutator) in enumerate(bad_scenarios):
            with self.subTest(scenario=label):
                nonce = f"NONCE-TX01-PAY-BAD-{idx}"
                payload = _make_payment_payload()
                self._seed_quarantined_tx(
                    nonce=nonce,
                    action="RECORD_SALE_PAYMENT",
                    target_tab="Payments",
                    payload=payload,
                    allocated_id="RCPT-000001",
                )
                tables = _valid_payment_tables(nonce)
                mutator(tables)

                res = self._run_same_nonce_replay(
                    nonce=nonce,
                    action="RECORD_SALE_PAYMENT",
                    target_tab="Payments",
                    id_field="payment_id",
                    payload=payload,
                    tables=tables,
                )
                self.assertEqual(res.status, "RECOVERY_REQUIRED")
                self.assertEqual(res.http_status, 409)
                self.assertEqual(
                    self.coord.get_governed_transaction(nonce)["lifecycle_state"],
                    TransactionState.RECOVERY_REQUIRED.value,
                )

        # Complete valid payment journal clears quarantine safely
        nonce_ok = "NONCE-TX01-PAY-OK"
        payload_ok = _make_payment_payload()
        self._seed_quarantined_tx(
            nonce=nonce_ok,
            action="RECORD_SALE_PAYMENT",
            target_tab="Payments",
            payload=payload_ok,
            allocated_id="RCPT-000001",
        )
        res_ok = self._run_same_nonce_replay(
            nonce=nonce_ok,
            action="RECORD_SALE_PAYMENT",
            target_tab="Payments",
            id_field="payment_id",
            payload=payload_ok,
            tables=_valid_payment_tables(nonce_ok),
        )
        self.assertEqual(res_ok.status, "CONFIRMED")
        self.assertEqual(res_ok.http_status, 200)
        self.assertEqual(
            self.coord.get_governed_transaction(nonce_ok)["lifecycle_state"],
            TransactionState.COMMITTED.value,
        )

    def test_sheets_read_failure_during_journal_verification_preserves_quarantine(self):
        nonce = "NONCE-TX01-SHEETS-ERR"
        payload = _make_sale_payload()
        self._seed_quarantined_tx(
            nonce=nonce,
            action="CREATE_SALE",
            target_tab="Sales",
            payload=payload,
            allocated_id="SAL-000001",
        )
        res = self._run_same_nonce_replay(
            nonce=nonce,
            action="CREATE_SALE",
            target_tab="Sales",
            id_field="sale_id",
            payload=payload,
            tables=_valid_sale_tables(nonce),
            fail_tab="JournalHeaders",
        )
        self.assertEqual(res.status, "RECOVERY_REQUIRED")
        self.assertEqual(res.http_status, 409)
        self.assertEqual(
            self.coord.get_governed_transaction(nonce)["lifecycle_state"],
            TransactionState.RECOVERY_REQUIRED.value,
        )


if __name__ == "__main__":
    unittest.main()
