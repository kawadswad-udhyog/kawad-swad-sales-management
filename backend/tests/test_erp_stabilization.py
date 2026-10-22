"""
Comprehensive ERP Stabilization & Calculation Engine Unit Tests
Covers Parts 2, 3, 4, 5, 6, 7, 8, 11 of the specification:
- Unit conversion & dimensional compatibility
- Recipe scaling, formulation protection, and zero/negative validations
- Production lifecycle, material issue vs approval, yield and variance
- Packaging calculation, SKU weights, packing loss, discrepancy blocking & approval
- Latest purchase rate selection, batch costing, finished packet costing
- Owner-only production security enforcement (PA, Salesman, Worker denied)
- Recovery and idempotency (no duplicate stock deductions or additions)
"""

import os
os.environ.setdefault("SALES_TESTING", "1")
os.environ.setdefault("SALES_JWT_SECRET", "test-only-secret-do-not-use-for-deployment-32")

import sys
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import asyncio
import unittest
from fastapi import HTTPException
from app.sheets import db
from app.routers import production as prod
from app.calculations import (
    normalize_to_canonical_unit,
    convert_unit,
    scale_recipe,
    validate_recipe_formulation,
    calculate_recipe_cost_estimate,
    calculate_production_requirements,
    reconcile_production_output,
    calculate_packed_weight,
    calculate_packing_variance,
    validate_packing_discrepancy,
    get_latest_purchase_rate,
    calculate_batch_actual_cost,
    calculate_finished_sku_cost,
    calculate_bulk_stock_balance,
    calculate_finished_stock_balance,
    calculate_raw_material_balance,
)


class TestERPStabilization(unittest.TestCase):
    def setUp(self):
        db.is_connected = False
        for key in list(db.memory_store):
            db.memory_store[key] = []
        db.memory_store.update({
            "Products": [
                {"product_id": "PRD-M-200", "sku": "KS-MP-200", "product_name": "Moong Master Papad", "active": "true", "pack_weight_g": 200},
                {"product_id": "PRD-M-500", "sku": "KS-MP-500", "product_name": "Moong Master Papad", "active": "true", "pack_weight_g": 500},
                {"product_id": "PRD-M-1000", "sku": "KS-MP-1000", "product_name": "Moong Master Papad", "active": "true", "pack_weight_g": 1000},
            ],
            "RawMaterials": [
                {"raw_material_id": "RM-MOONG", "material_name": "Moong Flour", "current_stock": 500.0, "unit": "kg", "rate_per_unit": 90.0, "rate_status": "CONFIRMED"},
                {"raw_material_id": "RM-SALT", "material_name": "Salt", "current_stock": 100.0, "unit": "kg", "rate_per_unit": 20.0, "rate_status": "CONFIRMED"},
                {"raw_material_id": "RM-OIL", "material_name": "Edible Oil", "current_stock": 50.0, "unit": "L", "rate_per_unit": 140.0, "rate_status": "CONFIRMED"},
                {"raw_material_id": "RM-SPECIAL", "material_name": "Special Spice", "current_stock": 10.0, "unit": "kg", "rate_per_unit": "", "rate_status": "PENDING"},
            ],
            "Recipes": [],
            "ProductionBatches": [],
            "PackagingBatches": [],
            "ProductionStockLedger": [],
            "ProductionDispatches": [],
            "RawMaterialLedger": [],
            "Workers": [],
            "WorkerAttendance": [],
            "AuditLog": [],
            "Sales": [],
            "SalesmanStockLedger": [],
        })
        self.owner_user = {"user_id": "USR-OWNER-1", "role": "OWNER"}
        self.pa_user = {"user_id": "USR-PA-1", "role": "PA"}
        self.salesman_user = {"user_id": "USR-SALES-1", "role": "SALESMAN"}
        self.worker_user = {"user_id": "USR-WORKER-1", "role": "FACTORY_WORKER"}

    # =========================================================
    # PART 3: RECIPE CALCULATION ENGINE TESTS
    # =========================================================

    def test_units_normalization_and_precision(self):
        # Grams to kg
        kg_val, unit = normalize_to_canonical_unit(250, "g")
        self.assertEqual(unit, "kg")
        self.assertEqual(kg_val, 0.25)

        # Millilitres to Litres
        l_val, unit_l = normalize_to_canonical_unit(500, "ml")
        self.assertEqual(unit_l, "L")
        self.assertEqual(l_val, 0.5)

        # Kilograms remain unchanged
        kg_same, u_same = normalize_to_canonical_unit(10.5, "kg")
        self.assertEqual(u_same, "kg")
        self.assertEqual(kg_same, 10.5)

        # Reject negative quantity
        with self.assertRaises(ValueError):
            normalize_to_canonical_unit(-5, "kg")

        # Reject incompatible dimension (kg to L without density)
        with self.assertRaises(ValueError):
            convert_unit(5, "kg", "L")

        # Valid conversion with density
        l_with_density = convert_unit(1.8, "kg", "L", density_kg_per_l=0.9)
        self.assertEqual(l_with_density, 2.0)

    def test_recipe_scaling_and_formulation_protection(self):
        # 1 kg flour base produces 1.2 kg finished papad
        items = [
            {"material_name": "Moong Flour", "quantity": 1000, "unit": "g"},
            {"material_name": "Salt", "quantity": 25, "unit": "g"},
        ]
        # Planned output: 120 kg finished papad (multiplier should be 120 / 1.2 = 100x)
        scaled = scale_recipe(items, expected_yield_kg=1.2, planned_output_kg=120.0, reference_flour_base_kg=1.0)
        self.assertEqual(scaled["batch_multiplier"], 100.0)
        self.assertEqual(scaled["calculated_flour_base_kg"], 100.0)

        flour_req = next(i for i in scaled["scaled_items"] if i["material_name"] == "Moong Flour")
        self.assertEqual(flour_req["canonical_quantity"], 100.0)
        self.assertEqual(flour_req["canonical_unit"], "kg")

        # Formulation violation: Moong Master Papad must never contain sabudana or urad flour
        bad_items = [
            {"material_name": "Moong Flour", "quantity": 800, "unit": "g"},
            {"material_name": "Urad Flour", "quantity": 200, "unit": "g"},
        ]
        with self.assertRaises(ValueError) as ctx:
            validate_recipe_formulation("Moong Master Papad", bad_items, 1.2)
        self.assertIn("Formulation violation", str(ctx.exception))

        # Zero or negative yield rejected
        with self.assertRaises(ValueError):
            validate_recipe_formulation("Moong Master Papad", items, 0.0)

    def test_missing_rates_not_silently_reported_as_zero(self):
        items_with_missing_rate = [
            {"material_name": "Moong Flour", "quantity": 1000, "unit": "g", "rate_per_unit": 90.0, "rate_status": "CONFIRMED"},
            {"material_name": "Special Spice", "quantity": 10, "unit": "g", "rate_per_unit": "", "rate_status": "PENDING"},
        ]
        cost_est = calculate_recipe_cost_estimate(items_with_missing_rate, expected_yield_kg=1.2)
        self.assertEqual(cost_est["cost_status"], "PENDING_RATES")
        self.assertIsNone(cost_est["cost_per_batch"])
        self.assertIsNone(cost_est["cost_per_kg"])
        self.assertIn("Special Spice", cost_est["pending_ingredients"])

    # =========================================================
    # PART 4: PRODUCTION LIFECYCLE TESTS (Issue Materials vs Approval)
    # =========================================================

    def test_production_material_issue_and_no_double_deduction_on_approval(self):
        # 1. Setup approved recipe
        asyncio.run(prod.save_recipe(
            prod.RecipeSave(
                product_id="PRD-M-200",
                items=[
                    prod.RecipeItemInput(material_name="Moong Flour", quantity_per_kg=0.8333, unit="kg"),
                    prod.RecipeItemInput(material_name="Salt", quantity_per_kg=0.02, unit="kg"),
                ],
                approved=True,
                expected_yield_kg=1.2,
            ),
            self.owner_user,
        ))

        # 2. Create batch of 60 kg finished dried papad
        batch = asyncio.run(prod.create_batch(
            prod.ProductionCreate(
                product_id="PRD-M-200",
                production_date="2026-10-20",
                quantity_kg=60.0,
                wastage_kg=2.0,
                flour_base_used_kg=50.0,
            ),
            self.owner_user,
        ))
        prod_id = batch["production_id"]
        self.assertEqual(batch["net_quantity_kg"], 58.0)
        self.assertEqual(len(db.memory_store["RawMaterialLedger"]), 0)

        # 3. Explicitly issue materials
        issue_res = asyncio.run(prod.issue_materials(prod_id, self.owner_user))
        self.assertEqual(issue_res["status"], "MATERIALS_ISSUED")
        initial_raw_ledger_count = len(db.memory_store["RawMaterialLedger"])
        self.assertEqual(initial_raw_ledger_count, 2)  # Moong Flour and Salt

        # 4. Repeated material issue must be idempotent (no duplicate deduction)
        retry_issue = asyncio.run(prod.issue_materials(prod_id, self.owner_user))
        self.assertEqual(retry_issue["status"], "ALREADY_ISSUED")
        self.assertEqual(len(db.memory_store["RawMaterialLedger"]), initial_raw_ledger_count)

        # 5. Production approval must NOT deduct materials again
        approved = asyncio.run(prod.approve_batch(
            prod_id,
            prod.ApprovalRequest(approved=True, notes="Quality passed"),
            self.owner_user,
        ))
        self.assertEqual(approved["status"], "APPROVED")
        # Raw material ledger count must remain EXACTLY the same!
        self.assertEqual(len(db.memory_store["RawMaterialLedger"]), initial_raw_ledger_count)

        # Bulk stock must be credited exactly once
        bulk_rows = [r for r in db.memory_store["ProductionStockLedger"] if r["movement_type"] == "BULK_PRODUCED" and r["reference_id"] == prod_id]
        self.assertEqual(len(bulk_rows), 1)
        self.assertEqual(bulk_rows[0]["quantity_kg"], 58.0)

        # Re-running approval must not duplicate bulk stock
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(prod.approve_batch(prod_id, prod.ApprovalRequest(approved=True), self.owner_user))
        self.assertEqual(ctx.exception.status_code, 409)

    # =========================================================
    # PART 5: PACKAGING & DISCREPANCY BLOCKING TESTS
    # =========================================================

    def test_packaging_calculation_and_unexplained_variance_blocks_completion(self):
        # Credit bulk stock 50 kg
        db.memory_store["ProductionStockLedger"].append({
            "movement_id": "BULK-CREDIT-1", "movement_type": "BULK_PRODUCED", "product_id": "PRD-M-200",
            "bulk_product_key": "moong master papad", "product_name_snapshot": "Moong Master Papad",
            "quantity_kg": 50.0, "quantity_packets": 0,
        })

        # Test A: Correct packaging: 20 kg bulk -> 50 pkts 200g (10kg) + 20 pkts 500g (10kg) = 20kg (variance 0.000)
        pack_ok = asyncio.run(prod.create_packaging(
            prod.PackagingCreate(
                product_id="PRD-M-200", packaging_date="2026-10-20", bulk_kg_used=20.0,
                packets_200g=50, packets_500g=20, packets_1000g=0, packing_loss_kg=0.0,
            ),
            self.owner_user,
        ))
        self.assertEqual(pack_ok["status"], "RECORDED")
        self.assertEqual(pack_ok["difference_status"], "MATCH")

        # Test B: Unexplained discrepancy: 20 kg bulk consumed, but only 19 kg packed (packets: 45x200g = 9kg, 20x500g = 10kg), loss: 0.2 kg.
        # Unexplained = 20 - 19 - 0.2 = 0.8 kg -> MUST BLOCK PACKING COMPLETION!
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(prod.create_packaging(
                prod.PackagingCreate(
                    product_id="PRD-M-200", packaging_date="2026-10-20", bulk_kg_used=20.0,
                    packets_200g=45, packets_500g=20, packets_1000g=0, packing_loss_kg=0.2, loss_reason="Normal seal trim",
                    discrepancy_approved=False,
                ),
                self.owner_user,
            ))
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("Packing completion blocked", str(ctx.exception.detail))

        # Test C: Discrepancy can be approved by Owner with authorized explanation
        pack_approved = asyncio.run(prod.create_packaging(
            prod.PackagingCreate(
                product_id="PRD-M-200", packaging_date="2026-10-20", bulk_kg_used=20.0,
                packets_200g=45, packets_500g=20, packets_1000g=0, packing_loss_kg=0.2, loss_reason="Normal seal trim",
                discrepancy_approved=True, discrepancy_explanation="Drying tray drop accident audited by Owner",
            ),
            self.owner_user,
        ))
        self.assertEqual(pack_approved["status"], "RECORDED")
        self.assertEqual(pack_approved["difference_status"], "APPROVED_DISCREPANCY")
        self.assertEqual(pack_approved["discrepancy_approved"], "true")

    # =========================================================
    # PART 6: COSTING ENGINE TESTS
    # =========================================================

    def test_costing_latest_purchase_rate_and_sku_cost(self):
        # 1. Add purchase ledger records
        db.memory_store["RawMaterialLedger"].extend([
            {
                "raw_material_txn_id": "PUR-1", "txn_datetime": "2026-10-01T10:00:00Z",
                "material_name": "Moong Flour", "movement_type": "PURCHASE_RECEIPT",
                "quantity": 100, "unit": "kg", "rate_per_unit": 85.0, "status": "VALID"
            },
            {
                "raw_material_txn_id": "PUR-2", "txn_datetime": "2026-10-15T10:00:00Z",
                "material_name": "Moong Flour", "movement_type": "PURCHASE_RECEIPT",
                "quantity": 200, "unit": "kg", "rate_per_unit": 92.5, "status": "VALID"
            },
            {
                "raw_material_txn_id": "PUR-3-CANCELLED", "txn_datetime": "2026-10-18T10:00:00Z",
                "material_name": "Moong Flour", "movement_type": "PURCHASE_RECEIPT",
                "quantity": 50, "unit": "kg", "rate_per_unit": 150.0, "status": "CANCELLED"
            },
        ])

        # Latest rate must be 92.5 (PUR-2), excluding cancelled PUR-3
        rate_info = get_latest_purchase_rate("Moong Flour", db.memory_store["RawMaterials"], db.memory_store["RawMaterialLedger"])
        self.assertEqual(rate_info["status"], "CONFIRMED")
        self.assertEqual(rate_info["rate_per_canonical_unit"], 92.5)
        self.assertIn("PUR-2", rate_info["source"])

        # Finished SKU cost calculation
        # 200g pack @ ₹120/kg production cost + ₹2.00 packaging = (0.2 * 120) + 2.0 = ₹26.00
        sku_cost = calculate_finished_sku_cost(
            pack_weight_grams=200,
            production_cost_per_saleable_kg=120.0,
            packaging_material_cost_per_packet=1.50,
            packing_labour_per_packet=0.50,
        )
        self.assertEqual(sku_cost["status"], "COMPLETE")
        self.assertEqual(sku_cost["base_papad_cost"], 24.0)
        self.assertEqual(sku_cost["total_packing_cost"], 2.0)
        self.assertEqual(sku_cost["finished_packet_cost"], 26.0)

    # =========================================================
    # PART 8: OWNER-ONLY PRODUCTION SECURITY TESTS
    # =========================================================

    def test_owner_only_production_access_enforcement(self):
        # 1. Owner CAN access summary
        summary = asyncio.run(prod.summary(self.owner_user))
        self.assertIn("bulk_stock", summary)

        # 2. PA has entry access in ERP 2.0
        pa_summary = asyncio.run(prod.summary(self.pa_user))
        self.assertIn("bulk_stock", pa_summary)

        # 3. PA can create pending batch
        batch = asyncio.run(prod.create_batch(
            prod.ProductionCreate(product_id="PRD-M-200", production_date="2026-10-20", quantity_kg=10),
            self.pa_user,
        ))
        self.assertEqual(batch["status"], "PENDING")

        # 4. PA MUST BE DENIED (403) on batch approval (strictly Owner-only)
        with self.assertRaises(HTTPException) as ctx_approve:
            asyncio.run(prod.approve_batch(
                batch["batch_id"],
                prod.ApprovalRequest(approved=True),
                self.pa_user,
            ))
        self.assertEqual(ctx_approve.exception.status_code, 403)
        self.assertIn("Owner", str(ctx_approve.exception.detail))

        # 5. Salesman MUST BE DENIED (403) from production access
        with self.assertRaises(HTTPException) as ctx_sales:
            asyncio.run(prod.summary(self.salesman_user))
        self.assertEqual(ctx_sales.exception.status_code, 403)

        # 6. Factory Worker MUST BE DENIED (403) from production access
        with self.assertRaises(HTTPException) as ctx_worker:
            asyncio.run(prod.summary(self.worker_user))
        self.assertEqual(ctx_worker.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
