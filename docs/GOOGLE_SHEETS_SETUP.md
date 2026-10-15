# Google Sheets setup for the full development application

Use only the dedicated development spreadsheet, not the production ERP spreadsheet.

## Existing tabs
Keep the 14 existing tabs and their exact first-row headers from `SALES_MANAGEMENT_SCHEMA.md`.

## Add one required tab: `AuthUsers`
The current Users tab does not contain password hashes. Create a new worksheet named exactly `AuthUsers` and paste this exact header row into A1:H1:

`auth_id | user_id | username | password_hash | role | active | created_at | must_change_password`

Do not store plaintext passwords in any worksheet. Password hashes are PBKDF2-SHA256. The API's user-creation endpoint hashes passwords before storing them.

## Create the first Owner account
The initial Owner cannot be created through the API because the API requires Owner authentication. Use the local bootstrap utility in `backend/scripts/bootstrap_owner.py` after setting environment variables. It will prompt for the username/password and add an AuthUsers record and matching Users record. Never commit passwords, tokens, JSON keys, or `.env` files.

## Required Render environment variables
- `SALES_GOOGLE_SPREADSHEET_ID`: ID of the dedicated development spreadsheet.
- `SALES_GOOGLE_SERVICE_ACCOUNT_FILE`: `/etc/secrets/sales-service-account.json`
- `SALES_JWT_SECRET`: at least 32 random characters; generate a unique value.
- `SALES_CORS_ORIGINS`: exact frontend origin(s), comma-separated. Do not use `*` with credentials.
- Optional `SALES_TOKEN_HOURS`: defaults to 8.

Render Secret File:
- Filename: `sales-service-account.json`
- Contents: entire downloaded service-account JSON
- The JSON must not be committed to GitHub or pasted into chat.

## Important limitations
Google Sheets is not a transactional database. A sale writes a Sales row, then SaleItems, then Payments; a network failure between writes can leave incomplete records. This starter does not yet implement a durable transaction/outbox repair process, concurrent ID allocation, or full idempotency. Use a development spreadsheet only until those controls are added and validated.
