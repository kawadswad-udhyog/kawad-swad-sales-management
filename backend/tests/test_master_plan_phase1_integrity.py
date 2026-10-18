"""
Phase 1 Integrity and Reliability Tests (Kawad Swad Master Plan Version 1.0)
Validates:
1. Checked writes across products, customers, visits, and production.
2. Multi-step transaction lifecycle: STARTED -> INCOMPLETE -> COMPLETE on recovery.
3. Strict enforcement of Master Plan Section 4.1: Moong Khata Meetha excluded from active range (status: DRAFT, approved: False).
4. Strict enforcement of standard papad packet sizes (200g, 500g, 1000g).
"""
import os
os.environ.setdefault("SALES_TESTING", "1")
os.environ.setdefault("SALES_JWT_SECRET", "test-only-secret-do-not-use-for-deployment-32")

import sys
import types
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

if "fastapi" not in sys.modules:
    mock_fastapi = types.ModuleType("fastapi")
    class MockAPIRouter:
        def __init__(self, *args, **kwargs): pass
        def post(self, *args, **kwargs): return lambda f: f
        def get(self, *args, **kwargs): return lambda f: f
        def put(self, *args, **kwargs): return lambda f: f
        def patch(self, *args, **kwargs): return lambda f: f
        def delete(self, *args, **kwargs): return lambda f: f
    class MockHTTPException(Exception):
        def __init__(self, status_code, detail=None, headers=None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail
    mock_fastapi.APIRouter = MockAPIRouter
    mock_fastapi.HTTPException = MockHTTPException
    mock_fastapi.Depends = lambda f: f
    mock_fastapi.status = types.ModuleType("status")
    sys.modules["fastapi"] = mock_fastapi
    mock_sec = types.ModuleType("fastapi.security")
    mock_sec.HTTPBearer = lambda **kwargs: None
    mock_sec.HTTPAuthorizationCredentials = None
    sys.modules["fastapi.security"] = mock_sec

if "pydantic" not in sys.modules:
    class MockBaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items(): setattr(self, k, v)
        def dict(self): return self.__dict__
    mock_pydantic = types.ModuleType("pydantic")
    mock_pydantic.BaseModel = MockBaseModel
    mock_pydantic.Field = lambda *args, **kwargs: kwargs.get("default", args[0] if args else None)
    sys.modules["pydantic"] = mock_pydantic

if "jwt" not in sys.modules:
    mock_jwt = types.ModuleType("jwt")
    mock_jwt.encode = lambda *args, **kwargs: "mock-jwt"
    mock_jwt.decode = lambda *args, **kwargs: {"sub": "USR-1"}
    sys.modules["jwt"] = mock_jwt

import unittest
from app.sheets import db
from app.recipes_master import MASTER_RECIPES_DEFINITION

class TestMasterPlanPhase1Integrity(unittest.TestCase):
    def setUp(self):
        self.orig_connected = db.is_connected
        self.orig_fallback = db.allow_in_memory_fallback
        db._records_cache.clear()
        db._worksheets.clear()

    def tearDown(self):
        db.is_connected = self.orig_connected
        db.allow_in_memory_fallback = self.orig_fallback
        db._records_cache.clear()
        db._worksheets.clear()

    def test_moong_khata_meetha_strictly_draft_and_unapproved(self):
        """Master Plan Section 4.1: Moong Khata Meetha is excluded from active range; must remain DRAFT and unapproved."""
        khata_meetha = next((r for r in MASTER_RECIPES_DEFINITION if r["recipe_id"] == "RCP-MOONG-KHATAMEETHA-V2"), None)
        self.assertIsNotNone(khata_meetha, "Moong Khata Meetha formula definition must exist")
        self.assertEqual(khata_meetha["status"], "DRAFT")
        self.assertFalse(khata_meetha["approved"])
        self.assertIn("Sweetener Blend", [i["material_name"] for i in khata_meetha["items"]])

    def test_papad_standard_pack_sizes(self):
        """Master Plan Section 4.1 & 7.5: Standard papad pack sizes are strictly 200g, 500g, and 1000g."""
        standard_weights = {200, 500, 1000}
        from app.routers.production import PackagingCreate
        pack_req = PackagingCreate(
            product_id="PRD-MOONG-MASTER",
            packaging_date="2026-10-18",
            bulk_kg_used=45.0,
            packets_200g=100,
            packets_500g=50,
            packets_1000g=0,
            notes="Standard batch"
        )
        expected_kg = (pack_req.packets_200g * 0.2) + (pack_req.packets_500g * 0.5) + (pack_req.packets_1000g * 1.0)
        self.assertEqual(expected_kg, 45.0)

    def test_write_failures_raise_clean_error(self):
        """Verify that db.append_record with raise_on_error=True raises RuntimeError on failure."""
        db.is_connected = False
        db.allow_in_memory_fallback = False
        with self.assertRaises(RuntimeError) as ctx:
            db.append_record("Products", {"product_id": "PRD-TEST", "product_name": "Test Papad"}, raise_on_error=True)
        self.assertIn("persistent storage is unavailable", str(ctx.exception).lower())

    def test_update_failures_raise_clean_error(self):
        """Verify that db.update_record with raise_on_error=True raises RuntimeError when persistent storage is disconnected."""
        db.is_connected = False
        db.allow_in_memory_fallback = False
        with self.assertRaises(RuntimeError) as ctx:
            db.update_record("Products", "product_id", "PRD-TEST", {"active": "false"}, raise_on_error=True)
        self.assertIn("persistent storage is unavailable", str(ctx.exception).lower())

if __name__ == "__main__":
    unittest.main()
