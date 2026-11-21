"""
Master Execution Regression & Cross-Module Verification Suite.
Locks in real production fixes and hardening verified across the full Kawad Swad ERP:
  1. post_packaging_batch_journal zero-bulk / non-zero-packaging-material guard (no zero-amount GL line crash)
  2. get_latest_purchase_rate allowing confirmed MILLING_OUTPUT while rejecting consumption/opening/adjustments
  3. AUTH-03 fail-closed active-status predicate & NO_CACHE_TABS fail-closed 429 behavior for AuthUsers/RevokedTokens
  4. _sanitize_diagnostic_error redaction of Apps Script HMAC secret and WebApp URL
  5. Domain status preservation over Apps Script bridge 'CONFIRMED' transport status + customer city default
  6. Full 7-stage end-to-end controlled business acceptance & double-entry trial balance reconciliation
"""

import asyncio
import os
import sys
import time
import unittest
from decimal import Decimal
from unittest.mock import patch

os.environ["SALES_TESTING"] = "1"
os.environ["SALES_JWT_SECRET"] = "test-only-secret-do-not-use-for-deployment-32"

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import tests.test_audit_reconciliation  # noqa: F401 - ensures FastAPI/Pydantic shims if needed
from tests.v2_test_harness import LocalAppsScriptSimulator, make_test_request

from app import auth as auth_mod
from app import main as main_mod
from app.accounting.postings import post_packaging_batch_journal
from app.calculations.costing import get_latest_purchase_rate
from app.models import CustomerCreate
from app.routers import customers as customers_router
from app.sheets import db, REQUIRED_TABS
from tests.verify_acceptance_and_reconciliation import run_acceptance_and_reconciliation


class TestMasterExecutionVerification(unittest.TestCase):
    def setUp(self):
        self._orig_connected = db.is_connected
        self._orig_spreadsheet = db.spreadsheet
        self._orig_fallback = db.allow_in_memory_fallback
        db.is_connected = False
        db.spreadsheet = None
        db.allow_in_memory_fallback = True
        for tab in REQUIRED_TABS:
            db.memory_store[tab] = []
        db._records_cache.clear()
        db._worksheets.clear()
        self._sim = LocalAppsScriptSimulator()
        self._sim.start()

    def tearDown(self):
        self._sim.stop()
        db.is_connected = self._orig_connected
        db.spreadsheet = self._orig_spreadsheet
        db.allow_in_memory_fallback = self._orig_fallback
        db._records_cache.clear()
        db._worksheets.clear()

    def test_post_packaging_batch_journal_zero_bulk_cost_nonzero_material_cost(self):
        """
        Packaging batches created while bulk WIP overhead valuation is pending (bulk_cost=0)
        but with confirmed packaging materials (e.g., pouches = Rs 875.00) must post a valid
        balanced journal (DR 1240 / CR 1250) without appending a zero-amount line on 1230.
        """
        pack_data = {
            "packaging_id": "PKB-TEST-ZERO-BULK",
            "product_name_snapshot": "Chana Masala Papad 200g",
            "bulk_kg_used": 50.0,
            "total_packets": 250,
            "packaging_date": "2026-11-21",
            "bulk_cost": 0.0,
            "packaging_material_cost": 875.0,
            "packaging_labor_cost": 0.0,
        }
        jv = post_packaging_batch_journal(
            pack_data,
            bulk_cost=Decimal("0.00"),
            packing_material_cost=Decimal("875.00"),
            packing_labor_cost=Decimal("0.00"),
            actor="USR-OWNER",
        )
        self.assertEqual(jv["status"], "POSTED")
        self.assertEqual(Decimal(str(jv["total_debit"])), Decimal("875.00"))
        self.assertEqual(Decimal(str(jv["total_credit"])), Decimal("875.00"))

        lines = [
            l for l in db.get_records("JournalLines", fresh=True)
            if str(l.get("journal_id")) == str(jv["journal_id"])
        ]
        self.assertEqual(len(lines), 2)
        codes = {str(l["account_code"]) for l in lines}
        self.assertEqual(codes, {"1240", "1250"})
        self.assertNotIn("1230", codes)

    def test_milling_output_establishes_confirmed_flour_rate_while_consumption_excluded(self):
        """
        Confirmed MILLING_OUTPUT receipts establish the landed flour rate for papad batch costing,
        while PRODUCTION_CONSUMPTION, MILLING_CONSUMPTION, OPENING_VERIFICATION, and ADJUSTMENT
        movements must never be treated as valid purchase/landed rate observations.
        """
        master = [
            {"raw_material_id": "RM-MOONG-FLOUR", "material_name": "Moong Dal Flour", "unit": "kg", "rate_per_unit": "", "rate_status": "PENDING"}
        ]
        blocked_ledger = [
            {"raw_material_txn_id": "RML-1", "raw_material_id": "RM-MOONG-FLOUR", "material_name": "Moong Dal Flour", "movement_type": "PRODUCTION_CONSUMPTION", "rate_per_unit": 200.0, "unit": "kg", "status": "VALID"},
            {"raw_material_txn_id": "RML-2", "raw_material_id": "RM-MOONG-FLOUR", "material_name": "Moong Dal Flour", "movement_type": "MILLING_CONSUMPTION", "rate_per_unit": 190.0, "unit": "kg", "status": "VALID"},
            {"raw_material_txn_id": "RML-3", "raw_material_id": "RM-MOONG-FLOUR", "material_name": "Moong Dal Flour", "movement_type": "OPENING_VERIFICATION", "rate_per_unit": 150.0, "unit": "kg", "status": "VALID"},
            {"raw_material_txn_id": "RML-4", "raw_material_id": "RM-MOONG-FLOUR", "material_name": "Moong Dal Flour", "movement_type": "ADJUSTMENT", "rate_per_unit": 140.0, "unit": "kg", "status": "VALID"},
        ]
        missing = get_latest_purchase_rate("Moong Dal Flour", master, blocked_ledger)
        self.assertEqual(missing["status"], "MISSING_RATE")
        self.assertIsNone(missing["rate_per_canonical_unit"])

        milling_ledger = blocked_ledger + [
            {"raw_material_txn_id": "RML-5", "raw_material_id": "RM-MOONG-FLOUR", "material_name": "Moong Dal Flour", "movement_type": "MILLING_OUTPUT", "rate_per_unit": 115.31, "unit": "kg", "txn_datetime": "2026-11-21T10:00:00Z", "status": "VALID"}
        ]
        confirmed = get_latest_purchase_rate("Moong Dal Flour", master, milling_ledger)
        self.assertEqual(confirmed["status"], "CONFIRMED")
        self.assertEqual(float(confirmed["rate_per_canonical_unit"]), 115.31)

    def test_auth03_fail_closed_deactivation_and_no_cache_security_tabs(self):
        """AUTH-03: Missing/None/unrecognized active values fail closed and security tabs never serve stale cache on 429."""
        for bad in (None, "", " ", False, 0, "false", "0", "no", "inactive", "suspended", "unknown"):
            self.assertFalse(auth_mod.is_account_active(bad))
            self.assertTrue(auth_mod.is_account_deactivated(bad))

        for good in (True, 1, "true", "TRUE", "1", "yes", "active", "ACTIVE"):
            self.assertTrue(auth_mod.is_account_active(good))
            self.assertFalse(auth_mod.is_account_deactivated(good))

        class QuotaWS:
            def get_all_records(self):
                raise Exception("APIError: [429]: Quota exceeded for Read requests")

        class QuotaBook:
            def worksheet(self, tab):
                return QuotaWS()

        db.is_connected = True
        db.spreadsheet = QuotaBook()
        for sec_tab in ("AuthUsers", "RevokedTokens"):
            db._records_cache[sec_tab] = (time.monotonic() - 50, [{"user_id": "USR-1", "active": "true"}])
            with self.assertRaises(RuntimeError) as ctx:
                db.get_records(sec_tab, fresh=False)
            self.assertIn("quota", str(ctx.exception).lower())

    def test_diagnostic_error_sanitizer_redacts_apps_script_secret_and_url(self):
        """Diagnostic sanitizer must redact Apps Script shared secret and WebApp URL in addition to JWT/Sheets secrets."""
        fake_secret = "hmac-super-secret-value-999999999999999999"
        fake_url = "https://script.google.com/macros/s/AKfycbTestDeployment123/exec"
        raw_err = f"Bridge POST to {fake_url} failed while signing with {fake_secret}"
        with patch.dict(
            os.environ,
            {
                "SALES_APPS_SCRIPT_SHARED_SECRET": fake_secret,
                "SALES_APPS_SCRIPT_WEBAPP_URL": fake_url,
            },
        ):
            sanitized = main_mod._sanitize_diagnostic_error(raw_err)
        self.assertNotIn(fake_secret, sanitized)
        self.assertNotIn(fake_url, sanitized)
        self.assertIn("[REDACTED]", sanitized)

    def test_customer_blank_city_defaults_to_bhilwara(self):
        """Blank customer city string normalizes cleanly to default 'Bhilwara'."""
        owner = {"user_id": "USR-000001", "role": "OWNER", "full_name": "Owner"}
        req = CustomerCreate(
            customer_type="RETAILER",
            shop_name="Nimar Kirana",
            shopkeeper_name="Mohan",
            mobile="9876501234",
            city="   ",
        )
        res = asyncio.run(customers_router.create_customer(req, request=make_test_request(), current_user=owner))
        self.assertEqual(res.city, "Bhilwara")

    def test_end_to_end_controlled_acceptance_and_trial_balance_reconciliation(self):
        """Execute complete 7-stage Kawad Swad ERP workflow with zero inventory and trial balance variance."""
        # Stop outer simulator cleanly because run_acceptance_and_reconciliation manages its own lifecycle
        self._sim.stop()
        try:
            run_acceptance_and_reconciliation()
        finally:
            self._sim.start()


if __name__ == "__main__":
    unittest.main()
