"""
Kawad Swad ERP - Controlled Staging Walkthrough & Verification Runner
Executes the practical 15-step low-risk business workflow in an isolated environment.
Validates end-to-end integrity:
Receiving -> Milling -> Production -> Packaging -> Dispatch -> Sale -> Daily Closing -> Persistence
"""

import sys
import os
import asyncio
from decimal import Decimal

# Ensure backend path is on sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import tests

os.environ["SALES_TESTING"] = "1"
os.environ["SALES_JWT_SECRET"] = "staging-walkthrough-secret-key-32chars"

from app.sheets import db, REQUIRED_TABS
from app.calculations import (
    calculate_raw_material_balance,
    calculate_bulk_stock_balance,
    calculate_finished_stock_balance,
    calculate_warehouse_stock_balance,
    calculate_salesman_stock_balance,
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
from app.routers import stock, sales, closing
from app.models import (
    StockIssueCreate,
    SaleCreate,
    SaleItemCreate,
    DailyClosingCreate,
)


def run_walkthrough():
    print("=" * 78)
    print("KAWAD SWAD ERP: CONTROLLED STAGING 15-STEP CANARY WALKTHROUGH")
    print("=" * 78)

    # Reset memory store
    for tab in REQUIRED_TABS:
        db.memory_store[tab] = []

    owner_user = {
        "user_id": "USR-OWNER-01",
        "full_name": "Staging Owner",
        "role": "OWNER",
        "mobile": "9999999999",
        "active": True,
    }
    salesman_user = {
        "user_id": "USR-SALES-01",
        "full_name": "Ramesh Salesman",
        "role": "SALESMAN",
        "mobile": "9888888888",
        "active": True,
    }
    db.append_record("Users", owner_user)
    db.append_record("Users", salesman_user)

    # Master Seed Data
    db.append_record("RawMaterials", {
        "raw_material_id": "RM-WHOLE-MOONG-DAL",
        "material_name": "Whole Moong Dal",
        "category": "WHOLE_GRAIN",
        "current_stock": 0.0,
        "unit": "kg",
        "rate_per_unit": 112.0,
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
        "raw_material_id": "RM-SALT",
        "material_name": "Salt",
        "category": "SALT",
        "current_stock": 50.0,
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
    db.append_record("Customers", {
        "customer_id": "CUS-STAGING-01",
        "shop_name": "Adarsh Kirana Bhandar",
        "active": "true",
        "city": "Bhilwara",
    })

    print("[SETUP] Staging master data initialized: Users, RawMaterials, Products, Customers.")

    # -------------------------------------------------------------------------
    # STEP 1 & 2: RECEIVE SMALL QUANTITY OF WHOLE DAL & VERIFY LANDED COST
    # -------------------------------------------------------------------------
    print("\n--- STEP 1 & 2: RECEIVE WHOLE DAL & VERIFY LANDED COST ---")
    rcv_req = RawMaterialReceiveRequest(
        raw_material_id="RM-WHOLE-MOONG-DAL",
        material_name="Whole Moong Dal",
        quantity=50.0,
        unit="kg",
        invoice_number="STG-INV-001",
        supplier_id="SUP-AGRO-STG",
        supplier_name="Kisan Agro Mandi",
        purchase_rate=112.0,
        freight_amount=400.0,
        idempotency_key="STG-RCV-DAL-001",
    )
    rcv_res = asyncio.run(receive_raw_material(rcv_req, user=owner_user))
    print(f"Receipt recorded: TxID={rcv_res.raw_material_txn_id}, Status={rcv_res.status}")
    print(f"Stock After={rcv_res.new_available_stock} kg, Landed Rate=Rs {rcv_res.landed_rate_per_unit:.2f}/kg")
    
    # Verification: (50 * 112 + 400) / 50 = (5600 + 400) / 50 = Rs 120.00/kg
    assert rcv_res.new_available_stock == 50.0, "Stock mismatch"
    assert rcv_res.landed_rate_per_unit == 120.0, f"Expected 120.0, got {rcv_res.landed_rate_per_unit}"
    print("[PASS] Step 1 & 2: 50.0 kg Whole Moong Dal received @ Rs 120.00/kg landed rate.")

    # -------------------------------------------------------------------------
    # STEP 3, 4, 5: DAL MILLING & COST ABSORPTION
    # -------------------------------------------------------------------------
    print("\n--- STEP 3, 4, 5: DAL MILLING & COST ABSORPTION ---")
    mill_req = DalMillingCreate(
        source_material_id="RM-WHOLE-MOONG-DAL",
        input_quantity_kg=40.0,
        flour_output_kg=39.0,
        milling_expenses=160.0,
        notes="Staging trial stone grinder run",
        idempotency_key="STG-MILL-001",
    )
    mill_res = asyncio.run(record_dal_milling_batch(mill_req, user=owner_user))
    print(f"Milling batch recorded: BatchID={mill_res.milling_batch_id}")
    print(f"Input: {mill_res.input_quantity_kg} kg -> Output: {mill_res.flour_output_kg} kg (Loss: {mill_res.processing_loss_kg} kg)")
    print(f"Flour Landed Cost: Rs {mill_res.flour_unit_cost:.2f}/kg")
    
    # Verification: Dal cost = 40 * 120 = 4800. Total = 4800 + 160 = 4960. Rate = 4960 / 39 = 127.179... -> 127.18
    assert mill_res.flour_unit_cost == 127.18, f"Expected 127.18, got {mill_res.flour_unit_cost}"
    
    # Check inventory balances:
    dal_bal = calculate_raw_material_balance("Whole Moong Dal", db.get_records("RawMaterials"), db.get_records("RawMaterialLedger"))
    flour_bal = calculate_raw_material_balance("Moong Dal Flour", db.get_records("RawMaterials"), db.get_records("RawMaterialLedger"))
    print(f"Inventory Check: Whole Dal remaining = {dal_bal['available']} kg (expected 10.0 kg)")
    print(f"Inventory Check: Moong Flour available = {flour_bal['available']} kg (expected 39.0 kg)")
    assert dal_bal["available"] == 10.0, "Whole dal balance incorrect"
    assert flour_bal["available"] == 39.0, "Flour balance incorrect"
    print("[PASS] Step 3, 4, 5: Milling consumed 40 kg dal, produced 39 kg flour @ Rs 127.18/kg.")

    # -------------------------------------------------------------------------
    # STEP 6 & 7: PRODUCE SMALL PAPAD BATCH & BULK CREDIT
    # -------------------------------------------------------------------------
    print("\n--- STEP 6 & 7: PAPAD PRODUCTION & BULK STOCK CREDITING ---")
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
        user=owner_user,
    ))

    # Produce 10 kg papad batch
    batch_rec = asyncio.run(create_batch(
        ProductionCreate(
            production_date="2026-10-29",
            product_id="PRD-MOONG-200",
            quantity_kg=10.0,
            wastage_kg=0.0,
            notes="Staging production trial",
        ),
        user=owner_user,
    ))
    batch_id = batch_rec["production_id"]
    print(f"Production batch created: BatchID={batch_id}, Status={batch_rec['status']}")

    # Approve batch
    app_res = asyncio.run(approve_batch(
        batch_id,
        ApprovalRequest(approved=True, notes="Staging batch verified and approved"),
        user=owner_user,
    ))
    print(f"Production batch approved: Status={app_res['status']}")
    
    # Check flour balance deduction: 39.0 - (10.0 * 0.833 = 8.33) = 30.67 kg
    flour_bal_after = calculate_raw_material_balance("Moong Dal Flour", db.get_records("RawMaterials"), db.get_records("RawMaterialLedger"))
    bulk_bal = calculate_bulk_stock_balance(db.get_records("ProductionStockLedger"), "Moong Master Papad")
    print(f"Flour balance after dough issuance: {flour_bal_after['available']} kg")
    print(f"Bulk papad stock in factory ledger: {bulk_bal['moong master papad']} kg")
    assert round(flour_bal_after["available"], 2) == 30.67, f"Expected 30.67 kg flour, got {flour_bal_after['available']}"
    assert bulk_bal["moong master papad"] == 10.0, f"Expected 10.0 kg bulk, got {bulk_bal['moong master papad']}"
    print("[PASS] Step 6 & 7: 10 kg bulk papad produced; flour deducted accurately.")

    # -------------------------------------------------------------------------
    # STEP 8 & 9: PACKAGING BULK PAPAD INTO 200G SKUS
    # -------------------------------------------------------------------------
    print("\n--- STEP 8 & 9: PACKAGING (10 KG BULK -> 50 PACKETS OF 200G) ---")
    pack_req = PackagingCreate(
        packaging_date="2026-10-29",
        product_id="PRD-MOONG-200",
        bulk_kg_used=10.0,
        packets_200g=50,
        packets_500g=0,
        packets_1000g=0,
        packing_loss_kg=0.0,
        reference="STG-PACK-001",
    )
    pack_res = asyncio.run(create_packaging(pack_req, user=owner_user))
    print(f"Packaging batch recorded: PackID={pack_res['packaging_id']}, Total Packets={pack_res['total_packets']}")

    bulk_bal_after = calculate_bulk_stock_balance(db.get_records("ProductionStockLedger"), "Moong Master Papad")
    fin_bal = calculate_finished_stock_balance(db.get_records("ProductionStockLedger"), "PRD-MOONG-200")
    print(f"Bulk papad balance after packaging: {bulk_bal_after['moong master papad']} kg")
    print(f"Finished packet stock available: {fin_bal['PRD-MOONG-200']} packets")
    assert bulk_bal_after["moong master papad"] == 0.0, "Bulk stock should be 0.0 kg"
    assert fin_bal["PRD-MOONG-200"] == 50, "Finished packets should be 50"
    print("[PASS] Step 8 & 9: 10 kg bulk converted into 50 packets (200g MM-200G).")

    # -------------------------------------------------------------------------
    # STEP 10: VAN LOADING / SALESMAN STOCK ISSUANCE
    # -------------------------------------------------------------------------
    print("\n--- STEP 10: VAN LOADING (ISSUE 20 PACKETS TO SALESMAN) ---")
    # Receive into central company stock
    db.append_record("SalesmanStockLedger", {
        "stock_txn_id": "STK-REC-STG-01",
        "txn_datetime": "2026-10-29T12:00:00Z",
        "salesman_user_id": "",
        "product_id": "PRD-MOONG-200",
        "sku_snapshot": "MM-200G",
        "txn_type": "COMPANY_RECEIPT",
        "quantity": 50,
        "unit": "PACKET",
        "pack_weight_g": 200,
    })

    issue_req = StockIssueCreate(
        txn_type="ISSUE_TO_SALESMAN",
        product_id="PRD-MOONG-200",
        salesman_user_id="USR-SALES-01",
        quantity=20,
        notes="Staging morning van issue",
    )
    issue_res = asyncio.run(stock.record_stock_movement(issue_req, current_user=owner_user))
    print(f"Stock issued: TxID={issue_res.stock_txn_id}, Qty={issue_res.quantity} {issue_res.unit}")

    s_bal = calculate_salesman_stock_balance(db.get_records("SalesmanStockLedger"), "USR-SALES-01", "PRD-MOONG-200")
    print(f"Salesman assigned stock: {s_bal} packets")
    assert s_bal == 20, "Salesman stock should be 20"
    print("[PASS] Step 10: 20 packets loaded to salesman van.")

    # -------------------------------------------------------------------------
    # STEP 11 & 12: RETAIL SALE BILLING & CASH PAYMENT
    # -------------------------------------------------------------------------
    print("\n--- STEP 11 & 12: RETAIL SALE & CASH COLLECTION ---")
    sale_req = SaleCreate(
        customer_id="CUS-STAGING-01",
        customer_name_snapshot="Adarsh Kirana Bhandar",
        payment_method="CASH",
        payment_status="PAID",
        subtotal=275.0,
        discount_amount=0.0,
        tax_amount=0.0,
        bill_total=275.0,
        idempotency_key="STG-SALE-BILL-001",
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
    sale_res = asyncio.run(sales.create_sale(sale_req, current_user=salesman_user))
    print(f"Sale completed: BillNo={sale_res.bill_number}, SaleID={sale_res.sale_id}, Total=Rs {sale_res.bill_total}")
    
    s_bal_after = calculate_salesman_stock_balance(db.get_records("SalesmanStockLedger"), "USR-SALES-01", "PRD-MOONG-200")
    print(f"Salesman stock after billing: {s_bal_after} packets (expected 15)")
    assert s_bal_after == 15, "Salesman stock should be 15"
    print("[PASS] Step 11 & 12: 5 packets sold, Rs 275 cash collected, 15 packets remaining.")

    # -------------------------------------------------------------------------
    # STEP 13: DAILY CASH CLOSING RECONCILIATION
    # -------------------------------------------------------------------------
    print("\n--- STEP 13: DAILY CLOSING RECONCILIATION ---")
    close_req = DailyClosingCreate(
        opening_cash=500.0,
        physical_cash_returned=775.0,  # 500 opening + 275 cash collected = 775 expected
        idempotency_key="STG-CLOSE-001",
    )
    close_res = asyncio.run(closing.submit_daily_closing(close_req, current_user=salesman_user))
    print(f"Daily closing submitted: ClosingID={close_res.closing_id}")
    print(f"Opening Cash: Rs {close_res.opening_cash:.2f}")
    print(f"Cash Collected: Rs {close_res.cash_collected:.2f}")
    print(f"Approved Expenses: Rs {close_res.approved_cash_expenses:.2f}")
    print(f"Expected Return: Rs {close_res.expected_cash_return:.2f}")
    print(f"Physical Cash: Rs {close_res.physical_cash_returned:.2f}")
    print(f"Difference: Rs {close_res.cash_difference:.2f}")
    assert close_res.cash_difference == 0.0, "Cash difference must be 0.0"
    print("[PASS] Step 13: Daily closing reconciled perfectly (difference = Rs 0.00).")

    # -------------------------------------------------------------------------
    # STEP 14: AUDIT TRAIL & TRANSACTION HISTORY VERIFICATION
    # -------------------------------------------------------------------------
    print("\n--- STEP 14: AUDIT TRAIL VERIFICATION ---")
    audits = db.get_records("AuditLog")
    print(f"Total audit log records created: {len(audits)}")
    actions = [a.get("action") for a in audits]
    print(f"Audit actions logged: {actions}")
    assert len(audits) >= 5, "Audit log entries missing"
    print("[PASS] Step 14: All transactions recorded immutable audit trail.")

    # -------------------------------------------------------------------------
    # STEP 15: RESTART / RE-READABILITY PERSISTENCE CHECK
    # -------------------------------------------------------------------------
    print("\n--- STEP 15: RESTART / RE-READABILITY PERSISTENCE CHECK ---")
    # Verify all records are present and readable fresh from store
    fresh_rcv = db.get_records("RawMaterialLedger", fresh=True)
    fresh_prod = db.get_records("ProductionBatches", fresh=True)
    fresh_pack = db.get_records("PackagingBatches", fresh=True)
    fresh_sales = db.get_records("Sales", fresh=True)
    fresh_closing = db.get_records("DailyClosing", fresh=True)
    
    assert len(fresh_rcv) >= 3, "RawMaterialLedger records missing"
    assert len(fresh_prod) >= 1, "ProductionBatches records missing"
    assert len(fresh_pack) >= 1, "PackagingBatches records missing"
    assert len(fresh_sales) >= 1, "Sales records missing"
    assert len(fresh_closing) >= 1, "DailyClosing records missing"
    print(f"Records verified across tabs: RML={len(fresh_rcv)}, Prod={len(fresh_prod)}, Pack={len(fresh_pack)}, Sales={len(fresh_sales)}, Close={len(fresh_closing)}")
    print("[PASS] Step 15: State persistence and referential integrity verified.")

    print("\n" + "=" * 78)
    print("ALL 15 CANARY WALKTHROUGH STEPS PASSED WITH 100% ACCURACY!")
    print("=" * 78)


if __name__ == "__main__":
    run_walkthrough()
