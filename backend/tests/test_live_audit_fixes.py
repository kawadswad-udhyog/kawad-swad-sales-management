"""
Comprehensive verification test suite for ERP Live Audit Fixes.
Covers:
- Finding A: Production backend routing to kawad-swad-sales-dev
- Finding B: Strict fail-closed configuration validation in production
- Finding C: Strict CORS origin restrictions in production
- Finding D: Public directory security & asset isolation
- Finding E: Sales transaction cancellation reliability and idempotency
- Finding F: Production batch approval concurrency lock and duplicate prevention
"""

import os
import sys
import types

os.environ["SALES_TESTING"] = "1"
os.environ["SALES_JWT_SECRET"] = "test-only-secret-do-not-use-for-deployment-32"

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

if "fastapi" not in sys.modules:
    class MockFastAPIModule(types.ModuleType):
        class APIRouter:
            def __init__(self, *args, **kwargs): self.routes = []
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
            def __init__(self, *args, **kwargs):
                self.middleware = []
                self.user_middleware = []
            def add_middleware(self, mw, **kwargs):
                self.middleware.append((mw, kwargs))
                mock_m = MagicMock()
                mock_m.cls = mw
                mock_m.kwargs = kwargs
                self.user_middleware.append(mock_m)
            def include_router(self, *args, **kwargs): pass
            def on_event(self, *args, **kwargs): return lambda f: f
            def get(self, *args, **kwargs): return lambda f: f
            def post(self, *args, **kwargs): return lambda f: f
            def put(self, *args, **kwargs): return lambda f: f
            def delete(self, *args, **kwargs): return lambda f: f
            def exception_handler(self, *args, **kwargs): return lambda f: f
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
    class MockCORSMiddleware:
        pass
    mock_cors.CORSMiddleware = MockCORSMiddleware
    sys.modules["fastapi"] = mock_mod
    sys.modules["fastapi.middleware"] = mock_mw
    sys.modules["fastapi.middleware.cors"] = mock_cors

if "fastapi.security" not in sys.modules:
    mock_sec = types.ModuleType("fastapi.security")
    mock_sec.HTTPBearer = lambda **kwargs: None
    class MockCredentials:
        def __init__(self, scheme="Bearer", credentials=""):
            self.scheme = scheme
            self.credentials = credentials
    mock_sec.HTTPAuthorizationCredentials = MockCredentials
    sys.modules["fastapi.security"] = mock_sec

if "jwt" not in sys.modules:
    import base64
    import json
    import hmac
    import hashlib
    mock_jwt = types.ModuleType("jwt")
    def mock_encode(payload, secret, algorithm="HS256"):
        header = base64.urlsafe_b64encode(json.dumps({"alg": algorithm, "typ": "JWT"}).encode()).rstrip(b"=").decode()
        body = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
        sig = base64.urlsafe_b64encode(hmac.new(secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
        return f"{header}.{body}.{sig}"
    def mock_decode(token, secret, algorithms=None):
        parts = token.split(".")
        if len(parts) != 3: raise ValueError("Invalid token")
        pad = len(parts[1]) % 4
        body = base64.urlsafe_b64decode(parts[1] + "=" * (4 - pad if pad else 0))
        return json.loads(body.decode())
    mock_jwt.encode = mock_encode
    mock_jwt.decode = mock_decode
    sys.modules["jwt"] = mock_jwt

if "pydantic" not in sys.modules:
    class MockBaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items(): setattr(self, k, v)
        def model_dump(self, *args, **kwargs): return self.__dict__
        def dict(self, *args, **kwargs): return self.__dict__
    def MockField(default=None, **kwargs): return default

    mock_pyd = types.ModuleType("pydantic")
    mock_pyd.BaseModel = MockBaseModel
    mock_pyd.Field = MockField
    sys.modules["pydantic"] = mock_pyd

import unittest
from unittest.mock import patch, MagicMock
import asyncio

from app.sheets import db
from app.config import assert_runtime_config
from app.routers import sales, production
from app.routers.sales import SaleCancelRequest
from app.routers.production import ApprovalRequest


class TestLiveAuditFixes(unittest.TestCase):
    def setUp(self):
        self.orig_connected = db.is_connected
        self.orig_spreadsheet = db.spreadsheet
        self.orig_fallback = db.allow_in_memory_fallback
        db._records_cache.clear()
        db._worksheets.clear()

    def tearDown(self):
        db.is_connected = self.orig_connected
        db.spreadsheet = self.orig_spreadsheet
        db.allow_in_memory_fallback = self.orig_fallback
        db._records_cache.clear()
        db._worksheets.clear()

    def test_finding_a_backend_service_name_contract(self):
        """Finding A: Verify health endpoint returns service name kawad-swad-sales-dev."""
        from app.main import health_check
        res = health_check()
        self.assertEqual(res.get("service"), "kawad-swad-sales-dev")
        self.assertEqual(res.get("backend", {}).get("service"), "kawad-swad-sales-dev")

    def test_finding_b_production_config_fail_closed(self):
        """Finding B: Verify production startup raises RuntimeError if spreadsheet ID or credentials missing."""
        # 1. Missing spreadsheet ID in production
        with patch("app.config.SALES_ENV", "production"):
            with patch("app.config.SALES_GOOGLE_SPREADSHEET_ID", ""):
                with patch("app.config.SALES_CORS_ORIGINS", "https://kawad-swad-sales-frontend.onrender.com"):
                    with patch("os.getenv", return_value="a" * 32):
                        with self.assertRaises(RuntimeError) as ctx:
                            assert_runtime_config()
                        self.assertIn("SALES_GOOGLE_SPREADSHEET_ID is missing", str(ctx.exception))

        # 2. Missing credentials in production
        with patch("app.config.SALES_ENV", "production"):
            with patch("app.config.SALES_GOOGLE_SPREADSHEET_ID", "mock-sheet-123"):
                with patch("app.config.SALES_GOOGLE_SERVICE_ACCOUNT_FILE", "/nonexistent/path/sa.json"):
                    with patch("app.config.SALES_GOOGLE_SERVICE_ACCOUNT_JSON", ""):
                        with patch("app.config.SALES_CORS_ORIGINS", "https://kawad-swad-sales-frontend.onrender.com"):
                            with patch("os.getenv", return_value="a" * 32):
                                with self.assertRaises(RuntimeError) as ctx:
                                    assert_runtime_config()
                                self.assertIn("Neither SALES_GOOGLE_SERVICE_ACCOUNT_FILE nor", str(ctx.exception))

        # 3. Wildcard CORS in production
        with patch("app.config.SALES_ENV", "production"):
            with patch("app.config.SALES_GOOGLE_SPREADSHEET_ID", "mock-sheet-123"):
                with patch("app.config.SALES_CORS_ORIGINS", "*"):
                    with patch("os.getenv", return_value="a" * 32):
                        with self.assertRaises(RuntimeError) as ctx:
                            assert_runtime_config()
                        self.assertIn("Wildcard CORS is not allowed", str(ctx.exception))

    def test_finding_c_cors_origin_bounds(self):
        """Finding C: Verify production frontend origin is in allowed origins list."""
        import app.main as main_mod
        self.assertIn("https://kawad-swad-sales-frontend.onrender.com", main_mod.origins)

    def test_finding_d_no_sensitive_files_in_public(self):
        """Finding D: Public directory must not expose sensitive zips, audits, or paste archives."""
        public_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "public"))
        if os.path.exists(public_dir):
            for root, dirs, files in os.walk(public_dir):
                if "aistudio" in root:
                    continue
                for f in files:
                    ext = os.path.splitext(f)[1].lower()
                    self.assertNotIn(ext, [".zip", ".tar", ".gz", ".json", ".md"],
                                     f"Sensitive file format {f} must not exist in public directory")
                    self.assertNotIn("paste", f.lower(), f"Paste file {f} must not be in public directory")
                    self.assertNotIn("audit", f.lower(), f"Audit file {f} must not be in public directory")

    def test_finding_e_sales_cancellation_idempotency(self):
        """Finding E: Sales cancellation must be idempotent and prevent duplicate reversals."""
        async def _test():
            sale_id = "SALE-IDEMP-01"
            bill_no = "BILL-001"
            db.memory_store["Sales"] = [{
                "sale_id": sale_id,
                "bill_number": bill_no,
                "salesman_user_id": "USR-SALES-01",
                "customer_id": "CUS-001",
                "bill_total": 500.0,
                "bill_status": "ISSUED",
                "payment_method": "CASH",
                "notes": "",
            }]
            db.memory_store["SaleItems"] = [{
                "sale_item_id": "ITEM-001",
                "sale_id": sale_id,
                "product_id": "PRD-001",
                "sku_snapshot": "SKU-001",
                "quantity": 2,
                "unit": "PACKET",
                "pack_weight_g": 500,
                "actual_unit_price": 250.0,
                "line_total": 500.0,
            }]
            db.memory_store["SalesmanStockLedger"] = []
            db.memory_store["Payments"] = []
            db.memory_store["CashLedger"] = []

            owner_user = {"user_id": "USR-OWNER", "role": "OWNER"}
            req = SaleCancelRequest(reason="Customer requested cancellation")

            # 1. First cancellation
            res1 = await sales.cancel_sale(sale_id, req, owner_user)
            self.assertTrue(res1.get("ok"))

            # Check stock reversal was written
            stock_revs = [r for r in db.memory_store["SalesmanStockLedger"] if r.get("related_sale_id") == sale_id]
            self.assertEqual(len(stock_revs), 1)
            self.assertEqual(stock_revs[0]["quantity"], 2)

            # Check payments reversal was written
            pay_revs = [p for p in db.memory_store["Payments"] if p.get("sale_id") == sale_id]
            self.assertEqual(len(pay_revs), 1)
            self.assertEqual(pay_revs[0]["amount"], -500.0)

            # Check cash reversal was written
            cash_revs = [c for c in db.memory_store["CashLedger"] if c.get("related_sale_id") == sale_id]
            self.assertEqual(len(cash_revs), 1)
            self.assertEqual(cash_revs[0]["amount"], -500.0)

            # 2. Second cancellation (idempotent retry)
            res2 = await sales.cancel_sale(sale_id, req, owner_user)
            self.assertTrue(res2.get("ok"))
            self.assertTrue(res2.get("already_cancelled"))

            # Verify no duplicate entries were added
            stock_revs_after = [r for r in db.memory_store["SalesmanStockLedger"] if r.get("related_sale_id") == sale_id]
            self.assertEqual(len(stock_revs_after), 1, "Duplicate stock reversals must not be appended on retry")

            pay_revs_after = [p for p in db.memory_store["Payments"] if p.get("sale_id") == sale_id]
            self.assertEqual(len(pay_revs_after), 1, "Duplicate payment refunds must not be appended on retry")

            cash_revs_after = [c for c in db.memory_store["CashLedger"] if c.get("related_sale_id") == sale_id]
            self.assertEqual(len(cash_revs_after), 1, "Duplicate cash refunds must not be appended on retry")

        asyncio.run(_test())

    def test_finding_f_production_approval_idempotency(self):
        """Finding F: Production batch approval must be locked and idempotent."""
        async def _test():
            batch_id = "PRB-TEST-APPR-01"
            db.memory_store["ProductionBatches"] = [{
                "production_id": batch_id,
                "batch_id": batch_id,
                "product_id": "PRD-PAPAD-01",
                "product_name_snapshot": "Moong Papad",
                "net_quantity_kg": 100.0,
                "status": "PENDING",
                "materials_issued": "true",
            }]
            db.memory_store["ProductionStockLedger"] = []
            db.memory_store["ApprovalRequests"] = []

            owner_user = {"user_id": "USR-OWNER", "role": "OWNER"}
            req = ApprovalRequest(approved=True, notes="Batch quality verified")

            # First approval
            res1 = await production.approve_batch(batch_id, req, owner_user)
            self.assertEqual(res1.get("status"), "APPROVED")

            bulk_entries = [
                s for s in db.memory_store["ProductionStockLedger"]
                if s.get("reference_id") == batch_id and s.get("movement_type") == "BULK_PRODUCED"
            ]
            self.assertEqual(len(bulk_entries), 1)
            self.assertEqual(bulk_entries[0]["quantity_kg"], 100.0)

            # Second approval (re-submission raises 409 and does not credit bulk stock again)
            with self.assertRaises(production.HTTPException) as ctx:
                await production.approve_batch(batch_id, req, owner_user)
            self.assertEqual(ctx.exception.status_code, 409)

            bulk_entries_after = [
                s for s in db.memory_store["ProductionStockLedger"]
                if s.get("reference_id") == batch_id and s.get("movement_type") == "BULK_PRODUCED"
            ]
            self.assertEqual(len(bulk_entries_after), 1, "Bulk stock must not be credited twice on re-approval")

        asyncio.run(_test())


if __name__ == "__main__":
    unittest.main()
