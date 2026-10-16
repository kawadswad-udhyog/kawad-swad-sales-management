#!/usr/bin/env python3
"""
Comprehensive automated test suite for initial OWNER setup endpoint.
Covers:
- Missing server secret (fail closed 503)
- Missing request header (401)
- Wrong secret (403)
- Field validations (username, full name, password length & complexity)
- Successful initial setup (Users + AuthUsers + AuditLog)
- Subsequent call rejection when OWNER exists (409)
- Existing OWNER rejection from Users or AuthUsers tab (409)
- Duplicate username rejection (409)
- Concurrency test (asyncio lock ensures exactly one winner)
- Partial write failure and automatic Users record rollback (500)
"""

import sys
import types
import os
import unittest
import asyncio

# Setup mocks for FastAPI/Pydantic/JWT dependencies if not present in environment
if "fastapi" not in sys.modules:
    class MockFastAPIModule(types.ModuleType):
        class APIRouter:
            def __init__(self, *args, **kwargs): pass
            def post(self, *args, **kwargs): return lambda f: f
            def get(self, *args, **kwargs): return lambda f: f
        class HTTPException(Exception):
            def __init__(self, status_code, detail=None, headers=None):
                super().__init__(detail)
                self.status_code = status_code
                self.detail = detail
                self.headers = headers
        class status:
            HTTP_401_UNAUTHORIZED = 401
            HTTP_403_FORBIDDEN = 403
            HTTP_409_CONFLICT = 409
            HTTP_422_UNPROCESSABLE_ENTITY = 422
            HTTP_500_INTERNAL_SERVER_ERROR = 500
            HTTP_503_SERVICE_UNAVAILABLE = 503
        @staticmethod
        def Depends(f): return f
        @staticmethod
        def Header(default=None, alias=None): return default

    sys.modules["fastapi"] = MockFastAPIModule("fastapi")
    sys.modules["fastapi.security"] = types.ModuleType("security")
    sys.modules["fastapi.security"].HTTPBearer = lambda **kwargs: None
    sys.modules["fastapi.security"].HTTPAuthorizationCredentials = None
    sys.modules["jwt"] = types.ModuleType("jwt")
    sys.modules["jwt"].encode = lambda payload, secret, algorithm="HS256": "mock-jwt-token"
    sys.modules["jwt"].decode = lambda token, secret, algorithms=["HS256"]: {"sub": "USR-000001", "role": "OWNER"}

    class MockBaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
        def dict(self):
            return self.__dict__

    sys.modules["pydantic"] = types.ModuleType("pydantic")
    sys.modules["pydantic"].BaseModel = MockBaseModel
    sys.modules["pydantic"].Field = lambda *args, **kwargs: kwargs.get("default", args[0] if args else None)

# Add backend directory to sys.path
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import app.config as config
import app.sheets as sheets
from app.sheets import db
from app.models import OwnerSetupRequest, LoginRequest
import app.routers.auth as auth_router
from app.auth import verify_password


class TestOwnerSetup(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        # Reset in-memory database store
        db.memory_store["AuthUsers"] = []
        db.memory_store["Users"] = []
        db.memory_store["AuditLog"] = []
        # Default test setup secret
        self.test_secret = "kawad-swad-super-secret-setup-key-2026"
        config.SALES_OWNER_SETUP_SECRET = self.test_secret
        auth_router.SALES_OWNER_SETUP_SECRET = self.test_secret

    def tearDown(self):
        db.memory_store["AuthUsers"] = []
        db.memory_store["Users"] = []
        db.memory_store["AuditLog"] = []

    async def test_01_missing_server_secret_fails_closed(self):
        """Server fails closed (HTTP 503) if SALES_OWNER_SETUP_SECRET is not configured."""
        config.SALES_OWNER_SETUP_SECRET = ""
        auth_router.SALES_OWNER_SETUP_SECRET = ""

        req = OwnerSetupRequest(
            username="ankit_owner",
            full_name="Ankit Kumar",
            password="StrongPassword2026!#",
        )
        with self.assertRaises(auth_router.HTTPException) as ctx:
            await auth_router.setup_owner(req, x_setup_secret=self.test_secret)

        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("disabled or unconfigured", ctx.exception.detail)

    async def test_02_missing_request_secret_header(self):
        """Request fails with HTTP 401 if X-Setup-Secret header is omitted."""
        req = OwnerSetupRequest(
            username="ankit_owner",
            full_name="Ankit Kumar",
            password="StrongPassword2026!#",
        )
        with self.assertRaises(auth_router.HTTPException) as ctx:
            await auth_router.setup_owner(req, x_setup_secret=None)

        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("Missing required setup secret header", ctx.exception.detail)

    async def test_03_wrong_secret_header(self):
        """Request fails with HTTP 403 if invalid setup secret is provided."""
        req = OwnerSetupRequest(
            username="ankit_owner",
            full_name="Ankit Kumar",
            password="StrongPassword2026!#",
        )
        with self.assertRaises(auth_router.HTTPException) as ctx:
            await auth_router.setup_owner(req, x_setup_secret="incorrect-secret-value")

        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("Invalid setup secret", ctx.exception.detail)

    async def test_04_field_validation_weak_password(self):
        """Request fails with HTTP 422 if password is less than 12 chars or lacks complexity."""
        # Under 12 characters
        req_short = OwnerSetupRequest(
            username="ankit_owner",
            full_name="Ankit Kumar",
            password="Short1!",
        )
        with self.assertRaises(auth_router.HTTPException) as ctx:
            await auth_router.setup_owner(req_short, x_setup_secret=self.test_secret)
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertIn("at least 12 characters", ctx.exception.detail)

        # 12+ chars but no digits/specials
        req_simple = OwnerSetupRequest(
            username="ankit_owner",
            full_name="Ankit Kumar",
            password="alllowercaseletters",
        )
        with self.assertRaises(auth_router.HTTPException) as ctx2:
            await auth_router.setup_owner(req_simple, x_setup_secret=self.test_secret)
        self.assertEqual(ctx2.exception.status_code, 422)

    async def test_05_field_validation_invalid_username(self):
        """Request fails with HTTP 422 if username contains invalid characters or is too short."""
        req_invalid = OwnerSetupRequest(
            username="ankit space",
            full_name="Ankit Kumar",
            password="StrongPassword2026!#",
        )
        with self.assertRaises(auth_router.HTTPException) as ctx:
            await auth_router.setup_owner(req_invalid, x_setup_secret=self.test_secret)
        self.assertEqual(ctx.exception.status_code, 422)

    async def test_06_successful_owner_setup_and_login(self):
        """Successful setup writes Users, AuthUsers, AuditLog, and allows immediate login."""
        raw_password = "CorrectHorseBatteryStaple2026!#"
        req = OwnerSetupRequest(
            username="ankit_owner",
            full_name="Ankit Kumar",
            password=raw_password,
        )

        res = await auth_router.setup_owner(req, x_setup_secret=self.test_secret)

        self.assertTrue(res.success)
        self.assertEqual(res.role, "OWNER")
        self.assertEqual(res.username, "ankit_owner")
        self.assertEqual(res.full_name, "Ankit Kumar")
        self.assertTrue(res.user_id.startswith("USR-"))

        # Verify Users tab record
        users = db.get_records("Users")
        self.assertEqual(len(users), 1)
        self.assertEqual(users[0]["role"], "OWNER")
        self.assertEqual(users[0]["user_id"], res.user_id)
        self.assertEqual(users[0]["active"], "true")

        # Verify AuthUsers tab record
        auths = db.get_records("AuthUsers")
        self.assertEqual(len(auths), 1)
        self.assertEqual(auths[0]["username"], "ankit_owner")
        self.assertEqual(auths[0]["role"], "OWNER")
        self.assertEqual(auths[0]["user_id"], res.user_id)
        # Verify password is encrypted with PBKDF2-SHA256, never plaintext
        self.assertNotEqual(auths[0]["password_hash"], raw_password)
        self.assertTrue(auths[0]["password_hash"].startswith("pbkdf2:sha256"))
        self.assertTrue(verify_password(raw_password, auths[0]["password_hash"]))

        # Verify AuditLog record (does not contain plaintext password or secret)
        audit_logs = db.get_records("AuditLog")
        self.assertEqual(len(audit_logs), 1)
        self.assertEqual(audit_logs[0]["action"], "BOOTSTRAP_OWNER_CREATED")
        self.assertNotIn(raw_password, str(audit_logs[0]))
        self.assertNotIn(self.test_secret, str(audit_logs[0]))

        # Verify login now succeeds with these credentials
        login_res = await auth_router.login(
            LoginRequest(username="ankit_owner", password=raw_password)
        )
        self.assertEqual(login_res.role, "OWNER")
        self.assertEqual(login_res.user_id, res.user_id)

    async def test_07_subsequent_setup_rejected_when_owner_exists(self):
        """Subsequent setup requests fail with HTTP 409 once an OWNER exists."""
        req1 = OwnerSetupRequest(
            username="owner_one",
            full_name="First Owner",
            password="StrongPassword2026!#",
        )
        await auth_router.setup_owner(req1, x_setup_secret=self.test_secret)

        # Attempt to run setup again
        req2 = OwnerSetupRequest(
            username="owner_two",
            full_name="Second Owner",
            password="AnotherStrongPassword2026!#",
        )
        with self.assertRaises(auth_router.HTTPException) as ctx:
            await auth_router.setup_owner(req2, x_setup_secret=self.test_secret)

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("already exists", ctx.exception.detail)

    async def test_08_duplicate_username_rejected(self):
        """Duplicate username is rejected even if no OWNER exists yet."""
        # Pre-seed a non-owner salesman in AuthUsers
        db.memory_store["AuthUsers"].append({
            "auth_id": "AUTH-000001",
            "user_id": "USR-000001",
            "username": "existing_salesman",
            "password_hash": "hash",
            "role": "SALESMAN",
            "active": "true",
        })

        req = OwnerSetupRequest(
            username="existing_salesman",
            full_name="Ankit Kumar",
            password="StrongPassword2026!#",
        )
        with self.assertRaises(auth_router.HTTPException) as ctx:
            await auth_router.setup_owner(req, x_setup_secret=self.test_secret)

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("already in use", ctx.exception.detail)
        # Ensure Users tab was not modified
        self.assertEqual(len(db.get_records("Users")), 0)

    async def test_09_concurrency_protection(self):
        """Simultaneous concurrent setup requests result in exactly one successful creation."""
        req1 = OwnerSetupRequest(
            username="owner_alpha",
            full_name="Alpha Owner",
            password="AlphaPassword2026!#",
        )
        req2 = OwnerSetupRequest(
            username="owner_beta",
            full_name="Beta Owner",
            password="BetaPassword2026!#",
        )
        req3 = OwnerSetupRequest(
            username="owner_gamma",
            full_name="Gamma Owner",
            password="GammaPassword2026!#",
        )

        results = await asyncio.gather(
            auth_router.setup_owner(req1, x_setup_secret=self.test_secret),
            auth_router.setup_owner(req2, x_setup_secret=self.test_secret),
            auth_router.setup_owner(req3, x_setup_secret=self.test_secret),
            return_exceptions=True,
        )

        successes = [r for r in results if not isinstance(r, Exception)]
        failures = [r for r in results if isinstance(r, Exception)]

        # Exactly 1 success, 2 failures with 409 Conflict
        self.assertEqual(len(successes), 1)
        self.assertEqual(len(failures), 2)
        for f in failures:
            self.assertEqual(f.status_code, 409)

        # Database must only have exactly 1 OWNER
        self.assertEqual(len(db.get_records("Users")), 1)
        self.assertEqual(len(db.get_records("AuthUsers")), 1)

    async def test_10_partial_write_failure_triggers_rollback(self):
        """If AuthUsers write fails after Users write, rollback deletes the orphaned Users record."""
        # Monkey-patch append_record to fail only when tab_name is AuthUsers
        original_append = db.append_record

        def failing_append(tab_name, record, raise_on_error=False):
            if tab_name == "AuthUsers":
                raise RuntimeError("Simulated Google Sheets timeout/quota error writing AuthUsers!")
            return original_append(tab_name, record, raise_on_error=raise_on_error)

        db.append_record = failing_append

        req = OwnerSetupRequest(
            username="owner_partial",
            full_name="Partial Owner",
            password="StrongPassword2026!#",
        )

        with self.assertRaises(auth_router.HTTPException) as ctx:
            await auth_router.setup_owner(req, x_setup_secret=self.test_secret)

        self.assertEqual(ctx.exception.status_code, 500)
        self.assertIn("Rollback of Users was completed successfully", ctx.exception.detail)

        # Restore original append
        db.append_record = original_append

        # Verify rollback worked: Users tab must NOT have the orphaned record
        users = db.get_records("Users")
        self.assertEqual(len(users), 0)
        auths = db.get_records("AuthUsers")
        self.assertEqual(len(auths), 0)


if __name__ == "__main__":
    unittest.main()
