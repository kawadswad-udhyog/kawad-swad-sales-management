"""
Regression and Verification Test Suite for Audit Findings Implementation.

Verifies:
1. Packing tolerance cannot be negative (ValueError & Pydantic validation).
2. Authoritative bulk cost carryover without ₹160/kg hardcoded fallback.
3. SKU packaging material & labor costing without ₹1.50/₹0.50 fallback.
4. Production batch cost carryover from raw materials & recipe to batch & stock ledger.
5. SKU-wise finished-goods valuation (bulk papad share + pouch + packing labor).
6. Sales COGS calculation using authoritative finished costs without ₹170/kg flat multiplier.
7. Accounting reconciliation interface with dry-run preview and confirmed backfill safety.
"""

import os
os.environ.setdefault("SALES_TESTING", "1")
os.environ.setdefault("SALES_JWT_SECRET", "test-only-secret-do-not-use-for-deployment-32")

import sys
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import unittest
from decimal import Decimal

from app.sheets import db
from app.calculations.packaging import calculate_packing_variance
from app.calculations.costing import (
    get_authoritative_bulk_cost_per_kg,
    get_sku_packing_costs,
    get_sku_finished_cost,
    calculate_finished_sku_cost,
)
from app.routers.production import PackagingCreate
from app.routers.sales import _compute_authoritative_cogs
from app.accounting.reconciliation import audit_and_reconcile_operational_events


class TestAuditFixesRegression(unittest.TestCase):
    def setUp(self):
        db.allow_in_memory_fallback = True
        db.is_connected = False
        # Reset DB tables
        for table in [
            "ProductionBatches",
            "PackagingBatches",
            "ProductionStockLedger",
            "RawMaterials",
            "RawMaterialLedger",
            "Recipes",
            "Products",
            "Sales",
            "JournalHeaders",
            "JournalVouchers",
            "AccountingLedger",
        ]:
            db.memory_store[table] = []

    def test_1_negative_packing_tolerance_rejection(self):
        """Packing tolerance cannot be negative in calculation and schema."""
        # 1. Calculation function rejection
        with self.assertRaises(ValueError) as ctx:
            calculate_packing_variance(
                bulk_consumed_kg=100.0,
                total_packed_kg=98.0,
                packing_loss_kg=0.0,
                tolerance_kg=-0.5,
            )
        self.assertIn("Packing tolerance cannot be negative", str(ctx.exception))

        # Positive or zero tolerance must succeed
        res_zero = calculate_packing_variance(
            bulk_consumed_kg=100.0,
            total_packed_kg=100.0,
            packing_loss_kg=0.0,
            tolerance_kg=0.0,
        )
        self.assertEqual(res_zero["status"], "MATCH")

        # 2. Schema / Pydantic validation rejection
        try:
            from pydantic import ValidationError
            with self.assertRaises((ValidationError, ValueError)):
                PackagingCreate(
                    batch_id="PRB-TEST-001",
                    bulk_consumed_kg=10.0,
                    pack_size_grams=200,
                    packets_produced=50,
                    tolerance_kg=-1.0,
                )
        except ImportError:
            pass

    def test_2_authoritative_bulk_cost_no_hardcoded_160(self):
        """Authoritative bulk cost per kg does not use ₹160 fallback."""
        # When no data exists, it must raise ValueError rather than returning ₹160.00
        with self.assertRaises(ValueError) as ctx:
            get_authoritative_bulk_cost_per_kg(
                bulk_key_or_product_id="PRB-NONEXISTENT",
                production_batches=[],
                recipes=[],
                production_stock_ledger=[],
            )
        self.assertIn("Authoritative bulk cost cannot be established", str(ctx.exception))

        # When ProductionBatches has actual cost, it is authoritative
        batches = [{
            "product_id": "PRD-MOONG",
            "product_name_snapshot": "Moong Special",
            "status": "APPROVED",
            "actual_cost_per_kg": "142.75",
        }]
        cost = get_authoritative_bulk_cost_per_kg(
            bulk_key_or_product_id="PRD-MOONG",
            production_batches=batches,
        )
        self.assertEqual(cost, Decimal("142.75"))

        # When resolving from ProductionStockLedger
        stock_ledger = [{
            "product_id": "PRD-MOONG",
            "movement_type": "BULK_PRODUCED",
            "unit_cost_per_kg": "138.50",
        }]
        cost_stock = get_authoritative_bulk_cost_per_kg(
            bulk_key_or_product_id="PRD-MOONG",
            production_batches=[],
            production_stock_ledger=stock_ledger,
        )
        self.assertEqual(cost_stock, Decimal("138.50"))

        # When resolving from Recipe standard formula
        recipes = [{
            "product_id": "PRD-MOONG",
            "product_name": "Moong Special",
            "approved": "true",
            "expected_yield_kg": "1.2",
            "items": '[{"item_name": "Moong Dal Flour", "quantity": 1.0, "unit": "kg", "rate_per_unit": 120.0}]',
        }]
        cost_recipe = get_authoritative_bulk_cost_per_kg(
            bulk_key_or_product_id="PRD-MOONG",
            production_batches=[],
            recipes=recipes,
        )
        self.assertEqual(cost_recipe, Decimal("100.00"))

    def test_3_sku_packing_costs_no_hardcoded_fallback(self):
        """SKU packing material and labor costs resolve dynamically without ₹1.50/₹0.50 fallback."""
        # Product with explicit packing costs
        product = {
            "sku": "MOONG-200G",
            "packaging_material_cost_per_packet": "2.25",
            "packing_labour_per_packet": "0.75",
        }
        mat_cost, lab_cost = get_sku_packing_costs(
            product_record=product,
        )
        self.assertEqual(mat_cost, Decimal("2.25"))
        self.assertEqual(lab_cost, Decimal("0.75"))

        # Product without costs returns 0.00 without inventing 1.50 or 0.50
        empty_prod = {"sku": "MOONG-200G", "pack_weight_g": 200}
        mat_cost_zero, lab_cost_zero = get_sku_packing_costs(
            product_record=empty_prod,
            raw_materials_master=[],
        )
        self.assertEqual(mat_cost_zero, Decimal("0.00"))
        self.assertEqual(lab_cost_zero, Decimal("0.00"))

        # Product with pouch lookup in RawMaterials
        rm_master = [{
            "material_name": "Pouch 200g Moong",
            "rate_per_unit": "1.85",
        }]
        mat_cost_rm, _ = get_sku_packing_costs(
            product_record=empty_prod,
            raw_materials_master=rm_master,
        )
        self.assertEqual(float(mat_cost_rm), 1.85)

    def test_4_sku_finished_goods_valuation(self):
        """SKU finished goods cost correctly combines bulk papad + material + labor."""
        # Direct calculation: 200g packet with ₹140.00/kg bulk + ₹2.00 material + ₹0.50 labor
        sku_val = calculate_finished_sku_cost(
            pack_weight_grams=200,
            production_cost_per_saleable_kg=140.00,
            packaging_material_cost_per_packet=2.00,
            packing_labour_per_packet=0.50,
        )
        # Bulk portion: 0.200 kg * 140 = 28.00; total = 28.00 + 2.00 + 0.50 = 30.50
        self.assertEqual(sku_val["base_papad_cost"], 28.00)
        self.assertEqual(sku_val["total_packing_cost"], 2.50)
        self.assertEqual(sku_val["finished_packet_cost"], 30.50)

        # 500g packet with ₹140.00/kg bulk + ₹3.00 material + ₹1.00 labor
        sku_val_500 = calculate_finished_sku_cost(
            pack_weight_grams=500,
            production_cost_per_saleable_kg=140.00,
            packaging_material_cost_per_packet=3.00,
            packing_labour_per_packet=1.00,
        )
        # Bulk portion: 0.500 kg * 140 = 70.00; total = 70.00 + 3.00 + 1.00 = 74.00
        self.assertEqual(sku_val_500["base_papad_cost"], 70.00)
        self.assertEqual(sku_val_500["total_packing_cost"], 4.00)
        self.assertEqual(sku_val_500["finished_packet_cost"], 74.00)

        # Via get_sku_finished_cost function
        prod_record = {
            "product_id": "PRD-M-200",
            "product_name": "Moong Special",
            "sku": "MOONG-200G",
            "pack_weight_g": 200,
            "packaging_material_cost_per_packet": 2.00,
            "packing_labour_per_packet": 0.50,
        }
        batches = [{
            "product_id": "PRD-M-200",
            "product_name_snapshot": "Moong Special",
            "status": "APPROVED",
            "actual_cost_per_kg": "140.00",
        }]
        fin_cost = get_sku_finished_cost(
            product_record=prod_record,
            production_batches=batches,
        )
        self.assertEqual(fin_cost, Decimal("30.50"))

    def test_5_authoritative_sales_cogs_no_hardcoded_170(self):
        """Sales COGS computes exact line-item finished cost instead of flat ₹170.00."""
        # Seed Products master with configured standard costs
        db.memory_store["Products"] = [
            {
                "product_id": "PRD-01",
                "sku": "MOONG-200G",
                "product_name": "Moong Papad 200g",
                "standard_cost": "30.50",
                "pack_weight_g": "200",
            },
            {
                "product_id": "PRD-02",
                "sku": "URAD-500G",
                "product_name": "Urad Papad 500g",
                "standard_cost": "75.00",
                "pack_weight_g": "500",
            },
        ]

        items = [
            {"product_id": "PRD-01", "sku": "MOONG-200G", "quantity": 10},  # 10 * 30.50 = 305.00
            {"product_id": "PRD-02", "sku": "URAD-500G", "quantity": 4},   # 4 * 75.00 = 300.00
        ]

        cogs = _compute_authoritative_cogs(items)
        # Expected: 305.00 + 300.00 = 605.00
        # If old hardcoded ₹170/kg were used: (10*0.2 + 4*0.5)*170 = 4kg * 170 = 680.00
        self.assertEqual(cogs, Decimal("605.00"))

    def test_6_accounting_reconciliation_dry_run_and_execution(self):
        """Reconciliation interface supports dry-run preview and confirmed live posting."""
        # Seed an operational sale with no JournalHeaders / JournalVouchers entry
        db.memory_store["Sales"] = [{
            "sale_id": "SALE-AUDIT-001",
            "bill_number": "BILL-001",
            "sale_date": "2026-03-01",
            "customer_id": "CUST-001",
            "customer_name_snapshot": "Test Trader",
            "subtotal": "1000.00",
            "tax_amount": "50.00",
            "bill_total": "1050.00",
            "payment_method": "CREDIT",
            "bill_status": "COMPLETED",
            "status": "COMPLETED",
        }]
        db.memory_store["SaleItems"] = [{
            "sale_id": "SALE-AUDIT-001",
            "product_id": "PRD-01",
            "quantity": "20",
            "unit_price": "52.50",
            "line_total": "1050.00",
        }]
        db.memory_store["Products"] = [{
            "product_id": "PRD-01",
            "sku": "MOONG-200G",
            "standard_cost": "30.00",
            "pack_weight_g": "200",
        }]

        # 1. Dry run execution
        preview = audit_and_reconcile_operational_events(
            dry_run=True,
            actor="SYSTEM_AUDITOR",
        )
        self.assertTrue(preview["dry_run"])
        self.assertEqual(preview["status"], "COMPLETED")
        self.assertGreaterEqual(preview["missing_count"], 1)
        self.assertEqual(preview["reconciled_count"], 0)
        # Verify no voucher was written to JournalHeaders during dry run
        self.assertEqual(len(db.memory_store["JournalHeaders"]), 0)

        # 2. Live execution
        result = audit_and_reconcile_operational_events(
            dry_run=False,
            actor="SYSTEM_AUDITOR",
        )
        self.assertFalse(result["dry_run"])
        self.assertEqual(result["status"], "COMPLETED")
        self.assertGreaterEqual(result["reconciled_count"], 1)
        self.assertGreaterEqual(len(db.memory_store["JournalHeaders"]), 1)
        voucher = db.memory_store["JournalHeaders"][0]
        self.assertEqual(voucher["status"], "POSTED")
        self.assertEqual(voucher["reference_type"], "SALE_INVOICE")
        self.assertEqual(voucher["reference_id"], "SALE-AUDIT-001")

        # 3. Running again should find 0 unposted events (idempotency)
        rerun = audit_and_reconcile_operational_events(
            dry_run=False,
            actor="SYSTEM_AUDITOR",
        )
        self.assertEqual(rerun["missing_count"], 0)
        self.assertEqual(rerun["reconciled_count"], 0)


if __name__ == "__main__":
    unittest.main()
