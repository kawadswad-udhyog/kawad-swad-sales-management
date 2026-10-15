# Next stage: Sales, Billing & Payment Recording

This update expands the existing sales screen to support multiple product lines per bill, quantity and actual unit price per line, bill-level discount, full-payment method/reference capture, confirmation before issue, recent bill search, and PDF invoice download/reprint.

## Deploy
1. Upload the contents of this repository folder to the existing `kawad-swad-sales-management` GitHub repository on `main`, replacing matching files.
2. Preserve the existing Render environment variables and Secret Files. Do not upload service-account JSON or secrets.
3. Render should redeploy automatically after the commit.

## Business logic boundary
- Each sale currently records full payment at the time the bill is issued. Do not issue a bill unless full payment has actually been received.
- Invoice reprint calls the existing invoice endpoint and does not create another sale.
- Automatic stock deduction, robust atomic multi-sheet writes/idempotency, bill cancellation/credit notes, and GST invoice logic are not implemented in this stage. Do not rely on this version for automatic stock control or GST tax invoicing until those stages are completed.
- The bill records zero tax under the current backend behavior. Confirm tax requirements before representing invoices as GST tax invoices.
