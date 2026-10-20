import os
import sys
import unittest
import asyncio
import types
import json
from datetime import datetime, timezone

# Configure testing environment
os.environ["SALES_TESTING"] = "1"
os.environ["SALES_JWT_SECRET"] = "test-only-secret-do-not-use-for-deployment-32"

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# Mock fastapi & pydantic if running in test environment without installed packages
class MockCredentials:
    def __init__(self, scheme="Bearer", credentials=""):
        self.scheme = scheme
        self.credentials = credentials

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

if "fastapi.security" not in sys.modules:
    mock_sec = types.ModuleType("fastapi.security")
    mock_sec.HTTPBearer = lambda **kwargs: None
    mock_sec.HTTPAuthorizationCredentials = MockCredentials
    sys.modules["fastapi.security"] = mock_sec
else:
    sys.modules["fastapi.security"].HTTPAuthorizationCredentials = MockCredentials

HTTPAuthorizationCredentials = MockCredentials

import base64

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

from fastapi import HTTPException

from app.sheets import db
from app.auth import hash_password, create_access_token, get_current_user, _REVOKED_TOKENS, _USER_REVOKED_AT
from app.models import UserCreate, UserUpdate, UserStatusUpdate, ApprovalDecisionRequest
from app.routers import users as users_router
from app.routers import approvals as approvals_router
from app.user_service import (
    execute_create_user,
    execute_update_user,
    execute_set_user_status,
    execute_reset_password,
    audit_user_reconciliation,
    get_all_users_with_auth,
)


class TestAuditReconciliation(unittest.TestCase):
    def setUp(self):
        self.orig_fallback = db.allow_in_memory_fallback
        db.allow_in_memory_fallback = True
        self.orig_is_connected = db.is_connected
        db.is_connected = False
        db._fail_once.clear()
        _REVOKED_TOKENS.clear()
        _USER_REVOKED_AT.clear()

        # Clean memory store
        db.memory_store["Users"] = []
        db.memory_store["AuthUsers"] = []
        db.memory_store["RevokedTokens"] = []
        db.memory_store["ApprovalRequests"] = []
        db.memory_store["AuditLog"] = []

        now_iso = datetime.now(timezone.utc).isoformat()

        # Seed Owner
        self.owner_id = "USR-OWNER-01"
        self.owner_ctx = {"user_id": self.owner_id, "username": "owner_raj", "role": "OWNER", "full_name": "Raj Owner"}
        db.memory_store["Users"].append({
            "user_id": self.owner_id,
            "full_name": "Raj Owner",
            "username": "owner_raj",
            "role": "OWNER",
            "mobile": "9876543210",
            "email": "raj@kawadswad.com",
            "active": "true",
            "created_at": now_iso,
            "notes": "Owner",
        })
        db.memory_store["AuthUsers"].append({
            "auth_id": "AUTH-OWNER-01",
            "user_id": self.owner_id,
            "username": "owner_raj",
            "password_hash": hash_password("OwnerSecurePass123"),
            "role": "OWNER",
            "active": "true",
            "created_at": now_iso,
            "must_change_password": "false",
            "sessions_revoked_at": "",
        })

        # Seed PA
        self.pa_id = "USR-PA-01"
        self.pa_ctx = {"user_id": self.pa_id, "username": "pa_suman", "role": "PA", "full_name": "Suman PA"}
        db.memory_store["Users"].append({
            "user_id": self.pa_id,
            "full_name": "Suman PA",
            "username": "pa_suman",
            "role": "PA",
            "mobile": "9876543211",
            "email": "suman@kawadswad.com",
            "active": "true",
            "created_at": now_iso,
            "notes": "Personal Assistant",
        })
        db.memory_store["AuthUsers"].append({
            "auth_id": "AUTH-PA-01",
            "user_id": self.pa_id,
            "username": "pa_suman",
            "password_hash": hash_password("PaSecurePass123"),
            "role": "PA",
            "active": "true",
            "created_at": now_iso,
            "must_change_password": "false",
            "sessions_revoked_at": "",
        })

        # Seed Salesman
        self.salesman_id = "USR-SALES-01"
        self.salesman_ctx = {"user_id": self.salesman_id, "username": "sales_anand", "role": "SALESMAN", "full_name": "Anand Sales"}
        db.memory_store["Users"].append({
            "user_id": self.salesman_id,
            "full_name": "Anand Sales",
            "username": "sales_anand",
            "role": "SALESMAN",
            "mobile": "9876543212",
            "email": "anand@kawadswad.com",
            "active": "true",
            "created_at": now_iso,
            "notes": "Field Sales",
        })
        db.memory_store["AuthUsers"].append({
            "auth_id": "AUTH-SALES-01",
            "user_id": self.salesman_id,
            "username": "sales_anand",
            "password_hash": hash_password("SalesSecurePass123"),
            "role": "SALESMAN",
            "active": "true",
            "created_at": now_iso,
            "must_change_password": "false",
            "sessions_revoked_at": "",
        })

    def tearDown(self):
        db.allow_in_memory_fallback = self.orig_fallback
        db.is_connected = self.orig_is_connected
        db._fail_once.clear()
        _REVOKED_TOKENS.clear()
        _USER_REVOKED_AT.clear()

    def test_p0_passwords_never_stored_in_approval_requests(self):
        """P0 Security: Passwords must NEVER be stored in ApprovalRequests sheet."""
        # 1. PA requests account creation
        create_req = UserCreate(
            username="new_candidate",
            full_name="New Candidate",
            role="SALESMAN",
            mobile="9998887771",
            email="candidate@kawadswad.com",
            password="ShouldNotBeStored123",
        )
        res = asyncio.run(users_router.create_user(create_req, current_user=self.pa_ctx))
        self.assertTrue(res.get("pending_approval"))
        req_id = res.get("request_id")

        # Verify ApprovalRequests sheet payload
        app_record = next(r for r in db.memory_store["ApprovalRequests"] if r["request_id"] == req_id)
        payload = json.loads(app_record["payload_json"])
        self.assertNotIn("password", payload, "Plaintext password must NOT be in ApprovalRequests payload_json")
        self.assertNotIn("password_hash", payload)
        self.assertEqual(payload["username"], "new_candidate")

        # 2. PA requests password reset
        reset_req = users_router.PasswordResetRequest(new_password="NewSecretPass123")
        res_reset = asyncio.run(users_router.reset_password(self.salesman_id, reset_req, current_user=self.pa_ctx))
        self.assertTrue(res_reset.get("pending_approval"))
        reset_req_id = res_reset.get("request_id")

        app_reset_record = next(r for r in db.memory_store["ApprovalRequests"] if r["request_id"] == reset_req_id)
        reset_payload = json.loads(app_reset_record["payload_json"])
        self.assertNotIn("new_password", reset_payload, "Password must NOT be in reset approval request payload")
        self.assertNotIn("password_hash", reset_payload)

    def test_p0_owner_approval_generates_temporary_credentials(self):
        """P0 Security: Owner approving account creation or reset safely returns temporary credentials."""
        # PA submits request without password
        create_req = UserCreate(
            username="onboarding_user",
            full_name="Onboarding Agent",
            role="SALESMAN",
            mobile="9998887772",
        )
        res = asyncio.run(users_router.create_user(create_req, current_user=self.pa_ctx))
        req_id = res.get("request_id")

        # Owner approves request
        decision = ApprovalDecisionRequest(decision="APPROVED", notes="Approved onboarding")
        decide_res = asyncio.run(approvals_router.decide_approval_request(req_id, decision, current_user=self.owner_ctx))
        self.assertEqual(decide_res.status, "EXECUTED")
        self.assertIn("Temporary Password", decide_res.temporary_credentials)

        # Confirm user was created in Users & AuthUsers with must_change_password=True
        auth_row = next(r for r in db.memory_store["AuthUsers"] if r["username"] == "onboarding_user")
        self.assertEqual(str(auth_row["must_change_password"]).lower(), "true")
        self.assertTrue(auth_row["password_hash"])

        # Confirm ApprovalRequests sheet still contains NO plaintext password
        app_record = next(r for r in db.memory_store["ApprovalRequests"] if r["request_id"] == req_id)
        self.assertNotIn("password", json.loads(app_record["payload_json"]))

    def test_p0_partial_update_write_rollback_never_reports_false_success(self):
        """P0 Consistency: When AuthUsers fails during an employee update, Users is rolled back and 503 is raised."""
        target_id = self.salesman_id
        orig_user = dict(next(u for u in db.memory_store["Users"] if u["user_id"] == target_id))
        self.assertEqual(orig_user["role"], "SALESMAN")

        # Inject failure for AuthUsers
        db._fail_once["AuthUsers"] = 1

        update_payload = {"role": "PA", "full_name": "Anand Promoted"}
        with self.assertRaises(HTTPException) as ctx:
            execute_update_user(target_id, update_payload, self.owner_id)

        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("rolled back", str(ctx.exception.detail).lower())

        # Verify that Users record was rolled back to original role and full_name
        rolled_back_user = next(u for u in db.memory_store["Users"] if u["user_id"] == target_id)
        self.assertEqual(rolled_back_user["role"], "SALESMAN")
        self.assertEqual(rolled_back_user["full_name"], "Anand Sales")

    def test_p0_partial_status_toggle_rollback(self):
        """P0 Consistency: When AuthUsers fails during deactivation/reactivation, Users is rolled back and 503 is raised."""
        target_id = self.salesman_id
        self.assertEqual(str(next(u for u in db.memory_store["Users"] if u["user_id"] == target_id)["active"]).lower(), "true")

        # Inject failure for AuthUsers status update
        db._fail_once["AuthUsers"] = 1

        with self.assertRaises(HTTPException) as ctx:
            execute_set_user_status(target_id, False, self.owner_id, "Test deactivation failure")

        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("rolled back", str(ctx.exception.detail).lower())

        # Verify Users status remains active
        u_rec = next(u for u in db.memory_store["Users"] if u["user_id"] == target_id)
        self.assertEqual(str(u_rec["active"]).lower(), "true")

    def test_p0_approval_retry_idempotency(self):
        """P0 Idempotency: Retrying an approved CREATE_USER or DEACTIVATE_USER succeeds idempotently without error."""
        # 1. Idempotent create
        create_payload = {
            "username": "sales_anand",
            "full_name": "Anand Sales",
            "role": "SALESMAN",
        }
        res = execute_create_user(create_payload, self.owner_id)
        self.assertEqual(res["user_id"], self.salesman_id)
        self.assertTrue(res.get("idempotent"))

        # 2. Idempotent status toggle
        res_status = execute_set_user_status(self.salesman_id, True, self.owner_id)
        self.assertTrue(res_status["active"])
        self.assertTrue(res_status.get("idempotent"))

    def test_p1_reconciliation_auditor_detects_all_mismatches(self):
        """P1 Reconciliation: The independent auditor detects orphaned profiles, orphaned auth, role & status mismatches."""
        # Initially system is healthy
        rep = audit_user_reconciliation()
        self.assertTrue(rep["healthy"])
        self.assertEqual(rep["total_issues_count"], 0)

        # 1. Add orphaned profile in Users (no login in AuthUsers)
        db.memory_store["Users"].append({
            "user_id": "USR-ORPHAN-01",
            "full_name": "Orphan Profile",
            "username": "orphan_user",
            "role": "SALESMAN",
            "active": "true",
        })

        # 2. Add orphaned login in AuthUsers (no profile in Users)
        db.memory_store["AuthUsers"].append({
            "auth_id": "AUTH-GHOST-01",
            "user_id": "USR-GHOST-01",
            "username": "ghost_login",
            "password_hash": hash_password("GhostPassword123"),
            "role": "SALESMAN",
            "active": "true",
        })

        # 3. Create role divergence on existing user
        sales_auth = next(a for a in db.memory_store["AuthUsers"] if a["user_id"] == self.salesman_id)
        sales_auth["role"] = "PA"  # Users has SALESMAN, AuthUsers has PA

        # 4. Create status divergence on PA
        pa_auth = next(a for a in db.memory_store["AuthUsers"] if a["user_id"] == self.pa_id)
        pa_auth["active"] = "false"  # Users has active=true, AuthUsers has active=false

        rep2 = audit_user_reconciliation()
        self.assertFalse(rep2["healthy"])
        self.assertEqual(len(rep2["orphaned_profiles"]), 1)
        self.assertEqual(rep2["orphaned_profiles"][0]["user_id"], "USR-ORPHAN-01")

        self.assertEqual(len(rep2["orphaned_auth_accounts"]), 1)
        self.assertEqual(rep2["orphaned_auth_accounts"][0]["user_id"], "USR-GHOST-01")

        self.assertEqual(len(rep2["role_mismatches"]), 1)
        self.assertEqual(rep2["role_mismatches"][0]["user_id"], self.salesman_id)

        self.assertEqual(len(rep2["status_mismatches"]), 1)
        self.assertEqual(rep2["status_mismatches"][0]["user_id"], self.pa_id)

    def test_p1_get_all_users_with_auth_does_not_conceal_mismatches(self):
        """P1 Directory: Profiles without login accounts are marked inactive with a sync_warning, and orphaned auth are listed."""
        db.memory_store["Users"].append({
            "user_id": "USR-NOLOGIN",
            "full_name": "No Login Account",
            "username": "nologin",
            "role": "SALESMAN",
            "active": "true",  # Sheet says active, but has no AuthUsers!
        })

        all_users = get_all_users_with_auth()
        nologin_entry = next(u for u in all_users if u["user_id"] == "USR-NOLOGIN")
        self.assertFalse(nologin_entry["active"], "A profile without an AuthUsers account MUST NOT be displayed as active!")
        self.assertIn("no login account", nologin_entry["sync_warning"].lower())


if __name__ == "__main__":
    unittest.main()
