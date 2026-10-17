# Kawad Swad Sales Management System (React Application)

A React + TypeScript application, with a FastAPI backend, for sales, stock, expenses, closings, incentives, and factory production at **Kawad Swad Udhyog** (Nimar, Madhya Pradesh).

Read `FINAL_SUMMARY.md` before using it for real bills. Deployment steps are in `MANUAL_DEPLOYMENT_GUIDE.md`. The backend address comes from `VITE_API_URL`. Do not commit secrets.

## Technology Stack

- **Framework**: React 18 with TypeScript
- **Bundler & Dev Server**: Vite (running on port 3000)
- **Styling**: Native CSS styled according to the Kawad Swad brand identity (`#183b35`, `#176b52`)
- **Document Generators**:
  - `jspdf` for on-demand customer invoice PDFs matching the ReportLab layout
  - `xlsx` for Excel worksheet exports
- **State & Persistence**: In-memory store with `localStorage` persistence and realistic seed data

## Ported Modules & Business Logic

1. **Role-Based Workspaces**:
   - **OWNER**: Full administrative dashboard, team member management, product & customer catalogue, reports & exports, stock adjustments, expense approvals, and daily closing reviews.
   - **PA** (e.g. Mahi Sharma): Product/customer administration, stock movements, and expense reviews.
   - **SALESMAN** (e.g. Ramesh Verma): Mobile-first field salesman workspace with quick actions (`New sale`, `Record visit`, `Add customer`, `Submit expense`, `My stock`, `Daily closing`) and daily checklists.

2. **Product Catalogue**:
   - SKU, product name, category (Papad, Masala, Katran), variant, pack weight in grams, selling units (packet, kg).
   - Retail pack rules: retail packs cannot be sold by loose weight.
   - Immutable SKU on edits to safeguard sales and billing history.

3. **Customer & Retailer Management**:
   - Customer types: Retail, Retailer, Wholesaler, Distributor.
   - Shop name, shopkeeper/contact name, phone numbers, area/locality, city, map location, and notes.

4. **Sales, Billing & Payments**:
   - Multi-item line builder with quantity and actual unit price per line.
   - Bill-level discounts and automatic total calculation.
   - Strict full-payment capture (Cash, UPI, Bank Transfer, Other) recorded at time of bill issue.
   - Real PDF invoice generation and download.
   - Instant search through bill history.

5. **Company & Salesman Stock**:
   - Derived stock balances from the immutable stock ledger (`SalesmanStockLedger`).
   - Movement types: `COMPANY_RECEIPT`, `ISSUED`, `RETURNED`, `SOLD`, `COMPANY_ADJUSTMENT`, `SALESMAN_ADJUSTMENT`.
   - Invariant enforcement: rejects issues greater than available company stock, and returns/sales greater than salesman stock.

6. **Expenses & Approvals**:
   - Expense submission with categories (Travel, Delivery, Other, Digital).
   - Pending state prevents premature reduction of cash due back.
   - Review workflow for Owner/PA with reason logging; approved cash expenses flag `cash_reducing_expense`.

7. **Shop Visits**:
   - Outcome logging, order-taken status, next action items, and follow-up dates.

8. **Daily Cash Closing**:
   - Server/store-derived expected cash return: `Opening Cash + Cash Collections - Approved Cash Expenses`.
   - Salesman records physical cash returned; difference is computed and flagged for review.
   - Manager confirmation and correction workflow.

9. **Salary & Incentives (Stage 10)**:
   - Configurable trial period, trial per-kg rates, monthly 100 kg volume blocks, and base salary.
   - Approval and disbursement reference tracking.

10. **Reports & Exports (Stage 11)**:
    - Monthly breakdown by sales type, product, and salesman.
    - One-click `.xlsx` downloads for all core ledgers.

## Development

```bash
# Install dependencies
npm install

# Start development server on port 3000
npm run dev

# Compile and build production bundle
npm run build
```
