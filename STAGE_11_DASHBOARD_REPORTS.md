# Stage 11: Dashboard & Excel Reports

## Included
- Monthly management report: issued bill count and recorded revenue.
- Sales-type breakdown.
- Product-wise quantity, qualifying kilograms and line revenue based on recorded SaleItems.
- Salesman-wise bill count and revenue.
- Payment-method totals from recorded Payments rows.
- Expense totals grouped by recorded approval status.
- Excel exports for sales, sale items, payments, products, customers, expenses, shop visits, salesman stock ledger, cash ledger, daily closing, salary/incentives and audit log.

## Deploy
1. Keep a backup of the current GitHub `main` branch before replacing files.
2. Upload the ZIP contents to the repository root, preserving `backend/`, `frontend/`, `docs/` and other project folders.
3. Commit to `main` and allow Render to deploy.
4. Keep existing Render environment variables and Secret Files unchanged.

## Important limitations
- Reports are derived from records currently stored in Google Sheets. Missing or incorrectly entered source records will affect the results.
- These reports are management summaries, not audited accounts, GST returns or statutory tax invoices.
- The payment-method report sums recorded payment rows and excludes rows marked VOID, CANCELLED or FAILED. It does not independently verify settlement with a bank or payment provider.
- Product revenue uses recorded SaleItems line totals. No stock valuation, profit calculation, receivables ledger or reconciliation to bank statements is added here.
- Export endpoints include business/customer data. Restrict access to trusted OWNER/PA users and store downloaded files securely.
- Syntax checks passed when this package was prepared; the live Render deployment and report data have not been verified.
