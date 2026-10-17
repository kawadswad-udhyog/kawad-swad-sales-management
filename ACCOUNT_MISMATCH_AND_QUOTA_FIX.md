# Account Mismatch and Google Sheets Quota Fix

## Changes in this update

1. Login now joins `AuthUsers` to `Users` using the immutable `user_id`.
2. Login is rejected with HTTP 409 if there is not exactly one matching staff profile, if the account role differs between the two tabs, or if the staff profile is inactive. This avoids silently displaying or authorizing the wrong account.
3. Login response now returns the actual username and staff full name from the matched records. `/api/auth/me` validates the same identity join and returns the username, canonical profile name, and normalized role.
4. Frontend login and session restoration use the API-provided username instead of substituting `user_id` as the username.
5. Google Sheets single-flight read coordination now remains active for the whole retry sequence. Previously the in-flight marker was cleared inside each retry attempt, which could wake concurrent callers and create additional read bursts during 429 quota errors.
6. Quota retry backoff now includes jitter and a capped delay outside test mode.

## Validation

- Backend tests: `53 passed, 5 warnings` using `SALES_TESTING=1`.
- Python compile check: passed.
- Frontend build: attempted, but the command timed out in this environment. It is not claimed as passed.
- Live Google Sheets / Render: not tested or modified.

## Account mismatch resolution guidance

If login now reports an account mismatch, inspect the `Users` and `AuthUsers` tabs using `user_id` as the join key. Each login must have exactly one row in each tab, the same normalized role, and both records active. Do not fix this by copying a different person's ID or by changing a role blindly. Correct the records only after confirming the intended staff identity and permission level.

## Deployment caution

Test against the development spreadsheet first. The change intentionally blocks accounts whose identity records disagree; this may expose pre-existing sheet inconsistencies that were previously hidden.
