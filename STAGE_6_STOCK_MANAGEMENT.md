# Stage 6: Company & Salesman Stock Management

## Included
- Stock summary derived from `SalesmanStockLedger`.
- Company receipt/opening stock, issue to salesman, return from salesman, recorded sale movement, and positive stock adjustments.
- Rejects issues above available company stock and returns/sales movements above the selected salesman's available stock.
- Stores movement actor, time, product/SKU snapshot, unit, quantity and notes.
- Stock screen for Owner/PA, with summaries and recent ledger rows.

## Required Google Sheets tab
Use the existing `SalesmanStockLedger` tab with the exact headers documented in `docs/SALES_MANAGEMENT_SCHEMA.md`. Do not rename columns.

## Important operating rules
1. Enter an opening quantity using **Company stock received / opening** for each product before issuing it.
2. Issue stock to a user whose `Users.role` is `SALESMAN` and whose account is active.
3. Record returns against the correct salesman.
4. Keep notes/references for opening quantities, challans, returns and corrections.
5. Do not record a second manual `SOLD` movement for a bill unless you have confirmed the bill is not already connected to stock. Automatic sale-to-stock deduction is not included in this stage.
6. This is a ledger-backed development workflow, not a multi-write atomic inventory system. Concurrent transactions and recovery from partial Google Sheets writes still require hardening before relying on it for final accounting.
