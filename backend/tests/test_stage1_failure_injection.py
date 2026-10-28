import os
import sys
import unittest
import asyncio
from unittest.mock import patch
from fastapi import HTTPException

os.environ["SALES_TESTING"] = "1"
os.environ["SALES_JWT_SECRET"] = "test-only-secret-do-not-use-for-deployment-32"

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.sheets import db, REQUIRED_TABS
from app.calculations.inventory import calculate_raw_material_balance
from app.routers.production import (
    receive_raw_material,
    RawMaterialReceiveRequest,
)


class TestStage1FailureInjection(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for tab in REQUIRED_TABS:
            db.memory_store[tab] = []

        db.memory_store.update({
            "Users": [
                {"user_id": "USR-OWNER-01", "username": "owner", "role": "OWNER", "active": "true"},
            ],
            "RawMaterials": [
                {"raw_material_id": "RM-WHOLE-MOONG-DAL", "material_name": "Whole Moong Dal", "category": "WHOLE_GRAIN", "current_stock": 0.0, "unit": "kg"},
            ],
            "RawMaterialLedger": [],
            "IncompleteTransactions": [],
            "IdAllocations": [],
            "AuditLog": [],
        })
        self.owner_user = {"user_id": "USR-OWNER-01", "role": "OWNER", "full_name": "Owner Admin"}

    def _get_stock(self, mat_id: str = "RM-WHOLE-MOONG-DAL") -> float:
        res = calculate_raw_material_balance(
            mat_id,
            db.get_records("RawMaterials"),
            db.get_records("RawMaterialLedger"),
        )
        return float(res.get("available", 0.0))

    # Scenario A: Failure during IncompleteTransactions append (fails closed, safe retry)
    async def test_failure_point_1_incomplete_transactions_write_failure(self):
        req = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=100.0,
            unit="kg",
            purchase_rate=110.0,
            supplier_name="Nimar Krishi Mandi",
            invoice_reference="INV-FAIL-INCOMP-01",
            line_number=1,
        )

        original_append = db.append_record
        first_attempt = True
        def simulated_append(tab, record, raise_on_error=False):
            nonlocal first_attempt
            if tab == "IncompleteTransactions" and first_attempt:
                first_attempt = False
                raise RuntimeError("Simulated network timeout appending IncompleteTransactions")
            return original_append(tab, record, raise_on_error=raise_on_error)

        with patch.object(db, "append_record", side_effect=simulated_append):
            with self.assertRaises(HTTPException) as ctx:
                await receive_raw_material(req, self.owner_user)
            self.assertEqual(ctx.exception.status_code, 503)
            self.assertIn("intent", ctx.exception.detail.lower())

            # Verify no ledger row created and stock remains 0
            self.assertEqual(len(db.get_records("RawMaterialLedger")), 0)
            self.assertEqual(self._get_stock(), 0.0)

            # Retry succeeds cleanly
            res = await receive_raw_material(req, self.owner_user)
            self.assertEqual(res.status, "SUCCESS")
            self.assertEqual(res.quantity, 100.0)
            self.assertEqual(self._get_stock(), 100.0)

        # Ledger now contains exactly 1 row
        ledger = db.get_records("RawMaterialLedger")
        self.assertEqual(len(ledger), 1)

    # Scenario B: Failure during RawMaterialLedger append (fails closed, status PARTIAL_FAILED)
    async def test_failure_point_2_ledger_append_failure_and_retry(self):
        req = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=100.0,
            unit="kg",
            purchase_rate=110.0,
            supplier_name="Nimar Krishi Mandi",
            invoice_reference="INV-FAIL-LEDGER-01",
            line_number=1,
        )

        original_append = db.append_record
        first_call = True
        def failing_ledger_append(tab, record, raise_on_error=False):
            nonlocal first_call
            if tab == "RawMaterialLedger" and first_call:
                first_call = False
                raise RuntimeError("Simulated Google Sheets 503 Service Unavailable")
            return original_append(tab, record, raise_on_error=raise_on_error)

        with patch.object(db, "append_record", side_effect=failing_ledger_append):
            with self.assertRaises(HTTPException) as ctx:
                await receive_raw_material(req, self.owner_user)
            self.assertEqual(ctx.exception.status_code, 503)

        # Confirm stock is still 0.0 and ledger is empty
        self.assertEqual(self._get_stock(), 0.0)
        self.assertEqual(len(db.get_records("RawMaterialLedger")), 0)

        # Confirm IncompleteTransactions has PARTIAL_FAILED row
        incomp = db.get_records("IncompleteTransactions")
        self.assertEqual(len(incomp), 1)
        self.assertEqual(incomp[0]["status"], "PARTIAL_FAILED")

        # Now client retries the identical request after network recovery
        res_retry = await receive_raw_material(req, self.owner_user)
        self.assertEqual(res_retry.status, "SUCCESS")
        self.assertEqual(res_retry.new_available_stock, 100.0)
        self.assertEqual(self._get_stock(), 100.0)
        self.assertEqual(len(db.get_records("RawMaterialLedger")), 1)

    # Scenario C: Post-write verification failure simulation and idempotent replay
    async def test_failure_point_3_post_write_verification_and_retry(self):
        req = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=150.0,
            unit="kg",
            purchase_rate=108.0,
            supplier_name="Nimar Krishi Mandi",
            invoice_reference="INV-FAIL-POSTREAD-01",
            line_number=1,
        )

        original_get = db.get_records
        append_occurred = False
        original_append = db.append_record

        def tracking_append(tab, record, raise_on_error=False):
            nonlocal append_occurred
            res = original_append(tab, record, raise_on_error=raise_on_error)
            if tab == "RawMaterialLedger":
                append_occurred = True
            return res

        def simulated_get_records(tab, fresh=False):
            if tab == "RawMaterialLedger" and fresh and append_occurred:
                # Return empty to simulate transient verification failure on read-back
                return []
            return original_get(tab, fresh=fresh)

        with patch.object(db, "append_record", side_effect=tracking_append), \
             patch.object(db, "get_records", side_effect=simulated_get_records):
            with self.assertRaises(HTTPException) as ctx:
                await receive_raw_material(req, self.owner_user)
            self.assertEqual(ctx.exception.status_code, 503)

        # Row WAS appended to ledger before the read-back failed
        self.assertEqual(len(db.get_records("RawMaterialLedger")), 1)
        self.assertEqual(self._get_stock(), 150.0)

        # Client retries identical request
        res_retry = await receive_raw_material(req, self.owner_user)
        self.assertEqual(res_retry.status, "ALREADY_RECORDED")
        self.assertTrue(res_retry.is_replay)
        self.assertEqual(res_retry.new_available_stock, 150.0)
        # Still exactly 1 row! No duplicate created
        self.assertEqual(len(db.get_records("RawMaterialLedger")), 1)
        self.assertEqual(self._get_stock(), 150.0)

    # Scenario D: Retry with conflicting payload after PARTIAL_FAILED
    async def test_failure_point_4_conflicting_retry_blocked(self):
        req_orig = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=100.0,
            unit="kg",
            purchase_rate=110.0,
            supplier_name="Nimar Krishi Mandi",
            invoice_reference="INV-FAIL-CONFLICT-01",
            line_number=1,
        )

        # Simulate initial failure at ledger append
        original_append = db.append_record
        def fail_append(tab, record, raise_on_error=False):
            if tab == "RawMaterialLedger":
                raise RuntimeError("Simulated failure")
            return original_append(tab, record, raise_on_error=raise_on_error)

        with patch.object(db, "append_record", side_effect=fail_append):
            with self.assertRaises(HTTPException):
                await receive_raw_material(req_orig, self.owner_user)

        # Now client attempts to retry with DIFFERENT quantity (200 kg) on the same invoice & line
        req_conflict = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=200.0,
            unit="kg",
            purchase_rate=110.0,
            supplier_name="Nimar Krishi Mandi",
            invoice_reference="INV-FAIL-CONFLICT-01",
            line_number=1,
        )
        with self.assertRaises(HTTPException) as ctx:
            await receive_raw_material(req_conflict, self.owner_user)

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("conflict", ctx.exception.detail.lower())
        self.assertEqual(self._get_stock(), 0.0)
        self.assertEqual(len(db.get_records("RawMaterialLedger")), 0)


if __name__ == "__main__":
    unittest.main()
