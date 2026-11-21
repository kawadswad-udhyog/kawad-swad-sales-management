import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Depends
try:
    from fastapi import Request
except ImportError:
    class Request:  # type: ignore
        pass
try:
    from fastapi.responses import JSONResponse
except ImportError:
    class JSONResponse:  # type: ignore
        def __init__(self, content, status_code=200):
            self.content = content
            self.status_code = status_code
from fastapi.middleware.cors import CORSMiddleware
from app.config import SALES_CORS_ORIGINS, SALES_ENV, assert_runtime_config
from app.sheets import db
from app.routers import (
    auth,
    users,
    products,
    customers,
    sales,
    stock,
    expenses,
    visits,
    closing,
    salary,
    dashboard,
    audit,
    production,
    workspace,
    approvals,
    accounting,
    purchasing,
    quality,
    workforce,
    v2_erp,
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kawad_swad")


def _check_configuration():
    import os
    if os.getenv("SALES_TESTING", "").strip() == "1":
        return
    try:
        assert_runtime_config()
    except Exception as exc:
        if SALES_ENV == "production":
            logger.critical("FATAL: Invalid production configuration: %s", exc)
            raise exc
        logger.error("Configuration warning on startup: %s", exc)


def _schedule_post_bind_sheets_init() -> None:
    """Schedule Google Sheets initialization strictly after Uvicorn binds $PORT."""
    import os
    if os.getenv("SALES_TESTING", "").strip() == "1":
        return
    try:
        loop = asyncio.get_running_loop()
        loop.call_later(0.05, db.start_background_init)
    except RuntimeError:
        db.start_background_init()


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI):
    _check_configuration()
    _schedule_post_bind_sheets_init()
    yield


app = FastAPI(
    title="Kawad Swad Sales Management API",
    description="FastAPI Google Sheets backend for Kawad Swad Udhyog sales, billing, stock, and expenses.",
    version="1.0.0",
    lifespan=lifespan,
)

if hasattr(app, "exception_handler"):
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        import uuid
        corr_id = (
            getattr(getattr(request, "headers", None), "get", lambda *_: None)("X-Correlation-Id")
            or f"CORR-{uuid.uuid4().hex[:12].upper()}"
        )
        logger.exception("Unhandled server error [%s] on %s %s: %s", corr_id, request.method, request.url.path, exc)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "An internal server error occurred. Please contact the system administrator.",
                "error_code": "INTERNAL_SERVER_ERROR",
                "correlation_id": corr_id,
                "retryable": False,
            },
        )

# Configure CORS
configured_origins = [o.strip().rstrip("/") for o in SALES_CORS_ORIGINS.split(",") if o.strip()]
default_origins = {
    "https://kawad-swad-sales-frontend.onrender.com",
}
if SALES_ENV != "production":
    default_origins.update({
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    })
origins = list(default_origins.union(configured_origins))

cors_kwargs = {
    "allow_origins": origins,
    "allow_credentials": True,
    "allow_methods": ["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    "allow_headers": ["*"],
    "expose_headers": ["*"],
}

if SALES_ENV != "production":
    cors_kwargs["allow_origin_regex"] = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"

app.add_middleware(
    CORSMiddleware,
    **cors_kwargs,
)

# Register Routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(approvals.router)
app.include_router(products.router)
app.include_router(customers.router)
app.include_router(sales.router)
app.include_router(stock.router)
app.include_router(expenses.router)
app.include_router(visits.router)
app.include_router(closing.router)
app.include_router(salary.router)
app.include_router(dashboard.router)
app.include_router(audit.router)
app.include_router(production.router)
app.include_router(workspace.router)
app.include_router(accounting.router)
app.include_router(purchasing.router)
app.include_router(quality.router)
app.include_router(workforce.router)
app.include_router(v2_erp.router)


def _sanitize_diagnostic_error(err: Optional[str]) -> Optional[str]:
    """Redact spreadsheet IDs, file paths, service-account emails, and secret keys from diagnostic messages."""
    if not err:
        return None
    import os
    import re
    from app.config import (
        SALES_GOOGLE_SPREADSHEET_ID,
        SALES_GOOGLE_SERVICE_ACCOUNT_FILE,
    )

    msg = str(err)
    for sensitive in (
        SALES_GOOGLE_SPREADSHEET_ID,
        SALES_GOOGLE_SERVICE_ACCOUNT_FILE,
        os.getenv("SALES_JWT_SECRET", "").strip(),
    ):
        if sensitive and len(sensitive) > 3:
            msg = msg.replace(sensitive, "[REDACTED]")

    msg = re.sub(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
        "[REDACTED_PRIVATE_KEY]",
        msg,
    )
    msg = re.sub(r'"private_key"\s*:\s*"[^"]*"', '"private_key": "[REDACTED]"', msg)
    msg = re.sub(
        r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.iam\.gserviceaccount\.com",
        "[REDACTED_SERVICE_ACCOUNT]",
        msg,
    )
    msg = re.sub(r"/(?:etc/secrets|tmp|var|app|home)/[^\s'\"]+\.json", "[REDACTED_PATH]", msg)
    return msg


def _sanitize_diagnostic_payload(payload: dict) -> dict:
    """Recursively sanitize error/diagnostic string fields in diagnostic payloads."""
    sanitized = dict(payload)
    if "error" in sanitized and isinstance(sanitized["error"], str):
        sanitized["error"] = _sanitize_diagnostic_error(sanitized["error"])
    if "diagnostics" in sanitized and isinstance(sanitized["diagnostics"], str):
        sanitized["diagnostics"] = _sanitize_diagnostic_error(sanitized["diagnostics"])
    if isinstance(sanitized.get("tabs"), dict):
        sanitized["tabs"] = {
            tab: (
                {**info, "error": _sanitize_diagnostic_error(info["error"])}
                if isinstance(info, dict) and isinstance(info.get("error"), str)
                else info
            )
            for tab, info in sanitized["tabs"].items()
        }
    if isinstance(sanitized.get("unreadable_tabs"), dict):
        sanitized["unreadable_tabs"] = {
            tab: (
                {**info, "error": _sanitize_diagnostic_error(info["error"])}
                if isinstance(info, dict) and isinstance(info.get("error"), str)
                else info
            )
            for tab, info in sanitized["unreadable_tabs"].items()
        }
    return sanitized


@app.get("/health", tags=["System"])
@app.get("/api/health", tags=["System"])
def health_check():
    """Public minimal liveness & connectivity check for Render and frontend pre-login indicator."""
    status_str = "ok" if db.is_connected else "storage_disconnected"
    persistent_writes = bool(db.is_connected and db.spreadsheet is not None)
    return {
        "status": status_str,
        "service": "kawad-swad-sales-dev",
        "google_sheets_connected": bool(db.is_connected),
        "persistent_writes_enabled": persistent_writes,
        "backend": {
            "status": "CONNECTED",
            "service": "kawad-swad-sales-dev",
            "version": "1.0.0",
        },
    }


@app.get("/health/details", tags=["System"])
@app.get("/api/health/details", tags=["System"])
def health_details(current_user: dict = Depends(auth.get_current_user)):
    """Authenticated Owner/PA infrastructure & storage configuration diagnostics."""
    import os
    from app.config import (
        SALES_GOOGLE_SPREADSHEET_ID,
        SALES_GOOGLE_SERVICE_ACCOUNT_FILE,
        SALES_GOOGLE_SERVICE_ACCOUNT_JSON,
    )
    from app.permissions import require_manager
    from app.sheets import REQUIRED_TABS

    require_manager(current_user)
    status_str = "ok" if db.is_connected else "storage_disconnected"
    has_sa_file = bool(SALES_GOOGLE_SERVICE_ACCOUNT_FILE and os.path.exists(SALES_GOOGLE_SERVICE_ACCOUNT_FILE))
    has_sa_json = bool(SALES_GOOGLE_SERVICE_ACCOUNT_JSON and len(SALES_GOOGLE_SERVICE_ACCOUNT_JSON.strip()) > 10)
    sanitized_error = _sanitize_diagnostic_error(db.last_connection_error)

    if not SALES_GOOGLE_SPREADSHEET_ID:
        gs_status = "NOT_CONFIGURED"
        gs_message = "Spreadsheet ID is not configured in environment"
    elif not (has_sa_file or has_sa_json):
        gs_status = "CREDENTIALS_MISSING"
        gs_message = "Service account credentials are not configured"
    elif db.is_connected and db.spreadsheet is not None:
        gs_status = "CONNECTED"
        gs_message = "Google Sheets connected and accessible"
    else:
        gs_status = "ERROR"
        gs_message = sanitized_error or "Google Sheets connection failed"

    return {
        "status": status_str,
        "service": "kawad-swad-sales-dev",
        "google_sheets_connected": bool(db.is_connected),
        "persistent_writes_enabled": bool(db.is_connected and db.spreadsheet is not None),
        "spreadsheet_id_configured": bool(SALES_GOOGLE_SPREADSHEET_ID),
        "service_account_configured": has_sa_file or has_sa_json,
        "last_connection_error": sanitized_error,
        "allow_in_memory_fallback": bool(db.allow_in_memory_fallback),
        "backend": {
            "status": "CONNECTED",
            "service": "kawad-swad-sales-dev",
            "version": "1.0.0",
        },
        "google_sheets": {
            "status": gs_status,
            "connected": bool(db.is_connected),
            "persistent_writes_enabled": bool(db.is_connected and db.spreadsheet is not None),
            "message": gs_message,
        },
        "required_sheets": {
            "status": "AVAILABLE" if db.is_connected else "NOT_VERIFIED",
            "total_managed_tabs": len(REQUIRED_TABS),
        },
    }


@app.post("/health/reconnect", tags=["System"])
@app.post("/api/health/reconnect", tags=["System"])
def health_reconnect(current_user: dict = Depends(auth.get_current_user)):
    from app.permissions import require_manager

    require_manager(current_user)
    success = db.reconnect()
    sanitized_error = _sanitize_diagnostic_error(db.last_connection_error)
    return {
        "success": success,
        "google_sheets_connected": bool(db.is_connected),
        "persistent_writes_enabled": bool(db.is_connected and db.spreadsheet is not None),
        "message": "Reconnected to Google Sheets successfully." if success else f"Reconnection failed: {sanitized_error}",
        "error": sanitized_error,
    }


@app.get("/health/verify-tabs", tags=["System"])
@app.get("/api/health/verify-tabs", tags=["System"])
def health_verify_tabs(refresh: bool = False, current_user: dict = Depends(auth.get_current_user)):
    from app.permissions import require_manager

    require_manager(current_user)
    return _sanitize_diagnostic_payload(db.verify_tabs_accessibility(force_refresh=bool(refresh)))


@app.get("/health/schema-compatibility", tags=["System"])
@app.get("/api/health/schema-compatibility", tags=["System"])
def health_schema_compatibility(refresh: bool = False, current_user: dict = Depends(auth.get_current_user)):
    from app.permissions import require_manager

    require_manager(current_user)
    return _sanitize_diagnostic_payload(db.inspect_schema_compatibility(force_refresh=bool(refresh)))

@app.get("/health/backup", tags=["System"])
@app.get("/api/health/backup", tags=["System"])
def health_backup(current_user: dict = Depends(auth.get_current_user)):
    from app.permissions import require_owner
    from app.schema_registry import NEVER_EXPOSE_CREDENTIAL_FIELDS
    from app.timeutil import now_iso
    from app.sheets import REQUIRED_TABS
    require_owner(current_user)
    snapshot = {}
    for tab in REQUIRED_TABS:
        try:
            rows = db.get_records(tab, fresh=False)
            if isinstance(rows, list):
                snapshot[tab] = [
                    {
                        k: v for k, v in row.items()
                        if str(k).strip().lower() not in NEVER_EXPOSE_CREDENTIAL_FIELDS
                    }
                    if isinstance(row, dict)
                    else row
                    for row in rows
                ]
            else:
                snapshot[tab] = rows
        except Exception as e:
            snapshot[tab] = {"error": _sanitize_diagnostic_error(str(e)) or "Tab read failed"}
    return {
        "timestamp": now_iso(),
        "exported_by": current_user.get("user_id"),
        "total_tabs": len(snapshot),
        "data": snapshot,
    }

@app.get("/", tags=["System"])
def root():
    return {
        "name": "Kawad Swad Sales Management API",
        "version": "1.0.0",
        "docs_url": "/docs",
        "health_check": "/health",
        "status": "ready",
    }
