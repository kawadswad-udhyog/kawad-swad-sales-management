"""
Kawad Swad ERP - End-to-End Full Lifecycle Integration Test Suite
Verifies the complete flow:
Raw Material Purchase -> Dal Milling -> Papad Production -> Packaging -> Dispatch -> Sale -> Daily Closing -> Costing Integrity
"""

import unittest
import asyncio
from unittest.mock import patch, MagicMock
from decimal import Decimal

from app.sheets import db
from app.calculations import (
    calculate_raw_material_balance,
    calculate_bulk_stock_balance,
    calculate_finished_stock_balance,
    calculate_warehouse_stock_balance,
    calculate_salesman_stock_balance,
    get_latest_purchase_rate,
    calculate_batch_actual_cost,
    calculate_finished_sku_cost,
    validate_recipe_formulation,
)
from app.routers.production import (
    receive_raw_material,
    RawMaterialReceiveRequest,
    record_dal_milling_batch,
    DalMillingCreate,
    create_batch,
    approve_batch,
    create_packaging,
    ProductionCreate,
    PackagingCreate,
    ApprovalRequest,
    save_recipe,
    RecipeSave,
    RecipeItemInput,
)
from app.routers import sales
from app.routers import stock
from app.routers import closing
from app.models import (
    StockIssueCreate,
    SaleCreate,
    SaleItemCreate,
    DailyClosingCreate,
)



from app.sheets import db, REQUIRED_TABS


class TestERPFullLifecycle(unittest.TestCase):
    def setUp(self):
        for tab in REQUIRED_TABS:
            db.memory_store[tab] = []
        self.owner_user = {
            "user_id": "USR-OWNER-01",
            "full_name": "Test Owner",
            "role": "OWNER",
            "mobile": "9999999999",
            "active": True,
        }

        self.salesman_user = {
            "user_id": "USR-SALES-01",
            "full_name": "Ramesh Salesman",
            "role": "SALESMAN",
            "mobile": "9888888888",
            "active": True,
        }

        # Seed master data
        db.append_record("Users", self.owner_user)
        db.append_record("Users", self.salesman_user)

        db.append_record("RawMaterials", {
            "raw_material_id": "RM-WHOLE-MOONG-DAL",
            "material_name": "Whole Moong Dal",
            "category": "WHOLE_GRAIN",
            "current_stock": 0.0,
            "unit": "kg",
            "rate_per_unit": 110.0,
            "rate_status": "CONFIRMED",
        })
        db.append_record("RawMaterials", {
            "raw_material_id": "RM-MOONG-FLOUR",
            "material_name": "Moong Dal Flour",
            "category": "FLOUR",
            "current_stock": 0.0,
            "unit": "kg",
            "rate_per_unit": 120.0,
            "rate_status": "CONFIRMED",
        })
        db.append_record("RawMaterials", {
            "raw_material_id": "RM-BLACK-PEPPER",
            "material_name": "Black Pepper",
            "category": "SPICE",
            "current_stock": 50.0,
            "unit": "kg",
            "rate_per_unit": 700.0,
            "rate_status": "CONFIRMED",
        })
        db.append_record("RawMaterials", {
            "raw_material_id": "RM-SALT",
            "material_name": "Salt",
            "category": "SALT",
            "current_stock": 100.0,
            "unit": "kg",
            "rate_per_unit": 20.0,
            "rate_status": "CONFIRMED",
        })

        db.append_record("Products", {
            "product_id": "PRD-MOONG-200",
            "product_name": "Moong Master Papad",
            "sku": "MM-200G",
            "pack_weight_g": 200,
            "selling_unit": "PACKET",
            "active": "true",
            "wholesale_packet_price": 50.0,
            "retailer_packet_price": 55.0,
        })

    # =========================================================================
    # 1. RAW MATERIAL RECEIVING & COSTING INTEGRITY
    # =========================================================================
    def test_stage1_raw_material_receiving_and_costing(self):
        """Verify receiving raw whole dal updates inventory with correct landed cost."""
        req = RawMaterialReceiveRequest(
            raw_material_id="RM-WHOLE-MOONG-DAL",
            material_name="Whole Moong Dal",
            quantity=100.0,
            unit="kg",
            invoice_number="BILL-DAL-001",
            supplier_id="SUP-AGRO-01",
            supplier_name="Kisan Agro Traders",
            purchase_rate=110.0,
            freight_amount=700.0,
            idempotency_key="TEST-PURCHASE-001",
        )

        res = asyncio.run(receive_raw_material(req, user=self.owner_user))
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.new_available_stock, 100.0)
        self.assertEqual(res.landed_rate_per_unit, 117.0)  # (100 * 110 + 700) / 100 = 117.0

        # Check raw material stock balance
        bal = calculate_raw_material_balance(
            "Whole Moong Dal",
            db.get_records("RawMaterials"),
            db.get_records("RawMaterialLedger"),
        )
        self.assertEqual(bal["available"], 100.0)

    # =========================================================================
    # 2. DAL MILLING (FLOUR PREPARATION) & COST ABSORPTION
    # =========================================================================
    def test_stage2_milling_transformation_and_costing(self):
        """Verify milling consumes whole dal, credits flour, and absorbs milling expense."""
        # Setup: initial 100 kg whole dal
        db.append_record("RawMaterialLedger", {
            "raw_material_txn_id": "RML-SEED-01",
            "txn_datetime": "2026-10-29T10:00:00Z",
            "raw_material_id": "RM-WHOLE-MOONG-DAL",
            "material_name": "Whole Moong Dal",
            "movement_type": "PURCHASE_RECEIPT",
            "quantity": 100.0,
            "unit": "kg",
            "rate_per_unit": 110.0,
            "status": "VALID",
        })

        # Mill 100 kg dal -> 98 kg flour with Rs 300 milling expense
        milling_req = DalMillingCreate(
            source_material_id="RM-WHOLE-MOONG-DAL",
            input_quantity_kg=100.0,
            flour_output_kg=98.0,
            milling_expenses=300.0,
            notes="Factory stone grinder run",
            idempotency_key="TEST-MILLING-001",
        )

        res = asyncio.run(record_dal_milling_batch(milling_req, user=self.owner_user))
        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.input_quantity_kg, 100.0)
        self.assertEqual(res.flour_output_kg, 98.0)
        self.assertEqual(res.processing_loss_kg, 2.0)
        self.assertEqual(res.flour_unit_cost, 115.31)

        # Check Whole Dal stock: 100 - 100 = 0.0
        dal_bal = calculate_raw_material_balance(
            "Whole Moong Dal",
            db.get_records("RawMaterials"),
            db.get_records("RawMaterialLedger"),
        )
        self.assertEqual(dal_bal["available"], 0.0)

        # Check Flour stock: 0 + 98 = 98.0
        flour_bal = calculate_raw_material_balance(
            "Moong Dal Flour",
            db.get_records("RawMaterials"),
            db.get_records("RawMaterialLedger"),
        )
        self.assertEqual(flour_bal["available"], 98.0)


    # =========================================================================
    # 3. PAPAD PRODUCTION & FORMULATION RULE ENFORCEMENT
    # =========================================================================
    def test_stage3_papad_production_prohibits_whole_dal(self):
        """Verify strict rule: Whole dal cannot be consumed directly in papad recipes."""
        # Formulation validation rejects whole dal
        bad_recipe_items = [
            {"material_name": "Whole Moong Dal", "quantity": 1000, "unit": "g"},
            {"material_name": "Salt", "quantity": 20, "unit": "g"},
        ]
        with self.assertRaises(ValueError) as ctx:
            validate_recipe_formulation("Moong Master Papad", bad_recipe_items, 1.2)
        self.assertIn("Formulation violation", str(ctx.exception))
        self.assertIn("Papad recipes require milled flour", str(ctx.exception))

    def test_stage3_papad_production_material_issue_and_approval(self):
        """Verify valid recipe issues flour and credits bulk stock upon batch approval."""
        # 1. Seed 100 kg flour in ledger
        db.append_record("RawMaterialLedger", {
            "raw_material_txn_id": "RML-FLOUR-01",
            "txn_datetime": "2026-10-29T10:00:00Z",
            "raw_material_id": "RM-MOONG-FLOUR",
            "material_name": "Moong Dal Flour",
            "movement_type": "MILLING_OUTPUT",
            "quantity": 100.0,
            "unit": "kg",
            "rate_per_unit": 115.31,
            "status": "VALID",
        })

        # 2. Save approved recipe using flour (NOT whole dal)
        asyncio.run(save_recipe(
            RecipeSave(
                product_id="PRD-MOONG-200",
                approved=True,
                expected_yield_kg=1.2,
                items=[
                    RecipeItemInput(material_name="Moong Dal Flour", quantity_per_kg=0.833, unit="kg"),
                    RecipeItemInput(material_name="Salt", quantity_per_kg=0.02, unit="kg"),
                ],
            ),
            user=self.owner_user,
        ))

        # 3. Create production batch for 10 kg papad
        batch = asyncio.run(create_batch(
            ProductionCreate(
                production_date="2026-10-29",
                product_id="PRD-MOONG-200",
                quantity_kg=10.0,
                wastage_kg=0.0,
            ),
            user=self.owner_user,
        ))
        prod_id = batch["production_id"]

        # 4. Approve batch (issues flour and credits bulk inventory)
        app_res = asyncio.run(approve_batch(
            prod_id,
            ApprovalRequest(approved=True, notes="Batch approved for packaging"),
            user=self.owner_user,
        ))
        self.assertEqual(app_res["status"], "APPROVED")

        # Verify bulk stock in ProductionStockLedger
        bulk_bals = calculate_bulk_stock_balance(
            db.get_records("ProductionStockLedger"),
            "Moong Master Papad",
        )
        self.assertEqual(bulk_bals["moong master papad"], 10.0)

    # =========================================================================
    # 4. PACKAGING (BULK TO PACKET CONVERSION)
    # =========================================================================
    def test_stage4_packaging_bulk_to_packets(self):
        """Verify bulk papad is converted into finished packet SKUs."""
        # Seed 10 kg bulk papad in ProductionStockLedger
        db.append_record("ProductionStockLedger", {
            "movement_id": "MVT-BULK-01",
            "txn_datetime": "2026-10-29T11:00:00Z",
            "movement_type": "BULK_PRODUCED",
            "product_id": "PRD-MOONG-200",
            "bulk_product_key": "moong master papad",
            "product_name_snapshot": "Moong Master Papad",
            "quantity_kg": 10.0,
            "quantity_packets": 0,
            "channel": "FACTORY_BULK",
            "reference_id": "BATCH-001",
        })

        # Pack 50 packets of 200g (50 * 0.2 = 10.0 kg)
        pack_req = PackagingCreate(
            packaging_date="2026-10-29",
            product_id="PRD-MOONG-200",
            bulk_kg_used=10.0,
            packets_200g=50,
            packets_500g=0,
            packets_1000g=0,
            packing_loss_kg=0.0,
            reference="PACK-RUN-001",
        )

        pack_res = asyncio.run(create_packaging(pack_req, user=self.owner_user))
        self.assertIn(pack_res["status"], ["RECORDED", "COMPLETE"])
        self.assertEqual(pack_res["total_packets"], 50)

        # Bulk stock should now be 0 kg
        bulk_bals = calculate_bulk_stock_balance(
            db.get_records("ProductionStockLedger"),
            "Moong Master Papad",
        )
        self.assertEqual(bulk_bals["moong master papad"], 0.0)

        # Finished stock should have 50 packets
        fin_bals = calculate_finished_stock_balance(
            db.get_records("ProductionStockLedger"),
            "PRD-MOONG-200",
        )
        self.assertEqual(fin_bals["PRD-MOONG-200"], 50)

    # =========================================================================
    # 5. VAN LOADING & SALES DISPATCH TO RETAILER
    # =========================================================================
    def test_stage5_stock_issuance_and_salesman_billing(self):
        """Verify finished goods are issued to salesman and billed with stock deduction."""
        # 1. Company warehouse stock: 50 packets
        db.append_record("SalesmanStockLedger", {
            "stock_txn_id": "STK-REC-01",
            "txn_datetime": "2026-10-29T12:00:00Z",
            "salesman_user_id": "",
            "product_id": "PRD-MOONG-200",
            "sku_snapshot": "MM-200G",
            "txn_type": "COMPANY_RECEIPT",
            "quantity": 50,
            "unit": "PACKET",
            "pack_weight_g": 200,
        })

        # 2. Issue 20 packets to salesman
        issue_req = StockIssueCreate(
            txn_type="ISSUE_TO_SALESMAN",
            product_id="PRD-MOONG-200",
            salesman_user_id="USR-SALES-01",
            quantity=20,
            notes="Daily van load",
        )
        issue_res = asyncio.run(stock.record_stock_movement(issue_req, current_user=self.owner_user))
        self.assertEqual(issue_res.quantity, 20)

        # Verify salesman available stock: 20 packets
        salesman_bal = calculate_salesman_stock_balance(
            db.get_records("SalesmanStockLedger"),
            salesman_user_id="USR-SALES-01",
            product_id="PRD-MOONG-200",
        )
        self.assertEqual(salesman_bal, 20)

        # 3. Salesman sells 5 packets to retailer
        db.append_record("Customers", {
            "customer_id": "CUS-001",
            "shop_name": "Shree Ram Kirana Store",
            "active": "true",
            "city": "Bhilwara",
        })

        sale_req = SaleCreate(
            customer_id="CUS-001",
            customer_name_snapshot="Shree Ram Kirana Store",
            payment_method="CASH",
            payment_status="PAID",
            subtotal=275.0,  # 5 * 55.0
            discount_amount=0.0,
            tax_amount=0.0,
            bill_total=275.0,
            idempotency_key="SALE-RUN-001",
            items=[
                SaleItemCreate(
                    product_id="PRD-MOONG-200",
                    product_name_snapshot="Moong Master Papad",
                    sku_snapshot="MM-200G",
                    pack_weight_g=200,
                    quantity=5,
                    actual_unit_price=55.0,
                    discount_amount=0.0,
                    line_total=275.0,
                )
            ],
        )

        sale_res = asyncio.run(sales.create_sale(sale_req, current_user=self.salesman_user))
        self.assertEqual(sale_res.bill_total, 275.0)
        self.assertEqual(sale_res.txn_status, "COMPLETE")

        # Salesman remaining stock: 20 - 5 = 15 packets
        salesman_bal_after = calculate_salesman_stock_balance(
            db.get_records("SalesmanStockLedger"),
            salesman_user_id="USR-SALES-01",
            product_id="PRD-MOONG-200",
        )
        self.assertEqual(salesman_bal_after, 15)

        # Verify cash collected in CashLedger
        cash_entries = [
            c for c in db.get_records("CashLedger")
            if str(c.get("salesman_user_id")) == "USR-SALES-01"
        ]
        self.assertEqual(len(cash_entries), 1)
        self.assertEqual(float(cash_entries[0]["amount"]), 275.0)

    # =========================================================================
    # 6. DAILY CLOSING & CASH RECONCILIATION
    # =========================================================================
    def test_stage6_daily_closing_reconciliation(self):
        """Verify daily closing reconciles opening cash, collections, and physical returns."""
        # Salesman collected Rs 275 in cash
        db.append_record("Sales", {
            "sale_id": "SALE-01",
            "sale_datetime": "2026-10-29T14:00:00Z",
            "salesman_user_id": "USR-SALES-01",
            "bill_total": 275.0,
            "txn_status": "COMPLETE",
        })
        db.append_record("Payments", {
            "payment_id": "PAY-01",
            "sale_id": "SALE-01",
            "payment_datetime": "2026-10-29T14:00:00Z",
            "payment_method": "CASH",
            "amount": 275.0,
        })

        closing_req = DailyClosingCreate(
            opening_cash=500.0,
            physical_cash_returned=775.0,  # 500 opening + 275 collected = 775 expected
            idempotency_key="CLOSING-001",
        )

        with patch("app.routers.closing.business_today", return_value="2026-10-29"):
            closing_res = asyncio.run(closing.submit_daily_closing(closing_req, current_user=self.salesman_user))

        self.assertEqual(closing_res.cash_collected, 275.0)
        self.assertEqual(closing_res.expected_cash_return, 775.0)
        self.assertEqual(closing_res.physical_cash_returned, 775.0)
        self.assertEqual(closing_res.cash_difference, 0.0)


if __name__ == "__main__":
    unittest.main()
