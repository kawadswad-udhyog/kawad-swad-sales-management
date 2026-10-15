# Kawad Swad Sales Management: Updated Upload Package

## What is included
This package retains the existing FastAPI + Google Sheets backend and static browser frontend, with an improved Stage 2/3 interface:
- Product catalogue: add products, search/filter, edit permitted fields, activate/deactivate products.
- Customer and retailer management: add retail customers, retailers, wholesalers, and distributors; search by shop, contact, phone, area, or city.
- Existing sales, expenses, visits, dashboard, and export screens are retained from the supplied project.
- Existing API security and Google Sheets integration files are retained.

## Upload to the existing GitHub repository
1. Extract this ZIP.
2. Open the extracted `kawad-swad-sales-management-main` folder.
3. Upload/replace the **contents** of that folder at the root of the existing repository `kawad-swad-sales-management`, branch `main`. Do not upload the outer folder as a nested folder.
4. Preserve paths, including `backend/` and `frontend/`.
5. Commit the changes. Render should redeploy the backend if its service is connected to this repository and the configured root directory is `backend`.

## Frontend hosting
The `frontend/` folder is a static website. Publish `frontend/index.html`, `frontend/app.js`, and `frontend/styles.css` using your existing static hosting setup.
In `frontend/app.js`, the first line currently sets:
`const API = (window.KAWAD_API_URL || '').replace(/\/$/,'');`
For a separately hosted frontend, replace the empty default with the exact Render API origin, for example:
`const API = (window.KAWAD_API_URL || 'https://YOUR-RENDER-SERVICE.onrender.com').replace(/\/$/,'');`
Use your actual service URL, not the example. Set `SALES_CORS_ORIGINS` on Render to the exact frontend origin, with no trailing slash. If frontend and API share an origin, the empty default may be suitable.

## Important configuration
Keep these Render settings as already configured:
- Root Directory: `backend`
- Build Command: `pip install -r requirements.txt`
- Start Command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health Check Path: `/health`
- `SALES_GOOGLE_SPREADSHEET_ID`
- `SALES_GOOGLE_SERVICE_ACCOUNT_FILE=/etc/secrets/sales-service-account.json`
- `SALES_JWT_SECRET` (32+ characters)
- `SALES_CORS_ORIGINS` (exact frontend origin)
- `SALES_OWNER_SETUP_SECRET` only while initial owner setup is still required.

Never upload the service-account JSON, JWT secret, owner setup secret, passwords, or password hashes to GitHub.

## Scope and business-safety note
This is an updated development package, not a certification that all 11 stages are complete. Stages 2 and 3 receive the main UI improvement here. Sales, payment, stock reconciliation, field workflow, expenses, closing, incentives, and reporting still need a staged business-rule review before using this system for real transactions. The existing Google Sheets backend does not provide atomic multi-row writes or robust concurrent ID allocation. Keep using a development spreadsheet until those controls and permissions are verified.

## Product catalogue notes
- Product SKU is not editable after creation through the UI, to reduce accidental changes to historical references.
- Product activation/deactivation uses the existing `/api/products/{product_id}` PATCH endpoint.
- The frontend validates required fields, but the backend remains the final validator.
- Do not create duplicate SKUs.

## Customer notes
- Customer creation is available to authenticated users according to the current backend permissions.
- This version adds customer search but does not implement customer editing/deactivation because the supplied backend has no customer PATCH endpoint.
- Check for an existing shop before creating a new record.

\n## Stage 6: Company & Salesman Stock\n\nThis package adds the Stock screen and ledger-backed stock endpoints. Upload the repository contents while preserving `backend/` and `frontend/`. Keep Render environment variables and Secret Files unchanged. Before using stock movements, confirm `SalesmanStockLedger` exists with the exact headers in `docs/SALES_MANAGEMENT_SCHEMA.md`; enter opening company quantities first. Sales do not automatically deduct stock in this stage.\n