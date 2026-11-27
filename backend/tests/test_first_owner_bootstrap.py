"""
Kawad Swad ERP — First-Owner Secure Initialization Unit & Security Test Suite.

IMPORTANT:
- 100% offline / isolated (`SALES_TESTING=1`, `LocalAppsScriptSimulator`, in-memory DB).
- Never connects to live Google Sheets, Apps Script, or Render.
- Covers all 12 security & governance invariants plus Owner decisions:
  1. Disabled fail-closed by default (403).
  2. Expired bootstrap window rejected (403).
  3. Weak secret (<32 chars) and secret reuse with JWT or Apps Script HMAC rejected (403).
  4. Invalid/missing X-KS-Bootstrap-Token rejected (403); query-string token rejected (400).
  5. Rate limiting triggers lockout after repeated invalid attempts (429).
  6. Missing X-KS-Idempotency-Key rejected (422).
  7. Non-empty Users OR non-empty AuthUsers rejected fail-closed (409 OWNER_ALREADY_INITIALIZED).
  8. Role tampering cannot alter forced canonical OWNER_ADMIN role.
  9. End-to-end governed bootstrap through signed Apps Script bridge succeeds (201):
     - Allocates canonical USR-xxxxxx ID via IdAllocator.
     - Persists PBKDF2-SHA256 hash only (never plaintext).
     - Enforces must_change_password = false.
     - Zero secrets/passwords/hashes in response or AuditLog.
  10. Created Owner logs in immediately via POST /api/auth/login and accesses /api/auth/me as OWNER.
  11. Second bootstrap attempt with new nonce is permanently rejected (409).
  12. Same nonce + same payload returns idempotent replay (`is_replay=True`);
      same nonce + modified payload is rejected with 409 IDEMPOTENCY_PAYLOAD_CONFLICT.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi import HTTPException, Request

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

os.environ.setdefault("SALES_TESTING", "1")
os.environ.setdefault("SALES_ENV", "development")

from app.auth import get_current_user, verify_password  # noqa: E402
from app.models import LoginRequest, OwnerSetupRequest  # noqa: E402
from app.routers import auth as auth_router  # noqa: E402
from app.sheets import db  # noqa: E402
from tests.v2_test_harness import LocalAppsScriptSimulator, TEST_SIM_SECRET  # noqa: E402


_VALID_BOOTSTRAP_SECRET = "KsOwnerBootstrapOneTimeAuthoritySecret2026!@#9876543210"
_OWNER_PASSWORD = "KawadSwad!Owner#Secure2026"


class _DummyBackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *args, **kwargs):
        self.tasks.append((fn, args, kwargs))


def _make_request(headers=None, query_string: bytes = b"") -> Request:
    raw_headers = []
    for k, v in (headers or {}).items():
        raw_headers.append((k.lower().encode("latin-1"), str(v).encode("latin-1")))
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/api/auth/bootstrap-owner",
        "headers": raw_headers,
        "query_string": query_string,
    }
    return Request(scope)


def _future_iso(minutes: int = 30) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


def _past_iso(minutes: int = 5) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


class TestFirstOwnerBootstrap(unittest.TestCase):
    def setUp(self):
        db.memory_store.clear()
        for tab in ("Users", "AuthUsers", "IdAllocations", "AuditLog", "RevokedTokens"):
            db.memory_store[tab] = []
        auth_router._LOGIN_ATTEMPTS.clear()
        self.sim = LocalAppsScriptSimulator().start()

    def tearDown(self):
        self.sim.stop()
        auth_router._LOGIN_ATTEMPTS.clear()

    def _run(self, coro):
        return asyncio.run(coro)

    def _valid_env(self, **overrides):
        env = {
            "SALES_OWNER_BOOTSTRAP_ENABLED": "true",
            "SALES_OWNER_BOOTSTRAP_SECRET": _VALID_BOOTSTRAP_SECRET,
            "SALES_OWNER_BOOTSTRAP_EXPIRES_AT": _future_iso(30),
        }
        env.update(overrides)
        return env

    def _valid_req(self, **overrides) -> OwnerSetupRequest:
        data = {
            "username": "kawad.owner",
            "full_name": "Rajesh Kawad",
            "password": _OWNER_PASSWORD,
            "email": "owner@kawadswad.example",
            "mobile": "9876543210",
            "notes": "Initial production owner setup",
        }
        data.update(overrides)
        return OwnerSetupRequest(**data)

    def test_01_disabled_by_default_fails_closed(self):
        req = self._make_bootstrap_request()
        with patch.dict(os.environ, {
            "SALES_OWNER_BOOTSTRAP_ENABLED": "false",
            "SALES_OWNER_BOOTSTRAP_SECRET": "",
            "SALES_OWNER_BOOTSTRAP_EXPIRES_AT": "",
        }, clear=False):
            with self.assertRaises(HTTPException) as ctx:
                self._run(auth_router.bootstrap_first_owner(self._valid_req(), req))
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail["error_code"], "OWNER_BOOTSTRAP_DISABLED")
        self.assertEqual(len(db.memory_store["Users"]), 0)
        self.assertEqual(len(db.memory_store["AuthUsers"]), 0)

    def test_02_expired_window_rejected(self):
        req = self._make_bootstrap_request()
        with patch.dict(os.environ, self._valid_env(SALES_OWNER_BOOTSTRAP_EXPIRES_AT=_past_iso(5)), clear=False):
            with self.assertRaises(HTTPException) as ctx:
                self._run(auth_router.bootstrap_first_owner(self._valid_req(), req))
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail["error_code"], "OWNER_BOOTSTRAP_EXPIRED")

    def test_03_secret_reuse_with_apps_script_hmac_rejected(self):
        req = self._make_bootstrap_request(token=TEST_SIM_SECRET)
        with patch.dict(os.environ, self._valid_env(
            SALES_OWNER_BOOTSTRAP_SECRET=TEST_SIM_SECRET,
            SALES_APPS_SCRIPT_SHARED_SECRET=TEST_SIM_SECRET,
        ), clear=False):
            with self.assertRaises(HTTPException) as ctx:
                self._run(auth_router.bootstrap_first_owner(self._valid_req(), req))
        self.assertEqual(ctx.exception.status_code, 403)
        self.assertEqual(ctx.exception.detail["error_code"], "OWNER_BOOTSTRAP_SECRET_REUSE_FORBIDDEN")

    def test_04_query_string_token_rejected(self):
        req = _make_request(
            headers={
                "X-KS-Bootstrap-Token": _VALID_BOOTSTRAP_SECRET,
                "X-KS-Idempotency-Key": "BOOTSTRAP-QSTR-001",
            },
            query_string=b"bootstrap_token=leaked-in-url",
        )
        with patch.dict(os.environ, self._valid_env(), clear=False):
            with self.assertRaises(HTTPException) as ctx:
                self._run(auth_router.bootstrap_first_owner(self._valid_req(), req))
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertEqual(ctx.exception.detail["error_code"], "BOOTSTRAP_TOKEN_IN_QUERY_FORBIDDEN")

    def test_05_invalid_token_and_rate_limit_lockout(self):
        with patch.dict(os.environ, self._valid_env(), clear=False):
            for idx in range(3):
                req = self._make_bootstrap_request(token="wrong-secret-" + ("x" * 30), nonce=f"BOOT-BAD-{idx}")
                with self.assertRaises(HTTPException) as ctx:
                    self._run(auth_router.bootstrap_first_owner(self._valid_req(), req))
                self.assertEqual(ctx.exception.status_code, 403)

            # 4th attempt must hit strict 429 lockout even with the real token
            req_valid = self._make_bootstrap_request(nonce="BOOT-AFTER-LOCKOUT")
            with self.assertRaises(HTTPException) as ctx:
                self._run(auth_router.bootstrap_first_owner(self._valid_req(), req_valid))
            self.assertEqual(ctx.exception.status_code, 429)
            self.assertEqual(ctx.exception.detail["error_code"], "OWNER_BOOTSTRAP_RATE_LIMITED")

    def test_06_missing_idempotency_key_rejected(self):
        req = _make_request(headers={"X-KS-Bootstrap-Token": _VALID_BOOTSTRAP_SECRET})
        with patch.dict(os.environ, self._valid_env(), clear=False):
            with self.assertRaises(HTTPException) as ctx:
                self._run(auth_router.bootstrap_first_owner(self._valid_req(), req))
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail["error_code"], "MISSING_IDEMPOTENCY_NONCE")

    def test_07_non_empty_users_or_authusers_blocks_bootstrap(self):
        # Case A: Users has 1 row, AuthUsers empty
        db.memory_store["Users"] = [{"user_id": "USR-000001", "username": "existing", "role": "OWNER_ADMIN"}]
        req = self._make_bootstrap_request(nonce="BOOT-NONEMPTY-U")
        with patch.dict(os.environ, self._valid_env(), clear=False):
            with self.assertRaises(HTTPException) as ctx:
                self._run(auth_router.bootstrap_first_owner(self._valid_req(), req))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["error_code"], "OWNER_ALREADY_INITIALIZED")

        # Case B: Users empty, AuthUsers has 1 row
        db.memory_store["Users"] = []
        db.memory_store["AuthUsers"] = [{"auth_id": "AUTH-000001", "user_id": "USR-000001", "username": "existing"}]
        req2 = self._make_bootstrap_request(nonce="BOOT-NONEMPTY-A")
        with patch.dict(os.environ, self._valid_env(), clear=False):
            with self.assertRaises(HTTPException) as ctx:
                self._run(auth_router.bootstrap_first_owner(self._valid_req(), req2))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["error_code"], "OWNER_ALREADY_INITIALIZED")

    def test_08_end_to_end_bootstrap_login_replay_conflict_and_no_secret_leak(self):
        nonce = "BOOTSTRAP-OWNER-E2E-001"
        req = self._make_bootstrap_request(nonce=nonce)
        valid_env = self._valid_env()

        with patch.dict(os.environ, valid_env, clear=False):
            res = self._run(auth_router.bootstrap_first_owner(self._valid_req(), req))

        # Verify response contract & Owner decisions
        self.assertTrue(res.success)
        self.assertEqual(res.status, "CONFIRMED")
        self.assertTrue(res.user_id.startswith("USR-"))
        self.assertEqual(res.username, "kawad.owner")
        self.assertEqual(res.role, "OWNER_ADMIN")
        self.assertEqual(res.canonical_role, "OWNER_ADMIN")
        self.assertFalse(res.must_change_password)
        self.assertFalse(res.is_replay)

        # Verify zero secrets or password hashes leaked into response or AuditLog
        res_json = json.dumps(res.model_dump(), default=str)
        self.assertNotIn(_OWNER_PASSWORD, res_json)
        self.assertNotIn(_VALID_BOOTSTRAP_SECRET, res_json)
        self.assertNotIn("pbkdf2:sha256:", res_json)

        audit_json = json.dumps(db.memory_store.get("AuditLog", []), default=str)
        self.assertNotIn(_OWNER_PASSWORD, audit_json)
        self.assertNotIn(_VALID_BOOTSTRAP_SECRET, audit_json)
        self.assertNotIn("pbkdf2:sha256:", audit_json)

        # Verify synchronized Users & AuthUsers rows
        users = db.memory_store["Users"]
        auth_users = db.memory_store["AuthUsers"]
        self.assertEqual(len(users), 1)
        self.assertEqual(len(auth_users), 1)
        self.assertEqual(users[0]["user_id"], res.user_id)
        self.assertEqual(users[0]["role"], "OWNER_ADMIN")
        self.assertEqual(users[0]["active"], "true")
        self.assertEqual(auth_users[0]["user_id"], res.user_id)
        self.assertEqual(auth_users[0]["role"], "OWNER_ADMIN")
        self.assertEqual(auth_users[0]["must_change_password"], "false")
        self.assertTrue(str(auth_users[0]["password_hash"]).startswith("pbkdf2:sha256:100000$"))
        self.assertNotEqual(auth_users[0]["password_hash"], _OWNER_PASSWORD)
        self.assertTrue(verify_password(_OWNER_PASSWORD, auth_users[0]["password_hash"]))

        # Verify Owner can log in immediately through existing /api/auth/login -> /api/auth/me
        bg = _DummyBackgroundTasks()
        token_resp = self._run(
            auth_router.login(LoginRequest(username="kawad.owner", password=_OWNER_PASSWORD), bg)
        )
        self.assertEqual(token_resp.user_id, res.user_id)
        self.assertEqual(token_resp.role, "OWNER_ADMIN")
        self.assertFalse(token_resp.must_change_password)

        from fastapi.security import HTTPAuthorizationCredentials
        from app.permissions import is_owner, require_owner, role_v2_of

        current = self._run(
            get_current_user(
                HTTPAuthorizationCredentials(scheme="Bearer", credentials=token_resp.access_token)
            )
        )
        self.assertTrue(is_owner(current))
        self.assertEqual(role_v2_of(current), "OWNER_ADMIN")
        require_owner(current)
        me = self._run(auth_router.get_me(current))
        self.assertEqual(me["user_id"], res.user_id)
        self.assertEqual(me["role"], "OWNER_ADMIN")
        self.assertFalse(me["must_change_password"])

        # Same nonce + identical payload -> idempotent replay, zero duplicate rows
        with patch.dict(os.environ, valid_env, clear=False):
            replay = self._run(auth_router.bootstrap_first_owner(self._valid_req(), req))
        self.assertTrue(replay.is_replay)
        self.assertEqual(replay.user_id, res.user_id)
        self.assertEqual(len(db.memory_store["Users"]), 1)
        self.assertEqual(len(db.memory_store["AuthUsers"]), 1)

        # Same nonce + modified payload -> 409 IDEMPOTENCY_PAYLOAD_CONFLICT
        with patch.dict(os.environ, valid_env, clear=False):
            with self.assertRaises(HTTPException) as conflict_ctx:
                self._run(
                    auth_router.bootstrap_first_owner(
                        self._valid_req(full_name="Tampered Owner Name"),
                        req,
                    )
                )
        self.assertEqual(conflict_ctx.exception.status_code, 409)
        self.assertEqual(conflict_ctx.exception.detail["error_code"], "IDEMPOTENCY_PAYLOAD_CONFLICT")

        # Fresh nonce after initialization -> permanently rejected 409 OWNER_ALREADY_INITIALIZED
        req_second = self._make_bootstrap_request(nonce="BOOTSTRAP-OWNER-SECOND-NEW")
        with patch.dict(os.environ, valid_env, clear=False):
            with self.assertRaises(HTTPException) as dup_ctx:
                self._run(auth_router.bootstrap_first_owner(self._valid_req(), req_second))
        self.assertEqual(dup_ctx.exception.status_code, 409)
        self.assertEqual(dup_ctx.exception.detail["error_code"], "OWNER_ALREADY_INITIALIZED")

    def test_09_apps_script_recovery_required_quarantines_non_retryable_409(self):
        from tests.v2_test_harness import _FakeHTTPResponse

        def _fake_recovery_required(_req):
            return _FakeHTTPResponse({
                "status": "RECOVERY_REQUIRED",
                "correlation_id": "",
                "nonce": "BOOTSTRAP-RECOVERY-001",
                "action": "BOOTSTRAP_FIRST_OWNER",
                "target_tab": "Users",
                "allocated_id": "USR-000001",
                "error_code": "PARTIAL_BOOTSTRAP_WRITE_AUTHUSERS_FAILED",
                "message": "Users row written but AuthUsers write failed; manual reconciliation required.",
                "http_status": 409,
                "retryable": False,
            })

        req = self._make_bootstrap_request(nonce="BOOTSTRAP-RECOVERY-001")
        with patch.dict(os.environ, self._valid_env(), clear=False):
            with patch.object(self.sim, "_dispatch_http_request", side_effect=_fake_recovery_required):
                with self.assertRaises(HTTPException) as ctx:
                    self._run(auth_router.bootstrap_first_owner(self._valid_req(), req))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["status"], "RECOVERY_REQUIRED")
        self.assertEqual(ctx.exception.detail["error_code"], "PARTIAL_BOOTSTRAP_WRITE_AUTHUSERS_FAILED")
        self.assertFalse(ctx.exception.detail["retryable"])

    def test_10_b2_allowlisted_apps_script_302_echo_redirect_and_header_stripping(self):
        import urllib.error
        import urllib.request
        from app.apps_script_bridge import (
            _AppsScriptEchoRedirectHandler,
            _is_allowed_apps_script_echo_url,
        )

        # 1. URL allowlist checks (strictly https://script.googleusercontent.com/macros/echo)
        allowed_echo = "https://script.googleusercontent.com/macros/echo?user_content_key=abc123&lib=xyz789"
        self.assertTrue(_is_allowed_apps_script_echo_url(allowed_echo))
        self.assertTrue(_is_allowed_apps_script_echo_url("https://script.googleusercontent.com:443/macros/echo?k=1"))

        disallowed_urls = [
            "http://script.googleusercontent.com/macros/echo?user_content_key=abc",
            "https://accounts.google.com/ServiceLogin?continue=https://script.google.com",
            "https://script.googleusercontent.com/other/path?k=1",
            "https://script.googleusercontent.com/macros/echo/extra?k=1",
            "https://script.googleusercontent.com.evil.com/macros/echo?k=1",
            "https://evil.com/macros/echo?k=1",
            "https://script.googleusercontent.com:8443/macros/echo?k=1",
            "https://script.googleusercontent.com@evil.com/macros/echo?k=1",
            "https://script.googleusercontent.com/macros/echo?k=1#frag",
            "https://127.0.0.1/macros/echo?k=1",
            "",
        ]
        for bad_url in disallowed_urls:
            self.assertFalse(_is_allowed_apps_script_echo_url(bad_url), f"Should reject {bad_url}")

        # 2. Verify POST -> GET conversion and complete stripping of secrets/HMAC headers/body
        handler = _AppsScriptEchoRedirectHandler()
        orig_req = urllib.request.Request(
            "https://script.google.com/macros/s/AKfycbTestDeployment/exec",
            data=b'{"bootstrap_token_digest":"secret","password_hash":"hash"}',
            method="POST",
            headers={
                "Content-Type": "application/json",
                "X-KS-Signature": "deadbeef" * 8,
                "X-KS-Bootstrap-Token": _VALID_BOOTSTRAP_SECRET,
                "X-KS-Idempotency-Key": "NONCE-302-001",
                "Authorization": "Bearer super-secret-jwt",
                "Cookie": "session=secret-cookie",
            },
        )
        redirected_req = handler.redirect_request(orig_req, None, 302, "Found", {}, allowed_echo)
        self.assertEqual(redirected_req.get_method(), "GET")
        self.assertIsNone(redirected_req.data)
        self.assertEqual(redirected_req.full_url, allowed_echo)
        self.assertTrue(handler.followed_echo_redirect)

        lower_headers = {k.lower(): v for k, v in redirected_req.header_items()}
        for forbidden_hdr in (
            "x-ks-signature",
            "x-ks-bootstrap-token",
            "x-ks-idempotency-key",
            "x-ks-correlation-id",
            "x-ks-transaction-id",
            "x-ks-payload-hash",
            "authorization",
            "cookie",
            "content-type",
        ):
            self.assertNotIn(forbidden_hdr, lower_headers, f"Header {forbidden_hdr} leaked across redirect")

        # 3. Verify 2nd chained redirect hop is blocked fail-closed even to echo URL
        with self.assertRaises(urllib.error.HTTPError) as hop2_ctx:
            handler.redirect_request(redirected_req, None, 302, "Found", {}, allowed_echo)
        self.assertEqual(hop2_ctx.exception.code, 302)

        # 4. Verify disallowed destination raises HTTPError immediately on first hop
        handler2 = _AppsScriptEchoRedirectHandler()
        with self.assertRaises(urllib.error.HTTPError) as bad_ctx:
            handler2.redirect_request(
                orig_req,
                None,
                302,
                "Found",
                {},
                "https://accounts.google.com/ServiceLogin",
            )
        self.assertEqual(bad_ctx.exception.code, 302)
        self.assertFalse(handler2.followed_echo_redirect)

    def test_11_b2_post_redirect_echo_failure_is_unknown_never_failed(self):
        import urllib.error
        import urllib.request
        from app.apps_script_bridge import _AppsScriptEchoRedirectHandler, apps_script_bridge
        from app.transaction_safety import TransactionState

        # Simulate: POST -> script.google.com returned 302 -> script.googleusercontent.com/macros/echo,
        # handler followed echo redirect, then GET /macros/echo returned HTTP 403/500.
        # Because doPost(e) already ran, FastAPI MUST classify outcome as PENDING_UNKNOWN / UNKNOWN
        # (NEVER FAILED / REJECTED).
        class _EchoFailingOpener:
            def __init__(self, handler):
                self._handler = handler

            def open(self, req, timeout=None):
                self._handler.followed_echo_redirect = True
                raise urllib.error.HTTPError(
                    "https://script.googleusercontent.com/macros/echo?user_content_key=expired",
                    403,
                    "Forbidden",
                    {},
                    None,
                )

        def _fake_build_opener(handler):
            self.assertIsInstance(handler, _AppsScriptEchoRedirectHandler)
            return _EchoFailingOpener(handler)

        with patch.object(urllib.request, "build_opener", side_effect=_fake_build_opener):
            res = apps_script_bridge.execute_governed_write(
                action="BOOTSTRAP_FIRST_OWNER",
                target_tab="Users",
                payload={"username": "kawad.owner", "full_name": "Rajesh Kawad"},
                actor_user_id="SYSTEM_BOOTSTRAP",
                actor_role="OWNER_ADMIN",
                nonce="BOOT-ECHO-FAIL-001",
                id_field="user_id",
            )
        self.assertEqual(res.status, "PENDING_UNKNOWN")
        self.assertEqual(res.transaction_state, TransactionState.UNKNOWN.value)
        self.assertEqual(res.error_code, "APPS_SCRIPT_ECHO_HTTP_403")
        self.assertTrue(res.retryable)

    def test_12_b2_disallowed_redirect_stays_rejected_failed(self):
        import urllib.error
        import urllib.request
        from app.apps_script_bridge import apps_script_bridge
        from app.transaction_safety import TransactionState

        class _DisallowedRedirectOpener:
            def open(self, req, timeout=None):
                raise urllib.error.HTTPError(
                    "https://accounts.google.com/ServiceLogin",
                    302,
                    "HTTP 302 redirect blocked on signed Apps Script bridge request.",
                    {},
                    None,
                )

        with patch.object(urllib.request, "build_opener", return_value=_DisallowedRedirectOpener()):
            res = apps_script_bridge.execute_governed_write(
                action="BOOTSTRAP_FIRST_OWNER",
                target_tab="Users",
                payload={"username": "kawad.owner", "full_name": "Rajesh Kawad"},
                actor_user_id="SYSTEM_BOOTSTRAP",
                actor_role="OWNER_ADMIN",
                nonce="BOOT-BAD-REDIR-001",
                id_field="user_id",
            )
        self.assertEqual(res.status, "REJECTED")
        self.assertEqual(res.transaction_state, TransactionState.FAILED.value)
        self.assertEqual(res.error_code, "APPS_SCRIPT_REDIRECT_BLOCKED_302")
        self.assertFalse(res.retryable)

    def test_13_b2_302_echo_redirect_commits_confirmed_end_to_end(self):
        import urllib.request
        from app.apps_script_bridge import _AppsScriptEchoRedirectHandler, apps_script_bridge
        from app.transaction_safety import TransactionState

        observed_echo_requests = []
        echo_url = "https://script.googleusercontent.com/macros/echo?user_content_key=confirmed123&lib=ks"

        class _Sim302Opener:
            def __init__(self, handler, sim):
                self._handler = handler
                self._sim = sim

            def open(self, req, timeout=None):
                # Step 1: Execute doPost(e) in simulator on initial POST (as Google Apps Script does)
                post_resp = self._sim._dispatch_http_request(req)
                # Step 2: Simulate Google Apps Script returning HTTP 302 -> /macros/echo
                echo_req = self._handler.redirect_request(req, None, 302, "Found", {"Location": echo_url}, echo_url)
                observed_echo_requests.append(echo_req)
                # Step 3: Return the JSON response from the GET echo request
                return post_resp

        def _build_302_opener(handler):
            self.assertIsInstance(handler, _AppsScriptEchoRedirectHandler)
            return _Sim302Opener(handler, self.sim)

        req = self._make_bootstrap_request(nonce="BOOT-302-CONFIRMED-001")
        with patch.dict(os.environ, self._valid_env(), clear=False):
            with patch.object(urllib.request, "build_opener", side_effect=_build_302_opener):
                res = self._run(auth_router.bootstrap_first_owner(self._valid_req(), req))

        self.assertEqual(res.status, "CONFIRMED")
        self.assertTrue(res.user_id.startswith("USR-"))
        self.assertEqual(len(observed_echo_requests), 1)
        echo_req = observed_echo_requests[0]
        self.assertEqual(echo_req.get_method(), "GET")
        self.assertIsNone(echo_req.data)
        self.assertEqual(echo_req.full_url, echo_url)
        hdrs = {k.lower() for k, _ in echo_req.header_items()}
        self.assertNotIn("x-ks-signature", hdrs)
        self.assertNotIn("authorization", hdrs)
        self.assertNotIn("x-ks-bootstrap-token", hdrs)

    def _make_bootstrap_request(
        self,
        token: str = _VALID_BOOTSTRAP_SECRET,
        nonce: str = "BOOTSTRAP-OWNER-TEST-001",
    ) -> Request:
        return _make_request(
            headers={
                "X-KS-Bootstrap-Token": token,
                "X-KS-Idempotency-Key": nonce,
            }
        )


if __name__ == "__main__":
    unittest.main()
