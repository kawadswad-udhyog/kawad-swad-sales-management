# Kawad Swad Sales Management: Account & Sheets Reliability Update

## Changes made

1. **Account identity consistency**
   - Login now matches the authenticated `AuthUsers.user_id` to exactly one `Users.user_id` profile.
   - Login rejects missing/duplicate profile matches and role mismatches with HTTP 409 and a specific account-mismatch message.
   - A deactivated staff profile is rejected.
   - The canonical profile supplies the displayed full name and role.
   - Login and `/api/auth/me` responses include the real username, so the frontend no longer has to display the internal user ID as the username.

2. **Google Sheets quota/read coordination**
   - Fixed the single-flight lifecycle so the in-flight marker remains active throughout the complete retry cycle, rather than being cleared after each failed attempt.
   - Added process-local serialization of Google Sheets reads to reduce request bursts from one backend instance.
   - Added jitter to exponential retry delays.
   - Critical tabs (including `AuthUsers`, `Users`, `Sales`, `Payments`, stock, cash, production and ID allocation tabs) do not fall back to stale cached data after quota exhaustion.
   - Stale fallback is retained only for non-critical tabs when the caller did not request a fresh read.

3. **Frontend sync message**
   - The workspace sync warning now distinguishes quota-related failures from generic backend/storage sync failures.

4. **Test updates**
   - Updated the quota test to assert that stale `AuthUsers` data is rejected after a quota failure.

## Verification performed

- `python -m compileall -q backend/app`: passed.
- `SALES_TESTING=1 pytest -q backend/tests`: 53 passed, 5 warnings.
- Frontend build: not verified. `npm install --no-audit --no-fund && npm run build` timed out in this environment.
- Live Google Sheets and Render: not tested or changed.

## Important limitations

- The process-local read semaphore coordinates reads only within one backend process. It does not coordinate multiple Render instances or other Google API clients.
- Account consistency checks may expose existing mismatches between `Users` and `AuthUsers`. Do not change IDs or roles blindly; inspect the two records and confirm the intended account.
- The live quota problem may also require reducing workspace read volume and/or reviewing Google Cloud API quota settings. This patch reduces duplicate concurrent reads but does not guarantee quota will never be exceeded.
- Test mode uses in-memory data. No live spreadsheet was modified by this update.
