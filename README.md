# Kawad Swad ERP

Full-stack Enterprise Resource Planning (ERP) application for **Kawad Swad Udhyog**, covering sales & billing, field salesman van operations, finished goods & warehouse inventory, raw material procurement & dal milling, recipe-governed papad production & packaging, double-entry accounting, workforce/attendance/payroll, quality & traceability, approvals, and audit trails.

---

## Architecture & Source of Truth

| Layer | Technology | Responsibility |
|---|---|---|
| **Frontend** | React 18, TypeScript, Vite 6, Tailwind CSS 4 | Role-based workspaces, desktop & mobile field views, PDF invoice generation (`jspdf`), Excel exports (`write-excel-file`), fail-closed blocked-state UX |
| **Backend API** | FastAPI (Python 3.11+), 20 modular routers, 206 `/api/*` routes | Business logic, costing & inventory engines, double-entry accounting, JWT auth & RBAC, pre-write validation, post-write read-back verification |
| **Authoritative Business Database** | Google Sheets (Workbook) | Authoritative system of record for all business tables and immutable ledgers |
| **Write Gateway (Single-Write-Owner)** | Google Apps Script Web App (`WebAppBridge.gs`) | Sole authorized writer to Google Sheets via HMAC-signed governed write envelopes (`backend/app/apps_script_bridge.py`). Backend Google Service Account uses strictly `spreadsheets.readonly` OAuth scope. |

### Zero Mock / Zero LocalStorage Business Data Policy
- The frontend **never** stores business records in `localStorage` or falls back to seeded demo data.
- Browser storage is strictly limited to UI layout state (`ks_nav_collapsed`), remembered login username, bearer JWT token (`ks_token`), and non-production local API URL override.
- When Google Sheets or the Apps Script gateway is unavailable, unconfigured, or blocked by an unresolved schema conflict, operations **fail closed** with structured HTTP `503`/`504` error responses.

---

## Operational Modules

1. **Authentication, RBAC & Approvals** (`/api/auth`, `/api/users`, `/api/approvals`, `/api/audit`)
   - PBKDF2-SHA256 password hashing, HS256 JWT tokens, login brute-force lockout, fail-closed account active predicate (`AUTH-03`), persistent token/session revocation (`RevokedTokens` + `sessions_revoked_at`, never cached), and Maker-Checker approval workflows.
   - Roles: `OWNER` / `OWNER_ADMIN`, `PA` / `MANAGER`, `SALESMAN`, `FACTORY_WORKER`, `FREELANCER`, `AUDITOR` (strictly read-only).
2. **Sales, Billing, Customers & Shop Visits** (`/api/sales`, `/api/customers`, `/api/visits`, `/api/products`)
   - Multi-line sales creation with idempotency keys, credit limit & credit-approval CAS reservations, partial/full payment collection, sales returns, PDF invoice generation, customer ledger & aging, and shop visit tracking.
3. **Finished Goods Inventory & Van Operations** (`/api/stock`)
   - Ledger-derived warehouse and salesman van balances (`ProductionStockLedger`, `SalesmanStockLedger`), van loading passes with acceptance/discrepancy/cancellation workflows, and idempotent discrepancy review with atomic audit trail.
4. **Purchasing & Supplier Payables** (`/api/purchasing`)
   - Supplier master, purchase orders, goods receipts (GRN), supplier bills, bill/advance payments with idempotency & crash recovery, advance-to-bill reconciliation, and supplier returns.
5. **Raw Materials, Dal Milling, Production & Packaging** (`/api/production`)
   - Stage 1 raw material receiving (landed cost calculation), Stage 2 whole-dal-to-flour milling conversion with yield & loss tracking, recipe master v2 validation (papad recipes require milled flour), production batches with material issuance & Owner approval, FIFO bulk-to-packet packaging conversion, discrepancy holds, and finished-goods dispatch.
6. **Double-Entry Accounting, Expenses & Daily Closing** (`/api/accounting`, `/api/expenses`, `/api/closing`, `/api/dashboard`)
   - Balanced double-entry journal engine (`JournalHeaders`, `JournalLines`), chart of accounts, trial balance, P&L, balance sheet, automated postings for purchases, milling, packaging, sales, payments, expenses, and payroll, plus CA-policy-gated overhead/GST rules.
7. **Workforce, Attendance, Labour & Payroll** (`/api/workforce`, `/api/salary`, `/api/workspace`)
   - Employee check-in/out attendance, task assignments, freelancer projects & milestones, daily/piece-rate labour register & bulk attendance, salary structures, monthly payroll calculation with salesman volume/commission incentives, Owner approval, disbursements, and isolated salary receipts.
8. **Quality, Lot Traceability & V2 Governed Operations** (`/api/quality`, `/api/v2`)
   - Product lots, QC inspections, lot status transitions, schema compatibility & tab governance status, and CA policy registry.

---

## Local Development Setup

### Prerequisites
- **Node.js** 18+ and `npm`
- **Python** 3.11+

### 1. Environment Configuration
Copy `.env.example` to `.env` (for local development only; never commit `.env` or secrets):

```bash
cp .env.example .env
```

Key backend environment variables (see `.env.example` and `backend/app/config.py`):
- `SALES_ENV` — `development` or `production`
- `SALES_JWT_SECRET` — minimum 32-character secret (required in production)
- `SALES_CORS_ORIGINS` — comma-separated allowed frontend origins (wildcard `*` rejected in production)
- `SALES_GOOGLE_SPREADSHEET_ID` — target Google Sheets workbook ID
- `SALES_GOOGLE_SERVICE_ACCOUNT_FILE` or `SALES_GOOGLE_SERVICE_ACCOUNT_JSON` — read-only Google service account credentials
- `SALES_APPS_SCRIPT_ENABLED`, `SALES_APPS_SCRIPT_WEBAPP_URL`, `SALES_APPS_SCRIPT_SHARED_SECRET`, `SALES_APPS_SCRIPT_TIMEOUT_SECONDS` — Apps Script Single-Write-Owner gateway settings
- `SALES_LOGIN_MAX_ATTEMPTS`, `SALES_LOGIN_LOCKOUT_SECONDS` — login lockout thresholds
- `SALES_CA_POLICY_CONFIG_JSON`, `SALES_APPROVED_CORE_SCHEMA_RECONCILIATIONS_JSON` — Owner/CA governance overrides

### 2. Frontend Setup & Run
```bash
npm install
npm run dev          # Starts Vite dev server on http://localhost:3000
npm run lint         # TypeScript typecheck (tsc --noEmit)
npm run build        # Production build (dist/)
```

### 3. Backend Setup & Run
```bash
pip install -r requirements.txt
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Verification & Test Commands (Safe Local-Only Execution)

All automated tests run strictly locally with zero live Google Sheets or Apps Script network calls:

```bash
# 1. Backend Python syntax/bytecode compilation
python3 -m compileall -q backend/app backend/scripts backend/tests

# 2. Full backend test suite (all 53 test modules)
SALES_TESTING=1 SALES_ENV=development PYTHONPATH=backend \
  python3 -m unittest discover -s backend/tests -p "test_*.py" -v

# 3. End-to-end 7-stage controlled business acceptance & Trial Balance reconciliation
SALES_TESTING=1 SALES_ENV=development PYTHONPATH=backend \
  python3 backend/tests/verify_acceptance_and_reconciliation.py

# 4. Frontend typecheck, contract tests, and production build
npm run lint
npx tsx scripts/test_phase1_6_frontend_contracts.ts
npm run build
```

---

## Known External Activation Prerequisites

The local codebase is verified and fail-closed. Live production activation requires three external Owner/Ops artifacts outside this repository (detailed in `PHASE1_8_DATABASE_BLOCKERS.md` and `docs/SYSTEM_ARCHITECTURE_AND_OPERATIONS.md`):

1. **`DB-003` — Workbook & Field Dictionary Reconciliation:** Authoritative 255-tab workbook export and DBV5 field dictionary (`91/255` tabs currently catalogued; `164` unmapped tabs remain blocked).
2. **`DB-007` — Physical Row-1 Header Verification for 12 Conflicting Core Tables:** Owner-exported physical Row-1 headers to supply canonical `SALES_APPROVED_CORE_SCHEMA_RECONCILIATIONS_JSON` (all 12 conflicting tabs remain write-blocked until verified).
3. **`DB-008` — Apps Script `WebAppBridge.gs` Writer Audit & Deployment:** Provisioning and auditing the external Google Apps Script `doPost` gateway source (`SALES_APPS_SCRIPT_WEBAPP_URL` + HMAC shared secret).

---

## Key Documentation
- `docs/SYSTEM_ARCHITECTURE_AND_OPERATIONS.md` — Architecture, API, gateway contract, security, and deployment runbook
- `docs/GOOGLE_SHEETS_SETUP.md` & `docs/SALES_MANAGEMENT_SCHEMA.md` — Google Sheets workbook & schema references
- `docs/CALCULATION_REGISTER_REG03.md` — Authoritative costing, inventory, and accounting calculation rules
- `PHASE1_8_DATABASE_BLOCKERS.md` — Detailed registry of external gates (`DB-003`, `DB-007`, `DB-008`)
- `MANUAL_DEPLOYMENT_GUIDE.md` — Step-by-step hosting & deployment guide
