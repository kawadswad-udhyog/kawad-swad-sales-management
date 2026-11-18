"""Phase 4 regression tests for clean master data, recipe approval and yields.

All writes are confined to the isolated in-memory Sheets adapter in this test.
"""
import os
os.environ["SALES_TESTING"] = "1"
os.environ.setdefault("SALES_JWT_SECRET", "phase-four-test-secret-only-000000000000000000000000")

import sys
import asyncio
import unittest
from pathlib import Path

backend_dir = str(Path(__file__).resolve().parents[1])
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from fastapi import HTTPException
from app.sheets import db, ID_PREFIXES, REQUIRED_TABS
from app.routers import production as prod
from app.calculations.production import reconcile_production_output
from app.calculations.costing import get_latest_purchase_rate


class PhaseFourCleanDataContracts(unittest.TestCase):
    def setUp(self):
        self.old_connected = db.is_connected
        self.old_fallback = db.allow_in_memory_fallback
        self.old_spreadsheet = db.spreadsheet
        db.is_connected = False
        db.allow_in_memory_fallback = True
        db.spreadsheet = None
        db._records_cache.clear()
        db._worksheets.clear()
        db._fail_once.clear()
        db.memory_store = {name: [] for name in set(ID_PREFIXES) | set(REQUIRED_TABS) | {"Settings"}}
        self.owner = {"user_id": "USR-P4-OWNER", "role": "OWNER", "full_name": "Test Owner"}
        self.pa = {"user_id": "USR-P4-PA", "role": "PA", "full_name": "Test PA"}
        self.sales = {"user_id": "USR-P4-SALES", "role": "SALESMAN"}
        db.memory_store["Products"] = [{
            "product_id": "PRD-P4-001", "sku": "KS-P4-001", "product_name": "Test Papad",
            "category": "PAPAD", "variant": "TEST", "pack_weight_g": 200,
            "selling_unit": "PACKET", "active": "true",
        }]

    def tearDown(self):
        db.is_connected = self.old_connected
        db.allow_in_memory_fallback = self.old_fallback
        db.spreadsheet = self.old_spreadsheet
        db._records_cache.clear()
        db._worksheets.clear()
        db._fail_once.clear()

    def test_empty_raw_material_get_is_empty(self):
        self.assertEqual(asyncio.run(prod.list_raw_materials(self.pa)), [])
        self.assertEqual(db.memory_store["RawMaterials"], [])

    def test_bulk_recipe_bootstrap_is_disabled(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(prod.bootstrap_master_recipes(self.owner))
        self.assertEqual(ctx.exception.status_code, 410)
        self.assertEqual(db.memory_store["RawMaterials"], [])
        self.assertEqual(db.memory_store["Recipes"], [])

    def test_recipe_master_get_does_not_inject_templates(self):
        self.assertEqual(asyncio.run(prod.get_master_recipes(self.pa)), [])
        self.assertEqual(db.memory_store["Recipes"], [])

    def test_receipt_cannot_create_unknown_raw_material(self):
        req = prod.RawMaterialReceiveRequest(
            raw_material_id="RM-UNKNOWN", quantity=5, unit="kg", purchase_rate=100,
            invoice_number="INV-P4-UNKNOWN-01",
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(prod.receive_raw_material(req, self.pa))
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(db.memory_store["RawMaterials"], [])
        self.assertEqual(db.memory_store["RawMaterialLedger"], [])

    def test_opening_stock_verification_cannot_use_seed_catalogue(self):
        req = prod.RawMaterialOpeningVerificationRequest(
            raw_material_id="RM-UNKNOWN", physical_count=10,
            confirm_physical_count=True, reason="Test physical count",
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(prod.verify_raw_material_opening_stock(req, self.owner))
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(db.memory_store["RawMaterials"], [])
        self.assertEqual(db.memory_store["RawMaterialLedger"], [])

    def test_only_owner_can_create_raw_material_master(self):
        req = prod.RawMaterialMasterCreate(
            material_name="Moong Flour", unit="kg", category="FLOUR", rate_status="PENDING"
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(prod.create_raw_material_master(req, self.pa))
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(db.memory_store["RawMaterials"], [])

    def test_owner_create_master_starts_with_zero_stock(self):
        req = prod.RawMaterialMasterCreate(
            material_name="  Moong   Flour ", unit="kg", category="flour", rate_status="PENDING"
        )
        created = asyncio.run(prod.create_raw_material_master(req, self.owner))
        self.assertEqual(created["material_name"], "Moong Flour")
        self.assertEqual(created["current_stock"], 0)
        self.assertEqual(created["rate_status"], "PENDING")
        self.assertEqual(len(db.memory_store["RawMaterials"]), 1)

    def test_duplicate_master_is_rejected_before_second_id_claim(self):
        req = prod.RawMaterialMasterCreate(material_name="Moong Flour", unit="kg")
        asyncio.run(prod.create_raw_material_master(req, self.owner))
        allocation_count = len(db.memory_store["IdAllocations"])
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(prod.create_raw_material_master(
                prod.RawMaterialMasterCreate(material_name=" moong flour ", unit="kg"), self.owner
            ))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(len(db.memory_store["IdAllocations"]), allocation_count)
        self.assertEqual(len(db.memory_store["RawMaterials"]), 1)

    def test_confirmed_rate_requires_positive_value(self):
        request = prod.RawMaterialMasterCreate(
            material_name="Chilli Paste", unit="kg", rate_status="CONFIRMED"
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(prod.create_raw_material_master(request, self.owner))
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(db.memory_store["RawMaterials"], [])

    def test_unknown_product_blocks_batch_before_allocation(self):
        allocation_count = len(db.memory_store["IdAllocations"])
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(prod.create_batch(
                prod.ProductionCreate(product_id="PRD-NOT-FOUND", quantity_kg=10), self.pa
            ))
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(db.memory_store["ProductionBatches"], [])
        self.assertEqual(len(db.memory_store["IdAllocations"]), allocation_count)

    def test_product_without_persisted_approved_recipe_cannot_be_scheduled(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(prod.create_batch(
                prod.ProductionCreate(product_id="PRD-P4-001", quantity_kg=10), self.pa
            ))
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(db.memory_store["ProductionBatches"], [])

    def test_batch_cannot_use_inline_ingredients(self):
        req = prod.ProductionCreate(
            product_id="PRD-P4-001", quantity_kg=10,
            ingredients=[{"material_name": "Flour", "quantity_per_kg": 0.8, "unit": "kg"}],
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(prod.create_batch(req, self.pa))
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(db.memory_store["ProductionBatches"], [])

    def test_no_default_batch_quantity(self):
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(prod.create_batch(prod.ProductionCreate(product_id="PRD-P4-001"), self.pa))
        self.assertEqual(ctx.exception.status_code, 422)

    def test_milling_requires_actual_source_and_flour_master_records(self):
        request = prod.DalMillingCreate(
            source_material_id="RM-WHOLE-MOONG-DAL",
            input_quantity_kg=10,
            flour_output_kg=9,
            milling_expenses=0,
            idempotency_key="P4-MILL-NO-MASTERS",
        )
        allocation_count = len(db.memory_store["IdAllocations"])
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(prod.record_dal_milling_batch(request, self.pa))
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(db.memory_store["RawMaterialLedger"], [])
        self.assertEqual(len(db.memory_store["IdAllocations"]), allocation_count)

    def test_production_consumption_movement_cannot_be_used_as_purchase_rate(self):
        master = [{
            "raw_material_id": "RM-TEST-01",
            "material_name": "Test Flour",
            "unit": "kg",
            "rate_per_unit": "",
            "rate_status": "PENDING",
        }]
        movements = [{
            "raw_material_id": "RM-TEST-01",
            "material_name": "Test Flour",
            "movement_type": "PRODUCTION_CONSUMPTION",
            "rate_per_unit": 200,
            "quantity": 1,
        }]
        result = get_latest_purchase_rate("RM-TEST-01", master, movements)
        self.assertNotEqual(result.get("status"), "CONFIRMED")
        self.assertIsNone(result.get("rate_per_canonical_unit"))

    def test_process_loss_is_part_of_mass_reconciliation(self):
        result = reconcile_production_output(
            saleable_output_kg=7,
            gross_output_kg=10,
            rejected_output_kg=1,
            process_loss_kg=2,
            flour_base_used_kg=8,
            benchmark_yield_ratio=None,
        )
        self.assertEqual(result["saleable_output_kg"], 7.0)
        self.assertEqual(result["rejected_output_kg"], 1.0)
        self.assertEqual(result["process_loss_kg"], 2.0)
        self.assertEqual(result["unexplained_variance_kg"], 0.0)

    def test_process_loss_cannot_exceed_gross_output_balance(self):
        with self.assertRaises(ValueError):
            reconcile_production_output(
                saleable_output_kg=9,
                gross_output_kg=10,
                rejected_output_kg=1,
                process_loss_kg=1,
            )


if __name__ == "__main__":
    unittest.main()
