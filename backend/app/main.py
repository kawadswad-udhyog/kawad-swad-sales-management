import logging
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
)


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kawad_swad")

app = FastAPI(
    title="Kawad Swad Sales Management API",
    description="FastAPI Google Sheets backend for Kawad Swad Udhyog sales, billing, stock, and expenses.",
    version="1.0.0",
)

if hasattr(app, "exception_handler"):
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception(f"Unhandled server error on {request.method} {request.url.path}: {exc}")
        return JSONResponse(
            status_code=500,
            content={"detail": "An internal server error occurred. Please contact the system administrator."},
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


@app.on_event("startup")
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

from app.permissions import require_manager, require_owner

@app.get("/health/live", tags=["System"])
def health_liveness():
    """Lightweight Kubernetes / Render liveness probe."""
    return {"status": "live", "service": "kawad-swad-sales-dev"}


@app.get("/health/ready", tags=["System"])
def health_readiness():
    """Readiness probe: validates application readiness and persistent storage capability."""
    is_ready = db.is_connected or db.allow_in_memory_fallback
    if not is_ready:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "service": "kawad-swad-sales-dev",
                "detail": db.last_connection_error or "Storage disconnected - writes paused",
            },
        )
    return {
        "status": "ready",
        "service": "kawad-swad-sales-dev",
        "persistent_writes_enabled": db.is_connected and db.spreadsheet is not None,
    }


@app.get("/health", tags=["System"])
@app.get("/api/health", tags=["System"])
def health_check():
    import os
    from app.config import (
        SALES_GOOGLE_SPREADSHEET_ID,
        SALES_GOOGLE_SERVICE_ACCOUNT_FILE,
        SALES_GOOGLE_SERVICE_ACCOUNT_JSON,
    )
    from app.sheets import REQUIRED_TABS

    is_persistent_ready = db.is_connected and db.spreadsheet is not None
    is_app_operational = is_persistent_ready or db.allow_in_memory_fallback

    status_str = "ok" if is_app_operational else "storage_disconnected"
    has_sa_file = bool(SALES_GOOGLE_SERVICE_ACCOUNT_FILE and os.path.exists(SALES_GOOGLE_SERVICE_ACCOUNT_FILE))
    has_sa_json = bool(SALES_GOOGLE_SERVICE_ACCOUNT_JSON and len(SALES_GOOGLE_SERVICE_ACCOUNT_JSON.strip()) > 10)

    # Subsystem: Google Auth
    if not SALES_GOOGLE_SPREADSHEET_ID:
        google_auth_state = "NOT_CONFIGURED"
    elif not (has_sa_file or has_sa_json):
        google_auth_state = "CREDENTIALS_MISSING"
    elif db.is_connected:
        google_auth_state = "AUTHENTICATED"
    else:
        google_auth_state = "AUTHENTICATION_FAILED"

    # Subsystem: Google Sheets & Storage
    if is_persistent_ready:
        gs_status = "CONNECTED"
        gs_message = "Google Sheets connected and accessible"
        write_capability = "ENABLED"
        persistent_storage = "ENABLED"
        backend_status = "CONNECTED"
        app_readiness = "READY"
    elif db.allow_in_memory_fallback:
        gs_status = "IN_MEMORY_FALLBACK"
        gs_message = "Operating in isolated in-memory test mode"
        write_capability = "ENABLED"
        persistent_storage = "TEST_ISOLATED"
        backend_status = "CONNECTED"
        app_readiness = "READY"
    else:
        gs_status = "DISCONNECTED"
        gs_message = db.last_connection_error or "Google Sheets connection failed"
        write_capability = "PAUSED"
        persistent_storage = "DISABLED"
        backend_status = "DEGRADED"
        app_readiness = "DEGRADED"

    return {
        "status": status_str,
        "service": "kawad-swad-sales-dev",
        "google_sheets_connected": db.is_connected,
        "persistent_writes_enabled": is_persistent_ready,
        "spreadsheet_id_configured": bool(SALES_GOOGLE_SPREADSHEET_ID),
        "service_account_configured": has_sa_file or has_sa_json,
        "last_connection_error": db.last_connection_error,
        "allow_in_memory_fallback": db.allow_in_memory_fallback,
        "subsystems": {
            "http_availability": "ONLINE",
            "application_readiness": app_readiness,
            "google_authentication": google_auth_state,
            "google_sheets_connectivity": "CONNECTED" if db.is_connected else "DISCONNECTED",
            "persistent_storage": persistent_storage,
            "write_capability": write_capability,
        },
        "backend": {
            "status": backend_status,
            "service": "kawad-swad-sales-dev",
            "version": "1.0.0",
            "readiness": app_readiness,
        },
        "google_sheets": {
            "status": gs_status,
            "connected": db.is_connected,
            "persistent_writes_enabled": is_persistent_ready,
            "message": gs_message,
        },
        "required_sheets": {
            "status": "AVAILABLE" if db.is_connected else ("STANDBY" if db.allow_in_memory_fallback else "NOT_VERIFIED"),
            "total_managed_tabs": len(REQUIRED_TABS),
        },
    }


@app.post("/health/reconnect", tags=["System"])
@app.post("/api/health/reconnect", tags=["System"])
def health_reconnect(current_user: dict = Depends(auth.get_current_user)):
    require_manager(current_user)
    success = db.reconnect()
    return {
        "success": success,
        "google_sheets_connected": db.is_connected,
        "persistent_writes_enabled": db.is_connected and db.spreadsheet is not None,
        "message": "Reconnected to Google Sheets successfully." if success else f"Reconnection failed: {db.last_connection_error}",
        "error": db.last_connection_error,
    }


@app.get("/health/verify-tabs", tags=["System"])
@app.get("/api/health/verify-tabs", tags=["System"])
def health_verify_tabs(current_user: dict = Depends(auth.get_current_user)):
    require_manager(current_user)
    return db.verify_tabs_accessibility()

@app.get("/health/backup", tags=["System"])
@app.get("/api/health/backup", tags=["System"])
def health_backup(current_user: dict = Depends(auth.get_current_user)):
    from app.permissions import require_owner
    from app.timeutil import now_iso
    from app.sheets import REQUIRED_TABS
    require_owner(current_user)
    snapshot = {}
    for tab in REQUIRED_TABS:
        try:
            snapshot[tab] = db.get_records(tab, fresh=False)
        except Exception as e:
            snapshot[tab] = {"error": str(e)}
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
