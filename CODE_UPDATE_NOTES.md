# Kawad Swad Sales Management: Update Notes

This package is based on the uploaded `kawad-swad-sales-management-main (12).zip`.

## Changes in this update

- Fixed expense approval/rejection API calls to use the backend's real `/api/expenses/{id}/approve` route and `{ approved, notes }` payload.
- Added the frontend's expected `POST /api/stock/transactions` endpoint as a compatibility route, translated the stock screen's movement labels to canonical ledger types, validated positive quantities/product existence, and exposed negative stock balances rather than hiding discrepancies by clamping to zero.
- Made the stock form await the API request, so failed stock writes show an error rather than a false success message.
- Connected customer edits to `PUT /api/customers/{customer_id}` and only update local UI state after the server confirms the change.
- Aligned dashboard metric types and daily totals with the backend response schema. Monthly figures continue to be calculated from loaded sales.
- Added a fail-closed Google Sheets connection guard to sale creation, stock movements, expense submission/review, daily closing submission/review, and salary proposal/approval/payment. If Sheets is disconnected, these writes return HTTP 503 instead of pretending that memory-only data is durable.
- Removed the one-time `/api/auth/setup-owner` endpoint and its setup-secret configuration, because the initial Owner has already been created. Do not use this package to re-run initial owner setup.
- Updated test mocks to support PATCH route decorators and removed the obsolete test that depended on the removed owner-setup endpoint.

## Verification performed here

- `python -m compileall -q backend/app`: passed.
- `python -m pytest -q backend/tests --disable-warnings`: 20 passed.
- Frontend build could not be verified in this environment because npm dependencies could not be installed before timeout. Run the normal Render build after pushing and check the deployment logs before using the changes operationally.

## Important remaining audit items

This is a targeted integration/reliability patch, not a certification that every workflow is production-ready. Remaining items from the audit include enforcing salesman stock availability before a sale is accepted, ensuring all multi-sheet writes roll back or reconcile safely, hardening globally unique IDs against concurrent writes, persisting payment reference correctly, full daily/monthly reporting, and complete cancellation/void workflows. Do not process real sales until those paths have been tested end-to-end against the development spreadsheet.

## Manual GitHub upload

Upload/replace the files in this ZIP in the repository's `main` branch, preserving the folder structure. Do not upload `node_modules`, `.env` files, service-account JSON files, tokens, or production data. After commit, check Render backend deployment logs and frontend build logs. The source code change does not itself deploy anything.
