# Kawad Swad Sales Management API (Development Starter)

This API is intentionally isolated from the existing ERP application. It does not mount or import the production ERP routers.

## Local run
From the `backend` directory:
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload
```

## Routes
- `GET /` service identity
- `GET /health` health check
- `GET /docs` interactive API docs
- `GET /api/sales/schema` verifies the configured sales spreadsheet schema
- `GET /api/sales/{sheet_name}?limit=100` reads from an allowlisted sales-management sheet

## Environment
- `SALES_GOOGLE_SPREADSHEET_ID`
- `SALES_GOOGLE_SERVICE_ACCOUNT_FILE`

Do not configure the existing ERP spreadsheet environment variable as a fallback. Do not use this starter with production data before authentication, role checks, validation, and audit controls are added.

This is not yet a full sales application: it does not yet provide login, sales creation, payments, stock movements, cash closing, expenses approval, Excel exports, or a frontend.
