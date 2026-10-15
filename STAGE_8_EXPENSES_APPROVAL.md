# Stage 8: Expenses & Approval

This stage adds an authenticated `GET /api/expenses` endpoint and upgrades the Expenses screen. Salesmen see only expenses they submitted; OWNER and PA users can view the register and approve/reject pending submissions.

## Workflow
1. Submit category, amount, description, and optional receipt link/reference.
2. New submissions start as `PENDING`; they do not reduce cash due back.
3. OWNER/PA can approve or reject pending records. Rejection requires a reason in the UI.
4. Approval decision, approver, timestamp, and audit entry are recorded by the existing approval route. Only approved eligible expenses are marked cash-reducing.

## Important
- Keep the existing Google Sheets `Expenses` tab and its exact headers from `docs/SALES_MANAGEMENT_SCHEMA.md`.
- Receipt field stores a link/reference only; this does not upload files.
- This is a code update, not a verification of the live deployment. Keep using your existing Render environment variables and Secret Files.
- Before relying on this for accounting, verify your deployed backend is running this version and confirm approval permissions with a non-production record.
