# Change report

This pass repaired the existing Kawad Swad sales application and connected the production module that was already partly written but not registered.

## Audit issues addressed

- A sale is no longer reported as finished if a required row fails. The sale stays `INCOMPLETE` until items, salesman stock, payment, and cash (for cash bills) all exist. Retrying the same idempotency key finishes the missing rows and does not create a second bill, payment, or stock movement.
- Bill totals and line totals are recalculated on the server. A mismatched total is rejected. Inactive products and insufficient salesman stock are rejected.
- A salesman cannot submit a sale or expense for another salesman.
- Stock responses now include both `current_stock` and the names the screens already use (`company_quantity`, `quantity`, `pack_weight_g`, `salesman_name`). Company stock and salesman stock are calculated from the same ledger rules.
- Payments are returned with sales and through `GET /api/sales/payments`. The workspace loader fills the arrays used by invoices, reports, closing, and incentives. UPI, bank, cash, and other references are stored.
- Invoice PDF shows the payment method and reference. Reprinting does not create a sale.
- Record IDs are allocated from the highest existing number plus a claim row in `IdAllocations`, not from `len(rows) + 1`. Historical IDs are not renumbered. Two servers can still race; the claim row decides the winner and the loser retries.
- Password checks accept only PBKDF2-SHA256. Plaintext and raw SHA-256 no longer log anyone in. An empty `AuthUsers` sheet no longer logs anyone in. Legacy hashes must be replaced with `backend/scripts/reset_password.py` or by an owner reset. There is no public setup URL and no default password.
- The API refuses to start in production without a JWT secret of at least 32 characters, and it rejects the old built-in default. Wildcard CORS is rejected when `SALES_ENV=production`. The service account now requests only the spreadsheets scope.
- User list, audit log, and dashboard require owner or PA. A PA cannot create an owner. Expense, salary, and closing decisions are saved only when the sheet update succeeds, and the screens wait for that result.
- Daily closing uses the Asia/Kolkata business date. Cash due is opening cash plus cash collections minus approved cash expenses. UPI, bank, and other collections are stored separately. A second closing for the same salesman and day is rejected. A physical count that does not match the ledger sets the discrepancy flag and does not relabel the difference as a loss.
- Salary status `PROPOSED` is shown to the screen as `PENDING`. Approval and payment no longer flip the screen before the server confirms. Incentives use the sale lines that were actually loaded, and only delivered, fully paid, non-cancelled sales.
- The production router and Production screen are registered. Approved recipes deduct raw materials. Packaging records kilograms, packet counts, and a difference that is not auto-corrected. Dispatch is stored as a stock movement, not a sale. A salesman-channel dispatch adds that salesman's packet stock without creating a bill.
- Login loads one workspace request instead of a dozen sheet downloads. Stock used to authorise a sale is read fresh. Sheet updates for a row are batched.

## Important files

- `backend/app/sheets.py`, `auth.py`, `config.py`, `permissions.py`, `stock_math.py`, `timeutil.py`
- `backend/app/routers/sales.py`, `stock.py`, `auth.py`, `users.py`, `closing.py`, `salary.py`, `expenses.py`, `audit.py`, `dashboard.py`, `production.py`, `workspace.py`, `main.py`
- `src/context/StoreContext.tsx`, `src/App.tsx`, `src/components/Navigation.tsx`, `src/views/ProductionView.tsx`, `src/utils/generateInvoicePdf.ts`
- `backend/tests/test_integrity.py` and updates to the existing sales tests
- `backend/scripts/reset_password.py`

## Spreadsheet changes

The app can add these extra columns when it next writes a row. It does not delete or reorder existing rows.

- `Sales`: `idempotency_key`, `txn_status`, `payment_method`, `payment_reference`
- `DailyClosing`: `upi_collected`, `bank_collected`, `other_collected`, `idempotency_key`
- New tab `IdAllocations`: `allocation_id`, `tab_name`, `allocated_id`, `nonce`, `created_at`

Production still uses the existing tabs: RawMaterials, Workers, WorkerAttendance, Recipes, ProductionBatches, PackagingBatches, ProductionStockLedger, ProductionDispatches, RawMaterialLedger.

GST rates, HSN codes, and tax-invoice wording are not invented. A tax amount is stored only when the operator enters one. Confirm GST with your accountant before treating a bill as a tax invoice.

No product recipe, wage, or incentive rate was invented. Recipes and daily wages are whatever you enter. Incentive rates remain the numbers typed on the salary screen.

## Remaining limits

- Google Sheets is still not a database transaction. A network failure can leave an incomplete sale. The retry path is the recovery. Do not delete the incomplete row and create the bill again by hand.
- Bill numbers are unique claims, not a perfect lock, if someone also types new bill numbers in the sheet at the same moment.
- Manual edits in the sheet and the app should not allocate IDs for the same tab at the same time. Prefer the app for sales, stock, and production.
- Factory dispatch to a salesman increases that salesman's packets. It does not reduce the separate company-warehouse balance. Company warehouse stock still moves only through company receipt, issue, and return.
- This was not tested against a live spreadsheet.
