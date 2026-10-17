# Safety Hardening Update

Date: 17 October 2026

## Included code change

`backend/app/sheets.py` now treats the following sheets as critical and requires a fresh Google Sheets read for them, bypassing the normal short-lived record cache:

- Authentication and user records: `AuthUsers`, `Users`
- Sales and payment records: `Sales`, `SaleItems`, `Payments`, `CashLedger`
- Stock and closing records: `SalesmanStockLedger`, `DailyClosing`
- Expense and ID allocation records: `Expenses`, `IdAllocations`
- Production and factory inventory records: `RawMaterials`, `RawMaterialLedger`, `Recipes`, `ProductionBatches`, `PackagingBatches`, `ProductionStockLedger`, `ProductionDispatches`, `WorkerAttendance`, `Workers`
- Product catalogue: `Products`

For these tabs, if Google Sheets cannot return current data because of a quota or read error, the adapter raises an error instead of returning an old cached snapshot. This is intended to avoid making authentication, stock, payment, closing, or production decisions from stale data.

Non-critical tabs can still use the short-lived cache and stale-cache fallback during quota errors. This is a deliberately narrow safety change, not a replacement of Google Sheets with a transactional database.

## Tests changed

`backend/tests/test_sheets_quota_handling.py` now checks that:

1. A quota error on `AuthUsers` does not fall back to stale cached records.
2. `Products` bypasses even an unexpired cache for critical reads.
3. Explicit fresh reads continue to reject stale cache on quota errors.
4. A clear quota error is raised when retries fail without usable data.

## Verification performed

Command run from `backend`:

```bash
SALES_TESTING=1 SALES_JWT_SECRET=test-only-secret-do-not-use-for-deployment-32 python -m pytest tests -q --tb=short
```

Result: **54 passed, 5 warnings**.

The warnings are deprecation warnings involving `datetime.utcnow()` in customer and recipe-sheet update code. They did not fail the test run.

## Important limitations

- No live Google Sheets spreadsheet was contacted.
- No live Render deployment was changed.
- No production spreadsheet or business records were modified.
- The frontend code was not changed by this patch, and a new frontend build was not run for this update.
- This patch does not make Google Sheets transactional and does not eliminate cross-server concurrency risks.
- It does not certify all sales, production, accounting, or security workflows for live use.

## Deployment caution

Do not replace the live application until the updated code has been uploaded to a development branch or otherwise tested against a separate development spreadsheet. Confirm the backend health response shows connected persistent storage before testing any business write.
