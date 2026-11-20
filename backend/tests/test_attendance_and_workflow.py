import os
import sys
import unittest
import asyncio
import types
from datetime import datetime, timezone
import concurrent.futures

os.environ["SALES_TESTING"] = "1"
os.environ["SALES_JWT_SECRET"] = "test-only-secret-do-not-use-for-deployment-32"

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import tests  # noqa: F401 - standardized hardened stdlib shims
from tests.v2_test_harness import LocalAppsScriptSimulator, make_test_request
from app.sheets import db
from app.routers.production import record_attendance, attendance, update_attendance, delete_duplicate_attendance, AttendanceCreate, AttendanceUpdate

class AttendanceAndWorkflowTestCase(unittest.TestCase):
    def setUp(self):
        db.memory_store["Workers"] = [
            {
                "worker_id": "WRK-000001",
                "worker_name": "Ramesh Kumar",
                "mobile": "9876543210",
                "daily_wage": 400.0,
                "active": "true",
            }
        ]
        db.memory_store["WorkerAttendance"] = []
        db.memory_store["AuditLog"] = []
        self.owner_user = {"user_id": "USR-OWNER-01", "role": "OWNER"}
        self._sim = LocalAppsScriptSimulator().start()

    def tearDown(self):
        self._sim.stop()

    def test_record_attendance_success(self):
        req = AttendanceCreate(worker_id="WRK-000001", attendance_date="2026-10-21", status="PRESENT", notes="Full day")
        rec = asyncio.run(record_attendance(req, user=self.owner_user, request=make_test_request()))
        self.assertEqual(rec["worker_id"], "WRK-000001")
        self.assertEqual(rec["status"], "PRESENT")
        self.assertEqual(rec["wage_accrued"], 400.0)

    def test_record_attendance_duplicate_blocked(self):
        req = AttendanceCreate(worker_id="WRK-000001", attendance_date="2026-10-21", status="PRESENT", notes="Full day")
        asyncio.run(record_attendance(req, user=self.owner_user, request=make_test_request()))

        # Attempt duplicate on same worker and date
        dup_req = AttendanceCreate(worker_id="WRK-000001", attendance_date="2026-10-21", status="HALF_DAY", notes="Second click")
        with self.assertRaises(Exception) as ctx:
            asyncio.run(record_attendance(dup_req, user=self.owner_user, request=make_test_request()))
        self.assertIn("already recorded", str(ctx.exception))

    def test_attendance_duplicate_annotation(self):
        # Seed duplicate rows as if historical sheets had duplicates
        db.memory_store["WorkerAttendance"] = [
            {
                "attendance_id": "ATT-000001",
                "worker_id": "WRK-000001",
                "worker_name_snapshot": "Ramesh Kumar",
                "attendance_date": "2026-10-20",
                "status": "PRESENT",
                "daily_wage_snapshot": 400.0,
                "wage_accrued": 400.0,
            },
            {
                "attendance_id": "ATT-000002",
                "worker_id": "WRK-000001",
                "worker_name_snapshot": "Ramesh Kumar",
                "attendance_date": "2026-10-20",
                "status": "PRESENT",
                "daily_wage_snapshot": 400.0,
                "wage_accrued": 400.0,
            },
        ]
        res = asyncio.run(attendance(self.owner_user))
        self.assertEqual(len(res), 2)
        self.assertTrue(res[0]["is_duplicate"])
        self.assertTrue(res[1]["is_duplicate"])

    def test_attendance_correction_endpoint(self):
        db.memory_store["WorkerAttendance"] = [
            {
                "attendance_id": "ATT-000001",
                "worker_id": "WRK-000001",
                "worker_name_snapshot": "Ramesh Kumar",
                "attendance_date": "2026-10-20",
                "status": "ABSENT",
                "daily_wage_snapshot": 400.0,
                "wage_accrued": 0.0,
                "notes": "Reported absent by supervisor",
            }
        ]
        update_req = AttendanceUpdate(status="HALF_DAY", notes="Worker came for second half - verified")
        updated = asyncio.run(update_attendance("ATT-000001", update_req, user=self.owner_user, request=make_test_request()))
        self.assertEqual(updated["status"], "HALF_DAY")
        self.assertEqual(updated["wage_accrued"], 200.0)
        self.assertIn("Corrected by USR-OWNER-01", updated["notes"])

    def test_concurrent_attendance_submission_safety(self):
        req = AttendanceCreate(worker_id="WRK-000001", attendance_date="2026-10-22", status="PRESENT")
        
        results = []
        errors = []

        def worker_task():
            try:
                res = asyncio.run(record_attendance(req, user=self.owner_user, request=make_test_request()))
                results.append(res)
            except Exception as e:
                errors.append(e)

        threads = [concurrent.futures.ThreadPoolExecutor().submit(worker_task) for _ in range(5)]
        for t in threads:
            t.result()

        # Exactly one request must succeed, and four must be rejected
        self.assertEqual(len(results), 1)
        self.assertEqual(len(errors), 4)
        for err in errors:
            self.assertIn("already recorded", str(err))

    def test_delete_duplicate_attendance_success(self):
        db.memory_store["WorkerAttendance"] = [
            {
                "attendance_id": "ATT-000001",
                "worker_id": "WRK-000001",
                "worker_name_snapshot": "Ramesh Kumar",
                "attendance_date": "2026-10-20",
                "status": "PRESENT",
                "daily_wage_snapshot": 400.0,
                "wage_accrued": 400.0,
            },
            {
                "attendance_id": "ATT-000002",
                "worker_id": "WRK-000001",
                "worker_name_snapshot": "Ramesh Kumar",
                "attendance_date": "2026-10-20",
                "status": "PRESENT",
                "daily_wage_snapshot": 400.0,
                "wage_accrued": 400.0,
            },
        ]
        res = asyncio.run(delete_duplicate_attendance("ATT-000002", user=self.owner_user, request=make_test_request()))
        self.assertEqual(res["status"], "DELETED")
        self.assertEqual(res["attendance_id"], "ATT-000002")
        remaining = db.memory_store["WorkerAttendance"]
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["attendance_id"], "ATT-000001")

    def test_delete_duplicate_attendance_blocks_unique_record(self):
        db.memory_store["WorkerAttendance"] = [
            {
                "attendance_id": "ATT-000001",
                "worker_id": "WRK-000001",
                "worker_name_snapshot": "Ramesh Kumar",
                "attendance_date": "2026-10-20",
                "status": "PRESENT",
                "daily_wage_snapshot": 400.0,
                "wage_accrued": 400.0,
            }
        ]
        with self.assertRaises(Exception) as ctx:
            asyncio.run(delete_duplicate_attendance("ATT-000001", user=self.owner_user, request=make_test_request()))
        self.assertIn("Cannot delete unique attendance record", str(ctx.exception))
        # Ensure record was NOT removed
        self.assertEqual(len(db.memory_store["WorkerAttendance"]), 1)

    def test_diagnostic_health_endpoint_schema(self):
        from app.main import health_check, health_details
        health = health_check()
        self.assertIn("backend", health)
        self.assertEqual(health["backend"]["status"], "CONNECTED")
        self.assertIn("google_sheets_connected", health)
        self.assertIn("persistent_writes_enabled", health)
        self.assertNotIn("spreadsheet_id_configured", health)
        self.assertNotIn("service_account_configured", health)
        self.assertNotIn("last_connection_error", health)

        details = health_details(current_user=self.owner_user)
        self.assertIn("google_sheets", details)
        self.assertIn("required_sheets", details)
        self.assertIn("spreadsheet_id_configured", details)
        self.assertIn("service_account_configured", details)

if __name__ == "__main__":
    unittest.main()
