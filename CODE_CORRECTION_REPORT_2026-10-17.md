# Code Correction Report — 17 October 2026

## Scope
Targeted corrections to the uploaded live GitHub repository ZIP. No live Render deployment or Google Sheets data was changed.

## Corrections made

1. **Login error/session handling (`src/services/api.ts`)**
   - A 401 response from `/api/auth/login` or `/auth/login` no longer triggers the global expired-session event. Credential errors remain visible to the login form instead of being treated as an already-expired session.
   - A 401 from an authenticated endpoint still clears the invalid token and triggers logout.
   - The authenticated-request failure is saved briefly in `sessionStorage` so the sign-in page can explain why the session returned to sign-in.

2. **Visible post-logout message (`src/components/LoginModal.tsx`)**
   - Displays the saved session rejection message after the app returns to the sign-in screen.

3. **Duplicate usernames (`backend/app/routers/auth.py`)**
   - Login now detects duplicate usernames case-insensitively before checking a password. It returns HTTP 409 with an actionable message rather than selecting the first row based on worksheet order.
   - Active-state handling is consistent for `false`, `0`, `no`, `inactive`, and `disabled` values.

4. **Session validation (`backend/app/auth.py`)**
   - An authenticated token is no longer accepted solely from its JWT payload when its corresponding `AuthUsers` record is missing.
   - Duplicate auth records are rejected explicitly.
   - Google Sheets read/quota errors during session validation return a controlled HTTP 503 message instead of an unhandled server error.
   - Inactive-state handling is consistent for common false values.

5. **Repository hygiene**
   - Added `.gitignore` entries for Python bytecode/cache, Node modules/build output, local environment files, and editor/OS files.
   - Removed the root-level duplicate ZIP from the source package. The `public/` downloadable ZIP is retained as the application download asset.

## Verification

- Backend pytest: **54 passed, 5 warnings**.
- Python test execution used `SALES_TESTING=1` and a test-only JWT secret; it did not connect to or modify live business data.
- Frontend build: **not verified**. `npm install --ignore-scripts --no-audit --no-fund` timed out in this environment, so a TypeScript/Vite build could not be completed.
- Live Google Sheets and Render integration: **not tested**.
- Deployment: **not performed**.

## Remaining verification before deployment

1. Run `npm ci` (or `npm install` if no lockfile is maintained) in the normal development environment, then `npm run build`.
2. Test login against the development spreadsheet with a valid account, invalid password, duplicate username, inactive account, missing AuthUsers row, and Google Sheets quota failure.
3. Confirm the production frontend serves the intended `public/kawad-swad-sales-management-updated.zip` asset.
4. Deploy only after frontend build and development-spreadsheet integration tests pass.
