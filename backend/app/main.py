"""Development-only FastAPI entry point for Kawad Swad Sales Management.

This is a starter API. It deliberately does not import or mount the existing ERP routers.
It only uses the dedicated SALES_GOOGLE_* configuration.
"""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Any, Optional
from app.services.sales_management_sheets import SalesManagementSheets, SalesSheetsConfigError

app = FastAPI(
    title="Kawad Swad Sales Management API (Development)",
    version="0.1.0",
    description="Isolated development API for the Kawad Swad sales management system.",
)

_sheets: Optional[SalesManagementSheets] = None

def get_sheets() -> SalesManagementSheets:
    global _sheets
    if _sheets is None:
        try:
            _sheets = SalesManagementSheets.from_environment()
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"Sales Sheets configuration unavailable: {exc}") from exc
    return _sheets

@app.get("/")
def root() -> dict[str, str]:
    return {"service": "kawad-swad-sales-dev", "status": "ok", "docs": "/docs"}

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/api/sales/schema")
def schema_status() -> dict[str, Any]:
    """Return configured sales-sheet schema status without returning credentials."""
    sheets = get_sheets()
    try:
        return sheets.check_schema()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Unable to verify sales spreadsheet schema: {exc}") from exc

@app.get("/api/sales/{sheet_name}")
def list_sheet_records(sheet_name: str, limit: int = 100) -> dict[str, Any]:
    """Development-only read endpoint for approved sales-management tabs."""
    allowed = {
        "Users", "Products", "Customers", "Sales", "SaleItems", "Payments",
        "SalesmanStockLedger", "CashLedger", "Expenses", "ShopVisits",
        "DailyClosing", "SalaryIncentives", "AuditLog", "Settings",
    }
    if sheet_name not in allowed:
        raise HTTPException(status_code=404, detail="Unknown sales-management sheet")
    if limit < 1 or limit > 500:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 500")
    sheets = get_sheets()
    try:
        return {"sheet": sheet_name, "records": sheets.list_records(sheet_name, limit=limit)}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Unable to read sales sheet: {exc}") from exc
