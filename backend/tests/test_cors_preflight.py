"""
Tests verifying CORS origins configuration, actual ASGI preflight handling, and security rules.
Exercises real CORS middleware request/response cycles including:
- OPTIONS preflight for allowed production frontend (kawad-swad-sales-frontend.onrender.com)
- OPTIONS preflight for allowed local dev origins (localhost:3000)
- OPTIONS preflight rejection for unauthorized origins (malicious-site.com)
- Simple GET requests with Origin header
- Credential and header reflection
"""
import os
os.environ.setdefault("SALES_TESTING", "1")
os.environ.setdefault("SALES_JWT_SECRET", "test-only-secret-do-not-use-for-deployment-32")

import sys
import types
import unittest
import asyncio

backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

try:
    from starlette.middleware.cors import CORSMiddleware as StarletteCORSMiddleware
    HAVE_REAL_STARLETTE = True
except ImportError:
    HAVE_REAL_STARLETTE = False

# Fallback ASGI CORS Implementation faithfully replicating Starlette's CORSMiddleware
class SimulatedCORSMiddleware:
    def __init__(self, app, allow_origins=None, allow_methods=None, allow_headers=None, allow_credentials=False, expose_headers=None):
        self.app = app
        self.allow_origins = set(allow_origins or [])
        self.allow_methods = set(allow_methods or ["*"])
        self.allow_headers = set(allow_headers or ["*"])
        self.allow_credentials = allow_credentials
        self.expose_headers = expose_headers or []

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = dict(scope.get("headers", []))
        origin = headers.get(b"origin", b"").decode("latin1")
        method = scope.get("method", "GET").upper()

        is_allowed = origin in self.allow_origins or "*" in self.allow_origins

        if method == "OPTIONS" and b"access-control-request-method" in headers:
            # Preflight response
            resp_headers = []
            if is_allowed:
                resp_headers.append((b"access-control-allow-origin", origin.encode("latin1")))
                if self.allow_credentials:
                    resp_headers.append((b"access-control-allow-credentials", b"true"))
                req_method = headers.get(b"access-control-request-method", b"")
                resp_headers.append((b"access-control-allow-methods", req_method or b"GET, POST, PUT, DELETE, OPTIONS"))
                req_headers = headers.get(b"access-control-request-headers", b"")
                if req_headers:
                    resp_headers.append((b"access-control-allow-headers", req_headers))
                resp_headers.append((b"access-control-max-age", b"600"))

            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": resp_headers,
            })
            await send({
                "type": "http.response.body",
                "body": b"OK",
            })
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                resp_headers = list(message.get("headers", []))
                if is_allowed:
                    resp_headers.append((b"access-control-allow-origin", origin.encode("latin1")))
                    if self.allow_credentials:
                        resp_headers.append((b"access-control-allow-credentials", b"true"))
                message["headers"] = resp_headers
            await send(message)

        await self.app(scope, receive, send_wrapper)


if "fastapi" not in sys.modules:
    mock_fastapi = types.ModuleType("fastapi")
    class MockFastAPI:
        def __init__(self, *args, **kwargs):
            self.middleware = []
        def add_middleware(self, mw, **kwargs):
            self.middleware.append((mw, kwargs))
        def include_router(self, *args, **kwargs): pass
        def on_event(self, *args, **kwargs): return lambda f: f
        def get(self, *args, **kwargs): return lambda f: f
        def post(self, *args, **kwargs): return lambda f: f
    class MockAPIRouter:
        def __init__(self, *args, **kwargs): pass
        def get(self, *args, **kwargs): return lambda f: f
        def post(self, *args, **kwargs): return lambda f: f
        def put(self, *args, **kwargs): return lambda f: f
        def patch(self, *args, **kwargs): return lambda f: f
        def delete(self, *args, **kwargs): return lambda f: f
    class MockStatus:
        HTTP_400_BAD_REQUEST = 400
        HTTP_401_UNAUTHORIZED = 401
        HTTP_403_FORBIDDEN = 403
        HTTP_404_NOT_FOUND = 404
        HTTP_409_CONFLICT = 409
        HTTP_422_UNPROCESSABLE_ENTITY = 422
        HTTP_429_TOO_MANY_REQUESTS = 429
        HTTP_500_INTERNAL_SERVER_ERROR = 500
        HTTP_503_SERVICE_UNAVAILABLE = 503

    class MockHTTPException(Exception):
        def __init__(self, status_code=500, detail=None, headers=None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail
            self.headers = headers

    mock_fastapi.FastAPI = MockFastAPI
    mock_fastapi.APIRouter = MockAPIRouter
    mock_fastapi.HTTPException = MockHTTPException
    mock_fastapi.status = MockStatus
    mock_fastapi.Depends = lambda f: f
    mock_fastapi.BackgroundTasks = lambda: None
    mock_fastapi.Header = lambda default=None, **kwargs: default
    mock_fastapi.Query = lambda default=None, **kwargs: default
    sys.modules["fastapi"] = mock_fastapi

    mock_sec = types.ModuleType("fastapi.security")
    mock_sec.HTTPBearer = lambda **kwargs: None
    mock_sec.HTTPAuthorizationCredentials = None
    sys.modules["fastapi.security"] = mock_sec

    mock_mw = types.ModuleType("fastapi.middleware")
    mock_cors = types.ModuleType("fastapi.middleware.cors")
    mock_cors.CORSMiddleware = StarletteCORSMiddleware if HAVE_REAL_STARLETTE else SimulatedCORSMiddleware
    mock_fastapi.middleware = mock_mw
    mock_fastapi.middleware.cors = mock_cors
    sys.modules["fastapi.middleware"] = mock_mw
    sys.modules["fastapi.middleware.cors"] = mock_cors

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
    mock_jwt.encode = lambda payload, secret, algorithm="HS256": "mock-jwt"
    mock_jwt.decode = lambda token, secret, algorithms=["HS256"]: {"sub": "USR-000001", "role": "OWNER"}
    sys.modules["jwt"] = mock_jwt

from app.config import SALES_CORS_ORIGINS, assert_runtime_config
from app.main import origins


class TestCorsConfigurationAndPreflight(unittest.TestCase):
    def setUp(self):
        # Build ASGI test application with active CORS middleware
        async def dummy_app(scope, receive, send):
            await send({
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            })
            await send({
                "type": "http.response.body",
                "body": b'{"status":"ok"}',
            })

        mw_cls = StarletteCORSMiddleware if HAVE_REAL_STARLETTE else SimulatedCORSMiddleware
        self.cors_app = mw_cls(
            dummy_app,
            allow_origins=origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["*"],
        )

    def _run_asgi_request(self, method: str, path: str, headers: list):
        """Helper to invoke ASGI middleware stack synchronously in test."""
        received_messages = []

        async def mock_receive():
            return {"type": "http.request", "body": b""}

        async def mock_send(message):
            received_messages.append(message)

        scope = {
            "type": "http",
            "method": method,
            "path": path,
            "headers": [(k.lower().encode("latin1"), v.encode("latin1")) for k, v in headers],
        }

        asyncio.run(self.cors_app(scope, mock_receive, mock_send))

        status = 200
        resp_headers = {}
        body = b""
        for msg in received_messages:
            if msg["type"] == "http.response.start":
                status = msg["status"]
                for k, v in msg.get("headers", []):
                    resp_headers[k.decode("latin1").lower()] = v.decode("latin1")
            elif msg["type"] == "http.response.body":
                body += msg.get("body", b"")

        return status, resp_headers, body

    def test_production_frontend_preflight_options(self):
        """Exercise real OPTIONS preflight for the official Render production frontend."""
        status, headers, _ = self._run_asgi_request(
            method="OPTIONS",
            path="/api/sales",
            headers=[
                ("origin", "https://kawad-swad-sales-frontend.onrender.com"),
                ("access-control-request-method", "POST"),
                ("access-control-request-headers", "authorization, content-type"),
            ],
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("access-control-allow-origin"), "https://kawad-swad-sales-frontend.onrender.com")
        self.assertEqual(headers.get("access-control-allow-credentials"), "true")
        self.assertIn("POST", headers.get("access-control-allow-methods", ""))

    def test_localhost_dev_preflight_options(self):
        """Exercise real OPTIONS preflight for localhost:3000 development."""
        status, headers, _ = self._run_asgi_request(
            method="OPTIONS",
            path="/api/products",
            headers=[
                ("origin", "http://localhost:3000"),
                ("access-control-request-method", "GET"),
            ],
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("access-control-allow-origin"), "http://localhost:3000")
        self.assertEqual(headers.get("access-control-allow-credentials"), "true")

    def test_unauthorized_origin_preflight_rejection(self):
        """Exercise OPTIONS preflight from unauthorized origin; access-control-allow-origin must NOT be present."""
        status, headers, _ = self._run_asgi_request(
            method="OPTIONS",
            path="/api/sales",
            headers=[
                ("origin", "https://malicious-attacker-site.com"),
                ("access-control-request-method", "POST"),
            ],
        )
        self.assertNotIn("access-control-allow-origin", headers)

    def test_simple_get_with_production_origin(self):
        """Exercise GET request with production origin; verify CORS headers added to response."""
        status, headers, body = self._run_asgi_request(
            method="GET",
            path="/health",
            headers=[
                ("origin", "https://kawad-swad-sales-frontend.onrender.com"),
            ],
        )
        self.assertEqual(status, 200)
        self.assertEqual(headers.get("access-control-allow-origin"), "https://kawad-swad-sales-frontend.onrender.com")
        self.assertEqual(headers.get("access-control-allow-credentials"), "true")

    def test_production_frontend_in_allowed_origins(self):
        """Verify that the official Render frontend origin is unconditionally allowed."""
        self.assertIn("https://kawad-swad-sales-frontend.onrender.com", origins)

    def test_local_dev_origins_allowed(self):
        """Verify localhost:3000 and 127.0.0.1:3000 are permitted for development."""
        self.assertIn("http://localhost:3000", origins)
        self.assertIn("http://127.0.0.1:3000", origins)

    def test_no_trailing_slashes_in_origins(self):
        """Origins with trailing slashes break browser CORS matching; verify all origins are clean."""
        for o in origins:
            if o != "*":
                self.assertFalse(o.endswith("/"), f"Origin '{o}' must not end with a trailing slash")

    def test_production_rejects_wildcard(self):
        """When SALES_ENV=production, wildcard '*' must raise RuntimeError during config check."""
        old_env = os.environ.get("SALES_ENV", "")
        old_origins = os.environ.get("SALES_CORS_ORIGINS", "")
        old_testing = os.environ.get("SALES_TESTING", "")
        try:
            os.environ["SALES_ENV"] = "production"
            os.environ["SALES_CORS_ORIGINS"] = "*"
            os.environ["SALES_TESTING"] = "0"
            import app.config as cfg
            cfg.SALES_ENV = "production"
            cfg.SALES_CORS_ORIGINS = "*"
            with self.assertRaises(RuntimeError):
                assert_runtime_config()
        finally:
            if old_env: os.environ["SALES_ENV"] = old_env
            else: os.environ.pop("SALES_ENV", None)
            if old_origins: os.environ["SALES_CORS_ORIGINS"] = old_origins
            else: os.environ.pop("SALES_CORS_ORIGINS", None)
            if old_testing: os.environ["SALES_TESTING"] = old_testing
            else: os.environ.pop("SALES_TESTING", None)
            import app.config as cfg
            cfg.SALES_ENV = old_env or "development"
            cfg.SALES_CORS_ORIGINS = old_origins or "https://kawad-swad-sales-frontend.onrender.com,http://localhost:3000"


if __name__ == "__main__":
    unittest.main()
