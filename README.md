# Kawad Swad Sales Management System

This is a development starter application intended for manual upload to the separate `kawad-swad-sales-management` repository. It must not be connected to production ERP credentials or data.

## Included modules
- Authentication using signed JWT access tokens and PBKDF2-SHA256 password hashes
- Roles: `OWNER`, `PA`, `SALESMAN`
- Product catalogue
- Customer records
- Sales and single-payment full-payment bills
- PDF bill generation
- Salesman stock issuance ledger
- Shop visits
- Expense submission and approval
- Cash closing calculation
- Dashboard and monthly report
- XLSX exports
- Responsive browser UI

## First-time setup
1. Follow `docs/GOOGLE_SHEETS_SETUP.md`.
2. Create `AuthUsers` worksheet with the exact headers shown there.
3. Configure Render Secret File and environment variables.
4. Create the first Owner locally using `backend/scripts/bootstrap_owner.py`.
5. Serve the `frontend/` folder on a static host and configure the API base URL in `frontend/app.js`/hosting configuration.
6. Add the exact frontend origin to `SALES_CORS_ORIGINS`.

## Render backend
Root directory: `backend`
Build command: `pip install -r requirements.txt`
Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
Health check path: `/health`

## Safety and completeness
This is a broad initial implementation, not a certified production accounting/ERP system. Google Sheets lacks multi-row transactions and robust concurrent ID allocation. Sale creation currently supports one or more lines at the API level, but the included simple UI creates one line per bill. GST is intentionally not calculated because registration/tax configuration has not been confirmed. Authentication must be enabled and the unauthenticated starter endpoints should be replaced by this version before any real data is used. Review all permissions and test with a non-production spreadsheet before operational use.
