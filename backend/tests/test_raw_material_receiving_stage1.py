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
from app.routers.production import (
    receive_raw_material,
    get_raw_material_balances,
    RawMaterialReceiveRequest,
    ProductionCreate,
    create_batch,
    approve_batch,
    ApprovalRequest,
)


class TestRawMaterialReceivingStage1(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Ensure all required tabs exist in memory store to prevent cross-test leakage
        for tab in REQUIRED_TABS:
            db.memory_store.setdefault(tab, [])

        db.memory_store.update({
            "Users": [
                {"user_id": "USR-OWNER-01", "username": "owner", "role": "OWNER", "active": "true"},
                {"user_id": "USR-PA-01", "username": "pa_user", "role": "PA", "active": "true"},
            ],
            "RawMaterials": [
                {"raw_material_id": "RM-WHOLE-MOONG-DAL", "material_name": "Whole Moong Dal", "category": "WHOLE_GRAIN", "current_stock": 0.0, "unit": "kg"},
                {"raw_material_id": "RM-WHOLE-URAD-DAL", "material_name": "Whole Urad Dal", "category": "WHOLE_GRAIN", "current_stock": 0.0, "unit": "kg"},
                {"raw_material_id": "RM-WHOLE-CHANA-DAL", "material_name": "Whole Chana Dal", "category": "WHOLE_GRAIN", "current_stock": 0.0, "unit": "kg"},
                {"raw_material_id": "RM-MOONG-FLOUR", "material_name": "Moong Dal Flour", "category": "FLOUR", "current_stock": 500.0, "unit": "kg"},
                {"raw_material_id": "RM-URAD-FLOUR", "material_name": "Urad Dal Flour", "category": "FLOUR", "current_stock": 300.0, "unit": "kg"},
                {"raw_material_id": "RM-CHANA-FLOUR", "material_name": "Chana Dal Flour", "category": "FLOUR", "current_stock": 200.0, "unit": "kg"},
                {"raw_material_id": "RAW-02", "material_name": "Black Pepper", "category": "SPICE", "current_stock": 50.0, "unit": "kg"},
                {"raw_material_id": "RAW-03", "material_name": "Hing", "category": "SPICE", "current_stock": 20.0, "unit": "kg"},
                {"raw_material_id": "RAW-04", "material_name": "Salt", "category": "SPICE", "current_stock": 100.0, "unit": "kg"},
            ],
            "RawMaterialLedger": [],
            "IncompleteTransactions": [],
            "IdAllocations": [],
            "AuditLog": [],
            "Products": [
                {
                    "product_id": "PRD-MOONG-MASTER",
                    "sku": "MM-01",
                    "product_name": "Moong Master",
                    "category": "Papad",
                    "pack_weight_g": "500",
                    "active": "true",
                }
            ],
            "Recipes": [
                {
                    "recipe_id": "RCP-MM-01",
                    "product_id": "PRD-MOONG-MASTER",
                    "product_name_snapshot": "Moong Master",
                    "version": "1",
                    "approved": "true",
                    "expected_yield_kg": "1.2",
                    "items_json": '[{"material_name": "Moong Dal Flour", "quantity_per_kg": 0.8333, "unit": "kg"}, {"material_name": "Black Pepper", "quantity_per_kg": 0.0125, "unit": "kg"}, {"material_name": "Hing", "quantity_per_kg": 0.0042, "unit": "kg"}, {"material_name": "Salt", "quantity_per_kg": 0.0417, "unit": "kg"}]',
                }
            ],
            "ProductionBatches": [],
            "ProductionStockLedger": [],
            "PackagingBatches": [],
            "ProductionDispatches": [],
            "Workers": [
                {"worker_id": "WRK-001", "worker_name": "Sita Devi", "daily_wage": 400.0, "active": "true"},
            ],
            "ApprovalRequests": [],
        })

        self.owner_user = {"user_id": "USR-OWNER-01", "role": "OWNER", "full_name": "Owner Admin"}
        self.pa_user = {"user_id": "USR-PA-01", "role": "PA", "full_name": "PA Manager"}

    def _get_available_stock(self, material_id_or_name: str) -> float:
        res = calculate_raw_material_balance(
            material_id_or_name,
            db.get_records("RawMaterials"),
            db.get_records("RawMaterialLedger"),
        )
        return float(res.get("available", 0.0))

    # SCENARIO 1: Whole-dal receipt works for Whole Moong Dal
    async def test_1_whole_moong_dal_receipt_success(self):
        req = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=100.0,
            unit="kg",
            purchase_rate=110.0,
            receipt_date="2026-10-28",
            supplier_name="Nimar Krishi Mandi, Barwani",
            invoice_reference="INV-NIMAR-001",
            line_number=1,
            freight_amount=500.0,
            other_expenses=200.0,
            gst_amount=0.0,
            gst_treatment="EXEMPT_NIL_RATED",
            notes="Initial whole moong consignment",
        )
        res = await receive_raw_material(req, self.owner_user)
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.material_id, "RM-WHOLE-MOONG-DAL")
        self.assertEqual(res.quantity, 100.0)
        self.assertFalse(res.is_replay)
        self.assertTrue(res.transaction_id.startswith("RML-"))

        # Verify ledger row exists
        ledger = db.get_records("RawMaterialLedger")
        self.assertEqual(len(ledger), 1)
        self.assertEqual(ledger[0]["movement_type"], "PURCHASE_RECEIPT")
        self.assertEqual(float(ledger[0]["quantity"]), 100.0)

    # SCENARIO 2: Correct stock balance increase in inventory calculations
    async def test_2_stock_balance_increase(self):
        bal_before = self._get_available_stock("RM-WHOLE-MOONG-DAL")
        self.assertEqual(bal_before, 0.0)

        req = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=250.0,
            unit="kg",
            purchase_rate=108.0,
            receipt_date="2026-10-28",
            supplier_name="Nimar Krishi Mandi, Barwani",
            invoice_reference="INV-NIMAR-002",
            line_number=1,
            freight_amount=0.0,
            other_expenses=0.0,
            gst_amount=0.0,
            gst_treatment="EXEMPT_NIL_RATED",
        )
        res = await receive_raw_material(req, self.owner_user)
        self.assertEqual(res.new_available_stock, 250.0)

        # Confirm calculate_raw_material_balance reads from RawMaterialLedger
        bal_after = self._get_available_stock("RM-WHOLE-MOONG-DAL")
        self.assertEqual(bal_after, 250.0)

        # Confirm GET /api/production/raw-materials balance endpoint
        balances = await get_raw_material_balances(self.owner_user)
        moong = next((b for b in balances if b.raw_material_id == "RM-WHOLE-MOONG-DAL"), None)
        self.assertIsNotNone(moong)
        self.assertEqual(moong.available_stock, 250.0)
        self.assertEqual(moong.received, 250.0)
        self.assertEqual(moong.opening_stock, 0.0)

    # SCENARIO 3: Correct landed cost calculation with freight and additional expenses
    async def test_3_landed_cost_calculation(self):
        # 100 kg @ ₹110 = ₹11,000 base
        # Freight = ₹500, Other = ₹200
        # Total Landed Cost = ₹11,700
        # Effective Landed Rate = ₹11,700 / 100 = ₹117.00/kg
        req = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=100.0,
            unit="kg",
            purchase_rate=110.0,
            receipt_date="2026-10-28",
            supplier_name="Nimar Krishi Mandi, Barwani",
            invoice_reference="INV-NIMAR-003",
            line_number=1,
            freight_amount=500.0,
            other_expenses=200.0,
            gst_amount=0.0,
            gst_treatment="EXEMPT_NIL_RATED",
        )
        res = await receive_raw_material(req, self.owner_user)
        self.assertEqual(res.base_value, 11000.0)
        self.assertEqual(res.total_landed_cost, 11700.0)
        self.assertEqual(res.landed_rate_per_unit, 117.0)

        ledger = db.get_records("RawMaterialLedger")
        self.assertEqual(float(ledger[0]["rate_per_unit"]), 117.0)

    # SCENARIO 4: Identical request replay returns HTTP 200 without duplicate stock
    async def test_4_identical_request_replay_idempotent(self):
        req = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=100.0,
            unit="kg",
            purchase_rate=110.0,
            receipt_date="2026-10-28",
            supplier_name="Nimar Krishi Mandi, Barwani",
            invoice_reference="INV-NIMAR-REPLAY",
            line_number=1,
            freight_amount=250.0,
            other_expenses=50.0,
            gst_treatment="RECOVERABLE_ITC",
        )
        res1 = await receive_raw_material(req, self.owner_user)
        self.assertFalse(res1.is_replay)
        self.assertEqual(res1.status, "SUCCESS")

        # Second submission with identical payload
        res2 = await receive_raw_material(req, self.owner_user)
        self.assertTrue(res2.is_replay)
        self.assertEqual(res2.status, "ALREADY_RECORDED")
        self.assertEqual(res1.transaction_id, res2.transaction_id)
        self.assertEqual(res2.new_available_stock, 100.0)

        # Confirm ledger only has 1 row
        ledger = db.get_records("RawMaterialLedger")
        self.assertEqual(len(ledger), 1)

    # SCENARIO 5: Reused invoice reference and line with different payload raises HTTP 409
    async def test_5_reused_key_different_payload_conflict(self):
        req1 = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=100.0,
            unit="kg",
            purchase_rate=110.0,
            receipt_date="2026-10-28",
            supplier_name="Nimar Krishi Mandi",
            invoice_reference="INV-CONFLICT-01",
            line_number=1,
        )
        await receive_raw_material(req1, self.owner_user)

        # Altered payload using the same invoice and line number
        req2 = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=150.0,  # Changed quantity
            unit="kg",
            purchase_rate=110.0,
            receipt_date="2026-10-28",
            supplier_name="Nimar Krishi Mandi",
            invoice_reference="INV-CONFLICT-01",
            line_number=1,
        )
        with self.assertRaises(HTTPException) as ctx:
            await receive_raw_material(req2, self.owner_user)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("conflict", ctx.exception.detail.lower())

    # SCENARIO 6: Different lines on same invoice succeed independently
    async def test_6_multiple_lines_same_invoice(self):
        # Line 1: 100 kg Whole Moong Dal
        req_line1 = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=100.0,
            unit="kg",
            purchase_rate=110.0,
            receipt_date="2026-10-28",
            supplier_name="Nimar Krishi Mandi",
            invoice_reference="INV-MULTI-LINE-01",
            line_number=1,
        )
        # Line 2: 80 kg Whole Urad Dal
        req_line2 = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-URAD-DAL",
            quantity=80.0,
            unit="kg",
            purchase_rate=120.0,
            receipt_date="2026-10-28",
            supplier_name="Nimar Krishi Mandi",
            invoice_reference="INV-MULTI-LINE-01",
            line_number=2,
        )

        res1 = await receive_raw_material(req_line1, self.owner_user)
        res2 = await receive_raw_material(req_line2, self.owner_user)

        self.assertEqual(res1.status, "SUCCESS")
        self.assertEqual(res2.status, "SUCCESS")
        self.assertNotEqual(res1.transaction_id, res2.transaction_id)

        # Verify balances
        self.assertEqual(self._get_available_stock("RM-WHOLE-MOONG-DAL"), 100.0)
        self.assertEqual(self._get_available_stock("RM-WHOLE-URAD-DAL"), 80.0)

    # SCENARIO 7: Whole Chana Dal receiving
    async def test_7_whole_chana_dal_receiving(self):
        req = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-CHANA-DAL",
            quantity=300.0,
            unit="kg",
            purchase_rate=75.0,
            receipt_date="2026-10-28",
            supplier_name="Indore Mandi Traders",
            invoice_reference="INV-CHANA-01",
            line_number=1,
            freight_amount=600.0,
            other_expenses=150.0,
            gst_treatment="EXEMPT_NIL_RATED",
        )
        res = await receive_raw_material(req, self.owner_user)
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.material_id, "RM-WHOLE-CHANA-DAL")
        self.assertEqual(res.quantity, 300.0)
        # 300 * 75 = 22,500 + 750 = 23,250 / 300 = 77.50
        self.assertEqual(res.landed_rate_per_unit, 77.50)
        self.assertEqual(self._get_available_stock("RM-WHOLE-CHANA-DAL"), 300.0)

    # SCENARIO 8: Validation rejects non-positive quantity
    async def test_8_validation_rejects_non_positive_quantity(self):
        req_zero = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=-1.0,  # Negative
            unit="kg",
            purchase_rate=110.0,
            supplier_name="Nimar Traders",
            invoice_reference="INV-INV-01",
        )
        with self.assertRaises(HTTPException) as ctx:
            await receive_raw_material(req_zero, self.owner_user)
        self.assertEqual(ctx.exception.status_code, 422)

    # SCENARIO 9: Validation rejects non-positive purchase rate
    async def test_9_validation_rejects_non_positive_rate(self):
        req_zero_rate = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=100.0,
            unit="kg",
            purchase_rate=-1.0,
            supplier_name="Nimar Traders",
            invoice_reference="INV-INV-02",
        )
        with self.assertRaises(HTTPException) as ctx:
            await receive_raw_material(req_zero_rate, self.owner_user)
        self.assertEqual(ctx.exception.status_code, 422)

    # SCENARIO 10: Validation rejects unknown raw material
    async def test_10_validation_rejects_unknown_raw_material(self):
        req = RawMaterialReceiveRequest(
            material_id="RM-DOES-NOT-EXIST-999",
            quantity=100.0,
            unit="kg",
            purchase_rate=100.0,
            supplier_name="Nimar Traders",
            invoice_reference="INV-INV-03",
        )
        with self.assertRaises(HTTPException) as ctx:
            await receive_raw_material(req, self.owner_user)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("not found in RawMaterials master", ctx.exception.detail)

    # SCENARIO 11: Recoverable GST (RECOVERABLE_ITC) excludes tax from landed inventory cost
    async def test_11_gst_recoverable_itc_excluded_from_cost(self):
        # 100 kg @ ₹110 = ₹11,000 base
        # Freight = ₹500, Other = ₹0
        # GST Amount = ₹550 (5% GST)
        # Treatment = RECOVERABLE_ITC
        # Total Landed Cost must EXCLUDE GST = ₹11,500
        # Rate per unit = ₹11,500 / 100 = ₹115.00
        req = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=100.0,
            unit="kg",
            purchase_rate=110.0,
            receipt_date="2026-10-28",
            supplier_name="Nimar Krishi Mandi",
            invoice_reference="INV-GST-ITC-01",
            line_number=1,
            freight_amount=500.0,
            other_expenses=0.0,
            gst_amount=550.0,
            gst_treatment="RECOVERABLE_ITC",
        )
        res = await receive_raw_material(req, self.owner_user)
        self.assertEqual(res.gst_amount, 550.0)
        self.assertEqual(res.gst_treatment, "RECOVERABLE_ITC")
        self.assertEqual(res.total_landed_cost, 11500.0)
        self.assertEqual(res.landed_rate_per_unit, 115.0)

        ledger = db.get_records("RawMaterialLedger")
        self.assertEqual(float(ledger[0]["rate_per_unit"]), 115.0)

    # SCENARIO 12: Capitalized GST (CAPITALIZED_TO_COST) includes tax in landed inventory cost
    async def test_12_gst_capitalized_to_cost_included_in_cost(self):
        # 100 kg @ ₹110 = ₹11,000 base
        # Freight = ₹500, Other = ₹0
        # GST Amount = ₹550 (e.g. Ineligible / Composition supplier)
        # Treatment = CAPITALIZED_TO_COST
        # Total Landed Cost must INCLUDE GST = ₹11,500 + ₹550 = ₹12,050
        # Rate per unit = ₹12,050 / 100 = ₹120.50
        req = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=100.0,
            unit="kg",
            purchase_rate=110.0,
            receipt_date="2026-10-28",
            supplier_name="Nimar Krishi Mandi",
            invoice_reference="INV-GST-CAP-01",
            line_number=1,
            freight_amount=500.0,
            other_expenses=0.0,
            gst_amount=550.0,
            gst_treatment="CAPITALIZED_TO_COST",
        )
        res = await receive_raw_material(req, self.owner_user)
        self.assertEqual(res.gst_amount, 550.0)
        self.assertEqual(res.gst_treatment, "CAPITALIZED_TO_COST")
        self.assertEqual(res.total_landed_cost, 12050.0)
        self.assertEqual(res.landed_rate_per_unit, 120.50)

        ledger = db.get_records("RawMaterialLedger")
        self.assertEqual(float(ledger[0]["rate_per_unit"]), 120.50)

    # SCENARIO 13: Opening baseline and stock of Moong Dal Flour remains unmutated
    async def test_13_existing_flour_stock_unmutated(self):
        # Baseline flour stock was 500.0 kg
        initial_flour = self._get_available_stock("RM-MOONG-FLOUR")
        self.assertEqual(initial_flour, 500.0)

        # Receive 500 kg of whole moong dal
        req = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=500.0,
            unit="kg",
            purchase_rate=112.0,
            supplier_name="Nimar Krishi Mandi",
            invoice_reference="INV-NO-CORRUPT-01",
        )
        await receive_raw_material(req, self.owner_user)

        # Check whole dal stock is 500.0 kg
        whole_stock = self._get_available_stock("RM-WHOLE-MOONG-DAL")
        self.assertEqual(whole_stock, 500.0)

        # Check flour stock is strictly unchanged at 500.0 kg
        flour_stock = self._get_available_stock("RM-MOONG-FLOUR")
        self.assertEqual(flour_stock, 500.0)

        # RawMaterials master sheet current_stock is also unmutated
        rm_row = next((r for r in db.get_records("RawMaterials") if r.get("raw_material_id") == "RM-MOONG-FLOUR"), None)
        self.assertIsNotNone(rm_row)
        self.assertEqual(float(rm_row["current_stock"]), 500.0)

    # SCENARIO 14: Unit conversion support (quintals -> kg)
    async def test_14_unit_conversion_quintal(self):
        # 2 quintals = 200 kg
        # Purchase rate = ₹11,000 per quintal = ₹110/kg
        req = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=2.0,
            unit="quintal",
            purchase_rate=11000.0,
            supplier_name="Nimar Mandi",
            invoice_reference="INV-QUINTAL-01",
        )
        res = await receive_raw_material(req, self.owner_user)
        self.assertEqual(res.quantity, 200.0)
        self.assertEqual(res.unit, "kg")
        self.assertEqual(res.landed_rate_per_unit, 110.0)
        self.assertEqual(self._get_available_stock("RM-WHOLE-MOONG-DAL"), 200.0)

    # SCENARIO 15: Existing papad production workflows continue working normally
    async def test_15_existing_papad_production_workflow_unaffected(self):
        # Create a papad production batch
        prod_req = ProductionCreate(
            product_id="PRD-MOONG-MASTER",
            production_date="2026-10-28",
            quantity_kg=120.0,
            wastage_kg=2.0,
            flour_base_used_kg=100.0,
            recipe_id="RCP-MM-01",
            notes="Stage 1 compatibility test",
        )
        batch = await create_batch(prod_req, self.pa_user)
        self.assertIsNotNone(batch)
        self.assertEqual(batch.get("status"), "PENDING")

        # Approve batch
        app_req = ApprovalRequest(approved=True, notes="Approved for test")
        res = await approve_batch(batch.get("production_id"), app_req, self.owner_user)
        self.assertEqual(res.get("status"), "APPROVED")

        # Moong Dal Flour consumed per recipe (118 kg net * 0.8333 = 98.329 kg)
        # Initial 500 kg - 98.329 kg = 401.671 kg
        flour_stock = self._get_available_stock("RM-MOONG-FLOUR")
        self.assertAlmostEqual(flour_stock, 401.67, places=1)


if __name__ == "__main__":
    unittest.main()
