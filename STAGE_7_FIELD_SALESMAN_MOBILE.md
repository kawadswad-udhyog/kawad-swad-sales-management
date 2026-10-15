# Stage 7: Field Salesman Mobile Workspace

This stage improves the existing frontend for phone use and gives the SALESMAN role a focused field-work dashboard with quick links to existing modules:
- New sale / billing
- Shop visit logging
- Customer registration
- Expense submission
- Stock summary and movements

It uses the existing authenticated API routes and does not create new business data tables or modify production Google Sheets schema.

## Upload
1. Extract this ZIP.
2. In the GitHub repository `kawad-swad-sales-management`, upload the contents of `kawad-swad-sales-management-main/` to the repository root, replacing matching files.
3. Commit to `main` and allow the existing Render service to redeploy.
4. Keep Render environment variables and Secret Files unchanged. Never commit service-account JSON or secrets.

## Scope and limitations
This is a mobile-responsive workspace, not an offline/PWA app. It does not add geolocation tracking, route planning, attendance, background sync, or automatic sale-to-stock deduction. Existing backend permissions and route behavior still apply. Sales and payment correctness depends on the current backend implementation.
