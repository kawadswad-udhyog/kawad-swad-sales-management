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
from app.calculations.costing import get_latest_purchase_rate
from app.recipes_master import calculate_recipe_cost
from app.routers.production import (
    receive_raw_material,
    RawMaterialReceiveRequest,
    record_dal_milling_batch,
    list_milling_history,
    DalMillingCreate,
)


class TestDalMillingStage2(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        for tab in REQUIRED_TABS:
            db.memory_store[tab] = []

        db.memory_store.update({
            "Users": [
                {"user_id": "USR-OWNER-01", "username": "owner", "role": "OWNER", "active": "true"},
            ],
            "RawMaterials": [
                {"raw_material_id": "RM-WHOLE-MOONG-DAL", "material_name": "Whole Moong Dal", "category": "WHOLE_GRAIN", "current_stock": 0.0, "unit": "kg", "rate_status": "APPROVED", "latest_landed_rate": 0.0},
                {"raw_material_id": "RM-MOONG-FLOUR", "material_name": "Moong Dal Flour", "category": "FLOUR", "current_stock": 0.0, "unit": "kg", "rate_status": "APPROVED", "latest_landed_rate": 0.0},
                {"raw_material_id": "RM-WHOLE-URAD-DAL", "material_name": "Whole Urad Dal", "category": "WHOLE_GRAIN", "current_stock": 0.0, "unit": "kg", "rate_status": "APPROVED", "latest_landed_rate": 0.0},
                {"raw_material_id": "RM-URAD-FLOUR", "material_name": "Urad Dal Flour", "category": "FLOUR", "current_stock": 0.0, "unit": "kg", "rate_status": "APPROVED", "latest_landed_rate": 0.0},
                {"raw_material_id": "RM-WHOLE-CHANA-DAL", "material_name": "Whole Chana Dal", "category": "WHOLE_GRAIN", "current_stock": 0.0, "unit": "kg", "rate_status": "APPROVED", "latest_landed_rate": 0.0},
                {"raw_material_id": "RM-CHANA-FLOUR", "material_name": "Chana Dal Flour", "category": "FLOUR", "current_stock": 0.0, "unit": "kg", "rate_status": "APPROVED", "latest_landed_rate": 0.0},
            ],
            "RawMaterialLedger": [],
            "IncompleteTransactions": [],
            "IdAllocations": [],
            "AuditLog": [],
        })
        self.owner_user = {"user_id": "USR-OWNER-01", "role": "OWNER", "full_name": "Owner Admin"}

    def _get_stock(self, mat_id: str) -> float:
        res = calculate_raw_material_balance(
            mat_id,
            db.get_records("RawMaterials"),
            db.get_records("RawMaterialLedger"),
        )
        return float(res.get("available", 0.0))

    async def test_exact_check2_numerical_example(self):
        """
        CHECK 2 Numerical Verification:
        - Whole Moong Dal input: 100 kg @ ₹110/kg (value ₹11,000)
        - Milling expenses: ₹300
        - Flour output: 98 kg (loss 2 kg / 2%)
        - Flour inventory valuation: exactly ₹11,300
        - Flour landed rate: 11300 / 98 = ₹115.306122.../kg -> ₹115.31/kg
        - Verify downstream recipe cost reads ₹115.31/kg
        """
        # 1. Receive 100 kg Whole Moong Dal @ ₹110
        await receive_raw_material(
            RawMaterialReceiveRequest(
                material_id="RM-WHOLE-MOONG-DAL",
                quantity=100.0,
                unit="kg",
                purchase_rate=110.0,
                supplier_name="Kisan Agro Mandi",
                invoice_reference="INV-EXACT-001",
                line_number=1,
            ),
            user=self.owner_user,
        )
        self.assertEqual(self._get_stock("RM-WHOLE-MOONG-DAL"), 100.0)

        # 2. Mill: 100 kg Whole Dal -> 98 kg Flour + ₹300 expense
        mill_resp = await record_dal_milling_batch(
            DalMillingCreate(
                source_material_id="RM-WHOLE-MOONG-DAL",
                input_quantity_kg=100.0,
                flour_output_kg=98.0,
                milling_expenses=300.0,
                milling_date="2026-10-28",
                batch_reference="RUN-EXACT-01",
            ),
            user=self.owner_user,
        )

        self.assertTrue(mill_resp.success)
        self.assertEqual(mill_resp.input_quantity_kg, 100.0)
        self.assertEqual(mill_resp.flour_output_kg, 98.0)
        self.assertEqual(mill_resp.processing_loss_kg, 2.0)
        self.assertEqual(mill_resp.loss_percentage, 2.0)
        self.assertEqual(mill_resp.source_unit_rate, 110.0)
        self.assertEqual(mill_resp.milling_expenses, 300.0)
        self.assertEqual(mill_resp.total_flour_cost, 11300.0)
        self.assertEqual(mill_resp.flour_unit_cost, 115.31)

        # 3. Stock verification
        self.assertEqual(self._get_stock("RM-WHOLE-MOONG-DAL"), 0.0)
        self.assertEqual(self._get_stock("RM-MOONG-FLOUR"), 98.0)

        # 4. Downstream Costing Integration
        raw_master = db.get_records("RawMaterials")
        raw_ledger = db.get_records("RawMaterialLedger")
        flour_rate_info = get_latest_purchase_rate("Moong Dal Flour", raw_master, raw_ledger)
        self.assertEqual(flour_rate_info.get("status"), "CONFIRMED")
        self.assertEqual(flour_rate_info.get("rate_per_canonical_unit"), 115.31)

        # 5. Papad recipe cost calculation using new flour rate
        recipe_items = [
            {"material_name": "Moong Dal Flour", "quantity": 1000, "unit": "g", "rate_per_unit": flour_rate_info["rate_per_canonical_unit"], "rate_status": "CONFIRMED"},
            {"material_name": "Salt", "quantity": 50, "unit": "g", "rate_per_unit": 20.0, "rate_status": "CONFIRMED"},
        ]
        calc = calculate_recipe_cost(recipe_items, expected_yield_kg=1.2)
        expected_batch_cost = round(115.31 + (50 / 1000.0 * 20.0), 2)  # 115.31 + 1.00 = 116.31
        self.assertEqual(calc["cost_per_batch"], expected_batch_cost)
        self.assertEqual(calc["cost_status"], "COMPLETE")

    async def test_failure_boundary_1_intent_write_failure_fails_closed(self):
        """
        CHECK 3 Boundary 1:
        Failure during intent write must fail closed (HTTP 503), preventing all ledger writes.
        Subsequent retry must succeed cleanly.
        """
        await receive_raw_material(
            RawMaterialReceiveRequest(
                material_id="RM-WHOLE-MOONG-DAL",
                quantity=100.0,
                unit="kg",
                purchase_rate=110.0,
                supplier_name="Kisan Agro",
                invoice_reference="INV-INTENT-FAIL-01",
            ),
            user=self.owner_user,
        )

        real_append = db.append_record
        attempt = [0]

        def fail_incomp(tab, rec, raise_on_error=False):
            if tab == "IncompleteTransactions" and attempt[0] == 0:
                attempt[0] += 1
                raise RuntimeError("Simulated transient network timeout writing IncompleteTransactions")
            return real_append(tab, rec, raise_on_error=raise_on_error)

        mill_req = DalMillingCreate(
            source_material_id="RM-WHOLE-MOONG-DAL",
            input_quantity_kg=50.0,
            flour_output_kg=49.0,
            milling_expenses=100.0,
            idempotency_key="IDEMP-INTENT-FAIL-01",
        )

        with patch.object(db, "append_record", side_effect=fail_incomp):
            with self.assertRaises(HTTPException) as ctx:
                await record_dal_milling_batch(mill_req, user=self.owner_user)
            self.assertEqual(ctx.exception.status_code, 503)

        # Whole dal stock remains completely untouched
        self.assertEqual(self._get_stock("RM-WHOLE-MOONG-DAL"), 100.0)
        self.assertEqual(self._get_stock("RM-MOONG-FLOUR"), 0.0)

        # Retry succeeds
        resp = await record_dal_milling_batch(mill_req, user=self.owner_user)
        self.assertEqual(resp.status, "SUCCESS")
        self.assertEqual(self._get_stock("RM-WHOLE-MOONG-DAL"), 50.0)
        self.assertEqual(self._get_stock("RM-MOONG-FLOUR"), 49.0)

    async def test_failure_boundary_2_leg1_written_leg2_failed_forward_recovery(self):
        """
        CHECK 3 Boundary 2:
        Simulate Leg 1 (consumption) succeeding, but Leg 2 (output) failing.
        When the operator retries the exact same request, the system MUST forward-recover Leg 2,
        without double-deducting Whole Dal or failing with 'Insufficient stock'.
        """
        await receive_raw_material(
            RawMaterialReceiveRequest(
                material_id="RM-WHOLE-URAD-DAL",
                quantity=100.0,
                unit="kg",
                purchase_rate=120.0,
                supplier_name="Urad Mandi",
                invoice_reference="INV-PARTIAL-LEG2-01",
            ),
            user=self.owner_user,
        )

        real_append = db.append_record
        attempt = [0]

        def fail_on_leg2(tab, rec, raise_on_error=False):
            if tab == "RawMaterialLedger" and rec.get("movement_type") == "MILLING_OUTPUT" and attempt[0] == 0:
                attempt[0] += 1
                raise RuntimeError("Simulated outage during Leg 2 MILLING_OUTPUT append")
            return real_append(tab, rec, raise_on_error=raise_on_error)

        mill_req = DalMillingCreate(
            source_material_id="RM-WHOLE-URAD-DAL",
            input_quantity_kg=100.0,  # All 100 kg
            flour_output_kg=97.5,
            milling_expenses=250.0,
            idempotency_key="IDEMP-PARTIAL-LEG2-RECOVER",
            batch_reference="BATCH-URAD-PARTIAL",
        )

        # Attempt 1: Leg 2 fails
        with patch.object(db, "append_record", side_effect=fail_on_leg2):
            with self.assertRaises(HTTPException) as ctx:
                await record_dal_milling_batch(mill_req, user=self.owner_user)
            self.assertEqual(ctx.exception.status_code, 503)

        # In memory store: Whole Dal was deducted in Leg 1, available is now 0 kg. Flour is 0 kg.
        self.assertEqual(self._get_stock("RM-WHOLE-URAD-DAL"), 0.0)
        self.assertEqual(self._get_stock("RM-URAD-FLOUR"), 0.0)

        # Attempt 2: Retry with identical payload -> MUST forward-recover Leg 2
        recover_resp = await record_dal_milling_batch(mill_req, user=self.owner_user)
        self.assertEqual(recover_resp.status, "SUCCESS")
        self.assertIn("Forward-recovered", recover_resp.message)

        # Verify stock: Whole Dal deducted exactly once (0 kg), Flour credited (97.5 kg)
        self.assertEqual(self._get_stock("RM-WHOLE-URAD-DAL"), 0.0)
        self.assertEqual(self._get_stock("RM-URAD-FLOUR"), 97.5)

        # Verify ledger has exactly 3 rows: 1 receipt + 1 consumption + 1 output
        ledger_rows = db.get_records("RawMaterialLedger")
        self.assertEqual(len(ledger_rows), 3)

        # IncompleteTransactions marked COMPLETED
        incomp_records = db.get_records("IncompleteTransactions")
        self.assertTrue(any(t.get("status") == "COMPLETED" for t in incomp_records))

    async def test_failure_boundary_3_readback_failure_and_retry(self):
        """
        CHECK 3 Boundary 3 & 4:
        Simulate readback verification failure right after Leg 2 is written.
        Client retry must detect existing batch and return ALREADY_RECORDED without duplicate movements.
        """
        await receive_raw_material(
            RawMaterialReceiveRequest(
                material_id="RM-WHOLE-CHANA-DAL",
                quantity=100.0,
                unit="kg",
                purchase_rate=75.0,
                supplier_name="Chana Mandi",
                invoice_reference="INV-READBACK-01",
            ),
            user=self.owner_user,
        )

        real_get = db.get_records
        fail_readback = [True]

        def mock_readback(tab, fresh=False):
            res = real_get(tab, fresh=fresh)
            if tab == "RawMaterialLedger" and fresh and fail_readback[0]:
                # Check if output is in memory
                if any(r.get("movement_type") == "MILLING_OUTPUT" for r in res):
                    fail_readback[0] = False
                    # Return empty list simulating readback error
                    return []
            return res

        mill_req = DalMillingCreate(
            source_material_id="RM-WHOLE-CHANA-DAL",
            input_quantity_kg=50.0,
            flour_output_kg=48.5,
            milling_expenses=120.0,
            idempotency_key="IDEMP-READBACK-TEST",
        )

        with patch.object(db, "get_records", side_effect=mock_readback):
            with self.assertRaises(HTTPException) as ctx:
                await record_dal_milling_batch(mill_req, user=self.owner_user)
            self.assertEqual(ctx.exception.status_code, 503)

        # On retry, readback succeeds, ALREADY_RECORDED returned
        retry_resp = await record_dal_milling_batch(mill_req, user=self.owner_user)
        self.assertEqual(retry_resp.status, "ALREADY_RECORDED")
        self.assertTrue(retry_resp.is_replay)
        self.assertEqual(self._get_stock("RM-WHOLE-CHANA-DAL"), 50.0)
        self.assertEqual(self._get_stock("RM-CHANA-FLOUR"), 48.5)

    async def test_failure_boundary_4_concurrent_requests_serialized(self):
        """
        CHECK 3 Boundary 8:
        Two concurrent requests with identical parameters must be serialized by mutex.
        One creates the batch, the other returns ALREADY_RECORDED. Stock moved exactly once.
        """
        await receive_raw_material(
            RawMaterialReceiveRequest(
                material_id="RM-WHOLE-MOONG-DAL",
                quantity=100.0,
                unit="kg",
                purchase_rate=110.0,
                supplier_name="Kisan Agro",
                invoice_reference="INV-CONCURRENT-01",
            ),
            user=self.owner_user,
        )

        mill_req = DalMillingCreate(
            source_material_id="RM-WHOLE-MOONG-DAL",
            input_quantity_kg=50.0,
            flour_output_kg=49.0,
            milling_expenses=150.0,
            idempotency_key="IDEMP-CONCURRENT-MIL-01",
        )

        res1, res2 = await asyncio.gather(
            record_dal_milling_batch(mill_req, user=self.owner_user),
            record_dal_milling_batch(mill_req, user=self.owner_user),
        )

        statuses = {res1.status, res2.status}
        self.assertIn("SUCCESS", statuses)
        self.assertIn("ALREADY_RECORDED", statuses)
        self.assertEqual(self._get_stock("RM-WHOLE-MOONG-DAL"), 50.0)
        self.assertEqual(self._get_stock("RM-MOONG-FLOUR"), 49.0)

    async def test_check4_validation_rules(self):
        """
        CHECK 4 Validation Rules:
        - Output cannot exceed input.
        - Whole Dal stock cannot be overdrawn.
        - Negative or zero quantities rejected.
        - Invalid material types rejected.
        - Incomplete batches excluded from history.
        """
        # 1. Output > Input rejected (HTTP 422)
        with self.assertRaises(HTTPException) as ctx:
            await record_dal_milling_batch(
                DalMillingCreate(
                    source_material_id="RM-WHOLE-MOONG-DAL",
                    input_quantity_kg=100.0,
                    flour_output_kg=105.0,
                ),
                user=self.owner_user,
            )
        self.assertEqual(ctx.exception.status_code, 422)

        # 2. Stock overdraw rejected (HTTP 400)
        with self.assertRaises(HTTPException) as ctx:
            await record_dal_milling_batch(
                DalMillingCreate(
                    source_material_id="RM-WHOLE-MOONG-DAL",
                    input_quantity_kg=100.0,
                    flour_output_kg=98.0,
                ),
                user=self.owner_user,
            )
        self.assertEqual(ctx.exception.status_code, 400)

        # 3. Invalid material (not a supported whole dal) rejected (HTTP 422)
        with self.assertRaises(HTTPException) as ctx:
            await record_dal_milling_batch(
                DalMillingCreate(
                    source_material_id="RM-SALT",
                    input_quantity_kg=10.0,
                    flour_output_kg=10.0,
                ),
                user=self.owner_user,
            )
        self.assertEqual(ctx.exception.status_code, 422)

        # 4. Incomplete batch (Leg 1 only) not listed in completed history
        db.memory_store["RawMaterialLedger"].append({
            "raw_material_txn_id": "RML-INCOMPLETE-01",
            "txn_datetime": "2026-10-28",
            "material_name": "Whole Moong Dal",
            "raw_material_id": "RM-WHOLE-MOONG-DAL",
            "movement_type": "MILLING_CONSUMPTION",
            "quantity": 50.0,
            "unit": "kg",
            "rate_per_unit": 110.0,
            "issue_txn_id": "MIL-INCOMPLETE",
            "notes": "{}",
        })
        history = await list_milling_history(user=self.owner_user)
        self.assertEqual(len(history), 0)


if __name__ == "__main__":
    unittest.main()
