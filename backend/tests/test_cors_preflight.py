"""
Tests verifying CORS origins configuration, preflight handling, and security rules.
"""
import os
os.environ.setdefault("SALES_TESTING", "1")
os.environ.setdefault("SALES_JWT_SECRET", "test-only-secret-do-not-use-for-deployment-32")

import sys
import types
import unittest
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

if "fastapi" not in sys.modules:
    mock_fastapi = types.ModuleType("fastapi")
    class MockFastAPI:
        def __init__(self, *args, **kwargs):
            self.middleware = []
        def add_middleware(self, mw, **kwargs):
            self.middleware.append((mw, kwargs))
        def include_router(self, *args, **kwargs):
            pass
        def on_event(self, *args, **kwargs):
            return lambda f: f
        def get(self, *args, **kwargs):
            return lambda f: f
        def post(self, *args, **kwargs):
            return lambda f: f
    class MockAPIRouter:
        def __init__(self, *args, **kwargs): pass
        def get(self, *args, **kwargs): return lambda f: f
        def post(self, *args, **kwargs): return lambda f: f
        def put(self, *args, **kwargs): return lambda f: f
        def patch(self, *args, **kwargs): return lambda f: f
        def delete(self, *args, **kwargs): return lambda f: f
    class MockHTTPException(Exception):
        def __init__(self, status_code=500, detail=None, headers=None):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail
            self.headers = headers
    class MockStatus:
        HTTP_400_BAD_REQUEST = 400
        HTTP_401_UNAUTHORIZED = 401
        HTTP_403_FORBIDDEN = 403
        HTTP_404_NOT_FOUND = 404
        HTTP_409_CONFLICT = 409
        HTTP_422_UNPROCESSABLE_ENTITY = 422
        HTTP_500_INTERNAL_SERVER_ERROR = 500
        HTTP_503_SERVICE_UNAVAILABLE = 503
    class MockBackgroundTasks:
        def add_task(self, *args, **kwargs): pass

    mock_fastapi.FastAPI = MockFastAPI
    mock_fastapi.APIRouter = MockAPIRouter
    mock_fastapi.HTTPException = MockHTTPException
    mock_fastapi.status = MockStatus
    mock_fastapi.Depends = lambda f: f
    mock_fastapi.BackgroundTasks = MockBackgroundTasks
    mock_fastapi.Header = lambda default=None, **kwargs: default
    mock_fastapi.Query = lambda default=None, **kwargs: default

    mock_sec = types.ModuleType("fastapi.security")
    mock_sec.HTTPBearer = lambda **kwargs: None
    mock_sec.HTTPAuthorizationCredentials = None

    class MockCORSMiddleware: pass
    mock_mw = types.ModuleType("fastapi.middleware")
    mock_cors = types.ModuleType("fastapi.middleware.cors")
    mock_cors.CORSMiddleware = MockCORSMiddleware
    mock_fastapi.middleware = mock_mw

    sys.modules["fastapi"] = mock_fastapi
    sys.modules["fastapi.security"] = mock_sec
    sys.modules["fastapi.middleware"] = mock_mw
    sys.modules["fastapi.middleware.cors"] = mock_cors

if "pydantic" not in sys.modules:
    class MockBaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
        def dict(self):
            return self.__dict__
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
from app.main import origins, app


class TestCorsConfiguration(unittest.TestCase):
    def test_production_frontend_in_allowed_origins(self):
        """Verify that the official Render frontend origin is unconditionally allowed."""
        self.assertIn("https://kawad-swad-sales-frontend.onrender.com", origins)

    def test_local_dev_origins_allowed(self):
        """Verify localhost:3000 is permitted for development."""
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
