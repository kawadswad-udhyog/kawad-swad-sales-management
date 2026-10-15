# Sales Management Development Integration

## Manual upload
Upload these files into the same relative paths in your repository. Do not overwrite existing files unless you have checked that they are the same files.

## Dedicated spreadsheet configuration
Set these environment variables only in the development backend service:
- `SALES_GOOGLE_SPREADSHEET_ID`: ID from the dedicated development Google Sheet.
- `SALES_GOOGLE_SERVICE_ACCOUNT_FILE`: path to a development service-account JSON secret mounted by the host.

Never set this module to fall back to `google_spreadsheet_id`, and never commit credentials. Share the development Sheet with the service account's email as Editor.

## Important Apps Script / backend ID rule
Spreadsheet `onEdit` scripts do not reliably run for API writes. The application must generate IDs for its own writes. For now, avoid editing a row manually at the same time the app is creating records in that tab. Before multi-user production use, ID allocation must be made single-writer/atomic across Apps Script and the backend, or app-managed tabs must become backend-only.

## Not yet implemented
- Authentication and role checks
- Safe central ID allocator and invoice numbering
- Idempotency / duplicate-request prevention
- Payment, stock, delivery and incentive invariants
- Append-only audit events
- PDF invoice and Excel exports
- Frontend and deployment

## Safety
This is a development starter. It is not mounted into the FastAPI app, and should not be deployed until reviewed and tested against a separate development spreadsheet.
