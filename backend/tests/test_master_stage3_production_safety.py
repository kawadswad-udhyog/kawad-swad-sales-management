"""
Tests for Kawad Swad ERP Master Stage 3 Production Safety, Multi-Batch Costing,
Legacy Cost Resolution, Incomplete Packaging Exclusion, and Accounting Integrity.
"""

import os
import sys
import json
import asyncio
import unittest
from decimal import Decimal
from fastapi import HTTPException

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from app.calculations.inventory import (
    calculate_batch_bulk_balances,
    resolve_packaging_batch_allocations,
    calculate_finished_stock_balance,
    calculate_consolidated_finished_goods_register,
)
from app.accounting.postings import post_packaging_batch_journal
from app.routers.production import (
    recover_packaging,
    resolve_legacy_cost,
    dispatch,
    ResolveLegacyCostRequest,
    DispatchCreate,
)
from app.routers.stock import get_bulk_batch_tracking
from app.sheets import db


class MasterStage3ProductionSafetyTests(unittest.TestCase):
    def setUp(self):
        db.memory_store = {tab: [] for tab in db.memory_store}

        # Seed Users
        self.owner_user = {"user_id": "USR-OWNER-01", "username": "owner", "role": "OWNER"}
        self.prod_user = {"user_id": "USR-PROD-01", "username": "prod_mgr", "role": "PA"}
        db.append_record("Users", {**self.owner_user, "active": "true", "full_name": "Sita Ram"})
        db.append_record("Users", {**self.prod_user, "active": "true", "full_name": "Gopal Sharma"})

        # Seed Products (Bulk + Finished SKUs)
        db.append_record("Products", {
            "product_id": "PRD-MOONG-BULK",
            "sku": "MOONG-BULK",
            "product_name": "Moong Papad",
            "selling_unit": "kg",
            "active": "true",
            "category": "Papad",
        })
        db.append_record("Products", {
            "product_id": "PRD-MOONG-200G",
            "sku": "MOONG-200G",
            "product_name": "Moong Papad",
            "selling_unit": "PACKET",
            "pack_weight_g": 200,
            "active": "true",
            "category": "Papad",
        })
        db.append_record("Products", {
            "product_id": "PRD-MOONG-500G",
            "sku": "MOONG-500G",
            "product_name": "Moong Papad",
            "selling_unit": "PACKET",
            "pack_weight_g": 500,
            "active": "true",
            "category": "Papad",
        })

    def test_legacy_batch_cost_distinguishes_actual_estimated_and_missing(self):
        """Verify calculate_batch_bulk_balances distinguishes ACTUAL, ESTIMATED, and MISSING costs."""
        # Batch 1: Has actual cost per kg
        db.append_record("ProductionBatches", {
            "production_id": "PRB-ACTUAL-01",
            "product_id": "PRD-MOONG-BULK",
            "product_name_snapshot": "Moong Papad",
            "status": "APPROVED",
            "net_quantity_kg": 100.0,
            "actual_cost_per_kg": 142.75,
            "production_date": "2026-11-01",
        })
        db.append_record("ProductionStockLedger", {
            "movement_id": "PSL-001",
            "reference_id": "PRB-ACTUAL-01",
            "movement_type": "BULK_PRODUCED",
            "product_id": "PRD-MOONG-BULK",
            "bulk_product_key": "moong papad",
            "quantity_kg": 100.0,
            "unit_cost_per_kg": 142.75,
        })

        # Batch 2: Legacy batch with recorded estimated cost
        db.append_record("ProductionBatches", {
            "production_id": "PRB-LEGACY-02",
            "product_id": "PRD-MOONG-BULK",
            "product_name_snapshot": "Moong Papad",
            "status": "APPROVED",
            "net_quantity_kg": 80.0,
            "estimated_cost_per_kg": 138.0,
            "cost_status": "ESTIMATED",
            "cost_source": "OWNER_AUDIT_OCT2026",
            "production_date": "2026-10-15",
        })
        db.append_record("ProductionStockLedger", {
            "movement_id": "PSL-002",
            "reference_id": "PRB-LEGACY-02",
            "movement_type": "BULK_PRODUCED",
            "product_id": "PRD-MOONG-BULK",
            "bulk_product_key": "moong papad",
            "quantity_kg": 80.0,
        })
        db.append_record("RawMaterials", {
            "raw_material_id": "RM-MOONG-FLOUR",
            "material_name": "Moong Flour",
            "rate_per_unit": 138.0,
        })

        # Batch 3: Legacy batch of unknown product with NO rate anywhere
        db.append_record("ProductionBatches", {
            "production_id": "PRB-UNKNOWN-03",
            "product_id": "PRD-UNKNOWN-BULK",
            "product_name_snapshot": "Unknown Special Papad",
            "status": "APPROVED",
            "net_quantity_kg": 50.0,
            "actual_cost_per_kg": "",
            "production_date": "2026-09-01",
        })
        db.append_record("ProductionStockLedger", {
            "movement_id": "PSL-003",
            "reference_id": "PRB-UNKNOWN-03",
            "movement_type": "BULK_PRODUCED",
            "product_id": "PRD-UNKNOWN-BULK",
            "bulk_product_key": "unknown special papad",
            "quantity_kg": 50.0,
        })

        ledger = db.get_records("ProductionStockLedger")
        batches = db.get_records("ProductionBatches")
        results = calculate_batch_bulk_balances(ledger, batches)

        res_actual = next(r for r in results if r["batch_id"] == "PRB-ACTUAL-01")
        self.assertEqual(res_actual["cost_status"], "ACTUAL")
        self.assertEqual(res_actual["unit_cost_per_kg"], 142.75)
        self.assertIn("PRODUCTION_BATCH", res_actual["cost_source"])

        res_estimated = next(r for r in results if r["batch_id"] == "PRB-LEGACY-02")
        self.assertEqual(res_estimated["cost_status"], "ESTIMATED")
        self.assertEqual(res_estimated["unit_cost_per_kg"], 138.0)
        self.assertIn("OWNER_AUDIT", res_estimated["cost_source"])

        res_missing = next(r for r in results if r["batch_id"] == "PRB-UNKNOWN-03")
        self.assertEqual(res_missing["cost_status"], "MISSING")
        self.assertEqual(res_missing["unit_cost_per_kg"], 0.0)

    def test_require_actual_cost_blocks_estimated_batch_in_accounting(self):
        """Verify post_packaging_batch_journal rejects estimated costs when require_actual_cost=True."""
        pack_data = {
            "packaging_id": "PKG-TEST-001",
            "product_name_snapshot": "Moong Papad",
            "bulk_kg_used": 50.0,
            "total_packets": 250,
            "has_estimated_cost": True,
            "cost_status": "ESTIMATED",
        }

        # Standard mode posts provisional voucher
        res = post_packaging_batch_journal(
            pack_data,
            bulk_cost=Decimal("7000.00"),
            packing_material_cost=Decimal("375.00"),
            packing_labor_cost=Decimal("125.00"),
            actor="test_user",
            require_actual_cost=False,
        )
        self.assertIsNotNone(res.get("journal_id"))
        self.assertEqual(res.get("voucher_type"), "PROVISIONAL_MANUFACTURING")
        self.assertIn("[PROVISIONAL_ESTIMATED_VALUATION]", res.get("narration", ""))

        # Strict actual cost mode rejects estimated cost
        with self.assertRaises(ValueError) as ctx:
            post_packaging_batch_journal(
                pack_data,
                bulk_cost=Decimal("7000.00"),
                packing_material_cost=Decimal("375.00"),
                packing_labor_cost=Decimal("125.00"),
                actor="test_user",
                require_actual_cost=True,
            )
        self.assertIn("Estimated cost rejected for actual-cost accounting", str(ctx.exception))

    def test_owner_resolve_legacy_cost_endpoint(self):
        """Verify Owner can resolve legacy batch cost and it updates both batch and bulk ledger."""
        db.append_record("ProductionBatches", {
            "production_id": "PRB-LEGACY-99",
            "product_id": "PRD-MOONG-BULK",
            "product_name_snapshot": "Moong Papad",
            "status": "APPROVED",
            "net_quantity_kg": 150.0,
            "actual_cost_per_kg": "",
            "production_date": "2026-10-01",
        })
        db.append_record("ProductionStockLedger", {
            "movement_id": "PSL-LEGACY-99",
            "reference_id": "PRB-LEGACY-99",
            "movement_type": "BULK_PRODUCED",
            "product_id": "PRD-MOONG-BULK",
            "bulk_product_key": "moong papad",
            "quantity_kg": 150.0,
        })

        req = ResolveLegacyCostRequest(
            cost_per_kg=146.50,
            cost_status="ACTUAL",
            source="OWNER_INVOICE_AUDIT_OCT2026",
            notes="Verified against dal procurement bill RM-BILL-104",
        )
        resp = asyncio.run(resolve_legacy_cost("PRB-LEGACY-99", req, user=self.owner_user))

        self.assertEqual(resp["status"], "SUCCESS")
        self.assertEqual(resp["cost_per_kg"], 146.50)
        self.assertEqual(resp["cost_status"], "ACTUAL")

        # Verify batch record updated
        b_rec = next(b for b in db.get_records("ProductionBatches") if b["production_id"] == "PRB-LEGACY-99")
        self.assertEqual(float(b_rec["actual_cost_per_kg"]), 146.50)
        self.assertEqual(b_rec["cost_status"], "ACTUAL")

        # Verify bulk ledger movement updated
        l_rec = next(m for m in db.get_records("ProductionStockLedger") if m["reference_id"] == "PRB-LEGACY-99")
        self.assertEqual(float(l_rec["unit_cost_per_kg"]), 146.50)

    def test_incomplete_packaging_excluded_from_finished_stock_and_dispatch(self):
        """Verify INCOMPLETE packaging batches do NOT produce usable finished stock for dispatch."""
        pkg_id = "PKG-INCOMPLETE-001"
        db.append_record("PackagingBatches", {
            "packaging_id": pkg_id,
            "product_id": "PRD-MOONG-500G",
            "product_name_snapshot": "Moong Papad",
            "bulk_kg_used": 50.0,
            "packets_500g": 100,
            "total_packets": 100,
            "status": "INCOMPLETE",
            "notes": "Interrupted packaging batch",
        })
        db.append_record("ProductionStockLedger", {
            "movement_id": "PSL-INC-001",
            "reference_id": pkg_id,
            "movement_type": "PACKETS_PACKAGED",
            "product_id": "PRD-MOONG-500G",
            "quantity_packets": 100,
            "channel": "FACTORY_FINISHED",
        })

        ledger = db.get_records("ProductionStockLedger")
        packages = db.get_records("PackagingBatches")

        # Finished stock balance MUST exclude incomplete batch
        bal = calculate_finished_stock_balance(ledger, "PRD-MOONG-500G", packaging_batches=packages)
        self.assertEqual(bal.get("PRD-MOONG-500G", 0), 0)

        # Dispatch endpoint MUST reject dispatch when only incomplete stock exists
        req = DispatchCreate(
            product_id="PRD-MOONG-500G",
            quantity_packets=20,
            channel="WAREHOUSE",
            destination="Central Warehouse",
            reference="DISP-FAIL-001",
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(dispatch(req, user=self.prod_user))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("Insufficient factory finished stock", ctx.exception.detail)

    def test_multi_batch_packaging_recovery_and_idempotency(self):
        """Verify recover_packaging idempotently handles multi-batch allocations and vouchers."""
        pkg_id = "PKG-MULTI-REC-01"
        allocations = [
            {"batch_id": "PRB-001", "quantity_kg": 60.0, "unit_cost_per_kg": 140.0, "total_cost": 8400.0},
            {"batch_id": "PRB-002", "quantity_kg": 40.0, "unit_cost_per_kg": 150.0, "total_cost": 6000.0},
        ]
        db.append_record("PackagingBatches", {
            "packaging_id": pkg_id,
            "product_id": "PRD-MOONG-BULK",
            "product_name_snapshot": "Moong Papad",
            "bulk_kg_used": 100.0,
            "packets_500g": 200,
            "total_packets": 200,
            "bulk_cost": 14400.0,
            "packaging_material_cost": 300.0,
            "packaging_labor_cost": 100.0,
            "total_finished_cost": 14800.0,
            "status": "INCOMPLETE",
            "batch_allocations_json": json.dumps(allocations),
        })

        # Call recover endpoint
        rec_resp = asyncio.run(recover_packaging(pkg_id, user=self.prod_user))
        self.assertEqual(rec_resp["status"], "RECORDED")

        # Check that 2 BULK_PACKAGED rows were created (one for PRB-001 and one for PRB-002)
        ledger_after = db.get_records("ProductionStockLedger")
        bulk_rows = [m for m in ledger_after if m.get("reference_id") == pkg_id and m.get("movement_type") == "BULK_PACKAGED"]
        self.assertEqual(len(bulk_rows), 2)
        batches_in_bulk = {r.get("production_batch_id") for r in bulk_rows}
        self.assertEqual(batches_in_bulk, {"PRB-001", "PRB-002"})

        # Check packet movement created
        pkt_rows = [m for m in ledger_after if m.get("reference_id") == pkg_id and m.get("movement_type") == "PACKETS_PACKAGED"]
        self.assertEqual(len(pkt_rows), 1)
        self.assertEqual(int(pkt_rows[0]["quantity_packets"]), 200)

        # Check status is now RECORDED
        batch_after = next(b for b in db.get_records("PackagingBatches") if b["packaging_id"] == pkg_id)
        self.assertEqual(batch_after["status"], "RECORDED")

        # Re-running recovery should be completely idempotent (no duplicate rows)
        rec_resp2 = asyncio.run(recover_packaging(pkg_id, user=self.prod_user))
        self.assertEqual(rec_resp2["status"], "RECORDED")

        ledger_after2 = db.get_records("ProductionStockLedger")
        bulk_rows2 = [m for m in ledger_after2 if m.get("reference_id") == pkg_id and m.get("movement_type") == "BULK_PACKAGED"]
        self.assertEqual(len(bulk_rows2), 2)

    def test_stock_bulk_batches_endpoint(self):
        """Verify get_bulk_batch_tracking returns correct batch tracking breakdown."""
        db.append_record("ProductionBatches", {
            "production_id": "PRB-TRACK-01",
            "product_id": "PRD-MOONG-BULK",
            "product_name_snapshot": "Moong Papad",
            "status": "APPROVED",
            "net_quantity_kg": 200.0,
            "actual_cost_per_kg": 144.20,
            "production_date": "2026-11-02",
        })
        db.append_record("ProductionStockLedger", {
            "movement_id": "PSL-TRK-01",
            "reference_id": "PRB-TRACK-01",
            "movement_type": "BULK_PRODUCED",
            "product_id": "PRD-MOONG-BULK",
            "bulk_product_key": "moong papad",
            "quantity_kg": 200.0,
            "unit_cost_per_kg": 144.20,
        })
        # Deduct 50 kg from this batch
        db.append_record("ProductionStockLedger", {
            "movement_id": "PSL-TRK-02",
            "reference_id": "PKG-001",
            "production_batch_id": "PRB-TRACK-01",
            "movement_type": "BULK_PACKAGED",
            "product_id": "PRD-MOONG-BULK",
            "bulk_product_key": "moong papad",
            "quantity_kg": 50.0,
            "unit_cost_per_kg": 144.20,
        })

        data = asyncio.run(get_bulk_batch_tracking(product_id="PRD-MOONG-BULK", current_user=self.owner_user))
        item = next(b for b in data if b["batch_id"] == "PRB-TRACK-01")
        self.assertEqual(item["produced_kg"], 200.0)
        self.assertEqual(item["consumed_kg"], 50.0)
        self.assertEqual(item["available_kg"], 150.0)
        self.assertEqual(item["unit_cost_per_kg"], 144.20)
        self.assertEqual(item["cost_status"], "ACTUAL")
        self.assertEqual(item["valuation"], 21630.0)


if __name__ == "__main__":
    unittest.main()
