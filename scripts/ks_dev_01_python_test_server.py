#!/usr/bin/env python3
"""
KS-DEV-01 Isolated Local Development Auth Test Server (Loopback-Only, Offline).

Strictly for local development & Playwright E2E testing under SALES_TESTING=1.
Binds ONLY to 127.0.0.1:<port> (default 18000) and dispatches HTTP requests directly
into the real Kawad Swad ERP backend routers (auth, dashboard, workspace) backed
by LocalAppsScriptSimulator and in-memory Sheets tables. Never touches production.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

BACKEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "backend"))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

os.environ["SALES_TESTING"] = "1"
os.environ["SALES_ENV"] = "development"

# Enable a short-lived local-only test bootstrap window via env vars if provided by test runner
os.environ.setdefault("SALES_OWNER_BOOTSTRAP_ENABLED", "true")
os.environ.setdefault(
    "SALES_OWNER_BOOTSTRAP_EXPIRES_AT",
    (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
)

import tests  # noqa: F401, E402  (initializes offline FastAPI/Pydantic/JWT stdlib harness)
from fastapi import HTTPException, Request  # noqa: E402
from fastapi.security import HTTPAuthorizationCredentials  # noqa: E402
from app.auth import (  # noqa: E402
    _REVOKED_TOKENS,
    _USER_REVOKED_AT,
    create_access_token,
    get_current_user,
    hash_password,
)
from app.models import LoginRequest, OwnerSetupRequest  # noqa: E402
from app.routers import auth as auth_router  # noqa: E402
from app.routers import dashboard as dashboard_router  # noqa: E402
from app.routers import workspace as workspace_router  # noqa: E402
from app.sheets import db  # noqa: E402
from tests.v2_test_harness import LocalAppsScriptSimulator  # noqa: E402


class _BgTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *args, **kwargs):
        self.tasks.append((fn, args, kwargs))

    def flush(self):
        for fn, args, kwargs in self.tasks:
            fn(*args, **kwargs)


def _reset_dev_memory_db():
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


def _to_jsonable(obj):
    if hasattr(obj, "model_dump"):
        return obj.model_dump()
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_jsonable(v) for v in obj]
    return obj


class DevAuthBridgeHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Quiet logging; never log secrets or tokens
        pass

    def _send_json(self, status_code: int, payload: object):
        body = json.dumps(_to_jsonable(payload)).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict:
        length = int(self.headers.get("Content-Length") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8", errors="replace")
        return json.loads(raw) if raw.strip() else {}

    def _extract_bearer(self) -> HTTPAuthorizationCredentials | None:
        auth_hdr = self.headers.get("Authorization") or ""
        if auth_hdr.lower().startswith("bearer "):
            tok = auth_hdr[7:].strip()
            if tok:
                return HTTPAuthorizationCredentials(scheme="Bearer", credentials=tok)
        return None

    def _build_request(self, method: str, path: str, query_string: str) -> Request:
        raw_headers = [(k.lower().encode("latin-1"), v.encode("latin-1")) for k, v in self.headers.items()]
        return Request({
            "type": "http",
            "method": method,
            "path": path,
            "headers": raw_headers,
            "query_string": query_string.encode("latin-1"),
        })

    def do_GET(self):
        parsed = urlsplit(self.path)
        path = parsed.path
        try:
            if path in ("/health", "/api/health"):
                return self._send_json(200, {
                    "status": "ok",
                    "service": "kawad-swad-erp-api-dev-test",
                    "google_sheets_connected": True,
                    "persistent_writes_enabled": True,
                    "apps_script_bridge_configured": True,
                    "backend": {"status": "CONNECTED", "service": "kawad-swad-erp-api", "version": "1.0.0"},
                    "google_sheets": {"status": "CONNECTED", "connected": True},
                })

            if path in ("/api/auth/bootstrap-status", "/auth/bootstrap-status"):
                res = asyncio.run(auth_router.get_owner_bootstrap_status())
                return self._send_json(200, res)

            if path in ("/api/auth/me", "/auth/me"):
                creds = self._extract_bearer()
                user = asyncio.run(get_current_user(creds))
                res = asyncio.run(auth_router.get_me(current_user=user))
                return self._send_json(200, res)

            if path == "/api/dashboard":
                creds = self._extract_bearer()
                user = asyncio.run(get_current_user(creds))
                res = asyncio.run(dashboard_router.get_dashboard_metrics(current_user=user))
                return self._send_json(200, res)

            if path == "/api/workspace":
                creds = self._extract_bearer()
                user = asyncio.run(get_current_user(creds))
                res = asyncio.run(workspace_router.load_workspace(current_user=user))
                return self._send_json(200, res)

            if path == "/api/v2/meta/capabilities":
                creds = self._extract_bearer()
                asyncio.run(get_current_user(creds))
                return self._send_json(200, {
                    "apps_script_bridge_configured": True,
                    "persistent_writes_enabled": True,
                    "google_sheets_connected": True,
                })

            return self._send_json(404, {"detail": f"Route not found: {path}"})
        except HTTPException as exc:
            return self._send_json(exc.status_code, {"detail": exc.detail})
        except Exception as exc:
            return self._send_json(500, {"detail": str(exc)})

    def do_POST(self):
        parsed = urlsplit(self.path)
        path = parsed.path
        try:
            body = self._read_json_body()

            if path == "/api/auth/bootstrap-owner":
                req = self._build_request("POST", path, parsed.query)
                payload = OwnerSetupRequest(**body)
                res = asyncio.run(auth_router.bootstrap_first_owner(payload, req))
                return self._send_json(201, res)

            if path in ("/api/auth/login", "/auth/login"):
                bg = _BgTasks()
                payload = LoginRequest(**body)
                res = asyncio.run(auth_router.login(payload, bg))
                bg.flush()
                return self._send_json(200, res)

            if path in ("/api/auth/logout", "/auth/logout"):
                creds = self._extract_bearer()
                user = asyncio.run(get_current_user(creds))
                res = asyncio.run(auth_router.logout(credentials=creds, current_user=user))
                return self._send_json(200, res)

            # Test-only local harness helpers (gated strictly under SALES_TESTING=1 loopback)
            if path == "/__test__/seed-inactive-user":
                uname = str(body.get("username") or "inactive.user").strip().lower()
                pwd = str(body.get("password") or "")
                db.memory_store["AuthUsers"].append({
                    "auth_id": "AUTH-INACTIVE-E2E",
                    "user_id": "USR-000099",
                    "username": uname,
                    "full_name": "Inactive Test Staff",
                    "password_hash": hash_password(pwd),
                    "role": "FIELD_SALESMAN",
                    "active": "false",
                    "must_change_password": "false",
                    "sessions_revoked_at": "",
                })
                return self._send_json(200, {"ok": True})

            if path == "/__test__/mint-expired-token":
                uid = str(body.get("user_id") or "USR-000001")
                uname = str(body.get("username") or "owner.dev")
                tok = create_access_token(
                    {
                        "sub": uid,
                        "user_id": uid,
                        "username": uname,
                        "full_name": "Rajesh Kawad",
                        "role": "OWNER_ADMIN",
                        "must_change_password": False,
                    },
                    expires_delta=timedelta(seconds=-120),
                )
                return self._send_json(200, {"access_token": tok})

            return self._send_json(404, {"detail": f"Route not found: {path}"})
        except HTTPException as exc:
            return self._send_json(exc.status_code, {"detail": exc.detail})
        except Exception as exc:
            return self._send_json(500, {"detail": str(exc)})


def main():
    port = int(os.environ.get("KS_DEV_TEST_PORT", "18000"))
    _reset_dev_memory_db()
    sim = LocalAppsScriptSimulator().start()
    server = ThreadingHTTPServer(("127.0.0.1", port), DevAuthBridgeHandler)
    print(f"KS_DEV_AUTH_SERVER_READY http://127.0.0.1:{port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        sim.stop()


if __name__ == "__main__":
    main()
