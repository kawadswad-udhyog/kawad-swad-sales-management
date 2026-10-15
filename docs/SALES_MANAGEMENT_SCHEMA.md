# Kawad Swad Sales Management System — Development Contract

Status: development-only specification. This must not be deployed to production until reviewed and tested.

## Safety boundaries
- Use the dedicated development spreadsheet ID from the deployment environment; never fall back to the existing ERP spreadsheet ID.
- Do not read, write, or migrate existing ERP transactions.
- Do not add the sales router to the production app entry point until integration is reviewed.
- Never store service-account JSON, tokens, passwords, or spreadsheet secrets in Git.
- GST/tax treatment remains configurable and unconfirmed.

## Google Sheets tabs and header contract

Tab names and headers are treated as API schema. Do not rename headers without updating code and tests.

- Users: user_id, full_name, role, mobile, email, active, created_at, notes
- Products: product_id, sku, product_name, category, variant, pack_weight_g, selling_unit, retail_pack_only, active, notes
- Customers: customer_id, customer_type, shop_name, shopkeeper_name, mobile, alternate_mobile, address, locality_area, city, map_location, active, created_at, notes
- Sales: sale_id, bill_number, sale_datetime, sales_type, customer_id, customer_name_snapshot, entered_by_user_id, salesman_user_id, delivery_status, payment_status, subtotal, discount_amount, tax_amount, bill_total, bill_status, created_at, notes
- SaleItems: sale_item_id, sale_id, product_id, product_name_snapshot, sku_snapshot, pack_weight_g, unit, quantity, actual_unit_price, discount_amount, line_total, qualifying_kg, created_at, notes
- Payments: payment_id, sale_id, payment_datetime, payment_method, amount, reference_number, received_by_user_id, payment_status, notes
- SalesmanStockLedger: stock_txn_id, txn_datetime, salesman_user_id, product_id, sku_snapshot, txn_type, quantity, unit, pack_weight_g, related_sale_id, issued_by_user_id, received_by_user_id, confirmed_by_user_id, reference_id, notes
- CashLedger: cash_txn_id, txn_datetime, salesman_user_id, txn_type, amount, payment_method, related_sale_id, related_expense_id, issued_by_user_id, received_by_user_id, confirmed_by_user_id, reference_id, notes
- Expenses: expense_id, expense_datetime, submitted_by_user_id, salesman_user_id, category, amount, description, receipt_link_or_file_ref, approval_status, approved_by_user_id, approval_datetime, cash_reducing_expense, related_closing_id, notes
- ShopVisits: visit_id, visit_datetime, salesman_user_id, customer_id, shop_name_snapshot, visit_outcome, order_taken, follow_up_date, next_action, created_at, notes
- DailyClosing: closing_id, closing_date, salesman_user_id, opening_cash, cash_collected, approved_cash_expenses, expected_cash_return, physical_cash_returned, cash_difference, opening_stock_reference, stock_discrepancy_flag, closing_status, submitted_at, reviewed_by_user_id, reviewed_at, notes
- SalaryIncentives: record_id, period_start, period_end, salesman_user_id, record_type, eligible_kg, completed_100kg_blocks, rate, calculated_amount, approved_amount, approval_status, approved_by_user_id, paid_datetime, payment_reference, notes
- AuditLog: audit_id, event_datetime, actor_user_id, action, entity_type, entity_id, field_changed, old_value, new_value, reason, approved_by_user_id, related_record_id
- Settings: setting_key, setting_value, description

## IDs and numbering

Readable ID prefixes:
- Users USR; Products PRD; Customers CUS; Sales SALE; SaleItems ITEM; Payments PAY
- SalesmanStockLedger STK; CashLedger CSH; Expenses EXP; ShopVisits VIS
- DailyClosing CLOSE; SalaryIncentives SAL; AuditLog AUD

Format: PREFIX-000001, with a separate bill number for issued sales. IDs are immutable and must never be based on row number.

The existing spreadsheet Apps Script generates IDs for direct manual edits. API writes do not reliably trigger onEdit, so the backend must generate IDs for all records it creates. Avoid having the spreadsheet script and backend both allocate IDs for the same row. During development, application-created records must use the backend ID allocator; manual sheet entries must not be made simultaneously in the same tab during a transaction test. Before production, unify allocation or make app-managed transaction tabs backend-only to eliminate cross-writer race conditions.

## Business rules

- Roles: OWNER_ADMIN, PA, FIELD_SALESMAN. Enforce access in the backend, not only in the UI.
- Mahi is the PA/data handler, not the field salesman.
- Record actual selling price per SaleItems line; no fixed sale price is required in Products.
- Sales types: Retail Sale, Retailer Sale, Wholesaler Sale, Distributor Sale.
- Retail Sale allows only papad packets of 200 g, 500 g, or 1,000 g. No loose-by-weight retail sales.
- Business sales may use configured packet or bulk/kg units where applicable.
- Full payment only. A completed/issued sale cannot be marked paid unless recorded payment total equals bill total. No credit or partial payment.
- Incentive eligibility requires delivery confirmed and full payment recorded.
- Reprinting an invoice must not create a new sale or stock movement.
- Issued sales cannot be silently overwritten. Corrections/cancellations require authorisation and an audit record.
- Salesman stock is separate from company stock. Sales transactions may affect only the salesman's assigned stock ledger unless a separately authorised company-stock transfer is implemented.
- Expected stock = opening stock + additional issues - sold - returns to company. Physical discrepancies are flagged for review, not automatically called losses.
- Expected physical cash return = opening cash + cash collections - approved cash expenses. UPI/bank collections are tracked separately.
- Only approved expenses reduce cash due back.
- GST registration and tax treatment are unconfirmed. Do not assume tax rates, GSTIN, HSN, or label the bill a tax invoice without confirmation.
- Salary/incentive values in Settings are proposals until the owner confirms them.

## Development sequence
1. Validate schema contract and product/SKU master.
2. Add an isolated sales Google Sheets adapter configured only by SALES_GOOGLE_SPREADSHEET_ID and dedicated service-account credentials.
3. Add tests using a fake/in-memory Sheets adapter before any real spreadsheet writes.
4. Implement role-scoped read/write routes and audit logging.
5. Implement sales/payment invariants and idempotency before frontend integration.
6. Build UI and PDF/Excel exports.
7. Test with a development spreadsheet, then deploy separately. Never attach this branch to production Render services during development.
