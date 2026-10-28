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


class TestStage1ComprehensiveVerification(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Guarantee clean isolated test state in db.memory_store
        for tab in REQUIRED_TABS:
            db.memory_store[tab] = []

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

    # TEST 1: Fresh Receipt
    async def test_1_fresh_receipt_execution(self):
        stock_before = self._get_available_stock("RM-WHOLE-MOONG-DAL")
        self.assertEqual(stock_before, 0.0, "Stock before receipt must be 0.0 kg")

        req = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=100.0,
            unit="kg",
            purchase_rate=110.0,
            receipt_date="2026-10-28",
            supplier_name="Nimar Krishi Mandi, Barwani",
            invoice_reference="INV-TEST-001",
            line_number=1,
            freight_amount=500.0,
            other_expenses=200.0,
            gst_amount=0.0,
            gst_treatment="EXEMPT_NIL_RATED",
            notes="Fresh receipt verification",
        )
        res = await receive_raw_material(req, self.owner_user)

        # 1. Verify transaction ID
        self.assertTrue(res.transaction_id.startswith("RML-"), f"Transaction ID should start with RML-, got {res.transaction_id}")
        self.assertEqual(res.status, "SUCCESS")
        self.assertFalse(res.is_replay)

        # 2. Verify returned fields
        self.assertEqual(res.quantity, 100.0)
        self.assertEqual(res.unit, "kg")
        self.assertEqual(res.material_name, "Whole Moong Dal")
        # (100 * 110 + 500 + 200) / 100 = 117.0
        self.assertEqual(res.landed_rate_per_unit, 117.0)
        self.assertEqual(res.new_available_stock, 100.0)

        # 3. Verify exactly one ledger row
        ledger = db.get_records("RawMaterialLedger")
        self.assertEqual(len(ledger), 1, "Exactly one ledger row must be created")
        row = ledger[0]
        self.assertEqual(row["movement_type"], "PURCHASE_RECEIPT")
        self.assertEqual(row["raw_material_txn_id"], res.transaction_id)
        self.assertEqual(float(row["quantity"]), 100.0)
        self.assertEqual(float(row["rate_per_unit"]), 117.0)

        # 4. Verify baseline stock in RawMaterials master is unincremented
        rm_master = db.get_records("RawMaterials")
        moong_raw = next(r for r in rm_master if r["raw_material_id"] == "RM-WHOLE-MOONG-DAL")
        self.assertEqual(float(moong_raw["current_stock"]), 0.0, "Baseline opening stock must not be incremented")

        # 5. Check calculated stock after
        stock_after = self._get_available_stock("RM-WHOLE-MOONG-DAL")
        self.assertEqual(stock_after, 100.0)
        print(f"[TEST 1 PASS] Stock Before: {stock_before} kg -> Stock After: {stock_after} kg | TxID: {res.transaction_id} | Landed Rate: Rs {res.landed_rate_per_unit}/kg")

    # TEST 2: Duplicate Submission (Idempotent Replay)
    async def test_2_duplicate_submission_replay(self):
        req = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=100.0,
            unit="kg",
            purchase_rate=110.0,
            receipt_date="2026-10-28",
            supplier_name="Nimar Krishi Mandi, Barwani",
            invoice_reference="INV-TEST-REPLAY",
            line_number=1,
            freight_amount=500.0,
            other_expenses=200.0,
            gst_amount=0.0,
            gst_treatment="EXEMPT_NIL_RATED",
            notes="Replay test initial receipt",
        )
        res1 = await receive_raw_material(req, self.owner_user)
        self.assertFalse(res1.is_replay)
        self.assertEqual(res1.status, "SUCCESS")
        tx1 = res1.transaction_id
        ledger_count_1 = len(db.get_records("RawMaterialLedger"))
        self.assertEqual(ledger_count_1, 1)

        # Duplicate submit with identical payload
        res2 = await receive_raw_material(req, self.owner_user)
        self.assertTrue(res2.is_replay, "Second submit must be flagged as is_replay=True")
        self.assertEqual(res2.status, "ALREADY_RECORDED")
        self.assertEqual(res2.transaction_id, tx1, "Transaction ID must remain consistent with original receipt")
        self.assertEqual(res2.new_available_stock, 100.0, "Stock balance must not change on replay")

        # Confirm no second ledger row created
        ledger_count_2 = len(db.get_records("RawMaterialLedger"))
        self.assertEqual(ledger_count_2, 1, "Ledger count must remain strictly 1 row")
        print(f"[TEST 2 PASS] Idempotent Replay Verified: TxID {tx1} replayed with status ALREADY_RECORDED. Ledger count: {ledger_count_2}.")

    # TEST 3: Conflicting Duplicate
    async def test_3_conflicting_duplicate(self):
        req_orig = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=100.0,
            unit="kg",
            purchase_rate=110.0,
            receipt_date="2026-10-28",
            supplier_name="Nimar Krishi Mandi, Barwani",
            invoice_reference="INV-CONFLICT-TEST",
            line_number=1,
        )
        res_orig = await receive_raw_material(req_orig, self.owner_user)
        self.assertEqual(res_orig.status, "SUCCESS")

        # Reuse same invoice reference & line number, but change quantity to 150 kg
        req_conflict = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=150.0,  # Changed quantity
            unit="kg",
            purchase_rate=110.0,
            receipt_date="2026-10-28",
            supplier_name="Nimar Krishi Mandi, Barwani",
            invoice_reference="INV-CONFLICT-TEST",
            line_number=1,
        )
        with self.assertRaises(HTTPException) as ctx:
            await receive_raw_material(req_conflict, self.owner_user)

        self.assertEqual(ctx.exception.status_code, 409, "Conflicting duplicate must return HTTP 409")
        self.assertIn("conflict", ctx.exception.detail.lower())

        # Verify ledger has only 1 row and stock is unchanged
        ledger = db.get_records("RawMaterialLedger")
        self.assertEqual(len(ledger), 1)
        self.assertEqual(self._get_available_stock("RM-WHOLE-MOONG-DAL"), 100.0)
        print(f"[TEST 3 PASS] Conflicting Duplicate rejected with HTTP 409: '{ctx.exception.detail}'. Stock balance remains 100.0 kg.")

    # TEST 4: Input Validation
    async def test_4_input_validation(self):
        ledger_initial_count = len(db.get_records("RawMaterialLedger"))

        # 4a: Empty material
        req_no_mat = RawMaterialReceiveRequest(
            material_id="",
            quantity=100.0,
            unit="kg",
            purchase_rate=100.0,
            supplier_name="Supplier A",
            invoice_reference="INV-VAL-01",
        )
        with self.assertRaises(HTTPException) as ctx_a:
            await receive_raw_material(req_no_mat, self.owner_user)
        self.assertEqual(ctx_a.exception.status_code, 422)

        # 4b: Quantity zero
        try:
            req_zero_qty = RawMaterialReceiveRequest(
                material_id="RM-WHOLE-MOONG-DAL",
                quantity=0.0,
                unit="kg",
                purchase_rate=100.0,
                supplier_name="Supplier A",
                invoice_reference="INV-VAL-02",
            )
            with self.assertRaises(HTTPException) as ctx_b:
                await receive_raw_material(req_zero_qty, self.owner_user)
            self.assertEqual(ctx_b.exception.status_code, 422)
        except ValueError as pydantic_err:
            # Pydantic validation Field(gt=0) rejected at schema parse time
            self.assertIn("greater than 0", str(pydantic_err))

        # 4c: Quantity negative
        try:
            req_neg_qty = RawMaterialReceiveRequest(
                material_id="RM-WHOLE-MOONG-DAL",
                quantity=-50.0,
                unit="kg",
                purchase_rate=100.0,
                supplier_name="Supplier A",
                invoice_reference="INV-VAL-03",
            )
            with self.assertRaises(HTTPException) as ctx_c:
                await receive_raw_material(req_neg_qty, self.owner_user)
            self.assertEqual(ctx_c.exception.status_code, 422)
        except ValueError as pydantic_err:
            self.assertIn("greater than 0", str(pydantic_err))

        # 4d: Purchase rate zero
        try:
            req_zero_rate = RawMaterialReceiveRequest(
                material_id="RM-WHOLE-MOONG-DAL",
                quantity=100.0,
                unit="kg",
                purchase_rate=0.0,
                supplier_name="Supplier A",
                invoice_reference="INV-VAL-04",
            )
            with self.assertRaises(HTTPException) as ctx_d:
                await receive_raw_material(req_zero_rate, self.owner_user)
            self.assertEqual(ctx_d.exception.status_code, 422)
        except ValueError as pydantic_err:
            self.assertIn("greater than 0", str(pydantic_err))

        # 4e: Purchase rate negative
        try:
            req_neg_rate = RawMaterialReceiveRequest(
                material_id="RM-WHOLE-MOONG-DAL",
                quantity=100.0,
                unit="kg",
                purchase_rate=-20.0,
                supplier_name="Supplier A",
                invoice_reference="INV-VAL-05",
            )
            with self.assertRaises(HTTPException) as ctx_e:
                await receive_raw_material(req_neg_rate, self.owner_user)
            self.assertEqual(ctx_e.exception.status_code, 422)
        except ValueError as pydantic_err:
            self.assertIn("greater than 0", str(pydantic_err))

        # 4f: Empty invoice reference
        req_empty_inv = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=100.0,
            unit="kg",
            purchase_rate=100.0,
            supplier_name="Supplier A",
            invoice_reference="",
        )
        with self.assertRaises(HTTPException) as ctx_f:
            await receive_raw_material(req_empty_inv, self.owner_user)
        self.assertEqual(ctx_f.exception.status_code, 422)
        self.assertIn("invoice", ctx_f.exception.detail.lower())

        # Verify no movements were created for any invalid input
        ledger_final_count = len(db.get_records("RawMaterialLedger"))
        self.assertEqual(ledger_final_count, ledger_initial_count)
        print("[TEST 4 PASS] All input validation edge cases rejected before ledger append; ledger remained intact.")

    # TEST 5: Landed Cost Calculation (Recoverable vs Capitalized GST)
    async def test_5_landed_cost_calculation(self):
        # Case A: Recoverable ITC (RECOVERABLE_ITC)
        # Base: 100 kg @ Rs 110 = Rs 11,000
        # Freight: Rs 500
        # Other: Rs 200
        # GST: Rs 550 (ITC) -> Excluded from inventory cost
        # Total landed cost: Rs 11,700
        # Rate per unit: Rs 117.00
        req_itc = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=100.0,
            unit="kg",
            purchase_rate=110.0,
            receipt_date="2026-10-28",
            supplier_name="Nimar Krishi Mandi",
            invoice_reference="INV-ITC-001",
            line_number=1,
            freight_amount=500.0,
            other_expenses=200.0,
            gst_amount=550.0,
            gst_treatment="RECOVERABLE_ITC",
        )
        res_itc = await receive_raw_material(req_itc, self.owner_user)
        self.assertEqual(res_itc.base_value, 11000.0)
        self.assertEqual(res_itc.total_landed_cost, 11700.0)
        self.assertEqual(res_itc.landed_rate_per_unit, 117.0)

        # Case B: Capitalized GST (CAPITALIZED_TO_COST)
        # Base: 100 kg @ Rs 110 = Rs 11,000
        # Freight: Rs 500
        # Other: Rs 200
        # GST: Rs 550 (Capitalized) -> Included in inventory cost
        # Total landed cost: Rs 11,700 + Rs 550 = Rs 12,250
        # Rate per unit: Rs 12,250 / 100 = Rs 122.50
        req_cap = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=100.0,
            unit="kg",
            purchase_rate=110.0,
            receipt_date="2026-10-28",
            supplier_name="Nimar Krishi Mandi",
            invoice_reference="INV-CAP-001",
            line_number=1,
            freight_amount=500.0,
            other_expenses=200.0,
            gst_amount=550.0,
            gst_treatment="CAPITALIZED_TO_COST",
        )
        res_cap = await receive_raw_material(req_cap, self.owner_user)
        self.assertEqual(res_cap.base_value, 11000.0)
        self.assertEqual(res_cap.total_landed_cost, 12250.0)
        self.assertEqual(res_cap.landed_rate_per_unit, 122.50)

        print(f"[TEST 5 PASS] Recoverable ITC: Rs {res_itc.landed_rate_per_unit}/kg (tax excluded) | Capitalized GST: Rs {res_cap.landed_rate_per_unit}/kg (tax included).")

    # TEST 6: Existing Workflow Regression
    async def test_6_existing_workflow_regression(self):
        # 1. Existing flour records baseline
        moong_flour = self._get_available_stock("RM-MOONG-FLOUR")
        urad_flour = self._get_available_stock("RM-URAD-FLOUR")
        chana_flour = self._get_available_stock("RM-CHANA-FLOUR")
        self.assertEqual(moong_flour, 500.0)
        self.assertEqual(urad_flour, 300.0)
        self.assertEqual(chana_flour, 200.0)

        # 2. Receive whole moong dal
        req_dal = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=200.0,
            unit="kg",
            purchase_rate=110.0,
            supplier_name="Mandi Traders",
            invoice_reference="INV-REG-DAL-01",
        )
        await receive_raw_material(req_dal, self.owner_user)

        # 3. Flours remain completely unmutated
        self.assertEqual(self._get_available_stock("RM-MOONG-FLOUR"), 500.0)
        self.assertEqual(self._get_available_stock("RM-URAD-FLOUR"), 300.0)
        self.assertEqual(self._get_available_stock("RM-CHANA-FLOUR"), 200.0)

        # 4. Production batch creation & approval uses Moong Dal Flour, NOT whole dal
        prod_req = ProductionCreate(
            product_id="PRD-MOONG-MASTER",
            production_date="2026-10-28",
            quantity_kg=120.0,
            wastage_kg=2.0,
            flour_base_used_kg=100.0,
            recipe_id="RCP-MM-01",
            notes="Daily production test",
        )
        batch = await create_batch(prod_req, self.pa_user)
        self.assertEqual(batch.get("status"), "PENDING")

        app_req = ApprovalRequest(approved=True, notes="Approved")
        app_res = await approve_batch(batch.get("production_id"), app_req, self.owner_user)
        self.assertEqual(app_res.get("status"), "APPROVED")

        # Whole dal stock remains exactly 200.0 kg!
        self.assertEqual(self._get_available_stock("RM-WHOLE-MOONG-DAL"), 200.0)

        # Moong Dal Flour consumed per recipe formula (118 kg net * 0.8333 = 98.329 kg)
        self.assertAlmostEqual(self._get_available_stock("RM-MOONG-FLOUR"), 401.67, places=1)

        # 5. Verify category separation in raw-material balances
        balances = await get_raw_material_balances(self.owner_user)
        whole_item = next(b for b in balances if b.raw_material_id == "RM-WHOLE-MOONG-DAL")
        flour_item = next(b for b in balances if b.raw_material_id == "RM-MOONG-FLOUR")
        self.assertEqual(whole_item.category, "WHOLE_GRAIN")
        self.assertEqual(flour_item.category, "FLOUR")
        print(f"[TEST 6 PASS] Existing flour stock, production batch, and recipe deductions isolated; Whole Dal stock intact at {whole_item.available_stock} kg.")

    # TEST 7: Failure Recovery
    async def test_7_failure_recovery_simulation(self):
        # Scenario: Server commits receipt to RawMaterialLedger, but a network interruption occurs
        # before the client receives the HTTP response.
        req = RawMaterialReceiveRequest(
            material_id="RM-WHOLE-MOONG-DAL",
            quantity=350.0,
            unit="kg",
            purchase_rate=109.0,
            receipt_date="2026-10-28",
            supplier_name="Barwani Farmers Producer Co",
            invoice_reference="INV-CRASH-RETRY-01",
            line_number=1,
            freight_amount=700.0,
            other_expenses=150.0,
            gst_treatment="RECOVERABLE_ITC",
            notes="Interrupted request recovery test",
        )
        res1 = await receive_raw_material(req, self.owner_user)
        self.assertEqual(res1.status, "SUCCESS")
        tx_id = res1.transaction_id
        stock_after_first = self._get_available_stock("RM-WHOLE-MOONG-DAL")
        self.assertEqual(stock_after_first, 350.0)

        # Client retries identical request after timeout/failure
        res_retry = await receive_raw_material(req, self.owner_user)
        self.assertEqual(res_retry.status, "ALREADY_RECORDED")
        self.assertTrue(res_retry.is_replay)
        self.assertEqual(res_retry.transaction_id, tx_id)
        self.assertEqual(res_retry.new_available_stock, 350.0)

        # Ledger row count is strictly 1
        matching_ledger = [r for r in db.get_records("RawMaterialLedger") if r.get("issue_txn_id") == "INV:INV-CRASH-RETRY-01:L:1"]
        self.assertEqual(len(matching_ledger), 1, "There must be exactly 1 ledger row after retry")
        print(f"[TEST 7 PASS] Interrupted request safely recovered: TxID {tx_id} returned, stock preserved at 350.0 kg without duplication.")


if __name__ == "__main__":
    unittest.main()
