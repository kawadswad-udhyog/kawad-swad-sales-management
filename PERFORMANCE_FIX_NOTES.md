# Performance and Login Reliability Update

## Changes included

1. **Login returns after successful authentication** instead of waiting for all sales, stock, customer, expense, visit, closing, salary, audit, and dashboard records to finish loading. Live data hydrates in the background and the UI displays a sync message.
2. **Login request timeout increased to 70 seconds** to accommodate a sleeping Render instance waking up. This reduces false failures during cold starts; it does not make a sleeping service itself start faster.
3. **Login audit write moved to a FastAPI background task**, so Google Sheets audit latency does not delay the authentication response.
4. **Initial data requests run together**, including expenses, visits, and Owner/PA dashboard and users, rather than fetching some tables in later sequential batches.
5. **Short-lived Google Sheets read cache (10 seconds)** reduces repeated reads of the same worksheet during dashboard/list refreshes. Backend writes invalidate the relevant worksheet cache. In-memory/test mode is not cached.
6. Session restoration no longer waits for every table to load before showing the workspace.

## Verification

- `python -m compileall -q backend`: passed.
- `python -m pytest -q backend/tests`: 20 passed.
- Frontend build: not verified in this environment because npm dependency installation timed out.

## Important limitations

- Render cold starts may still cause a long wait on the very first request. The longer timeout prevents a premature client-side abort; it does not remove cold-start latency.
- Google Sheets remains the data store, so a large sheet or Google API latency can still make refreshes slow.
- The cache is only for live Google Sheets reads, expires after 10 seconds, and is invalidated by backend write helpers. Direct manual spreadsheet edits may take up to 10 seconds to appear.
- This update has not been deployed to Render and has not been tested against the live spreadsheet.
