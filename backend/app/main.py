import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import SALES_CORS_ORIGINS, assert_runtime_config
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
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("kawad_swad")

app = FastAPI(
    title="Kawad Swad Sales Management API",
    description="FastAPI Google Sheets backend for Kawad Swad Udhyog sales, billing, stock, and expenses.",
    version="1.0.0",
)

# Configure CORS
origins = [o.strip() for o in SALES_CORS_ORIGINS.split(",") if o.strip()]
if not origins or "*" in origins:
    origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True if "*" not in origins else False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register Routers
app.include_router(auth.router)
app.include_router(users.router)
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


@app.on_event("startup")
def _check_configuration():
    import os
    if os.getenv("SALES_TESTING", "").strip() == "1":
        return
    assert_runtime_config()

@app.get("/health", tags=["System"])
def health_check():
    return {
        "status": "ok",
        "service": "kawad-swad-sales-backend",
        "google_sheets_connected": db.is_connected,
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
