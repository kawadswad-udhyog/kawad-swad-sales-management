"""
Kawad Swad ERP — KS-DEV-01 First Owner Setup & First Login End-to-End Backend Test Suite.

Runs 100% offline in isolated development/testing mode (`SALES_TESTING=1`) against
the real authentication router, JWT verification, revocation store, dashboard/workspace
protected endpoints, and `LocalAppsScriptSimulator` (zero live Google Sheets or Render mutations).

Mandatory KS-DEV-01 Stage F Scenarios Covered:
  1. First Owner setup succeeds (201, PBKDF2 hash, OWNER_ADMIN, zero secret leakage)
  2. Second Owner setup is rejected (409 OWNER_ALREADY_INITIALIZED) & bootstrap-status flips to INITIALIZED
  3. Incorrect password is rejected (401)
  4. Correct password succeeds (200, Bearer JWT, canonical username & OWNER role)
  5. Inactive user cannot log in (403) and deactivated user's active session is rejected (401)
  6. Unauthorized user cannot access protected routes (401 without valid session / 403 for non-owner on owner-only routes)
  7. Owner can access authorized dashboard and workspace endpoints (200, role=OWNER)
  8. Refresh preserves a valid session (GET /api/auth/me validates Bearer token & restores identity)
  9. Expired session is rejected (401 on expired JWT)
 10. Logout terminates and revokes the session (POST /api/auth/logout -> 200, token revoked)
 11. Logged-out user cannot revisit protected pages/endpoints with revoked token (401)
 12. Direct API access without authentication is rejected (401)
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

os.environ.setdefault("SALES_TESTING", "1")
os.environ.setdefault("SALES_ENV", "development")

from app.auth import (  # noqa: E402
    _REVOKED_TOKENS,
    _USER_REVOKED_AT,
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.models import LoginRequest, OwnerSetupRequest  # noqa: E402
from app.routers import audit as audit_router  # noqa: E402
from app.routers import auth as auth_router  # noqa: E402
from app.routers import dashboard as dashboard_router  # noqa: E402
from app.routers import workspace as workspace_router  # noqa: E402
from app.sheets import db  # noqa: E402
from tests.v2_test_harness import LocalAppsScriptSimulator  # noqa: E402


_TEST_BOOTSTRAP_SECRET = "KsDev01OneTimeBootstrapAuthorityToken#2026!998877"
_TEST_OWNER_PASSWORD = "KawadSwad!DevOwner#2026"
_TEST_STAFF_PASSWORD = "KawadSwad!DevStaff#2026"


class _DummyBackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *args, **kwargs):
        self.tasks.append((fn, args, kwargs))


def _make_request(headers=None, path: str = "/api/auth/bootstrap-owner", method: str = "POST") -> Request:
    raw_headers = [
        (k.lower().encode("latin-1"), str(v).encode("latin-1"))
        for k, v in (headers or {}).items()
    ]
    return Request({
        "type": "http",
        "method": method,
        "path": path,
        "headers": raw_headers,
        "query_string": b"",
    })


def _future_iso(minutes: int = 30) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


class TestKSDev01FirstOwnerAndLogin(unittest.TestCase):
    def setUp(self):
        db.memory_store.clear()
        for tab in (
            "Users",
            "AuthUsers",
            "IdAllocations",
            "AuditLog",
            "RevokedTokens",
            "Products",
            "Customers",
            "Sales",
            "SaleItems",
            "Payments",
            "StockTransactions",
            "Expenses",
            "ShopVisits",
            "DailyClosing",
            "SalaryIncentives",
            "ApprovalRequests",
            "StockDiscrepancies",
            "ProductionBatches",
            "Attendance",
            "Workers",
        ):
            db.memory_store[tab] = []
        auth_router._LOGIN_ATTEMPTS.clear()
        _REVOKED_TOKENS.clear()
        _USER_REVOKED_AT.clear()
        self.sim = LocalAppsScriptSimulator().start()

    def tearDown(self):
        self.sim.stop()
        auth_router._LOGIN_ATTEMPTS.clear()
        _REVOKED_TOKENS.clear()
        _USER_REVOKED_AT.clear()

    def _run(self, coro):
        return asyncio.run(coro)

    def _bootstrap_env(self, **overrides):
        env = {
            "SALES_OWNER_BOOTSTRAP_ENABLED": "true",
            "SALES_OWNER_BOOTSTRAP_SECRET": _TEST_BOOTSTRAP_SECRET,
            "SALES_OWNER_BOOTSTRAP_EXPIRES_AT": _future_iso(30),
        }
        env.update(overrides)
        return env

    def _bootstrap_first_owner(self, username="owner.dev", nonce="KS-DEV-01-BOOTSTRAP-001"):
        req = _make_request(
            headers={
                "X-KS-Bootstrap-Token": _TEST_BOOTSTRAP_SECRET,
                "X-KS-Idempotency-Key": nonce,
            }
        )
        body = OwnerSetupRequest(
            username=username,
            full_name="Rajesh Kawad",
            password=_TEST_OWNER_PASSWORD,
            email="owner@kawadswad.dev",
            mobile="9876543210",
            notes="KS-DEV-01 development initialization",
        )
        with patch.dict(os.environ, self._bootstrap_env(), clear=False):
            return self._run(auth_router.bootstrap_first_owner(body, req))

    def _login(self, username: str, password: str):
        bg = _DummyBackgroundTasks()
        res = self._run(auth_router.login(LoginRequest(username=username, password=password), bg))
        for fn, args, kwargs in bg.tasks:
            fn(*args, **kwargs)
        return res

    # ------------------------------------------------------------------
    # Bootstrap status endpoint verification
    # ------------------------------------------------------------------
    def test_00_bootstrap_status_reflects_disabled_ready_and_initialized_states(self):
        # Empty DB + disabled env -> BOOTSTRAP_DISABLED
        with patch.dict(os.environ, {
            "SALES_OWNER_BOOTSTRAP_ENABLED": "false",
            "SALES_OWNER_BOOTSTRAP_SECRET": "",
            "SALES_OWNER_BOOTSTRAP_EXPIRES_AT": "",
        }, clear=False):
            st_disabled = self._run(auth_router.get_owner_bootstrap_status())
        self.assertFalse(st_disabled.initialized)
        self.assertFalse(st_disabled.bootstrap_enabled)
        self.assertEqual(st_disabled.status, "BOOTSTRAP_DISABLED")
        self.assertTrue(st_disabled.storage_ready)

        # Empty DB + valid env -> BOOTSTRAP_READY (never exposes secret)
        with patch.dict(os.environ, self._bootstrap_env(), clear=False):
            st_ready = self._run(auth_router.get_owner_bootstrap_status())
        self.assertFalse(st_ready.initialized)
        self.assertTrue(st_ready.bootstrap_enabled)
        self.assertEqual(st_ready.status, "BOOTSTRAP_READY")
        self.assertNotIn(_TEST_BOOTSTRAP_SECRET, str(st_ready.model_dump()))

        # After Owner creation -> INITIALIZED, bootstrap_enabled=False
        self._bootstrap_first_owner()
        with patch.dict(os.environ, self._bootstrap_env(), clear=False):
            st_init = self._run(auth_router.get_owner_bootstrap_status())
        self.assertTrue(st_init.initialized)
        self.assertFalse(st_init.bootstrap_enabled)
        self.assertEqual(st_init.status, "INITIALIZED")

    # ------------------------------------------------------------------
    # Scenario 1 & 2: First Owner setup succeeds; Second Owner setup rejected
    # ------------------------------------------------------------------
    def test_01_and_02_first_owner_setup_succeeds_and_second_setup_rejected(self):
        res = self._bootstrap_first_owner()
        self.assertTrue(res.success)
        self.assertEqual(res.username, "owner.dev")
        self.assertEqual(res.full_name, "Rajesh Kawad")
        self.assertEqual(res.role, "OWNER_ADMIN")
        self.assertEqual(res.canonical_role, "OWNER_ADMIN")
        self.assertFalse(res.must_change_password)
        self.assertTrue(res.user_id.startswith("USR-"))

        # Password stored as PBKDF2-SHA256 hash only (never plaintext)
        self.assertEqual(len(db.memory_store["Users"]), 1)
        self.assertEqual(len(db.memory_store["AuthUsers"]), 1)
        stored_hash = db.memory_store["AuthUsers"][0]["password_hash"]
        self.assertTrue(stored_hash.startswith("pbkdf2:sha256:"))
        self.assertNotIn(_TEST_OWNER_PASSWORD, stored_hash)
        self.assertTrue(verify_password(_TEST_OWNER_PASSWORD, stored_hash))
        self.assertNotIn(_TEST_OWNER_PASSWORD, str(res.model_dump()))
        self.assertNotIn(_TEST_BOOTSTRAP_SECRET, str(res.model_dump()))

        # Scenario 2: Second Owner setup attempt is permanently rejected (409)
        req2 = _make_request(
            headers={
                "X-KS-Bootstrap-Token": _TEST_BOOTSTRAP_SECRET,
                "X-KS-Idempotency-Key": "KS-DEV-01-BOOTSTRAP-002",
            }
        )
        body2 = OwnerSetupRequest(
            username="second.owner",
            full_name="Unauthorized Second Owner",
            password=_TEST_OWNER_PASSWORD,
        )
        with patch.dict(os.environ, self._bootstrap_env(), clear=False):
            with self.assertRaises(HTTPException) as ctx:
                self._run(auth_router.bootstrap_first_owner(body2, req2))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["error_code"], "OWNER_ALREADY_INITIALIZED")
        self.assertEqual(len(db.memory_store["Users"]), 1)
        self.assertEqual(len(db.memory_store["AuthUsers"]), 1)

    # ------------------------------------------------------------------
    # Scenario 3 & 4: Incorrect password rejected; Correct password succeeds
    # ------------------------------------------------------------------
    def test_03_and_04_incorrect_password_rejected_and_correct_password_succeeds(self):
        self._bootstrap_first_owner()

        # Scenario 3: Wrong password -> 401
        with self.assertRaises(HTTPException) as ctx:
            self._login("owner.dev", "WrongPassword#2026")
        self.assertEqual(ctx.exception.status_code, 401)

        # Scenario 4: Correct password -> 200 with Bearer JWT + OWNER identity
        tok = self._login("owner.dev", _TEST_OWNER_PASSWORD)
        self.assertEqual(tok.token_type, "bearer")
        self.assertTrue(bool(tok.access_token))
        self.assertEqual(tok.username, "owner.dev")
        self.assertEqual(tok.full_name, "Rajesh Kawad")
        self.assertEqual(tok.role, "OWNER_ADMIN")

    # ------------------------------------------------------------------
    # Scenario 5: Inactive user cannot log in & deactivated token rejected
    # ------------------------------------------------------------------
    def test_05_inactive_user_cannot_login_and_deactivated_session_rejected(self):
        self._bootstrap_first_owner()
        # Add an inactive staff account
        db.memory_store["AuthUsers"].append({
            "auth_id": "AUTH-INACTIVE-1",
            "user_id": "USR-000002",
            "username": "inactive.staff",
            "full_name": "Inactive Worker",
            "password_hash": hash_password(_TEST_STAFF_PASSWORD),
            "role": "FIELD_SALESMAN",
            "active": "false",
            "must_change_password": "false",
            "sessions_revoked_at": "",
        })

        with self.assertRaises(HTTPException) as ctx:
            self._login("inactive.staff", _TEST_STAFF_PASSWORD)
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertIn("inactive", str(ctx.exception.detail).lower())

        # Also verify that if an active user logs in and is then deactivated, their existing token is rejected
        tok = self._login("owner.dev", _TEST_OWNER_PASSWORD)
        db.memory_store["AuthUsers"][0]["active"] = "false"
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=tok.access_token)
        with self.assertRaises(HTTPException) as ctx_deact:
            self._run(get_current_user(creds))
        self.assertEqual(ctx_deact.exception.status_code, 401)

    # ------------------------------------------------------------------
    # Scenario 6 & 12: Direct unauthenticated access & unauthorized role access rejected
    # ------------------------------------------------------------------
    def test_06_and_12_unauthorized_and_unauthenticated_access_rejected(self):
        self._bootstrap_first_owner()

        # Scenario 12: Direct API access without Authorization header -> 401
        with self.assertRaises(HTTPException) as ctx_no_auth:
            self._run(get_current_user(None))
        self.assertEqual(ctx_no_auth.exception.status_code, 401)

        # Invalid/forged token -> 401
        bad_creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="forged.invalid.jwt")
        with self.assertRaises(HTTPException) as ctx_bad:
            self._run(get_current_user(bad_creds))
        self.assertEqual(ctx_bad.exception.status_code, 401)

        # Scenario 6: Non-owner authenticated user cannot access Owner-only protected routes -> 403
        db.memory_store["AuthUsers"].append({
            "auth_id": "AUTH-SALES-1",
            "user_id": "USR-000003",
            "username": "sales.staff",
            "full_name": "Field Salesman",
            "password_hash": hash_password(_TEST_STAFF_PASSWORD),
            "role": "FIELD_SALESMAN",
            "active": "true",
            "must_change_password": "false",
            "sessions_revoked_at": "",
        })
        sales_tok = self._login("sales.staff", _TEST_STAFF_PASSWORD)
        sales_creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=sales_tok.access_token)
        sales_user = self._run(get_current_user(sales_creds))
        self.assertEqual(sales_user["role"], "FIELD_SALESMAN")

        with self.assertRaises(HTTPException) as ctx_forbidden:
            self._run(audit_router.list_audit_logs(current_user=sales_user))
        self.assertEqual(ctx_forbidden.exception.status_code, 403)

    # ------------------------------------------------------------------
    # Scenario 7 & 8: Owner accesses authorized dashboard & refresh preserves valid session
    # ------------------------------------------------------------------
    def test_07_and_08_owner_accesses_dashboard_and_refresh_preserves_session(self):
        self._bootstrap_first_owner()
        tok = self._login("owner.dev", _TEST_OWNER_PASSWORD)
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=tok.access_token)

        # Scenario 8: Simulate browser refresh -> GET /api/auth/me validates Bearer token
        current_user = self._run(get_current_user(creds))
        me = self._run(auth_router.get_me(current_user=current_user))
        self.assertEqual(me["user_id"], tok.user_id)
        self.assertEqual(me["username"], "owner.dev")
        self.assertEqual(me["full_name"], "Rajesh Kawad")
        self.assertEqual(me["role"], "OWNER_ADMIN")

        # Scenario 7: Owner accesses protected Dashboard & Workspace endpoints
        dash = self._run(dashboard_router.get_dashboard_metrics(current_user=current_user))
        dash_dict = dash.model_dump() if hasattr(dash, "model_dump") else dict(dash)
        self.assertIn("today_sales", dash_dict)
        self.assertIn(dash_dict.get("role"), ("OWNER", "OWNER_ADMIN"))

        ws = self._run(workspace_router.load_workspace(current_user=current_user))
        self.assertIsInstance(ws, dict)
        self.assertIn("dashboard", ws)
        self.assertIn("users", ws)

    # ------------------------------------------------------------------
    # Scenario 9: Expired session is rejected
    # ------------------------------------------------------------------
    def test_09_expired_session_token_is_rejected(self):
        res = self._bootstrap_first_owner()
        expired_token = create_access_token(
            {
                "sub": res.user_id,
                "user_id": res.user_id,
                "username": "owner.dev",
                "full_name": "Rajesh Kawad",
                "role": "OWNER_ADMIN",
                "must_change_password": False,
            },
            expires_delta=timedelta(seconds=-120),
        )
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=expired_token)
        with self.assertRaises(HTTPException) as ctx:
            self._run(get_current_user(creds))
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("expired", str(ctx.exception.detail).lower())

    # ------------------------------------------------------------------
    # Scenario 10 & 11: Logout terminates session & logged-out token rejected
    # ------------------------------------------------------------------
    def test_10_and_11_logout_terminates_session_and_revoked_token_rejected(self):
        self._bootstrap_first_owner()
        tok = self._login("owner.dev", _TEST_OWNER_PASSWORD)
        creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=tok.access_token)

        # Verify session works before logout
        current_user = self._run(get_current_user(creds))
        self.assertEqual(current_user["username"], "owner.dev")

        # Scenario 10: Logout revokes token
        logout_res = self._run(auth_router.logout(credentials=creds, current_user=current_user))
        self.assertTrue(logout_res.get("ok"))

        # Scenario 11: Reusing revoked token on protected endpoints fails with 401
        with self.assertRaises(HTTPException) as ctx:
            self._run(get_current_user(creds))
        self.assertEqual(ctx.exception.status_code, 401)
        self.assertIn("revoked", str(ctx.exception.detail).lower())


if __name__ == "__main__":
    unittest.main()
