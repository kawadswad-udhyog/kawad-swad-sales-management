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

if "fastapi" not in sys.modules:
    class MockFastAPIModule(types.ModuleType):
        class APIRouter:
            def __init__(self, *args, **kwargs):
                self.routes = []
            def post(self, path="", **kwargs): return lambda f: f
            def get(self, path="", **kwargs): return lambda f: f
            def put(self, path="", **kwargs): return lambda f: f
            def patch(self, path="", **kwargs): return lambda f: f
            def delete(self, path="", **kwargs): return lambda f: f
        class HTTPException(Exception):
            def __init__(self, status_code, detail=None, headers=None):
                super().__init__(detail)
                self.status_code = status_code
                self.detail = detail
                self.headers = headers
        class status:
            HTTP_400_BAD_REQUEST = 400
            HTTP_401_UNAUTHORIZED = 401
            HTTP_403_FORBIDDEN = 403
            HTTP_404_NOT_FOUND = 404
            HTTP_409_CONFLICT = 409
            HTTP_422_UNPROCESSABLE_ENTITY = 422
            HTTP_429_TOO_MANY_REQUESTS = 429
            HTTP_500_INTERNAL_SERVER_ERROR = 500
            HTTP_503_SERVICE_UNAVAILABLE = 503
        class FastAPI:
            def __init__(self, *args, **kwargs): self.middleware = []
            def add_middleware(self, mw, **kwargs): self.middleware.append((mw, kwargs))
            def include_router(self, *args, **kwargs): pass
            def on_event(self, *args, **kwargs): return lambda f: f
            def get(self, *args, **kwargs): return lambda f: f
            def post(self, *args, **kwargs): return lambda f: f
            def put(self, *args, **kwargs): return lambda f: f
            def patch(self, *args, **kwargs): return lambda f: f
            def delete(self, *args, **kwargs): return lambda f: f
        class BackgroundTasks:
            def add_task(self, *args, **kwargs): pass
        @staticmethod
        def Depends(f): return f
        @staticmethod
        def Header(default=None, alias=None): return default
        @staticmethod
        def Query(default=None, **kwargs): return default

    mock_mod = MockFastAPIModule("fastapi")
    mock_mod.FastAPI = MockFastAPIModule.FastAPI
    mock_mod.BackgroundTasks = MockFastAPIModule.BackgroundTasks
    mock_mod.Query = MockFastAPIModule.Query
    mock_mod.APIRouter = MockFastAPIModule.APIRouter
    mock_mod.HTTPException = MockFastAPIModule.HTTPException
    mock_mod.status = MockFastAPIModule.status
    mock_mod.Depends = MockFastAPIModule.Depends
    mock_mod.Header = MockFastAPIModule.Header

    mock_mw = types.ModuleType("fastapi.middleware")
    mock_cors = types.ModuleType("fastapi.middleware.cors")
    mock_cors.CORSMiddleware = object
    sys.modules["fastapi"] = mock_mod
    sys.modules["fastapi.middleware"] = mock_mw
    sys.modules["fastapi.middleware.cors"] = mock_cors

if "pydantic" not in sys.modules:
    class MockBaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
        def dict(self, **kwargs):
            return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}
    mock_pyd = types.ModuleType("pydantic")
    mock_pyd.BaseModel = MockBaseModel
    mock_pyd.Field = lambda *args, **kwargs: kwargs.get("default", args[0] if args else None)
    sys.modules["pydantic"] = mock_pyd

import base64
import json

class SmartMockJWT:
    _token_map = {}
    @classmethod
    def encode(cls, payload, secret, algorithm="HS256"):
        data = dict(payload)
        for k, v in list(data.items()):
            if isinstance(v, datetime):
                data[k] = int(v.timestamp())
        token_str = "tok_" + base64.urlsafe_b64encode(json.dumps(data).encode("utf-8")).decode("utf-8").rstrip("=")
        cls._token_map[token_str] = data
        return token_str

    @classmethod
    def decode(cls, token, secret, algorithms=None):
        if token in cls._token_map:
            return dict(cls._token_map[token])
        try:
            if token.startswith("tok_"):
                raw = token[4:]
                padded = raw + "=" * (-len(raw) % 4)
                return json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
        except Exception:
            pass
        return {"sub": "USR-000001", "role": "SALESMAN"}

if "jwt" not in sys.modules:
    sys.modules["jwt"] = types.ModuleType("jwt")
sys.modules["jwt"].encode = SmartMockJWT.encode
sys.modules["jwt"].decode = SmartMockJWT.decode

if "fastapi.security" not in sys.modules:
    mock_sec = types.ModuleType("fastapi.security")
    mock_sec.HTTPBearer = lambda **kwargs: None
    class MockCredentials:
        def __init__(self, scheme="Bearer", credentials=""):
            self.scheme = scheme
            self.credentials = credentials
    mock_sec.HTTPAuthorizationCredentials = MockCredentials
    sys.modules["fastapi.security"] = mock_sec

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

    def test_record_attendance_success(self):
        req = AttendanceCreate(worker_id="WRK-000001", attendance_date="2026-10-21", status="PRESENT", notes="Full day")
        rec = asyncio.run(record_attendance(req, self.owner_user))
        self.assertEqual(rec["worker_id"], "WRK-000001")
        self.assertEqual(rec["status"], "PRESENT")
        self.assertEqual(rec["wage_accrued"], 400.0)

    def test_record_attendance_duplicate_blocked(self):
        req = AttendanceCreate(worker_id="WRK-000001", attendance_date="2026-10-21", status="PRESENT", notes="Full day")
        asyncio.run(record_attendance(req, self.owner_user))

        # Attempt duplicate on same worker and date
        dup_req = AttendanceCreate(worker_id="WRK-000001", attendance_date="2026-10-21", status="HALF_DAY", notes="Second click")
        with self.assertRaises(Exception) as ctx:
            asyncio.run(record_attendance(dup_req, self.owner_user))
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
        updated = asyncio.run(update_attendance("ATT-000001", update_req, self.owner_user))
        self.assertEqual(updated["status"], "HALF_DAY")
        self.assertEqual(updated["wage_accrued"], 200.0)
        self.assertIn("Corrected by USR-OWNER-01", updated["notes"])

    def test_concurrent_attendance_submission_safety(self):
        req = AttendanceCreate(worker_id="WRK-000001", attendance_date="2026-10-22", status="PRESENT")
        
        results = []
        errors = []

        def worker_task():
            try:
                res = asyncio.run(record_attendance(req, self.owner_user))
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
        res = asyncio.run(delete_duplicate_attendance("ATT-000002", self.owner_user))
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
            asyncio.run(delete_duplicate_attendance("ATT-000001", self.owner_user))
        self.assertIn("Cannot delete unique attendance record", str(ctx.exception))
        # Ensure record was NOT removed
        self.assertEqual(len(db.memory_store["WorkerAttendance"]), 1)

    def test_diagnostic_health_endpoint_schema(self):
        from app.main import health_check
        health = health_check()
        self.assertIn("backend", health)
        self.assertEqual(health["backend"]["status"], "CONNECTED")
        self.assertIn("google_sheets", health)
        self.assertIn("required_sheets", health)

if __name__ == "__main__":
    unittest.main()
