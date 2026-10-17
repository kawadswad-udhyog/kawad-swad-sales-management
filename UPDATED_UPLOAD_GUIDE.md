# Stage 9 Upload Guide

1. Extract this ZIP.
2. Open the existing GitHub repository and upload the package contents to the repository root, preserving `backend/` and `frontend/`.
3. Replace matching files and commit to `main`.
4. Allow Render to redeploy from GitHub.
5. Keep Render environment variables and Secret Files unchanged. Never commit service-account JSON or secrets.
6. Keep the Google Sheets `DailyClosing` and `AuditLog` headers exactly as documented.

This package adds daily cash closing history and Owner/PA review. It is not a claim that physical stock reconciliation or duplicate-closing prevention is complete.

## Performance update
See `PERFORMANCE_FIX_NOTES.md` for the login, session restoration, and Google Sheets read-cache changes and their verification status. Frontend build and live Render behavior still need to be checked after upload/deployment.
