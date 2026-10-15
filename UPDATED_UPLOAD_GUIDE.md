# Updated upload guide — Stage 8

1. Extract the ZIP.
2. In the existing GitHub repository, upload the contents of `kawad-swad-sales-management-main/` to the repository root, preserving folder paths and replacing matching files.
3. Commit to `main`; Render should redeploy from the connected branch.
4. Keep existing Render environment variables and Secret Files unchanged. Never commit service-account JSON, tokens, or secrets.
5. Review `STAGE_8_EXPENSES_APPROVAL.md` for the workflow and limitations.

This package adds the expenses list API and approval interface. It does not alter existing Google Sheets data during upload.
