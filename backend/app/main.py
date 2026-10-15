"""Isolated development FastAPI entry point for Kawad Swad Sales Management."""
from fastapi import FastAPI, HTTPException, Query
from typing import Any
from app.services.sales_management_sheets import (
    SalesGoogleSheets,
    SalesSheetsConfigurationError,
    SalesSheetsSchemaError,
)

app = FastAPI(
    title="Kawad Swad Sales Management API (Development)",
    version="0.1.1",
    description="Isolated development starter; not the production ERP.",
)

def get_sheets() -> SalesGoogleSheets:
    try:
        return SalesGoogleSheets()
    except (SalesSheetsConfigurationError, SalesSheetsSchemaError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Sales Sheets configuration unavailable") from exc

@app.get("/")
def root() -> dict[str, str]:
    return {"service": "kawad-swad-sales-dev", "status": "ok", "docs": "/docs"}

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/api/sales/schema")
def schema_status() -> dict[str, Any]:
    # Reports configured tabs/headers without exposing credentials or spreadsheet data.
    sheets = get_sheets()
    result = {}
    for tab_name in sheets.headers:
        try:
            ws = sheets.worksheet(tab_name)
            result[tab_name] = {"status": "ok", "header_count": len(ws.row_values(1))}
        except Exception as exc:
            result[tab_name] = {"status": "error", "error": str(exc)}
    return {"sheets": result}

@app.get("/api/sales/{sheet_name}")
def list_sheet_records(
    sheet_name: str,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    allowed = {
        "Users", "Products", "Customers", "Sales", "SaleItems", "Payments",
        "SalesmanStockLedger", "CashLedger", "Expenses", "ShopVisits",
        "DailyClosing", "SalaryIncentives", "AuditLog", "Settings",
    }
    if sheet_name not in allowed:
        raise HTTPException(status_code=404, detail="Unknown sales-management sheet")
    try:
        records = get_sheets().list_records(sheet_name)
        return {"sheet": sheet_name, "records": records[:limit]}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Unable to read sales sheet: {exc}") from exc
