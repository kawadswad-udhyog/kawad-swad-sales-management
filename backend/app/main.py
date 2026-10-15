"""Isolated development FastAPI entry point for Kawad Swad Sales Management."""
from fastapi import FastAPI, HTTPException, Query
from typing import Any
from app.services.sales_management_sheets import (
    SalesGoogleSheets,
    SalesSheetsConfigurationError,
    SalesSheetsSchemaError,
    SALES_HEADERS,
)

app = FastAPI(
    title="Kawad Swad Sales Management API (Development)",
    version="0.1.2",
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
    # Use the module-level schema contract; SalesGoogleSheets has no .headers attribute.
    sheets = get_sheets()
    result: dict[str, Any] = {}
    for tab_name in SALES_HEADERS:
        try:
            worksheet = sheets.worksheet(tab_name)
            result[tab_name] = {"status": "ok", "header_count": len(worksheet.row_values(1))}
        except Exception as exc:
            # Avoid returning credential details or other sensitive internals.
            result[tab_name] = {"status": "error", "error": str(exc)}
    return {"sheets": result}

@app.get("/api/sales/{sheet_name}")
def list_sheet_records(
    sheet_name: str,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    if sheet_name not in SALES_HEADERS:
        raise HTTPException(status_code=404, detail="Unknown sales-management sheet")
    try:
        records = get_sheets().list_records(sheet_name)
        return {"sheet": sheet_name, "records": records[:limit]}
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Unable to read sales sheet: {exc}") from exc
