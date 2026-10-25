# Kawad Swad ERP Repair Notes — 25 October 2026

## Applied in this repair package
- Production frontend host `kawad-swad-sales-frontend.onrender.com` now always uses same-origin relative routing so a stale `ks_backend_api_url` cannot redirect production traffic to another backend.
- Removed the hard-coded `https://kawad-swad-sales-dev.onrender.com` emergency fallback. A production API failure is no longer silently sent to a different environment/database.
- Login header now shows API Offline in red when backend is not verified, and does not falsely claim ERP Ready.
- The lower connection indicator now reflects actual backend and storage state.
- Google Sheets and persistent-write state now initialize as false until a health response verifies them.

## Verification
- Backend tests: 132 passed, 0 failed, 2 deprecation warnings.
- Frontend production build could not be verified in this environment because npm dependency installation did not complete; `node_modules` was unavailable. Run `npm ci && npm run build` in GitHub/Render build environment before release.
- No live Render settings, production browser, Google Sheets, credentials, or live business records were changed or verified by this package.

## Required deployment checks
1. Confirm Render frontend rewrite rules route `/api/*` to the intended production backend, and `/health` to that same backend.
2. Confirm the deployed frontend service is using the intended backend service URL. This source package's `render.yaml` targets `kawad-swad-sales-backend.onrender.com`, while the supplied logs show a service URL ending in `kawad-swad-sales-dev.onrender.com`. Do not change service names blindly: confirm which service has the production spreadsheet and secrets.
3. Deploy this source to the intended frontend service, then test `/api/health`, `/health`, and the login request in browser DevTools.
4. Verify health JSON reports Google Sheets connected and persistent writes enabled before using production transactions.
5. Test one valid login and one invalid login; confirm valid login returns a backend-issued `access_token` and authenticated API requests succeed.

## Important limitation
This patch corrects unsafe frontend routing behavior and misleading status UI. It cannot itself repair Render dashboard service wiring, missing environment variables, wrong credentials, or a mismatched backend login response. Those require live deployment verification.
