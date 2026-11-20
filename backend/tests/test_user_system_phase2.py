import os
import sys
import unittest
import asyncio
import types
from datetime import datetime, timezone

# Configure testing environment
os.environ["SALES_TESTING"] = "1"
os.environ["SALES_JWT_SECRET"] = "test-only-secret-do-not-use-for-deployment-32"

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

import tests  # Hardened FastAPI/HMAC-JWT/Pydantic test shims
from fastapi import HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from app.sheets import db
from tests.v2_test_harness import LocalAppsScriptSimulator, make_test_request
from app.auth import (
    create_access_token,
    get_current_user,
    hash_password,
    revoke_token,
    revoke_all_user_sessions,
    _REVOKED_TOKENS,
    _USER_REVOKED_AT,
)
from app.models import UserCreate, UserUpdate, UserStatusUpdate, ApprovalDecisionRequest
from app.routers import users as users_router
from app.routers import auth as auth_router
from app.routers import approvals as approvals_router
from app.user_service import execute_create_user


class TestUserSystemPhase2(unittest.TestCase):
    def setUp(self):
        self.orig_fallback = db.allow_in_memory_fallback
        db.allow_in_memory_fallback = True
        self.orig_is_connected = db.is_connected
        db.is_connected = False
        db._fail_once.clear()
        _REVOKED_TOKENS.clear()
        _USER_REVOKED_AT.clear()

        # Seed memory store
        db.memory_store["Users"] = []
        db.memory_store["AuthUsers"] = []
        db.memory_store["RevokedTokens"] = []
        db.memory_store["ApprovalRequests"] = []
        db.memory_store["AuditLog"] = []

        # Create Owner
        self.owner_user_id = "USR-OWNER-001"
        self.owner_username = "owner_test"
        now_iso = datetime.now(timezone.utc).isoformat()
        db.memory_store["Users"].append({
            "user_id": self.owner_user_id,
            "full_name": "Test Owner",
            "username": self.owner_username,
            "role": "OWNER",
            "mobile": "9999999991",
            "email": "owner@kawadswad.com",
            "active": "true",
            "created_at": now_iso,
            "notes": "Owner account",
        })
        db.memory_store["AuthUsers"].append({
            "auth_id": "AUTH-OWNER-001",
            "user_id": self.owner_user_id,
            "username": self.owner_username,
            "password_hash": hash_password("OwnerPassword123"),
            "role": "OWNER",
            "active": "true",
            "created_at": now_iso,
            "must_change_password": "false",
            "sessions_revoked_at": "",
        })

        # Create PA
        self.pa_user_id = "USR-PA-001"
        self.pa_username = "pa_test"
        db.memory_store["Users"].append({
            "user_id": self.pa_user_id,
            "full_name": "Test PA",
            "username": self.pa_username,
            "role": "PA",
            "mobile": "9999999992",
            "email": "pa@kawadswad.com",
            "active": "true",
            "created_at": now_iso,
            "notes": "Personal Assistant",
        })
        db.memory_store["AuthUsers"].append({
            "auth_id": "AUTH-PA-001",
            "user_id": self.pa_user_id,
            "username": self.pa_username,
            "password_hash": hash_password("PaPassword123"),
            "role": "PA",
            "active": "true",
            "created_at": now_iso,
            "must_change_password": "false",
            "sessions_revoked_at": "",
        })

        # Create Regular Salesman
        self.salesman_user_id = "USR-SALES-001"
        self.salesman_username = "salesman_test"
        db.memory_store["Users"].append({
            "user_id": self.salesman_user_id,
            "full_name": "Test Salesman",
            "username": self.salesman_username,
            "role": "SALESMAN",
            "mobile": "9999999993",
            "email": "sales@kawadswad.com",
            "active": "true",
            "created_at": now_iso,
            "notes": "Field Salesman",
        })
        db.memory_store["AuthUsers"].append({
            "auth_id": "AUTH-SALES-001",
            "user_id": self.salesman_user_id,
            "username": self.salesman_username,
            "password_hash": hash_password("SalesPassword123"),
            "role": "SALESMAN",
            "active": "true",
            "created_at": now_iso,
            "must_change_password": "false",
            "sessions_revoked_at": "",
        })

        self.owner_ctx = {"user_id": self.owner_user_id, "username": self.owner_username, "role": "OWNER"}
        self.pa_ctx = {"user_id": self.pa_user_id, "username": self.pa_username, "role": "PA"}
        self.salesman_ctx = {"user_id": self.salesman_user_id, "username": self.salesman_username, "role": "SALESMAN"}
        self._sim = LocalAppsScriptSimulator().start()

    def tearDown(self):
        self._sim.stop()
        db.allow_in_memory_fallback = self.orig_fallback
        db.is_connected = self.orig_is_connected
        db._fail_once.clear()
        _REVOKED_TOKENS.clear()
        _USER_REVOKED_AT.clear()

    def test_logout_token_revocation(self):
        """Phase 1: Calling logout revokes the active token and blocks further use."""
        token = create_access_token({"sub": self.salesman_user_id, "user_id": self.salesman_user_id, "role": "SALESMAN"})
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        # Token is valid initially
        user_payload = asyncio.run(get_current_user(creds))
        self.assertEqual(user_payload["user_id"], self.salesman_user_id)

        # Call logout
        res = asyncio.run(auth_router.logout(credentials=creds, current_user=user_payload))
        self.assertTrue(res["ok"])

        # Attempting to use the same token must raise 401
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(get_current_user(creds))
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("revoked", str(ctx.exception.detail).lower())

    def test_deactivation_immediate_session_invalidation(self):
        """Phase 1 & 2: Deactivating an employee immediately invalidates all active sessions."""
        token = create_access_token({"sub": self.salesman_user_id, "user_id": self.salesman_user_id, "role": "SALESMAN"})
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        # Token is valid initially
        user_payload = asyncio.run(get_current_user(creds))
        self.assertEqual(user_payload["user_id"], self.salesman_user_id)

        # Owner deactivates the salesman
        status_req = UserStatusUpdate(active=False, reason="Security audit suspension")
        res = asyncio.run(users_router.set_user_status(self.salesman_user_id, status_req, current_user=self.owner_ctx, request=make_test_request()))
        self.assertFalse(res["active"])

        # The active token must immediately be rejected with 401
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(get_current_user(creds))
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("deactivated", str(ctx.exception.detail).lower())

    def test_role_change_session_invalidation(self):
        """Phase 1 & 3: Changing an employee's role immediately revokes existing sessions."""
        token = create_access_token({"sub": self.salesman_user_id, "user_id": self.salesman_user_id, "role": "SALESMAN"})
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        # Token is valid initially
        asyncio.run(get_current_user(creds))

        # Owner changes salesman to PA
        update_req = UserUpdate(role="PA")
        asyncio.run(users_router.update_user(self.salesman_user_id, update_req, current_user=self.owner_ctx, request=make_test_request()))

        # Prior session token must be revoked
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(get_current_user(creds))
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("revoked", str(ctx.exception.detail).lower())

    def test_password_reset_session_invalidation(self):
        """Phase 1 & 3: Resetting a user password revokes all existing sessions across devices."""
        token = create_access_token({"sub": self.salesman_user_id, "user_id": self.salesman_user_id, "role": "SALESMAN"})
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        # Token is valid initially
        asyncio.run(get_current_user(creds))

        # Owner resets the salesman's password
        reset_req = users_router.PasswordResetRequest(new_password="NewSecurePassword123")
        res = asyncio.run(users_router.reset_password(self.salesman_user_id, reset_req, current_user=self.owner_ctx, request=make_test_request()))
        self.assertTrue(res["ok"])

        # Prior session token must be revoked
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(get_current_user(creds))
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("revoked", str(ctx.exception.detail).lower())

    def test_sheets_failure_raises_503_no_stale_jwt_fallback(self):
        """Phase 1: When Sheets cannot be reached, reject with 503 rather than granting access with stale JWT claims."""
        token = create_access_token({"sub": self.salesman_user_id, "user_id": self.salesman_user_id, "role": "SALESMAN"})
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)

        # Simulate Google Sheets outage by having get_records raise RuntimeError
        orig_get_records = db.get_records
        db.get_records = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("Google Sheets connection timed out"))
        try:
            with self.assertRaises(HTTPException) as ctx:
                asyncio.run(get_current_user(creds))
            self.assertEqual(ctx.exception.status_code, 503)
            self.assertIn("unreachable", str(ctx.exception.detail).lower())
        finally:
            db.get_records = orig_get_records

    def test_unique_username_validation(self):
        """Phase 2: Creating a user with a duplicate username must be rejected with 409 Conflict."""
        # Attempt to create another user with username 'owner_test'
        create_req = UserCreate(
            username=self.owner_username.upper(),  # case-insensitive check
            full_name="Duplicate Test",
            role="SALESMAN",
            password="TestPassword123",
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(users_router.create_user(create_req, current_user=self.owner_ctx, request=make_test_request()))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("already taken", str(ctx.exception.detail).lower())

    def test_two_phase_creation_rollback_on_auth_failure(self):
        """Phase 2: If AuthUsers write fails inside atomic Apps Script create, zero orphan Users or AuthUsers rows exist."""
        db._fail_once["AuthUsers"] = 1

        payload = {
            "username": "new_worker",
            "full_name": "New Worker",
            "role": "SALESMAN",
            "password": "WorkerPassword123",
        }

        with self.assertRaises(HTTPException) as ctx:
            execute_create_user(payload, actor_user_id=self.owner_user_id, nonce="TEST-CREATE-ROLLBACK-1")
        self.assertEqual(ctx.exception.status_code, 503)

        # Atomic rollback: neither Users nor AuthUsers contains an orphan
        users = [u for u in db.memory_store["Users"] if u.get("username") == "new_worker"]
        self.assertEqual(len(users), 0)
        auths = [a for a in db.memory_store["AuthUsers"] if a.get("username") == "new_worker"]
        self.assertEqual(len(auths), 0)

    def test_pa_cannot_create_or_modify_owner(self):
        """Phase 4: PA cannot create, modify, or reset password for an Owner account."""
        # PA attempts to create an Owner
        create_req = UserCreate(
            username="new_owner",
            full_name="Illegal Owner",
            role="OWNER",
            password="StrongPassword123",
        )
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(users_router.create_user(create_req, current_user=self.pa_ctx, request=make_test_request()))
        self.assertEqual(ctx.exception.status_code, 403)

        # PA attempts to edit Owner
        update_req = UserUpdate(full_name="Hacked Owner")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(users_router.update_user(self.owner_user_id, update_req, current_user=self.pa_ctx, request=make_test_request()))
        self.assertEqual(ctx.exception.status_code, 403)

        # PA attempts to reset Owner password
        pw_req = users_router.PasswordResetRequest(new_password="NewPassword123")
        with self.assertRaises(HTTPException) as ctx:
            asyncio.run(users_router.reset_password(self.owner_user_id, pw_req, current_user=self.pa_ctx, request=make_test_request()))
        self.assertEqual(ctx.exception.status_code, 403)

    def test_pa_approval_workflow_lifecycle(self):
        """Phase 4: PA submits request -> PENDING -> Owner APPROVES -> EXECUTED."""
        # 1. PA requests to create a regular salesman
        create_req = UserCreate(
            username="raghav_sales",
            full_name="Raghav Kumar",
            role="SALESMAN",
            mobile="9876543210",
            password="RaghavPassword123",
        )
        res = asyncio.run(users_router.create_user(create_req, current_user=self.pa_ctx, request=make_test_request()))
        self.assertTrue(res["pending_approval"])
        req_id = res["request_id"]

        # User is not created yet
        auths = [a for a in db.memory_store["AuthUsers"] if a.get("username") == "raghav_sales"]
        self.assertEqual(len(auths), 0)

        # 2. PA sees the request in list
        pa_requests = asyncio.run(approvals_router.list_approval_requests(current_user=self.pa_ctx))
        self.assertTrue(any(r.request_id == req_id and r.status == "PENDING" for r in pa_requests))

        # 3. Owner approves the request
        dec_req = ApprovalDecisionRequest(decision="APPROVED", notes="Approved by Owner")
        decided = asyncio.run(approvals_router.decide_approval_request(req_id, dec_req, current_user=self.owner_ctx, request=make_test_request()))
        self.assertEqual(decided.status, "EXECUTED")

        # Now the user profile and credentials must exist in Google Sheets!
        auths = [a for a in db.memory_store["AuthUsers"] if a.get("username") == "raghav_sales"]
        self.assertEqual(len(auths), 1)
        self.assertEqual(auths[0]["role"], "SALESMAN")

    def test_pa_approval_rejection(self):
        """Phase 4: Owner can reject a pending PA request."""
        create_req = UserCreate(
            username="rejected_worker",
            full_name="Rejected Worker",
            role="SALESMAN",
            password="WorkerPassword123",
        )
        res = asyncio.run(users_router.create_user(create_req, current_user=self.pa_ctx, request=make_test_request()))
        req_id = res["request_id"]

        # Owner rejects
        dec_req = ApprovalDecisionRequest(decision="REJECTED", notes="Budget exceeded")
        decided = asyncio.run(approvals_router.decide_approval_request(req_id, dec_req, current_user=self.owner_ctx, request=make_test_request()))
        self.assertEqual(decided.status, "REJECTED")

        # User was not created
        auths = [a for a in db.memory_store["AuthUsers"] if a.get("username") == "rejected_worker"]
        self.assertEqual(len(auths), 0)

    def test_pa_cancel_request(self):
        """Phase 4: PA can cancel their own pending request."""
        create_req = UserCreate(
            username="cancelled_worker",
            full_name="Cancelled Worker",
            role="SALESMAN",
            password="WorkerPassword123",
        )
        res = asyncio.run(users_router.create_user(create_req, current_user=self.pa_ctx, request=make_test_request()))
        req_id = res["request_id"]

        # PA cancels request
        cancelled = asyncio.run(approvals_router.cancel_approval_request(req_id, current_user=self.pa_ctx, request=make_test_request()))
        self.assertEqual(cancelled.status, "CANCELLED")

    def test_approval_execution_failure_and_retry(self):
        """Phase 4: Atomic approval failure raises 503 with zero partial state, automatic retry endpoint stays disabled (409), and clean re-approval succeeds."""
        create_req = UserCreate(
            username="retry_worker",
            full_name="Retry Worker",
            role="SALESMAN",
            password="WorkerPassword123",
        )
        res = asyncio.run(users_router.create_user(create_req, current_user=self.pa_ctx, request=make_test_request()))
        req_id = res["request_id"]

        # Inject failure on Users sheet during atomic approval execution -> HTTP 503, request stays PENDING
        db._fail_once["Users"] = 1
        dec_req = ApprovalDecisionRequest(decision="APPROVED", notes="Approved")
        with self.assertRaises(HTTPException) as fail_ctx:
            asyncio.run(approvals_router.decide_approval_request(req_id, dec_req, current_user=self.owner_ctx, request=make_test_request()))
        self.assertEqual(fail_ctx.exception.status_code, 503)
        self.assertEqual(len([a for a in db.memory_store["AuthUsers"] if a.get("username") == "retry_worker"]), 0)

        # Automatic retry endpoint is intentionally disabled (409 fail-closed safety guard)
        with self.assertRaises(HTTPException) as retry_ctx:
            asyncio.run(approvals_router.retry_failed_execution(req_id, current_user=self.owner_ctx))
        self.assertEqual(retry_ctx.exception.status_code, 409)

        # Clean Owner approval after storage recovery executes atomically
        decided = asyncio.run(approvals_router.decide_approval_request(req_id, dec_req, current_user=self.owner_ctx, request=make_test_request()))
        self.assertEqual(decided.status, "EXECUTED")

        # Verified created
        auths = [a for a in db.memory_store["AuthUsers"] if a.get("username") == "retry_worker"]
        self.assertEqual(len(auths), 1)


if __name__ == "__main__":
    unittest.main()
