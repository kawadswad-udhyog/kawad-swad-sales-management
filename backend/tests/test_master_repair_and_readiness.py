import os
import sys
import unittest
import asyncio
from datetime import datetime, timezone
from fastapi import HTTPException

os.environ["SALES_TESTING"] = "1"
os.environ["SALES_JWT_SECRET"] = "test-only-secret-do-not-use-for-deployment-32"

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.sheets import db
from app.models import (
    SaleCreate,
    SaleItemCreate,
    CustomRoleCreate,
)
from app.permissions import (
    canonical_role,
    has_permission,
    validate_custom_role_permissions,
    OWNER_ONLY_PERMISSIONS,
)
import app.routers.production as prod_router
import app.routers.stock as stock_router
import app.routers.sales as sales_router
import app.routers.users as users_router
from app.user_service import audit_user_reconciliation
from app.calculations.inventory import (
    calculate_bulk_stock_balance,
    calculate_finished_stock_balance,
    calculate_warehouse_stock_balance,
    calculate_salesman_stock_balance,
    calculate_physical_count_variance,
    calculate_consolidated_finished_goods_register,
)


class TestMasterRepairAndReadiness(unittest.TestCase):
    def setUp(self):
        db.memory_store = {
            "Users": [
                {"user_id": "USR-OWNER-01", "username": "owner", "role": "OWNER", "active": "true", "full_name": "Test Owner"},
                {"user_id": "USR-PA-01", "username": "pa_user", "role": "PA", "active": "true", "full_name": "Test PA"},
                {"user_id": "USR-SALES-01", "username": "sales_anand", "role": "SALESMAN", "active": "true", "full_name": "Anand Sales"},
                {"user_id": "USR-000003", "username": "manish", "role": "FIELD_SALESMAN", "active": "true", "full_name": "Manish Sales"},
            ],
            "AuthUsers": [
                {"auth_id": "AUTH-1", "user_id": "USR-OWNER-01", "username": "owner", "role": "OWNER", "active": "true", "password_hash": "pbkdf2:sha256:100000$c2FsdHNhbHQ=$ZGtka2RrZGtka2RrZGtka2RrZGs="},
                {"auth_id": "AUTH-2", "user_id": "USR-PA-01", "username": "pa_user", "role": "PA", "active": "true", "password_hash": "pbkdf2:sha256:100000$c2FsdHNhbHQ=$ZGtka2RrZGtka2RrZGtka2RrZGs="},
                {"auth_id": "AUTH-3", "user_id": "USR-SALES-01", "username": "sales_anand", "role": "SALESMAN", "active": "true", "password_hash": "pbkdf2:sha256:100000$c2FsdHNhbHQ=$ZGtka2RrZGtka2RrZGtka2RrZGs="},
                {"auth_id": "AUTH-4", "user_id": "USR-000003", "username": "manish", "role": "SALESMAN", "active": "true", "password_hash": "pbkdf2:sha256:100000$c2FsdHNhbHQ=$ZGtka2RrZGtka2RrZGtka2RrZGs="},
            ],
            "Products": [
                {
                    "product_id": "PRD-MOONG-MASTER",
                    "sku": "MM-01",
                    "product_name": "Moong Master",
                    "category": "Papad",
                    "pack_weight_g": "500",
                    "selling_unit": "PACKET",
                    "active": "true",
                },
                {
                    "product_id": "PRD-MM-200G",
                    "sku": "MM-01-200g",
                    "product_name": "Moong Master",
                    "category": "Papad",
                    "pack_weight_g": "200",
                    "selling_unit": "PACKET",
                    "active": "true",
                },
                {
                    "product_id": "PRD-MM-500G",
                    "sku": "MM-01-500g",
                    "product_name": "Moong Master",
                    "category": "Papad",
                    "pack_weight_g": "500",
                    "selling_unit": "PACKET",
                    "active": "true",
                },
                {
                    "product_id": "PRD-INACTIVE",
                    "sku": "INACT-01",
                    "product_name": "Inactive Papad",
                    "category": "Papad",
                    "pack_weight_g": "500",
                    "selling_unit": "PACKET",
                    "active": "false",
                },
            ],
            "ProductionBatches": [],
            "PackagingBatches": [],
            "ProductionStockLedger": [],
            "ProductionDispatches": [],
            "SalesmanStockLedger": [],
            "Sales": [],
            "SaleItems": [],
            "Payments": [],
            "RawMaterials": [
                {"raw_material_id": "RWM-MOONG", "material_name": "Moong Dal Flour", "current_stock": "500", "unit": "kg", "rate_per_unit": "110", "rate_status": "CONFIRMED"},
                {"raw_material_id": "RWM-SALT", "material_name": "Salt", "current_stock": "100", "unit": "kg", "rate_per_unit": "20", "rate_status": "CONFIRMED"},
                {"raw_material_id": "RWM-PAPADKHAR", "material_name": "Papadkhar", "current_stock": "100", "unit": "kg", "rate_per_unit": "80", "rate_status": "CONFIRMED"},
                {"raw_material_id": "RWM-BLACKPEPPER", "material_name": "Black Pepper", "current_stock": "100", "unit": "kg", "rate_per_unit": "650", "rate_status": "CONFIRMED"},
                {"raw_material_id": "RWM-HING", "material_name": "Compounded Asafoetida (Hing)", "current_stock": "50", "unit": "kg", "rate_per_unit": "1200", "rate_status": "CONFIRMED"},
                {"raw_material_id": "RWM-OIL", "material_name": "Edible Oil", "current_stock": "100", "unit": "kg", "rate_per_unit": "140", "rate_status": "CONFIRMED"},
                {"raw_material_id": "RWM-WATER", "material_name": "Water", "current_stock": "1000", "unit": "kg", "rate_per_unit": "0", "rate_status": "CONFIRMED"},
            ],
            "RawMaterialLedger": [],
            "StockDiscrepancies": [],
            "CustomRoles": [],
            "AuditLog": [],
            "ApprovalRequests": [],
        }

        self.owner = {"user_id": "USR-OWNER-01", "username": "owner", "role": "OWNER"}
        self.pa = {"user_id": "USR-PA-01", "username": "pa_user", "role": "PA"}
        self.salesman = {"user_id": "USR-SALES-01", "username": "sales_anand", "role": "SALESMAN"}

    # -------------------------------------------------------------------------
    # 1. Production approval posts stock exactly once & 2. Pending production
    # -------------------------------------------------------------------------
    def test_production_approval_and_pending_stock_isolation(self):
        # Create batch by PA
        batch = asyncio.run(prod_router.create_batch(
            prod_router.ProductionCreate(
                product_id="PRD-MOONG-MASTER",
                production_date="2026-10-23",
                quantity_kg=60.0,
            ),
            self.pa,
        ))
        b_id = batch["batch_id"]
        self.assertEqual(batch["status"], "PENDING")

        # 2. Verify pending production does NOT appear in available bulk stock
        ledger = db.memory_store["ProductionStockLedger"]
        bulk_before = calculate_bulk_stock_balance(ledger, "moong master").get("moong master", 0)
        self.assertEqual(bulk_before, 0.0)

        # 1. Owner approves batch
        app_res = asyncio.run(prod_router.approve_batch(
            b_id,
            prod_router.ApprovalRequest(approved=True, notes="Initial owner approval"),
            self.owner,
        ))
        self.assertEqual(app_res["status"], "APPROVED")

        # Bulk stock is credited
        bulk_after = calculate_bulk_stock_balance(db.memory_store["ProductionStockLedger"], "moong master").get("moong master", 0)
        self.assertEqual(bulk_after, 60.0)

        # Retrying approval on already approved batch raises 409 and does not double-post
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(prod_router.approve_batch(
                b_id,
                prod_router.ApprovalRequest(approved=True),
                self.owner,
            ))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(calculate_bulk_stock_balance(db.memory_store["ProductionStockLedger"], "moong master").get("moong master", 0), 60.0)

    # -------------------------------------------------------------------------
    # 3. Packaging creates correct SKU quantities & 4. Inactive/Missing SKU blocks
    # -------------------------------------------------------------------------
    def test_packaging_sku_quantities_and_inactive_guard(self):
        # First seed bulk stock
        db.memory_store["ProductionStockLedger"].append({
            "movement_id": "PST-SEED-1",
            "txn_datetime": "2026-10-23T10:00:00Z",
            "movement_type": "BULK_PRODUCED",
            "product_id": "PRD-MOONG-MASTER",
            "bulk_product_key": "moong master",
            "product_name_snapshot": "Moong Master",
            "quantity_kg": 50.0,
            "quantity_packets": 0,
            "channel": "FACTORY_BULK",
        })

        # 4. Inactive product packaging attempt must fail
        with self.assertRaises(HTTPException) as ctx_inact:
            asyncio.run(prod_router.create_packaging(
                prod_router.PackagingCreate(
                    product_id="PRD-INACTIVE",
                    packaging_date="2026-10-23",
                    bulk_kg_used=10.0,
                    packets_500g=20,
                ),
                self.pa,
            ))
        self.assertEqual(ctx_inact.exception.status_code, 400)

        # 3. Successful packaging: 10 kg bulk used -> 50 packets of 200g (50 * 0.2 = 10 kg)
        pack_res = asyncio.run(prod_router.create_packaging(
            prod_router.PackagingCreate(
                product_id="PRD-MOONG-MASTER",
                packaging_date="2026-10-23",
                bulk_kg_used=10.0,
                packets_200g=50,
                reference="PKG-REF-001",
            ),
            self.pa,
        ))
        self.assertEqual(pack_res["status"], "RECORDED")
        self.assertEqual(pack_res["total_packets"], 50)

        # Verify bulk deducted by 10 kg (50 -> 40) and finished 200g packets credited by 50
        bulk_rem = calculate_bulk_stock_balance(db.memory_store["ProductionStockLedger"], "moong master").get("moong master", 0)
        self.assertEqual(bulk_rem, 40.0)
        finished = calculate_finished_stock_balance(db.memory_store["ProductionStockLedger"], "PRD-MM-200G").get("PRD-MM-200G", 0)
        self.assertEqual(finished, 50)

    # -------------------------------------------------------------------------
    # 5. Packaging discrepancies cannot be silently reconciled
    # -------------------------------------------------------------------------
    def test_packaging_discrepancy_blocked_without_owner_approval(self):
        # 20 kg bulk consumed, but only 10 × 200 g packets produced (2 kg packed, 18 kg unexplained variance)
        with self.assertRaises(HTTPException) as ctx_disc:
            asyncio.run(prod_router.create_packaging(
                prod_router.PackagingCreate(
                    product_id="PRD-MOONG-MASTER",
                    packaging_date="2026-10-23",
                    bulk_kg_used=20.0,
                    packets_200g=10,
                    reference="PKG-DISC-001",
                ),
                self.pa,
            ))
        self.assertEqual(ctx_disc.exception.status_code, 422)
        self.assertIn("Unexplained variance", str(ctx_disc.exception.detail))

    # -------------------------------------------------------------------------
    # 6. Packaging retries: Idempotency vs conflicting payload rejection
    # -------------------------------------------------------------------------
    def test_packaging_retry_idempotency_and_conflicting_payload_rejection(self):
        # Seed 100 kg bulk
        db.memory_store["ProductionStockLedger"].append({
            "movement_id": "PST-SEED-2",
            "txn_datetime": "2026-10-23T10:00:00Z",
            "movement_type": "BULK_PRODUCED",
            "product_id": "PRD-MOONG-MASTER",
            "bulk_product_key": "moong master",
            "product_name_snapshot": "Moong Master",
            "quantity_kg": 100.0,
            "quantity_packets": 0,
            "channel": "FACTORY_BULK",
        })

        # Initial packaging: 10 kg -> 20 x 500g
        res1 = asyncio.run(prod_router.create_packaging(
            prod_router.PackagingCreate(
                product_id="PRD-MOONG-MASTER",
                packaging_date="2026-10-23",
                bulk_kg_used=10.0,
                packets_500g=20,
                reference="PKG-IDEMP-001",
            ),
            self.pa,
        ))
        self.assertEqual(res1["status"], "RECORDED")

        # Retry with identical reference and payload: returns existing batch without duplicate movements
        res2 = asyncio.run(prod_router.create_packaging(
            prod_router.PackagingCreate(
                product_id="PRD-MOONG-MASTER",
                packaging_date="2026-10-23",
                bulk_kg_used=10.0,
                packets_500g=20,
                reference="PKG-IDEMP-001",
            ),
            self.pa,
        ))
        self.assertEqual(res1["packaging_id"], res2["packaging_id"])

        # Conflicting retry with same reference but different packets: must be rejected with 409
        with self.assertRaises(HTTPException) as ctx_conflict:
            asyncio.run(prod_router.create_packaging(
                prod_router.PackagingCreate(
                    product_id="PRD-MOONG-MASTER",
                    packaging_date="2026-10-23",
                    bulk_kg_used=15.0,
                    packets_500g=30,
                    reference="PKG-IDEMP-001",
                ),
                self.pa,
            ))
        self.assertEqual(ctx_conflict.exception.status_code, 409)

    # -------------------------------------------------------------------------
    # 7 & 8. Dispatch transfers stock without altering total internal stock
    # -------------------------------------------------------------------------
    def test_dispatch_transfer_preserves_internal_stock_and_rejects_conflicts(self):
        # Seed 100 packets at factory
        db.memory_store["ProductionStockLedger"].append({
            "movement_id": "PST-SEED-3",
            "txn_datetime": "2026-10-23T10:00:00Z",
            "movement_type": "PACKETS_PACKAGED",
            "product_id": "PRD-MM-500G",
            "sku_snapshot": "MM-01-500g",
            "quantity_packets": 100,
            "channel": "FACTORY_FINISHED",
        })

        reg_before = calculate_consolidated_finished_goods_register(
            db.memory_store["Products"],
            db.memory_store["ProductionStockLedger"],
            db.memory_store["SalesmanStockLedger"],
        )
        total_before = reg_before["summary"]["total_on_hand_packets"]

        # Dispatch 30 packets from FACTORY to WAREHOUSE
        disp = asyncio.run(prod_router.dispatch(
            prod_router.DispatchCreate(
                product_id="PRD-MM-500G",
                channel="WAREHOUSE",
                destination="Central Warehouse",
                quantity_packets=30,
                reference="DSP-WH-001",
            ),
            self.pa,
        ))
        self.assertEqual(disp["status"], "DISPATCHED_NOT_SALE")

        # Consolidated internal stock must remain unchanged
        reg_after = calculate_consolidated_finished_goods_register(
            db.memory_store["Products"],
            db.memory_store["ProductionStockLedger"],
            db.memory_store["SalesmanStockLedger"],
        )
        total_after = reg_after["summary"]["total_on_hand_packets"]
        self.assertEqual(total_before, total_after)

        # Factory finished stock = 100 - 30 = 70
        # Warehouse stock = 30
        sku_row = next(r for r in reg_after["register"] if r["product_id"] == "PRD-MM-500G")
        self.assertEqual(sku_row["factory_stock"], 70)
        self.assertEqual(sku_row["warehouse_stock"], 30)

        # Conflicting retry on same reference must fail with 409
        with self.assertRaises(HTTPException) as ctx_disp_conflict:
            asyncio.run(prod_router.dispatch(
                prod_router.DispatchCreate(
                    product_id="PRD-MM-500G",
                    channel="WAREHOUSE",
                    destination="Central Warehouse",
                    quantity_packets=50,
                    reference="DSP-WH-001",
                ),
                self.pa,
            ))
        self.assertEqual(ctx_disp_conflict.exception.status_code, 409)

    # -------------------------------------------------------------------------
    # 9. Sales deduct stock from correct salesman location
    # -------------------------------------------------------------------------
    def test_sales_deduct_stock_from_correct_location(self):
        # Issue 40 packets to salesman
        db.memory_store["SalesmanStockLedger"].append({
            "stock_txn_id": "STK-SEED-1",
            "txn_datetime": "2026-10-23T11:00:00Z",
            "salesman_user_id": "USR-SALES-01",
            "product_id": "PRD-MM-500G",
            "sku_snapshot": "MM-01-500g",
            "txn_type": "ISSUE_TO_SALESMAN",
            "quantity": 40,
        })

        avail_before = calculate_salesman_stock_balance(
            db.memory_store["SalesmanStockLedger"],
            "USR-SALES-01",
            "PRD-MM-500G",
        )
        self.assertEqual(avail_before, 40)

        # Record sale of 10 packets
        sale_res = asyncio.run(sales_router.create_sale(
            SaleCreate(
                salesman_user_id="USR-SALES-01",
                sales_type="Retailer Sale",
                payment_method="CASH",
                payment_status="PAID",
                payment_reference="CASH-001",
                lines=[
                    SaleItemCreate(
                        product_id="PRD-MM-500G",
                        quantity=10,
                        actual_unit_price=120.0,
                    )
                ],
                idempotency_key="SALE-IDEMP-001",
            ),
            self.salesman,
        ))
        self.assertEqual(sale_res.txn_status, "COMPLETE")

        # Salesman balance is now 30
        avail_after = calculate_salesman_stock_balance(
            db.memory_store["SalesmanStockLedger"],
            "USR-SALES-01",
            "PRD-MM-500G",
        )
        self.assertEqual(avail_after, 30)

    # -------------------------------------------------------------------------
    # 12. Physical reconciliation creates auditable adjustment
    # -------------------------------------------------------------------------
    def test_physical_reconciliation_auditable_adjustment(self):
        # Factory stock starts with 0
        rec_res = asyncio.run(stock_router.reconcile_physical_stock(
            stock_router.PhysicalStockReconcile(
                product_id="PRD-MM-500G",
                location="FACTORY",
                physical_count=85,
                reason="Physical month-end count",
            ),
            self.owner,
        ))
        self.assertTrue(rec_res["ok"])
        self.assertEqual(rec_res["physical_count"], 85)
        self.assertEqual(rec_res["variance"], 85)
        self.assertIn("adjustment_txn_id", rec_res)
        self.assertEqual(rec_res["final_balance"], 85)
        self.assertEqual(rec_res["reconciled_by"], "USR-OWNER-01")

        # Idempotent second check: diff is 0, no duplicate adjustment
        rec_res_2 = asyncio.run(stock_router.reconcile_physical_stock(
            stock_router.PhysicalStockReconcile(
                product_id="PRD-MM-500G",
                location="FACTORY",
                physical_count=85,
                reason="Physical month-end count duplicate check",
            ),
            self.owner,
        ))
        self.assertTrue(rec_res_2["ok"])
        self.assertEqual(rec_res_2["adjusted"], 0)

    # -------------------------------------------------------------------------
    # 14. Canonical role aliases (FIELD_SALESMAN and SALESMAN)
    # -------------------------------------------------------------------------
    def test_canonical_role_mapping_resolves_manish_mismatch(self):
        # USR-000003 has Users.role = FIELD_SALESMAN and AuthUsers.role = SALESMAN
        self.assertEqual(canonical_role("FIELD_SALESMAN"), "SALESMAN")
        self.assertEqual(canonical_role("SALESMAN"), "SALESMAN")

        rep = audit_user_reconciliation()
        # Verify no false positive in role_mismatches for USR-000003
        self.assertFalse(any(r["user_id"] == "USR-000003" for r in rep["role_mismatches"]))

        # Verify it appears in canonical_aliases
        self.assertTrue(any(a["user_id"] == "USR-000003" and a["canonical_role"] == "SALESMAN" for a in rep.get("canonical_aliases", [])))

    # -------------------------------------------------------------------------
    # 16. Custom roles cannot escalate to Owner permissions
    # -------------------------------------------------------------------------
    def test_custom_roles_cannot_escalate_to_owner_permissions(self):
        # Attempt to create custom role with Owner-only permission production:approve
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(users_router.create_or_update_custom_role(
                CustomRoleCreate(
                    role_name="SUPERVISOR",
                    description="Floor Supervisor",
                    permissions={
                        "production": ["view", "approve"],  # approve is Owner-only!
                    },
                ),
                self.owner,
            ))
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("Owner-only permission", str(ctx.exception.detail))

        # Legitimate custom role succeeds
        created_role = asyncio.run(users_router.create_or_update_custom_role(
            CustomRoleCreate(
                role_name="SUPERVISOR",
                description="Floor Supervisor",
                permissions={
                    "production": ["view", "create"],
                    "attendance": ["view", "mark"],
                },
            ),
            self.owner,
        ))
        self.assertTrue(created_role["ok"])


if __name__ == "__main__":
    unittest.main()
