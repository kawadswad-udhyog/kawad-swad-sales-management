import os
import sys
import unittest
import asyncio
from fastapi import HTTPException

os.environ["SALES_TESTING"] = "1"
os.environ["SALES_JWT_SECRET"] = "test-only-secret-do-not-use-for-deployment-32"

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.sheets import db, REQUIRED_TABS
from app.calculations.inventory import calculate_raw_material_balance
from app.calculations.costing import get_latest_purchase_rate
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

    async def test_successful_milling_run_costing_and_stock_transfer(self):
        """
        Scenario 1: Full lifecycle test
        - Inward Whole Moong Dal: 100 kg @ ₹110.00/kg
        - Mill into Moong Dal Flour: 100 kg input -> 98 kg flour output + ₹300 milling expense
        - Cost Transfer: Dal basis (₹11,000) + Exp (₹300) = ₹11,300 total cost
        - Landed Flour Rate: ₹11,300 / 98 = ₹115.31 / kg (loss of 2.0 kg / 2.0% absorbed into rate)
        - Stock balance: Whole Dal -> 0 kg, Flour -> 98 kg
        - Atomic Ledger records: 1 MILLING_CONSUMPTION row + 1 MILLING_OUTPUT row linked by milling_batch_id
        """
        # Step 1: Inward Whole Dal
        recv_req = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=100.0,
            unit="kg",
            purchase_rate=110.0,
            supplier_name="Kisan Agro Mandi",
            invoice_reference="INV-DAL-001",
            line_number=1,
        )
        recv_resp = await receive_raw_material(recv_req, user=self.owner_user)
        self.assertEqual(recv_resp.status, "SUCCESS")
        self.assertEqual(self._get_stock("RM-WHOLE-MOONG-DAL"), 100.0)
        self.assertEqual(self._get_stock("RM-MOONG-FLOUR"), 0.0)

        # Step 2: Mill Whole Dal to Flour
        mill_req = DalMillingCreate(
            source_material_id="RM-WHOLE-MOONG-DAL",
            input_quantity_kg=100.0,
            flour_output_kg=98.0,
            milling_expenses=300.0,
            milling_date="2026-10-28",
            batch_reference="RUN-MILL-01",
            notes="Standard stone mill pass 1",
        )
        mill_resp = await record_dal_milling_batch(mill_req, user=self.owner_user)

        self.assertTrue(mill_resp.success)
        self.assertEqual(mill_resp.status, "SUCCESS")
        self.assertEqual(mill_resp.source_material_id, "RM-WHOLE-MOONG-DAL")
        self.assertEqual(mill_resp.target_flour_id, "RM-MOONG-FLOUR")
        self.assertEqual(mill_resp.input_quantity_kg, 100.0)
        self.assertEqual(mill_resp.flour_output_kg, 98.0)
        self.assertEqual(mill_resp.processing_loss_kg, 2.0)
        self.assertEqual(mill_resp.loss_percentage, 2.0)
        self.assertEqual(mill_resp.source_unit_rate, 110.0)
        self.assertEqual(mill_resp.milling_expenses, 300.0)
        self.assertEqual(mill_resp.total_flour_cost, 11300.0)
        self.assertEqual(mill_resp.flour_unit_cost, 115.31)
        self.assertFalse(mill_resp.is_replay)

        # Step 3: Verify Stock Balances
        self.assertEqual(self._get_stock("RM-WHOLE-MOONG-DAL"), 0.0)
        self.assertEqual(self._get_stock("RM-MOONG-FLOUR"), 98.0)

        # Step 4: Verify Ledger Integrity
        ledger_rows = db.get_records("RawMaterialLedger")
        # Total rows: 1 receipt + 1 milling consumption + 1 milling output = 3 rows
        self.assertEqual(len(ledger_rows), 3)

        cons_row = next(r for r in ledger_rows if r.get("movement_type") == "MILLING_CONSUMPTION")
        self.assertEqual(cons_row.get("issue_txn_id"), mill_resp.milling_batch_id)
        self.assertEqual(cons_row.get("raw_material_id"), "RM-WHOLE-MOONG-DAL")
        self.assertEqual(float(cons_row.get("quantity")), 100.0)
        self.assertEqual(float(cons_row.get("rate_per_unit")), 110.0)

        out_row = next(r for r in ledger_rows if r.get("movement_type") == "MILLING_OUTPUT")
        self.assertEqual(out_row.get("issue_txn_id"), mill_resp.milling_batch_id)
        self.assertEqual(out_row.get("raw_material_id"), "RM-MOONG-FLOUR")
        self.assertEqual(float(out_row.get("quantity")), 98.0)
        self.assertEqual(float(out_row.get("rate_per_unit")), 115.31)

        # Step 5: Verify Flour rate automatically feeds downstream costing
        raw_master = db.get_records("RawMaterials")
        flour_cost = get_latest_purchase_rate("Moong Dal Flour", raw_master, ledger_rows)
        self.assertEqual(flour_cost.get("rate_per_canonical_unit"), 115.31)
        self.assertEqual(flour_cost.get("status"), "CONFIRMED")

    async def test_insufficient_stock_fails(self):
        """
        Attempting to mill more whole dal than is in stock must fail with HTTP 400.
        """
        # Stock is 0
        mill_req = DalMillingCreate(
            source_material_id="RM-WHOLE-URAD-DAL",
            input_quantity_kg=50.0,
            flour_output_kg=49.0,
            milling_expenses=100.0,
        )
        with self.assertRaises(HTTPException) as ctx:
            await record_dal_milling_batch(mill_req, user=self.owner_user)
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Insufficient", ctx.exception.detail)
        self.assertEqual(len(db.get_records("RawMaterialLedger")), 0)

    async def test_flour_output_exceeding_input_rejected(self):
        """
        Flour output cannot exceed input quantity (gain of matter impossible in grinding).
        """
        mill_req = DalMillingCreate(
            source_material_id="RM-WHOLE-CHANA-DAL",
            input_quantity_kg=100.0,
            flour_output_kg=105.0,  # Invalid!
        )
        with self.assertRaises(HTTPException) as ctx:
            await record_dal_milling_batch(mill_req, user=self.owner_user)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("cannot exceed", ctx.exception.detail)

    async def test_zero_or_negative_quantities_rejected(self):
        mill_req_zero_in = DalMillingCreate(
            source_material_id="RM-WHOLE-MOONG-DAL",
            input_quantity_kg=0.0,
            flour_output_kg=10.0,
        )
        with self.assertRaises(HTTPException) as ctx1:
            await record_dal_milling_batch(mill_req_zero_in, user=self.owner_user)
        self.assertEqual(ctx1.exception.status_code, 422)

        mill_req_zero_out = DalMillingCreate(
            source_material_id="RM-WHOLE-MOONG-DAL",
            input_quantity_kg=50.0,
            flour_output_kg=-5.0,
        )
        with self.assertRaises(HTTPException) as ctx2:
            await record_dal_milling_batch(mill_req_zero_out, user=self.owner_user)
        self.assertEqual(ctx2.exception.status_code, 422)

    async def test_idempotent_replay_preserves_stock_and_returns_already_recorded(self):
        """
        Re-submitting an identical milling batch must return ALREADY_RECORDED and not double-deduct.
        """
        # Inward 100 kg
        await receive_raw_material(
            RawMaterialReceiveRequest(
                material_id="RM-WHOLE-URAD-DAL",
                quantity=100.0,
                purchase_rate=120.0,
                supplier_name="Urad Mandi",
                invoice_reference="INV-URAD-01",
                line_number=1,
            ),
            user=self.owner_user,
        )

        mill_req = DalMillingCreate(
            source_material_id="RM-WHOLE-URAD-DAL",
            input_quantity_kg=50.0,
            flour_output_kg=48.5,
            milling_expenses=150.0,
            idempotency_key="IDEMP-MILL-URAD-001",
            batch_reference="BATCH-URAD-RUN1",
        )

        resp1 = await record_dal_milling_batch(mill_req, user=self.owner_user)
        self.assertEqual(resp1.status, "SUCCESS")
        self.assertFalse(resp1.is_replay)
        self.assertEqual(self._get_stock("RM-WHOLE-URAD-DAL"), 50.0)
        self.assertEqual(self._get_stock("RM-URAD-FLOUR"), 48.5)

        # Re-submit identical batch
        resp2 = await record_dal_milling_batch(mill_req, user=self.owner_user)
        self.assertEqual(resp2.status, "ALREADY_RECORDED")
        self.assertTrue(resp2.is_replay)
        self.assertEqual(resp2.milling_batch_id, resp1.milling_batch_id)

        # Stock must NOT be deducted twice
        self.assertEqual(self._get_stock("RM-WHOLE-URAD-DAL"), 50.0)
        self.assertEqual(self._get_stock("RM-URAD-FLOUR"), 48.5)

    async def test_conflicting_replay_returns_409(self):
        """
        Re-submitting with same idempotency key but different flour output must return 409 Conflict.
        """
        await receive_raw_material(
            RawMaterialReceiveRequest(
                material_id="RM-WHOLE-CHANA-DAL",
                quantity=100.0,
                purchase_rate=95.0,
                supplier_name="Chana Mandi",
                invoice_reference="INV-CHANA-01",
                line_number=1,
            ),
            user=self.owner_user,
        )

        mill_req1 = DalMillingCreate(
            source_material_id="RM-WHOLE-CHANA-DAL",
            input_quantity_kg=50.0,
            flour_output_kg=48.0,
            idempotency_key="IDEMP-MILL-CHANA-CONF",
        )
        await record_dal_milling_batch(mill_req1, user=self.owner_user)

        mill_req2 = DalMillingCreate(
            source_material_id="RM-WHOLE-CHANA-DAL",
            input_quantity_kg=50.0,
            flour_output_kg=46.0,  # Conflicting output!
            idempotency_key="IDEMP-MILL-CHANA-CONF",
        )
        with self.assertRaises(HTTPException) as ctx:
            await record_dal_milling_batch(mill_req2, user=self.owner_user)
        self.assertEqual(ctx.exception.status_code, 409)

    async def test_milling_history_retrieval(self):
        """
        Verify GET /api/production/milling/history reconstructs history items correctly.
        """
        await receive_raw_material(
            RawMaterialReceiveRequest(
                material_id="RM-WHOLE-MOONG-DAL",
                quantity=100.0,
                purchase_rate=110.0,
                supplier_name="Kisan Agro Mandi",
                invoice_reference="INV-DAL-HIST",
                line_number=1,
            ),
            user=self.owner_user,
        )
        await record_dal_milling_batch(
            DalMillingCreate(
                source_material_id="RM-WHOLE-MOONG-DAL",
                input_quantity_kg=60.0,
                flour_output_kg=58.5,
                milling_expenses=180.0,
                milling_date="2026-10-28",
                batch_reference="RUN-HIST-01",
                notes="History test batch",
            ),
            user=self.owner_user,
        )

        history = await list_milling_history(user=self.owner_user)
        self.assertEqual(len(history), 1)
        item = history[0]
        self.assertEqual(item.source_material_id, "RM-WHOLE-MOONG-DAL")
        self.assertEqual(item.target_flour_id, "RM-MOONG-FLOUR")
        self.assertEqual(item.input_quantity_kg, 60.0)
        self.assertEqual(item.flour_output_kg, 58.5)
        self.assertEqual(item.batch_reference, "RUN-HIST-01")
        self.assertEqual(item.notes, "History test batch")


if __name__ == "__main__":
    unittest.main()
