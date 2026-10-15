# Stage 10: Salary & Incentives

This development stage adds a payroll register, configurable calculations, approval/rejection, and explicit payment marking.

## Calculation rules
- Includes only issued, delivered, fully paid sales with positive `SaleItems.qualifying_kg`.
- Trial incentive: eligible kg sold during the configured trial window after `Users.created_at` multiplied by the configured per-kg rate.
- Monthly incentive: completed 100 kg blocks outside the trial window multiplied by the configured rate per block.
- Base salary: configured monthly amount when the configured trial has ended by the period end.
- Defaults shown in the UI are user-configurable suggestions: 7 trial days, ₹10/kg trial incentive, ₹150 per completed 100 kg, ₹7,000 monthly salary. Confirm policy and user join dates before payroll reliance.
- Existing records for the same period, salesman, and record type are not duplicated. To recalculate after changing rules, an administrator must review the existing records; this build does not overwrite them.
- Approval is distinct from payment. Only approved records may be marked paid.

## Google Sheets requirements
`SalaryIncentives` must have the exact headers in `docs/SALES_MANAGEMENT_SCHEMA.md`. `Users.created_at` should represent the employee join date for trial-period logic. The app uses the existing `Users`, `Sales`, `SaleItems`, `SalaryIncentives`, and `AuditLog` tabs.

## Important limits
- This is a development feature, not a payroll/tax compliance engine. It does not calculate statutory deductions, PF/ESI, TDS, overtime, attendance proration, or advances.
- It does not transfer money or verify bank/UPI payment. Mark paid only after the real payment is completed.
- Google Sheets does not provide a multi-sheet transaction. Review all results before relying on them for actual salary disbursement.
- Do not change the production ERP spreadsheet or credentials.
