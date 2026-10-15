# Stage 9: Daily Cash Closing and Review

## Included
- Daily closing screen for salesman and managers.
- Server-calculated expected cash return from today's paid sales and approved cash-reducing expenses.
- Actual physical cash returned and recorded difference.
- Closing history, restricted to the submitting salesman or visible to Owner/PA.
- Owner/PA review actions: confirm or mark needs correction. Review records reviewer, timestamp, and audit entry.
- Review never changes the submitted cash amounts.

## Google Sheets
Uses the existing `DailyClosing` and `AuditLog` tabs. Preserve the exact headers in `docs/SALES_MANAGEMENT_SCHEMA.md`. The `DailyClosing` header order must include 16 fields through `notes`, as defined in the schema.

## Important limitations
- This stage does not yet reconcile physical stock counts against expected stock. The stock ledger remains available in the Stock screen, and stock-to-bill automatic deduction remains a separate integration step.
- Closing cash is derived from records currently in the application. Correct opening cash must be entered for the applicable workday.
- Avoid submitting multiple closings for the same salesman and date until duplicate-closing prevention is added.
- Review this module in the development service before relying on it for real cash handling. No live Render deployment was performed by generating this ZIP.
