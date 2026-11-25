"""
Backend test package initialization.
Configures test environment and mock framework stubs so tests execute cleanly in pure Python 3.10 standard library.
"""
import os
import sys
import types
from unittest.mock import MagicMock

os.environ["SALES_TESTING"] = "1"
os.environ.setdefault("SALES_JWT_SECRET", "test-only-secret-do-not-use-for-deployment-32")

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
            HTTP_200_OK = 200
            HTTP_201_CREATED = 201
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
        class Request:
            def __init__(self, scope=None, headers=None, query_params=None):
                import urllib.parse as _urlparse
                raw = dict(headers or {})
                qp = dict(query_params or {})
                if isinstance(scope, dict):
                    for k, v in scope.get("headers") or []:
                        ks = k.decode("latin-1") if isinstance(k, (bytes, bytearray)) else str(k)
                        vs = v.decode("latin-1") if isinstance(v, (bytes, bytearray)) else str(v)
                        raw[ks] = vs
                    qs = scope.get("query_string") or b""
                    qs_str = qs.decode("latin-1") if isinstance(qs, (bytes, bytearray)) else str(qs)
                    if qs_str:
                        for qk, qv in _urlparse.parse_qsl(qs_str, keep_blank_values=True):
                            qp[qk] = qv
                class _CIHeaders(dict):
                    def get(self, key, default=None):
                        kl = str(key).lower()
                        for k, v in self.items():
                            if str(k).lower() == kl:
                                return v
                        return default
                    def __contains__(self, key):
                        kl = str(key).lower()
                        return any(str(k).lower() == kl for k in self.keys())
                self.headers = _CIHeaders(raw)
                self.query_params = qp
        @staticmethod
        def Depends(f): return f
        @staticmethod
        def Header(default=None, alias=None): return default
        @staticmethod
        def Query(default=None, **kwargs): return default

    mock_mod = MockFastAPIModule("fastapi")
    mock_mod.FastAPI = MockFastAPIModule.FastAPI
    mock_mod.BackgroundTasks = MockFastAPIModule.BackgroundTasks
    mock_mod.Request = MockFastAPIModule.Request
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
    from datetime import datetime as _dt
    mock_jwt = types.ModuleType("jwt")
    def mock_encode(payload, secret, algorithm="HS256"):
        safe_payload = {}
        for k, v in payload.items():
            if isinstance(v, _dt):
                safe_payload[k] = int(v.timestamp())
            else:
                safe_payload[k] = v
        header = base64.urlsafe_b64encode(json.dumps({"alg": algorithm, "typ": "JWT"}).encode()).rstrip(b"=").decode()
        body = base64.urlsafe_b64encode(json.dumps(safe_payload).encode()).rstrip(b"=").decode()
        sig = base64.urlsafe_b64encode(hmac.new(secret.encode(), f"{header}.{body}".encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
        return f"{header}.{body}.{sig}"
    def mock_decode(token, secret, algorithms=None):
        import time as _time
        if not isinstance(token, str):
            raise ValueError("Invalid token")
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Invalid token")
        expected_sig = base64.urlsafe_b64encode(
            hmac.new(secret.encode(), f"{parts[0]}.{parts[1]}".encode(), hashlib.sha256).digest()
        ).rstrip(b"=").decode()
        if not hmac.compare_digest(parts[2], expected_sig):
            raise ValueError("Invalid token signature")
        pad = len(parts[1]) % 4
        body = base64.urlsafe_b64decode(parts[1] + "=" * (4 - pad if pad else 0))
        payload = json.loads(body.decode())
        exp = payload.get("exp")
        if exp is not None:
            try:
                if _time.time() > float(exp):
                    raise ValueError("Token has expired")
            except (TypeError, ValueError) as exc:
                raise ValueError(str(exc)) from exc
        return payload
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
