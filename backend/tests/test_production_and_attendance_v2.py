import os
import sys
import unittest
import asyncio
import types

os.environ["SALES_TESTING"] = "1"
os.environ["SALES_JWT_SECRET"] = "test-only-secret-do-not-use-for-deployment-32"

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.sheets import db
from app.models import (
    BulkAttendanceCreate,
    BulkAttendanceItem,
    BulkAttendanceResponse,
    DashboardMetrics,
)
from app.routers.production import (
    create_batch,
    approve_batch,
    record_bulk_attendance,
    record_attendance,
    ProductionCreate,
    ApprovalRequest,
    AttendanceCreate,
)
from app.routers.dashboard import get_dashboard_metrics


class TestProductionAndAttendanceV2(unittest.TestCase):
    def setUp(self):
        db.memory_store = {
            "Users": [
                {"user_id": "USR-OWNER-01", "username": "owner", "role": "OWNER", "active": "true"},
                {"user_id": "USR-PA-01", "username": "pa_user", "role": "PA", "active": "true"},
                {"user_id": "USR-SALES-01", "username": "sales_user", "role": "SALESMAN", "active": "true"},
            ],
            "Products": [
                {
                    "product_id": "PRD-MOONG-MASTER",
                    "sku": "MM-01",
                    "product_name": "Moong Master",
                    "category": "Papad",
                    "pack_weight_g": "500",
                    "active": "true",
                },
                {
                    "product_id": "PRD-MM-200G",
                    "sku": "MM-01-200g",
                    "product_name": "Moong Master",
                    "category": "Papad",
                    "pack_weight_g": "200",
                    "active": "true",
                },
                {
                    "product_id": "PRD-MM-500G",
                    "sku": "MM-01-500g",
                    "product_name": "Moong Master",
                    "category": "Papad",
                    "pack_weight_g": "500",
                    "active": "true",
                },
                {
                    "product_id": "PRD-MM-1000G",
                    "sku": "MM-01-1000g",
                    "product_name": "Moong Master",
                    "category": "Papad",
                    "pack_weight_g": "1000",
                    "active": "true",
                },
            ],
            "RawMaterials": [
                {"raw_material_id": "RAW-01", "material_name": "Moong Dal Flour", "current_stock": 1000.0, "unit": "kg"},
                {"raw_material_id": "RAW-02", "material_name": "Black Pepper", "current_stock": 100.0, "unit": "kg"},
                {"raw_material_id": "RAW-03", "material_name": "Hing", "current_stock": 50.0, "unit": "kg"},
                {"raw_material_id": "RAW-04", "material_name": "Salt", "current_stock": 200.0, "unit": "kg"},
            ],
            "RawMaterialLedger": [],
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
            "SalesmanStockLedger": [],
            "Workers": [
                {"worker_id": "WRK-001", "worker_name": "Sita Devi", "daily_wage": 400.0, "active": "true"},
                {"worker_id": "WRK-002", "worker_name": "Geeta Sharma", "daily_wage": 450.0, "active": "true"},
                {"worker_id": "WRK-003", "worker_name": "Ramu Lal", "daily_wage": 350.0, "active": "false"},
            ],
            "WorkerAttendance": [],
            "ApprovalRequests": [],
            "AuditLog": [],
            "Sales": [],
            "SaleItems": [],
            "Expenses": [],
            "DailyClosings": [],
        }

        self.owner_user = {"user_id": "USR-OWNER-01", "role": "OWNER", "full_name": "Owner Admin"}
        self.pa_user = {"user_id": "USR-PA-01", "role": "PA", "full_name": "PA Manager"}
        self.sales_user = {"user_id": "USR-SALES-01", "role": "SALESMAN", "full_name": "Field Salesman"}

    def test_pa_can_create_batch_as_pending(self):
        req = ProductionCreate(
            product_id="PRD-MOONG-MASTER",
            production_date="2026-10-22",
            quantity_kg=120.0,
            wastage_kg=0.0,
            flour_base_used_kg=100.0,
            notes="Morning batch recorded by PA",
        )
        batch = asyncio.run(create_batch(req, self.pa_user))
        self.assertEqual(batch["status"], "PENDING")
        self.assertEqual(batch["created_by"], "USR-PA-01")
        self.assertEqual(batch["net_quantity_kg"], 120.0)

        # Pending batch must NOT increase available production stock
        ledger = db.memory_store["ProductionStockLedger"]
        self.assertEqual(len(ledger), 0)

    def test_pa_cannot_approve_batch_strictly_owner_only(self):
        req = ProductionCreate(
            product_id="PRD-MOONG-MASTER",
            production_date="2026-10-22",
            quantity_kg=60.0,
            wastage_kg=0.0,
        )
        batch = asyncio.run(create_batch(req, self.pa_user))
        batch_id = batch["production_id"]

        approval_req = ApprovalRequest(approved=True, notes="PA attempting approval")
        with self.assertRaises(Exception) as ctx:
            asyncio.run(approve_batch(batch_id, approval_req, self.pa_user))
        self.assertIn("Only the Owner", str(ctx.exception))

    def test_owner_approval_credits_bulk_stock_and_issues_raw_materials(self):
        req = ProductionCreate(
            product_id="PRD-MOONG-MASTER",
            production_date="2026-10-22",
            quantity_kg=120.0,
            wastage_kg=0.0,
            flour_base_used_kg=100.0,
        )
        batch = asyncio.run(create_batch(req, self.pa_user))
        batch_id = batch["production_id"]

        approval_req = ApprovalRequest(approved=True, notes="Approved by Owner")
        approved_batch = asyncio.run(approve_batch(batch_id, approval_req, self.owner_user))

        self.assertEqual(approved_batch["status"], "APPROVED")
        self.assertEqual(approved_batch["approved_by"], "USR-OWNER-01")

        # Check ProductionStockLedger has BULK_PRODUCED
        prod_ledger = db.memory_store["ProductionStockLedger"]
        bulk_entries = [m for m in prod_ledger if m["movement_type"] == "BULK_PRODUCED" and m["reference_id"] == batch_id]
        self.assertEqual(len(bulk_entries), 1)
        self.assertEqual(bulk_entries[0]["quantity_kg"], 120.0)

        # Check RawMaterialLedger has consumption movements
        raw_ledger = db.memory_store["RawMaterialLedger"]
        consumption_entries = [r for r in raw_ledger if r["production_id"] == batch_id and r["movement_type"] == "PRODUCTION_CONSUMPTION"]
        self.assertGreater(len(consumption_entries), 0)

    def test_salesman_blocked_from_production(self):
        req = ProductionCreate(
            product_id="PRD-MOONG-MASTER",
            production_date="2026-10-22",
            quantity_kg=50.0,
        )
        with self.assertRaises(Exception) as ctx:
            asyncio.run(create_batch(req, self.sales_user))
        self.assertIn("Owner or PA", str(ctx.exception))

    def test_bulk_attendance_marks_multiple_workers_and_calculates_wages(self):
        req = BulkAttendanceCreate(
            attendance_date="2026-10-22",
            records=[
                BulkAttendanceItem(worker_id="WRK-001", status="PRESENT", notes="Shift A"),
                BulkAttendanceItem(worker_id="WRK-002", status="HALF_DAY", notes="Afternoon half"),
                BulkAttendanceItem(worker_id="WRK-003", status="PRESENT", notes="Inactive worker test"),
            ],
        )
        res = asyncio.run(record_bulk_attendance(req, self.pa_user))

        self.assertEqual(res.status, "SUCCESS")
        self.assertEqual(res.saved_count, 2)
        # WRK-003 is inactive so must be skipped
        self.assertEqual(res.skipped_count, 1)
        self.assertEqual(res.skipped_workers[0]["worker_id"], "WRK-003")

        records = db.memory_store["WorkerAttendance"]
        self.assertEqual(len(records), 2)
        r1 = next(r for r in records if r["worker_id"] == "WRK-001")
        r2 = next(r for r in records if r["worker_id"] == "WRK-002")
        self.assertEqual(r1["wage_accrued"], 400.0)
        self.assertEqual(r2["wage_accrued"], 225.0)

    def test_bulk_attendance_prevents_duplicate_for_already_recorded_worker(self):
        # First record single attendance for WRK-001
        single_req = AttendanceCreate(worker_id="WRK-001", attendance_date="2026-10-22", status="PRESENT")
        asyncio.run(record_attendance(single_req, self.pa_user))

        # Now attempt bulk attendance including WRK-001 and WRK-002
        bulk_req = BulkAttendanceCreate(
            attendance_date="2026-10-22",
            records=[
                BulkAttendanceItem(worker_id="WRK-001", status="PRESENT"),
                BulkAttendanceItem(worker_id="WRK-002", status="PRESENT"),
            ],
        )
        res = asyncio.run(record_bulk_attendance(bulk_req, self.pa_user))

        self.assertEqual(res.saved_count, 1)  # Only WRK-002 saved
        self.assertEqual(res.skipped_count, 1)  # WRK-001 skipped
        self.assertEqual(res.skipped_workers[0]["worker_id"], "WRK-001")
        self.assertIn("already recorded", res.skipped_workers[0]["reason"])

        # Total attendance rows in database must be exactly 2
        self.assertEqual(len(db.memory_store["WorkerAttendance"]), 2)

    def test_dashboard_metrics_includes_production_and_attendance(self):
        # Create a pending batch
        from app.timeutil import business_today
        today_date = business_today()
        asyncio.run(create_batch(
            ProductionCreate(
                product_id="PRD-MOONG-MASTER",
                production_date=today_date,
                quantity_kg=120.0,
            ),
            self.pa_user,
        ))

        # Record attendance for 1 worker
        asyncio.run(record_attendance(
            AttendanceCreate(worker_id="WRK-001", attendance_date=today_date, status="PRESENT"),
            self.pa_user,
        ))

        metrics = asyncio.run(get_dashboard_metrics(self.owner_user))
        self.assertIsInstance(metrics, DashboardMetrics)
        self.assertEqual(metrics.pending_production_approvals, 1)
        self.assertEqual(metrics.pending_production_kg, 120.0)
        self.assertEqual(metrics.workers_present_today, 1)
        self.assertEqual(metrics.active_workers_count, 2)


if __name__ == "__main__":
    unittest.main()
